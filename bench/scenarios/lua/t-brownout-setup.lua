-- t-brownout setup (stage S3): a little steam plant (offshore pump on a pond, 1 coal boiler fed by an inserter
-- from a coal belt, 1 steam engine = 0.9 MW) powering 8 engine-unit assemblers plus a fixed 1.5 MW load (an energy
-- interface standing in for the rest of the factory): ~2.7 MW asked of 0.9 MW. Met = all 8 assemblers back to
-- full speed with the load still there, i.e. more steam (boilers + engines, coal by belt).
local s, f = game.surfaces.nauvis, game.forces.player
local function free(x, y, w, h)
  local a = { { x, y }, { x + w, y + h } }
  if s.count_tiles_filtered { area = a, collision_mask = "water_tile" } > 0 then return false end
  return s.count_entities_filtered { area = a, type = { "tree", "simple-entity", "resource", "corpse", "fish" },
    invert = true } == 0 and s.count_entities_filtered { area = a, type = "resource" } == 0
end
local function find(w, h, r0)
  for r = r0, 240, 4 do
    for _, d in pairs { { 1, 0 }, { 0, 1 }, { -1, 0 }, { 0, -1 }, { 1, 1 }, { -1, 1 }, { 1, -1 }, { -1, -1 } } do
      local x, y = d[1] * r, d[2] * r
      if free(x, y, w, h) then return x, y end
    end
  end
end
local function clear(x, y, w, h)
  for _, e in pairs(s.find_entities_filtered { area = { { x, y }, { x + w, y + h } }, type = { "tree", "simple-entity" } }) do
    e.destroy()
  end
end
local function put(name, x, y, dir, extra)
  local spec = { name = name, position = { x, y }, direction = dir, force = f }
  for k, v in pairs(extra or {}) do spec[k] = v end
  local e = s.create_entity(spec)
  if not e then error("could not place " .. name .. " at " .. x .. "," .. y) end
  return e
end
local function source(x, y, item) -- an infinity chest that never runs out
  local c = put("infinity-chest", x, y)
  c.set_infinity_container_filter(1, { name = item, count = 100, mode = "exactly", index = 1 })
  return c
end
local N, E, S, W = defines.direction.north, defines.direction.east, defines.direction.south, defines.direction.west
local ox, oy = find(40, 24, 40)
if not ox then error("no free 40x24 area") end
clear(ox, oy, 40, 24)
local X, Y = ox + 7, oy + 4
local t = {}
for x = X - 6, X - 1 do for y = Y, Y + 6 do t[#t + 1] = { name = "water", position = { x, y } } end end
s.set_tiles(t)
put("offshore-pump", X + 0.5, Y + 3.5, W)
put("pipe", X + 1.5, Y + 3.5)
local boiler = put("boiler", X + 3.5, Y + 3, N)
put("steam-engine", X + 3.5, Y - 0.5, N)
put("inserter", X + 3.5, Y + 4.5, S) -- coal from the belt into the boiler
for x = 2, 9 do put("transport-belt", X + x + 0.5, Y + 5.5, W) end
source(X + 9.5, Y + 7.5, "coal")
put("inserter", X + 9.5, Y + 6.5, S)
boiler.insert { name = "coal", count = 20 }
-- the load: 8 engine-unit assemblers (slow recipe, so only power limits them; parts in from infinity chests,
-- engines out into a chest that deletes them)
for row = 0, 1 do
  for k = 0, 3 do
    local ax, ay = X + 13.5 + 4 * k, Y + 1.5 + 8 * row
    put("assembling-machine-2", ax, ay).set_recipe("engine-unit")
    local parts = source(ax, ay - 3, "steel-plate")
    parts.set_infinity_container_filter(2, { name = "iron-gear-wheel", count = 100, mode = "exactly", index = 2 })
    parts.set_infinity_container_filter(3, { name = "pipe", count = 100, mode = "exactly", index = 3 })
    put("inserter", ax, ay - 2, N)
    put("inserter", ax, ay + 2, N)
    local sink = put("infinity-chest", ax, ay + 3)
    sink.set_infinity_container_filter(1, { name = "engine-unit", count = 0, mode = "exactly", index = 1 })
  end
end
local load = put("electric-energy-interface", X + 30, Y + 6)
load.power_production, load.power_usage, load.electric_buffer_size = 0, 25000, 100000 -- 25 kJ/tick = 1.5 MW
-- poles: by the plant, then down the gaps between the assembler columns
for _, p in pairs { { 5.5, 1.5 }, { 5.5, 4.5 }, { 10.5, 6.5 }, { 11.5, 1.5 }, { 11.5, 5.5 }, { 11.5, 9.5 },
  { 15.5, 1.5 }, { 19.5, 1.5 }, { 23.5, 1.5 }, { 27.5, 1.5 }, { 15.5, 9.5 }, { 19.5, 9.5 }, { 23.5, 9.5 },
  { 27.5, 9.5 }, { 27.5, 5.5 } } do
  put("small-electric-pole", X + p[1], Y + p[2])
end
storage.bench_brownout = { area = { { X - 1, Y - 6 }, { X + 34, Y + 18 } }, load = load, origin = { X, Y } }
return { gx = math.floor(X + 18), gy = math.floor(Y + 5) }
