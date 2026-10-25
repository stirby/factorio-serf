-- Agent registry: script-driven characters with a name tag, a job queue and a result outbox.
local util = require("scripts.util")
local link = require("scripts.link")

local agents = {}

local RESPAWN_TICKS = 60 * 10
local DEFAULT_COLORS = {
  { r = 0.85, g = 0.47, b = 0.34 }, -- claude orange
  { r = 0.35, g = 0.65, b = 0.95 },
  { r = 0.55, g = 0.85, b = 0.40 },
  { r = 0.90, g = 0.75, b = 0.30 },
  { r = 0.75, g = 0.50, b = 0.90 },
  { r = 0.30, g = 0.85, b = 0.80 },
}

function agents.init()
  storage.agents = storage.agents or {}
  storage.by_unit = storage.by_unit or {} -- character unit_number -> agent name
  storage.chat, storage.events = nil, nil -- before schema 3; now link.lua's feed
  link.init()
  storage.path_results = storage.path_results or {}
  storage.next_job_id = storage.next_job_id or 1
  storage.built_by = storage.built_by or {}
end

function agents.get(name)
  local a = storage.agents[name]
  if not a then error("unknown agent: " .. tostring(name)) end
  return a
end

function agents.alive(a)
  return a.char and a.char.valid
end

function agents.event(ev)
  ev.tick = game.tick
  link.push("event", ev)
end

local function draw_tag(a)
  if a.tag and a.tag.valid then a.tag.destroy() end
  a.tag = rendering.draw_text {
    text = a.name,
    surface = a.char.surface,
    target = { entity = a.char, offset = { 0, -2.6 } },
    color = a.color,
    scale = 1.1,
    alignment = "center",
    vertical_alignment = "middle",
    use_rich_text = false,
  }
  -- and on the map: a script character gets no player marker there (live test: "I can't see the serf on the map")
  for _, k in pairs { "map_dot", "map_tag" } do
    if a[k] and a[k].valid then a[k].destroy() end
  end
  a.map_dot = rendering.draw_circle {
    radius = 0.3, filled = true, surface = a.char.surface, target = a.char, color = a.color,
    render_mode = "chart", scale_with_zoom = true,
  }
  a.map_tag = rendering.draw_text {
    text = a.name, surface = a.char.surface, target = a.char, color = a.color, scale = 1.1,
    alignment = "center", vertical_alignment = "bottom", render_mode = "chart", scale_with_zoom = true,
    use_rich_text = false,
  }
end

local function default_spawn(surface)
  -- Next to the first connected player if any, else the force spawn.
  for _, p in pairs(game.connected_players) do
    if p.surface == surface and p.character then return p.position end
  end
  return game.forces.player.get_spawn_position(surface)
end

local function create_char(a, surface, near)
  local pos = surface.find_non_colliding_position("character", near, 32, 0.5) or near
  local char = surface.create_entity { name = "character", position = pos, force = "player" }
  if not char then error("could not create character") end
  char.color = a.color
  a.char = char
  a.surface = surface.name
  storage.by_unit[char.unit_number] = a.name
  draw_tag(a)
  return char
end

function agents.spawn(args)
  local name = args.name
  if not name or name == "" then error("spawn needs a name") end
  local a = storage.agents[name]
  if a and (agents.alive(a) or a.away) then
    -- an app taking over a serf a save already has (live test: a single-player save's serf kept client p1, so the
    -- server's RCON app showed "no serf connected")
    a.client = args.client or a.client
    a.owner = args.owner or a.owner
    if agents.alive(a) and not (a.map_dot and a.map_dot.valid) then draw_tag(a) end  -- from before 0.3.4
    return a  -- away: it stays away until a player types /serf join
  end  -- away: it stays away until a player types /serf join
  if not a then
    local n = 0
    for _ in pairs(storage.agents) do n = n + 1 end
    a = {
      name = name,
      color = args.color or DEFAULT_COLORS[(n % #DEFAULT_COLORS) + 1],
      queue = {},
      results = {},
    }
    storage.agents[name] = a
  end
  local surface = game.surfaces[args.surface or "nauvis"] or game.surfaces.nauvis
  local near = util.pos(args.position)
  if not near and args.near_player then
    local p = util.find_player(args.near_player)
    if p and p.connected then surface, near = p.surface, p.position end
  end
  a.client = args.client or a.client
  a.owner = args.owner or a.owner
  local fresh = not a.kit_given
  create_char(a, surface, near or default_spawn(surface))
  if fresh and args.starter_kit ~= false then
    -- Same kit freeplay gives a new player.
    for name, n in pairs { ["iron-plate"] = 8, ["wood"] = 1, ["burner-mining-drill"] = 1, ["stone-furnace"] = 1,
      ["pistol"] = 1, ["firearm-magazine"] = 10 } do
      a.char.insert { name = name, count = n }
    end
  end
  a.kit_given = true
  a.dead_until = nil
  agents.event { type = "spawned", agent = name, position = util.xy(a.char.position) }
  return a
end

-- Leaving and coming back (/serf leave, /serf join): whole stacks move to script inventories and back, so armor keeps
-- its equipment and items their quality. Main before armor on the way out (taking the armor off first would spill its
-- bonus slots), armor first on the way back. The caller cancels the agent's jobs first.
local STASH_OUT = { "character_main", "character_trash", "character_guns", "character_ammo", "character_armor" }
local STASH_BACK = { "character_armor", "character_main", "character_guns", "character_ammo", "character_trash" }

-- Whole stacks out of the character into script inventories (a.stash), and back into a new character.
local function stash_out(a, c, kinds)
  a.stash = a.stash or {}
  for _, k in ipairs(kinds) do
    local inv = c.get_inventory(defines.inventory[k])
    if inv and not inv.is_empty() then
      local box = game.create_inventory(#inv)
      for i = 1, #inv do
        if inv[i].valid_for_read then box[i].transfer_stack(inv[i]) end
      end
      a.stash[k] = box
    end
  end
end

local function stash_back(a, c)
  local surface = c.surface
  local main = c.get_inventory(defines.inventory.character_main)
  for _, k in ipairs(STASH_BACK) do
    local box = a.stash and a.stash[k]
    if box and box.valid then
      local inv = c.get_inventory(defines.inventory[k])
      for i = 1, #box do
        local s = box[i]
        if s.valid_for_read and inv and i <= #inv then inv[i].transfer_stack(s) end
        if s.valid_for_read and main then  -- that slot isn't there now: any free one
          local free = main.find_empty_stack(s.name)
          if free then free.transfer_stack(s) end
        end
        if s.valid_for_read then  -- no room: at its feet
          surface.spill_item_stack { position = c.position, stack = s, enable_looted = true }
          s.clear()
        end
      end
      box.destroy()
    end
  end
  a.stash = nil
end

local function drop_char(a)
  storage.by_unit[a.char.unit_number] = nil
  a.char.destroy()
  for _, k in pairs { "tag", "state_tag", "bubble", "map_dot", "map_tag" } do
    if a[k] and a[k].valid then a[k].destroy() end
    a[k] = nil
  end
  a.char = nil
end

function agents.leave(a)
  if a.away then return end
  if agents.alive(a) then
    local c = a.char
    pcall(function()  -- hand-crafting in progress gives its ingredients back
      while c.crafting_queue_size > 0 do
        local q = c.crafting_queue
        c.cancel_crafting { index = q[#q].index, count = q[#q].count }
      end
    end)
    a.stash = {}
    stash_out(a, c, STASH_OUT)
    a.left_from = { surface = c.surface.name, position = util.xy(c.position) }
    drop_char(a)
  end
  for _, k in pairs { "tag", "state_tag", "bubble", "map_dot", "map_tag" } do
    if a[k] and a[k].valid then a[k].destroy() end
    a[k] = nil
  end
  a.char, a.away, a.dead_until = nil, true, nil
  agents.event { type = "left", agent = a.name }
end

-- Back next to the player who called it (if they have a character), else where it left.
function agents.join(a, player)
  if not a.away and agents.alive(a) then return end
  local surface, near
  if player and player.valid and player.connected and player.character then
    surface, near = player.surface, player.position
  else
    local lf = a.left_from or {}
    surface = game.surfaces[lf.surface or a.surface or "nauvis"] or game.surfaces.nauvis
    near = util.pos(lf.position) or default_spawn(surface)
  end
  local c = create_char(a, surface, near)
  stash_back(a, c)
  a.away, a.left_from = nil, nil
  agents.event { type = "joined", agent = a.name, position = util.xy(c.position) }
end

-- The planets with a surface (someone has been there), for the planner and for hop.
function agents.planets()
  local out = {}
  for _, sf in pairs(game.surfaces) do
    if sf.planet then out[#out + 1] = sf.name end
  end
  table.sort(out)
  return out
end

-- Planet hop: to another planet's spawn, as a teammate who'd otherwise need a rocket and a platform ride. Only
-- empty-handed: main inventory, trash, cursor and hand-crafting must be empty, so nothing crosses planets that a
-- player would have to ship. Armor, guns and ammo go along (as they would on a player). can_hop says whether it may
-- (the surface, or nil and why); the caller cancels the agent's jobs between the two.
function agents.can_hop(a, planet)
  local c = a.char
  local sf = game.surfaces[planet or ""]
  if not (sf and sf.planet) then
    return nil, "no planet surface called " .. tostring(planet) .. " (planets with a surface: "
      .. table.concat(agents.planets(), ", ") .. ")"
  end
  if c.surface == sf then return nil, "already on " .. sf.name end
  local held = {}
  for _, k in ipairs { "character_main", "character_trash" } do
    local inv = c.get_inventory(defines.inventory[k])
    if inv and not inv.is_empty() then held[#held + 1] = k:gsub("character_", "") .. " inventory" end
  end
  if c.cursor_stack and c.cursor_stack.valid_for_read then held[#held + 1] = "cursor" end
  if c.crafting_queue_size > 0 then held[#held + 1] = "hand-crafting" end
  if #held > 0 then
    return nil, "can only hop empty-handed: " .. table.concat(held, ", ") .. " not empty (store it in a chest first)"
  end
  return sf
end

function agents.hop(a, sf)
  local c = a.char
  local from = { surface = c.surface.name, position = util.xy(c.position) }
  local spawn = game.forces.player.get_spawn_position(sf)
  sf.request_to_generate_chunks(spawn, 2)
  sf.force_generate_chunk_requests()
  a.stash = {}
  stash_out(a, c, { "character_armor", "character_guns", "character_ammo" })
  drop_char(a)
  local nc = create_char(a, sf, spawn)
  stash_back(a, nc)
  agents.event { type = "hopped", agent = a.name, from = from, to = sf.name, position = util.xy(nc.position) }
  return nc
end

function agents.despawn(name)
  local a = agents.get(name)
  if agents.alive(a) then
    storage.by_unit[a.char.unit_number] = nil
    a.char.destroy()
  end
  if a.tag and a.tag.valid then a.tag.destroy() end
  for _, box in pairs(a.stash or {}) do
    if box.valid then box.destroy() end
  end
  storage.agents[name] = nil
end

-- Chat line in the agent's color, plus a short speech bubble over its head.
function agents.say(a, text)
  game.print({ "", "[color=" .. string.format("%.2f,%.2f,%.2f", a.color.r, a.color.g, a.color.b) .. "]" ..
    a.name .. "[/color]: " .. text }, { sound = defines.print_sound.never, skip = defines.print_skip.never })
  if agents.alive(a) then
    if a.bubble and a.bubble.valid then a.bubble.destroy() end
    local short = text:gsub("%[[^%]]*%]", "")
    if #short > 70 then short = short:sub(1, 67) .. "..." end
    a.bubble = rendering.draw_text {
      text = short,
      surface = a.char.surface,
      target = { entity = a.char, offset = { 0, -3.75 } },
      color = { 1, 1, 1 },
      scale = 0.9,
      alignment = "center",
      vertical_alignment = "middle",
      time_to_live = 60 * 6,
    }
  end
end

function agents.on_died(entity)
  local name = storage.by_unit[entity.unit_number]
  if not name then return end
  storage.by_unit[entity.unit_number] = nil
  local a = storage.agents[name]
  if not a then return end
  a.char = nil
  a.queue = {}
  a.job = nil
  a.craft_snap = nil
  a.dead_until = game.tick + RESPAWN_TICKS
  agents.event { type = "died", agent = name, position = util.xy(entity.position) }
  game.print("[color=red]" .. name .. " died.[/color] Respawning in " .. RESPAWN_TICKS / 60 .. "s.")
end

function agents.respawn_tick()
  for _, a in pairs(storage.agents) do
    if a.dead_until and game.tick >= a.dead_until then
      local surface = game.surfaces[a.surface or "nauvis"] or game.surfaces.nauvis
      create_char(a, surface, game.forces.player.get_spawn_position(surface))
      a.dead_until = nil
      agents.event { type = "respawned", agent = a.name, position = util.xy(a.char.position) }
    end
  end
end

return agents
