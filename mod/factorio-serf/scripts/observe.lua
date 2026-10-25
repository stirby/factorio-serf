-- What an agent can see: itself, nearby entities/resources, an ASCII map, research, players.
local util = require("scripts.util")
local agents = require("scripts.agents")
local jobs = require("scripts.jobs")

local observe = {}

local NOISY = { ["transport-belt"] = true, ["pipe"] = true, ["straight-rail"] = true, ["curved-rail-a"] = true,
  ["curved-rail-b"] = true, ["half-diagonal-rail"] = true, ["wall"] = true }
local SKIP = { ["character-corpse"] = true, ["item-entity"] = true, ["tree"] = true, ["resource"] = true,
  ["simple-entity"] = true, ["fish"] = true, ["cliff"] = true, ["decorative"] = true, ["highlight-box"] = true }

local function entity_info(e)
  local d = { n = e.name, p = util.xy(e.position) }
  if e.supports_direction and e.direction ~= 0 then d.dir = util.DIR_NAMES[e.direction] end
  local okS, st = pcall(function() return e.status end)
  if okS and st then
    local s = util.STATUS_NAMES[st]
    if s and s ~= "working" then d.status = s end
  end
  if e.type == "assembling-machine" or e.type == "furnace" then
    local okR, r = pcall(e.get_recipe)
    if okR and r then d.recipe = r.name end
  end
  if e.burner then
    local fuel = util.contents(e.get_fuel_inventory())
    d.fuel = next(fuel) and fuel or "none"
  end
  if e.type == "container" or e.type == "logistic-container" or e.type == "furnace"
      or e.type == "assembling-machine" or e.type == "lab" then
    local out = util.contents(e.get_output_inventory())
    if next(out) then d.out = out end
  end
  if e.type == "furnace" or e.type == "assembling-machine" then
    local src = util.contents(e.get_inventory(defines.inventory.crafter_input))
    if next(src) then d.input = src end
  end
  if e.type == "mining-drill" then
    if e.mining_target then d.mining = e.mining_target.name end
    d.drops_at = util.xy(e.drop_position)
  end
  if e.type == "inserter" then
    d.from, d.to = util.xy(e.pickup_position), util.xy(e.drop_position)
    d.sides = util.inserter_sides(e)
  end
  if e.type == "underground-belt" then d.ug = e.belt_to_ground_type end
  local pw = util.power(e)
  if pw and pw ~= "powered" then d.power = pw end
  if e.unit_number then
    local by = storage.built_by and storage.built_by[e.unit_number]
    if by then d.by = by elseif e.last_user then d.by = e.last_user.name end
  end
  if e.type == "character" then
    local who = storage.by_unit[e.unit_number]
    d.n = who and ("agent:" .. who) or (e.player and ("player:" .. e.player.name) or "character")
  end
  return d
end

function observe.self(a)
  local c = a.char
  local q = {}
  for _, item in pairs(c.crafting_queue or {}) do q[#q + 1] = item.recipe .. " x" .. item.count end
  local armor
  local slot = c.get_inventory(defines.inventory.character_armor)
  if slot and slot[1] and slot[1].valid_for_read then
    local eq = {}
    for _, e in pairs(c.grid and c.grid.equipment or {}) do eq[e.name] = (eq[e.name] or 0) + 1 end
    armor = { name = slot[1].name, equipment = eq }
  end
  return {
    armor = armor,
    name = a.name,
    surface = c.surface.name,
    planets = agents.planets(),
    position = util.xy(c.position),
    health = math.floor(c.health),
    inventory = util.contents(c.get_main_inventory()),
    free_slots = c.get_main_inventory().count_empty_stacks(),
    crafting = #q > 0 and q or nil,
    job = jobs.describe(a.job),
    queued = #a.queue,
    reach = { build = c.build_distance, reach = c.reach_distance, mine = c.resource_reach_distance },
  }
end

-- Belt lines as groups (connected via belt_neighbours): length, ends, items, and whether they're backed up.
local BELT_TYPES = { ["transport-belt"] = true, ["underground-belt"] = true, ["splitter"] = true }

local function belt_groups(belts)
  local idx, parent = {}, {}
  for i, b in ipairs(belts) do idx[b.unit_number] = i parent[i] = i end
  local function find(i)
    while parent[i] ~= i do parent[i] = parent[parent[i]] i = parent[i] end
    return i
  end
  for i, b in ipairs(belts) do
    local okN, nb = pcall(function() return b.belt_neighbours end)
    if okN and nb then
      for _, list in pairs { nb.inputs or {}, nb.outputs or {} } do
        for _, o in pairs(list) do
          local j = idx[o.unit_number]
          if j then parent[find(i)] = find(j) end
        end
      end
    end
  end
  local groups = {}
  for i, b in ipairs(belts) do
    local r = find(i)
    local g = groups[r]
    if not g then g = { n = 0, items = {}, starts = {}, ends = {}, full = 0 } groups[r] = g end
    g.n = g.n + 1
    local okN, nb = pcall(function() return b.belt_neighbours end)
    local ins = okN and nb and nb.inputs or {}
    local outs = okN and nb and nb.outputs or {}
    local in_group_in, in_group_out = false, false
    for _, o in pairs(ins) do if idx[o.unit_number] then in_group_in = true end end
    for _, o in pairs(outs) do if idx[o.unit_number] then in_group_out = true end end
    if not in_group_in and #g.starts < 3 then g.starts[#g.starts + 1] = util.xy(b.position) end
    if not in_group_out and #g.ends < 3 then g.ends[#g.ends + 1] = util.xy(b.position) end
    local load = 0
    for li = 1, 2 do
      local okL, line = pcall(b.get_transport_line, li)
      if okL and line then
        for _, it in pairs(line.get_contents()) do
          g.items[it.name] = (g.items[it.name] or 0) + it.count
          load = load + it.count
        end
      end
    end
    if load >= 7 then g.full = g.full + 1 end -- a yellow belt tile holds 8 items when compressed
  end
  local out = {}
  for _, g in pairs(groups) do
    local state = "empty"
    local total = 0
    for _, n in pairs(g.items) do total = total + n end
    if total > 0 then state = g.full >= g.n * 0.8 and "backed up" or "flowing" end
    out[#out + 1] = { tiles = g.n, from = g.starts, to = g.ends, items = next(g.items) and g.items or nil, state = state }
  end
  table.sort(out, function(x, y) return x.tiles > y.tiles end)
  return out
end

function observe.nearby(a, radius, center)
  local c = a.char
  radius = math.min(radius or 16, 64)
  local pos = center or c.position
  local list = c.surface.find_entities_filtered { position = pos, radius = radius }
  local ents, counts, res, trees, rocks, enemies = {}, {}, {}, { n = 0 }, { n = 0 }, { n = 0 }
  local belts = {}
  local function nearest(bucket, e)
    bucket.n = bucket.n + 1
    local d = util.dist(e.position, pos)
    if not bucket.d or d < bucket.d then bucket.d, bucket.at = d, util.xy(e.position) end
  end
  for _, e in pairs(list) do
    if e ~= c then
      local t = e.type
      if t == "resource" then
        local r = res[e.name] or { tiles = 0, amount = 0, n = 0 }
        res[e.name] = r
        r.tiles, r.amount = r.tiles + 1, r.amount + e.amount
        nearest(r, e)
      elseif t == "tree" then
        nearest(trees, e)
      elseif t == "simple-entity" and e.prototype.mineable_properties.minable then
        nearest(rocks, e)
      elseif e.force.name == "enemy" then
        nearest(enemies, e)
      elseif not SKIP[t] and e.force.name ~= "neutral" then
        counts[e.name] = (counts[e.name] or 0) + 1
        if BELT_TYPES[t] then belts[#belts + 1] = e end
        if not NOISY[t] then
          ents[#ents + 1] = { e = e, d = util.dist(e.position, pos) }
        end
      end
    end
  end
  table.sort(ents, function(x, y) return x.d < y.d end)
  local out = {}
  for i = 1, math.min(#ents, 40) do out[i] = entity_info(ents[i].e) end
  local resources = {}
  for name, r in pairs(res) do resources[name] = { tiles = r.tiles, amount = r.amount, nearest = r.at } end
  local function brief(b) if b.n > 0 then return { count = b.n, nearest = b.at } end end
  return {
    radius = radius,
    entities = out,
    entity_counts = next(counts) and counts or nil,
    belt_lines = #belts > 0 and belt_groups(belts) or nil,
    more_entities = #ents > 40 and (#ents - 40) or nil,
    resources = next(resources) and resources or nil,
    trees = brief(trees),
    rocks = brief(rocks),
    enemies = brief(enemies),
  }
end

-- ASCII map centered on the agent. Uppercase letters are entities (legend), lowercase are ores.
local ORE = { ["iron-ore"] = "i", ["copper-ore"] = "c", ["stone"] = "s", ["coal"] = "k", ["uranium-ore"] = "u",
  ["crude-oil"] = "o", ["calcite"] = "a", ["tungsten-ore"] = "w", ["scrap"] = "x", ["sulfuric-acid-geyser"] = "g",
  ["lithium-brine"] = "l", ["fluorine-vent"] = "f" }

function observe.map(a, radius, center)
  local c = a.char
  radius = math.min(radius or 12, 24)
  local cx = math.floor((center and center.x) or c.position.x)
  local cy = math.floor((center and center.y) or c.position.y)
  local x0, y0, w = cx - radius, cy - radius, radius * 2 + 1
  local grid = {}
  for j = 1, w do
    local row = {}
    for i = 1, w do row[i] = "." end
    grid[j] = row
  end
  local function set(x, y, ch)
    local i, j = math.floor(x) - x0 + 1, math.floor(y) - y0 + 1
    if i >= 1 and i <= w and j >= 1 and j <= w then grid[j][i] = ch end
  end
  local area = { { x0, y0 }, { x0 + w, y0 + w } }
  local surface = c.surface
  for _, t in pairs(surface.find_tiles_filtered { area = area, collision_mask = "water_tile" }) do
    set(t.position.x, t.position.y, "~")
  end
  for _, t in pairs(surface.find_tiles_filtered { area = area, name = { "out-of-map", "empty-space" } }) do
    set(t.position.x, t.position.y, " ")
  end
  for _, e in pairs(surface.find_entities_filtered { area = area, type = "resource" }) do
    set(e.position.x, e.position.y, ORE[e.name] or "r")
  end
  local legend, letters, next_letter = {}, {}, 0
  local ALPHA = "BCDEFGHIJKLMNOPQSUVWXYZ"
  local function letter(name)
    if letters[name] then return letters[name] end
    next_letter = next_letter + 1
    local ch = next_letter <= #ALPHA and ALPHA:sub(next_letter, next_letter) or "?"
    letters[name] = ch
    legend[ch] = name
    return ch
  end
  for _, e in pairs(surface.find_entities_filtered { area = area }) do
    local t = e.type
    if t == "tree" then
      set(e.position.x, e.position.y, "T")
    elseif t == "simple-entity" then
      set(e.position.x, e.position.y, "R")
    elseif t == "cliff" then
      set(e.position.x, e.position.y, "#")
    elseif t == "character" then
      -- drawn last
    elseif t ~= "resource" and not SKIP[t] then
      local ch = e.force.name == "enemy" and "!" or letter(e.name)
      local bb = e.bounding_box
      for y = math.floor(bb.left_top.y + 0.01), math.ceil(bb.right_bottom.y - 0.01) - 1 do
        for x = math.floor(bb.left_top.x + 0.01), math.ceil(bb.right_bottom.x - 0.01) - 1 do
          set(x, y, ch)
        end
      end
      if t == "transport-belt" or t == "inserter" then
        local arrow = ({ [defines.direction.north] = "^", [defines.direction.east] = ">",
          [defines.direction.south] = "v", [defines.direction.west] = "<" })[e.direction]
        if arrow then set(e.position.x, e.position.y, arrow) end
      end
    end
  end
  for _, e in pairs(surface.find_entities_filtered { area = area, type = "character" }) do
    set(e.position.x, e.position.y, e == c and "@" or (storage.by_unit[e.unit_number] and "A" or "P"))
  end
  local rows = {}
  for j = 1, w do rows[j] = table.concat(grid[j]) end
  legend["@"] = "you"
  legend["A"] = "other agent"
  legend["P"] = "player"
  return {
    top_left = { x0, y0 },
    note = "row r, col c = tile (x0+c, y0+r), 0-based. '.' open ground, '~' water, '#' cliff, T tree, R rock, "
        .. "lowercase ore (i iron c copper s stone k coal u uranium o oil), ^>v< belt/inserter facing, ! enemy",
    legend = legend,
    rows = rows,
  }
end

-- Valid offshore-pump spots (position + direction) on the shore near some water tiles.
local function pump_spots(surface, force, tiles, want)
  local spots, seen = {}, {}
  local dirs = { "north", "east", "south", "west" }
  for _, t in ipairs(tiles) do
    for _, off in ipairs { { 0, 0 }, { 1, 0 }, { -1, 0 }, { 0, 1 }, { 0, -1 } } do
      local pos = { x = t.position.x + off[1] + 0.5, y = t.position.y + off[2] + 0.5 }
      local k = pos.x .. "," .. pos.y
      if not seen[k] then
        seen[k] = true
        for _, dn in ipairs(dirs) do
          if surface.can_place_entity { name = "offshore-pump", position = pos, direction = defines.direction[dn],
                force = force, build_check_type = defines.build_check_type.manual } then
            spots[#spots + 1] = { p = util.xy(pos), direction = dn }
            break
          end
        end
        if #spots >= want then return spots end
      end
    end
  end
  return spots
end

-- Nearest water (or any tile by name), with offshore-pump spots for water.
local function find_tiles(a, args)
  local c = a.char
  local water = args.name == "water" or args.tile == "water"
  local max_r = math.min(args.max_radius or 256, 512)
  for _, r in ipairs { 32, 96, 192, 384, 512 } do
    if r > max_r then r = max_r end
    local f = { position = c.position, radius = r, limit = 4000 }
    if water then f.collision_mask = "water_tile" else f.name = args.tile or args.name end
    local tiles = c.surface.find_tiles_filtered(f)
    if #tiles > 0 then
      table.sort(tiles, function(x, y) return util.dist(x.position, c.position) < util.dist(y.position, c.position) end)
      local out = {}
      for i = 1, math.min(#tiles, args.limit or 3) do
        local t = tiles[i]
        out[i] = { n = t.name, p = util.xy({ x = t.position.x + 0.5, y = t.position.y + 0.5 }),
          dist = math.floor(util.dist(t.position, c.position)) }
      end
      local res = { found = out, tiles_in_radius = #tiles, radius = r }
      if water then
        local near = {}
        for i = 1, math.min(#tiles, 60) do near[i] = tiles[i] end
        res.offshore_pump_spots = pump_spots(c.surface, c.force, near, 3)
      end
      return res
    end
    if r >= max_r then break end
  end
  return { found = {}, radius = max_r }
end

-- Nearest entities/resources by name or type, searched outward up to max_radius.
local entity_types
local function is_entity_type(t)
  if not entity_types then
    entity_types = {}
    for _, pr in pairs(prototypes.entity) do entity_types[pr.type] = true end
  end
  return entity_types[t] or false
end

function observe.find(a, args)
  if args.name == "water" or args.tile then return find_tiles(a, args) end
  local c = a.char
  local max_r = math.min(args.max_radius or 256, 1024)
  local filter = { name = args.name, type = args.type, force = args.force }
  -- Forgive the usual slips: an item name (rail -> straight-rail), a type given as a name (tree), a near miss.
  if args.name and not prototypes.entity[args.name] then
    local item = prototypes.item[args.name]
    if item and item.place_result then
      filter.name = item.place_result.name
    elseif is_entity_type(args.name) then
      filter.name, filter.type = nil, args.name
    else
      local close = {}
      local bits = args.name:gsub("%-", " ")
      local junk = { explosion = true, corpse = true, ["rail-remnants"] = true, ["particle-source"] = true,
        projectile = true, stream = true, sticker = true, fire = true, beam = true, ["smoke-with-trigger"] = true }
      for name, pr in pairs(prototypes.entity) do
        for w in bits:gmatch("%w+") do
          if #w > 2 and not junk[pr.type] and name:find(w, 1, true) then close[#close + 1] = name break end
        end
        if #close >= 8 then break end
      end
      error("no entity called " .. args.name .. (#close > 0 and (" (did you mean " .. table.concat(close, ", ") .. "?)") or ""), 0)
    end
  end
  if type(filter.type) == "string" and not is_entity_type(filter.type) then
    error("no entity type " .. tostring(filter.type) .. " (types look like assembling-machine, furnace, mining-drill, "
      .. "transport-belt, inserter, container, tree, resource)", 0)
  end
  for _, r in ipairs { 32, 96, 256, 512, 1024 } do
    if r > max_r then r = max_r end
    filter.position, filter.radius = c.position, r
    local list = c.surface.find_entities_filtered(filter)
    if #list > 0 then
      table.sort(list, function(x, y) return util.dist(x.position, c.position) < util.dist(y.position, c.position) end)
      local out = {}
      for i = 1, math.min(#list, args.limit or 5) do
        local e = list[i]
        local d = { n = e.name, p = util.xy(e.position), dist = math.floor(util.dist(e.position, c.position)) }
        if e.type == "resource" then d.amount = e.amount end
        out[i] = d
      end
      local res = { found = out, total_in_radius = #list, radius = r }
      if list[1].type == "resource" then
        local sum = 0
        for _, e in pairs(list) do sum = sum + e.amount end
        res.total_amount = sum
      end
      return res
    end
    if r >= max_r then break end
  end
  return { found = {}, radius = max_r }
end

function observe.world(a)
  local force = game.forces.player
  local cur = force.current_research
  local queue = {}
  for _, t in pairs(force.research_queue or {}) do queue[#queue + 1] = t.name end
  local players = {}
  for _, p in pairs(game.connected_players) do
    players[#players + 1] = { name = p.name, position = util.xy(p.position), surface = p.surface.name }
  end
  local crew = {}
  for name, o in pairs(storage.agents) do
    if name ~= (a and a.name) then
      crew[#crew + 1] = { name = name, position = agents.alive(o) and util.xy(o.char.position) or "dead",
        job = jobs.describe(o.job) }
    end
  end
  return {
    tick = game.tick,
    game_time = string.format("%dh%02dm", math.floor(game.tick / 216000), math.floor(game.tick / 3600) % 60),
    research = cur and { name = cur.name, progress = math.floor(force.research_progress * 100) .. "%" } or "none",
    research_queue = queue,
    players = players,
    crew = crew,
    cheat_mode = util.cheat(),
  }
end

-- Recipes/techs an agent can use right now (names only, filtered).
function observe.recipes(a, args)
  local out = {}
  local filter = args.filter
  for name, r in pairs(a.char.force.recipes) do
    if r.enabled and (not filter or name:find(filter, 1, true)) and not r.hidden then
      if args.detail then
        local ing = {}
        for _, i in pairs(r.ingredients) do ing[i.name] = i.amount end
        local first = r.products[1]
        out[name] = { ingredients = ing, category = r.category, time = r.energy,
          makes = first and (first.amount or first.amount_min) or 1 }
      else
        out[#out + 1] = name
      end
    end
  end
  if not args.detail then table.sort(out) end
  return out
end

local trigger_text = util.trigger_text

-- Researchable now. 2.0 has trigger techs (craft/mine/build something) as well as lab techs.
function observe.techs(a, args)
  local out = {}
  -- args.toward = a goal tech: mark the available techs that lead to it (it or any of its unresearched prerequisites)
  local leads = {}
  if args.toward and a.char.force.technologies[args.toward] then
    local function walk(t)
      if leads[t.name] or t.researched then return end
      leads[t.name] = true
      for _, pre in pairs(t.prerequisites) do walk(pre) end
    end
    walk(a.char.force.technologies[args.toward])
  end
  for name, t in pairs(a.char.force.technologies) do
    if not t.researched and t.enabled then
      local ready = true
      for _, pre in pairs(t.prerequisites) do if not pre.researched then ready = false break end end
      if ready and (not args.filter or name:find(args.filter, 1, true)) then
        local d = { name = name }
        local trig = trigger_text(t)
        if trig then
          d.unlock_by = trig
        else
          local packs = {}
          for _, ing in pairs(t.research_unit_ingredients) do packs[#packs + 1] = ing.name end
          d.packs, d.units = packs, t.research_unit_count
        end
        local unlocks = {}
        for _, eff in pairs(t.prototype.effects or {}) do
          if eff.type == "unlock-recipe" then unlocks[#unlocks + 1] = eff.recipe end
        end
        if #unlocks > 0 then d.unlocks = unlocks end
        if leads[name] then d.toward = true end
        out[#out + 1] = d
      end
    end
  end
  table.sort(out, function(x, y) return x.name < y.name end)
  return out
end

-- Items per minute over the last minute (top N) on the agent's surface.
-- The grid a pole is on, in four lines: load vs capacity over the last 5 s, generators, boiler fuel, top users.
local GENERATORS = { "generator", "solar-panel", "electric-energy-interface", "burner-generator", "fusion-generator" }
function observe.grid(pole)
  local id = pole.electric_network_id
  if not id then return nil end
  local st = pole.electric_network_statistics
  local function watts(cat, name)  -- the flow is J per tick
    return st.get_flow_count { name = name, category = cat, precision_index = defines.flow_precision_index.five_seconds,
      count = false } * 60
  end
  local used, users = 0, {}
  for name in pairs(st.input_counts) do
    local w = watts("input", name)
    if w > 0 then used, users[#users + 1] = used + w, { name, w } end
  end
  local gens, names, cap, solar = {}, {}, 0, false
  local burners, seen = {}, {}  -- what burns fuel for this grid: boilers next to its steam engines, burner generators
  for _, g in pairs(pole.surface.find_entities_filtered { force = pole.force, type = GENERATORS }) do
    if g.electric_network_id == id then
      local near = g.type == "generator" and pole.surface.find_entities_filtered {
        force = pole.force, type = "boiler", position = g.position, radius = 6 } or { g }
      for _, b in pairs(near) do
        if b.burner and not seen[b] then seen[b], burners[#burners + 1] = true, b end
      end
      if not gens[g.name] then names[#names + 1] = g.name end
      gens[g.name] = (gens[g.name] or 0) + 1
      local okP, j = pcall(function()
        if g.type == "electric-energy-interface" then return g.power_production end
        if g.type == "solar-panel" then return g.prototype.get_max_energy_production(g.quality) end
        return g.prototype.get_max_power_output(g.quality)
      end)
      if okP and j then cap = cap + j * 60 end
      solar = solar or g.type == "solar-panel"
    end
  end
  local out = {}
  if cap == 0 then
    out[1] = "grid #" .. id .. ": no generators on it (using " .. util.watts(used) .. ")"
  else
    local pct = math.floor(used / cap * 100 + 0.5)
    out[1] = "grid #" .. id .. ": using " .. util.watts(used) .. " of " .. util.watts(cap) .. " capacity (" .. pct
      .. "%, last 5 s)" .. (pct >= 97 and "; MAXED OUT: machines run slow, add generators or fuel" or "")
    local list = {}
    for _, n in ipairs(names) do list[#list + 1] = gens[n] .. " " .. n end
    out[2] = "generators: " .. table.concat(list, ", ") .. (solar and " (solar counted at full daylight)" or "")
  end
  local boilers, low, at = #burners, 0, nil
  for _, b in ipairs(burners) do
    local fuel = b.get_fuel_inventory()
    if not (fuel and fuel.get_item_count() >= 5) then low, at = low + 1, at or b.position end
  end
  if boilers > 0 then
    out[#out + 1] = low == 0 and ("fuel: all " .. boilers .. " boilers fuelled")
      or string.format("fuel: %d of %d boilers low or out (e.g. %g,%g)", low, boilers, at.x, at.y)
  end
  table.sort(users, function(x, y) return x[2] > y[2] end)
  if #users > 0 then
    local top = {}
    for i = 1, math.min(3, #users) do top[i] = users[i][1] .. " " .. util.watts(users[i][2]) end
    out[#out + 1] = "top users: " .. table.concat(top, ", ")
  end
  return out
end

-- Power for a set of placed entities (a build zone, or what an act just placed): how many need electricity and
-- don't have it. With ghosts=true, also whether any pole (built or planned) is in or next to the area.
function observe.power_check(surface, list, area, ghosts)
  local seen, n, off, low, first = {}, 0, 0, 0, nil
  for _, e in pairs(list) do
    if e.valid and not seen[e] and util.needs_power(e) then
      seen[e] = true
      n = n + 1
      local p = util.power(e)
      if p:find("^no power") then off, first = off + 1, first or e
      elseif p:find("^low power") then low = low + 1 end
    end
  end
  local out = { machines = n, unpowered = off, low = low }
  if first then
    local pole = util.grid_pole(surface, first.force, first.position)
    out.nearest_pole = pole and util.xy(pole.position) or nil
    out.example = util.xy(first.position)
  end
  if ghosts and area then
    local gm = 0
    for _, g in pairs(surface.find_entities_filtered { area = area, type = "entity-ghost" }) do
      local okE, src = pcall(function() return g.ghost_prototype.electric_energy_source_prototype end)
      if okE and src and not util.NOT_CONSUMERS[g.ghost_type] then gm = gm + 1 end
    end
    local wide = { { area[1][1] - 8, area[1][2] - 8 }, { area[2][1] + 8, area[2][2] + 8 } }
    out.ghost_machines = gm
    out.poles_near = surface.count_entities_filtered { area = wide, type = "electric-pole" }
      + surface.count_entities_filtered { area = wide, ghost_type = "electric-pole" }
  end
  return out
end

function observe.production(a, args)
  local stats = game.forces.player.get_item_production_statistics(a.char.surface)
  local prod, cons = {}, {}
  local idx = defines.flow_precision_index.one_minute
  for name, _ in pairs(stats.input_counts) do
    local n = stats.get_flow_count { name = name, category = "input", precision_index = idx, count = true }
    if n > 0 then prod[#prod + 1] = { name, math.floor(n) } end
  end
  for name, _ in pairs(stats.output_counts) do
    local n = stats.get_flow_count { name = name, category = "output", precision_index = idx, count = true }
    if n > 0 then cons[#cons + 1] = { name, math.floor(n) } end
  end
  table.sort(prod, function(x, y) return x[2] > y[2] end)
  table.sort(cons, function(x, y) return x[2] > y[2] end)
  local function top(l)
    local t = {}
    for i = 1, math.min(#l, args.limit or 20) do t[l[i][1]] = l[i][2] end
    return t
  end
  return { per_minute_produced = top(prod), per_minute_consumed = top(cons) }
end

-- Follow a belt line from one of its tiles, downstream (where the items go) or upstream (where they come from):
-- the path as straight runs and underground hops, why it ends, what's on it, and who takes from or puts onto it.
local BELTS = { "transport-belt", "underground-belt", "splitter", "linked-belt", "loader", "loader-1x1", "lane-splitter" }
local IS_BELT = {}
for _, t in ipairs(BELTS) do IS_BELT[t] = true end
local VEC = { [0] = { 0, -1 }, [4] = { 1, 0 }, [8] = { 0, 1 }, [12] = { -1, 0 } }

local function tile_key(x, y) return math.floor(x) .. "," .. math.floor(y) end

local function belt_neighbours(e)
  local ok, nb = pcall(function() return e.belt_neighbours end)
  return ok and nb or { inputs = {}, outputs = {} }
end

-- The next belt along the flow (or against it when up), and whether it was reached by an underground hop.
local function step(e, up)
  if e.type == "underground-belt" and e.belt_to_ground_type == (up and "output" or "input") then
    local pair = e.neighbours
    return pair and { pair } or {}, true
  end
  if e.type == "linked-belt" and e.linked_belt_type == (up and "output" or "input") then
    local pair = e.linked_belt_neighbour
    return pair and { pair } or {}, true
  end
  local nb = belt_neighbours(e)
  return (up and nb.inputs or nb.outputs) or {}, false
end

-- A belt that points into the side of a straight belt side-loads it; into a curve's input side, it's the curve.
local function side_loads(from, to)
  if to.direction == from.direction then return false end
  if to.type == "transport-belt" then return to.belt_shape == "straight" end
  return to.type == "underground-belt" or to.type == "splitter"
end

-- Why a downstream walk stopped at e: nothing ahead, a gap, head-on, or something that isn't a belt.
local function end_reason(e)
  local v = VEC[e.direction]
  if not v or e.type == "splitter" then return "ends at the splitter" end
  local s, x, y = e.surface, e.position.x, e.position.y
  if e.type == "underground-belt" and e.belt_to_ground_type == "input" then
    return "underground with no exit (nothing pairs with it within reach)"
  end
  local ahead
  for _, o in pairs(s.find_entities_filtered { position = { x + v[1], y + v[2] } }) do
    if IS_BELT[o.type] then ahead = o break end
    if not SKIP[o.type] and o.type ~= "character" and o.type ~= "entity-ghost" then ahead = ahead or o end
  end
  if ahead and IS_BELT[ahead.type] then
    if ahead.direction == util.opposite_dir(e.direction) then
      return "head-on into the " .. ahead.name .. " at " .. table.concat(util.xy(ahead.position), ",") .. " (they don't connect)"
    end
    return "runs into the back of the " .. ahead.name .. " at " .. table.concat(util.xy(ahead.position), ",") .. " (not connected)"
  elseif ahead then
    return "ends against the " .. ahead.name .. " at " .. table.concat(util.xy(ahead.position), ",")
      .. " (belts don't feed machines; an inserter has to)"
  end
  for k = 2, 4 do
    local b = s.find_entities_filtered { position = { x + v[1] * k, y + v[2] * k }, type = BELTS, limit = 1 }[1]
    if b then
      return "gap of " .. (k - 1) .. " tile" .. (k > 2 and "s" or "") .. ": the next " .. b.name .. " is at "
        .. table.concat(util.xy(b.position), ",") .. " facing " .. (util.DIR_NAMES[b.direction] or "?")
    end
  end
  return "ends, nothing ahead"
end

function observe.trace(a, args)
  local s = a and a.char and a.char.surface or game.surfaces[args.surface or "nauvis"]
  local p = util.pos(args.position or { args.x, args.y })
  if not (p and p.x and p.y) then error("trace needs x,y of a belt", 0) end
  local up = args.direction == "up"
  local max = math.min(args.max or 600, 3000)
  local start = s.find_entities_filtered { position = p, type = BELTS, limit = 1 }[1]
    or s.find_entities_filtered { position = p, radius = 0.8, type = BELTS, limit = 1 }[1]
  if not start then error("no belt at " .. p.x .. "," .. p.y, 0) end

  local seen, tiles, path, branches, extra_in = {}, {}, {}, {}, {}
  local stop, n = nil, 0
  local todo = { { e = start, hop = false } }
  local walks = 0
  while #todo > 0 and walks < 3 do
    walks = walks + 1
    local cur = table.remove(todo, 1)
    local e, hop = cur.e, cur.hop
    if walks > 1 then path[#path + 1] = { branch = true, p = util.xy(e.position) } end
    while e do
      if seen[e.unit_number] then
        stop = stop or ("loops back to " .. table.concat(util.xy(e.position), ","))
        break
      end
      seen[e.unit_number] = true
      n = n + 1
      path[#path + 1] = { e = e, hop = hop }
      tiles[tile_key(e.position.x, e.position.y)] = e
      if e.type == "splitter" then
        local v = VEC[(e.direction + 4) % 16]
        if v then
          tiles[tile_key(e.position.x + v[1] * 0.5, e.position.y + v[2] * 0.5)] = e
          tiles[tile_key(e.position.x - v[1] * 0.5, e.position.y - v[2] * 0.5)] = e
        end
      end
      if n >= max then
        stop = "stopped after " .. n .. " belts (max); trace again from " .. table.concat(util.xy(e.position), ",")
        break
      end
      local nexts, hopped = step(e, up)
      -- downstream: other belts feeding this one from the side; upstream: the inputs not followed
      if not up then
        for _, i in pairs(belt_neighbours(e).inputs or {}) do
          local prev = path[#path - 1]
          if not (prev and prev.e and prev.e.unit_number == i.unit_number) and side_loads(i, e) then
            extra_in[#extra_in + 1] = i
          end
        end
      end
      local nx = nexts[1]
      if up and #nexts > 1 then
        -- prefer the belt straight behind; the rest are side-loads onto this line
        for _, i in pairs(nexts) do if not side_loads(i, e) then nx = i end end
        for _, i in pairs(nexts) do if i ~= nx then extra_in[#extra_in + 1] = i end end
      elseif #nexts > 1 then
        for k = 2, #nexts do todo[#todo + 1] = { e = nexts[k], hop = false } branches[#branches + 1] = util.xy(nexts[k].position) end
      end
      if not nx then
        if up then
          stop = "starts here (nothing feeds it from behind)"
        else
          stop = end_reason(e)
        end
        path[#path].last = true
        break
      end
      if not up and not hopped and side_loads(e, nx) then
        path[#path].last = true
        stop = "side-loads onto the " .. nx.name .. " at " .. table.concat(util.xy(nx.position), ",")
          .. " (facing " .. (util.DIR_NAMES[nx.direction] or "?") .. ")"
        break
      end
      e, hop = nx, hopped
    end
    if walks == 1 then path.main_end = stop end
  end

  -- Straight runs: a new run on a direction or belt change and on every underground hop.
  local runs, run = {}, nil
  for _, st in ipairs(path) do
    if st.branch then
      run = nil
      runs[#runs + 1] = { branch = st.p }
    else
      local e = st.e
      local dir = util.DIR_NAMES[e.direction]
      if st.hop and run then
        run.to, run.under = util.xy(e.position), true
        run = nil
      elseif run and run.name == e.name and run.dir == dir and e.type ~= "underground-belt" then
        run.to, run.n = util.xy(e.position), run.n + 1
      else
        run = { name = e.name, dir = dir, from = util.xy(e.position), to = util.xy(e.position), n = 1 }
        runs[#runs + 1] = run
      end
    end
  end

  -- What's on it, and who takes from or puts onto it.
  local lanes, full = { left = {}, right = {} }, 0
  local x0, y0, x1, y1 = math.huge, math.huge, -math.huge, -math.huge
  for _, st in ipairs(path) do
    local e = st.e
    if e then
      local load = 0
      for li = 1, 2 do
        local okL, line = pcall(e.get_transport_line, li)
        if okL and line then
          local t = lanes[li == 1 and "left" or "right"]
          for _, it in pairs(line.get_contents()) do
            t[it.name] = (t[it.name] or 0) + it.count
            load = load + it.count
          end
        end
      end
      if load >= 7 then full = full + 1 end
      x0, y0 = math.min(x0, e.position.x), math.min(y0, e.position.y)
      x1, y1 = math.max(x1, e.position.x), math.max(y1, e.position.y)
    end
  end
  local takes, puts, nt, np = {}, {}, 0, 0
  local function where(e) return e.name .. "@" .. table.concat(util.xy(e.position), ",") end
  if x0 <= x1 then
    -- one query per 64-tile box keeps a long line's search small
    for bx = math.floor(x0 / 64), math.floor(x1 / 64) do
      for by = math.floor(y0 / 64), math.floor(y1 / 64) do
        local area = { { math.max(bx * 64, x0) - 3, math.max(by * 64, y0) - 3 },
          { math.min(bx * 64 + 64, x1) + 3, math.min(by * 64 + 64, y1) + 3 } }
        for _, i in pairs(s.find_entities_filtered { area = area, type = "inserter" }) do
          local pk, dp = i.pickup_position, i.drop_position
          if tiles[tile_key(pk.x, pk.y)] then
            nt = nt + 1
            if #takes < 8 then
              local tgt = i.drop_target
              takes[#takes + 1] = where(i) .. (tgt and (" -> " .. where(tgt)) or " -> ground")
            end
          elseif tiles[tile_key(dp.x, dp.y)] then
            np = np + 1
            if #puts < 8 then
              local src = i.pickup_target
              puts[#puts + 1] = where(i) .. (src and (" <- " .. where(src)) or "")
            end
          end
        end
        for _, d in pairs(s.find_entities_filtered { area = area, type = "mining-drill" }) do
          local dp = d.drop_position
          if tiles[tile_key(dp.x, dp.y)] then
            np = np + 1
            if #puts < 8 then
              puts[#puts + 1] = where(d) .. (d.mining_target and (" mining " .. d.mining_target.name) or "")
            end
          end
        end
      end
    end
  end
  for _, b in ipairs(extra_in) do
    np = np + 1
    if #puts < 8 then puts[#puts + 1] = "side-load from " .. where(b) end
  end
  local items = {}
  for lane, t in pairs(lanes) do if next(t) then items[lane] = t end end
  return {
    from = util.xy(start.position), direction = up and "up" or "down", belts = n, runs = runs,
    ["end"] = path.main_end or stop, branches = #branches > 0 and branches or nil,
    items = next(items) and items or "empty", backed_up = n > 0 and math.floor(full / n * 100 + 0.5) or 0,
    takes = takes, takes_total = nt, puts = puts, puts_total = np,
  }
end

return observe
