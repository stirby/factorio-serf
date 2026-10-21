-- d4-library setup (stage S3): the player's own smelter design, "my-smelter", taught to the serf before the run.
-- Builds it once on open ground, blueprints it, removes it again (so the serf can't just copy it), and finds an open
-- spot for two more. Returns learn = {name = blueprint string} (bench feeds it to /serf learn) and where to build.
-- my-smelter, 12x6: ore belt east along the top, 6 stone furnaces fed and emptied by inserters, plates belt east
-- along the bottom, 6 small poles. 48 entities.
local s, f = game.surfaces.nauvis, game.forces.player
local function free(x, y, w, h)
  local a = { { x, y }, { x + w, y + h } }
  if s.count_tiles_filtered { area = a, collision_mask = "water_tile" } > 0 then return false end
  return s.count_entities_filtered { area = a, type = { "tree", "simple-entity", "resource", "corpse", "fish" },
    invert = true } == 0 and s.count_entities_filtered { area = a, type = "resource" } == 0
end
local function find(w, h, r0, skip)
  for r = r0, 200, 4 do
    for _, d in pairs { { 1, 0 }, { 0, 1 }, { -1, 0 }, { 0, -1 }, { 1, 1 }, { -1, 1 }, { 1, -1 }, { -1, -1 } } do
      local x, y = d[1] * r, d[2] * r
      if not (skip and math.abs(x - skip[1]) < 60 and math.abs(y - skip[2]) < 30) and free(x, y, w, h) then
        return x, y
      end
    end
  end
end
local ox, oy = find(14, 8, 40)
if not ox then error("no free 14x8 area for the reference build") end
local X, Y = ox + 1, oy + 1
local made = {}
local function put(name, x, y, dir)
  for _, e in pairs(s.find_entities_filtered { position = { X + x, Y + y }, radius = 1.5, type = { "tree", "simple-entity" } }) do
    e.destroy()
  end
  local e = s.create_entity { name = name, position = { X + x, Y + y }, direction = dir, force = f }
  if not e then error("could not place " .. name .. " at " .. (X + x) .. "," .. (Y + y)) end
  made[#made + 1] = e
end
for i = 0, 11 do
  put("transport-belt", i + 0.5, 0.5, defines.direction.east)
  put("transport-belt", i + 0.5, 5.5, defines.direction.east)
end
for k = 0, 5 do
  local cx = 1 + 2 * k
  put("inserter", cx - 0.5, 1.5, defines.direction.north) -- takes from the ore belt, drops into the furnace
  put("stone-furnace", cx, 3)
  put("inserter", cx - 0.5, 4.5, defines.direction.north) -- takes from the furnace, drops onto the plate belt
end
for _, px in pairs { 1.5, 5.5, 9.5 } do
  put("small-electric-pole", px, 1.5)
  put("small-electric-pole", px, 4.5)
end
local inv = game.create_inventory(1)
inv[1].set_stack { name = "blueprint" }
inv[1].create_blueprint { surface = s, force = f, area = { { X - 0.5, Y - 0.5 }, { X + 12.5, Y + 6.5 } } }
inv[1].label = "My smelter"
local str = inv[1].export_stack()
local n = inv[1].get_blueprint_entity_count()
inv.destroy()
for _, e in pairs(made) do e.destroy() end
local tx, ty = find(34, 10, 24, { ox, oy })
if not tx then error("no free 34x10 area for the two copies") end
storage.bench_lib = { area = { { tx - 12, ty - 12 }, { tx + 46, ty + 22 } } }
return { learn = { ["my-smelter"] = str }, entities = n, tx = math.floor(tx + 2), ty = math.floor(ty + 2) }
