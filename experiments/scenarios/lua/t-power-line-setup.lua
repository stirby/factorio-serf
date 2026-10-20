-- t-power-line: a block of 4 gear assemblers, wired up inside (its own poles) but not connected to anything, 48
-- tiles east of a pole on the grid. A 4-wide stream runs north-south between them.
-- Each assembler: infinity chest of iron plates -> fast inserter -> assembler -> inserter -> a chest that empties itself
-- (a stand-in for "the rest of the factory"), so it keeps working once it has power.
local ox, oy = find(72, 38)
X, Y = ox + 5, oy + 17
clear(ox, oy, ox + 72, oy + 38)
local water = {}
for x = 20, 23 do for y = -16, 20 do water[#water + 1] = { name = "water", position = { X + x, Y + y } } end end
s.set_tiles(water)
grid(0, 0)
local gp = put("small-electric-pole", 1.5, -1.5)
local BX = 46
for k = 0, 3 do
  local x0 = BX + 5 * k
  local src = put("infinity-chest", x0 + 1.5, -2.5)
  src.set_infinity_container_filter(1, { name = "iron-plate", count = 100, mode = "at-least" })
  put("fast-inserter", x0 + 1.5, -1.5, D.north)
  local a = put("assembling-machine-1", x0 + 1.5, 0.5)
  a.set_recipe("iron-gear-wheel")
  put("fast-inserter", x0 + 1.5, 2.5, D.north)
  local sink = put("infinity-chest", x0 + 1.5, 3.5)
  sink.remove_unfiltered_items = true
  put("small-electric-pole", x0 + 3.5, -1.5)
  put("small-electric-pole", x0 + 3.5, 2.5)
end
storage.bench_power = { block = { { X + BX - 1, Y - 4 }, { X + BX + 21, Y + 5 } }, pole = gp, X = X, Y = Y }
return { block = gps(BX + 9, 0), pole = gps(1.5, -1.5) }
