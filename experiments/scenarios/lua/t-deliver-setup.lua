-- t-deliver setup (stage S3): an empty iron chest on open ground near the base. The player wants 20 inserters and
-- 50 transport belts in it: from the base's stock chests, or crafted. Met = the chest holds both.
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
local ox, oy = find(4, 4, 20)
if not ox then error("no free 4x4 area") end
clear(ox, oy, 4, 4)
local chest = put("iron-chest", ox + 1.5, oy + 1.5)
storage.bench_deliver = { chest = chest }
return { gx = math.floor(ox + 1.5), gy = math.floor(oy + 1.5) }
