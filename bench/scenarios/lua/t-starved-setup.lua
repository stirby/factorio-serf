-- t-starved setup (stage S3): a 3-assembler red science line, belt-fed (copper belt on top, gear belt below,
-- each loaded from an infinity chest), powered by an energy interface. One copper belt faces the wrong way, so all
-- three starve. The fix has to make them run on their own: hand-feeding doesn't count (score skips chest-fed ones).
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
local ox, oy = find(22, 14, 40)
if not ox then error("no free 22x14 area") end
clear(ox, oy, 22, 14)
local X, Y = ox + 4, oy + 2
local eei = put("electric-energy-interface", X - 1, Y + 4)
eei.power_production, eei.electric_buffer_size = 2000000, 10000000
source(X + 0.5, Y - 1.5, "copper-plate")
put("inserter", X + 0.5, Y - 0.5, N) -- picks from the chest to the north, drops on the copper belt
source(X + 0.5, Y + 8.5, "iron-gear-wheel")
put("inserter", X + 0.5, Y + 7.5, S)
for i = 0, 13 do
  put("transport-belt", X + i + 0.5, Y + 0.5, E)
  put("transport-belt", X + i + 0.5, Y + 6.5, E)
end
for k = 0, 2 do
  local ax = X + 3.5 + 4 * k
  local a = put("assembling-machine-1", ax, Y + 3.5)
  a.set_recipe("automation-science-pack")
  put("inserter", ax, Y + 1.5, N)
  put("inserter", ax, Y + 5.5, S)
end
for _, px in pairs { 1.5, 5.5, 9.5 } do
  put("small-electric-pole", X + px, Y + 1.5)
  put("small-electric-pole", X + px, Y + 5.5)
end
-- the fault: one copper belt turned back against the flow
s.find_entity("transport-belt", { X + 2.5, Y + 0.5 }).direction = W
storage.bench_starved = { area = { { X - 3, Y - 3 }, { X + 16, Y + 10 } }, bad = { X + 2.5, Y + 0.5 } }
return { gx = math.floor(X + 7), gy = math.floor(Y + 3) }
