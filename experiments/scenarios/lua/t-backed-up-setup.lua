-- t-backed-up setup (stage S3): 4 stone furnaces on an ore belt (loaded from an infinity chest), fuelled for the
-- whole run, each emptying into its own wooden chest. The chests are full of plates and so are the furnaces, so
-- nothing smelts. Met = the 4 furnaces smelting again for 3 straight samples (any fix that frees their output).
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
local ox, oy = find(16, 12, 40)
if not ox then error("no free 16x12 area") end
clear(ox, oy, 16, 12)
local X, Y = ox + 4, oy + 3
local eei = put("electric-energy-interface", X - 2, Y + 3)
eei.power_production, eei.electric_buffer_size = 1000000, 5000000
source(X + 0.5, Y - 1.5, "iron-ore")
put("fast-inserter", X + 0.5, Y - 0.5, N)
for i = 0, 9 do put("transport-belt", X + i + 0.5, Y + 0.5, E) end
for k = 0, 3 do
  local fx = X + 2 + 2 * k
  local fur = put("stone-furnace", fx, Y + 3)
  fur.insert { name = "coal", count = 50 }
  fur.insert { name = "iron-ore", count = 50 }
  fur.get_output_inventory().insert { name = "iron-plate", count = 100 }
  put("inserter", fx - 0.5, Y + 1.5, N)
  put("inserter", fx - 0.5, Y + 4.5, N)
  local chest = put("wooden-chest", fx - 0.5, Y + 5.5)
  chest.insert { name = "iron-plate", count = 1600 }
end
for _, p in pairs { { -0.5, 1.5 }, { 2.5, 1.5 }, { 6.5, 1.5 }, { 2.5, 4.5 }, { 6.5, 4.5 } } do
  put("small-electric-pole", X + p[1], Y + p[2])
end
storage.bench_backed = { area = { { X - 4, Y - 3 }, { X + 12, Y + 8 } } }
return { gx = math.floor(X + 5), gy = math.floor(Y + 3) }
