-- x-outpost setup: a delivery point near spawn (a steel chest filled by a fast inserter from the end of a 3-tile
-- belt stub, a grid corner, and a supply chest with drills, belts, undergrounds and poles) and a fresh iron patch
-- ~250 tiles away. Met = >= 60 ore/min arriving in the chest and electric drills on the patch working on the
-- delivery point's grid.
local dx, dy
if LAB then dx, dy = find_near(-140, -4, 10, 8, 40) else dx, dy = find_ring(10, 8, 30, 140) end
clear(dx, dy, 10, 8)
local X, Y = dx + 1, dy + 1
local chest = put("steel-chest", X + 0.5, Y + 0.5)
put("fast-inserter", X + 1.5, Y + 0.5, D.east)
for x = 2, 4 do put("transport-belt", X + x + 0.5, Y + 0.5, D.west) end
grid(X + 1, Y + 3, 3000000)
local pole = put("medium-electric-pole", X + 2.5, Y + 2.5)
local supply = put("steel-chest", X + 0.5, Y + 4.5)
for name, n in pairs { ["electric-mining-drill"] = 10, ["transport-belt"] = 350, ["underground-belt"] = 20,
  ["medium-electric-pole"] = 45, ["splitter"] = 4 } do
  supply.insert { name = name, count = n }
end

-- the patch: 12x12 of iron ore ~250 tiles from the delivery point, in the first direction with open ground
local px, py
local dirs = LAB and { { 1, 0 } } or { { 1, 0 }, { 0, 1 }, { 0, -1 }, { -1, 0 }, { 0.7, 0.7 }, { 0.7, -0.7 },
  { -0.7, 0.7 }, { -0.7, -0.7 } }
for _, d in pairs(dirs) do
  local ok, x, y = pcall(find_near, X + d[1] * 250, Y + d[2] * 250, 16, 16, 40)
  if ok then px, py = x, y break end
end
if not px then error("no open ground for the ore patch") end
clear(px, py, 16, 16)
for x = px + 2, px + 13 do
  for y = py + 2, py + 13 do s.create_entity { name = "iron-ore", position = { x + 0.5, y + 0.5 }, amount = 3000 } end
end
storage.bench_outpost = { chest = chest, pole = pole, patch = { { px, py }, { px + 16, py + 16 } }, X = X, Y = Y }
return { patch = gps(px + 8, py + 8), chest = gps(X + 3, Y), supply = gps(X, Y + 4),
  dist = math.floor(math.sqrt((px + 8 - X) ^ 2 + (py + 8 - Y) ^ 2)) }
