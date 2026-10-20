-- t-stamp-book setup (stage S3): the player taught two designs before the run: "gear-cell" (2 gear assemblers
-- between an input belt and output chests) and "mini-smelter" (4 stone furnaces with inserters, ore belt on top,
-- plate belt below, 4 poles). Each is built once, blueprinted and removed again. The goal describes the smelter
-- without naming it, so the serf has to pick the right design from its library. Met = 4 furnaces and 8 powered
-- inserters around the target spot.
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
local function blueprint(name, label, x1, y1, x2, y2, made)
  local inv = game.create_inventory(1)
  inv[1].set_stack { name = "blueprint" }
  inv[1].create_blueprint { surface = s, force = f, area = { { x1, y1 }, { x2, y2 } } }
  inv[1].label = label
  local str, n = inv[1].export_stack(), inv[1].get_blueprint_entity_count()
  inv.destroy()
  for _, e in pairs(made) do e.destroy() end
  return str, n
end
local ox, oy = find(28, 10, 60)
if not ox then error("no free 28x10 area for the reference builds") end
clear(ox, oy, 28, 10)
local X, Y = ox + 1, oy + 1
-- mini-smelter, 8x6
local made = {}
local function add(e) made[#made + 1] = e return e end
for i = 0, 7 do
  add(put("transport-belt", X + i + 0.5, Y + 0.5, E))
  add(put("transport-belt", X + i + 0.5, Y + 5.5, E))
end
for k = 0, 3 do
  local cx = X + 1 + 2 * k
  add(put("inserter", cx - 0.5, Y + 1.5, N))
  add(put("stone-furnace", cx, Y + 3))
  add(put("inserter", cx - 0.5, Y + 4.5, N))
end
for _, px in pairs { 1.5, 5.5 } do
  add(put("small-electric-pole", X + px, Y + 1.5))
  add(put("small-electric-pole", X + px, Y + 4.5))
end
local smelter, n1 = blueprint("mini-smelter", "Mini smelter", X - 0.5, Y - 0.5, X + 8.5, Y + 6.5, made)
-- gear-cell, 8x6: iron belt on top, 2 gear assemblers, output inserters into chests below
made = {}
local G = X + 14
for i = 0, 7 do add(put("transport-belt", G + i + 0.5, Y + 0.5, E)) end
for k = 0, 1 do
  local ax = G + 1.5 + 4 * k
  add(put("assembling-machine-1", ax, Y + 3.5)).set_recipe("iron-gear-wheel")
  add(put("inserter", ax, Y + 1.5, N))
  add(put("inserter", ax, Y + 5.5, N))
  add(put("iron-chest", ax, Y + 6.5))
end
add(put("small-electric-pole", G + 3.5, Y + 1.5))
add(put("small-electric-pole", G + 3.5, Y + 5.5))
local cell, n2 = blueprint("gear-cell", "Gear cell", G - 0.5, Y - 0.5, G + 8.5, Y + 7.5, made)
local tx, ty = find(16, 10, 24)
if not tx then error("no free 16x10 area for the copy") end
storage.bench_book = { area = { { tx - 10, ty - 10 }, { tx + 26, ty + 20 } } }
return { learn = { ["mini-smelter"] = smelter, ["gear-cell"] = cell }, entities = { n1, n2 },
  tx = math.floor(tx + 2), ty = math.floor(ty + 2) }
