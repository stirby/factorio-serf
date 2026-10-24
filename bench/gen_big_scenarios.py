#!/usr/bin/env python3
"""The biggest single orders: a rocket from what the map has (b15). Research is done and machines are in chests, so
the order measures building at scale: mines, smelting, oil from a far field (pumps on a pipeline over 320 tiles),
every intermediate chain, the silo and its 50 parts.

    .venv/bin/python bench/gen_big_scenarios.py   -> bench/scenarios/b15-rocket-from-ore.json
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

STOCK = {
    "electric-mining-drill": 120, "steel-furnace": 80, "stone-furnace": 40, "assembling-machine-2": 150,
    "chemical-plant": 40, "oil-refinery": 10, "pumpjack": 10, "pump": 12, "offshore-pump": 4, "storage-tank": 10,
    "inserter": 500, "fast-inserter": 200, "long-handed-inserter": 80, "transport-belt": 4000,
    "underground-belt": 300, "splitter": 60, "pipe": 1200, "pipe-to-ground": 150, "medium-electric-pole": 300,
    "big-electric-pole": 80, "small-electric-pole": 100, "iron-chest": 40, "rocket-silo": 1, "lab": 4,
}

SETUP = r"""
-- research: the rocket silo and everything before it (an order about building, not about research)
local function done_(t) if t.researched then return end for _, q in pairs(t.prerequisites) do done_(q) end t.researched = true end
for _, t in pairs { 'rocket-silo', 'advanced-material-processing', 'fluid-handling', 'electric-energy-distribution-2' } do
  if f.technologies[t] then done_(f.technologies[t]) end
end
local sp = f.get_spawn_position(s)
s.request_to_generate_chunks(sp, 14)
s.force_generate_chunk_requests()
local function near(name)
  local best
  for _, e in pairs(s.find_entities_filtered { name = name, position = sp, radius = 420 }) do
    local d = (e.position.x - sp.x) ^ 2 + (e.position.y - sp.y) ^ 2
    if not best or d < best[1] then best = { d, e.position } end
  end
  return best and (math.floor(best[2].x) .. ',' .. math.floor(best[2].y)) or '?'
end
-- a clear 12x12 spot near spawn for power and the stock
local ox, oy
for r = 0, 60, 4 do
  for _, d in ipairs { {1, 0}, {0, 1}, {-1, 0}, {0, -1} } do
    local x0, y0 = math.floor(sp.x + d[1] * r), math.floor(sp.y + d[2] * r)
    local a = { { x0, y0 }, { x0 + 12, y0 + 12 } }
    if s.count_entities_filtered { area = a, type = { 'resource', 'cliff' } } == 0
       and s.count_tiles_filtered { area = a, collision_mask = 'water_tile' } == 0 then ox, oy = x0, y0 break end
  end
  if ox then break end
end
for _, e in pairs(s.find_entities_filtered { area = { { ox, oy }, { ox + 12, oy + 12 } }, type = { 'tree', 'simple-entity' } }) do e.destroy() end
local eei = s.create_entity { name = 'electric-energy-interface', position = { ox + 2, oy + 2 }, force = f }
eei.power_production = 1e8 eei.electric_buffer_size = 1e9
s.create_entity { name = 'big-electric-pole', position = { ox + 4, oy + 2 }, force = f }
local cx = 0
local function stock_chest()
  local c = s.create_entity { name = 'steel-chest', position = { ox + 1.5 + cx % 10, oy + 6.5 + math.floor(cx / 10) }, force = f }
  cx = cx + 1
  return c
end
local chest = stock_chest()
for nm, k in pairs { STOCK } do
  local left = k
  while left > 0 do
    local got = chest.insert { name = nm, count = left }
    left = left - got
    if left > 0 then chest = stock_chest() end
  end
end
local c = storage.agents and storage.agents['serf'] and storage.agents['serf'].char
if c and c.valid then c.teleport { ox + 6, oy + 5 } end
local w = s.find_tiles_filtered { name = { 'water', 'deepwater' }, position = sp, radius = 300, limit = 1 }[1]
return { power = math.floor(ox + 4) .. ',' .. math.floor(oy + 2), chests = math.floor(ox + 2) .. ',' .. math.floor(oy + 6),
  iron = near('iron-ore'), copper = near('copper-ore'), coal = near('coal'), stone = near('stone'),
  crude = near('crude-oil'), water = w and (math.floor(w.position.x) .. ',' .. math.floor(w.position.y)) or '?' }
"""


def main() -> None:
    stock = ", ".join(f"['{k}'] = {v}" for k, v in STOCK.items())
    scn = {
        "name": "b15-rocket-from-ore",
        "stage": "crew-test",
        "minutes": 900,
        "agents": 1,
        "kind": "directive",
        "note": "A rocket from the map: no plates, no bus, no fluids handed over. Research done (through the rocket "
                "silo), a power source at spawn (an energy interface on a big pole) and chests of machines and the "
                "silo; everything else from the ore patches and the crude field ~350 tiles out (a pipeline that long "
                "needs pumps). Met = one rocket launched.",
        "setup_lua": SETUP.replace("{ STOCK }", "{ " + stock + " }"),
        "objectives": [{
            "name": "launch", "minutes": 900, "hold_samples": 1,
            "goal": "@{agent} launch a rocket from this map. All the research is done; power is on at the big pole at "
                    "[gps={power}]; machines, belts, poles and a rocket silo are in the chests at [gps={chests}]. Mine "
                    "and smelt what you need: iron ore at [gps={iron}], copper at [gps={copper}], coal at [gps={coal}], "
                    "stone at [gps={stone}], crude oil at [gps={crude}], water at [gps={water}].",
            "score": [{"name": "rockets", "lua": "return f.rockets_launched", "target": 1}],
        }],
        "score": [{"name": "drills", "lua": "count('electric-mining-drill')"},
                  {"name": "furnaces", "lua": "count('steel-furnace') + count('stone-furnace')"},
                  {"name": "assemblers", "lua": "count('assembling-machine-2')"},
                  {"name": "rocket_parts", "lua": "local n = 0 for _, e in pairs(s.find_entities_filtered { name = 'rocket-silo', force = f }) do n = n + (e.rocket_parts or 0) end return n"},
                  {"name": "pu_per_min", "lua": "pm('processing-unit')"},
                  {"name": "lds_per_min", "lua": "pm('low-density-structure')"},
                  {"name": "fuel_per_min", "lua": "pm('rocket-fuel')"}],
    }
    out = ROOT / "bench" / "scenarios" / "b15-rocket-from-ore.json"
    out.write_text(json.dumps(scn, indent=1))
    print(out)


if __name__ == "__main__":
    main()
