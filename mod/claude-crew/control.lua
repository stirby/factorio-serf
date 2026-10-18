-- Claude Crew: script-driven characters that an external orchestrator controls over RCON.
-- RCON protocol: `/crew <json>` with { op = ..., ... }; the reply is one JSON object via rcon.print.
local util = require("scripts.util")
local agents = require("scripts.agents")
local movement = require("scripts.movement")
local jobs = require("scripts.jobs")
local observe = require("scripts.observe")

local CHAT_KEEP = 300

script.on_init(agents.init)
script.on_configuration_changed(agents.init)

script.on_event(defines.events.on_tick, function()
  jobs.tick()
  if game.tick % 60 == 0 then
    agents.respawn_tick()
    movement.gc()
  end
end)

script.on_event(defines.events.on_script_path_request_finished, movement.on_path)

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
    out[#out + 1] = { name = name, alive = agents.alive(a), position = agents.alive(a) and util.xy(a.char.position) or nil,
      job = jobs.describe(a.job), queued = #a.queue }
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

remote.add_interface("claude-crew", {
  agents = function() return storage.agents end,
})
