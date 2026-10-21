-- Factorio Serf: AI teammates as script-driven characters, driven by an app outside the game.
-- Protocol: a JSON request { op = ..., ... } and one JSON reply { ok, data | error }, over RCON (`/crew <json>`,
-- reply via rcon.print) or localhost UDP (scripts/link.lua). Players bring in their own with `/serf add`.
local util = require("scripts.util")
local agents = require("scripts.agents")
local movement = require("scripts.movement")
local jobs = require("scripts.jobs")
local observe = require("scripts.observe")
local scan = require("scripts.scan")
local panel = require("scripts.panel")
local triggers = require("scripts.triggers")
local marks = require("scripts.marks")
local late = require("scripts.late")
local orders = require("scripts.orders")
local link = require("scripts.link")

script.on_init(agents.init)
script.on_configuration_changed(agents.init)

-- Bump when agents.init gains new storage keys; checked from storage so it stays multiplayer-deterministic.
local SCHEMA = 3

script.on_event(defines.events.on_tick, function()
  if storage.schema ~= SCHEMA then
    agents.init()
    storage.schema = SCHEMA
  end
  link.udp_tick()
  jobs.tick()
  if game.tick % 30 == 0 then panel.refresh() end
  if game.tick % 60 == 0 then
    agents.respawn_tick()
    movement.gc()
    link.gc()
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
  link.push("chat", { tick = game.tick, player = p.name, message = e.message, position = util.xy(p.position) })
end)

---------------------------------------------------------------------- API
local API = {}

local function agent_of(req) return agents.get(req.agent) end
local function live(req)
  local a = agent_of(req)
  if not agents.alive(a) then error("agent " .. a.name .. " is dead (respawning)") end
  return a
end

API.ping = function()
  return { pong = game.tick, version = script.active_mods["factorio-serf"], seed = game.surfaces.nauvis.map_gen_settings.seed }
end

-- A line from the serf app to one player (e.g. "that name is taken"). Over UDP: only to the app's own player.
API.tell = function(req, ctx)
  local p = ctx.udp and game.get_player(ctx.player_index) or util.find_player(tostring(req.player or ""))
  if p then p.print("[serf] " .. tostring(req.text or ""):sub(1, 300)) end
  return {}
end

API.spawn = function(req)
  local a = agents.spawn(req)
  return { agent = a.name, position = util.xy(a.char.position) }
end

API.despawn = function(req) agents.despawn(req.agent) return {} end

API.list = function()
  local out = {}
  for name, a in pairs(storage.agents) do
    out[#out + 1] = { name = name, alive = agents.alive(a) and true or false, position = agents.alive(a) and util.xy(a.char.position) or nil,
      job = jobs.describe(a.job), queued = #a.queue, stats = a.stats, client = link.client_of(a), owner = a.owner }
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

-- Live status from the orchestrator. Any field may be sent alone:
--   text: the agent's own status line; state: thinking | ready | limit | paused | error | offline;
--   detail: words for that state; thought: the model's latest words; task: what it's working on; model.
API.status = function(req)
  local a = agent_of(req)
  if req.text ~= nil then a.status_text = tostring(req.text):sub(1, 140) end
  if req.state ~= nil and req.state ~= a.state then a.state, a.state_since = tostring(req.state), game.tick end
  if req.detail ~= nil then a.state_detail = tostring(req.detail):sub(1, 100) end
  if req.thought ~= nil then a.thought = tostring(req.thought):sub(1, 160) end
  if req.task ~= nil then a.task_text = tostring(req.task):sub(1, 100) end
  if req.model ~= nil then a.model = tostring(req.model):sub(1, 40) end
  return {}
end

-- Look and naming for the panel: title (e.g. "otterplex's daemon") and the word for one agent.
API.brand = function(req)
  storage.brand = { title = tostring(req.title or "Serfs"):sub(1, 60), kind = tostring(req.kind or "agent"):sub(1, 30) }
  return {}
end

API.say = function(req)
  agents.say(agent_of(req), tostring(req.text or ""))
  return {}
end

API.observe = function(req)
  local a = live(req)
  local out = { self = observe.self(a), world = observe.world(a) }
  if req.nearby ~= false then out.nearby = observe.nearby(a, req.radius, req.center and util.pos(req.center)) end
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
  local labs, working, starved, missing = 0, 0, 0, {}
  local r = f.current_research
  local needs = {}
  if r then
    local okI, ing = pcall(function() return r.research_unit_ingredients end)
    for _, it in pairs(okI and ing or {}) do needs[#needs + 1] = it.name end
  end
  for _, e in pairs(s.find_entities_filtered { type = "lab", force = f }) do
    labs = labs + 1
    local okS, stt = pcall(function() return e.status end)
    if okS and stt == S.working then working = working + 1
    elseif okS and stt == S.missing_science_packs then
      starved = starved + 1
      local inv = e.get_inventory(defines.inventory.lab_input)
      for _, n in ipairs(needs) do
        if inv and inv.get_item_count(n) == 0 then missing[n] = (missing[n] or 0) + 1 end
      end
    end
  end
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
    labs_missing = missing,
    science_used = used, science_made = made,
    plates = { iron = pm("iron-plate"), copper = pm("copper-plate"), steel = pm("steel-plate"),
      circuits = pm("electronic-circuit") } }
end

API.research = function(req) return jobs.research_direct(req) end
API.diagnose = function(req) return late.diagnose(req) end
API.copy = function(req) return late.copy(req) end
API.paste = function(req) return late.paste(req) end
API.blueprint_info = function(req) return late.blueprint_info(req) end
API.order = function(req) return late.order(req) end
API.network = function(req) return late.network(req) end
API.calc = function(req) return late.calc(req) end
API.find_space = function(req) return late.find_space(req) end
API.zone = function(req) return orders.zone(req) end
API.sources = function(req) return orders.sources(req) end
API.check = function(req) return orders.check(req) end

API.self = function(req) return observe.self(live(req)) end
API.nearby = function(req) return observe.nearby(live(req), req.radius) end
-- Power for what was just built: area={x1,y1,x2,y2} (a build zone) or positions=[[x,y],...] (what an act placed).
API.power_check = function(req)
  local s = req.agent and live(req).char.surface or game.surfaces[req.surface or "nauvis"]
  local f = game.forces.player
  local list, area = {}, nil
  if req.positions then
    for _, p in ipairs(req.positions) do
      for _, e in pairs(s.find_entities_filtered { position = { p[1], p[2] }, radius = 0.5, force = f }) do list[#list + 1] = e end
    end
  else
    area = { { req.x1, req.y1 }, { req.x2, req.y2 } }
    list = s.find_entities_filtered { area = area, force = f }
  end
  return observe.power_check(s, list, area, req.ghosts)
end

API.map = function(req) return observe.map(live(req), req.radius, util.pos(req.center)) end
API.find = function(req) return observe.find(live(req), req) end
-- Where an item is stored (chests, machine outputs), nearest first; nil item = not an item name.
API.stored = function(req)
  local proto = req.item and prototypes.item[req.item]
  if not proto then return { item = false } end
  local c = live(req).char
  local r = req.radius or 400
  local src = orders.sources { items = { req.item }, x = c.position.x, y = c.position.y, radius = r, limit = 5 }
  local recipe = c.force.recipes[req.item]
  local per = recipe and recipe.enabled and recipe.products[1].name == req.item and (recipe.products[1].amount or 1)
  local okC, runs = pcall(function() return per and c.get_craftable_count(recipe) or 0 end)
  return { item = true, stored = src.sources[req.item], in_storage_total = src.totals[req.item], radius = r,
    craftable = okC and per and runs * per or 0,
    entity = proto.place_result ~= nil or prototypes.entity[req.item] ~= nil }
end
API.trace = function(req) return observe.trace(req.agent and live(req) or nil, req) end
API.world = function(req) return observe.world(req.agent and storage.agents[req.agent] or nil) end
API.recipes = function(req) return { recipes = observe.recipes(live(req), req) } end
API.techs = function(req) return { available = observe.techs(live(req), req) } end
API.production = function(req) return observe.production(live(req), req) end

-- Read-only lookups the agent app needs that would otherwise take eval (which only RCON may use):
--   items        names of every (not hidden) item prototype
--   materials    totals of every item in the force's storage chests (not endless ones), {item = n}
--   live_pole    the nearest pole on a grid that has produced power, within radius (default 300) of x,y
--   clutter      trees and rocks within radius (default 8, max 32) of x,y: {name, x, y}
--   items_near   totals of the given items in containers near x,y (radius), e.g. a belt puzzle's kit
API.query = function(req)
  local s = game.surfaces[req.surface or "nauvis"] or game.surfaces.nauvis
  local w = req.what
  if w == "items" then
    local t = {}
    for n, p in pairs(prototypes.item) do if not p.hidden then t[#t + 1] = n end end
    return { items = t }
  elseif w == "materials" then
    local t = {}
    for _, c in pairs(s.find_entities_filtered { type = { "container", "logistic-container" }, force = "player" }) do
      local inv = c.get_inventory(defines.inventory.chest)
      if inv then for _, it in pairs(inv.get_contents()) do t[it.name] = (t[it.name] or 0) + it.count end end
    end
    return { materials = t }
  elseif w == "live_pole" then
    local p = { x = tonumber(req.x) or 0, y = tonumber(req.y) or 0 }
    local best, bd
    for _, e in pairs(s.find_entities_filtered { type = "electric-pole", position = p,
      radius = math.min(tonumber(req.radius) or 300, 500), force = "player" }) do
      local st = e.electric_network_statistics
      if st and next(st.output_counts) then
        local d = (e.position.x - p.x) ^ 2 + (e.position.y - p.y) ^ 2
        if not bd or d < bd then best, bd = e, d end
      end
    end
    return { pole = best and { best.position.x, best.position.y } or nil }
  elseif w == "clutter" then
    -- trees and rocks in a square around x,y (what has to go before building there)
    local p = { x = tonumber(req.x) or 0, y = tonumber(req.y) or 0 }
    local r = math.min(tonumber(req.radius) or 8, 32)
    local out = {}
    for _, e in pairs(s.find_entities_filtered { area = { { p.x - r, p.y - r }, { p.x + r, p.y + r } },
      type = { "tree", "simple-entity" }, limit = 400 }) do
      out[#out + 1] = { e.name, e.position.x, e.position.y }
    end
    return { clutter = out }
  end
  error("unknown query " .. tostring(w))
end

-- One compact snapshot of an area (all buildings, belts with neighbours, grids as numbers) for the world model.
API.scan = function(req) return scan.area(req.agent and storage.agents[req.agent] or nil, req) end

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
      d.power = util.power(e)
      if e.type == "accumulator" and e.electric_buffer_size and e.electric_buffer_size > 0 then
        d.charge = math.floor(e.energy / e.electric_buffer_size * 100) .. "%"
      end
      if e.type == "electric-pole" then d.grid = observe.grid(e) end
      if e.supports_direction then d.dir = util.DIR_NAMES[e.direction] end
      if e.type == "inserter" then
        d.pickup, d.drop = util.xy(e.pickup_position), util.xy(e.drop_position)
        d.sides = util.inserter_sides(e)
      end
      if e.type == "underground-belt" then
        d.ug = e.belt_to_ground_type == "input" and "input (entrance)" or "output (exit)"
      end
      if e.type == "transport-belt" or e.type == "underground-belt" or e.type == "splitter" then
        local lanes = {}
        for i = 1, 2 do
          local okL, line = pcall(e.get_transport_line, i)
          if okL and line then
            local c = {}
            for _, it in pairs(line.get_contents()) do c[it.name] = (c[it.name] or 0) + it.count end
            lanes[i == 1 and "left" or "right"] = next(c) and c or "empty"
          end
        end
        d.lanes = lanes
      end
      local fb = e.fluidbox
      if fb and #fb > 0 then
        local fl = {}
        for i = 1, #fb do
          local f = fb[i]
          if f then fl[f.name] = math.floor((fl[f.name] or 0) + f.amount) end
        end
        if next(fl) then d.fluids = fl end
      end
      out[#out + 1] = d
    end
  end
  return { entities = out }
end

-- Dev/testing: chat as if a player said it (RCON only). Shows in game chat too.
API.chat = function(req)
  local name, msg = tostring(req.player or "tester"), tostring(req.message or "")
  game.print("[color=0.7,0.7,0.7]" .. name .. " (via console):[/color] " .. msg)
  link.push("chat", { tick = game.tick, player = name, message = msg, position = req.position })
  return {}
end

-- Everything new for this orchestrator since its last poll: player chat, its agents' job results and events.
-- Polling is also the heartbeat: the panel shows an agent "offline" when its orchestrator stops.
API.poll = function(req, ctx) return link.poll(ctx, req) end

-- Dev helper: run Lua in mod context (RCON only). Returns whatever the chunk returns.
API.eval = function(req)
  local fn, err = load(req.code, "crew-eval", "t", setmetatable({ storage = storage, util = util }, { __index = _G }))
  if not fn then error(err) end
  return { result = fn() }
end

-- Ops only a server operator (RCON) may use: test helpers that inject chat or run code.
local TRUSTED_ONLY = { eval = true, chat = true, brand = true, as_player = true }

-- A player's own app (UDP) drives only the agents it owns, within the server's limits.
local function guard(req, ctx)
  if TRUSTED_ONLY[req.op] then error(req.op .. " is only for the server operator (RCON)", 0) end
  if req.op == "spawn" then
    if not settings.global["factorio-serf-player-serfs"].value then error("this server doesn't allow player serfs", 0) end
    -- From a player's machine the serf is theirs. From the server's own machine (player 0: an operator's app on
    -- the server box) it may be for any player.
    local p = ctx.player_index > 0 and game.get_player(ctx.player_index)
      or util.find_player(tostring(req.owner or ""))
    if not p then error("spawn needs a player (owner)", 0) end
    local existing = storage.agents[req.name or ""]
    if existing and existing.client ~= ctx.client then error("the name " .. req.name .. " is taken", 0) end
    if not existing then
      local mine = 0
      for _, a in pairs(storage.agents) do if a.client == ctx.client then mine = mine + 1 end end
      local cap = settings.global["factorio-serf-serfs-per-player"].value
      if mine >= cap then error("you already have " .. mine .. " (the server allows " .. cap .. ")", 0) end
    end
    req.owner, req.near_player = p.name, req.near_player or p.name
    if game.is_multiplayer() then req.starter_kit = false end -- no free items on shared servers
  elseif req.agent ~= nil then
    local a = storage.agents[req.agent]
    if a and a.client ~= ctx.client then error(tostring(req.agent) .. " belongs to someone else", 0) end
  end
end

-- One request in, one JSON reply out, whatever carried it.
local function dispatch(json, ctx)
  local okk, res = pcall(function()
    local req = helpers.json_to_table(json or "{}")
    if type(req) ~= "table" then error("bad JSON") end
    local fn = API[req.op or ""]
    if not fn then error("unknown op " .. tostring(req.op)) end
    if ctx.udp then
      guard(req, ctx)
    elseif not ctx.trusted and TRUSTED_ONLY[req.op] then
      error(req.op .. " is RCON-only")
    end
    if req.op == "spawn" then req.client = ctx.client end
    return fn(req, ctx)
  end)
  if okk then return helpers.table_to_json { ok = true, data = res } end
  return helpers.table_to_json { ok = false, error = tostring(res) }
end

script.on_event(defines.events.on_udp_packet_received, function(e) link.on_udp(e, dispatch) end)

-- Tests (RCON only): run a request exactly as a player's own app would send it over UDP, minus the socket.
API.as_player = function(req)
  local pi = tonumber(req.player_index) or 1
  return helpers.json_to_table(dispatch(helpers.table_to_json(req.request or {}),
    { client = "p" .. pi, player_index = pi, udp = true }))
end

commands.add_command("crew", "Serf API (RCON/admin). Takes JSON.", function(cmd)
  if cmd.player_index then
    -- Admins can call it from the console to look at things; the reply is printed to them.
    local p = game.get_player(cmd.player_index)
    if not (p and p.admin) then return end
    p.print(dispatch(cmd.parameter, { client = "console", player_index = cmd.player_index, udp = false }))
    return
  end
  local req_client = (cmd.parameter or ""):match('"client"%s*:%s*"([%w_%-]+)"')
  rcon.print(dispatch(cmd.parameter, { client = req_client or "rcon", trusted = true }))
end)

---------------------------------------------------------------------- /serf
local SETUP = table.concat({
  "[serf] No serf app is connected for you. To bring in a serf, on your own computer:",
  "  1. Install the app and log in once: see github.com/stirby/factorio-serf (pip install, then `claude login` or an API key).",
  "  2. Start Factorio with the launch option  --enable-lua-udp 27200  (Steam: Factorio > Properties > Launch options).",
  "  3. Run  serf  and type /serf add again.",
}, "\n")

local function owned_by(p)
  local out = {}
  for name, a in pairs(storage.agents) do
    if a.owner == p.name then out[#out + 1] = name end
  end
  table.sort(out)
  return out
end

-- Gives the serf's things to its player (or drops them at the player's feet), then removes the character.
local function dismiss(name, p)
  local a = storage.agents[name]
  if agents.alive(a) then
    for _, id in pairs { defines.inventory.character_main, defines.inventory.character_guns,
      defines.inventory.character_ammo, defines.inventory.character_armor, defines.inventory.character_trash } do
      local inv = a.char.get_inventory(id)
      if inv then
        for _, it in pairs(inv.get_contents()) do
          local stack = { name = it.name, count = it.count, quality = it.quality }
          local got = (p.character and p.insert(stack)) or 0
          if got < it.count then
            stack.count = it.count - got
            p.surface.spill_item_stack { position = p.position, stack = stack, enable_looted = true }
          end
        end
      end
    end
  end
  local client = link.client_of(a)
  agents.despawn(name)
  link.push("event", { type = "removed", agent = name, by = p.name, tick = game.tick }, client)
end

-- Teaching designs: whatever blueprint or blueprint book the player holds goes into their serf's design library.
local function design_name(label, fallback)
  local n = (label or ""):lower():gsub("%[[^%]]*%]", ""):gsub("[^%w_%-]+", "-"):gsub("%-+", "-"):gsub("^%-", "")
    :gsub("%-$", ""):sub(1, 40)
  return n ~= "" and n or fallback
end

-- Collects { {name, string}, ... }; names come from labels, made unique.
local function design_list()
  local out, used = {}, {}
  return out, function(label, str, fallback)
    local n = design_name(label, fallback)
    local base, k = n, 2
    while used[n] do n, k = base .. "-" .. k, k + 1 end
    used[n] = true
    out[#out + 1] = { name = n, string = str }
  end
end

-- Every set-up blueprint in an item stack: the blueprint itself, or all of a book's (nested books too).
local function stack_designs(st, prefix, add)
  if not (st and st.valid_for_read) then return end
  if st.is_blueprint then
    if st.is_blueprint_setup() then add(st.label, st.export_stack(), prefix) end
  elseif st.is_blueprint_book then
    local inv = st.get_inventory(defines.inventory.item_main)
    local book = design_name(st.label, prefix)
    for i = 1, inv and #inv or 0 do stack_designs(inv[i], book .. "-" .. i, add) end
  end
end

-- What the player holds: a blueprint or book item, or (single player) one picked straight from the library.
local function held_designs(p, name)
  local out, add = design_list()
  local cs = p.cursor_stack
  local book
  if cs and cs.valid_for_read and (cs.is_blueprint or cs.is_blueprint_book) then
    book = cs.is_blueprint_book and (cs.label or "book") or nil
    stack_designs(cs, name or ("design-" .. game.tick), add)
  elseif p.cursor_record then
    -- Picked straight from the blueprint library. "Game blueprints" are part of the save, so every peer can read
    -- them. "My blueprints" exist only on that player's computer: reading one on a server could desync, so they're
    -- read in single player only.
    local r = p.cursor_record
    if game.is_multiplayer() and not r.valid_for_write then return out, nil, "mine" end
    if r.is_preview then return out, nil, "preview" end
    pcall(function()
      local function from_record(rec, prefix)
        if rec.type == "blueprint" then
          if not rec.is_preview and rec.is_blueprint_setup() then add(rec.label, rec.export_record(), prefix) end
        elseif rec.type == "blueprint-book" then
          local b = design_name(rec.label, prefix)
          for i, sub in pairs(rec.contents or {}) do from_record(sub, b .. "-" .. i) end
        end
      end
      book = r.type == "blueprint-book" and (r.label or "book") or nil
      from_record(r, name or ("design-" .. game.tick))
    end)
  end
  if name and #out == 1 then out[1].name = name end -- /serf learn <name> names a single blueprint
  return out, book
end

local function teach(p, name)
  local designs, book, why = held_designs(p, name)
  if why == "mine" then
    p.print("[serf] That one is in My blueprints, which only your computer has. Drag it into Game blueprints (or "
      .. "your inventory) and teach it from there.")
    return
  elseif why == "preview" then
    p.print("[serf] That blueprint is still loading; try again in a moment.")
    return
  elseif #designs == 0 then
    p.print("[serf] Hold a blueprint or a blueprint book first (from your inventory or Game blueprints), then teach it.")
    return
  end
  -- Their own app, else the server's: designs taught on a server go to the serfs that server runs.
  local client = link.client_for_player(p.index) or link.server_client()
  if not client then
    p.print(SETUP)
    return
  end
  link.push("event", { type = "learn", designs = designs, book = book, player = p.name, tick = game.tick }, client)
  p.print("[serf] Teaching " .. (book and (#designs .. " designs from " .. book) or designs[1].name) .. "...")
end

script.on_event(defines.events.on_lua_shortcut, function(e)
  if e.prototype_name == "factorio-serf-teach" then teach(game.get_player(e.player_index)) end
end)
script.on_event("factorio-serf-teach", function(e) teach(game.get_player(e.player_index)) end)

commands.add_command("serf", "Bring in an AI helper: /serf add [name], /serf remove [name], /serf learn [name], /serf list", function(cmd)
  local p = cmd.player_index and game.get_player(cmd.player_index)
  if not p then return end
  local words = {}
  for w in (cmd.parameter or ""):gmatch("%S+") do words[#words + 1] = w end
  local sub, arg = words[1] or "help", words[2]
  if sub == "add" or sub == "join" then
    if not settings.global["factorio-serf-player-serfs"].value then
      p.print("[serf] This server doesn't allow player serfs (mod setting).")
      return
    end
    if arg and not arg:match("^[%w_%-]+$") then
      p.print("[serf] Names are letters, digits, - and _.")
      return
    end
    local client = link.client_for_player(p.index)
    if not client then
      p.print(SETUP)
      return
    end
    local cap = settings.global["factorio-serf-serfs-per-player"].value
    if client == "p" .. p.index and #owned_by(p) >= cap then
      p.print("[serf] You already have " .. table.concat(owned_by(p), ", ") .. " (this server allows " .. cap .. ").")
      return
    end
    link.push("event", { type = "add", player = p.name, player_index = p.index, name = arg,
      position = util.xy(p.position), surface = p.surface.name, tick = game.tick }, client)
    p.print("[serf] Calling a serf...")
  elseif sub == "learn" then
    -- Teach your serf a design: hold a blueprint or a book (or click the Teach serf shortcut), or paste a string.
    if arg and not arg:match("^[%w_%-]+$") then
      p.print("[serf] /serf learn [name]  while holding a blueprint or book, or  /serf learn <name> <blueprint string>")
      return
    end
    if words[3] then
      local client = link.client_for_player(p.index) or link.server_client()
      if not client then
        p.print(SETUP)
        return
      end
      link.push("event", { type = "learn", designs = { { name = arg, string = words[3] } }, player = p.name,
        tick = game.tick }, client)
      p.print("[serf] Teaching " .. arg .. "...")
      return
    end
    teach(p, arg)
  elseif sub == "remove" then
    local mine = owned_by(p)
    local name = arg or mine[1]
    local a = name and storage.agents[name]
    if not a then
      p.print("[serf] " .. (arg and ("No serf called " .. arg) or "You have no serf") .. ".")
    elseif a.owner ~= p.name and not p.admin then
      p.print("[serf] " .. name .. " isn't yours.")
    else
      dismiss(name, p)
      game.print("[serf] " .. name .. " left (dismissed by " .. p.name .. ").")
    end
  elseif sub == "list" then
    local lines = {}
    for name, a in pairs(storage.agents) do
      lines[#lines + 1] = "  " .. name .. (a.owner and (" (with " .. a.owner .. ")") or "")
        .. (link.online(link.client_of(a)) and "" or ", offline")
    end
    table.sort(lines)
    p.print(#lines > 0 and ("[serf] In this world:\n" .. table.concat(lines, "\n")) or "[serf] No serfs in this world yet.")
  else
    p.print("[serf] /serf add [name]: bring in a helper (runs on your computer with your Claude login).\n"
      .. "  /serf learn [name]: teach it the blueprint or book you're holding (or click Teach serf in the toolbar).\n"
      .. "  /serf remove [name]: send yours away (you get its items).  /serf list: who's here.\n"
      .. "  Talk to it in chat: @serf build more iron smelting")
  end
end)

commands.add_command("crew-panel", "Show or hide the serf panel.", function(cmd)
  if cmd.player_index then panel.toggle(game.get_player(cmd.player_index)) end
end)

remote.add_interface("factorio-serf", {
  agents = function() return storage.agents end,
  -- What teaching this item stack would send (tests; other mods).
  stack_designs = function(stack, prefix)
    local out, add = design_list()
    stack_designs(stack, prefix or "design", add)
    return out
  end,
})
