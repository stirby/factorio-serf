-- Shared helpers for the x-* lab scenarios (pasted at the top of each setup_lua by lab-gen.py). The lab stage is a
-- clean landfill square around spawn (0,0), so fixtures sit at a fixed origin X,Y instead of searching for space.
-- put(name, x, y, dir, extra): a player-force entity at X+x, Y+y, or fail loudly.
-- feed(items, x, y, dir, len): an input belt of `len` belts from tile (x,y) in direction dir ("east" or "south"),
--   full on both lanes: one item from an infinity chest + loader behind its start, or two items (one per lane)
--   side-loaded onto its first tile from both sides. Chests and loaders can't be mined or emptied by hand.
-- grid(x, y): an always-on power source and a medium pole at X+x, Y+y, like a corner of the main grid.
-- supply(x, y): steel chests of building materials (no plates or intermediates), the serf's stock for the job.
-- gps(x, y): "x,y" for a goal's [gps=...].
local s, f = game.surfaces.nauvis, game.forces.player
local D = defines.direction
local X, Y
local function put(name, x, y, dir, extra)
  local spec = { name = name, position = { X + x, Y + y }, direction = dir, force = f }
  for k, v in pairs(extra or {}) do spec[k] = v end
  local e = s.create_entity(spec)
  if not e then error("could not place " .. name .. " at " .. (X + x) .. "," .. (Y + y)) end
  return e
end
local function fixed(e)
  e.minable, e.destructible, e.operable = false, false, false
  return e
end
local function feed(items, x, y, dir, len)
  local dx, dy = (dir == "east") and 1 or 0, (dir == "south") and 1 or 0
  local d = (dir == "east") and D.east or D.south
  local function source(item, px, py, n) -- infinity chest at offset n, loader, then belts toward the start tile
    local face = px > 0 and D.west or px < 0 and D.east or py > 0 and D.north or D.south
    local c = fixed(put("infinity-chest", x + 0.5 + n * px, y + 0.5 + n * py))
    c.set_infinity_container_filter(1, { name = item, count = 100, mode = "exactly" })
    fixed(put("loader", x + 0.5 + (n - 1.5) * px, y + 0.5 + (n - 1.5) * py, face, { type = "output" }))
    for k = 1, n - 3 do put("transport-belt", x + 0.5 + k * px, y + 0.5 + k * py, face) end
  end
  if #items == 1 then
    source(items[1], -dx, -dy, 3)
  else -- a loader fills both lanes from its chest's first item only: side-load one item onto each lane
    source(items[1], -dy, -dx, 4)
    source(items[2], dy, dx, 4)
  end
  for i = 0, len - 1 do put("transport-belt", x + i * dx + 0.5, y + i * dy + 0.5, d) end
end
local function grid(x, y)
  local e = fixed(put("electric-energy-interface", x, y))
  e.power_production, e.electric_buffer_size = 166667, 10000000 -- 10 MW
  return put("medium-electric-pole", x + 2.5, y + 0.5)
end
local SUPPLY = {
  { "assembling-machine-2", 50 }, { "assembling-machine-1", 20 }, { "fast-inserter", 150 }, { "inserter", 150 },
  { "long-handed-inserter", 50 }, { "transport-belt", 600 }, { "underground-belt", 50 }, { "splitter", 20 },
  { "small-electric-pole", 100 }, { "medium-electric-pole", 50 }, { "stone-furnace", 100 }, { "steel-furnace", 20 },
  { "wooden-chest", 20 }, { "iron-chest", 20 },
}
local function supply(x, y)
  local i = 0
  local c = put("steel-chest", x + 0.5, y + 0.5)
  for _, it in ipairs(SUPPLY) do
    local left = it[2]
    while left > 0 do
      left = left - c.insert { name = it[1], count = left }
      if left > 0 then -- full: the next chest east
        i = i + 1
        c = put("steel-chest", x + 0.5 + i, y + 0.5)
      end
    end
  end
end
local function gps(x, y) return math.floor(X + x) .. "," .. math.floor(Y + y) end
