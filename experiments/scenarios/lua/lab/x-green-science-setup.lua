-- x-green-science: belts of iron plate and copper plate (full, both lanes) running east, a supply chest of building
-- materials, a grid pole. The serf builds gears, cables, circuits, inserters and belts into logistic science packs.
X, Y = 12, 8
feed({ "iron-plate" }, 0, 0, "east", 40)
feed({ "copper-plate" }, 0, 12, "east", 40)
local pole = grid(-10, 6)
supply(2, -5)
storage.bench_green = { area = { { X - 12, Y - 8 }, { X + 48, Y + 50 } }, X = X, Y = Y }
return { fe = gps(0, 0), cu = gps(0, 12), supply = gps(2, -5),
  pole = math.floor(pole.position.x) .. "," .. math.floor(pole.position.y) }
