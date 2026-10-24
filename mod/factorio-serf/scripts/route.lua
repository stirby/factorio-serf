-- A* tile router for belts, pipes and pole lines. Returns tile centers from start to goal (inclusive).
local route = {}

local function key(x, y) return x * 65536 + y end
route.key = key -- for opts.allow

-- Minimal binary heap on f-score; ties go to the node nearer the goal (on an open diagonal, every staircase has the
-- same f, and without this A* fills the whole rectangle and runs out of its node budget).
local function before(a, b)
  return a.f < b.f or (a.f == b.f and (a.h or 0) < (b.h or 0))
end
local function push(h, node)
  h[#h + 1] = node
  local i = #h
  while i > 1 do
    local p = math.floor(i / 2)
    if not before(h[i], h[p]) then break end
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
      if h[l] and before(h[l], h[s]) then s = l end
      if h[r] and before(h[r], h[s]) then s = r end
      if s == i then break end
      h[s], h[i] = h[i], h[s]
      i = s
    end
  end
  return top
end

local DIRS = { { 1, 0 }, { -1, 0 }, { 0, 1 }, { 0, -1 } }

-- The tile an open belt end (a belt, an underground exit, a splitter) points into: a new belt laid there would take
-- that end's items, side-loaded or head on. b4: an iron feed ran straight down past the copper tap's end, copper
-- side-loaded onto it, and the green chain starved for 30 minutes on a belt with copper on both lanes.
local BELT_T = { "transport-belt", "underground-belt", "splitter", "loader", "loader-1x1" }
local function fed_by_belt_end(surface, x, y)
  for _, b in pairs(surface.find_entities_filtered { area = { { x - 1.5, y - 1.5 }, { x + 2.5, y + 2.5 } }, type = BELT_T }) do
    local v = ({ [defines.direction.north] = { 0, -1 }, [defines.direction.east] = { 1, 0 },
                 [defines.direction.south] = { 0, 1 }, [defines.direction.west] = { -1, 0 } })[b.direction]
    local into = v and not (b.type == "underground-belt" and b.belt_to_ground_type == "input")
      and not (b.type:find("loader") and b.loader_type == "input")
    if into then
      local offs = { 0 }
      if b.type == "splitter" then offs = { -0.5, 0.5 } end
      for _, o in ipairs(offs) do
        local tx = math.floor(b.position.x - v[2] * o + v[1])
        local ty = math.floor(b.position.y + v[1] * o + v[2])
        if tx == x and ty == y then return true end
      end
    end
  end
  return false
end

-- opts: entity (prototype name to test placement), force, max_nodes, allow (tile keys always passable),
-- hop = { name = underground entity, reach = max tiles from entrance to exit }: when the way ahead is blocked,
-- the line may go under it (belts under belts, pipes under pipes, either under water). Entrances are entered
-- straight, exits lead straight on. Path entries for those tiles carry ug = "input" | "output" and dir = {dx, dy}.
-- start_forbid / goal_forbid = {dx, dy}: a first step / last step in that direction is not allowed (it would run
-- a belt head-on into the belt there). goal_join: the goal is an existing belt the line feeds; nothing lands on it.
-- belt: a belt line, which keeps off tiles an open belt end points into (except its own two ends).
-- start_dir = {dx, dy}: the way items arrive into the start tile; an underground entrance there faces that way.
function route.find(surface, from, to, opts)
  local sx, sy = math.floor(from.x), math.floor(from.y)
  local gx, gy = math.floor(to.x), math.floor(to.y)
  local max_nodes = opts.max_nodes or math.max(6000, math.min(100000, 100 * (math.abs(gx - sx) + math.abs(gy - sy))))
  local cache = {}
  -- a pipe line carrying opts.fluid: a tile beside another fluid would join the two (the game refuses that, or
  -- the line ends up mixed), so it's a wall; the machines at the line's own ends don't count
  -- An empty pipe beside the route is a wall too: it belongs to some other line that isn't flowing yet (p2: a water
  -- line joined the empty acid pipe of a starved processing-unit row, and water reached its acid inlets). Only
  -- things holding the line's own fluid, and the line's own ends, may touch it.
  local ends = {}
  ends[key(math.floor(from.x), math.floor(from.y))] = true
  ends[key(math.floor(to.x), math.floor(to.y))] = true
  local function other_fluid_near(x, y)
    if not opts.fluid then return false end
    for _, d in ipairs(DIRS) do
      local nx, ny = x + d[1], y + d[2]
      if not ends[key(nx, ny)] then
        for _, n in pairs(surface.find_entities_filtered { position = { nx + 0.5, ny + 0.5 }, limit = 3 }) do
          local joined = false
          if opts.join_segments and next(opts.join_segments) then
            local okF0, fb0 = pcall(function() return n.fluidbox end)
            if okF0 and fb0 and #fb0 >= 1 then
              local okS, seg = pcall(fb0.get_fluid_segment_id, 1)
              joined = okS and seg and opts.join_segments[seg] or false
            end
          end
          if not joined and not (opts.fluid_ignore and n.unit_number and opts.fluid_ignore[n.unit_number]) then
            local okF, fb = pcall(function() return n.fluidbox end)
            if okF and fb and #fb > 0 then
              local mine = false
              for i = 1, #fb do
                local name = fb[i] and fb[i].name
                if not name then
                  local okL, lk = pcall(fb.get_locked_fluid, i)
                  name = okL and lk or nil
                end
                if not name then
                  local okL, flt = pcall(fb.get_filter, i)
                  name = okL and flt and flt.name or nil
                end
                if name and name ~= opts.fluid then return name end
                if name == opts.fluid then mine = true end
              end
              if not mine then return "empty" end -- empty: some other line's
            end
          end
        end
      end
    end
    return false
  end
  local function free(x, y)
    local k = key(x, y)
    if opts.avoid and opts.avoid[k] then return false end -- kept clear for something the caller builds next
    if cache[k] == nil then
      -- can_place_entity says yes over a belt or pipe it could fast-replace; for a route that's a wall, not a tile.
      cache[k] = (opts.allow and opts.allow[k]) or (surface.can_place_entity {
        name = opts.entity, position = { x + 0.5, y + 0.5 }, force = opts.force,
        build_check_type = defines.build_check_type.manual,
      } and surface.count_entities_filtered { area = { { x + 0.2, y + 0.2 }, { x + 0.8, y + 0.8 } },
        type = { "resource", "character", "corpse", "item-entity", "entity-ghost", "tile-ghost" }, invert = true,
        limit = 1 } == 0 and not other_fluid_near(x, y)
        and not (opts.belt and not ends[k] and fed_by_belt_end(surface, x, y)))
    end
    return cache[k]
  end
  if not free(sx, sy) then return nil, "start tile " .. sx .. "," .. sy .. " is blocked" end
  if not free(gx, gy) then return nil, "end tile " .. gx .. "," .. gy .. " is blocked" end
  local h = {}
  local came, g = {}, {}
  g[key(sx, sy)] = 0
  -- start_dir: the way items come into the start tile (from a splitter's or underground's output, or the line it
  -- continues): an underground entrance there must face that way too, or it's fed from the side and takes nothing
  -- (p6: "connect turned the first tile after a splitter into a sideways underground entrance")
  push(h, { x = sx, y = sy, f = math.abs(gx - sx) + math.abs(gy - sy), dir = opts.start_dir })
  local hop = opts.hop
  local function tunnel_ok(x, y, d, k)
    -- Another underground of the same kind in line between would pair with ours instead.
    local x2, y2 = x + d[1] * k, y + d[2] * k
    return surface.count_entities_filtered {
      area = { { math.min(x, x2) + 0.1, math.min(y, y2) + 0.1 }, { math.max(x, x2) + 0.9, math.max(y, y2) + 0.9 } },
      name = hop.name, limit = 1 } == 0
  end
  local expanded = 0
  local best = { x = sx, y = sy, h = math.abs(gx - sx) + math.abs(gy - sy) }
  -- Why there's no route, in words the planner can act on: an end with no way in (planners pick the side of a
  -- machine), else how close the search got. "no route found within search limit" for a 4-tile line said nothing.
  local function what_at(x, y)
    local es = surface.find_entities_filtered { area = { { x + 0.2, y + 0.2 }, { x + 0.8, y + 0.8 } }, limit = 1,
      type = { "resource", "character", "corpse", "item-entity" }, invert = true }
    if es[1] then return es[1].name end
    local okT, t = pcall(surface.get_tile, x, y)
    return (okT and t and t.valid) and t.name or "?"
  end
  local function no_way(x, y, skip)
    local around = {}
    for _, d in ipairs(DIRS) do
      local nx, ny = x + d[1], y + d[2]
      if not (skip and skip[1] == d[1] and skip[2] == d[2]) then
        if free(nx, ny) then return nil end
        around[#around + 1] = what_at(nx, ny) .. "@" .. nx .. "," .. ny
      end
    end
    return table.concat(around, ", ")
  end
  -- The free tiles reachable from x,y on the surface (no undergrounds), up to cap: nil when there are more (open
  -- ground), else their count and what walls them in. p6's 13-tile petroleum pipe failed "within search limit" at
  -- 6,000 and at 24,000 nodes alike: its inlet sat in a pocket closed off by other fluids' pipes.
  local function pocket(x0, y0, cap)
    local seen, q, walls = { [key(x0, y0)] = true }, { { x0, y0 } }, {}
    local head = 1
    while head <= #q do
      if #q > cap then return nil end
      local pt = q[head]
      head = head + 1
      for _, d in ipairs(DIRS) do
        local x, y = pt[1] + d[1], pt[2] + d[2]
        local k = key(x, y)
        if not seen[k] then
          seen[k] = true
          if free(x, y) then
            q[#q + 1] = { x, y }
          else
            local es = surface.find_entities_filtered { area = { { x + 0.2, y + 0.2 }, { x + 0.8, y + 0.8 } }, limit = 1,
              type = { "resource", "character", "corpse", "item-entity" }, invert = true }
            local w
            if es[1] then w = es[1].name
            else
              local okT, t = pcall(surface.get_tile, x, y)
              local tn = (okT and t and t.valid) and t.name or "?"
              local other = opts.fluid and other_fluid_near(x, y)
              w = (tn:find("water") and tn)
                or (other == "empty" and "free ground beside an empty pipe of another line")
                or (other and ("free ground beside " .. other .. " pipes"))
                or (opts.belt and "free ground an open belt end points into") or tn
            end
            walls[w] = (walls[w] or 0) + 1
          end
        end
      end
    end
    return #q, walls
  end
  local function pocket_words(x0, y0, what)
    local n, walls = pocket(x0, y0, 3000)
    if not n then return nil end
    local parts = {}
    for w, c in pairs(walls) do parts[#parts + 1] = { c, w } end
    table.sort(parts, function(a, b) return a[1] > b[1] end)
    local ws = {}
    for i = 1, math.min(#parts, 6) do ws[#ws + 1] = parts[i][1] .. " " .. parts[i][2] end
    return what .. " " .. x0 .. "," .. y0 .. " sits in a closed pocket of " .. n .. " free tiles, walled in by "
      .. table.concat(ws, ", ") .. (opts.fluid and " (a pipe beside another fluid's pipe would join them, so those are walls)" or "")
      .. (hop and "; going under found no way out either" or "")
      .. ". Make an opening (pick up what's in the way), or end the line somewhere else"
  end
  local function why_not(reason)
    -- the last step into the goal can't be in direction gf: from the tile at goal - gf
    local gin = opts.goal_forbid and { -opts.goal_forbid[1], -opts.goal_forbid[2] } or nil
    local gb = (not hop) and no_way(gx, gy, gin)
    if gb then return "end tile " .. gx .. "," .. gy .. " has no free tile beside it to come in from (" .. gb .. ")" end
    local sb = (not hop) and no_way(sx, sy, opts.start_forbid)
    if sb then return "start tile " .. sx .. "," .. sy .. " has no free tile beside it to leave by (" .. sb .. ")" end
    local pw = pocket_words(gx, gy, "the end") or pocket_words(sx, sy, "the start")
    if pw then return pw end
    return reason .. " (searched " .. expanded .. " tiles; got as close as " .. best.x .. "," .. best.y .. ", "
      .. best.h .. " tiles from the end)"
  end
  while #h > 0 do
    local n = pop(h)
    if n.h and n.h < best.h then best = { x = n.x, y = n.y, h = n.h } end
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
    if expanded > max_nodes then return nil, why_not("no route found within search limit") end
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
          local hh = math.abs(gx - x) + math.abs(gy - y)
          push(h, { x = x, y = y, dir = d, f = cost + hh, h = hh })
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
              local hh = math.abs(gx - ex) + math.abs(gy - ey)
              push(h, { x = ex, y = ey, dir = d, exit = true, f = cost + hh, h = hh })
            end
            break
          end
        end
      end
    end
    ::continue::
  end
  return nil, why_not("no route (blocked)")
end

return route
