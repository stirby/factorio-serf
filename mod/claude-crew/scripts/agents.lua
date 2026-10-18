-- Agent registry: script-driven characters with a name tag, a job queue and a result outbox.
local util = require("scripts.util")

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
  storage.chat = storage.chat or {}
  storage.events = storage.events or {}
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
  local list = storage.events
  list[#list + 1] = ev
  if #list > 500 then table.remove(list, 1) end
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
  if a and agents.alive(a) then return a end
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

function agents.despawn(name)
  local a = agents.get(name)
  if agents.alive(a) then
    storage.by_unit[a.char.unit_number] = nil
    a.char.destroy()
  end
  if a.tag and a.tag.valid then a.tag.destroy() end
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
      target = { entity = a.char, offset = { 0, -3.4 } },
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
