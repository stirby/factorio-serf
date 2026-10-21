-- t-smelter-column: an ore belt (iron ore on the south lane, coal on the north lane, like a mixed mining belt) runs
-- east past open ground, with grid poles along its north side; a chest with its inserter waits 12 tiles south.
-- The task: 8 stone furnaces fed from the belt, plates out on a belt to that chest.
-- Sources at the west end: infinity chests and inserters (2 fast inserters for ore, 1 inserter for coal).
local ox, oy = find(50, 28)
X, Y = ox + 4, oy + 8
clear(ox, oy, ox + 50, oy + 28)
grid(4, -3)
local function source(item, x, y, name)
  local c = put("infinity-chest", x, y)
  c.set_infinity_container_filter(1, { name = item, count = 100, mode = "at-least" })
end
source("iron-ore", 0.5, -1.5) put("fast-inserter", 0.5, -0.5, D.north) -- drops on the far (south) lane
source("iron-ore", 1.5, -1.5) put("fast-inserter", 1.5, -0.5, D.north)
source("coal", 0.5, 2.5) put("inserter", 0.5, 1.5, D.south) -- drops on the far (north) lane
for x = 0, 40 do put("transport-belt", x + 0.5, 0.5, D.east) end
put("small-electric-pole", 2.5, -1.5)
put("small-electric-pole", 1.5, 2.5)
for _, x in pairs { 8.5, 14.5, 20.5, 26.5, 32.5, 38.5 } do put("small-electric-pole", x, -2.5) end
local dest = put("iron-chest", 28.5, 14.5)
local ins = put("fast-inserter", 28.5, 13.5, D.north) -- picks from (28.5, 12.5), drops into the chest
grid(31, 15)
put("small-electric-pole", 29.5, 13.5)
storage.bench_smelt = { area = { { X - 1, Y + 1 }, { X + 42, Y + 13 } }, dest = dest, ins = ins, X = X, Y = Y }
return { ore = gps(20, 0.5), chest = gps(28.5, 14.5) }
