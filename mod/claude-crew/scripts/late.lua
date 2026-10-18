-- Late-game views and planners: what a player reads off the production screen, alerts and the logistic network,
-- plus the copy/upgrade/deconstruct planners. None of these need a character in reach, the same as for a player
-- with planners and the map open.
local util = require("scripts.util")

local late = {}

local STATUS = {}
for k, v in pairs(defines.entity_status) do STATUS[v] = k end

local function surface_of(req)
  return game.surfaces[req.surface or "nauvis"] or game.surfaces.nauvis
end

local function per_min(stats, name, cat, idx)
  local ok, v = pcall(stats.get_flow_count, { name = name, category = cat, precision_index = idx, count = true })
  return ok and math.floor(v + 0.5) or 0
end

-- What an entity makes right now: recipe products for crafters, the ore for drills.
local function makes(e)
  if e.type == "mining-drill" then
    local t = e.mining_target
    if t and t.valid then
      local p = t.prototype.mineable_properties.products
      return p and p[1] and p[1].name, nil
    end
    return nil, nil
  end
  local okR, r = pcall(e.get_recipe)
  if (not okR or not r) and e.type == "furnace" then r = e.previous_recipe and e.previous_recipe.name and prototypes.recipe[e.previous_recipe.name] or nil end
  if not r then return nil, nil end
  return nil, r
end

local function site_key(p) return math.floor(p.x / 32) .. "," .. math.floor(p.y / 32) end

local function summarize(list)
  -- {status -> {n, at}}, plus sites: 32x32 areas with how many of these machines and how many work
  local by, sites = {}, {}
  for _, e in ipairs(list) do
    local st = STATUS[e.status] or "unknown"
    local b = by[st] or { n = 0, at = {} }
    b.n = b.n + 1
    if #b.at < 3 then b.at[#b.at + 1] = util.xy(e.position) end
    by[st] = b
    local k = site_key(e.position)
    local s = sites[k] or { n = 0, working = 0, x = 0, y = 0 }
    s.n, s.x, s.y = s.n + 1, s.x + e.position.x, s.y + e.position.y
    if st == "working" then s.working = s.working + 1 end
    sites[k] = s
  end
  local out = {}
  for _, s in pairs(sites) do
    out[#out + 1] = { at = { math.floor(s.x / s.n), math.floor(s.y / s.n) }, machines = s.n, working = s.working }
  end
  table.sort(out, function(p, q) return p.machines > q.machines end)
  while #out > 6 do table.remove(out) end
  return by, out
end

-- Why is <item> short? Flow per minute, every machine that makes it and every machine that uses it, by status,
-- the flow of its ingredients, and a first guess at the cause. This is the production screen plus alt-mode.
function late.diagnose(req)
  local item = req.item or "iron-plate"
  local s = surface_of(req)
  local f = game.forces.player
  local stats = f.get_item_production_statistics(s)
  local M1, M10 = defines.flow_precision_index.one_minute, defines.flow_precision_index.ten_minutes
  local out = { item = item, surface = s.name,
    made_per_min = per_min(stats, item, "input", M1), used_per_min = per_min(stats, item, "output", M1),
    made_per_min_10m = per_min(stats, item, "input", M10), used_per_min_10m = per_min(stats, item, "output", M10) }
  local producers, consumers, ingredients = {}, {}, {}
  local machines = s.find_entities_filtered { type = { "assembling-machine", "furnace", "mining-drill" }, force = f }
  for _, e in ipairs(machines) do
    local ore, r = makes(e)
    if ore == item then producers[#producers + 1] = e
    elseif r then
      for _, p in pairs(r.products) do
        if p.name == item then
          producers[#producers + 1] = e
          for _, ing in pairs(r.ingredients) do ingredients[ing.name] = true end
        end
      end
      for _, ing in pairs(r.ingredients) do
        if ing.name == item then consumers[#consumers + 1] = e end
      end
    end
  end
  -- labs and boilers eat things too
  if prototypes.item[item] then
    for _, e in ipairs(s.find_entities_filtered { type = "lab", force = f }) do
      local inv = e.get_inventory(defines.inventory.lab_input)
      if inv and string.find(item, "science%-pack") then consumers[#consumers + 1] = e end
    end
  end
  local pb, psites = summarize(producers)
  local cb, csites = summarize(consumers)
  out.producers = { total = #producers, by_status = pb, sites = psites }
  out.consumers = { total = #consumers, by_status = cb, sites = csites }
  local ing = {}
  for name in pairs(ingredients) do
    ing[name] = { made_per_min = per_min(stats, name, "input", M1), used_per_min = per_min(stats, name, "output", M1) }
  end
  out.ingredients = ing
  -- drills: what's left under them
  if #producers > 0 and producers[1].type == "mining-drill" then
    local left, low = 0, 0
    for _, d in ipairs(producers) do
      local t = d.mining_target
      if t and t.valid then
        left = left + t.amount
        if t.amount < 2000 then low = low + 1 end
      end
    end
    out.ore_under_drills = left
    out.drills_nearly_dry = low
  end
  -- first guess, like a player squinting at the status colours
  local function n(by, k) return by[k] and by[k].n or 0 end
  local starved = n(pb, "no_ingredients") + n(pb, "waiting_for_source_items") + n(pb, "no_input_fluid")
    + n(pb, "item_ingredient_shortage") + n(pb, "fluid_ingredient_shortage")
  local blocked = n(pb, "full_output") + n(pb, "waiting_for_space_in_destination")
  local nofuel, nopower = n(pb, "no_fuel"), n(pb, "no_power") + n(pb, "low_power")
  local dry = n(pb, "no_minable_resources")
  local cstarved = n(cb, "no_ingredients") + n(cb, "missing_science_packs") + n(cb, "waiting_for_source_items")
    + n(cb, "item_ingredient_shortage")
  local function first(by, keys)
    for _, k in ipairs(keys) do if by[k] and by[k].at[1] then return by[k].at[1] end end
  end
  local function gps(p) return p and ("[gps=" .. p[1] .. "," .. p[2] .. "]") or "?" end
  local hint
  if #producers == 0 then hint = "nothing makes " .. item .. " on " .. s.name .. ": build producers"
  elseif nofuel + nopower > #producers / 4 then hint = "producers lack fuel/power (" .. nofuel .. " no fuel, " .. nopower .. " power): fix energy first"
  elseif dry > #producers / 4 then hint = dry .. " drills are on exhausted ore: move them to fresh ore / open a new patch"
  elseif starved > #producers / 3 then hint = starved .. " of " .. #producers .. " producers are starved of inputs: trace the ingredients upstream (see ingredients) and add supply there"
  elseif cstarved > 0 and blocked > 0 then
    hint = "DISTRIBUTION: " .. blocked .. " producers are backed up (full output, e.g. "
      .. gps(first(pb, { "full_output", "waiting_for_space_in_destination" })) .. ") while " .. cstarved
      .. " consumers starve (e.g. " .. gps(first(cb, { "item_ingredient_shortage", "no_ingredients", "missing_science_packs", "waiting_for_source_items" }))
      .. "). The " .. item .. " exists but doesn't reach them: belt/connect the backed-up site to the starved ones (or fix a broken belt/inserter between them) before building more producers"
  elseif blocked > #producers / 3 then hint = blocked .. " producers have full output: output transport is the limit (belt/inserter/chest backed up), or demand is low"
  elseif cstarved > 0 then hint = "producers mostly work but " .. cstarved .. " consumers are starved: build MORE producers (copy a working " .. item .. " site with copy/paste) and belt them to the starved consumers"
  else hint = "no obvious shortage: compare made vs used per minute" end
  out.hint = hint
  return out
end

-- Copy an area into a blueprint string (like ctrl+C), for paste elsewhere with the blueprint op.
function late.copy(req)
  local s = surface_of(req)
  local x1, y1, x2, y2 = math.min(req.x1, req.x2), math.min(req.y1, req.y2), math.max(req.x1, req.x2), math.max(req.y1, req.y2)
  local inv = game.create_inventory(1)
  local stack = inv[1]
  stack.set_stack { name = "blueprint" }
  local mapping = stack.create_blueprint { surface = s, force = game.forces.player,
    area = { { x1, y1 }, { x2, y2 } }, always_include_tiles = false, include_entities = true, include_modules = true,
    include_trains = false, include_station_names = false }
  local count, names = 0, {}
  for _, e in pairs(mapping or {}) do
    count = count + 1
    names[e.name] = (names[e.name] or 0) + 1
  end
  if count == 0 or not stack.is_blueprint_setup() then
    inv.destroy()
    error("nothing to copy in x " .. x1 .. ".." .. x2 .. ", y " .. y1 .. ".." .. y2)
  end
  local str = stack.export_stack()
  local cost = stack.cost_to_build
  inv.destroy()
  local need = {}
  for _, c in pairs(cost or {}) do
    if type(c) == "table" and c.name then need[c.name] = (need[c.name] or 0) + (c.count or 0) end
  end
  return { string = str, entities = count, by_name = names, needs = need, size = { x2 - x1, y2 - y1 } }
end

-- Place a blueprint string as ghosts (like placing a blueprint from map view). x,y is where its centre goes.
function late.paste(req)
  local s, f = surface_of(req), game.forces.player
  local inv = game.create_inventory(1)
  local stack = inv[1]
  stack.set_stack { name = "blueprint" }
  local res = stack.import_stack(req.string or "")
  if res ~= 0 or not stack.is_blueprint or not stack.is_blueprint_setup() then
    inv.destroy()
    error("that's not a valid single-blueprint string")
  end
  local total = 0
  for _ in pairs(stack.get_blueprint_entities() or {}) do total = total + 1 end
  local ghosts = stack.build_blueprint { surface = s, force = f, position = { req.x, req.y },
    direction = util.parse_dir(req.direction), build_mode = defines.build_mode.forced, raise_built = true }
  inv.destroy()
  local need = {}
  for _, g in pairs(ghosts or {}) do
    if g.valid and g.type == "entity-ghost" then
      for _, it in pairs(g.ghost_prototype.items_to_place_this or {}) do
        need[it.name] = (need[it.name] or 0) + (it.count or 1)
      end
    end
  end
  return { placed = #(ghosts or {}), of = total, needs = need }
end

-- Upgrade / deconstruction planners over an area: robots do the work (or a character with build_ghosts/mine).
function late.order(req)
  local s, f = surface_of(req), game.forces.player
  local area = { { math.min(req.x1, req.x2), math.min(req.y1, req.y2) }, { math.max(req.x1, req.x2), math.max(req.y1, req.y2) } }
  local n, skipped = 0, 0
  if req.kind == "deconstruct" then
    local filt = { area = area, force = f }
    if req.name then filt.name = req.name end
    for _, e in ipairs(s.find_entities_filtered(filt)) do
      if e.type ~= "character" and e.minable then
        if e.order_deconstruction(f) then n = n + 1 else skipped = skipped + 1 end
      end
    end
    -- trees and rocks in the way, as a player would sweep them
    if req.trees then
      for _, e in ipairs(s.find_entities_filtered { area = area, type = { "tree", "simple-entity" } }) do
        if e.order_deconstruction(f) then n = n + 1 end
      end
    end
    return { ordered = n, skipped = skipped }
  elseif req.kind == "upgrade" then
    local to = prototypes.entity[req.to or ""]
    if not to then error("unknown entity " .. tostring(req.to)) end
    for _, e in ipairs(s.find_entities_filtered { area = area, force = f, name = req.from }) do
      local ok = pcall(e.order_upgrade, { target = to.name, force = f })
      if ok then n = n + 1 else skipped = skipped + 1 end
    end
    return { ordered = n, skipped = skipped }
  elseif req.kind == "cancel" then
    for _, e in ipairs(s.find_entities_filtered { area = area, force = f }) do
      if e.to_be_deconstructed() then e.cancel_deconstruction(f) n = n + 1 end
      if e.to_be_upgraded() then e.cancel_upgrade(f) n = n + 1 end
    end
    return { cancelled = n }
  end
  error("kind must be deconstruct, upgrade or cancel")
end

-- The logistic network(s): robots, storage, and what construction is waiting on.
function late.network(req)
  local s, f = surface_of(req), game.forces.player
  local out = {}
  for _, net in pairs((f.logistic_networks or {})[s.name] or {}) do
    local items, top = {}, {}
    local okC, contents = pcall(net.get_contents)
    for _, c in pairs(okC and contents or {}) do
      if type(c) == "table" and c.name then items[#items + 1] = { c.name, c.count } end
    end
    table.sort(items, function(p, q) return p[2] > q[2] end)
    for i = 1, math.min(#items, 25) do top[items[i][1]] = items[i][2] end
    local cells = net.cells
    local center = cells[1] and cells[1].owner and util.xy(cells[1].owner.position) or nil
    out[#out + 1] = { id = net.network_id, roboports = #cells, at = center,
      construction_robots = net.all_construction_robots, idle_construction = net.available_construction_robots,
      logistic_robots = net.all_logistic_robots, idle_logistic = net.available_logistic_robots,
      storage_items = top, requesters = #net.requesters, providers = #net.providers }
  end
  local ghosts = s.count_entities_filtered { type = "entity-ghost", force = f }
  local decon = 0
  local okD = pcall(function()
    decon = #s.find_entities_filtered { to_be_deconstructed = true }
  end)
  return { networks = out, ghosts = ghosts, marked_for_deconstruction = okD and decon or nil }
end

return late
