-- t-cross-bus: copper plates come out onto a short belt stub on the west side of a 4-lane main bus (4 parallel belts
-- running north-south, 45 tiles long, carrying iron); the chest that needs them is on the east side, with its
-- inserter already in place. The task: get copper to the chest without cutting the bus (undergrounds fit exactly,
-- or go around the end).
local ox, oy = find(52, 52)
X, Y = ox + 4, oy + 24
clear(ox, oy, ox + 52, oy + 52)
grid(0, 5)
put("small-electric-pole", 2.5, 4.5)
local src = put("infinity-chest", 2.5, 2.5)
src.set_infinity_container_filter(1, { name = "copper-plate", count = 100, mode = "at-least" })
put("inserter", 3.5, 2.5, D.west) -- picks from the chest (west), drops onto the stub (east)
for x = 4, 7 do put("transport-belt", x + 0.5, 2.5, D.east) end
for bx = 20, 23 do
  for y = -20, 24 do put("transport-belt", bx + 0.5, y + 0.5, D.south) end
end
-- the bus is in use: iron on every lane, backed up at its south end
for bx = 20, 23 do
  for y = 14, 24 do
    local b = s.find_entity("transport-belt", { X + bx + 0.5, Y + y + 0.5 })
    for i = 1, 2 do
      local l, k = b.get_transport_line(i), 0
      while k < 20 and l.can_insert_at_back() do l.insert_at_back { name = "iron-plate", count = 1 } k = k + 1 end
    end
  end
end
grid(43, 5)
put("small-electric-pole", 41.5, 4.5)
local dest = put("iron-chest", 41.5, 2.5)
local ins = put("inserter", 40.5, 2.5, D.west) -- picks from x 39.5 (west), drops into the chest
storage.bench_bus = { dest = dest, ins = ins, bus = { { X + 20, Y - 20 }, { X + 24, Y + 25 } }, X = X, Y = Y }
return { stub = gps(7.5, 2.5), chest = gps(41.5, 2.5) }
