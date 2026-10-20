-- Shared helpers for the t-* logistics micro scenarios (pasted at the top of each setup_lua by t-logistics-gen.py).
-- find(w, h): an open w x h area away from the base (no water, ore or buildings; trees and rocks are cleared).
-- put(name, x, y, dir, extra): create a player-force entity at X+x, Y+y or fail loudly.
local s, f = game.surfaces.nauvis, game.forces.player
local D = defines.direction
local function open(x, y, w, h)
  local a = { { x, y }, { x + w, y + h } }
  for _, c in pairs { { x, y }, { x + w, y }, { x, y + h }, { x + w, y + h } } do
    if not s.is_chunk_generated { math.floor(c[1] / 32), math.floor(c[2] / 32) } then return false end
  end
  if s.count_tiles_filtered { area = a, collision_mask = "water_tile" } > 0 then return false end
  if s.count_entities_filtered { area = a, type = "resource" } > 0 then return false end
  return s.count_entities_filtered { area = a, invert = true,
    type = { "tree", "simple-entity", "corpse", "fish", "item-entity", "character" } } == 0
end
local function find(w, h, r0)
  for r = r0 or 50, 260, 6 do
    for _, d in pairs { { 1, 0 }, { 0, 1 }, { -1, 0 }, { 0, -1 }, { 1, 1 }, { -1, 1 }, { 1, -1 }, { -1, -1 } } do
      local x, y = d[1] * r, d[2] * r
      if open(x, y, w, h) then return x, y end
    end
  end
  error("no open " .. w .. "x" .. h .. " area")
end
local X, Y
local function clear(x1, y1, x2, y2)
  for _, e in pairs(s.find_entities_filtered { area = { { x1, y1 }, { x2, y2 } },
    type = { "tree", "simple-entity", "item-entity", "corpse" } }) do e.destroy() end
end
local function put(name, x, y, dir, extra)
  local spec = { name = name, position = { X + x, Y + y }, direction = dir, force = f }
  for k, v in pairs(extra or {}) do spec[k] = v end
  local e = s.create_entity(spec)
  if not e then error("could not place " .. name .. " at " .. (X + x) .. "," .. (Y + y)) end
  return e
end
local function grid(x, y) -- an always-on power source with its own pole, like a corner of the main grid
  local e = put("electric-energy-interface", x, y)
  e.power_production, e.electric_buffer_size = 100000, 10000000 -- 6 MW
  return e
end
local function gps(x, y) return math.floor(X + x) .. "," .. math.floor(Y + y) end
