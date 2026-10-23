-- Walking with the game's pathfinder. A move state m = { goal, radius } is ticked by jobs;
-- it returns nil while moving, "arrived", or a failure string.
local util = require("scripts.util")

local movement = {}

-- First try a box a bit wider than the character (clearance), then the real one.
local PATH_BOXES = { { { -0.35, -0.35 }, { 0.35, 0.35 } }, { { -0.2, -0.2 }, { 0.2, 0.2 } } }
local WAYPOINT_EPS = 0.45
local STUCK_TICKS = 45
local MAX_REPATHS = 4
local PATH_TIMEOUT = 60 * 20

function movement.stop(char)
  if char and char.valid then char.walking_state = { walking = false, direction = defines.direction.north } end
end

local function request(char, m)
  local proto = prototypes.entity["character"]
  local attempt = m.attempt or 1
  local start = char.position
  if attempt > 1 then
    start = char.surface.find_non_colliding_position("character", start, 3, 0.25) or start
  end
  m.req = char.surface.request_path {
    bounding_box = PATH_BOXES[math.min(attempt, #PATH_BOXES)],
    collision_mask = proto.collision_mask,
    start = start,
    goal = m.goal,
    force = char.force,
    radius = math.max(m.radius - 0.3, 0.5),
    entity_to_ignore = char,
    can_open_gates = true,
    path_resolution_modifier = 0,
    pathfind_flags = { cache = false, prefer_straight_paths = true, allow_paths_through_own_entities = false },
  }
  m.req_tick = game.tick
  m.path, m.idx = nil, nil
end

function movement.on_path(e)
  storage.path_results[e.id] = { path = e.path, again = e.try_again_later, tick = game.tick }
end

-- Drop stale path results (job got cancelled before the path came back).
function movement.gc()
  for id, r in pairs(storage.path_results) do
    if game.tick - r.tick > 600 then storage.path_results[id] = nil end
  end
end

function movement.tick(char, m)
  if m.pause then
    if game.tick < m.pause then return nil end
    m.pause, m.stuck_ref = nil, nil
  end
  local pos = char.position
  local d = util.dist(pos, m.goal)
  if d <= m.radius then
    movement.stop(char)
    return "arrived"
  end

  if util.cheat() then
    local dest = char.surface.find_non_colliding_position("character", m.goal, m.radius + 4, 0.5)
    if not dest then return "no free spot near goal" end
    char.teleport(dest)
    return "arrived"
  end

  if not m.path then
    if d < 2.5 then
      m.path, m.idx = { { position = m.goal } }, 1
    elseif not m.req then
      request(char, m)
      return nil
    else
      local r = storage.path_results[m.req]
      if not r then
        if game.tick - m.req_tick > PATH_TIMEOUT then return "pathfinder timed out" end
        return nil
      end
      storage.path_results[m.req] = nil
      m.req = nil
      if not r.path then
        m.path_fails = (m.path_fails or 0) + 1
        if r.again and m.path_fails < 5 then return nil end -- pathfinder busy; ask again next tick
        if not m.snapped then
          -- The goal itself may be unstandable (inside a building, on water): aim for the nearest free spot instead.
          m.snapped = true
          local spot = char.surface.find_non_colliding_position("character", m.goal, math.max(m.radius + 2, 6), 0.5)
          if spot and util.dist(spot, m.goal) > 0.5 then
            m.radius = math.max(0.5, m.radius - util.dist(spot, m.goal))
            m.goal = spot
            return nil
          end
        end
        m.attempt = (m.attempt or 1) + 1
        if m.attempt <= 3 then
          if m.attempt == 3 then m.radius = m.radius + 2 end -- last try: accept getting a bit closer only
          return nil
        end
        local g = util.xy(m.goal)
        local gen = char.surface.is_chunk_generated { math.floor(m.goal.x / 32), math.floor(m.goal.y / 32) }
        return "no path to " .. g[1] .. "," .. g[2] .. (gen and " (blocked by water/cliffs/buildings?)" or " (that area isn't generated yet)")
      end
      m.path, m.idx = r.path, 1
    end
  end

  local wp = m.path[m.idx].position
  while m.idx < #m.path and util.dist(pos, wp) < WAYPOINT_EPS do
    m.idx = m.idx + 1
    wp = m.path[m.idx].position
  end
  local dw = util.dist(pos, wp)
  if m.idx == #m.path and dw < WAYPOINT_EPS then
    movement.stop(char)
    -- End of path but not within radius: goal itself is blocked. Close enough counts.
    if d <= m.radius + 1.5 then return "arrived" end
    return "path ended " .. string.format("%.1f", d) .. " tiles short of goal"
  end

  char.walking_state = { walking = true, direction = util.walk_dir(wp.x - pos.x, wp.y - pos.y) }

  -- Stuck detection: replan from here if we haven't moved.
  m.stuck_ref = m.stuck_ref or { x = pos.x, y = pos.y, tick = game.tick }
  if util.dist(pos, m.stuck_ref) > 0.3 then
    m.stuck_ref = { x = pos.x, y = pos.y, tick = game.tick }
  elseif game.tick - m.stuck_ref.tick > STUCK_TICKS then
    m.repaths = (m.repaths or 0) + 1
    if m.repaths > MAX_REPATHS then
      movement.stop(char)
      return "stuck at " .. util.xy(pos)[1] .. "," .. util.xy(pos)[2]
    end
    m.stuck_ref = nil
    movement.stop(char)
    if m.repaths >= 2 then
      -- Caught twice: in a forest (q7 got stuck at the same tree on every walk home), cut down the tree or rock
      -- it is caught on, as a player would, and stand still while the axe works; else wiggle free like a player
      -- would (at most a tile, to the nearest clear spot).
      local cut = false
      local snags = char.surface.find_entities_filtered { position = pos, radius = 1.5, type = { "tree", "simple-entity" } }
      table.sort(snags, function(a, b) return util.dist(a.position, pos) < util.dist(b.position, pos) end)
      for _, e in ipairs(snags) do
        if e.valid and e.minable and (e.type == "tree" or e.prototype.count_as_rock_for_filtered_deconstruction) then
          local secs = e.prototype.mineable_properties.mining_time / char.prototype.mining_speed
          if char.mine_entity(e) then
            cut = true
            m.pause = game.tick + math.ceil(secs * 60)
            break
          end
        end
      end
      if not cut then
        local spot = char.surface.find_non_colliding_position("character", pos, 1.2, 0.1)
        if spot and util.dist(spot, pos) > 0.05 then char.teleport(spot) end
      end
    end
    request(char, m)
  end
  return nil
end

return movement
