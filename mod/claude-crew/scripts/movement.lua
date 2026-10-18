-- Walking with the game's pathfinder. A move state m = { goal, radius } is ticked by jobs;
-- it returns nil while moving, "arrived", or a failure string.
local util = require("scripts.util")

local movement = {}

local PATH_BOX = { { -0.35, -0.35 }, { 0.35, 0.35 } } -- a bit wider than the character, for clearance
local WAYPOINT_EPS = 0.45
local STUCK_TICKS = 45
local MAX_REPATHS = 4
local PATH_TIMEOUT = 60 * 20

function movement.stop(char)
  if char and char.valid then char.walking_state = { walking = false, direction = defines.direction.north } end
end

local function request(char, m)
  local proto = prototypes.entity["character"]
  m.req = char.surface.request_path {
    bounding_box = PATH_BOX,
    collision_mask = proto.collision_mask,
    start = char.position,
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
        return "no path to " .. util.xy(m.goal)[1] .. "," .. util.xy(m.goal)[2]
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
    request(char, m)
  end
  return nil
end

return movement
