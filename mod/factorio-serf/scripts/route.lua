-- A* tile router for belts, pipes and pole lines. Returns tile centers from start to goal (inclusive).
local route = {}

local function key(x, y) return x * 65536 + y end
route.key = key -- for opts.allow

-- Minimal binary heap on f-score.
local function push(h, node)
  h[#h + 1] = node
  local i = #h
  while i > 1 do
    local p = math.floor(i / 2)
    if h[p].f <= h[i].f then break end
    h[p], h[i] = h[i], h[p]
    i = p
  end
end
local function pop(h)
  local top = h[1]
  local last = table.remove(h)
  if #h > 0 then
    h[1] = last
    local i = 1
    while true do
      local l, r, s = i * 2, i * 2 + 1, i
      if h[l] and h[l].f < h[s].f then s = l end
      if h[r] and h[r].f < h[s].f then s = r end
      if s == i then break end
      h[s], h[i] = h[i], h[s]
      i = s
    end
  end
  return top
end

local DIRS = { { 1, 0 }, { -1, 0 }, { 0, 1 }, { 0, -1 } }

-- opts: entity (prototype name to test placement), force, max_nodes, allow (tile keys always passable),
-- hop = { name = underground entity, reach = max tiles from entrance to exit }: when the way ahead is blocked,
-- the line may go under it (belts under belts, pipes under pipes, either under water). Entrances are entered
-- straight, exits lead straight on. Path entries for those tiles carry ug = "input" | "output" and dir = {dx, dy}.
-- start_forbid / goal_forbid = {dx, dy}: a first step / last step in that direction is not allowed (it would run
-- a belt head-on into the belt there). goal_join: the goal is an existing belt the line feeds; nothing lands on it.
function route.find(surface, from, to, opts)
  local sx, sy = math.floor(from.x), math.floor(from.y)
  local gx, gy = math.floor(to.x), math.floor(to.y)
  local max_nodes = opts.max_nodes or 6000
  local cache = {}
  local function free(x, y)
    local k = key(x, y)
    if cache[k] == nil then
      -- can_place_entity says yes over a belt or pipe it could fast-replace; for a route that's a wall, not a tile.
      cache[k] = (opts.allow and opts.allow[k]) or (surface.can_place_entity {
        name = opts.entity, position = { x + 0.5, y + 0.5 }, force = opts.force,
        build_check_type = defines.build_check_type.manual,
      } and surface.count_entities_filtered { area = { { x + 0.2, y + 0.2 }, { x + 0.8, y + 0.8 } },
        type = { "resource", "character", "corpse", "item-entity", "entity-ghost", "tile-ghost" }, invert = true,
        limit = 1 } == 0)
    end
    return cache[k]
  end
  if not free(sx, sy) then return nil, "start tile " .. sx .. "," .. sy .. " is blocked" end
  if not free(gx, gy) then return nil, "end tile " .. gx .. "," .. gy .. " is blocked" end
  local h = {}
  local came, g = {}, {}
  g[key(sx, sy)] = 0
  push(h, { x = sx, y = sy, f = math.abs(gx - sx) + math.abs(gy - sy), dir = nil })
  local hop = opts.hop
  local function tunnel_ok(x, y, d, k)
    -- Another underground of the same kind in line between would pair with ours instead.
    local x2, y2 = x + d[1] * k, y + d[2] * k
    return surface.count_entities_filtered {
      area = { { math.min(x, x2) + 0.1, math.min(y, y2) + 0.1 }, { math.max(x, x2) + 0.9, math.max(y, y2) + 0.9 } },
      name = hop.name, limit = 1 } == 0
  end
  local expanded = 0
  while #h > 0 do
    local n = pop(h)
    local nk = key(n.x, n.y)
    local is_exit = came[nk] and came[nk].hop or false
    if (n.exit or false) ~= is_exit then goto continue end -- a stale heap entry for this tile
    if n.x == gx and n.y == gy then
      -- Walk back from the goal; the start tile has no `came` entry.
      local path = {}
      local k = nk
      while k do
        local c = came[k]
        path[#path + 1] = { pos = c and c.pos or { x = sx, y = sy }, hop = c and c.hop, d = c and c.d }
        k = c and c.prev or nil
      end
      local out = {}
      for i = #path, 1, -1 do
        out[#out + 1] = { x = path[i].pos.x + 0.5, y = path[i].pos.y + 0.5 }
        if path[i].hop then
          out[#out].ug, out[#out].dir = "output", path[i].d
          out[#out - 1].ug, out[#out - 1].dir = "input", path[i].d
        end
      end
      return out
    end
    expanded = expanded + 1
    if expanded > max_nodes then return nil, "no route found within search limit" end
    for _, d in ipairs(DIRS) do
      local x, y = n.x + d[1], n.y + d[2]
      local k = key(x, y)
      local straight = not n.dir or (n.dir[1] == d[1] and n.dir[2] == d[2])
      local sf, gf = opts.start_forbid, opts.goal_forbid
      if is_exit and not straight then
        -- an exit only leads straight on
      elseif (sf and not n.dir and sf[1] == d[1] and sf[2] == d[2])
          or (gf and x == gx and y == gy and gf[1] == d[1] and gf[2] == d[2]) then
        -- head-on into a belt
      elseif free(x, y) then
        -- Turns cost a little extra so routes come out straight.
        local turn = (n.dir and (n.dir[1] ~= d[1] or n.dir[2] ~= d[2])) and 0.5 or 0
        local cost = g[nk] + 1 + turn
        if g[k] == nil or cost < g[k] then
          g[k] = cost
          came[k] = { prev = nk, pos = { x = x, y = y } }
          push(h, { x = x, y = y, dir = d, f = cost + math.abs(gx - x) + math.abs(gy - y) })
        end
      elseif hop and straight and not is_exit then
        -- Blocked ahead: go under, to the nearest free tile within reach.
        for j = 2, hop.reach do
          local ex, ey = n.x + d[1] * j, n.y + d[2] * j
          if free(ex, ey) and not (opts.goal_join and ex == gx and ey == gy) then
            local ek = key(ex, ey)
            local cost = g[nk] + j + 3 -- undergrounds cost items: prefer the surface when it's close
            if (g[ek] == nil or cost < g[ek]) and tunnel_ok(n.x, n.y, d, j) then
              g[ek] = cost
              came[ek] = { prev = nk, pos = { x = ex, y = ey }, hop = true, d = d }
              push(h, { x = ex, y = ey, dir = d, exit = true, f = cost + math.abs(gx - ex) + math.abs(gy - ey) })
            end
            break
          end
        end
      end
    end
    ::continue::
  end
  return nil, "no route (blocked)"
end

return route
