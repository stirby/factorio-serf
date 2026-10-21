-- Turn a freshly created map into the LAB stage: a flat, empty 448x448 square of landfill around spawn (no trees,
-- rocks, ore, water or cliffs), mid-game research (assembling-machine-2, fast inserters, undergrounds, splitters,
-- advanced circuits, steel, electric drills, medium poles), and a small always-on power block at spawn.
-- Run through the mod's eval op by make_stage_lab.py. Fixtures bring their own grid corner (lab-common.lua).
local s, f = game.surfaces.nauvis, game.forces.player
local R = 224
local done = {}

-- Research: each target with all its prerequisites.
local function learn(name)
  local t = f.technologies[name]
  if not t or t.researched then return end
  for _, p in pairs(t.prerequisites) do learn(p.name) end
  t.researched = true
  done[#done + 1] = name
end
for _, t in ipairs { "automation-2", "fast-inserter", "logistics-2", "advanced-circuit", "steel-processing",
  "advanced-material-processing", "electric-mining-drill", "electric-energy-distribution-1", "logistic-science-pack",
  "lamp", "engine" } do learn(t) end
f.research_queue = {}

-- Flatten: landfill everywhere in the square, then nothing but player-force things on it.
s.request_to_generate_chunks({ 0, 0 }, R / 32 + 1)
s.force_generate_chunk_requests()
local tiles = {}
for x = -R, R - 1 do
  for y = -R, R - 1 do tiles[#tiles + 1] = { name = "landfill", position = { x, y } } end
end
s.set_tiles(tiles, true, true, true, true)
local removed = 0
for _, e in pairs(s.find_entities_filtered { area = { { -R - 8, -R - 8 }, { R + 8, R + 8 } } }) do
  if e.valid and e.type ~= "character" and e.force.name ~= "player" then
    e.destroy()
    removed = removed + 1
  end
end
for _, e in pairs(s.find_entities_filtered { area = { { -R, -R }, { R, R } }, type = "resource" }) do e.destroy() end
s.destroy_decoratives { area = { { -R, -R }, { R, R } } }
f.set_spawn_position({ 0, 0 }, s)

-- A small power block at spawn, for anything a scenario wants on "the grid".
local eei = s.create_entity { name = "electric-energy-interface", position = { -6, -6 }, force = f }
eei.power_production, eei.electric_buffer_size = 166667, 10000000 -- 10 MW
s.create_entity { name = "medium-electric-pole", position = { -3.5, -6.5 }, force = f }
return { researched = #done, removed = removed, tiles = #tiles }
