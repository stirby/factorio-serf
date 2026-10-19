-- d3b-circuit-mall setup (stage S6): an inserter "mall" that needs green circuits and gets none. Two
-- assembling-machine-2 making inserters (90/min each = 180 circuits/min of demand). Iron plates and gears come
-- from infinity chests, finished inserters go into a deleting chest, power from a hidden interface: the only
-- missing input is circuits, on the mall's input belt (flowing east along the top). Returns where things are.
local s, f = game.surfaces.nauvis, game.forces.player
local W, H = 16, 12
local function free(x, y)
  local a = { { x, y }, { x + W, y + H } }
  if s.count_tiles_filtered { area = a, collision_mask = "water_tile" } > 0 then return false end
  return s.count_entities_filtered { area = a, type = { "tree", "simple-entity", "resource", "corpse", "fish" },
    invert = true } == 0
end
local ox, oy
for r = 20, 160, 4 do
  for _, d in pairs { { 1, 0 }, { 0, 1 }, { -1, 0 }, { 0, -1 }, { 1, 1 }, { -1, 1 }, { 1, -1 }, { -1, -1 } } do
    local x, y = 20 + d[1] * r, 20 + d[2] * r
    if not ox and free(x, y) then ox, oy = x, y end
  end
  if ox then break end
end
if not ox then error("no free 16x12 area for the mall") end
for _, e in pairs(s.find_entities_filtered { area = { { ox, oy }, { ox + W, oy + H } }, type = { "tree", "simple-entity" } }) do
  e.destroy()
end
local X, Y = ox + 1, oy + 1 -- one tile of margin
local function put(name, x, y, dir)
  local e = s.create_entity { name = name, position = { X + x, Y + y }, direction = dir, force = f }
  if not e then error("could not place " .. name .. " at " .. (X + x) .. "," .. (Y + y)) end
  e.minable = false -- the scenario's fixture, not the agent's materials
  return e
end
local belt = {}
for i = 0, 12 do belt[#belt + 1] = put("transport-belt", i + 0.5, 0.5, defines.direction.east) end
local asms = {}
for _, cx in pairs { 4.5, 9.5 } do
  put("fast-inserter", cx, 1.5, defines.direction.north) -- takes from the belt (north), drops into the assembler
  local a = put("assembling-machine-2", cx, 3.5)
  a.set_recipe("inserter")
  asms[#asms + 1] = a
  put("fast-inserter", cx, 5.5, defines.direction.north) -- takes from the assembler, drops south
  local sink = put("infinity-chest", cx, 6.5)
  sink.remove_unfiltered_items = true
end
for _, side in pairs { { 1.5, 2.5, defines.direction.west }, { 12.5, 11.5, defines.direction.east } } do
  local chest = put("infinity-chest", side[1], 3.5)
  chest.set_infinity_container_filter(1, { name = "iron-plate", count = 100, mode = "exactly" })
  chest.set_infinity_container_filter(2, { name = "iron-gear-wheel", count = 100, mode = "exactly" })
  put("fast-inserter", side[2], 3.5, side[3])
end
local sub = put("substation", 7, 8)
for _, c in pairs { defines.wire_connector_id.pole_copper } do -- don't wire into the base's grid
  local w = sub.get_wire_connector(c, false)
  if w then w.disconnect_all() end
end
local eei = put("electric-energy-interface", 7, 10)
eei.power_production = 50000 -- J/tick = 3 MW
eei.electric_buffer_size = 5000000
eei.destructible = false
storage.bench_mall = { asm = { asms[1].position, asms[2].position }, belt = { X + 0.5, Y + 0.5 },
  center = { X + 7, Y + 4 } }
return { mx = math.floor(X + 7), my = math.floor(Y + 4), bx = math.floor(X + 0.5), by = math.floor(Y + 0.5),
  powered = asms[1].electric_network_id ~= nil and asms[1].electric_network_id == eei.electric_network_id }
