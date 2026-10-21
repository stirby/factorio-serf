-- x-multi-fault setup: a small science block that looks finished but has four independent faults.
-- Red: copper (infinity chest) and gears share one belt into 2 red assemblers. Gears come from a gear assembler
-- fed by a plate chest that 2 stone furnaces fill. Green: 2 assemblers fed from chests. Both put packs on a
-- science belt that runs past 2 labs into an overflow sink, so production never backs up.
-- Faults: (1) one belt tile on the red input belt faces west; (2) the gear assembler makes pipes;
-- (3) the pole over the green assemblers is missing; (4) the plate chest is full of stone, so both furnaces sit on
-- full output. Fixing all four gets red and green packs into both labs.
local fx, fy = find_ring(34, 18, 40, 220)
clear(fx, fy, 34, 18)
local X, Y = fx + 9, fy - 1
local function at(name, x, y, dir, extra) return put(name, X + x, Y + y, dir, extra) end

grid(X - 1, Y + 3, 2000000)
for _, p in pairs { { -2.5, 5.5 }, { 2.5, 5.5 }, { 7.5, 8.5 }, { 14.5, 9.5 }, { 19.5, 9.5 } } do
  at("medium-electric-pole", p[1], p[2])
end

-- smelting pair -> plate chest -> gear assembler
local f1, f2 = at("stone-furnace", -5, 7), at("stone-furnace", -3, 10)
source(X - 7.5, Y + 7.5, { "iron-ore" })
source(X - 5.5, Y + 9.5, { "iron-ore" })
for _, b in pairs { at("burner-inserter", -6.5, 7.5, D.west), at("burner-inserter", -4.5, 9.5, D.west) } do
  b.insert { name = "coal", count = 20 }
end
for _, fu in pairs { f1, f2 } do
  fu.insert { name = "coal", count = 50 }
  fu.get_output_inventory().insert { name = "iron-plate", count = 100 }
end
local chest = at("wooden-chest", -2.5, 7.5)
chest.insert { name = "stone", count = 800 } -- fault 4
at("inserter", -3.5, 7.5, D.west)
at("inserter", -2.5, 8.5, D.south)
at("inserter", -1.5, 7.5, D.west)
local gear = at("assembling-machine-1", 0.5, 7.5)
gear.set_recipe("pipe") -- fault 2
at("inserter", 0.5, 5.5, D.south)

-- red: copper + gears on one belt
source(X + 1.5, Y + 2.5, { "copper-plate" })
at("inserter", 1.5, 3.5, D.north)
for x = 0, 11 do at("transport-belt", x + 0.5, 4.5, D.east) end
s.find_entity("transport-belt", { X + 3.5, Y + 4.5 }).direction = D.west -- fault 1
for _, x in pairs { 5.5, 9.5 } do
  at("assembling-machine-1", x, 7.5).set_recipe("automation-science-pack")
  at("inserter", x, 5.5, D.north)
  at("inserter", x, 9.5, D.north)
end

-- green: chest-fed assemblers (their pole at 7.5,15.5 is missing: fault 3)
for _, x in pairs { 5.5, 9.5 } do
  at("assembling-machine-1", x, 13.5).set_recipe("logistic-science-pack")
  at("inserter", x, 11.5, D.south)
  at("inserter", x, 15.5, D.south)
  source(X + x, Y + 16.5, { "inserter", "transport-belt" })
end

-- science belt -> 2 labs -> overflow sink
for x = 4, 20 do at("transport-belt", x + 0.5, 10.5, D.east) end
at("lab", 16.5, 7.5)
at("lab", 16.5, 13.5)
at("inserter", 16.5, 9.5, D.south)
at("inserter", 16.5, 11.5, D.north)
at("inserter", 21.5, 10.5, D.west)
sink(X + 22.5, Y + 10.5)

-- research that needs both packs, if one is open
local function both(t)
  local ing = t.research_unit_ingredients
  if #ing ~= 2 then return false end
  local n = 0
  for _, i in pairs(ing) do
    if i.name == "automation-science-pack" or i.name == "logistic-science-pack" then n = n + 1 end
  end
  return n == 2
end
local tech
for _, t in pairs(f.technologies) do
  if not tech and t.enabled and not t.researched and both(t) then
    local ok = true
    for _, p in pairs(t.prerequisites) do if not p.researched then ok = false end end
    if ok then tech = t end
  end
end
if tech then
  f.cancel_current_research()
  f.add_research(tech)
end

storage.bench_mf = {
  X = X, Y = Y, area = { { X - 9, Y + 1 }, { X + 24, Y + 18 } },
  red = { { X + 3, Y + 5 }, { X + 12, Y + 10 } }, green = { { X + 3, Y + 11.5 }, { X + 12, Y + 16 } },
  labs = { { X + 14, Y + 5 }, { X + 19, Y + 16 } }, row = { { X, Y + 4 }, { X + 12, Y + 5 } },
  gear = { X + 0.5, Y + 7.5 }, chest = { X - 2.5, Y + 7.5 },
}
return { gx = math.floor(X + 8), gy = math.floor(Y + 10), tech = tech and tech.name or "none" }
