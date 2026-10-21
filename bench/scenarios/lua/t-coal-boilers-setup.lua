-- t-coal-boilers: a boiler with two steam engines (water from a pipe, a steady 1 MW load) that's been hand-fed and is
-- about to run dry; 28 tiles west, two burner drills on coal drop onto a belt stub that goes nowhere (backed up).
-- The task: belt the coal to the boiler. Passes when the boiler burns, an inserter feeds it from a belt, and the
-- coal drills keep working (their stub would back up otherwise).
local ox, oy = find(54, 26)
X, Y = ox + 6, oy + 12
clear(ox, oy, ox + 54, oy + 26)
for x = 0, 3 do for y = 0, 1 do s.create_entity { name = "coal", position = { X + x + 0.5, Y + y + 0.5 }, amount = 5000 } end end
for _, cx in pairs { 1, 3 } do
  local d = put("burner-mining-drill", cx, 1, D.south)
  d.insert { name = "coal", count = 50 }
end
for x = 0, 7 do put("transport-belt", x + 0.5, 2.5, D.east) end
for x = 0, 7 do
  local b = s.find_entity("transport-belt", { X + x + 0.5, Y + 2.5 })
  for i = 1, 2 do
    local l, k = b.get_transport_line(i), 0
    while k < 20 and l.can_insert_at_back() do l.insert_at_back { name = "coal", count = 1 } k = k + 1 end
  end
end
local BX = 36.5
local boiler = put("boiler", BX, 2, D.north)
boiler.insert { name = "coal", count = 5 }
local water = put("infinity-pipe", BX - 2, 2.5)
water.set_infinity_pipe_filter { name = "water", percentage = 1, mode = "at-least" }
put("steam-engine", BX, -1.5, D.north)
put("steam-engine", BX, -6.5, D.north)
put("small-electric-pole", BX + 2, -1.5)
local load = put("electric-energy-interface", BX + 4, -3)
load.power_production, load.power_usage, load.electric_buffer_size = 0, 1000000 / 60, 1000000
storage.bench_coal = { boiler = boiler, drills = { { X - 1, Y - 1 }, { X + 5, Y + 3 } }, X = X, Y = Y, BX = BX }
return { coal = gps(4, 2.5), boiler = gps(BX, 2) }
