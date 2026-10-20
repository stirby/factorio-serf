-- Transport Belt Madness (the base game's belt puzzle campaign) for the serf, on TBM's own island maps
-- (stage-tbm-01/02/03, made by tbm-gen.py --stages). Pasted into each tbm-N setup_lua by tbm-gen.py after
--   local LEVEL = <the level's table from TBM's control.lua>   local KIT = {item = count}
-- Placement is TBM's own (transportbeltmadness.lua): a steel chest of 20 items and an inserter per input, a red
-- chest seeded with 1 of its item and a fast inserter per output. TBM's player has no body and infinite items and
-- presses Start; here the serf gets a finite KIT, and the inserters start by themselves once every input's belt
-- reaches an output's pickup tile (followed belt by belt, undergrounds and side-loads included). TBM's check: an
-- output holding any other item fails the level; every output at 21 of its own item solves it. A failure (or a
-- minute with nothing arriving) stops the inserters, resets the chests and belts' items, and tells the serf in chat;
-- the inserters restart only after the belts change. A tick handler (on_nth_tick 31, unused by the mod) runs it.
local s, f, D = game.surfaces.nauvis, game.forces.player, defines.direction
s.always_day = true -- the inserters run on TBM's solar islands
local function move(p, d, n)
  local x, y = p[1] or p.x, p[2] or p.y
  if d == D.north then y = y - n elseif d == D.south then y = y + n elseif d == D.east then x = x + n
  elseif d == D.west then x = x - n end
  return { x, y }
end
local function opp(d) return (d + 8) % 16 end
local function tile(p) return { math.floor(p.x or p[1]) + 0.5, math.floor(p.y or p[2]) + 0.5 } end
local function key(p) return math.floor(p[1]) .. "," .. math.floor(p[2]) end

local n = #LEVEL.chests
local sx, sy = -math.ceil(LEVEL.level_width / 2), -math.ceil(n / 2)
local ex = math.ceil(LEVEL.level_width / 2)
local T = { pairs = {}, started = false, solved = false, resets = 0, stalls = 0, starts = 0, fails = {},
  kit = KIT, kit_given = false, area = LEVEL.area, level = LEVEL.description }
local lines = {}
for i, it in ipairs(LEVEL.chests) do
  local ip = it.input_position and it.input_position[1] or { sx, sy + it.input }
  local idir = it.input_position and it.input_position[2] or D.east
  local iip = it.input_position and move(ip, idir, 1) or { sx + 1, sy + it.input }
  local op = it.output_position and it.output_position[1] or { ex, sy + it.output }
  local odir = it.output_position and it.output_position[2] or D.west
  local oip = it.output_position and move(op, odir, 1) or { op[1] - 1, op[2] }
  local ic = s.create_entity { name = "steel-chest", position = ip, force = f }
  local ii = s.create_entity { name = "inserter", position = iip, direction = opp(idir), force = f }
  local oc = s.create_entity { name = "red-chest", position = op, force = f }
  local oi = s.create_entity { name = "fast-inserter", position = oip, direction = odir, force = f }
  ic.insert { name = it.item, count = 20 }
  oc.insert { name = it.item, count = 1 }
  for _, e in pairs { ic, ii, oc, oi } do e.minable, e.operable, e.rotatable = false, false, false end
  ii.active, oi.active = false, false
  local p = { item = it.item, ic = ic, ii = ii, oc = oc, oi = oi, drop = tile(ii.drop_position),
    pick = tile(oi.pickup_position), last = 1 }
  T.pairs[i] = p
  lines[#lines + 1] = string.format("%s: [gps=%s,%s] to [gps=%s,%s]", it.item, p.drop[1], p.drop[2], p.pick[1],
    p.pick[2])
end
f.set_spawn_position(LEVEL.starting_location or { 0, 0 }, s)
storage.tbm = T

local BELTS = { "transport-belt", "fast-transport-belt", "express-transport-belt", "underground-belt",
  "fast-underground-belt", "express-underground-belt", "splitter", "fast-splitter", "express-splitter" }
local function belt_at(p)
  return s.find_entities_filtered { area = { { p[1] - 0.4, p[2] - 0.4 }, { p[1] + 0.4, p[2] + 0.4 } }, name = BELTS,
    limit = 1 }[1]
end
local outs = {}
for i, p in ipairs(T.pairs) do outs[key(p.pick)] = i end
-- Which output's pickup tile a belt line starting at p reaches (following belts, undergrounds, side-loads), or nil.
local function reaches(p)
  local b = belt_at(p)
  if not b then return nil end
  local seen, q, i = {}, { b }, 1
  while q[i] and i < 3000 do
    local e = q[i]
    i = i + 1
    if e.valid and not seen[e.unit_number] then
      seen[e.unit_number] = true
      local o = outs[key(tile(e.position))]
      if o then return o end
      for _, nb in pairs(e.belt_neighbours.outputs or {}) do q[#q + 1] = nb end
      if e.type == "underground-belt" and e.belt_to_ground_type == "input" then
        local u = e.neighbours
        if u and u.valid then q[#q + 1] = u end
      end
    end
  end
end
-- The belts' layout, so a stopped level restarts only after the serf changed something.
local function layout()
  local t = {}
  for _, e in pairs(s.find_entities_filtered { area = T.area, name = BELTS }) do
    t[#t + 1] = e.name .. "@" .. e.position.x .. "," .. e.position.y .. ":" .. e.direction
  end
  table.sort(t)
  return table.concat(t, ";")
end
local function agent_name()
  for name, a in pairs(storage.agents or {}) do
    if a.char and a.char.valid then return name, a end
  end
end
local link = package.loaded["__factorio-serf__/scripts/link.lua"]
local function say(msg)
  game.print("[TBM] " .. msg)
  local name = agent_name()
  if link and name then
    pcall(link.push, "chat", { tick = game.tick, player = "ops", message = "@" .. name .. " " .. msg })
  end
end
local function set_running(on)
  for _, p in pairs(T.pairs) do
    if p.ii.valid then p.ii.active = on end
    if p.oi.valid then p.oi.active = on end
  end
end
-- TBM's "Back to building": the chests as they started, nothing in flight.
local function reset(why)
  set_running(false)
  for _, e in pairs(s.find_entities_filtered { area = T.area, name = BELTS }) do
    for i = 1, e.get_max_transport_line_index() do e.get_transport_line(i).clear() end
  end
  for _, e in pairs(s.find_entities_filtered { area = T.area, type = "item-entity" }) do e.destroy() end
  for _, p in pairs(T.pairs) do
    for _, ins in pairs { p.ii, p.oi } do
      if ins.valid and ins.held_stack.valid_for_read then ins.held_stack.clear() end
    end
    if p.ic.valid then
      p.ic.clear_items_inside()
      p.ic.insert { name = p.item, count = 20 }
    end
    if p.oc.valid then
      p.oc.clear_items_inside()
      p.oc.insert { name = p.item, count = 1 }
    end
    p.last = 1
  end
  T.started, T.failed_layout = false, layout()
  T.fails[#T.fails + 1] = { tick = game.tick, why = why }
  say(why .. " The inserters stopped and the level is reset. They start again once you've changed the belts and "
    .. "every input's belt reaches an output chest.")
end

local function check()
  if T.solved then return end
  if not T.kit_given then
    local _, a = agent_name()
    if a then
      for item, k in pairs(T.kit) do a.char.insert { name = item, count = k } end
      T.kit_given = true
    end
  end
  if not T.started then
    if game.tick % 62 ~= 0 then return end -- every other run: tracing all inputs is the costly part
    for _, p in ipairs(T.pairs) do
      if not reaches(p.drop) then return end
    end
    local l = layout()
    if l == T.failed_layout then return end
    T.started, T.starts, T.progress_tick = true, T.starts + 1, game.tick
    T.start_tick = T.start_tick or game.tick
    set_running(true)
    say("Every input's belt reaches an output chest, so the inserters are on. Watch the output chests fill to 21.")
    return
  end
  local full = 0
  for _, p in ipairs(T.pairs) do
    local c = p.oc.get_item_count()
    local own = p.oc.get_item_count(p.item)
    if c ~= own then
      local wrong = "something else"
      for _, it in pairs(p.oc.get_inventory(defines.inventory.chest).get_contents()) do
        if it.name ~= p.item then wrong = it.name end
      end
      T.resets = T.resets + 1
      reset(string.format("Level failed: %s reached the %s chest at [gps=%s,%s].", wrong, p.item, p.oc.position.x,
        p.oc.position.y))
      return
    end
    if c ~= p.last then p.last, T.progress_tick = c, game.tick end
    if c >= 21 then full = full + 1 end
  end
  if full == #T.pairs then
    T.solved, T.solved_tick = true, game.tick
    say(string.format("Level solved: every output chest holds 21 of its item (%d belts and undergrounds placed).",
      #s.find_entities_filtered { area = T.area, name = BELTS }))
  elseif game.tick - T.progress_tick > 3600 then
    T.stalls = T.stalls + 1
    reset(string.format("Nothing new reached an output chest for a minute (%d of %d full).", full, #T.pairs))
  end
end
script.on_nth_tick(31, function()
  local ok, err = pcall(check)
  if not ok then
    T.error = tostring(err)
    script.on_nth_tick(31, nil)
    game.print("[TBM] check stopped: " .. T.error)
  end
end)

local kit = {}
for item, k in pairs(KIT) do kit[#kit + 1] = k .. " " .. item end
table.sort(kit)
return { pairs = table.concat(lines, "; "), n = n, kit = table.concat(kit, ", "),
  gx = LEVEL.starting_location and LEVEL.starting_location[1] or 0,
  gy = LEVEL.starting_location and LEVEL.starting_location[2] or 0 }
