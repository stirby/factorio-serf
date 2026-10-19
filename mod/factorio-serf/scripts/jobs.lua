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
      if e.minable and e.type ~= "character" and e.prototype.mineable_properties.minable then
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

local function first_product(e)
  for _, p in pairs(e.prototype.mineable_properties.products or {}) do
    if p.type == "item" then return p.name end
  end
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
        return fail("nothing minable at " .. tostring(args.x) .. "," .. tostring(args.y))
      end
      job.searched = true
      e = find_mine_target(a, args)
      job.target, job.move, job.no_progress = e, nil, 0
      if not e then
        if job.got > 0 then
          return ok("mined " .. job.got .. ", no more " .. (args.name or "") .. " nearby", { mined = job.got })
        end
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

    c.update_selected_entity(e.position)
    if c.selected ~= e then c.selected = e end
    c.mining_state = { mining = true, position = e.position }
    local prog = c.character_mining_progress
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

H.craft = {
  start = function(a, job)
    local args, c = job.args, a.char
    local recipe = c.force.recipes[args.recipe or ""]
    if not recipe then return fail("unknown recipe " .. tostring(args.recipe)) end
    if not recipe.enabled then
      return fail("recipe " .. recipe.name .. " is locked; see techs for what unlocks it")
    end
    local count = args.count or 1
    local first = recipe.products[1]
    if util.cheat() then
      local inserted = c.insert { name = first.name, count = (first.amount or 1) * count }
      return ok("crafted " .. inserted .. " " .. first.name)
    end
    local craftable = c.get_craftable_count(recipe)
    if craftable == 0 then
      return fail("cannot craft " .. recipe.name .. ": missing ingredients",
        { missing = missing_for(a, recipe, count), category = recipe.category })
    end
    local n = math.min(count, craftable)
    local started = c.begin_crafting { count = n, recipe = recipe, silent = true }
    if started == 0 then
      return fail("cannot hand-craft " .. recipe.name .. " (category " .. recipe.category .. ")")
    end
    job.item, job.want = first.name, c.get_item_count(first.name) + started * (first.amount or 1)
    job.started_n, job.asked, job.per = started, count, first.amount or 1
    if args.wait == false then return ok("queued " .. started .. "x " .. recipe.name) end
  end,
  tick = function(a, job)
    local c = a.char
    if c.crafting_queue_size == 0 or c.get_item_count(job.item) >= job.want then
      if c.crafting_queue_size > 0 and c.get_item_count(job.item) >= job.want then
        -- Our part is done; other queued crafts keep going.
      end
      account_crafts(a) -- credit stats/triggers now, not on the next 30-tick sweep
      local msg = "crafted " .. job.started_n .. "x " .. job.args.recipe
      if job.started_n < job.asked then msg = msg .. " (only had ingredients for " .. job.started_n .. " of " .. job.asked .. ")" end
      return ok(msg, { have = c.get_item_count(job.item) })
    end
    return nil
  end,
}

------------------------------------------------------------------------- place
local function place_target(args)
  local item = prototypes.item[args.name or ""]
  if not item then return nil, "unknown item " .. tostring(args.name) end
  local ent = item.place_result
  if not ent then return nil, args.name .. " is not placeable" end
  return ent
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
      if game.tick < job.clearing.done_at then return nil end
      local inv, n = c.get_main_inventory(), 0
      for _, e in pairs(job.clearing.list) do
        if e.valid then
          local name = e.name
          if not e.mine { inventory = inv, force = false, raise_destroyed = true } then
            job.clearing = nil
            return fail("inventory full while clearing " .. name .. " at " .. xystr(e.position) .. " to place "
              .. job.entity)
          end
          n = n + 1
          triggers.note(c.force, surface, "mine-entity", name, 1)
        end
      end
      job.clearing, job.cleared = nil, (job.cleared or 0) + n
    end
    local spec = {
      name = job.entity, position = job.pos, direction = job.dir, force = c.force,
      build_check_type = defines.build_check_type.manual,
    }
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
    end
    if not surface.can_place_entity(spec) then
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
      local clutter = surface.find_entities_filtered {
        area = { { area[1][1] - 0.6, area[1][2] - 0.6 }, { area[2][1] + 0.6, area[2][2] + 0.6 } },
        type = { "tree", "simple-entity", "item-entity" },
      }
      local others = 0
      for _, e in pairs(found) do
        if e.type ~= "resource" and e.type ~= "tree" and e.type ~= "simple-entity" and e.type ~= "item-entity" then
          others = others + 1
        end
      end
      if #clutter > 0 and others == 0 and (job.clears or 0) < 3 then
        job.clears = (job.clears or 0) + 1
        local speed = c.prototype.mining_speed * (1 + c.force.manual_mining_speed_modifier
          + (c.character_mining_speed_modifier or 0))
        local secs = 0
        for _, e in pairs(clutter) do
          if e.valid and e.minable then secs = secs + (e.prototype.mineable_properties.mining_time or 0.5) / speed end
        end
        job.clearing = { list = clutter, done_at = game.tick + (util.cheat() and 0 or math.ceil(secs * 60)) }
        return nil
      end
      for _, e in pairs(found) do
        if e.type ~= "resource" then blockers[#blockers + 1] = e.name .. "@" .. xystr(e.position) end
      end
      local why
      if #blockers > 0 then
        why = "blocked by " .. table.concat(blockers, ", ", 1, math.min(#blockers, 4))
      elseif proto.type == "mining-drill" then
        why = "a mining drill needs ore under it (check the map for the patch)"
      elseif proto.type == "offshore-pump" then
        why = "an offshore pump must be placed at the edge of water, facing it"
      else
        why = "invalid spot (water, cliff or wrong tile)"
      end
      return fail("cannot place " .. job.entity .. " at " .. xystr(job.pos) .. ": " .. why)
    end
    ::place::
    local ptype = prototypes.entity[job.entity].type
    local created = surface.create_entity {
      name = job.entity, position = job.pos, direction = job.dir, force = c.force,
      raise_built = true, create_build_effect_smoke = false,
      -- underground belts: "input" is the entrance, "output" the exit; both face the travel direction
      type = (ptype == "underground-belt") and (args.type or "input") or nil,
    }
    if not created then return fail("create_entity failed for " .. job.entity) end
    if not util.cheat() then c.remove_item { name = args.name, count = 1 } end
    if created.unit_number then storage.built_by[created.unit_number] = a.name end
    triggers.note(c.force, surface, "build-entity", created.name, 1)
    local data = { entity = created.name, position = util.xy(created.position), unit_number = created.unit_number }
    local msg = "placed " .. created.name .. " at " .. xystr(created.position)
    if job.cleared then msg = msg .. " (cleared " .. job.cleared .. " trees/rocks first)" end
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
      msg = msg .. " (takes from " .. xystr(created.pickup_position) .. ", drops to " .. xystr(created.drop_position) .. ")"
    end
    return ok(msg, data)
  end,
}

------------------------------------------------------------------------- insert / take
H.insert = {
  start = function(a, job)
    local args = job.args
    if not args.item then return fail("insert needs item") end
    job.target = entity_at(a, args)
    if not job.target then return fail("no entity at " .. tostring(args.x) .. "," .. tostring(args.y)) end
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
      return fail("nothing to take from " .. e.name .. (args.item and (" (" .. args.item .. ")") or "") .. hint)
    end
    local parts = {}
    for k, v in pairs(taken) do parts[#parts + 1] = v .. " " .. k end
    return ok("took " .. table.concat(parts, ", ") .. " from " .. e.name, { taken = taken })
  end,
}

------------------------------------------------------------------------- set_recipe / rotate / research / wait
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
  local box = ent.collision_box
  local odd = math.floor(box.right_bottom.x - box.left_top.x + 0.5) % 2 == 1 -- 1x1 poles sit on tile centers
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

-- Route a belt / pipe / pole line between two points around obstacles, then queue the placements.
H.connect = {
  start = function(a, job)
    local args, c = job.args, a.char
    local item = args.item or args.name or "transport-belt"
    local ent = prototypes.item[item] and prototypes.item[item].place_result
    if not ent then return fail(tostring(item) .. " is not placeable") end
    local from = util.pos(args.from or { args.from_x, args.from_y })
    local to = util.pos(args.to or { args.to_x, args.to_y })
    if not (from and from.x and to and to.x) then return fail("connect needs from=[x,y] and to=[x,y]") end
    if util.dist(from, to) > 250 then return fail("too far to route in one go (max ~250 tiles); split it") end
    -- Endpoints often land on a machine edge; slide them to the nearest free tile.
    local function free_tile(p)
      for r = 0, 2 do
        for dx = -r, r do
          for dy = -r, r do
            if math.max(math.abs(dx), math.abs(dy)) == r then
              local q = { x = math.floor(p.x) + dx + 0.5, y = math.floor(p.y) + dy + 0.5 }
              if c.surface.can_place_entity { name = ent.name, position = q, force = c.force,
                    build_check_type = defines.build_check_type.manual } then return q end
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
      from, to = free_tile(from), free_tile(to)
      local err
      path, err = route.find(c.surface, from, to, { entity = ent.name, force = c.force })
      if not path then return fail("can't route " .. item .. ": " .. err) end
      for i, p in ipairs(path) do
        local dir
        if ent.supports_direction then
          local nxt = path[i + 1]
          if nxt then
            dir = VEC_DIR[(nxt.x - p.x) .. "," .. (nxt.y - p.y)]
          else
            dir = args.end_direction or (places[#places] and places[#places].dir) or "north"
          end
        end
        places[#places + 1] = { pos = p, dir = dir }
      end
      path.n = #path
    end

    -- Don't silently feed a teammate's belt: check what the last tile points into and what points into the first.
    if ent.type == "transport-belt" and not args.join and #places > 0 then
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
    local have = c.get_item_count(item)
    if not util.cheat() and have < #places then
      return fail("route needs " .. #places .. " " .. item .. " but you have " .. have,
        { needed = #places, have = have })
    end
    -- Place every piece inside this job, so the result says what actually got built (not just what was planned).
    job.places, job.i, job.placed, job.failed = places, 1, 0, {}
    job.item, job.span = item, { util.xy(path[1]), util.xy(path[#path]), path.n }
    if #places == 0 then
      return ok("already connected: the " .. item .. "s at both ends are within wire reach", { placed = 0, planned = 0 })
    end
  end,
  tick = function(a, job)
    local pl = job.places[job.i]
    if not pl then
      local span = "from " .. job.span[1][1] .. "," .. job.span[1][2] .. " to " .. job.span[2][1] .. "," .. job.span[2][2]
      local data = { placed = job.placed, planned = #job.places, failed = job.failed }
      if #job.failed == 0 then
        return ok("placed all " .. job.placed .. " " .. job.item .. " (" .. job.span[3] .. " tiles) " .. span, data)
      end
      return fail("placed " .. job.placed .. " of " .. #job.places .. " " .. job.item .. " " .. span .. "; failed: "
        .. table.concat(job.failed, "; ", 1, math.min(#job.failed, 3)), data)
    end
    local sub = job.sub
    if not sub then
      sub = { id = job.id, op = "place", args = { name = job.item, x = pl.pos.x, y = pl.pos.y, direction = pl.dir } }
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
  start = function(a, job) job.built, job.skip = 0, {} end,
  tick = function(a, job)
    local c, args = a.char, job.args
    local g = job.target
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
        if left == 0 then return ok("built " .. job.built .. " ghosts; none left here", { built = job.built }) end
        return ok("built " .. job.built .. " ghosts; " .. left .. " left need items you don't have",
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
      return nil
    end
    local item, n = ghost_item(g)
    local name, pos = g.ghost_name, g.position
    local _, ent = g.revive { raise_revive = true }
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
      return nil
    end
    job.stepped = nil
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

H.blueprint = {
  start = function(a, job)
    local c, args = a.char, job.args
    local ghosts = {}
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
        local okp, g = pcall(c.surface.create_entity, spec)
        if okp and g then
          if e.recipe then pcall(function() g.set_recipe(e.recipe) end) end
          ghosts[#ghosts + 1] = g
        else
          failed = failed + 1
        end
      end
      if failed > 0 and #ghosts == 0 then return fail("no ghosts placed (" .. failed .. " invalid entries)") end
    else
      return fail("blueprint needs string=<blueprint string> + x,y, or entities=[{name,x,y,direction}]")
    end
    local need = needed_items(ghosts)
    return ok("placed " .. #ghosts .. " ghosts; to build them you need " .. helpers.table_to_json(need)
      .. " (then use build_ghosts)", { ghosts = #ghosts, needs = need })
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

function jobs.cancel(a, why)
  if a.job then finish(a, a.job, fail("cancelled" .. (why and (": " .. why) or ""))) end
  for _, q in ipairs(a.queue) do
    a.results[#a.results + 1] = { id = q.id, op = q.op, ok = false, msg = "cancelled", tick = game.tick }
  end
  a.queue = {}
  if agents.alive(a) then
    movement.stop(a.char)
    a.char.mining_state = { mining = false }
  end
end

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
      if tick30 then account_crafts(a) end
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
      if job then
        local res = run(H[job.op].tick, a, job)
        if res then finish(a, job, res) end
      end
    end
  end
end

function jobs.describe(job)
  if not job then return nil end
  local d = { id = job.id, op = job.op, secs = math.floor((game.tick - (job.started_tick or game.tick)) / 60) }
  if job.move then d.walking_to = util.xy(job.move.goal) end
  if job.got then d.got = job.got end
  return d
end

-- Research queue changes without a character (the foreman): same rules as the research action.
function jobs.research_direct(args)
  return H.research.start({ char = { force = game.forces.player } }, { args = args })
end

return jobs
