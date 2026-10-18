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
  end
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
    position = util.xy(c.position),
    health = math.floor(c.health),
    inventory = util.contents(c.get_main_inventory()),
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

function observe.nearby(a, radius)
  local c = a.char
  radius = math.min(radius or 16, 64)
  local pos = c.position
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
function observe.find(a, args)
  if args.name == "water" or args.tile then return find_tiles(a, args) end
  local c = a.char
  local max_r = math.min(args.max_radius or 256, 1024)
  local filter = { name = args.name, type = args.type, force = args.force }
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
        out[name] = { ingredients = ing, category = r.category, time = r.energy }
      else
        out[#out + 1] = name
      end
    end
  end
  if not args.detail then table.sort(out) end
  return out
end

local function trigger_text(t)
  local trig = t.prototype.research_trigger
  if not trig then return nil end
  local what = trig.item and (type(trig.item) == "table" and trig.item.name or trig.item)
      or trig.entity or trig.tile or ""
  local n = trig.count and trig.count > 1 and (" x" .. trig.count) or ""
  return trig.type .. " " .. tostring(what) .. n
end

-- Researchable now. 2.0 has trigger techs (craft/mine/build something) as well as lab techs.
function observe.techs(a, args)
  local out = {}
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
        out[#out + 1] = d
      end
    end
  end
  table.sort(out, function(x, y) return x.name < y.name end)
  return out
end

-- Items per minute over the last minute (top N) on the agent's surface.
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

return observe
