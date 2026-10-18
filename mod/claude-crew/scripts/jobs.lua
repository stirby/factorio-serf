-- Per-agent job queue. Each job walks into reach first (where it needs to), then acts,
-- obeying normal player rules unless cheat mode is on.
-- A handler is { start = fn(a, job) -> result?, tick = fn(a, job) -> result? }.
-- A result is { ok = bool, msg = string, data = table? }.
local util = require("scripts.util")
local movement = require("scripts.movement")
local agents = require("scripts.agents")
local triggers = require("scripts.triggers")
local route = require("scripts.route")

local jobs = {}
local H = {}

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
      triggers.note(c.force, c.surface, "craft-item", job.item, job.started_n * (job.per or 1))
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
      local found = surface.find_entities_filtered {
        area = { { job.pos.x - half, job.pos.y - half }, { job.pos.x + half, job.pos.y + half } },
      }
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
    local created = surface.create_entity {
      name = job.entity, position = job.pos, direction = job.dir, force = c.force,
      raise_built = true, create_build_effect_smoke = false,
    }
    if not created then return fail("create_entity failed for " .. job.entity) end
    if not util.cheat() then c.remove_item { name = args.name, count = 1 } end
    if created.unit_number then storage.built_by[created.unit_number] = a.name end
    triggers.note(c.force, surface, "build-entity", created.name, 1)
    local data = { entity = created.name, position = util.xy(created.position), unit_number = created.unit_number }
    local msg = "placed " .. created.name .. " at " .. xystr(created.position)
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
    if next(taken) == nil then return fail("nothing to take from " .. e.name .. (args.item and (" (" .. args.item .. ")") or "")) end
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
    else
      e.rotate { reverse = job.args.reverse or false }
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
      return fail(tech.name .. " is a trigger tech; it unlocks by doing: " .. tech.prototype.research_trigger.type
        .. " (see techs)")
    end
    for _, q in pairs(force.research_queue or {}) do
      if q.name == tech.name then return ok(tech.name .. " is already in the research queue") end
    end
    if force.add_research(tech) then return ok("queued research " .. tech.name) end
    return fail("could not queue " .. tech.name .. " (missing prerequisites or queue full)")
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
    local path, err = route.find(c.surface, from, to, { entity = ent.name, force = c.force })
    if not path then return fail("can't route " .. item .. ": " .. err) end

    local places = {}
    if ent.type == "electric-pole" then
      local reach = 7.5
      pcall(function() reach = ent.get_max_wire_distance() end)
      local step = math.max(1, math.floor(reach) - 1)
      for i = 1, #path, step do places[#places + 1] = { pos = path[i] } end
      if places[#places].pos ~= path[#path] then places[#places + 1] = { pos = path[#path] } end
    else
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
    end

    local have = c.get_item_count(item)
    if not util.cheat() and have < #places then
      return fail("route needs " .. #places .. " " .. item .. " but you have " .. have,
        { needed = #places, have = have })
    end
    for i, pl in ipairs(places) do
      table.insert(a.queue, i, new_job("place", { name = item, x = pl.pos.x, y = pl.pos.y, direction = pl.dir }))
    end
    return ok("routed " .. #path .. " tiles; placing " .. #places .. " " .. item .. " from " .. xystr(path[1])
      .. " to " .. xystr(path[#path]), { count = #places, start = util.xy(path[1]), finish = util.xy(path[#path]) })
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
  if not res.ok and job.stop_on_fail ~= false then
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

function jobs.tick()
  for _, a in pairs(storage.agents) do
    if agents.alive(a) then
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

return jobs
