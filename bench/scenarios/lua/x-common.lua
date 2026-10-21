-- Shared helpers for the x-* harder scenarios (pasted at the top of each setup_lua by x-gen.py). Positions are
-- absolute; each setup picks its own origin with find_near/find_ring and adds offsets.
-- open(x, y, w, h): no water, ore or buildings in the box (trees and rocks get cleared).
-- find_near(cx, cy, w, h, rmax): the open box nearest to cx,cy (spiral search), generating chunks as needed.
-- find_ring(w, h, r0, r1): an open box between r0 and r1 tiles from the origin.
local s, f = game.surfaces.nauvis, game.forces.player
local D = defines.direction
local LAB = s.get_tile(200, 200).name == "landfill" -- the flat lab stage (448x448 landfill around spawn)
local function gen(x, y, w, h)
  local need = false
  for cx = math.floor(x / 32), math.floor((x + w) / 32) do
    for cy = math.floor(y / 32), math.floor((y + h) / 32) do
      if not s.is_chunk_generated { cx, cy } then
        s.request_to_generate_chunks({ cx * 32 + 16, cy * 32 + 16 }, 0)
        need = true
      end
    end
  end
  if need then s.force_generate_chunk_requests() end
end
local function open(x, y, w, h)
  gen(x, y, w, h)
  local a = { { x, y }, { x + w, y + h } }
  if s.count_tiles_filtered { area = a, collision_mask = "water_tile" } > 0 then return false end
  if s.count_entities_filtered { area = a, type = "resource" } > 0 then return false end
  if s.count_entities_filtered { area = a, type = "cliff" } > 0 then return false end
  return s.count_entities_filtered { area = a, invert = true,
    type = { "tree", "simple-entity", "corpse", "fish", "item-entity", "character" } } == 0
end
local function find_near(cx, cy, w, h, rmax)
  cx, cy = math.floor(cx), math.floor(cy)
  if open(cx, cy, w, h) then return cx, cy end
  for r = 4, rmax or 60, 4 do
    for i = -r, r, 4 do
      for _, p in pairs { { cx + i, cy - r }, { cx + i, cy + r }, { cx - r, cy + i }, { cx + r, cy + i } } do
        if open(p[1], p[2], w, h) then return p[1], p[2] end
      end
    end
  end
  error("no open " .. w .. "x" .. h .. " area near " .. cx .. "," .. cy)
end
local function find_ring(w, h, r0, r1)
  for r = r0, r1, 6 do
    for _, d in pairs { { 1, 0 }, { 0, 1 }, { -1, 0 }, { 0, -1 }, { 0.7, 0.7 }, { -0.7, 0.7 }, { 0.7, -0.7 },
      { -0.7, -0.7 } } do
      local x, y = math.floor(d[1] * r), math.floor(d[2] * r)
      if open(x, y, w, h) then return x, y end
    end
  end
  error("no open " .. w .. "x" .. h .. " area " .. r0 .. "-" .. r1 .. " tiles out")
end
local function clear(x, y, w, h)
  for _, e in pairs(s.find_entities_filtered { area = { { x, y }, { x + w, y + h } },
    type = { "tree", "simple-entity", "item-entity", "corpse" } }) do e.destroy() end
end
local function put(name, x, y, dir, extra)
  local spec = { name = name, position = { x, y }, direction = dir, force = f }
  for k, v in pairs(extra or {}) do spec[k] = v end
  local e = s.create_entity(spec)
  if not e then error("could not place " .. name .. " at " .. x .. "," .. y) end
  return e
end
local function source(x, y, items) -- an infinity chest that never runs out of each item in `items`
  local c = put("infinity-chest", x, y)
  for i, it in ipairs(items) do
    c.set_infinity_container_filter(i, { name = it, count = 50, mode = "exactly", index = i })
  end
  return c
end
local function sink(x, y) -- an infinity chest that deletes whatever goes in
  local c = put("infinity-chest", x, y)
  c.remove_unfiltered_items = true
  return c
end
local function grid(x, y, watts) -- an always-on power source, a corner of the main grid
  local e = put("electric-energy-interface", x, y)
  e.power_production, e.electric_buffer_size = (watts or 6000000) / 60, 10000000
  return e
end
local function gps(x, y) return math.floor(x) .. "," .. math.floor(y) end
