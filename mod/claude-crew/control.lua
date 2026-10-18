-- Claude Crew: script-driven characters that an external orchestrator controls over RCON.
-- RCON protocol: `/crew <json>` with { op = ..., ... }; the reply is one JSON object via rcon.print.
local util = require("scripts.util")
local agents = require("scripts.agents")
local movement = require("scripts.movement")
local jobs = require("scripts.jobs")
local observe = require("scripts.observe")
local panel = require("scripts.panel")
local triggers = require("scripts.triggers")
local marks = require("scripts.marks")

local CHAT_KEEP = 300

script.on_init(agents.init)
script.on_configuration_changed(agents.init)

-- Bump when agents.init gains new storage keys; checked from storage so it stays multiplayer-deterministic.
local SCHEMA = 2

script.on_event(defines.events.on_tick, function()
  if storage.schema ~= SCHEMA then
    agents.init()
    storage.schema = SCHEMA
  end
  jobs.tick()
  if game.tick % 30 == 0 then panel.refresh() end
  if game.tick % 60 == 0 then
    agents.respawn_tick()
    movement.gc()
  end
end)

script.on_event(defines.events.on_script_path_request_finished, movement.on_path)

-- Entities built by construction robots (any force), so tests can tell whether the crew uses its bots.
script.on_event(defines.events.on_robot_built_entity, function()
  storage.robot_built = (storage.robot_built or 0) + 1
end)

script.on_event(defines.events.on_research_finished, function(e)
  local t = e.research
  local unlocks = {}
  for _, eff in pairs(t.prototype.effects or {}) do
    if eff.type == "unlock-recipe" then unlocks[#unlocks + 1] = eff.recipe end
  end
  agents.event { type = "research_finished", tech = t.name, unlocks = unlocks }
  triggers.recheck(t.force)
end)

script.on_event(defines.events.on_entity_died, function(e) agents.on_died(e.entity) end,
  { { filter = "type", type = "character" } })

script.on_event(defines.events.on_console_chat, function(e)
  if not e.player_index then return end
  local p = game.get_player(e.player_index)
  if not p then return end
  local chat = storage.chat
  chat[#chat + 1] = { tick = game.tick, player = p.name, message = e.message, position = util.xy(p.position) }
  if #chat > CHAT_KEEP then table.remove(chat, 1) end
end)

---------------------------------------------------------------------- API
local API = {}

local function agent_of(req) return agents.get(req.agent) end
local function live(req)
  local a = agent_of(req)
  if not agents.alive(a) then error("agent " .. a.name .. " is dead (respawning)") end
  return a
end

API.ping = function() return { pong = game.tick, version = script.active_mods["claude-crew"] } end

API.spawn = function(req)
  local a = agents.spawn(req)
  return { agent = a.name, position = util.xy(a.char.position) }
end

API.despawn = function(req) agents.despawn(req.agent) return {} end

API.list = function()
  local out = {}
  for name, a in pairs(storage.agents) do
    out[#out + 1] = { name = name, alive = agents.alive(a) and true or false, position = agents.alive(a) and util.xy(a.char.position) or nil,
      job = jobs.describe(a.job), queued = #a.queue, stats = a.stats }
  end
  return { agents = out }
end

API.act = function(req)
  local a = live(req)
  local actions = req.actions or { req.action }
  return { job_ids = jobs.enqueue(a, actions, req.replace) }
end

API.cancel = function(req)
  jobs.cancel(agent_of(req), req.reason)
  return {}
end

API.status = function(req)
  local a = agent_of(req)
  a.status_text = tostring(req.text or ""):sub(1, 140)
  return {}
end

API.say = function(req)
  agents.say(agent_of(req), tostring(req.text or ""))
  return {}
end

API.observe = function(req)
  local a = live(req)
  local out = { self = observe.self(a), world = observe.world(a) }
  if req.nearby ~= false then out.nearby = observe.nearby(a, req.radius) end
  return out
end

API.mark = function(req)
  local a = live(req)
  local m = marks.add(a.char.surface, a.name, req)
  return { id = m.id }
end
API.unmark = function(req) marks.remove(req.id) return {} end
API.marks = function() return { marks = marks.list() } end

-- Ghosts waiting to be built: count and the items they need, near a point (or the whole map).
API.ghosts = function(req)
  local surface = game.surfaces.nauvis
  local f = { type = "entity-ghost", force = "player" }
  if req.x then f.position, f.radius = { req.x, req.y }, req.radius or 64 end
  local need, n, nearest = {}, 0, nil
  for _, g in pairs(surface.find_entities_filtered(f)) do
    n = n + 1
    for _, it in pairs(g.ghost_prototype.items_to_place_this or {}) do
      need[it.name] = (need[it.name] or 0) + (it.count or 1)
    end
    nearest = nearest or util.xy(g.position)
  end
  return { count = n, needs = need, example = nearest }
end

-- What's in the way of building in an area: entities (trees/rocks are clearable by mining) and water tiles.
API.blockers = function(req)
  local surface = game.surfaces.nauvis
  local area = { { req.x1, req.y1 }, { req.x2, req.y2 } }
  local out, clearable = {}, 0
  for _, e in pairs(surface.find_entities_filtered { area = area }) do
    local t = e.type
    if t ~= "resource" and t ~= "character" and t ~= "corpse" and t ~= "character-corpse" and t ~= "item-entity"
        and t ~= "decorative" then
      if t == "tree" or t == "simple-entity" then
        clearable = clearable + 1
      elseif #out < 12 then
        local label = t == "entity-ghost" and ("ghost of " .. e.ghost_name) or e.name
        out[#out + 1] = label .. "@" .. util.xy(e.position)[1] .. "," .. util.xy(e.position)[2]
      end
    end
  end
  local water = surface.count_tiles_filtered { area = area, collision_mask = "water_tile" }
  return { blockers = out, trees_or_rocks = clearable, water_tiles = water }
end

-- Base health, like the game's alert icons: what's out of fuel or power, and whether labs are researching.
API.alerts = function(req)
  local surface = game.surfaces.nauvis
  local force = game.forces.player
  local S = defines.entity_status
  local watch = { [S.no_fuel] = "no_fuel", [S.no_power] = "no_power", [S.low_power] = "low_power",
    [S.missing_science_packs] = "starved", [S.item_ingredient_shortage] = "starved" }
  local out, total = {}, 0
  for _, e in pairs(surface.find_entities_filtered { force = force,
    type = { "boiler", "furnace", "mining-drill", "assembling-machine", "lab", "inserter" } }) do
    total = total + 1
    local okS, st = pcall(function() return e.status end)
    local name = okS and st and watch[st]
    if name == "starved" and e.type == "assembling-machine" then
      -- only science packs: an idle mall assembler waiting for plates is normal
      local okR, r = pcall(function() return e.get_recipe() end)
      if not (okR and r and r.name:find("science%-pack")) then name = nil end
    end
    if name then
      local key = e.type .. ":" .. name
      local b = out[key]
      if not b then b = { n = 0, at = {} } out[key] = b end
      b.n = b.n + 1
      if #b.at < 3 then b.at[#b.at + 1] = util.xy(e.position) end
    end
  end
  local labs = surface.count_entities_filtered { force = force, type = "lab" }
  return { problems = out, checked = total, labs = labs, researching = force.current_research and force.current_research.name or nil }
end

-- The numbers a player keeps glancing at: research, lab utilisation, science and plate flow per minute.
API.vitals = function(req)
  local f, s = game.forces.player, game.surfaces.nauvis
  local st = f.get_item_production_statistics(s)
  local function pm(n, cat)
    local ok, v = pcall(st.get_flow_count, { name = n, category = cat or "input",
      precision_index = defines.flow_precision_index.one_minute, count = true })
    return ok and math.floor(v + 0.5) or 0
  end
  local S = defines.entity_status
  local labs, working, starved = 0, 0, 0
  for _, e in pairs(s.find_entities_filtered { type = "lab", force = f }) do
    labs = labs + 1
    local okS, stt = pcall(function() return e.status end)
    if okS and stt == S.working then working = working + 1
    elseif okS and stt == S.missing_science_packs then starved = starved + 1 end
  end
  local r = f.current_research
  local okQ, q = pcall(function() return #f.research_queue end)
  local packs = { red = "automation-science-pack", green = "logistic-science-pack", blue = "chemical-science-pack",
    purple = "production-science-pack", yellow = "utility-science-pack" }
  local used, made = {}, {}
  for k, n in pairs(packs) do
    local u, m = pm(n, "output"), pm(n, "input")
    if u > 0 then used[k] = u end
    if m > 0 then made[k] = m end
  end
  return { research = r and r.name or nil, progress = r and math.floor(f.research_progress * 100) or nil,
    queued = okQ and math.max(q - 1, 0) or nil, labs = labs, labs_working = working, labs_starved = starved,
    science_used = used, science_made = made,
    plates = { iron = pm("iron-plate"), copper = pm("copper-plate"), steel = pm("steel-plate"),
      circuits = pm("electronic-circuit") } }
end

API.research = function(req) return jobs.research_direct(req) end

API.self = function(req) return observe.self(live(req)) end
API.nearby = function(req) return observe.nearby(live(req), req.radius) end
API.map = function(req) return observe.map(live(req), req.radius, util.pos(req.center)) end
API.find = function(req) return observe.find(live(req), req) end
API.world = function(req) return observe.world(req.agent and storage.agents[req.agent] or nil) end
API.recipes = function(req) return { recipes = observe.recipes(live(req), req) } end
API.techs = function(req) return { available = observe.techs(live(req), req) } end
API.production = function(req) return observe.production(live(req), req) end

API.inspect = function(req)
  local a = live(req)
  local p = util.pos(req.position or { req.x, req.y })
  local list = a.char.surface.find_entities_filtered { position = p, radius = req.radius or 1 }
  local out = {}
  for _, e in pairs(list) do
    if e.type ~= "character" then
      local d = { n = e.name, type = e.type, p = util.xy(e.position) }
      if e.type == "resource" then d.amount = e.amount end
      local okS, st = pcall(function() return e.status end)
      if okS and st then d.status = util.STATUS_NAMES[st] end
      local invs = {}
      for i = 1, e.get_max_inventory_index() do
        local inv = e.get_inventory(i)
        if inv and #inv > 0 then
          local c = util.contents(inv)
          if next(c) then invs[#invs + 1] = c end
        end
      end
      if #invs > 0 then d.inventories = invs end
      if e.type == "assembling-machine" or e.type == "furnace" then
        local okR, r = pcall(e.get_recipe)
        if okR and r then d.recipe = r.name end
        d.progress = e.crafting_progress
      end
      if e.energy then d.energy = e.energy end
      out[#out + 1] = d
    end
  end
  return { entities = out }
end

-- Dev/testing: chat as if a player said it (RCON only). Shows in game chat too.
API.chat = function(req, from_player)
  if from_player then error("chat injection is RCON-only") end
  local name, msg = tostring(req.player or "tester"), tostring(req.message or "")
  game.print("[color=0.7,0.7,0.7]" .. name .. " (via console):[/color] " .. msg)
  local chat = storage.chat
  chat[#chat + 1] = { tick = game.tick, player = name, message = msg, position = req.position }
  return {}
end

-- Everything new since the last poll: player chat, job results per agent, agent events.
API.poll = function()
  local results = {}
  for name, a in pairs(storage.agents) do
    if #a.results > 0 then
      results[name] = a.results
      a.results = {}
    end
  end
  local out = { tick = game.tick, chat = storage.chat, results = results, events = storage.events }
  storage.chat, storage.events = {}, {}
  return out
end

-- Dev helper: run Lua in mod context (RCON only). Returns whatever the chunk returns.
API.eval = function(req, from_player)
  if from_player then error("eval is RCON-only") end
  local fn, err = load(req.code, "crew-eval", "t", setmetatable({ storage = storage, util = util }, { __index = _G }))
  if not fn then error(err) end
  return { result = fn() }
end

commands.add_command("crew", "Claude Crew API (RCON/admin). Takes JSON.", function(cmd)
  local from_player = cmd.player_index ~= nil
  if from_player then
    local p = game.get_player(cmd.player_index)
    if not (p and p.admin) then return end
  end
  local okk, res = pcall(function()
    local req = helpers.json_to_table(cmd.parameter or "{}")
    if type(req) ~= "table" then error("bad JSON") end
    local fn = API[req.op or ""]
    if not fn then error("unknown op " .. tostring(req.op)) end
    return fn(req, from_player)
  end)
  local reply
  if okk then
    reply = helpers.table_to_json { ok = true, data = res }
  else
    reply = helpers.table_to_json { ok = false, error = tostring(res) }
  end
  if from_player then
    game.get_player(cmd.player_index).print(reply)
  else
    rcon.print(reply)
  end
end)

commands.add_command("crew-panel", "Show or hide the Claude Crew panel.", function(cmd)
  if cmd.player_index then panel.toggle(game.get_player(cmd.player_index)) end
end)

remote.add_interface("claude-crew", {
  agents = function() return storage.agents end,
})
