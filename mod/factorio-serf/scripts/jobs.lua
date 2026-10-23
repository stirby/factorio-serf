-- Per-agent job queue. Each job walks into reach first (where it needs to), then acts,
-- obeying normal player rules unless cheat mode is on.
-- A handler is { start = fn(a, job) -> result?, tick = fn(a, job) -> result? }.
-- A result is { ok = bool, msg = string, data = table? }.
local util = require("scripts.util")
local movement = require("scripts.movement")
local agents = require("scripts.agents")
local triggers = require("scripts.triggers")
local route = require("scripts.route")
local order_queries = require("scripts.orders")

local jobs = {}
local H = {}
local account_crafts -- defined with the engine below

local function ok(msg, data) return { ok = true, msg = msg, data = data } end
local function fail(msg, data) return { ok = false, msg = msg, data = data } end

local function xystr(p) local t = util.xy(p) return t[1] .. "," .. t[2] end

-- Walk until within `reach` of target position. Returns nil while walking, true on arrival,
-- or a failure result.
local function approach(a, job, target, reach)
  if util.cheat() then return true end
  local c = a.char
  if util.dist(c.position, target) <= reach then
    if job.move then movement.stop(c) job.move = nil end
    return true
  end
  job.move = job.move or { goal = util.pos(target), radius = math.max(reach - 0.8, 0.5) }
  local r = movement.tick(c, job.move)
  if r == nil then return nil end
  job.move = nil
  if r == "arrived" then
    if util.dist(c.position, target) <= reach then return true end
    return fail("could not get within reach of " .. xystr(target))
  end
  return fail(r)
end

-- Entity at a position (ignores characters, corpses, trees, resources unless asked).
local function entity_at(a, args, opts)
  opts = opts or {}
  local surface = a.char.surface
  if args.unit_number then
    local found = surface.find_entities_filtered { position = a.char.position, radius = 200 }
    for _, e in pairs(found) do
      if e.unit_number == args.unit_number then return e end
    end
    return nil
  end
  local p = util.pos(args.position or { args.x, args.y })
  if not (p and p.x and p.y) then return nil end
  -- Prefer whatever's footprint contains the point (agents often give a tile corner or center of a 2x2),
  -- then the nearest center within 1.5 tiles.
  local cands = surface.find_entities_filtered { position = p, radius = opts.radius or 1.5, name = args.name }
  local best, bd
  for _, e in pairs(cands) do
    local t = e.type
    local skip = t == "character" or t == "character-corpse" or t == "item-entity"
        or (not opts.any and (t == "resource" or t == "tree" or t == "simple-entity"))
    if not skip and e.name ~= "entity-ghost" then
      local bb = e.bounding_box
      local inside = p.x >= bb.left_top.x - 0.25 and p.x <= bb.right_bottom.x + 0.25
          and p.y >= bb.left_top.y - 0.25 and p.y <= bb.right_bottom.y + 0.25
      local d = util.dist(e.position, p) - (inside and 100 or 0)
      if not bd or d < bd then best, bd = e, d end
    end
  end
  return best
end

local function needs_reach(a, entity)
  if util.cheat() then return true end
  return a.char.can_reach_entity(entity)
end

------------------------------------------------------------------------- move
H.move = {
  start = function(a, job)
    local args = job.args
    local goal = util.pos(args.position or (args.x and { args.x, args.y }))
    if args.player then
      local p = util.find_player(args.player)
      if not (p and p.connected) then return fail("player " .. args.player .. " not online") end
      if p.surface ~= a.char.surface then return fail("player is on another surface") end
      goal = p.position
    elseif args.agent then
      local o = storage.agents[args.agent]
      if not (o and agents.alive(o)) then return fail("agent " .. args.agent .. " not found") end
      goal = o.char.position
    end
    if not goal then return fail("move needs x,y or player or agent") end
    job.move = { goal = goal, radius = args.radius or (args.player or args.agent) and 3 or 0.7 }
  end,
  tick = function(a, job)
    local r = movement.tick(a.char, job.move)
    if r == nil then return nil end
    if r == "arrived" then return ok("arrived at " .. xystr(a.char.position)) end
    return fail(r)
  end,
}

------------------------------------------------------------------------- mine
-- args: name (resource/tree/rock/entity), or x,y; count (items wanted, for resources).
local function find_mine_target(a, args)
  local c = a.char
  if args.x or args.position then
    local p = util.pos(args.position or { args.x, args.y })
    local list = c.surface.find_entities_filtered { position = p, radius = 0.8, name = args.name }
    local best, bd
    for _, e in pairs(list) do
      -- "mine x,y" picks up what's built there; the ore under it only when asked by name (a drill already gone
      -- left its ore tile, which was then hand-mined until the 60 s timeout: 91 times in an afternoon)
      if e.minable and e.type ~= "character" and e.prototype.mineable_properties.minable
          and (args.name or e.type ~= "resource") then
        local d = util.dist(e.position, p)
        if not bd or d < bd then best, bd = e, d end
      end
    end
    return best
  end
  if not args.name then return nil end
  local filter = { name = args.name }
  if args.name == "tree" then filter = { type = "tree" } end
  if args.name == "rock" then filter = { type = "simple-entity" } end
  for _, r in ipairs { 16, 48, 128, 256 } do
    filter.position, filter.radius = c.position, r
    local list = c.surface.find_entities_filtered(filter)
    local best, bd
    for _, e in pairs(list) do
      if e.minable and (e.type ~= "simple-entity" or e.prototype.mineable_properties.minable) then
        local d = util.dist(e.position, c.position)
        if not bd or d < bd then best, bd = e, d end
      end
    end
    if best then return best end
  end
  return nil
end

-- Mining a building also puts what it holds in the pocket (a furnace's ore, plates and coal; a chest's contents).
-- With no room the mining starts over and over until the caller's timeout (clear: 14 stone furnaces at 60 s each).
-- Returns false and what doesn't fit.
local function contents_fit(c, e)
  local inv = c.get_main_inventory()
  local okN, max = pcall(function() return e.get_max_inventory_index() end)
  for i = 1, (okN and max or 0) do
    local okI, ei = pcall(e.get_inventory, i)
    if okI and ei and ei.valid then
      for name, n in pairs(util.contents(ei)) do
        if not name:find("@") and inv.get_insertable_count(name) < n then return false, n .. " " .. name end
      end
    end
  end
  return true
end

local function first_product(e)
  for _, p in pairs(e.prototype.mineable_properties.products or {}) do
    if p.type == "item" then return p.name end
  end
end

-- mine x,y found nothing there: coordinates are often a tile off, so name what is close.
local function missed_at(c, args)
  local near = {}
  local at = util.pos(args.position or { args.x, args.y })
  if at and at.x then
    for _, e in pairs(c.surface.find_entities_filtered { position = at, radius = 3, limit = 20 }) do
      if e.minable and e.type ~= "character" and #near < 4 then
        near[#near + 1] = e.name .. " at " .. xystr(e.position)
      end
    end
  end
  return "nothing minable at " .. tostring(args.x) .. "," .. tostring(args.y)
    .. (#near > 0 and ("; within 3 tiles: " .. table.concat(near, ", ")) or "; nothing minable within 3 tiles either")
end

-- Resources: count = items wanted (tracked by inventory delta, hopping tiles as they run out).
-- Trees/rocks/buildings: count = entities to mine. With x,y: just that entity.
H.mine = {
  start = function(a, job)
    job.got = 0
    job.positional = job.args.x ~= nil or job.args.position ~= nil
  end,
  tick = function(a, job)
    local c, args = a.char, job.args
    local e = job.target
    if not (e and e.valid) then
      if job.target_name then
        if not job.resource then
          job.got = job.got + 1
          triggers.note(c.force, nil, "mine-entity", job.target_name, 1)
          if job.positional or job.got >= (args.count or 1) then
            return ok("mined " .. job.got .. " " .. job.target_name, { mined = job.got })
          end
        elseif job.positional then
          return ok("ore tile depleted after " .. job.got .. " " .. job.product, { mined = job.got })
        end
      elseif job.positional and job.searched then
        return fail(missed_at(c, args))
      end
      job.searched = true
      e = find_mine_target(a, args)
      job.target, job.move, job.no_progress = e, nil, 0
      if not e then
        if job.got > 0 then
          return ok("mined " .. job.got .. ", no more " .. (args.name or "") .. " nearby", { mined = job.got })
        end
        if job.positional then return fail(missed_at(c, args)) end
        return fail("nothing minable" .. (args.name and (" named " .. args.name) or "") .. " found near " .. xystr(c.position))
      end
      local mate = e.unit_number and storage.built_by[e.unit_number]
      if mate and not (storage.agents[mate] and agents.alive(storage.agents[mate])) then mate = nil end
      if mate and mate ~= a.name and not args.force_pickup then
        return fail(e.name .. " at " .. xystr(e.position) .. " was built by " .. mate
          .. ". If it's broken (leaking, unpaired, facing wrong, blocking you), fix it now with force_pickup=true and"
          .. " tell them; ask first only to tear down or redesign something that works")
      end
      if e.last_user and e.last_user.valid and not args.force_pickup then
        return fail(e.name .. " at " .. xystr(e.position) .. " was built by " .. e.last_user.name
          .. "; only pick it up if a human asked you to (then pass force_pickup=true)")
      end
      job.target_name = e.name
      job.resource = e.type == "resource"
      if job.resource and not job.product then
        job.product = first_product(e)
        job.base = c.get_item_count(job.product)
      end
    end

    local want = args.count or (job.resource and 10 or 1)
    -- Ore, trees and rocks need mining range; buildings can be picked up from full reach.
    local close = job.resource or e.type == "tree" or e.type == "simple-entity"
    local reach = close and c.resource_reach_distance or c.reach_distance
    local near = approach(a, job, e.position, reach - 0.5)
    if near == nil then return nil end
    if type(near) == "table" then return near end

    if util.cheat() then
      if job.resource then
        local n = c.insert { name = job.product, count = want - job.got }
        return ok("mined " .. (job.got + n) .. " " .. job.product, { mined = job.got + n })
      end
      c.mine_entity(e, true)
      return nil -- target now invalid; counted next tick
    end

    if job.resource then
      job.got = c.get_item_count(job.product) - job.base
      if job.got >= want then return ok("mined " .. job.got .. " " .. job.product, { mined = job.got }) end
    end
    local prod = first_product(e)
    if prod and not c.can_insert { name = prod, count = 1 } then
      return fail("inventory full", { mined = job.got })
    end
    if not job.resource and job.fit_checked ~= e then
      job.fit_checked = e
      local fits, what = contents_fit(c, e)
      if not fits then
        return fail("inventory full: no room for the " .. what .. " in the " .. e.name .. " at " .. xystr(e.position),
          { mined = job.got, inventory_full = true })
      end
    end

    c.update_selected_entity(e.position)
    if c.selected ~= e then c.selected = e end
    c.mining_state = { mining = true, position = e.position }
    local prog = c.character_mining_progress
    -- (ore, trees and rocks start over after every unit: only a building's mining starting over means trouble)
    if not job.resource and e.type ~= "tree" and e.type ~= "simple-entity" and job.last_progress
        and prog + 0.05 < job.last_progress then
      job.resets = (job.resets or 0) + 1
      if job.resets >= 3 then
        return fail("mining " .. e.name .. " at " .. xystr(e.position) .. " keeps starting over (is the inventory full?)",
          { mined = job.got })
      end
    end
    if prog == job.last_progress then
      job.no_progress = job.no_progress + 1
      if job.no_progress > 180 then
        return fail("mining is not progressing on " .. e.name .. " at " .. xystr(e.position))
      end
    else
      job.no_progress = 0
    end
    job.last_progress = prog
    return nil
  end,
  finish = function(a, job)
    if agents.alive(a) then a.char.mining_state = { mining = false } end
  end,
}

------------------------------------------------------------------------- craft
local function missing_for(a, recipe, count)
  local out = {}
  for _, ing in pairs(recipe.ingredients) do
    if ing.type == "item" then
      local have = a.char.get_item_count(ing.name)
      local need = ing.amount * count
      if have < need then out[ing.name] = need - have end
    end
  end
  return out
end

-- Hand-crafting with no room for what it makes (an intermediate gear, or the product) stops without a word and
-- the job waited forever (yellow-blk-r4: a fetch of 4 assemblers ran 41 minutes). True once the crafting queue
-- hasn't moved for 5 s; the queue stays, and finishes on its own once there's room.
local function craft_stalled(c, job)
  local key = c.crafting_queue_size .. ":" .. string.format("%.4f", c.crafting_queue_progress or 0)
  if job.craft_key ~= key then
    job.craft_key, job.craft_since = key, game.tick
    return false
  end
  return game.tick - job.craft_since > 300
end

local function stalled_msg(c, what)
  if c.get_main_inventory().count_empty_stacks() == 0 then
    return fail("my inventory is full: crafting " .. what .. " is stuck (it carries on once there's room)",
      { inventory_full = true })
  end
  return fail("crafting " .. what .. " stopped and isn't moving")
end

H.craft = {
  start = function(a, job)
    local args, c = job.args, a.char
    local recipe = c.force.recipes[args.recipe or ""]
    if not recipe then return fail("unknown recipe " .. tostring(args.recipe)) end
    if not recipe.enabled then
      return fail("recipe " .. recipe.name .. " is locked; see techs for what unlocks it")
    end
    -- count = items wanted (not recipe runs): copper-cable count=10 is 5 runs of 2.
    local first = recipe.products[1]
    local per = first.amount or first.amount_min or 1
    local count = args.count or per
    local runs = math.max(1, math.ceil(count / per))
    if util.cheat() then
      local inserted = c.insert { name = first.name, count = per * runs }
      return ok("crafted " .. inserted .. " " .. first.name)
    end
    local craftable = c.get_craftable_count(recipe)
    if craftable == 0 then
      return fail("cannot craft " .. first.name .. ": missing ingredients",
        { missing = missing_for(a, recipe, runs), category = recipe.category })
    end
    local n = math.min(runs, craftable)
    local short = ""
    if n < runs then
      local miss = missing_for(a, recipe, runs)
      local ing = next(miss)
      short = " (only " .. n * per .. " of " .. runs * per .. ": not enough " .. (ing or "ingredients") .. ")"
    end
    local started = c.begin_crafting { count = n, recipe = recipe, silent = true }
    if started == 0 then
      return fail("cannot hand-craft " .. recipe.name .. " (category " .. recipe.category .. ")")
    end
    job.item, job.want = first.name, c.get_item_count(first.name) + started * per
    job.made, job.short = started * per, short
    if args.wait == false then return ok("queued " .. started * per .. " " .. first.name .. short) end
  end,
  tick = function(a, job)
    local c = a.char
    if c.crafting_queue_size == 0 or c.get_item_count(job.item) >= job.want then
      account_crafts(a) -- credit stats/triggers now, not on the next 30-tick sweep
      return ok("crafted " .. job.made .. " " .. job.item .. job.short, { have = c.get_item_count(job.item) })
    end
    if craft_stalled(c, job) then return stalled_msg(c, job.item) end
    return nil
  end,
}

------------------------------------------------------------------------- place
local BELT_KIND = { ["transport-belt"] = true, ["underground-belt"] = true, splitter = true }
local function place_target(args)
  local item = prototypes.item[args.name or ""]
  if not item then return nil, "unknown item " .. tostring(args.name) end
  local ent = item.place_result
  if not ent then return nil, args.name .. " is not placeable" end
  return ent
end

-- Clearing trees, rocks and items on the ground out of a footprint, like a player would: it takes mining time and
-- the products go to the inventory. begin_clearing returns the state to keep on the job, or nil if nothing's there.
local CLUTTER = { "tree", "simple-entity", "item-entity" }
local function begin_clearing(c, area)
  local list = c.surface.find_entities_filtered {
    area = { { area[1][1] - 0.6, area[1][2] - 0.6 }, { area[2][1] + 0.6, area[2][2] + 0.6 } }, type = CLUTTER }
  if #list == 0 then return nil end
  local speed = c.prototype.mining_speed * (1 + c.force.manual_mining_speed_modifier
    + (c.character_mining_speed_modifier or 0))
  local secs = 0
  for _, e in pairs(list) do
    if e.valid and e.minable then secs = secs + (e.prototype.mineable_properties.mining_time or 0.5) / speed end
  end
  return { list = list, done_at = game.tick + (util.cheat() and 0 or math.ceil(secs * 60)) }
end

-- nil while the mining time runs; then the number cleared, or false and why (inventory full).
local function finish_clearing(c, clearing)
  if game.tick < clearing.done_at then return nil end
  local inv, n = c.get_main_inventory(), 0
  for _, e in pairs(clearing.list) do
    if e.valid then
      local name, pos = e.name, e.position
      if not e.mine { inventory = inv, force = false, raise_destroyed = true } then
        return false, "inventory full while clearing " .. name .. " at " .. xystr(pos)
      end
      n = n + 1
      triggers.note(c.force, c.surface, "mine-entity", name, 1)
    end
  end
  return n
end

-- An underground belt placed without saying entrance or exit: what a player gets. Just downstream of an unpaired
-- entrance facing the same way (within reach), it's that entrance's exit; otherwise an entrance. (rocket-r3: a plan
-- re-placed an exit and got a second entrance, "input, not paired yet", and the copper column stayed stopped.)
local function auto_ug_type(surface, name, pos, dir)
  local vecs = { [defines.direction.north] = { 0, -1 }, [defines.direction.east] = { 1, 0 },
    [defines.direction.south] = { 0, 1 }, [defines.direction.west] = { -1, 0 } }
  local v = vecs[dir]
  local proto = prototypes.entity[name]
  if not (v and proto) then return "input" end
  for k = 1, (proto.max_underground_distance or 5) do
    local u = surface.find_entities_filtered { position = { pos.x - v[1] * k, pos.y - v[2] * k }, radius = 0.3,
      name = name, limit = 1 }[1]
    if u then
      local paired = false
      pcall(function() paired = u.neighbours ~= nil end)
      if u.direction == dir and u.belt_to_ground_type == "input" and not paired then return "output" end
      return "input"
    end
  end
  return "input"
end

H.place = {
  start = function(a, job)
    local args = job.args
    local ent, err = place_target(args)
    if not ent then return fail(err) end
    job.entity = ent.name
    job.pos = util.pos(args.position or { args.x, args.y })
    if not (job.pos and job.pos.x and job.pos.y) then return fail("place needs x,y") end
    job.dir = util.parse_dir(args.direction)
    -- Inserters by where they pick up / drop (an inserter's direction is the side it takes from).
    local toward = args.pickup or args.drop
    if toward then
      local t = util.pos(toward)
      local dx, dy = t.x - job.pos.x, t.y - job.pos.y
      local d = math.abs(dx) >= math.abs(dy) and (dx > 0 and "east" or "west") or (dy > 0 and "south" or "north")
      if not args.pickup then d = ({ north = "south", south = "north", east = "west", west = "east" })[d] end
      job.dir = util.parse_dir(d)
    end
    -- Onto the grid like the game's cursor: odd sizes on tile centers (x.5), even sizes on tile edges.
    local w, h = ent.tile_width or 1, ent.tile_height or 1
    if job.dir == defines.direction.east or job.dir == defines.direction.west then w, h = h, w end
    local function grid(v, n) return n % 2 == 1 and (math.floor(v) + 0.5) or math.floor(v + 0.5) end
    if ent.type ~= "curved-rail-a" and ent.type ~= "curved-rail-b" and not ent.type:find("rail") then
      job.pos = { x = grid(job.pos.x, w), y = grid(job.pos.y, h) }
    end
    if not util.cheat() and a.char.get_item_count(args.name) < 1 then
      return fail("no " .. args.name .. " in inventory")
    end
  end,
  tick = function(a, job)
    local c, args = a.char, job.args
    local near = approach(a, job, job.pos, c.build_distance - 0.5)
    if near == nil then return nil end
    if type(near) == "table" then return near end

    local surface = c.surface
    if job.clearing then
      local n, why = finish_clearing(c, job.clearing)
      if n == nil then return nil end
      job.clearing = nil
      if not n then return fail(why .. " to place " .. job.entity) end
      job.cleared = (job.cleared or 0) + n
    end
    local spec = {
      name = job.entity, position = job.pos, direction = job.dir, force = c.force,
      build_check_type = defines.build_check_type.manual,
    }
    -- Something already on this exact spot that a player would just click over: the same thing (done, or rotate it)
    -- or the same family (yellow belt -> red, belt -> underground): fast-replace, the old one back to the inventory.
    local proto = prototypes.entity[job.entity]
    for _, e in pairs(surface.find_entities_filtered { position = job.pos, radius = 0.05, force = c.force }) do
      if util.dist(e.position, job.pos) < 0.1 then
        if e.name == job.entity and not (proto.type == "underground-belt" and args.type and e.belt_to_ground_type ~= args.type) then
          if e.supports_direction and e.direction ~= job.dir and e.rotatable then
            e.direction = job.dir
            return ok("turned the " .. e.name .. " already at " .. xystr(e.position) .. " to face "
              .. (util.DIR_NAMES[job.dir] or "?"), { entity = e.name, position = util.xy(e.position), rotated = true })
          end
          return ok(job.entity .. " is already at " .. xystr(e.position),
            { entity = e.name, position = util.xy(e.position), unit_number = e.unit_number, already = true })
        elseif proto.fast_replaceable_group and proto.fast_replaceable_group == e.prototype.fast_replaceable_group then
          job.fast_replace = e.name
        elseif args.replace_belt and BELT_KIND[proto.type] and BELT_KIND[e.type] then
          -- belt -> underground/splitter and back (different replace groups): pick the old one up, as a player
          -- would, and put the new one down; whatever was on it goes to the inventory too
          local was = e.name
          if pcall(function() return c.mine_entity(e, true) end) and not e.valid then
            job.replaced = was
          end
        end
      end
    end
    if not surface.can_place_entity(spec) and prototypes.entity[job.entity].type == "offshore-pump" then
      -- Pumps only fit facing the water one way; try the others before giving up.
      for _, dn in ipairs { "north", "east", "south", "west" } do
        local s2 = { name = spec.name, position = spec.position, direction = defines.direction[dn], force = spec.force,
          build_check_type = spec.build_check_type }
        if surface.can_place_entity(s2) then
          spec, job.dir = s2, s2.direction
          break
        end
      end
      -- still nowhere: the water's edge is near but not right there; look around (a player shifts the cursor)
      if not surface.can_place_entity(spec) then
        local found
        for r = 1, 6 do
          for dx = -r, r do
            for dy = -r, r do
              if not found and math.max(math.abs(dx), math.abs(dy)) == r then
                for _, dn in ipairs { "north", "east", "south", "west" } do
                  local q = { x = math.floor(job.pos.x) + dx + 0.5, y = math.floor(job.pos.y) + dy + 0.5 }
                  local s2 = { name = spec.name, position = q, direction = defines.direction[dn], force = spec.force,
                    build_check_type = spec.build_check_type }
                  if surface.can_place_entity(s2) then found = s2 break end
                end
              end
            end
          end
          if found then break end
        end
        if found then
          spec, job.dir, job.pos = found, found.direction, found.position
          job.moved = true
        end
      end
    end
    -- (can_place_entity can't be told an underground is an exit, so it judges an exit's swap as an entrance: skip it
    -- for an underground replacing its own kind; create_entity's fast_replace does the real check)
    local ug_swap = job.fast_replace and proto.type == "underground-belt"
    if not ug_swap and not surface.can_place_entity(spec) then
      -- We may be standing on the spot; step aside once and retry.
      local proto = prototypes.entity[job.entity]
      local box = proto.collision_box
      local half = math.max(box.right_bottom.x - box.left_top.x, box.right_bottom.y - box.left_top.y) / 2
      local cp = c.position
      local inside = math.abs(cp.x - job.pos.x) < half + 0.5 and math.abs(cp.y - job.pos.y) < half + 0.5
      if inside and not job.sidestepped then
        job.sidestepped = true
        local dx, dy = cp.x - job.pos.x, cp.y - job.pos.y
        if math.abs(dx) + math.abs(dy) < 0.1 then dx = 1 end
        local len = math.sqrt(dx * dx + dy * dy)
        local goal = { x = job.pos.x + dx / len * (half + 1.6), y = job.pos.y + dy / len * (half + 1.6) }
        job.side = { goal = goal, radius = 0.4 }
      end
      if job.side then
        local r = movement.tick(c, job.side)
        if r == nil then return nil end
        job.side = nil
        if surface.can_place_entity(spec) then goto place end
      end
      local blockers = {}
      local area = { { job.pos.x - half, job.pos.y - half }, { job.pos.x + half, job.pos.y + half } }
      local found = surface.find_entities_filtered { area = area }
      for _, e in pairs(found) do
        if e.name == job.entity and util.dist(e.position, job.pos) < 0.1 then
          -- Already built (by us earlier, a teammate or a bot): that's the outcome asked for.
          local note = (e.supports_direction and e.direction ~= job.dir)
            and (", facing " .. (util.DIR_NAMES[e.direction] or "?") .. "; rotate it if that's wrong") or ""
          return ok(job.entity .. " is already at " .. xystr(e.position) .. note,
            { entity = e.name, position = util.xy(e.position), unit_number = e.unit_number, already = true })
        end
      end
      -- Trees, rocks and items on the ground: clear them like a player would (mining time, products to the
      -- inventory), then place. Search a little wider: a tree's center can sit outside the footprint.
      local others = 0
      for _, e in pairs(found) do
        if e.type ~= "resource" and e.type ~= "tree" and e.type ~= "simple-entity" and e.type ~= "item-entity" then
          others = others + 1
        end
      end
      if others == 0 and (job.clears or 0) < 3 then
        job.clearing = begin_clearing(c, area)
        if job.clearing then
          job.clears = (job.clears or 0) + 1
          return nil
        end
      end
      for _, e in pairs(found) do
        if e.type ~= "resource" then blockers[#blockers + 1] = e.name .. "@" .. xystr(e.position) end
      end
      -- the game won't let a player join two different fluids: say which, not "water, cliff or wrong tile"
      -- (a pipe line's last tile beside a machine inlet for another fluid: 9 failures in an afternoon)
      local fluids, seenF = {}, {}
      if proto.fluidbox_prototypes and #proto.fluidbox_prototypes > 0 then
        for _, n in pairs(surface.find_entities_filtered { area = { { job.pos.x - 1.4, job.pos.y - 1.4 },
          { job.pos.x + 1.4, job.pos.y + 1.4 } }, force = c.force }) do
          local okF, fb = pcall(function() return n.fluidbox end)
          if okF and fb then
            for i = 1, #fb do
              local fl = fb[i]
              if fl and fl.name and not seenF[fl.name] then
                seenF[fl.name] = true
                fluids[#fluids + 1] = fl.name .. " (" .. n.name .. "@" .. xystr(n.position) .. ")"
              end
            end
          end
        end
      end
      local why
      if #blockers > 0 then
        why = "blocked by " .. table.concat(blockers, ", ", 1, math.min(#blockers, 4))
      elseif #fluids >= 2 then
        why = "it would join " .. table.concat(fluids, " and ", 1, math.min(#fluids, 3))
          .. ", and fluids can't mix: connect to the inlet for the right fluid, or pass under with pipe-to-ground"
      elseif proto.type == "mining-drill" then
        why = "a mining drill needs ore under it (check the map for the patch)"
      elseif proto.type == "offshore-pump" then
        why = "an offshore pump must be placed at the edge of water, facing it"
      else
        why = "invalid spot (water, cliff or wrong tile)"
      end
      if #blockers > 0 then
        local spot = surface.find_non_colliding_position(job.entity, job.pos, 12, 0.5)
        if spot then
          local w, h = proto.tile_width or 1, proto.tile_height or 1
          if job.dir == defines.direction.east or job.dir == defines.direction.west then w, h = h, w end
          local function grid(v, n) return n % 2 == 1 and (math.floor(v) + 0.5) or math.floor(v + 0.5) end
          spot = { x = grid(spot.x, w), y = grid(spot.y, h) }
          if surface.can_place_entity { name = job.entity, position = spot, direction = job.dir, force = c.force,
                build_check_type = defines.build_check_type.manual } then
            why = why .. "; nearest free spot: " .. xystr(spot)
          end
        end
      end
      return fail("cannot place " .. job.entity .. " at " .. xystr(job.pos) .. ": " .. why)
    end
    ::place::
    local ptype = prototypes.entity[job.entity].type
    if ptype == "underground-belt" and not args.type then
      args.type = auto_ug_type(surface, job.entity, job.pos, job.dir)
    end
    local created = surface.create_entity {
      name = job.entity, position = job.pos, direction = job.dir, force = c.force,
      raise_built = true, create_build_effect_smoke = false,
      fast_replace = job.fast_replace and true or nil, character = job.fast_replace and c or nil,
      spill = job.fast_replace and true or nil,
      -- underground belts: "input" is the entrance, "output" the exit; both face the travel direction
      type = (ptype == "underground-belt") and (args.type or "input") or nil,
    }
    if not created and BELT_KIND[ptype] then
      -- a splitter or underground dropped onto belts: the game swaps them in for a player; do the same
      created = surface.create_entity {
        name = job.entity, position = job.pos, direction = job.dir, force = c.force, raise_built = true,
        fast_replace = true, character = c, spill = true,
        type = (ptype == "underground-belt") and (args.type or "input") or nil,
      }
      if not created then
        local box = prototypes.entity[job.entity].collision_box
        local area = { { job.pos.x + box.left_top.x, job.pos.y + box.left_top.y },
          { job.pos.x + box.right_bottom.x, job.pos.y + box.right_bottom.y } }
        if job.dir == defines.direction.east or job.dir == defines.direction.west then
          area = { { job.pos.x + box.left_top.y, job.pos.y + box.left_top.x },
            { job.pos.x + box.right_bottom.y, job.pos.y + box.right_bottom.x } }
        end
        for _, o in pairs(surface.find_entities_filtered { area = area, force = c.force }) do
          if o.valid and BELT_KIND[o.type] then pcall(function() return c.mine_entity(o, true) end) end
        end
        created = surface.create_entity {
          name = job.entity, position = job.pos, direction = job.dir, force = c.force, raise_built = true,
          type = (ptype == "underground-belt") and (args.type or "input") or nil,
        }
        if created then job.replaced = "belts" end
      end
    end
    if not created then return fail("create_entity failed for " .. job.entity) end
    if not util.cheat() then c.remove_item { name = args.name, count = 1 } end
    if created.unit_number then storage.built_by[created.unit_number] = a.name end
    triggers.note(c.force, surface, "build-entity", created.name, 1)
    local data = { entity = created.name, position = util.xy(created.position), unit_number = created.unit_number }
    local msg = "placed " .. created.name .. " at " .. xystr(created.position)
    if job.cleared then msg = msg .. " (cleared " .. job.cleared .. " trees/rocks first)" end
    if job.fast_replace then msg = msg .. " (replaced the " .. job.fast_replace .. " there)" end
    if job.replaced then msg = msg .. " (picked up the " .. job.replaced .. " there first)" end
    if job.moved then msg = msg .. " (the nearest spot where it fits)" end
    if created.type == "mining-drill" then
      data.drops_at = util.xy(created.drop_position)
      msg = msg .. " (output drops at " .. xystr(created.drop_position) .. ")"
      -- mining_target isn't set until the drill's first update, so count ore under its footprint instead.
      local ores = surface.find_entities_filtered { area = created.bounding_box, type = "resource" }
      if #ores == 0 then
        msg = msg .. " WARNING: no resource under it"
      else
        local total, name = 0, ores[1].name
        for _, o in pairs(ores) do total = total + o.amount end
        data.ore, data.ore_amount = name, total
        msg = msg .. " on " .. #ores .. " tiles of " .. name .. " (" .. total .. " ore)"
      end
    elseif created.type == "underground-belt" then
      local n = created.neighbours
      msg = msg .. " (" .. created.belt_to_ground_type .. (n and (", paired with " .. xystr(n.position)) or ", not paired yet") .. ")"
    elseif created.type == "inserter" then
      data.from, data.to = util.xy(created.pickup_position), util.xy(created.drop_position)
      msg = msg .. " (" .. util.inserter_sides(created) .. ": takes from " .. xystr(created.pickup_position)
        .. ", drops to " .. xystr(created.drop_position) .. ")"
    end
    return ok(msg, data)
  end,
}

------------------------------------------------------------------------- insert / take
-- A locked entity (operable = false: a map's or test's fixture) can't be opened by players, so not by a serf either.
local function locked(e)
  return e.name .. " at " .. xystr(e.position) .. " is locked: nobody can open it"
end

H.insert = {
  start = function(a, job)
    local args = job.args
    if not args.item then return fail("insert needs item") end
    if args.player then  -- hand it to a player: walk up to them (wherever they go) and put it in their inventory
      local p = util.find_player(args.player)
      if not (p and p.connected and p.character) then return fail("player " .. args.player .. " isn't here") end
      job.target = p.character
      return nil
    end
    job.target = entity_at(a, args)
    if not job.target then return fail("no entity at " .. tostring(args.x) .. "," .. tostring(args.y)) end
    if not job.target.operable then return fail(locked(job.target)) end
  end,
  tick = function(a, job)
    local c, args, e = a.char, job.args, job.target
    if not e.valid then return fail("target is gone") end
    local near = approach(a, job, e.position, c.reach_distance - 0.5)
    if near == nil then return nil end
    if type(near) == "table" then return near end
    if not needs_reach(a, e) then return fail("out of reach of " .. e.name) end
    local have = util.cheat() and (args.count or 50) or c.get_item_count(args.item)
    local count = math.min(args.count or have, have)
    if count <= 0 then return fail("no " .. args.item .. " in inventory") end
    local inserted = e.insert { name = args.item, count = count }
    if inserted == 0 then
      -- Like a player: swap out a different fuel that's sitting in the only fuel slot.
      local fuel = e.get_fuel_inventory and e.get_fuel_inventory()
      local proto = prototypes.item[args.item]
      if fuel and fuel.valid and proto and proto.fuel_value > 0 then
        for name, n in pairs(util.contents(fuel)) do
          if name ~= args.item and not name:find("@") then
            local moved = c.insert { name = name, count = n }
            if moved > 0 then fuel.remove { name = name, count = moved } end
          end
        end
        inserted = e.insert { name = args.item, count = count }
      end
    end
    if inserted == 0 then
      local fuel = e.get_fuel_inventory and e.get_fuel_inventory()
      local why = ""
      if fuel and fuel.valid and prototypes.item[args.item] and prototypes.item[args.item].fuel_value > 0 then
        local f = util.contents(fuel)
        if next(f) then why = " (fuel slot already holds " .. helpers.table_to_json(f) .. "; burn it down or take it out)" end
      end
      if why == "" then
        local okR, r = pcall(e.get_recipe)
        if e.type == "assembling-machine" and not (okR and r) then
          why = " (no recipe set yet: set its recipe first)"
        elseif okR and r then
          local ings, uses = {}, false
          for _, ing in pairs(r.ingredients) do
            ings[#ings + 1] = ing.name
            if ing.name == args.item then uses = true end
          end
          why = uses and " (its input already holds as much " .. args.item .. " as it takes)"
            or (" (its recipe " .. r.name .. " uses " .. table.concat(ings, ", ") .. ")")
        elseif e.type == "lab" then
          why = " (labs take science packs only)"
        elseif e.type == "container" or e.type == "logistic-container" then
          why = " (it's full)"
        end
      end
      return fail(e.name .. " won't accept " .. args.item .. why)
    end
    if not util.cheat() then c.remove_item { name = args.item, count = inserted } end
    return ok("inserted " .. inserted .. " " .. args.item .. " into " .. e.name .. " at " .. xystr(e.position),
      { inserted = inserted })
  end,
}

H.take = {
  start = function(a, job)
    job.target = entity_at(a, job.args)
    if not job.target then return fail("no entity at " .. tostring(job.args.x) .. "," .. tostring(job.args.y)) end
    if not job.target.operable then return fail(locked(job.target)) end
  end,
  tick = function(a, job)
    local c, args, e = a.char, job.args, job.target
    if not e.valid then return fail("target is gone") end
    local near = approach(a, job, e.position, c.reach_distance - 0.5)
    if near == nil then return nil end
    if type(near) == "table" then return near end
    local taken = {}
    local function pull(inv, only)
      if not (inv and inv.valid) then return end
      for name, n in pairs(util.contents(inv)) do
        if (not only or name == only) and not name:find("@") then
          local want = args.count and math.min(args.count - (taken[name] or 0), n) or n
          if want > 0 then
            local got = c.insert { name = name, count = want }
            if got > 0 then
              inv.remove { name = name, count = got }
              taken[name] = (taken[name] or 0) + got
            end
          end
        end
      end
    end
    if args.item then
      for i = 1, e.get_max_inventory_index() do pull(e.get_inventory(i), args.item) end
    else
      pull(e.get_output_inventory())
    end
    if next(taken) == nil then
      local hint = ""
      if args.item then
        local okS, src = pcall(order_queries.sources,
          { items = { args.item }, x = c.position.x, y = c.position.y, radius = 300 })
        local list = okS and src.sources[args.item] or {}
        if list[1] then
          hint = "; nearest with " .. args.item .. ": " .. list[1].n .. " at " .. list[1].p[1] .. "," .. list[1].p[2]
        else
          hint = "; no chest or machine output within 300 tiles has any"
        end
      end
      local holds, room = {}, false
      for i = 1, e.get_max_inventory_index() do
        for name, n in pairs(util.contents(e.get_inventory(i))) do
          if #holds < 6 then holds[#holds + 1] = n .. " " .. name end
          if not name:find("@") and c.can_insert { name = name, count = 1 } then room = true end
        end
      end
      if #holds > 0 and not room then
        -- the chest has it but the pocket can't take any: say so ("nothing to take from a chest of 3200 plates"
        -- read as an empty chest, and the actor tried again 489 times)
        return fail("my inventory is full: can't take from " .. e.name .. " (it holds " .. table.concat(holds, ", ")
          .. ")", { inventory_full = true })
      end
      hint = " (it holds " .. (#holds > 0 and table.concat(holds, ", ") or "nothing") .. ")" .. hint
      return fail("nothing to take from " .. e.name .. (args.item and (" (" .. args.item .. ")") or "") .. hint)
    end
    local parts = {}
    for k, v in pairs(taken) do parts[#parts + 1] = v .. " " .. k end
    return ok("took " .. table.concat(parts, ", ") .. " from " .. e.name, { taken = taken })
  end,
}

------------------------------------------------------------------------- set_recipe / rotate / research / wait
-- Pick items up off belts, like a player hovering a belt and grabbing: walk to the nearest belt carrying the item
-- (near x,y, or near the character), take from every belt in reach, wait for more to flow by, until count or ~30 s.
local GRAB_BELTS = { "transport-belt", "underground-belt", "splitter" }
H.grab = {
  start = function(a, job)
    local name = job.args.item
    if not (name and prototypes.item[name]) then return fail("grab needs an item") end
    job.want = tonumber(job.args.count) or 50
    job.got = 0
    job.t0 = game.tick
  end,
  tick = function(a, job)
    local c, name = a.char, job.args.item
    if not job.belt or not job.belt.valid then
      local center = (job.args.x and { x = job.args.x, y = job.args.y }) or c.position
      local best, bd
      for _, b in pairs(c.surface.find_entities_filtered { type = GRAB_BELTS, position = center, radius = 64,
        force = c.force }) do
        local n = 0
        for li = 1, 2 do
          local okL, line = pcall(b.get_transport_line, li)
          if okL and line then n = n + line.get_item_count(name) end
        end
        if n > 0 then
          local d = util.dist(b.position, c.position)
          if not bd or d < bd then best, bd = b, d end
        end
      end
      if not best then
        if job.got > 0 then return ok("grabbed " .. job.got .. " " .. name .. " off belts", { got = job.got }) end
        return fail("no belt within 64 tiles carries " .. name)
      end
      job.belt = best
    end
    local near = approach(a, job, job.belt.position, c.reach_distance - 1)
    if near == nil then return nil end
    if type(near) == "table" then return near end
    for _, b in pairs(c.surface.find_entities_filtered { type = GRAB_BELTS, position = c.position,
      radius = c.reach_distance - 0.5, force = c.force }) do
      for li = 1, 2 do
        local okL, line = pcall(b.get_transport_line, li)
        if okL and line then
          local n = math.min(line.get_item_count(name), job.want - job.got)
          if n > 0 then
            local got = c.insert { name = name, count = n }
            if got > 0 then
              line.remove_item { name = name, count = got }
              job.got = job.got + got
            elseif job.got == 0 then
              -- the items are right there and the pocket takes none: say so now, not "nothing to grab" in 30 s
              return fail("my inventory is full: can't grab " .. name, { inventory_full = true })
            end
          end
        end
      end
    end
    if job.got >= job.want then return ok("grabbed " .. job.got .. " " .. name .. " off belts", { got = job.got }) end
    if game.tick - job.t0 > 1800 then
      return job.got > 0 and ok("grabbed " .. job.got .. " " .. name .. " off belts (wanted " .. job.want .. ")",
        { got = job.got }) or fail("nothing to grab within reach")
    end
    return nil
  end,
}

H.set_recipe = {
  start = function(a, job)
    job.target = entity_at(a, job.args)
    if not job.target then return fail("no machine at " .. tostring(job.args.x) .. "," .. tostring(job.args.y)) end
    if job.target.type ~= "assembling-machine" then return fail(job.target.name .. " has no recipe to set") end
  end,
  tick = function(a, job)
    local c, e = a.char, job.target
    if not e.valid then return fail("target is gone") end
    local near = approach(a, job, e.position, c.reach_distance - 0.5)
    if near == nil then return nil end
    if type(near) == "table" then return near end
    local okk, err = pcall(function() e.set_recipe(job.args.recipe) end)
    if not okk then return fail("set_recipe failed: " .. tostring(err)) end
    local r = e.get_recipe()
    return ok("set " .. e.name .. " at " .. xystr(e.position) .. " to " .. (r and r.name or "nothing"))
  end,
}

H.rotate = {
  start = function(a, job)
    job.target = entity_at(a, job.args)
    if not job.target then return fail("no entity at " .. tostring(job.args.x) .. "," .. tostring(job.args.y)) end
  end,
  tick = function(a, job)
    local c, e = a.char, job.target
    if not e.valid then return fail("target is gone") end
    local near = approach(a, job, e.position, c.reach_distance - 0.5)
    if near == nil then return nil end
    if type(near) == "table" then return near end
    if job.args.direction then
      e.direction = util.parse_dir(job.args.direction)
    elseif job.args.reverse then  -- turn it around (180 degrees), e.g. an inserter facing the wrong way
      e.rotate {}
      e.rotate {}
    else
      e.rotate {}
    end
    return ok("rotated " .. e.name .. " to " .. (util.DIR_NAMES[e.direction] or "?"))
  end,
}

H.research = {
  start = function(a, job)
    local force = a.char.force
    local tech = force.technologies[job.args.tech or ""]
    if not tech then return fail("unknown technology " .. tostring(job.args.tech)) end
    if tech.researched then return fail(tech.name .. " is already researched") end
    if tech.prototype.research_trigger then
      return fail(tech.name .. " isn't researched in labs; it unlocks when you " .. util.trigger_text(tech))
    end
    local queue = {}
    for _, q in pairs(force.research_queue or {}) do queue[#queue + 1] = q.name end
    local function names() return table.concat(queue, ", ") end
    if job.args.remove then
      local keep = {}
      for _, n in ipairs(queue) do if n ~= tech.name then keep[#keep + 1] = n end end
      if #keep == #queue then return fail(tech.name .. " isn't in the research queue") end
      force.research_queue = keep
      queue = {}
      for _, q in pairs(force.research_queue or {}) do queue[#queue + 1] = q.name end
      return ok("removed " .. tech.name .. "; queue now: " .. names())
    end
    if job.args.first then
      -- Like dragging it to the front in the research GUI: its unresearched prerequisites come with it.
      local front, seen, blocked = {}, {}, nil
      local function add(t)
        if seen[t.name] or t.researched then return end
        seen[t.name] = true
        if t.prototype.research_trigger then blocked = blocked or t.name return end
        for _, p in pairs(t.prerequisites) do add(p) end
        front[#front + 1] = t.name
      end
      add(tech)
      if blocked then
        return fail(tech.name .. " needs " .. blocked .. " first, a trigger tech that unlocks by doing: "
          .. util.trigger_text(force.technologies[blocked]))
      end
      for _, n in ipairs(queue) do if not seen[n] then front[#front + 1] = n end end
      local okSet, err = pcall(function() force.research_queue = front end)
      if not okSet then return fail("could not reorder: " .. tostring(err)) end
      queue = {}
      local there = false
      for _, q in pairs(force.research_queue or {}) do
        queue[#queue + 1] = q.name
        there = there or q.name == tech.name
      end
      if not there then return fail("the game refused that order; queue now: " .. names()) end
      return ok("moved " .. tech.name .. " to the front; queue now: " .. names())
    end
    for _, n in ipairs(queue) do
      if n == tech.name then return ok(tech.name .. " is already in the research queue (first=true moves it to the front)") end
    end
    if force.add_research(tech) then return ok("queued research " .. tech.name) end
    return fail("could not queue " .. tech.name .. " (missing prerequisites or queue full)")
  end,
}

-- The settings a player clicks into a building: logistic requests (requester/buffer chests, or your own
-- character with self=true), inserter filters, splitter filter and priorities.
local function set_requests(point, requests)
  if not point then return "no logistic requests on that" end
  local section = point.sections_count > 0 and point.get_section(1) or point.add_section()
  for i = section.filters_count, 1, -1 do section.clear_slot(i) end
  local i = 0
  for name, count in pairs(requests) do
    if not prototypes.item[name] then return "unknown item " .. name end
    i = i + 1
    section.set_slot(i, { value = { name = name, quality = "normal", comparator = "=" }, min = tonumber(count) or 0 })
  end
  return nil, i
end

local function configure(e, args)
  local done = {}
  if args.requests then
    local err, n = set_requests(e.get_requester_point and e.get_requester_point() or nil, args.requests)
    if err then return nil, err end
    done[#done + 1] = n .. " requests"
  end
  if args.filter ~= nil or args.filters then
    local list = args.filters or (args.filter ~= "none" and { args.filter } or {})
    if e.type == "inserter" then
      if (e.filter_slot_count or 0) == 0 then return nil, e.name .. " has no filter slots (use a fast/bulk/stack inserter)" end
      e.use_filters = #list > 0
      for i = 1, e.filter_slot_count do e.set_filter(i, list[i] and { name = list[i] } or nil) end
      if args.blacklist then e.inserter_filter_mode = "blacklist" else e.inserter_filter_mode = "whitelist" end
      done[#done + 1] = "filter " .. (#list > 0 and table.concat(list, ",") or "cleared")
    elseif e.type == "splitter" then
      e.splitter_filter = list[1] and { name = list[1] } or nil
      done[#done + 1] = "filter " .. (list[1] or "cleared")
    else
      return nil, e.name .. " has no filters"
    end
  end
  if args.output_priority or args.input_priority then
    if e.type ~= "splitter" then return nil, "priority is for splitters" end
    if args.output_priority then e.splitter_output_priority = args.output_priority end
    if args.input_priority then e.splitter_input_priority = args.input_priority end
    done[#done + 1] = "priority in " .. e.splitter_input_priority .. " out " .. e.splitter_output_priority
  end
  if #done == 0 then return nil, "nothing to set: give requests={item:count}, filter=item|none, output_priority, input_priority" end
  return table.concat(done, "; ")
end

H.configure = {
  start = function(a, job)
    if job.args.self then
      local pt = a.char.get_requester_point()
      if not pt then return fail("your character can't make logistic requests yet (research logistic-robotics)") end
      local err, n = set_requests(pt, job.args.requests or {})
      if err then return fail(err) end
      return ok("set " .. n .. " personal logistic requests (robots bring them when you're in a network)")
    end
    job.target = entity_at(a, job.args)
    if not job.target then return fail("no entity at " .. tostring(job.args.x) .. "," .. tostring(job.args.y)) end
  end,
  tick = function(a, job)
    local c, e = a.char, job.target
    if not e.valid then return fail("target is gone") end
    local near = approach(a, job, e.position, c.reach_distance - 0.5)
    if near == nil then return nil end
    if type(near) == "table" then return near end
    local okC, msg, err = pcall(configure, e, job.args)
    if not okC then return fail("configure failed: " .. tostring(msg)) end
    if not msg then return fail(err) end
    return ok(e.name .. ": " .. msg)
  end,
}

-- Wear armor and fill its equipment grid from your inventory, like a player does. Exoskeletons make you faster;
-- a personal roboport plus construction robots in your inventory builds ghosts around you while you walk.
H.equip = {
  start = function(a, job)
    local c, args = a.char, job.args
    local main = c.get_inventory(defines.inventory.character_main)
    local done = {}
    local worn = c.get_inventory(defines.inventory.character_armor)[1]
    if args.armor and worn.valid_for_read and worn.name == args.armor then
      done[#done + 1] = "already wearing " .. args.armor
    elseif args.armor then
      if main.get_item_count(args.armor) < 1 then return fail("no " .. args.armor .. " in your inventory") end
      local slot = c.get_inventory(defines.inventory.character_armor)
      local old = slot[1].valid_for_read and slot[1].name or nil
      if old then
        if main.insert(slot[1]) < 1 then return fail("no room to take off your " .. old) end
        slot[1].clear()
      end
      main.remove { name = args.armor, count = 1 }
      slot.insert { name = args.armor, count = 1 }
      done[#done + 1] = "wearing " .. args.armor
    end
    local list = args.equipment or (args.item and { args.item }) or {}
    if #list > 0 then
      local grid = c.grid
      if not grid then return fail("your armor has no equipment grid (wear modular or power armor first)") end
      for _, name in ipairs(list) do
        local item = prototypes.item[name]
        local eq = item and item.place_as_equipment_result
        if not eq then return fail(name .. " isn't equipment") end
        if main.get_item_count(name) < 1 then return fail("no " .. name .. " in your inventory") end
        local placed = grid.put { name = eq.name }
        if not placed then return fail("no room in the armor grid for " .. name .. " (" .. #done .. " done)") end
        main.remove { name = name, count = 1 }
        done[#done + 1] = name
      end
    end
    if #done == 0 then return fail("equip needs armor=<armor item> and/or equipment=[items]") end
    local grid = c.grid
    local summary = ""
    if grid then
      summary = " (grid " .. grid.width .. "x" .. grid.height .. ", " .. #grid.equipment .. " pieces"
      local okE, pct = pcall(function()
        return grid.battery_capacity > 0 and math.floor(100 * grid.available_in_batteries / grid.battery_capacity) or nil
      end)
      if okE and pct then summary = summary .. ", battery " .. pct .. "%" end
      summary = summary .. ")"
    end
    return ok("equipped: " .. table.concat(done, ", ") .. summary)
  end,
}

-- The red X in a chest's inventory: only the first `slots` slots accept items from inserters (0 = none).
H.limit = {
  start = function(a, job)
    job.target = entity_at(a, job.args)
    if not job.target then return fail("no entity at " .. tostring(job.args.x) .. "," .. tostring(job.args.y)) end
  end,
  tick = function(a, job)
    local c, e = a.char, job.target
    if not e.valid then return fail("target is gone") end
    local near = approach(a, job, e.position, c.reach_distance - 0.5)
    if near == nil then return nil end
    if type(near) == "table" then return near end
    local inv = e.get_inventory(defines.inventory.chest)
    if not inv or not inv.supports_bar() then return fail(e.name .. " has no limitable inventory") end
    if job.args.slots == nil or job.args.slots == "none" then
      inv.set_bar()
      return ok("cleared the limit on " .. e.name)
    end
    local n = math.max(0, math.min(tonumber(job.args.slots) or 0, #inv))
    inv.set_bar(n + 1)
    return ok("limited " .. e.name .. " to " .. n .. " of " .. #inv .. " slots")
  end,
}

H.wait = {
  start = function(a, job) job.until_tick = game.tick + math.min((job.args.seconds or 1) * 60, 60 * 120) end,
  tick = function(a, job) if game.tick >= job.until_tick then return ok("waited") end end,
}

H.say = {
  start = function(a, job)
    agents.say(a, tostring(job.args.text or ""))
    return ok("said")
  end,
}

------------------------------------------------------------------------- connect / follow
local VEC_DIR = { ["1,0"] = "east", ["-1,0"] = "west", ["0,1"] = "south", ["0,-1"] = "north" }
local DIR_VEC = { [defines.direction.north] = { 0, -1 }, [defines.direction.east] = { 1, 0 },
  [defines.direction.south] = { 0, 1 }, [defines.direction.west] = { -1, 0 } }
local BELTS = { "transport-belt", "underground-belt", "splitter" }

local function belt_at(surface, p)
  return surface.find_entities_filtered { position = p, radius = 0.3, type = BELTS, limit = 1 }[1]
end

-- The belt in front of a belt, if any.
local function ahead(surface, e)
  local v = DIR_VEC[e.direction]
  return v and belt_at(surface, { x = e.position.x + v[1], y = e.position.y + v[2] })
end

-- The last belt of a line: nothing in front of it takes its items (or what's there runs head-on into it).
local function line_end(surface, e)
  local f = ahead(surface, e)
  return not f or f.direction == util.opposite_dir(e.direction)
end

-- The neighbouring belt that runs straight into this one, if any.
local function feeder_of(surface, e)
  for _, v in pairs(DIR_VEC) do
    local p = { x = e.position.x + v[1], y = e.position.y + v[2] }
    local n = belt_at(surface, p)
    local nv = n and DIR_VEC[n.direction]
    if nv and nv[1] == -v[1] and nv[2] == -v[2] then return p end
  end
end

-- Getting items for a job the way a player would: walk to the nearest chests and machine outputs that hold them
-- and take what's needed, then hand-craft whatever storage couldn't cover. supply_start(job, {item = n}) sets it
-- up; supply_tick returns nil while walking/crafting, true once the inventory holds every n, or a failure.
local SUPPLY_RADIUS = 400

local function supply_start(job, need)
  local items = {}
  for name in pairs(need) do items[#items + 1] = name end
  table.sort(items)
  job.supply = { need = need, items = items, k = 1, took = {}, crafted = {} }
end

local function supply_tick(a, job)
  local c, st = a.char, job.supply
  if util.cheat() then
    for name, n in pairs(st.need) do
      local short = n - c.get_item_count(name)
      if short > 0 then c.insert { name = name, count = short } end
    end
    return true
  end
  while st.items[st.k] do
    local name = st.items[st.k]
    local n = st.need[name]
    local have = c.get_item_count(name)
    if st.crafting then
      if have >= n then
        account_crafts(a)
        st.crafting, st.k, st.srcs = nil, st.k + 1, nil
      elseif c.crafting_queue_size == 0 then
        return fail("needs " .. n .. " " .. name .. " but crafting fell short (have " .. have .. ")")
      elseif craft_stalled(c, job) then
        return stalled_msg(c, name)
      else
        return nil
      end
    elseif have >= n then
      st.k, st.srcs = st.k + 1, nil
    else
      if not st.srcs then
        local okS, src = pcall(order_queries.sources, { items = { name }, x = c.position.x, y = c.position.y,
          radius = SUPPLY_RADIUS, limit = 8, exclude = job.supply_exclude })
        st.srcs, st.j = okS and src.sources[name] or {}, 1
      end
      local s = st.srcs[st.j]
      if s then
        local e = c.surface.find_entities_filtered { position = s.p, radius = 0.6, type = { "container",
          "logistic-container", "infinity-container", "furnace", "assembling-machine" }, limit = 1 }[1]
        if not (e and e.valid) then
          st.j = st.j + 1
        else
          local near = approach(a, st, e.position, c.reach_distance - 0.5)
          if near == nil then return nil end
          if type(near) == "table" then
            st.j = st.j + 1 -- unreachable: try the next one
          else
            local machine = e.type == "furnace" or e.type == "assembling-machine"
            local inv = machine and e.get_output_inventory() or e.get_inventory(defines.inventory.chest)
            local avail = inv and inv.get_item_count(name) or 0
            local got = avail > 0 and c.insert { name = name, count = math.min(n - have, avail) } or 0
            if got > 0 then
              if e.type ~= "infinity-container" then inv.remove { name = name, count = got } end
              st.took[#st.took + 1] = got .. " " .. name .. " from " .. e.name .. " at " .. xystr(e.position)
            end
            st.j = st.j + 1
          end
        end
      else
        -- Storage is out: hand-craft the rest if the ingredients are on hand.
        local recipe = c.force.recipes[name]
        local per = recipe and recipe.enabled and recipe.products[1].name == name and (recipe.products[1].amount or 1)
        local runs = per and math.ceil((n - have) / per)
        st.expanded = st.expanded or {}
        if runs and c.get_craftable_count(recipe) < runs and not st.expanded[name] then
          -- Not enough on hand to craft it: fetch the ingredients from storage first (each of those may in turn be
          -- crafted from its own), then come back to this item. Like a player grabbing plates to craft chests.
          st.expanded[name] = true
          local pos = st.k
          for _, ing in pairs(recipe.ingredients) do
            if ing.type == "item" then
              local want = ing.amount * runs
              if c.get_item_count(ing.name) < want then
                st.need[ing.name] = math.max(st.need[ing.name] or 0, want)
                table.insert(st.items, pos, ing.name)  -- a later duplicate is skipped once it's in inventory
                pos = pos + 1
              end
            end
          end
          st.srcs = nil
          return nil
        end
        if not (runs and c.get_craftable_count(recipe) >= runs
              and c.begin_crafting { count = runs, recipe = recipe, silent = true } == runs) then
          local found = #st.srcs == 0 and ("no chest or machine output within " .. SUPPLY_RADIUS .. " tiles has any")
            or ("storage within " .. SUPPLY_RADIUS .. " tiles ran out")
          return fail("needs " .. n .. " " .. name .. " but you have " .. have .. "; " .. found
            .. ", and you can't hand-craft the other " .. (n - have) .. " from what you carry",
            { needed = n, have = have, item = name, took = st.took })
        end
        st.crafted[#st.crafted + 1] = (runs * per) .. " " .. name
        st.crafting = true
      end
    end
  end
  return true
end

-- What supply did, for a result message: "; took 10 x from chest at 1,2; crafted 4 y".
local function supply_note(job)
  local st = job.supply
  if not st then return "" end
  local out = ""
  if #st.took > 0 then out = out .. "; took " .. table.concat(st.took, ", ", 1, math.min(#st.took, 4)) end
  if #st.crafted > 0 then out = out .. "; crafted " .. table.concat(st.crafted, ", ") end
  return out
end

-- Whether a finished belt line joined anything at its ends, so nobody has to look: "; start: continues the belt at
-- 1,2; end: not joined, nearest belt 1 tile away at 5,6 (east)".
local function ends_note(a, job)
  local places = job.places
  if not (places and places[1] and prototypes.entity[job.item] and prototypes.entity[job.item].type == "transport-belt") then
    return ""
  end
  local surface, mine = a.char.surface, {}
  for _, pl in ipairs(places) do mine[math.floor(pl.pos.x) .. "," .. math.floor(pl.pos.y)] = true end
  local function ours(e) return mine[math.floor(e.position.x) .. "," .. math.floor(e.position.y)] end
  local function nearest(p)
    local best, bd
    for _, e in pairs(surface.find_entities_filtered { position = p, radius = 2.5, type = BELTS }) do
      local d = util.dist(e.position, p)
      if not ours(e) and (not bd or d < bd) then best, bd = e, d end
    end
    return best, bd
  end
  local first, last = places[1].pos, places[#places].pos
  local start
  if job.continues and job.continues.valid then
    start = "continues the belt at " .. xystr(job.continues.position)
  else
    for _, v in pairs(DIR_VEC) do
      local n = belt_at(surface, { x = first.x + v[1], y = first.y + v[2] })
      local nv = n and not ours(n) and DIR_VEC[n.direction]
      if nv and nv[1] == -v[1] and nv[2] == -v[2] then start = "fed by the " .. n.name .. " at " .. xystr(n.position) end
    end
  end
  local finish
  if job.join_into and job.join_into.valid then
    finish = "feeds the " .. job.join_into.name .. " at " .. xystr(job.join_into.position)
  else
    local e = belt_at(surface, last)
    local f = e and ahead(surface, e)
    if f and not ours(f) then
      finish = "feeds the " .. f.name .. " at " .. xystr(f.position)
    else
      local n, d = nearest(last)
      finish = n and ("not joined, nearest belt " .. math.floor(d + 0.5) .. " tile(s) away at " .. xystr(n.position)
        .. " (" .. (util.DIR_NAMES[n.direction] or "?") .. ")") or "open (no belt ahead)"
    end
  end
  return "; start: " .. (start or "new line") .. "; end: " .. finish
end

-- fetch: get `count` of an item into the inventory from the nearest storage (then hand-craft the rest).
H.fetch = {
  start = function(a, job)
    local name, count = job.args.item or job.args.name, tonumber(job.args.count) or 1
    if not (name and prototypes.item[name]) then return fail("unknown item " .. tostring(name)) end
    local have = a.char.get_item_count(name)
    if have >= count then return ok("already have " .. have .. " " .. name, { have = have }) end
    supply_start(job, { [name] = count })
    job.item, job.count = name, count
  end,
  tick = function(a, job)
    local r = supply_tick(a, job)
    if r == nil then return nil end
    if r ~= true then return r end
    local have = a.char.get_item_count(job.item)
    return ok("have " .. have .. " " .. job.item .. supply_note(job), { have = have })
  end,
}

local function new_job(op, args)
  local job = { id = storage.next_job_id, op = op, args = args }
  storage.next_job_id = storage.next_job_id + 1
  return job
end

-- Pole lines go by wire reach, not tile by tile: wires span belts, machines and water, so each hop is the free
-- spot within reach of the last pole that gets closest to the goal. An existing pole at either end is used as is.
-- Returns the positions to place (plus .first/.last for the span), or nil and why.
local function pole_hops(c, ent, from, to, free_tile)
  local s = c.surface
  local reach = 7.5
  pcall(function() reach = ent.get_max_wire_distance() end)
  local function pole_at(p)
    return s.find_entities_filtered { position = p, radius = 0.8, type = "electric-pole", force = c.force,
      limit = 1 }[1]
  end
  local function wire(e)
    local r = reach
    if e then pcall(function() r = math.min(r, e.prototype.get_max_wire_distance()) end) end
    return r - 0.05
  end
  -- 1x1 poles sit on tile centers, 2x2 ones on corners. By tile width: a small pole's collision box is only 0.3
  -- wide, which read as "even", so hops were picked on corners and the game then moved each pole up to 0.7 tiles
  -- further, past wire reach.
  local box = ent.collision_box
  local tw = math.floor(box.right_bottom.x - box.left_top.x + 0.999)
  pcall(function() tw = ent.tile_width end)
  local odd = tw % 2 == 1
  local function to_grid(v) return odd and (math.floor(v) + 0.5) or math.floor(v + 0.5) end
  local function placeable(p)
    return s.can_place_entity { name = ent.name, position = p, force = c.force,
      build_check_type = defines.build_check_type.manual }
  end
  local hops = {}
  local start_pole, goal_pole = pole_at(from), pole_at(to)
  local cur = start_pole and start_pole.position or free_tile(from)
  if not start_pole then hops[#hops + 1] = cur end
  local goal = goal_pole and goal_pole.position or free_tile(to)
  local first, seen = cur, {}
  for _ = 1, 200 do
    local d = util.dist(cur, goal)
    local r = wire(#hops == 0 and start_pole or nil)
    if d <= math.min(r, wire(goal_pole)) then
      if not goal_pole and d > 0.1 then hops[#hops + 1] = goal end
      hops.first, hops.last = first, goal
      return hops
    end
    -- Best free spot in reach: the one closest to the goal.
    local best, best_d
    local R = math.floor(r)
    for dx = -R, R do
      for dy = -R, R do
        local q = { x = to_grid(cur.x + dx), y = to_grid(cur.y + dy) }
        if util.dist(cur, q) <= r and not seen[q.x .. "," .. q.y] then
          local qd = util.dist(q, goal)
          if qd < d - 1 and (not best_d or qd < best_d - 0.01) and placeable(q) then best, best_d = q, qd end
        end
      end
    end
    if not best then
      return nil, "no free spot within wire reach (" .. string.format("%.1f", r) .. " tiles) of " .. xystr(cur)
        .. " that gets closer; pick a waypoint around the obstacle and connect in two legs"
    end
    seen[best.x .. "," .. best.y] = true
    hops[#hops + 1] = best
    cur = best
  end
  return nil, "too many poles (over 200); split the line"
end

-- Wire a finished pole line explicitly, end to end (start pole, new poles, goal pole): auto-connection on placement
-- sometimes skips a neighbour, which leaves the far end off the grid.
local function wire_line(surface, job)
  local it = prototypes.item[job.item]
  if not (it and it.place_result and it.place_result.type == "electric-pole") then return end
  local function pole_at(p, r)
    p = util.pos(p)
    return p and surface.find_entities_filtered { type = "electric-pole", position = p, radius = r }[1]
  end
  local chain = {}
  local s0 = job.args.from and pole_at(job.args.from, 1.5)
  if s0 then chain[#chain + 1] = s0 end
  for _, pl in ipairs(job.places) do
    local q = pole_at(pl.pos, 0.5)
    if q and q ~= chain[#chain] then chain[#chain + 1] = q end
  end
  local g = job.args.to and pole_at(job.args.to, 1.5)
  if g and g ~= chain[#chain] then chain[#chain + 1] = g end
  for i = 2, #chain do
    local x, y = chain[i - 1], chain[i]
    if x.valid and y.valid and x.electric_network_id ~= y.electric_network_id then
      pcall(function()
        local cx = x.get_wire_connector(defines.wire_connector_id.pole_copper, true)
        local cy = y.get_wire_connector(defines.wire_connector_id.pole_copper, true)
        cx.connect_to(cy, true)
      end)
    end
  end
end

-- A finished pole line: the first new pole that isn't on the same network as the existing pole at either end
-- (from, else to), or nil when it's all one grid (or no existing pole to compare with).
local function pole_gap(surface, job)
  local it = prototypes.item[job.item]
  if not (it and it.place_result and it.place_result.type == "electric-pole") then return nil end
  local function pole_at(p, r)
    p = util.pos(p)
    return p and surface.find_entities_filtered { type = "electric-pole", position = p, radius = r }[1]
  end
  local placed = {}
  for _, pl in ipairs(job.places) do placed[#placed + 1] = pole_at(pl.pos, 0.5) end
  local new = {}
  for _, q in ipairs(placed) do new[q] = true end
  local ref
  for _, end_ in ipairs { job.args.from, job.args.to } do
    local q = end_ and pole_at(end_, 1.5)
    if q and not new[q] and q.electric_network_id then ref = q break end
  end
  if not ref then return nil end
  for _, q in ipairs(placed) do
    if q.electric_network_id ~= ref.electric_network_id then return q end
  end
end

-- Route a belt / pipe / pole line between two points around obstacles, then queue the placements.
-- A machine's fluid port: the tile a pipe must take to join the machine's box for `fluid` (an output for a line's
-- start, an input for its end). Which side each fluid is on depends on rotation, and planners got it wrong (p1:
-- "refinery outlets mismatched with pipes (east=heavy, west=petroleum)", heavy oil never reaching the lube plant).
local PORT_TYPES = { "assembling-machine", "furnace", "boiler", "generator", "offshore-pump", "pump", "storage-tank",
  "mining-drill", "reactor", "heat-exchanger", "fluid-turret" }
local function fluid_port(surface, p, fluid, want_out, force)
  local best, bd
  for _, e in pairs(surface.find_entities_filtered { position = p, radius = 4, type = PORT_TYPES, force = force }) do
    local d = util.dist(e.position, p)
    if not bd or d < bd then best, bd = e, d end
  end
  if not best then return nil, "no machine with fluid connections near " .. xystr(p) end
  local fb = best.fluidbox
  local cands, seen = {}, {}
  for i = 1, #fb do
    local okP, pr = pcall(fb.get_prototype, i)
    if okP and pr and pr.object_name ~= "LuaFluidBoxPrototype" and pr[1] then pr = pr[1] end
    local kind = (okP and pr and pr.production_type) or "none"
    -- the fluid a recipe locked onto the box (empty until it flows), else its filter, else what it holds
    local okL, locked = pcall(fb.get_locked_fluid, i)
    local okF, flt = pcall(fb.get_filter, i)
    local name = (okL and locked) or (okF and flt and flt.name) or (fb[i] and fb[i].name) or nil
    if type(name) == "table" then name = name.name end
    seen[#seen + 1] = (name or "empty") .. " " .. kind
    local dir_ok = kind == "input-output" or kind == "none"
      or (want_out and kind == "output") or (not want_out and kind == "input")
    if dir_ok and (name == fluid or name == nil) then
      local okC, pcs = pcall(fb.get_pipe_connections, i)
      for _, pc in pairs(okC and pcs or {}) do
        if pc.target_position then cands[#cands + 1] = { pos = pc.target_position, exact = name == fluid } end
      end
    end
  end
  table.sort(cands, function(x, y) return (x.exact and 1 or 0) > (y.exact and 1 or 0) end)
  for _, cd in ipairs(cands) do
    local t = { x = math.floor(cd.pos.x) + 0.5, y = math.floor(cd.pos.y) + 0.5 }
    if surface.count_entities_filtered { area = { { t.x - 0.4, t.y - 0.4 }, { t.x + 0.4, t.y + 0.4 } }, limit = 1,
        invert = true, type = { "resource", "character", "corpse", "item-entity" } } == 0 then
      return t, best
    end
  end
  -- a pipe already on the port (empty, or holding this fluid): the line carries on from it (an offshore pump's
  -- first pipe was "already taken", and the line gave up)
  local there = {}
  for _, cd in ipairs(cands) do
    local t = { x = math.floor(cd.pos.x) + 0.5, y = math.floor(cd.pos.y) + 0.5 }
    local pipe = surface.find_entities_filtered { position = t, radius = 0.4, type = { "pipe", "pipe-to-ground" }, limit = 1 }[1]
    local held = pipe and pipe.fluidbox[1] and pipe.fluidbox[1].name
    if pipe and (not held or held == fluid) then return t, best, true end
    -- say what's in the way, so the plan can pick it up or route round it (q6 guessed at a stone wall that wasn't there)
    for _, o in pairs(surface.find_entities_filtered { position = t, radius = 0.4, limit = 2,
        type = { "resource", "character", "corpse", "item-entity" }, invert = true }) do
      local f = ""
      local okF, fb = pcall(function() return o.fluidbox end)
      if okF and fb and #fb >= 1 and fb[1] then f = " holding " .. fb[1].name end
      there[#there + 1] = o.name .. " at " .. xystr(o.position) .. f
    end
  end
  if #cands > 0 then
    return nil, best.name .. " at " .. xystr(best.position) .. ": its " .. fluid .. " connection"
      .. (#cands > 1 and "s are" or " is") .. " taken by " .. (#there > 0 and table.concat(there, ", ") or "something")
      .. ": pick that up (mine_at) and connect again, or join a pipe that carries " .. fluid
  end
  return nil, best.name .. " at " .. xystr(best.position) .. " has no " .. (want_out and "output" or "input")
    .. " for " .. fluid .. " (its boxes: " .. table.concat(seen, ", ") .. ")"
end

-- The fluid a pipe line will carry when none is named: what its start tile (else its end) holds or touches. With
-- it the route keeps clear of other fluids (c2: a 500-tile crude trunk laid as a plain pipe line joined the oil
-- field's refinery inlets and broke the site).
local function fluid_near(surface, p)
  local function names(pos, r)
    for _, n in pairs(surface.find_entities_filtered { position = pos, radius = r, limit = 6 }) do
      local okF, fb = pcall(function() return n.fluidbox end)
      -- only single-box things (pipes, tanks, pumps): a refinery or chemical plant holds several fluids, and which
      -- one the line is for has to be named (from_fluid / to_fluid)
      if okF and fb and #fb == 1 then
        local name = fb[1] and fb[1].name
        if not name then
          local okL, lk = pcall(fb.get_locked_fluid, 1)
          name = okL and lk or nil
        end
        if name then return name end
      end
    end
  end
  return names(p, 0.5) or names(p, 1.2)
end

-- the machine whose footprint holds p (the planner pointed at the machine itself), if any
local function machine_at(surface, p, force)
  for _, m in pairs(surface.find_entities_filtered { position = p, radius = 0.1, type = PORT_TYPES, force = force }) do
    return m
  end
end

H.connect = {
  start = function(a, job)
    local args, c = job.args, a.char
    local item = args.item or args.name or "transport-belt"
    local ent = prototypes.item[item] and prototypes.item[item].place_result
    if not ent then return fail(tostring(item) .. " is not placeable") end
    local from = util.pos(args.from or { args.from_x, args.from_y })
    local to = util.pos(args.to or { args.to_x, args.to_y })
    if not (from and from.x and to and to.x) then return fail("connect needs from=[x,y] and to=[x,y]") end
    local line_fluid = args.fluid or args.from_fluid or args.to_fluid
    if not line_fluid and ent.type == "pipe" then line_fluid = fluid_near(c.surface, from) or fluid_near(c.surface, to) end
    local port_keys, port_units = {}, {}
    if args.from_fluid or args.to_fluid then
      if ent.type ~= "pipe" then return fail("from_fluid / to_fluid are for pipe lines") end
      if args.from_fluid then
        local q, e = fluid_port(c.surface, from, args.from_fluid, true, c.force)
        if not q then return fail(e) end
        from = q
        port_keys[route.key(math.floor(q.x), math.floor(q.y))] = true
        if e.unit_number then port_units[e.unit_number] = true end
      end
      if args.to_fluid then
        local q, e = fluid_port(c.surface, to, args.to_fluid, false, c.force)
        if not q then return fail(e) end
        to = q
        port_keys[route.key(math.floor(q.x), math.floor(q.y))] = true
        if e.unit_number then port_units[e.unit_number] = true end
      end
    end
    -- an end on a machine, with the fluid known: that machine's port for it (its output at the start, its input at
    -- the end), the same as naming from_fluid / to_fluid
    if line_fluid and ent.type == "pipe" then
      if not args.from_fluid and machine_at(c.surface, from, c.force) then
        local q, e = fluid_port(c.surface, from, line_fluid, true, c.force)
        if q then
          from = q
          port_keys[route.key(math.floor(q.x), math.floor(q.y))] = true
          if e.unit_number then port_units[e.unit_number] = true end
        end
      end
      if not args.to_fluid and machine_at(c.surface, to, c.force) then
        local q, e = fluid_port(c.surface, to, line_fluid, false, c.force)
        if q then
          to = q
          port_keys[route.key(math.floor(q.x), math.floor(q.y))] = true
          if e.unit_number then port_units[e.unit_number] = true end
        end
      end
    end
    -- the machines the line runs between have other boxes too (a chemical plant's water inlet beside its acid one):
    -- those aren't walls for this line, or it can't reach the port (it stalled 2 tiles from a chemical plant)
    local function ignore_ends(pt, set)
      if not line_fluid then return end
      for _, m in pairs(c.surface.find_entities_filtered { position = pt, radius = 3, type = PORT_TYPES, force = c.force }) do
        local okF, fb = pcall(function() return m.fluidbox end)
        if okF and fb and m.unit_number then
          for i = 1, #fb do
            local okL, lk = pcall(fb.get_locked_fluid, i)
            local name = (okL and lk) or (fb[i] and fb[i].name)
            if name == line_fluid then set[m.unit_number] = true break end
          end
        end
      end
    end
    if util.dist(from, to) > 250 then return fail("too far to route in one go (max ~250 tiles); split it") end
    -- Endpoints often land on a machine edge; slide them to the nearest free tile.
    local function free_tile(p)
      for r = 0, 2 do
        for dx = -r, r do
          for dy = -r, r do
            if math.max(math.abs(dx), math.abs(dy)) == r then
              local q = { x = math.floor(p.x) + dx + 0.5, y = math.floor(p.y) + dy + 0.5 }
              -- (can_place_entity says yes over a belt it could fast-replace; the router treats that as a wall)
              if c.surface.can_place_entity { name = ent.name, position = q, force = c.force,
                    build_check_type = defines.build_check_type.manual }
                  and (ent.type ~= "electric-pole" or c.surface.count_entities_filtered {
                    area = { { q.x - 0.3, q.y - 0.3 }, { q.x + 0.3, q.y + 0.3 } }, limit = 1,
                    type = { "transport-belt", "underground-belt", "splitter" } } == 0)
                  and (ent.type == "electric-pole" or c.surface.count_entities_filtered {
                    area = { { q.x - 0.3, q.y - 0.3 }, { q.x + 0.3, q.y + 0.3 } }, invert = true, limit = 1,
                    type = { "resource", "character", "corpse", "item-entity", "entity-ghost", "tile-ghost" } } == 0)
              then return q end
            end
          end
        end
      end
      return p
    end
    local places, path = {}, nil
    if ent.type == "electric-pole" then
      local hops, err = pole_hops(c, ent, from, to, free_tile)
      if not hops then return fail("can't run " .. item .. " from " .. xystr(from) .. " to " .. xystr(to) .. ": " .. err) end
      for _, p in ipairs(hops) do places[#places + 1] = { pos = p } end
      path = { hops.first, hops.last, n = math.floor(util.dist(hops.first, hops.last) + 0.5) }
    else
      ignore_ends(from, port_units)
      ignore_ends(to, port_units)
      local ropts = { entity = ent.name, force = c.force, allow = {}, fluid = line_fluid, fluid_ignore = port_units }
      local fk, tk = route.key(math.floor(from.x), math.floor(from.y)), route.key(math.floor(to.x), math.floor(to.y))
      for k in pairs(port_keys) do ropts.allow[k] = true end -- a port tile is where the pipe must go: no sliding
      if ent.type == "transport-belt" then
        -- Endpoints name tiles: x,y and x.5,y.5 are the same tile (a bare corner would touch four belts).
        local function tile(p) return { x = math.floor(p.x) + 0.5, y = math.floor(p.y) + 0.5 } end
        -- Start on the last belt of a line: continue from it (it turns to face the new line).
        -- Start on an underground exit or a splitter: start on the tile it feeds.
        -- Start next to a dangling line end (an off-by-one start): continue that line.
        local s = belt_at(c.surface, tile(from))
        if not s then
          for _, v in pairs(DIR_VEC) do
            local n = belt_at(c.surface, { x = tile(from).x + v[1], y = tile(from).y + v[2] })
            local nv = n and n.type == "transport-belt" and DIR_VEC[n.direction]
            -- (a line end pointing at the start tile already feeds it as is)
            if nv and line_end(c.surface, n) and not (nv[1] == -v[1] and nv[2] == -v[2]) then
              s, from = n, n.position
              fk = route.key(math.floor(from.x), math.floor(from.y))
              break
            end
          end
        end
        if s and s.type == "transport-belt" and line_end(c.surface, s) then
          job.continues = s
          from, ropts.allow[fk] = s.position, true
          local feeder = feeder_of(c.surface, s)
          if feeder then ropts.start_forbid = { util.sign(feeder.x - s.position.x), util.sign(feeder.y - s.position.y) } end
        elseif s and s.type ~= "transport-belt" then
          local v = DIR_VEC[s.direction]
          if v and (s.type == "splitter" or s.belt_to_ground_type == "output") then
            from = { x = from.x + v[1], y = from.y + v[2] }
            fk = route.key(math.floor(from.x), math.floor(from.y))
          end
        end
        -- End on a belt: feed into it from behind or the side, never head-on, and leave it as it is.
        -- An end on a tile something else blocks, next to exactly one belt, means that belt.
        local e = belt_at(c.surface, tile(to))
        if not e and not c.surface.can_place_entity { name = ent.name, position = tile(to), force = c.force,
              build_check_type = defines.build_check_type.manual } then
          local near = {}
          for _, v in pairs(DIR_VEC) do
            near[#near + 1] = belt_at(c.surface, { x = tile(to).x + v[1], y = tile(to).y + v[2] })
          end
          if #near == 1 then e = near[1] end
        end
        local v = e and DIR_VEC[e.direction]
        if v then
          to, job.join_into = e.position, e
          tk = route.key(math.floor(to.x), math.floor(to.y))
          ropts.allow[tk], ropts.goal_join, ropts.goal_forbid = true, true, { -v[1], -v[2] }
        end
      end
      if not ropts.allow[fk] then from = free_tile(from) end
      if not job.join_into then to = free_tile(to) end
      -- Undergrounds when the way is blocked, if the force can make them (or the agent carries some).
      local hop
      local ug = ent.type == "transport-belt" and ent.related_underground_belt and ent.related_underground_belt.name
        or (ent.name == "pipe" and "pipe-to-ground") or nil
      if ug and args.underground ~= false and prototypes.entity[ug]
          and ((c.force.recipes[ug] and c.force.recipes[ug].enabled) or c.get_item_count(ug) > 0) then
        local reach = ent.type == "transport-belt" and prototypes.entity[ug].max_underground_distance or 10
        hop = { name = ug, reach = math.max(2, reach) }
      end
      ropts.hop = hop
      ropts.belt = ent.type == "transport-belt"
      local err
      path, err = route.find(c.surface, from, to, ropts)
      if not path then return fail("can't route " .. item .. ": " .. err) end
      if job.join_into then path[#path] = nil end -- the belt it feeds is already there
      if #path == 0 then return ok("already connected: " .. xystr(from) .. " is next to the belt it feeds") end
      local SIGN = function(v) return v > 0 and 1 or (v < 0 and -1 or 0) end
      for i, p in ipairs(path) do
        local dir
        if p.ug then
          local travel = VEC_DIR[p.dir[1] .. "," .. p.dir[2]]
          -- Underground belts face the travel direction at both ends; a pipe-to-ground faces its above-ground side.
          dir = (ug == "pipe-to-ground" and p.ug == "input") and util.opposite(travel) or travel
          places[#places + 1] = { pos = p, dir = dir, item = ug, ug = p.ug }
        else
          if ent.supports_direction then
            local nxt = path[i + 1] or (job.join_into and job.join_into.position)
            if nxt then
              dir = VEC_DIR[SIGN(nxt.x - p.x) .. "," .. SIGN(nxt.y - p.y)]
            else
              dir = args.end_direction or (places[#places] and places[#places].dir) or "north"
            end
          end
          places[#places + 1] = { pos = p, dir = dir }
        end
      end
      path.n = #path
    end

    -- Don't silently feed a teammate's belt: check what the last tile points into and what points into the first.
    if ent.type == "transport-belt" and not args.join and not job.join_into and #places > 0 then
      local function foreign_belt_at(p)
        for _, e in pairs(c.surface.find_entities_filtered { position = p, radius = 0.3,
          type = { "transport-belt", "underground-belt", "splitter" } }) do
          local who = e.unit_number and storage.built_by[e.unit_number]
          if who ~= a.name then return e, who or (e.last_user and e.last_user.name) or "someone" end
        end
      end
      local last = places[#places]
      local d = last.dir and defines.direction[last.dir]
      local step = d and ({ [defines.direction.north] = { 0, -1 }, [defines.direction.south] = { 0, 1 },
        [defines.direction.east] = { 1, 0 }, [defines.direction.west] = { -1, 0 } })[d]
      if step then
        local e, who = foreign_belt_at({ x = last.pos.x + step[1], y = last.pos.y + step[2] })
        if e then
          return fail("this line would feed into " .. who .. "'s belt at " .. xystr(e.position)
            .. "; pick another end point, or pass join=true if that's intended")
        end
      end
    end
    local need = {}
    for _, pl in ipairs(places) do
      -- A belt already there only gets turned; it needs no item.
      local here = pl.item == nil and ent.type == "transport-belt" and belt_at(c.surface, pl.pos)
      if not (here and here.name == item) then need[pl.item or item] = (need[pl.item or item] or 0) + 1 end
    end
    for name, n in pairs(need) do
      -- Short: fetch the rest from storage, then hand-craft what's still missing, like a player would.
      if c.get_item_count(name) < n and not job.supply then supply_start(job, need) end
      if name ~= item then job.under = " incl. " .. n .. " " .. name .. " to pass under what's in the way" end
    end
    -- Place every piece inside this job, so the result says what actually got built (not just what was planned).
    job.places, job.i, job.placed, job.failed = places, 1, 0, {}
    job.item, job.span = item, { util.xy(path[1]), util.xy(path[#path]), path.n }
    if #places == 0 then
      return ok("already connected: the " .. item .. "s at both ends are within wire reach", { placed = 0, planned = 0 })
    end
  end,
  tick = function(a, job)
    if job.supply and not job.supplied then
      local r = supply_tick(a, job)
      if r == nil then return nil end
      if r ~= true then
        r.msg = "route " .. r.msg
        return r
      end
      job.supplied = true
    end
    local pl = job.places[job.i]
    if not pl then
      local span = "from " .. job.span[1][1] .. "," .. job.span[1][2] .. " to " .. job.span[2][1] .. "," .. job.span[2][2]
      local data = { placed = job.placed, planned = #job.places, failed = job.failed }
      if #job.failed == 0 and job.places[1] then pcall(wire_line, a.char.surface, job) end
      local gap = #job.failed == 0 and job.places[1] and pole_gap(a.char.surface, job)
      if gap then
        return fail("placed all " .. job.placed .. " " .. job.item .. " " .. span .. ", but the line doesn't reach the "
          .. "grid at its other end: the pole at " .. xystr(gap.position) .. " isn't wired to it (a hop is too long "
          .. "or blocked; add a pole between)", data)
      end
      if #job.failed == 0 then
        return ok("placed all " .. job.placed .. " " .. job.item .. (job.under or "") .. " (" .. job.span[3]
          .. " tiles) " .. span .. ends_note(a, job) .. supply_note(job), data)
      end
      return fail("placed " .. job.placed .. " of " .. #job.places .. " " .. job.item .. " " .. span .. "; failed: "
        .. table.concat(job.failed, "; ", 1, math.min(#job.failed, 3)), data)
    end
    local sub = job.sub
    if not sub then
      -- the first piece may go where the line we continue ends (an underground or splitter replacing that belt)
      local cont = job.i == 1 and job.continues and job.continues.valid
        and util.dist(job.continues.position, pl.pos) < 0.1
      sub = { id = job.id, op = "place", args = { name = pl.item or job.item, x = pl.pos.x, y = pl.pos.y,
        direction = pl.dir, type = pl.ug, replace_belt = cont or nil } }
      job.sub = sub
      local r = H.place.start(a, sub)
      if r then
        if r.ok then job.placed = job.placed + 1 else job.failed[#job.failed + 1] = r.msg end
        job.sub, job.i = nil, job.i + 1
      end
      return nil
    end
    local r = H.place.tick(a, sub)
    if r then
      if r.ok then job.placed = job.placed + 1 else job.failed[#job.failed + 1] = r.msg end
      job.sub, job.i = nil, job.i + 1
    end
    return nil
  end,
}

-- Stay near a player or agent until cancelled (or `seconds` pass, default 5 minutes).
H.follow = {
  start = function(a, job)
    job.until_tick = game.tick + math.min(job.args.seconds or 300, 1800) * 60
    job.dist = job.args.distance or 3
  end,
  tick = function(a, job)
    if game.tick >= job.until_tick then return ok("stopped following (time up)") end
    local target
    if job.args.player then
      local p = util.find_player(job.args.player)
      if not (p and p.connected) then return fail("player " .. job.args.player .. " is not online") end
      if p.surface ~= a.char.surface then return fail(job.args.player .. " is on another surface") end
      target = p.position
    elseif job.args.agent then
      local o = storage.agents[job.args.agent]
      if not (o and agents.alive(o)) then return fail("agent " .. job.args.agent .. " not found") end
      target = o.char.position
    else
      return fail("follow needs player or agent")
    end
    local d = util.dist(a.char.position, target)
    if d <= job.dist then
      if job.move then movement.stop(a.char) job.move = nil end
      return nil
    end
    if not job.move or util.dist(job.move.goal, target) > 3 then
      job.move = { goal = { x = target.x, y = target.y }, radius = job.dist }
    end
    local r = movement.tick(a.char, job.move)
    if r and r ~= "arrived" then job.move = nil end -- retry next tick from wherever we are
    return nil
  end,
}

------------------------------------------------------------------------- ghosts / blueprints / loot
local function ghost_item(g)
  for _, it in pairs(g.ghost_prototype.items_to_place_this or {}) do return it.name, it.count or 1 end
end

-- Ghosts on the agent's force in an area, nearest first.
local function find_ghosts(a, args)
  local c = a.char
  local center = util.pos(args.position or (args.x and { args.x, args.y })) or c.position
  local list
  if args.zone then  -- an order's zone: exactly that rectangle
    local z = args.zone
    list = c.surface.find_entities_filtered { type = "entity-ghost", force = c.force,
      area = { { math.min(z[1], z[3]), math.min(z[2], z[4]) }, { math.max(z[1], z[3]), math.max(z[2], z[4]) } } }
  else
    list = c.surface.find_entities_filtered { type = "entity-ghost", force = c.force, position = center,
      radius = math.min(args.radius or 32, 128) }
  end
  table.sort(list, function(x, y) return util.dist(x.position, c.position) < util.dist(y.position, c.position) end)
  return list, center
end

-- Build ghosts (a human's plan, a blueprint, or an architect layout) with items from inventory.
H.build_ghosts = {
  start = function(a, job) job.built, job.skip, job.last_event = 0, {}, game.tick end,
  tick = function(a, job)
    local c, args = a.char, job.args
    local g = job.target
    if game.tick - job.last_event > 7200 then
      -- two minutes with nothing built or skipped: give up on this ghost and say which (small builds ran into
      -- the 600 s timeout twice in a row, with nothing to show what they were stuck on)
      job.stalls = (job.stalls or 0) + 1
      local what = (g and g.valid) and (g.ghost_name .. " at " .. xystr(g.position)) or "the next ghost"
      job.stuck_on = what
      if g and g.valid then job.skip[g.unit_number] = true end
      job.target, job.move, job.side, job.clearing, job.stepped = nil, nil, nil, nil, nil
      job.last_event = game.tick
      if job.stalls >= 3 then
        return fail("built " .. job.built .. " ghosts, then got nowhere for 2 minutes three times (last on " .. what
          .. ")", { built = job.built })
      end
      g = nil
    end
    if not (g and g.valid) then
      job.target, job.move = nil, nil
      local missing = {}
      local list = find_ghosts(a, args)
      for _, cand in ipairs(list) do
        if not job.skip[cand.unit_number] then
          local item, n = ghost_item(cand)
          if item and (util.cheat() or c.get_item_count(item) >= n) then
            g = cand
            break
          elseif item then
            missing[item] = (missing[item] or 0) + n
          end
        end
      end
      if not g then
        local left = 0
        for _, cand in ipairs(list) do if not job.skip[cand.unit_number] then left = left + 1 end end
        local trees = job.cleared and (" (cleared " .. job.cleared .. " trees/rocks in the way)") or ""
        local stuck = job.stuck_on and ("; gave up on " .. job.stuck_on .. " after 2 minutes stuck") or ""
        if left == 0 then return ok("built " .. job.built .. " ghosts" .. trees .. "; none left here" .. stuck, { built = job.built }) end
        return ok("built " .. job.built .. " ghosts; " .. left .. " left need items you don't have" .. stuck,
          { built = job.built, left = left, missing = missing })
      end
      if args.limit and job.built >= args.limit then return ok("built " .. job.built .. " ghosts", { built = job.built }) end
      job.target = g
    end
    local near = approach(a, job, g.position, c.build_distance - 0.5)
    if near == nil then return nil end
    if type(near) == "table" then
      job.skip[g.unit_number] = true
      job.target = nil
      job.last_event = game.tick
      return nil
    end
    if job.clearing then
      local cleared, why = finish_clearing(c, job.clearing)
      if cleared == nil then return nil end
      job.clearing = nil
      if not cleared then return fail(why .. " to build ghosts", { built = job.built }) end
      job.cleared = (job.cleared or 0) + cleared
      job.last_event = game.tick
    end
    local item, n = ghost_item(g)
    local name, pos = g.ghost_name, g.position
    local _, ent = g.revive { raise_revive = true }
    if not ent and g.valid and job.clear_tried ~= g.unit_number then
      -- Trees or rocks in its footprint: clear them, then try again.
      job.clear_tried = g.unit_number
      local bb = g.bounding_box
      job.clearing = begin_clearing(c, { { bb.left_top.x, bb.left_top.y }, { bb.right_bottom.x, bb.right_bottom.y } })
      if job.clearing then return nil end
    end
    if not ent then
      -- Usually we're standing on it: step aside once, else skip it.
      if not job.stepped then
        job.stepped = true
        job.side = { goal = { x = pos.x + 2.5, y = pos.y + 2.5 }, radius = 0.5 }
      end
      if job.side then
        local r = movement.tick(c, job.side)
        if r == nil then return nil end
        job.side = nil
        return nil
      end
      job.skip[g.unit_number] = true
      job.target, job.stepped = nil, nil
      job.last_event = game.tick
      return nil
    end
    job.stepped = nil
    job.last_event = game.tick
    if not util.cheat() and item then c.remove_item { name = item, count = n } end
    if ent.unit_number then storage.built_by[ent.unit_number] = a.name end
    triggers.note(c.force, c.surface, "build-entity", name, 1)
    job.built = job.built + 1
    job.target = nil
    return nil
  end,
}

-- Lay ghosts from a blueprint string, or from an explicit layout {name, x, y, direction, recipe}. Instant, like
-- a player placing a blueprint; then build_ghosts (by anyone) turns them into buildings.
local function needed_items(ghosts)
  local need = {}
  for _, g in pairs(ghosts) do
    if g.valid then
      local item, n = ghost_item(g)
      if item then need[item] = (need[item] or 0) + n end
    end
  end
  return need
end

-- Underground belts in a layout need to be an entrance ("input") or exit ("output"); a layout that leaves it out
-- would otherwise get two entrances that leak onto whatever is past them. Unspecified ones pair up like a player
-- places them: walking in their direction, the first is the entrance and the next one within reach is the exit.
local function pair_undergrounds(entities)
  local out, open = {}, {}
  local DV = { north = { 0, -1 }, south = { 0, 1 }, east = { 1, 0 }, west = { -1, 0 } }
  for i, e in ipairs(entities) do
    local item = prototypes.item[e.name or ""]
    local ent = item and item.place_result or prototypes.entity[e.name or ""]
    if ent and ent.type == "underground-belt" then
      if e.type == "input" or e.type == "output" then
        out[i] = e.type
      else
        open[#open + 1] = { i = i, x = e.x or e[1], y = e.y or e[2], d = util.DIR_NAMES[util.parse_dir(e.direction)] or "north",
          reach = ent.max_underground_distance or 5 }
      end
    end
  end
  -- upstream first, so an exit is never mistaken for an entrance with nothing ahead of it
  local function progress(u) local dv = DV[u.d] or { 0, 0 } return u.x * dv[1] + u.y * dv[2] end
  table.sort(open, function(p, q) return progress(p) < progress(q) end)
  for _, u in ipairs(open) do
    if not out[u.i] then
      local v, best = nil, math.huge
      local dv = DV[u.d]
      for _, w in ipairs(open) do
        if w ~= u and not out[w.i] and w.d == u.d and dv then
          local dx, dy = w.x - u.x, w.y - u.y
          local ahead = dx * dv[1] + dy * dv[2]
          local side = math.abs(dx * dv[2]) + math.abs(dy * dv[1])
          if side < 0.1 and ahead > 0 and ahead <= u.reach + 1 and ahead < best then v, best = w, ahead end
        end
      end
      if v then out[u.i], out[v.i] = "input", "output" else out[u.i] = "input" end
    end
  end
  return out
end

-- Things that can swap for each other in place (the game's fast-replace), so a ghost may go on top of one.
local BELTISH = { ["transport-belt"] = true, ["underground-belt"] = true, splitter = true, loader = true,
  ["loader-1x1"] = true, ["lane-splitter"] = true }
local PIPEISH = { pipe = true, ["pipe-to-ground"] = true }
local NOT_SOLID = { character = true, ["entity-ghost"] = true, ["tile-ghost"] = true, ["item-request-proxy"] = true,
  ["highlight-box"] = true, ["item-entity"] = true, corpse = true, ["character-corpse"] = true, ["deconstructible-tile-proxy"] = true }

local function same_family(proto, o)
  local a, b = proto.type, o.type
  if (BELTISH[a] and BELTISH[b]) or (PIPEISH[a] and PIPEISH[b]) then return true end
  local g = proto.fast_replaceable_group
  return g ~= nil and g ~= "" and g == o.prototype.fast_replaceable_group
end

-- A built thing of ours in the ghost's footprint that the ghost can't replace (create_entity places ghosts without
-- checking, so such a ghost could never be built). Trees and rocks don't count: the builder clears those.
local function ghost_conflict(c, ename, p, dir)
  local proto = prototypes.entity[ename]
  if not proto then return nil end
  local b = proto.collision_box
  local w, h = b.right_bottom.x - b.left_top.x, b.right_bottom.y - b.left_top.y
  if dir == defines.direction.east or dir == defines.direction.west then w, h = h, w end
  local area = { { p.x - w / 2 + 0.05, p.y - h / 2 + 0.05 }, { p.x + w / 2 - 0.05, p.y + h / 2 - 0.05 } }
  for _, o in ipairs(c.surface.find_entities_filtered { area = area, force = c.force }) do
    if o.valid and not NOT_SOLID[o.type] and not o.to_be_deconstructed() and not same_family(proto, o) then
      return "blocked by " .. o.name .. "@" .. o.position.x .. "," .. o.position.y
    end
  end
end

-- Why a ghost couldn't go at p: "same" when an identical entity (or ghost) already stands there (nothing to do),
-- else what blocks it.
local function ghost_blocker(c, ename, p, dir)
  local s = c.surface
  local here = s.find_entities_filtered { area = { { p.x - 0.45, p.y - 0.45 }, { p.x + 0.45, p.y + 0.45 } } }
  local names = {}
  for _, o in ipairs(here) do
    if o.valid and o.type ~= "character" then
      local oname = o.name == "entity-ghost" and o.ghost_name or o.name
      if oname == ename and (dir == nil or o.direction == dir) then
        return { name = ename, x = p.x, y = p.y, why = "same" }
      end
      -- the same thing facing another way: a player placing over it just turns it (not undergrounds: that flips them)
      if o.name == ename and dir ~= nil and o.type ~= "underground-belt" and o.supports_direction then
        return { name = ename, x = p.x, y = p.y, why = "turn", direction = util.DIR_NAMES[dir] }
      end
      local n = o.name == "entity-ghost" and ("ghost of " .. o.ghost_name) or o.name
      local proto = prototypes.entity[ename]
      if o.name ~= "entity-ghost" and proto and same_family(proto, o) then
        return { name = ename, x = p.x, y = p.y, why = "a " .. o.name .. " already stands at " .. o.position.x .. ","
          .. o.position.y .. " (to turn it use rotate; to swap it, mine_at it first)" }
      end
      names[#names + 1] = n .. "@" .. o.position.x .. "," .. o.position.y
      if #names >= 2 then break end
    end
  end
  local why = #names > 0 and ("blocked by " .. table.concat(names, ", ")) or nil
  if not why then
    local okw, wet = pcall(function() return s.get_tile(p.x, p.y).collides_with("water_tile") end)
    why = (okw and wet) and "water" or "invalid spot or too big for the gap"
  end
  return { name = ename, x = p.x, y = p.y, why = why }
end

H.blueprint = {
  start = function(a, job)
    local c, args = a.char, job.args
    local ghosts, why = {}, {}
    local existing = 0 -- entries already standing there, identical
    if args.string then
      local inv = game.create_inventory(1)
      local stack = inv[1]
      stack.set_stack { name = "blueprint" }
      local res = stack.import_stack(args.string)
      if res ~= 0 or not stack.is_blueprint or not stack.is_blueprint_setup() then
        inv.destroy()
        return fail("that's not a valid single-blueprint string")
      end
      local pos = util.pos(args.position or { args.x, args.y })
      if not (pos and pos.x) then inv.destroy() return fail("blueprint needs x,y") end
      ghosts = stack.build_blueprint { surface = c.surface, force = c.force, position = pos,
        direction = util.parse_dir(args.direction), build_mode = defines.build_mode.forced, raise_built = true }
      inv.destroy()
    elseif args.entities then
      local failed = 0
      local ug_type = pair_undergrounds(args.entities)
      for i, e in ipairs(args.entities) do
        local item = prototypes.item[e.name or ""]
        local ent = item and item.place_result
        local ename = ent and ent.name or e.name
        local p = { x = e.x or e[1], y = e.y or e[2] }
        local spec = { name = "entity-ghost", inner_name = ename, position = p, direction = util.parse_dir(e.direction),
          force = c.force, expires = false, type = ug_type[i] }
        -- the very same thing already standing there (a design laid again over itself): nothing to plan; a ghost on
        -- top of it could never be built. Its recipe is set if the design wants another.
        local same
        if p.x and p.y then
          for _, o in ipairs(c.surface.find_entities_filtered { name = ename, force = c.force,
            area = { { p.x - 0.1, p.y - 0.1 }, { p.x + 0.1, p.y + 0.1 } } }) do
            if o.valid and math.abs(o.position.x - p.x) < 0.1 and math.abs(o.position.y - p.y) < 0.1
                and (not o.supports_direction or e.direction == nil or o.direction == spec.direction)
                and (not ug_type[i] or o.type ~= "underground-belt" or o.belt_to_ground_type == ug_type[i]) then
              same = o
              break
            end
          end
        end
        local okc, conflict = pcall(ghost_conflict, c, ename, p, spec.direction)
        local okp, g
        if same then
          existing = existing + 1
          if e.recipe and same.type == "assembling-machine" then
            pcall(function()
              local r = same.get_recipe()
              if not r or r.name ~= e.recipe then same.set_recipe(e.recipe) end
            end)
          end
          okp = "same"
        elseif okc and conflict then
          okp, g = true, nil
        else
          okp, g = pcall(c.surface.create_entity, spec)
        end
        if okp == "same" then
          -- already built
        elseif okp and g then
          if e.recipe then pcall(function() g.set_recipe(e.recipe) end) end
          ghosts[#ghosts + 1] = g
        else
          failed = failed + 1
          if #why < 8 and p.x and p.y then
            why[#why + 1] = (okc and conflict) and { name = ename, x = p.x, y = p.y, why = conflict }
              or ghost_blocker(c, ename, p, spec.direction)
          end
        end
      end
      if failed > 0 and #ghosts == 0 and existing == 0 then
        return fail("no ghosts placed (" .. failed .. " invalid entries)", { failed = why })
      end
    else
      return fail("blueprint needs string=<blueprint string> + x,y, or entities=[{name,x,y,direction}]")
    end
    local need = needed_items(ghosts)
    return ok("placed " .. #ghosts .. " ghosts" .. (existing > 0 and (" (" .. existing .. " already built there)") or "")
      .. "; to build them you need " .. helpers.table_to_json(need)
      .. " (then use build_ghosts)", { ghosts = #ghosts, existing = existing, needs = need, failed = why })
  end,
}

-- Remove planned buildings (ghosts) in an area, like a deconstruction planner on ghosts: instant, no walking.
-- Human players' ghosts are their plans, so those stay unless asked (force=true).
H.clear_ghosts = {
  start = function(a, job)
    local c, args = a.char, job.args
    local center = util.pos(args.position or (args.x and { args.x, args.y }))
    if not (center and center.x) then return fail("clear_ghosts needs x,y (and radius, default 8)") end
    local list = c.surface.find_entities_filtered { type = "entity-ghost", force = c.force, position = center,
      radius = math.min(args.radius or 8, 64) }
    local removed, kept = 0, 0
    for _, g in pairs(list) do
      if g.valid and (not args.name or g.ghost_name == args.name) then
        local human = g.last_user and g.last_user.valid  -- agents build by script, so any last_user is a person
        if human and not args.force then
          kept = kept + 1
        else
          g.destroy()
          removed = removed + 1
        end
      end
    end
    return ok("removed " .. removed .. " ghosts" .. (kept > 0 and ("; kept " .. kept .. " placed by a human (force=true to remove)") or ""),
      { removed = removed, kept = kept })
  end,
}

-- Take everything back from the nearest character corpse (yours after dying).
H.loot = {
  start = function(a, job)
    local c = a.char
    local p = util.pos(job.args.position or (job.args.x and { job.args.x, job.args.y })) or c.position
    local list = c.surface.find_entities_filtered { type = "character-corpse", position = p, radius = 256 }
    table.sort(list, function(x, y) return util.dist(x.position, p) < util.dist(y.position, p) end)
    job.target = list[1]
    if not job.target then return fail("no corpse nearby") end
  end,
  tick = function(a, job)
    local c, e = a.char, job.target
    if not e.valid then return fail("corpse is gone") end
    local near = approach(a, job, e.position, c.reach_distance - 0.5)
    if near == nil then return nil end
    if type(near) == "table" then return near end
    local taken = 0
    for i = 1, e.get_max_inventory_index() do
      local inv = e.get_inventory(i)
      if inv and inv.valid then
        for name, n in pairs(util.contents(inv)) do
          if not name:find("@") then
            local got = c.insert { name = name, count = n }
            if got > 0 then inv.remove { name = name, count = got } taken = taken + got end
          end
        end
      end
    end
    local left = 0
    for i = 1, e.get_max_inventory_index() do
      local inv = e.get_inventory(i)
      if inv and inv.valid then left = left + inv.get_item_count() end
    end
    if left == 0 then e.destroy() end
    return ok("looted " .. taken .. " items" .. (left > 0 and (", " .. left .. " left (inventory full)") or ""))
  end,
}

---------------------------------------------------------------------- engine
local function finish(a, job, res)
  local h = H[job.op]
  if h and h.finish then pcall(h.finish, a, job) end
  if agents.alive(a) then movement.stop(a.char) end
  res.id, res.op, res.tick = job.id, job.op, game.tick
  local out = a.results
  out[#out + 1] = res
  if #out > 200 then table.remove(out, 1) end
  a.job = nil
  if not res.ok and job.stop_on_fail == true then
    for _, q in ipairs(a.queue) do
      out[#out + 1] = { id = q.id, op = q.op, ok = false, msg = "skipped: earlier job " .. job.id .. " failed", tick = game.tick }
    end
    a.queue = {}
  end
end

function jobs.enqueue(a, actions, replace)
  if replace then jobs.cancel(a, "replaced") end
  local ids = {}
  for _, act in ipairs(actions) do
    local op = act.op or act.action
    if not H[op] then error("unknown action op '" .. tostring(op) .. "'") end
    local job = { id = storage.next_job_id, op = op, args = act, stop_on_fail = act.stop_on_fail }
    storage.next_job_id = storage.next_job_id + 1
    a.queue[#a.queue + 1] = job
    ids[#ids + 1] = job.id
  end
  return ids
end

-- Cancel the agent's running job and everything queued, or (only = a job id) just that one job: a caller that gave
-- up on its own job must not take down another task's job that happens to be running (p2: a restock insert that
-- had waited behind a 5-minute hand-crafting fetch would have cancelled the fetch and all queued work).
-- Returns "running" or "queued" for a single job, nil if it wasn't there (already finished).
function jobs.cancel(a, why, only)
  local reason = "cancelled" .. (why and (": " .. why) or "")
  if only then
    only = tonumber(only)
    if a.job and a.job.id == only then
      finish(a, a.job, fail(reason))
      if agents.alive(a) then
        movement.stop(a.char)
        a.char.mining_state = { mining = false }
      end
      return "running"
    end
    for i, q in ipairs(a.queue) do
      if q.id == only then
        table.remove(a.queue, i)
        a.results[#a.results + 1] = { id = q.id, op = q.op, ok = false, msg = reason, tick = game.tick }
        return "queued"
      end
    end
    return nil
  end
  if a.job then finish(a, a.job, fail(reason)) end
  for _, q in ipairs(a.queue) do
    a.results[#a.results + 1] = { id = q.id, op = q.op, ok = false, msg = "cancelled", tick = game.tick }
  end
  a.queue = {}
  if agents.alive(a) then
    movement.stop(a.char)
    a.char.mining_state = { mining = false }
  end
end

local MAX_JOB_TICKS = 20 * 60 * 60  -- 20 minutes: the longest a caller waits is the plan's 15-minute builds

local function run(fn, a, job)
  local okk, res = pcall(fn, a, job)
  if not okk then return fail("error: " .. tostring(res)) end
  return res
end

-- Hand-crafts by playerless characters don't count natively. Diff each agent's crafting queue and credit
-- whatever left it (waited or background crafts alike).
account_crafts = function(a)
  local c = a.char
  local now = {}
  for _, item in pairs(c.crafting_queue or {}) do now[item.recipe] = (now[item.recipe] or 0) + item.count end
  local prev = a.craft_snap or {}
  for recipe, n in pairs(prev) do
    local done = n - (now[recipe] or 0)
    if done > 0 then
      local r = prototypes.recipe[recipe]
      local prod = r and r.products[1]
      if prod and prod.type == "item" then
        triggers.note(c.force, c.surface, "craft-item", prod.name, done * (prod.amount or 1))
      end
    end
  end
  a.craft_snap = now
end

function jobs.tick()
  local tick30 = game.tick % 30 == 0
  for _, a in pairs(storage.agents) do
    if agents.alive(a) then
      local st = a.stats
      if not st then
        st = { busy_ticks = 0, idle_ticks = 0, crafting_ticks = 0 }
        a.stats = st
      end
      if a.job or #a.queue > 0 then st.busy_ticks = st.busy_ticks + 1 else st.idle_ticks = st.idle_ticks + 1 end
      if a.char.crafting_queue_size > 0 then st.crafting_ticks = st.crafting_ticks + 1 end
      if tick30 then
        account_crafts(a)
        -- the map generates and charts around a player as they walk; a script character gets neither, so the
        -- serf could walk 240 tiles out and still find no crude oil ("that area isn't generated yet"). Do for it
        -- what the game does for a player: on entering a new chunk, generate and chart 3 chunks around. Charting
        -- skips chunks that aren't generated yet, so chart again 2 s later, once the new ones exist. (Charting only
        -- runs while a player is connected; the generation is what find and the pathfinder need.)
        local p = a.char.position
        local cx, cy = math.floor(p.x / 32), math.floor(p.y / 32)
        local moved = a.chunk_x ~= cx or a.chunk_y ~= cy
        if moved or (a.chart_at and game.tick >= a.chart_at) then
          a.chart_at = moved and game.tick + 120 or nil
          a.chunk_x, a.chunk_y = cx, cy
          pcall(function()
            if moved then a.char.surface.request_to_generate_chunks(p, 3) end
            a.char.force.chart(a.char.surface, { { p.x - 96, p.y - 96 }, { p.x + 96, p.y + 96 } })
          end)
        end
      end
      -- Start as many instant jobs as possible this tick; stop at the first long one.
      local guard = 0
      while not a.job and #a.queue > 0 and guard < 20 do
        guard = guard + 1
        local job = table.remove(a.queue, 1)
        job.started_tick = game.tick
        a.job = job
        local h = H[job.op]
        local res = h.start and run(h.start, a, job)
        if res then finish(a, job, res)
        elseif not h.tick then finish(a, job, ok("done")) end
      end
      local job = a.job
      if job and game.tick - (job.started_tick or game.tick) > MAX_JOB_TICKS then
        -- nobody is waiting on a job this old: its caller gave up without cancelling it, and every action queued
        -- behind it times out (yellow-blk-r4: a fetch of 4 assemblers ran 41 minutes; ~9 h of queue timeouts in all)
        jobs.cancel(a, "ran " .. math.floor(MAX_JOB_TICKS / 3600) .. " minutes without finishing", job.id)
      elseif job then
        local res = run(H[job.op].tick, a, job)
        if res then finish(a, job, res) end
      end
    end
  end
end

-- A few words for a job ("fetch pipe 557", "insert electronic-circuit 200 at -65.5,-19.5").
local function job_what(job)
  local args, parts = job.args or {}, { job.op }
  local item = args.item or args.name or args.recipe
  if type(item) == "string" then parts[#parts + 1] = item end
  if args.count then parts[#parts + 1] = tostring(args.count) end
  if args.x and args.y then parts[#parts + 1] = "at " .. tostring(args.x) .. "," .. tostring(args.y) end
  return table.concat(parts, " ")
end

function jobs.describe(job)
  if not job then return nil end
  local d = { id = job.id, op = job.op, secs = math.floor((game.tick - (job.started_tick or game.tick)) / 60),
    what = job_what(job) }
  if job.move then d.walking_to = util.xy(job.move.goal) end
  if job.got then d.got = job.got end
  return d
end

-- Research queue changes without a character (the foreman): same rules as the research action.
function jobs.research_direct(args)
  return H.research.start({ char = { force = game.forces.player } }, { args = args })
end

return jobs
