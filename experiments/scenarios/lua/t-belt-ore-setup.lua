-- t-belt-ore: 4 electric drills on a small iron patch drop onto a short belt stub that goes nowhere; 26 tiles east,
-- 5 fuelled stone furnaces wait on an empty input belt. Between them: a long north-south belt and a few trees.
-- Layout (X, Y = top-left of the patch): drills face south at y 1.5, their stub runs east along y 3.5 to x 15.5;
-- the furnace input belt runs east along y 5.5 from x 40.5; furnaces at y 8, inserters y 6.5 (in) and 10.5 (out).
local ox, oy = find(66, 30)
X, Y = ox + 8, oy + 10
clear(ox, oy, ox + 66, oy + 30)
for x = -1, 13 do for y = -1, 3 do s.create_entity { name = "iron-ore", position = { X + x + 0.5, Y + y + 0.5 }, amount = 4000 } end end
grid(-4, 1)
put("small-electric-pole", -1.5, -1.5)
put("small-electric-pole", 4.5, -1.5)
put("small-electric-pole", 10.5, -1.5)
for k = 0, 3 do put("electric-mining-drill", 1.5 + 3 * k, 1.5, D.south) end
for x = 0, 15 do put("transport-belt", x + 0.5, 3.5, D.east) end
-- the stub is already backed up: the drills are stalled until their ore goes somewhere
for x = 0, 15 do
  local b = s.find_entity("transport-belt", { X + x + 0.5, Y + 3.5 })
  for i = 1, 2 do
    local l, k = b.get_transport_line(i), 0
    while k < 20 and l.can_insert_at_back() do l.insert_at_back { name = "iron-ore", count = 1 } k = k + 1 end
  end
end
-- the obstacle: a belt someone else uses, running the whole height of the area
for y = -9, 18 do put("transport-belt", 24.5, y + 0.5, D.south) end
for _, p in pairs { { 18.3, 2.7 }, { 20.6, 4.2 }, { 29.4, 3.1 }, { 31.8, 5.6 }, { 34.2, 2.4 }, { 27.1, 6.8 } } do
  s.create_entity { name = "tree-01", position = { X + p[1], Y + p[2] } }
end
local FX = 41
grid(FX + 13, 8)
for x = FX - 0.5, FX + 10.5 do put("transport-belt", x, 5.5, D.east) end
for k = 0, 4 do
  local cx = FX + 1 + 2 * k
  local fu = put("stone-furnace", cx, 8)
  fu.insert { name = "coal", count = 50 }
  put("inserter", cx - 0.5, 6.5, D.north) -- picks from the belt (north), drops into the furnace
  put("inserter", cx - 0.5, 10.5, D.north) -- picks from the furnace, drops into the chest
  put("wooden-chest", cx - 0.5, 11.5)
end
for _, px in pairs { FX + 1.5, FX + 5.5, FX + 9.5, FX + 12.5 } do
  put("small-electric-pole", px, 6.5)
  put("small-electric-pole", px, 10.5)
end
storage.bench_belt_ore = { area = { { ox, oy }, { ox + 66, oy + 30 } }, drills = { { X - 1, Y - 1 }, { X + 13, Y + 4 } },
  furnaces = { { X + FX, Y + 4 }, { X + FX + 11, Y + 10 } }, X = X, Y = Y, FX = FX }
return { drills = gps(6, 1), furnaces = gps(FX + 5, 8) }
