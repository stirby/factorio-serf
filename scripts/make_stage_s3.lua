-- Turn the S2 base into an S3 fixture: steel/oil-ready research and a stocked, marked depot.
-- Run through the mod's eval op. Returns what it did.
local f = game.forces.player
local s = game.surfaces.nauvis
local done = {}
for _, t in ipairs { "automation", "logistics", "electronics", "steel-processing", "logistic-science-pack",
  "automation-2", "fast-inserter", "electric-mining-drill", "advanced-material-processing", "fluid-handling",
  "oil-gathering", "engine", "logistics-2", "lamp", "military", "military-2", "stone-wall", "gun-turret" } do
  local tech = f.technologies[t]
  if tech and not tech.researched then
    tech.researched = true
    done[#done + 1] = t
  end
end
f.research_queue = {}

-- Depot: a row of iron chests next to the existing labs, stocked like a mid-game player's stockpile.
local labs = s.find_entities_filtered { name = "lab", force = f }
local anchor = labs[1] and labs[1].position or { x = 0, y = 0 }
local spot = s.find_non_colliding_position("iron-chest", { anchor.x + 12, anchor.y + 8 }, 40, 1)
local stock = {
  { "iron-plate", 1600 }, { "copper-plate", 1200 }, { "steel-plate", 200 }, { "stone-brick", 400 },
  { "coal", 1000 }, { "iron-gear-wheel", 400 }, { "electronic-circuit", 400 }, { "transport-belt", 400 },
  { "inserter", 100 }, { "small-electric-pole", 100 }, { "assembling-machine-1", 20 }, { "electric-mining-drill", 20 },
  { "stone-furnace", 40 }, { "pipe", 100 }, { "underground-belt", 40 }, { "splitter", 10 },
}
local chests = {}
local i = 0
for _, st in ipairs(stock) do
  local pos = { x = spot.x + (i % 8), y = spot.y + math.floor(i / 8) * 2 }
  local c = s.find_entities_filtered { position = pos, radius = 0.4, name = "iron-chest" }[1]
  if not c then
    local free = s.find_non_colliding_position("iron-chest", pos, 6, 1)
    c = s.create_entity { name = "iron-chest", position = free, force = f }
  end
  c.insert { name = st[1], count = st[2] }
  chests[#chests + 1] = { item = st[1], p = { c.position.x, c.position.y } }
  i = i + 1
end
return { researched = done, depot = { spot.x, spot.y }, chests = #chests }
