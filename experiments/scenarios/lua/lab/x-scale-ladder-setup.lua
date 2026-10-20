-- x-scale-ladder: seven column sites in a row, 16 tiles apart. Each has a full belt of iron ore and coal running
-- south (ore on one lane, coal on the other) and an empty output chest at its foot. Objective 1 asks for one 8-furnace column (site 1), objective 2 for two
-- more (sites 2-3), objective 3 for four more (sites 4-7). A grid pole and a supply chest at the west end.
X, Y = 12, 8
local sites = {}
for i = 1, 7 do
  local sx = (i - 1) * 16
  feed({ "iron-ore", "coal" }, sx, -2, "south", 22)
  put("wooden-chest", sx + 4.5, 22.5)
  sites[i] = { box = { { X + sx - 6, Y - 4 }, { X + sx + 10, Y + 26 } }, gps = gps(sx, 0), chest = gps(sx + 4, 22) }
end
local pole = grid(-12, 6)
supply(-12, 0)
storage.bench_ladder = { sites = sites, X = X, Y = Y, seen = {}, plates = {} }
local out = { supply = gps(-12, 0), pole = math.floor(pole.position.x) .. "," .. math.floor(pole.position.y) }
for i, st in ipairs(sites) do out["s" .. i] = st.gps out["c" .. i] = st.chest end
return out
