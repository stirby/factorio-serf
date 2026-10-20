-- x-red-circuits: belts of iron plate, copper plate and plastic bar (full, both lanes) running east, a supply chest
-- of building materials, a grid pole. The serf builds cables -> green circuits -> red circuits into a chest.
X, Y = 12, 8
feed({ "iron-plate" }, 0, 0, "east", 40)
feed({ "copper-plate" }, 0, 12, "east", 40)
feed({ "plastic-bar" }, 0, 24, "east", 40)
local pole = grid(-10, 12)
supply(2, -5)
storage.bench_red = { area = { { X - 12, Y - 8 }, { X + 48, Y + 50 } }, X = X, Y = Y }
return { fe = gps(0, 0), cu = gps(0, 12), pl = gps(0, 24), supply = gps(2, -5),
  pole = math.floor(pole.position.x) .. "," .. math.floor(pole.position.y) }
