-- Fluid lines: follow the pipes from a machine port, a pumpjack or a pipe and say what the line joins, what it holds
-- and where it ends, with what sits past each end. Managers kept laying a third crude line because nothing could
-- show them where the first two stopped (q7, p7: "my tools can't trace fluid in pipes").
local util = require("scripts.util")

local fluids = {}

-- entities a line runs through; anything else on it is a machine at the end of a line
local PASS = { pipe = true, ['pipe-to-ground'] = true, ['storage-tank'] = true, pump = true, ['infinity-pipe'] = true }

-- A fluid segment longer than this (bounding box, tiles) fills but moves nothing in 2.0 (utility constant
-- default_pipeline_extent; measured: 300 tiles carried 1200/s, 330 carried 0). Pumps start new segments.
fluids.EXTENT = 320

local function key(e, i) return e.unit_number .. ':' .. i end

local function box_kind(fb, i)
  local okP, pr = pcall(fb.get_prototype, i)
  if not okP or not pr then return 'none' end
  local okA, first = pcall(function() return pr[1] end)  -- some ports give a list of prototypes
  if okA and first then pr = first end
  local okT, t = pcall(function() return pr.production_type end)
  return (okT and t) or 'none'
end

-- the fluid a box holds, or the one it's set up for (a recipe's input, a filter)
local function box_fluid(fb, i)
  local okF, fl = pcall(function() return fb[i] end)
  if okF and fl and fl.amount > 0 then return fl.name, fl.amount end
  local okL, f = pcall(fb.get_filter, i)
  if okL and f and f.name then return f.name, 0 end
  local okK, lf = pcall(fb.get_locked_fluid, i)
  if okK and lf then return lf, 0 end
  return nil, 0
end

local function status_of(e)
  local okS, st = pcall(function() return e.status end)
  return okS and st and util.STATUS_NAMES[st] or nil
end

local function member(e)
  return { n = e.name, p = util.xy(e.position), status = status_of(e) }
end

local function unit(dx, dy)
  local ax = (dx > 0.25 and 1) or (dx < -0.25 and -1) or 0
  local ay = (dy > 0.25 and 1) or (dy < -0.25 and -1) or 0
  return ax, ay
end

local function things_at(s, x, y)
  local found = s.find_entities_filtered { area = { { x - 0.3, y - 0.3 }, { x + 0.3, y + 0.3 } },
    type = { 'resource', 'corpse', 'character-corpse', 'item-entity', 'character', 'highlight-box' }, invert = true }
  return found[1]
end

-- What sits past an open end, looking straight ahead from `p` along (ax, ay): the entity on the next tile, or the
-- next pipe further on (a gap), up to `reach` tiles.
local function past(s, p, ax, ay, reach, f)
  local x, y = p.x + ax, p.y + ay
  local o = things_at(s, x, y)
  if o then
    local d = { n = o.name, p = util.xy(o.position) }
    if o.fluidbox and #o.fluidbox > 0 then d.fluid = box_fluid(o.fluidbox, 1) end
    if o.type == 'tree' or o.type == 'simple-entity' or o.type == 'cliff' then d.blocks = true end
    return { next_to = d }
  end
  for k = 2, reach do
    local q = { x = p.x + ax * k, y = p.y + ay * k }
    local g = s.find_entities_filtered { position = q, radius = 0.3, force = f, type = { 'pipe', 'pipe-to-ground', 'storage-tank', 'pump' }, limit = 1 }[1]
    if g then
      local d = { n = g.name, p = util.xy(g.position), gap = k - 1 }
      d.fluid = box_fluid(g.fluidbox, 1)
      if g.type == 'pipe-to-ground' then d.dir = util.DIR_NAMES[g.direction] end
      return { further = d }
    end
  end
  return {}
end

-- Walk one line from box `si` of `start`. Returns a summary: fluid, size, fill, sources, users, ends.
local function walk(start, si, max)
  local s, f = start.surface, start.force
  local seen = { [key(start, si)] = true }
  local queue = { { e = start, i = si, start = true } }
  local net = { pipes = 0, tanks = 0, pumps = 0, amount = 0, capacity = 0, sources = {}, users = {}, through = {},
    ends = {}, ends_total = 0, extent = { math.huge, math.huge, -math.huge, -math.huge } }
  local units, segs, raw = {}, {}, {}
  local head = 1
  while head <= #queue do
    if head > max then net.cut = true break end
    local cur = queue[head]
    head = head + 1
    local e, i = cur.e, cur.i
    local fb = e.fluidbox
    local pass = PASS[e.type]
    if pass then
      units[e.unit_number] = true
      if e.type == 'storage-tank' then net.tanks = net.tanks + 1
      elseif e.type == 'pump' then net.pumps = net.pumps + 1
      else net.pipes = net.pipes + 1 end
      local fl, amt = box_fluid(fb, i)
      if fl and amt > 0 then net.fluid = net.fluid or fl end
      net.amount = net.amount + amt
      -- the piece's own volume: get_capacity gives the whole segment's (74,900 for a 499-pipe line), and summing
      -- that made every long line read "0% full" (b15: four plans spent mending a water line that was full)
      local okV, vol = pcall(function() return fb.get_prototype(i).volume end)
      if not (okV and vol) then
        local okC, c = pcall(fb.get_capacity, i)
        vol = okC and c or 0
      end
      net.capacity = net.capacity + vol
      local x, y = e.position.x, e.position.y
      local b = net.extent
      b[1], b[2], b[3], b[4] = math.min(b[1], x), math.min(b[2], y), math.max(b[3], x), math.max(b[4], y)
      local okG, sid = pcall(fb.get_fluid_segment_id, i)
      if okG and sid then
        local sb = segs[sid] or { math.huge, math.huge, -math.huge, -math.huge }
        sb[1], sb[2], sb[3], sb[4] = math.min(sb[1], x), math.min(sb[2], y), math.max(sb[3], x), math.max(sb[4], y)
        segs[sid] = sb
      end
    end
    local okP, conns = pcall(fb.get_pipe_connections, i)
    local linked, open = {}, {}
    for _, c in pairs(okP and conns or {}) do
      local t = c.target
      if t and t.owner and t.owner.valid then
        linked[#linked + 1] = c
        local o = t.owner
        local ti = c.target_fluidbox_index or 1
        local k = key(o, ti)
        if not seen[k] then
          seen[k] = true
          if PASS[o.type] then
            queue[#queue + 1] = { e = o, i = ti }
          elseif o.type == 'entity-ghost' then
            -- a planned piece not built yet: the line is open there until it is (q7's crude line, 2026-10-23)
            net.ends_total = net.ends_total + 1
            if #raw < 400 then raw[#raw + 1] = { e = o, en = { kind = 'ghost', ghost = o.ghost_name, ax = 0, ay = 0 } } end
          else
            local kind = box_kind(o.fluidbox, ti)
            local lk = (kind == 'output' and 'sources') or (kind == 'input' and 'users') or 'through'
            local list = net[lk]
            if #list < 12 then list[#list + 1] = member(o) end
            net[lk .. '_n'] = (net[lk .. '_n'] or 0) + 1
            local fl = box_fluid(o.fluidbox, ti)
            if kind == 'input' and fl then net.wanted = net.wanted or fl end
            if kind == 'output' and fl then net.made = net.made or fl end
          end
        end
      else
        open[#open + 1] = c
      end
    end
    if pass then
      -- an end: a pipe joined on one side only (or none), a pipe-to-ground or pump with a port left open
      local ends = {}
      if e.type == 'pipe' or e.type == 'infinity-pipe' then
        if #linked == 1 then
          local c = linked[1]
          local ax, ay = unit(c.target_position.x - c.position.x, c.target_position.y - c.position.y)
          ends[1] = { kind = 'pipe end', ax = -ax, ay = -ay }
        elseif #linked == 0 then
          ends[1] = { kind = 'lone pipe', ax = 0, ay = 0 }
        end
      elseif e.type == 'pipe-to-ground' or e.type == 'pump' then
        for _, c in pairs(open) do
          local ax, ay = unit(c.target_position.x - c.position.x, c.target_position.y - c.position.y)
          ends[#ends + 1] = { kind = c.connection_type == 'underground' and 'underground, no exit' or 'open port',
            ax = ax, ay = ay }
        end
      end
      for _, en in ipairs(ends) do
        net.ends_total = net.ends_total + 1
        if #raw < 400 then raw[#raw + 1] = { e = e, en = en } end
      end
    end
  end
  -- the ends farthest from where the walk started first: near ones are the stubs beside the start
  local sx, sy = start.position.x, start.position.y
  for _, r in ipairs(raw) do r.d = (r.e.position.x - sx) ^ 2 + (r.e.position.y - sy) ^ 2 end
  table.sort(raw, function(a, b) return a.d > b.d end)
  for idx = 1, math.min(#raw, 12) do
    local e, en = raw[idx].e, raw[idx].en
    local d = { at = util.xy(e.position), n = e.name, kind = en.kind, toward = util.DIR_NAMES[
      (en.ax == 1 and defines.direction.east) or (en.ax == -1 and defines.direction.west)
      or (en.ay == 1 and defines.direction.south) or (en.ay == -1 and defines.direction.north) or -1] }
    if en.kind == 'ghost' then
      d.n = en.ghost
    elseif en.ax ~= 0 or en.ay ~= 0 then
      if en.kind == 'underground, no exit' then
        -- the nearest pipe-to-ground further along this line, and which way it faces
        for k = 2, 14 do
          local g = s.find_entities_filtered { position = { e.position.x + en.ax * k, e.position.y + en.ay * k },
            radius = 0.3, force = f, type = 'pipe-to-ground', limit = 1 }[1]
          if g then
            d.further = { n = g.name, p = util.xy(g.position), gap = k - 1, dir = util.DIR_NAMES[g.direction],
              fluid = box_fluid(g.fluidbox, 1) }
            break
          end
        end
      else
        local w = past(s, e.position, en.ax, en.ay, 8, f)
        d.next_to, d.further = w.next_to, w.further
      end
    end
    net.ends[#net.ends + 1] = d
  end
  net.segments, net.long = 0, {}
  for _, sb in pairs(segs) do
    net.segments = net.segments + 1
    local span = math.max(sb[3] - sb[1], sb[4] - sb[2]) + 1
    if span > fluids.EXTENT and #net.long < 6 then net.long[#net.long + 1] = { span = math.floor(span), from = { sb[1], sb[2] }, to = { sb[3], sb[4] } } end
  end
  net.fill = net.capacity > 0 and math.floor(100 * net.amount / net.capacity + 0.5) or 0
  net.amount = math.floor(net.amount)
  net.capacity = nil
  local b = net.extent
  if b[1] == math.huge then net.extent = nil else net.extent = { b[1], b[2], b[3], b[4] } end
  return net, units
end

local function entity_at(s, p)
  local e = s.find_entities_filtered { position = p, radius = 0.3, type = { 'pipe', 'pipe-to-ground', 'storage-tank', 'pump' }, limit = 1 }[1]
  if e then return e end
  for _, o in pairs(s.find_entities_filtered { area = { { p.x - 0.4, p.y - 0.4 }, { p.x + 0.4, p.y + 0.4 } } }) do
    if o.fluidbox and #o.fluidbox > 0 then return o end
  end
  for _, o in pairs(s.find_entities_filtered { position = p, radius = 1.5 }) do
    if o.fluidbox and #o.fluidbox > 0 then return o end
  end
end

-- req: x, y (a pipe, a machine, a pumpjack...), fluid (only that port), max (boxes to walk, default 6000)
function fluids.trace(req)
  local s = game.surfaces[req.surface or 'nauvis']
  local p = util.pos(req.position or { req.x, req.y })
  if not (p and p.x and p.y) then error("pipes needs x,y", 0) end
  local e = entity_at(s, p)
  if not e then error("nothing that holds fluid at " .. p.x .. "," .. p.y, 0) end
  local fb = e.fluidbox
  local out = { at = member(e), lines = {} }
  local done = {}
  for i = 1, #fb do
    local fl = box_fluid(fb, i)
    if (not req.fluid or fl == req.fluid) and not done[key(e, i)] then
      local net, units = walk(e, i, math.min(req.max or 6000, 20000))
      net.port = { index = i, kind = box_kind(fb, i), fluid = fl }
      out.lines[#out.lines + 1] = net
      done[key(e, i)] = true
      if PASS[e.type] then break end
      for u in pairs(units) do done[u .. ':1'] = true end
    end
  end
  return out
end

local STARVED = { fluid_ingredient_shortage = true, no_input_fluid = true }
local FULL = { waiting_for_space_in_destination = true, full_output = true }

-- For the audit: the lines behind machines missing a fluid (traced from the empty input) and behind pumpjacks or
-- offshore pumps that can't push theirs out (traced from the output), one per line, up to `limit`.
function fluids.breaks(s, f, limit)
  local out, walked = {}, {}
  local cands = {}
  for _, e in pairs(s.find_entities_filtered { force = f, type = { 'assembling-machine', 'furnace', 'boiler',
    'generator', 'mining-drill', 'offshore-pump', 'fusion-reactor', 'reactor' } }) do
    local st = status_of(e)
    if st and (STARVED[st] or (FULL[st] and e.type ~= 'assembling-machine' and e.type ~= 'furnace')) and e.fluidbox
        and #e.fluidbox > 0 then
      cands[#cands + 1] = { e = e, st = st }
    end
  end
  -- starved machines first: they name the fluid that's missing
  table.sort(cands, function(a, b) return (STARVED[a.st] and 0 or 1) < (STARVED[b.st] and 0 or 1) end)
  for _, c in ipairs(cands) do
    if #out >= limit then break end
    local e, fb = c.e, c.e.fluidbox
    for i = 1, #fb do
      local kind = box_kind(fb, i)
      local fl, amt = box_fluid(fb, i)
      local want = STARVED[c.st] and (kind == 'input' or kind == 'input-output') and amt < 1
      local push = FULL[c.st] and kind == 'output'
      if (want or push) and not walked[key(e, i)] then
        local net, units = walk(e, i, 6000)
        local dup = false
        for u in pairs(units) do if walked[u] then dup = true break end end
        for u in pairs(units) do walked[u] = true end
        walked[key(e, i)] = true
        if not dup then
          net.port = { index = i, kind = kind, fluid = fl }
          out[#out + 1] = { machine = member(e), why = want and 'missing' or 'full', fluid = fl, line = net }
        end
        break
      end
    end
  end
  return out
end

-- Every segment of the force's pipes longer than EXTENT: where it runs and what it holds.
function fluids.long_segments(s, f, limit)
  local segs = {}
  for _, e in pairs(s.find_entities_filtered { force = f, type = { 'pipe', 'pipe-to-ground' } }) do
    local okG, sid = pcall(e.fluidbox.get_fluid_segment_id, 1)
    if okG and sid then
      local x, y = e.position.x, e.position.y
      local sb = segs[sid]
      if not sb then
        sb = { x0 = x, y0 = y, x1 = x, y1 = y, n = 0 }
        segs[sid] = sb
      end
      sb.x0, sb.y0, sb.x1, sb.y1 = math.min(sb.x0, x), math.min(sb.y0, y), math.max(sb.x1, x), math.max(sb.y1, y)
      sb.n = sb.n + 1
      if not sb.fluid then
        local fl = e.fluidbox[1]
        if fl then sb.fluid = fl.name end
      end
    end
  end
  local out = {}
  for _, sb in pairs(segs) do
    local span = math.max(sb.x1 - sb.x0, sb.y1 - sb.y0) + 1
    if span > fluids.EXTENT then
      out[#out + 1] = { span = math.floor(span), pipes = sb.n, fluid = sb.fluid, from = { sb.x0, sb.y0 }, to = { sb.x1, sb.y1 } }
    end
  end
  table.sort(out, function(a, b) return a.span > b.span end)
  while #out > limit do table.remove(out) end
  return out
end

return fluids
