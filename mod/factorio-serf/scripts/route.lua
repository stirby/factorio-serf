-- A* tile router for belts, pipes and pole lines. Returns tile centers from start to goal (inclusive).
local route = {}

local function key(x, y) return x * 65536 + y end

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

-- opts: entity (prototype name to test placement), force, max_nodes, allow (tile keys always passable)
function route.find(surface, from, to, opts)
  local sx, sy = math.floor(from.x), math.floor(from.y)
  local gx, gy = math.floor(to.x), math.floor(to.y)
  local max_nodes = opts.max_nodes or 6000
  local cache = {}
  local function free(x, y)
    local k = key(x, y)
    if cache[k] == nil then
      cache[k] = (opts.allow and opts.allow[k]) or surface.can_place_entity {
        name = opts.entity, position = { x + 0.5, y + 0.5 }, force = opts.force,
        build_check_type = defines.build_check_type.manual,
      }
    end
    return cache[k]
  end
  if not free(sx, sy) then return nil, "start tile " .. sx .. "," .. sy .. " is blocked" end
  if not free(gx, gy) then return nil, "end tile " .. gx .. "," .. gy .. " is blocked" end
  local h = {}
  local came, g = {}, {}
  g[key(sx, sy)] = 0
  push(h, { x = sx, y = sy, f = math.abs(gx - sx) + math.abs(gy - sy), dir = nil })
  local expanded = 0
  while #h > 0 do
    local n = pop(h)
    local nk = key(n.x, n.y)
    if n.x == gx and n.y == gy then
      -- Walk back from the goal; the start tile has no `came` entry.
      local path = {}
      local k = nk
      while k do
        path[#path + 1] = came[k] and came[k].pos or { x = sx, y = sy }
        k = came[k] and came[k].prev or nil
      end
      local out = {}
      for i = #path, 1, -1 do out[#out + 1] = { x = path[i].x + 0.5, y = path[i].y + 0.5 } end
      return out
    end
    expanded = expanded + 1
    if expanded > max_nodes then return nil, "no route found within search limit" end
    for _, d in ipairs(DIRS) do
      local x, y = n.x + d[1], n.y + d[2]
      local k = key(x, y)
      if free(x, y) then
        -- Turns cost a little extra so routes come out straight.
        local turn = (n.dir and (n.dir[1] ~= d[1] or n.dir[2] ~= d[2])) and 0.5 or 0
        local cost = g[nk] + 1 + turn
        if g[k] == nil or cost < g[k] then
          g[k] = cost
          came[k] = { prev = nk, pos = { x = x, y = y } }
          push(h, { x = x, y = y, dir = d, f = cost + math.abs(gx - x) + math.abs(gy - y) })
        end
      end
    end
  end
  return nil, "no route (blocked)"
end

return route
