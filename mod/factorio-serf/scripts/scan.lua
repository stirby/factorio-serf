-- One compact snapshot of an area for the Python world model: every building (and ghost) with the fields that
-- decide whether it works, belts with their neighbours so lines can be rebuilt, inserter and drill targets,
-- resource patches, power grids as numbers. No words here: Python turns it into words.
local util = require("scripts.util")

local scan = {}

local SKIP = { ["character-corpse"] = true, ["item-entity"] = true, ["tree"] = true, ["resource"] = true,
  ["simple-entity"] = true, ["fish"] = true, ["cliff"] = true, ["decorative"] = true, ["highlight-box"] = true,
  ["item-request-proxy"] = true, ["particle-source"] = true, ["smoke-with-trigger"] = true, ["projectile"] = true,
  ["sticker"] = true, ["flying-text"] = true, ["deconstructible-tile-proxy"] = true, ["tile-ghost"] = true }
local BELTS = { ["transport-belt"] = true, ["underground-belt"] = true, ["splitter"] = true }
local GENERATORS = { "generator", "solar-panel", "electric-energy-interface", "burner-generator", "fusion-generator" }

local function r2(v) return math.floor(v * 2 + 0.5) / 2 end

-- Footprint in tiles: the entity's own tile size (rotation included), else its collision box rounded up.
local function footprint(e)
  local okW, w = pcall(function() return e.tile_width end)
  local okH, h = pcall(function() return e.tile_height end)
  if okW and okH and w and h and w > 0 and h > 0 then return w, h end
  local bb = e.bounding_box
  return math.max(1, math.ceil(bb.right_bottom.x - bb.left_top.x - 0.05)),
    math.max(1, math.ceil(bb.right_bottom.y - bb.left_top.y - 0.05))
end

-- A machine's fluid inputs: for each input box, the fluid it wants (its filter), what it holds, what the pipes
-- joined to it carry, how many boxes it's joined to and where its pipe should be. Answers "why is it starved of
-- water": nothing there, the wrong fluid in those pipes (inlets swapped), or empty pipes.
local function fluid_inputs(e)
  local okF, fb = pcall(function() return e.fluidbox end)
  if not okF or not fb or #fb == 0 then return nil end
  local out = {}
  for i = 1, #fb do
    local ok, info = pcall(function()
      local pr = fb.get_prototype(i)
      if pr and pr.object_name ~= "LuaFluidBoxPrototype" and pr[1] then pr = pr[1] end
      local kind = pr and pr.production_type
      if kind ~= "input" and kind ~= "input-output" then return nil end
      local f = fb.get_filter(i)
      local here = fb[i]
      local r = { want = f and f.name or nil, have = here and here.name or nil,
        amt = here and math.floor(here.amount) or 0, linked = #(fb.get_connections(i) or {}) }
      pcall(function()
        local seg = {}
        for name in pairs(fb.get_fluid_segment_contents(i) or {}) do seg[#seg + 1] = name end
        if #seg > 0 then r.pipes = seg end
      end)
      pcall(function()
        local pc = fb.get_pipe_connections(i)
        if pc and pc[1] and pc[1].target_position then
          r.at = util.xy(pc[1].target_position)
          -- what the pipe at the inlet holds (a filtered inlet doesn't share a network with the wrong fluid)
          for _, n in pairs(e.surface.find_entities_filtered { position = pc[1].target_position, limit = 3 }) do
            local okN, nb = pcall(function() return n.fluidbox end)
            if okN and nb then
              for k = 1, #nb do if nb[k] then r.next = nb[k].name break end end
              r.next_kind = n.type
              if r.next then break end
            end
          end
        end
      end)
      return r
    end)
    if ok and info then out[#out + 1] = info end
  end
  return #out > 0 and out or nil
end

local function contents(inv)
  local out = util.contents(inv)
  return next(out) and out or nil
end

local function unit(e) return e and e.valid and e.unit_number or nil end

local function entry(e)
  local t = e.type
  local d = { u = e.unit_number, n = e.name, t = t, x = r2(e.position.x), y = r2(e.position.y) }
  if t == "entity-ghost" then
    d.n, d.ghost = e.ghost_name, true
    d.t = e.ghost_type
    if e.supports_direction then d.d = util.DIR_NAMES[e.direction] end
    if e.ghost_type == "underground-belt" then pcall(function() d.ug = e.belt_to_ground_type end) end
    pcall(function() local r = e.get_recipe() if r then d.r = r.name end end)
    return d
  end
  if e.supports_direction then d.d = util.DIR_NAMES[e.direction] end
  local w, h = footprint(e)
  if w > 1 or h > 1 then d.w, d.h = w, h end
  local okS, st = pcall(function() return e.status end)
  if okS and st then d.s = util.STATUS_NAMES[st] end
  if t == "assembling-machine" or t == "furnace" then
    local okR, r = pcall(e.get_recipe)
    if okR and r then d.r = r.name end
    if not d.r and t == "furnace" then
      pcall(function() local pr = e.previous_recipe if pr then d.r = pr.name and pr.name.name or pr.name end end)
      if type(d.r) ~= "string" then d.r = nil end
    end
    d.inp = contents(e.get_inventory(defines.inventory.crafter_input))
    d.out = contents(e.get_output_inventory())
    if t == "assembling-machine" then d.fin = fluid_inputs(e) end
    pcall(function() d.prog = math.floor(e.crafting_progress * 100) end)
  elseif t == "container" or t == "logistic-container" or t == "infinity-container" then
    local inv = e.get_inventory(defines.inventory.chest)
    d.inv = contents(inv)
    if inv then
      d.slots = #inv
      d.free = inv.count_empty_stacks()
    end
    if t == "infinity-container" then d.infinite = true end
  elseif t == "lab" then
    d.inp = contents(e.get_inventory(defines.inventory.lab_input))
  elseif t == "boiler" then
    pcall(function() d.fluid = e.fluidbox[1] and e.fluidbox[1].amount and math.floor(e.fluidbox[1].amount) or 0 end)
  end
  if e.burner then
    local fuel = e.get_fuel_inventory()
    local f = contents(fuel)
    d.fuel = f or {}
  end
  if BELTS[t] then
    local lanes = {}
    for li = 1, (t == "splitter" and 0 or 2) do
      local okL, line = pcall(e.get_transport_line, li)
      if okL and line then
        local c = {}
        for _, it in pairs(line.get_contents()) do c[it.name] = (c[it.name] or 0) + it.count end
        if next(c) then lanes[li] = c end
      end
    end
    if next(lanes) then d.lanes = { lanes[1] or {}, lanes[2] or {} } end
    local okN, nb = pcall(function() return e.belt_neighbours end)
    if okN and nb then
      local o, i = {}, {}
      for _, x in pairs(nb.outputs or {}) do o[#o + 1] = x.unit_number end
      for _, x in pairs(nb.inputs or {}) do i[#i + 1] = x.unit_number end
      if #o > 0 then d.o = o end
      if #i > 0 then d.i = i end
    end
    if t == "underground-belt" then
      d.ug = e.belt_to_ground_type
      local okP, pair = pcall(function() return e.neighbours end)
      if okP and pair and pair.valid then d.pair = pair.unit_number end
    end
  end
  if t == "inserter" then
    d.pk = util.xy(e.pickup_position)
    d.dp = util.xy(e.drop_position)
    d.pku = unit(e.pickup_target)
    d.dpu = unit(e.drop_target)
    local okH, h = pcall(function() return e.held_stack end)
    if okH and h and h.valid_for_read then d.hold = h.name end
  end
  if t == "mining-drill" then
    if e.mining_target then d.mt = e.mining_target.name end
    d.dp = util.xy(e.drop_position)
    d.dpu = unit(e.drop_target)
    pcall(function() d.left = e.mining_target and e.mining_target.amount or nil end)
  end
  if t == "electric-pole" then
    d.net = e.electric_network_id
  elseif t == "generator" or t == "solar-panel" or t == "accumulator" or t == "burner-generator" then
    local okN, nid = pcall(function() return e.electric_network_id end)
    if okN then d.net = nid end
    if d.s == "not_plugged_in_electric_network" then d.pw = "no power" end
  elseif util.needs_power(e) then
    local okN, nid = pcall(function() return e.electric_network_id end)
    if okN then d.net = nid end
    local p = util.power(e)
    if p and p ~= "powered" then d.pw = p:match("^(%a+ ?%a*)") end
  end
  if t == "pipe" or t == "pipe-to-ground" or t == "offshore-pump" or t == "storage-tank" or t == "pump" then
    pcall(function()
      local fb = e.fluidbox[1]
      if fb then d.fl = { fb.name, math.floor(fb.amount) } end
    end)
  end
  if e.unit_number then
    local by = storage.built_by and storage.built_by[e.unit_number]
    if by then d.by = by elseif e.last_user then d.by = e.last_user.name end
  end
  return d
end

-- Numbers for one grid, from any pole on it: watts used over the last 5 s, generator capacity, and the
-- generators and their fuel.
local function grid(pole)
  local id = pole.electric_network_id
  local st = pole.electric_network_statistics
  local used = 0
  for name in pairs(st.input_counts) do
    used = used + st.get_flow_count { name = name, category = "input",
      precision_index = defines.flow_precision_index.five_seconds, count = false } * 60
  end
  local made = 0
  for name in pairs(st.output_counts) do
    made = made + st.get_flow_count { name = name, category = "output",
      precision_index = defines.flow_precision_index.five_seconds, count = false } * 60
  end
  local cap, gens, boilers, low, low_at = 0, {}, 0, 0, {}
  -- live: it can power something now (made power in the last 5 s, or has a source that would if asked: an energy
  -- interface, solar, an engine holding steam, a burning burner generator). Steam engines alone are capacity, not power.
  local live = made > 0
  local seen = {}
  for _, g in pairs(pole.surface.find_entities_filtered { force = pole.force, type = GENERATORS }) do
    if g.electric_network_id == id then
      gens[g.name] = (gens[g.name] or 0) + 1
      if not live then
        pcall(function()
          if g.type == "electric-energy-interface" then live = (g.power_production or 0) > 0
          elseif g.type == "solar-panel" then live = true
          elseif g.type == "generator" then local fb = g.fluidbox[1] live = fb ~= nil and fb.amount > 0
          elseif g.type == "burner-generator" then live = g.burner ~= nil and g.burner.currently_burning ~= nil
          end
        end)
      end
      local okP, j = pcall(function()
        if g.type == "electric-energy-interface" then return g.power_production end
        if g.type == "solar-panel" then return g.prototype.get_max_energy_production(g.quality) end
        return g.prototype.get_max_power_output(g.quality)
      end)
      if okP and j then cap = cap + j * 60 end
      if g.type == "generator" then
        for _, b in pairs(pole.surface.find_entities_filtered { force = pole.force, type = "boiler",
          position = g.position, radius = 6 }) do
          if not seen[b.unit_number] then
            seen[b.unit_number] = true
            boilers = boilers + 1
            local fuel = b.get_fuel_inventory()
            local n = fuel and fuel.get_item_count() or 0
            -- under 20 coal: a hand-fed boiler burns that in ~45 s, so "low" leaves time to get there. An inserter
            -- keeps only a few coal in it, so a fed boiler is low only when it's empty.
            local fed = false
            if n > 0 and n < 20 then
              local bb = b.bounding_box
              for _, ins in pairs(b.surface.find_entities_filtered { force = b.force, type = "inserter",
                area = { { bb.left_top.x - 1.5, bb.left_top.y - 1.5 }, { bb.right_bottom.x + 1.5, bb.right_bottom.y + 1.5 } } }) do
                if ins.drop_target == b then fed = true break end
              end
            end
            if n < 20 and not fed then
              low = low + 1
              if #low_at < 12 then low_at[#low_at + 1] = { b.position.x, b.position.y } end
            end
          end
        end
      end
    end
  end
  return { id = id, used_w = math.floor(used), made_w = math.floor(made), cap_w = math.floor(cap), gens = gens,
    boilers = boilers, boilers_low_fuel = low, boilers_low_at = #low_at > 0 and low_at or nil, live = live }
end
scan.grid = grid

-- req: center {x,y} (default the agent), radius (default 24, max 96), agent (for the default center)
function scan.area(a, req)
  local s = (a and a.char and a.char.surface) or game.surfaces.nauvis
  local c = req.center and util.pos(req.center) or (a and a.char and a.char.position) or { x = 0, y = 0 }
  local r = math.min(tonumber(req.radius) or 24, 96)
  local area = { { c.x - r, c.y - r }, { c.x + r, c.y + r } }
  local ents, res, chars, poles = {}, {}, {}, {}
  local trees, rocks = 0, 0
  local nearest_tree, nearest_rock
  for _, e in pairs(s.find_entities_filtered { area = area }) do
    local t = e.type
    if t == "resource" then
      local p = res[e.name]
      if not p then
        p = { n = 0, amount = 0, x0 = e.position.x, y0 = e.position.y, x1 = e.position.x, y1 = e.position.y }
        res[e.name] = p
      end
      p.n, p.amount = p.n + 1, p.amount + e.amount
      p.x0, p.y0 = math.min(p.x0, e.position.x), math.min(p.y0, e.position.y)
      p.x1, p.y1 = math.max(p.x1, e.position.x), math.max(p.y1, e.position.y)
    elseif t == "tree" then
      trees = trees + 1
    elseif t == "simple-entity" then
      rocks = rocks + 1
    elseif t == "character" then
      local who = storage.by_unit and storage.by_unit[e.unit_number]
      chars[#chars + 1] = { name = who or (e.player and e.player.name) or "character", agent = who and true or nil,
        x = r2(e.position.x), y = r2(e.position.y) }
    elseif not SKIP[t] and e.force.name == "neutral" then
      -- neutral buildings (scenario props, wrecks): only an obstacle, with its footprint
      local w, h = footprint(e)
      ents[#ents + 1] = { n = e.name, t = t, x = r2(e.position.x), y = r2(e.position.y), neutral = true, w = w, h = h }
    elseif not SKIP[t] and e.force.name ~= "enemy" and e.force.name ~= "neutral" then
      local okE, d = pcall(entry, e)
      if okE and d then ents[#ents + 1] = d end
      if t == "electric-pole" and e.electric_network_id and not poles[e.electric_network_id] then
        poles[e.electric_network_id] = e
      end
    end
  end
  local grids = {}
  for _, pole in pairs(poles) do
    local okG, g = pcall(grid, pole)
    if okG and g then grids[#grids + 1] = g end
  end
  local water
  pcall(function()
    local w = s.find_tiles_filtered { area = area, collision_mask = "water_tile", limit = 4000 }
    if #w > 0 then
      local best, bd
      for _, tl in pairs(w) do
        local d = (tl.position.x - c.x) ^ 2 + (tl.position.y - c.y) ^ 2
        if not bd or d < bd then best, bd = tl.position, d end
      end
      water = { tiles = #w, x = best.x + 0.5, y = best.y + 0.5 }
    end
  end)
  local blocked
  if req.tiles then
    blocked = {}
    for _, tl in pairs(s.find_tiles_filtered { area = area, collision_mask = "water_tile" }) do
      blocked[#blocked + 1] = { tl.position.x, tl.position.y }
    end
    for _, tl in pairs(s.find_tiles_filtered { area = area, name = { "out-of-map", "empty-space" } }) do
      blocked[#blocked + 1] = { tl.position.x, tl.position.y }
    end
  end
  return { tick = game.tick, center = { r2(c.x), r2(c.y) }, radius = r, ents = ents, res = res, trees = trees,
    rocks = rocks, chars = chars, grids = grids, water = water, blocked = blocked }
end

return scan
