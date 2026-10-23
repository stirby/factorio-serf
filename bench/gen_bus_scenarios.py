#!/usr/bin/env python3
"""Directive tests on a main bus: a stage with a bus already laid and fed (iron and copper plates from endless
chests), registered like one the serf laid, and an order a player would give about it. Writes
bench/scenarios/b*-bus-*.json.

    .venv/bin/python bench/gen_bus_scenarios.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from jev.busgen import Bus  # noqa: E402

LANES = ["iron-plate", "copper-plate", "spare", "spare"]
LENGTH = 60
STOCK = {"assembling-machine-2": 20, "inserter": 80, "fast-inserter": 20, "transport-belt": 400,
         "underground-belt": 40, "splitter": 10, "small-electric-pole": 60, "medium-electric-pole": 30,
         "iron-chest": 10}
TECHS = ["automation", "automation-2", "logistics", "electronics", "fast-inserter", "electric-energy-distribution-1"]


def setup_lua() -> str:
    b = Bus(name="main", x=0.5, y=0.5, direction="south", side="east", lanes=LANES, length=LENGTH)
    belts = ",".join(f"{{{e['x'] - 0.5:g},{e['y'] - 0.5:g}}}" for e in b.lay())
    feeds = ",".join(f"{{{b.u(i)},'{it}'}}" for i, it in enumerate(LANES) if it != "spare")
    stock = ",".join(f"['{k}']={v}" for k, v in STOCK.items())
    techs = ",".join(f"'{t}'" for t in TECHS)
    return f"""
for _, t in pairs {{ {techs} }} do if f.technologies[t] then f.technologies[t].researched = true end end
-- a clear 70x70 area near spawn (no buildings, no water, no ore)
local sp = f.get_spawn_position(s)
local function clear(x0, y0)
  local area = {{ {{ x0 - 4, y0 - 6 }}, {{ x0 + 66, y0 + 66 }} }}
  return s.count_entities_filtered {{ area = area, force = 'player' }} == 0
     and s.count_entities_filtered {{ area = area, type = 'resource' }} == 0
     and s.count_tiles_filtered {{ area = area, collision_mask = 'water_tile' }} == 0
end
local ox, oy
for r = 20, 400, 10 do
  for _, d in ipairs {{ {{1, 0}}, {{0, 1}}, {{-1, 0}}, {{0, -1}}, {{1, 1}}, {{-1, 1}}, {{1, -1}}, {{-1, -1}} }} do
    local x0, y0 = math.floor(sp.x + d[1] * r), math.floor(sp.y + d[2] * r)
    if clear(x0, y0) then ox, oy = x0, y0 break end
  end
  if ox then break end
end
if not ox then return {{ error = 'no clear area' }} end
for _, t in pairs(s.find_entities_filtered {{ area = {{ {{ ox - 4, oy - 6 }}, {{ ox + 66, oy + 66 }} }}, type = {{ 'tree', 'simple-entity' }} }}) do t.destroy() end
for _, p in pairs {{ {belts} }} do
  s.create_entity {{ name = 'transport-belt', position = {{ ox + p[1] + 0.5, oy + p[2] + 0.5 }}, direction = defines.direction.south, force = f }}
end
-- each lane fed from an endless chest by a fast inserter, powered by an energy interface
local eei = s.create_entity {{ name = 'electric-energy-interface', position = {{ ox - 3, oy - 4 }}, force = f }}
eei.power_production = 1e7
eei.electric_buffer_size = 1e8
s.create_entity {{ name = 'medium-electric-pole', position = {{ ox - 2.5, oy - 1.5 }}, force = f }}
for _, fd in pairs {{ {feeds} }} do
  local x = ox + fd[1] + 0.5
  local ch = s.create_entity {{ name = 'infinity-chest', position = {{ x, oy - 1.5 }}, force = f }}
  ch.set_infinity_container_filter(1, {{ name = fd[2], count = 100, index = 1 }})
  s.create_entity {{ name = 'fast-inserter', position = {{ x, oy - 0.5 }}, direction = defines.direction.north, force = f }}
end
-- a pole line down the far side of the production area, from the same supply
for k = 0, 6 do s.create_entity {{ name = 'medium-electric-pole', position = {{ ox + 20.5, oy - 1.5 + 9 * k }}, force = f }} end
for k = 0, 2 do s.create_entity {{ name = 'medium-electric-pole', position = {{ ox + 4.5 + 8 * k, oy - 1.5 }}, force = f }} end
-- building materials in a chest by the bus head
local chest = s.create_entity {{ name = 'steel-chest', position = {{ ox + 12.5, oy - 4.5 }}, force = f }}
for n, k in pairs {{ {stock} }} do chest.insert {{ name = n, count = k }} end
storage.layout = storage.layout or {{}}
storage.layout['bus:main'] = {{ name = 'main', x = ox + 0.5, y = oy + 0.5, direction = 'south', side = 'east',
  lanes = {{ {",".join(f"'{x}'" for x in LANES)} }}, length = {LENGTH}, starts = {{}}, joins = {{}} }}
local c = storage.agents and storage.agents['serf'] and storage.agents['serf'].char
if c and c.valid then c.teleport {{ ox + 10, oy - 3 }} end
return {{ origin = {{ ox, oy }} }}
"""


ON_BUS = """local b = storage.layout and storage.layout['bus:main'] if not b then return 0 end
local n = 0
for _, e in pairs(s.find_entities_filtered { area = { { b.x - 3, b.y + b.length - 8 }, { b.x + 12, b.y + b.length } }, type = 'transport-belt' }) do
  for l = 1, 2 do for _, c in pairs(e.get_transport_line(l).get_contents()) do if c.name == 'electronic-circuit' then n = n + c.count end end end
end
return n"""
TAPS = "local b = storage.layout and storage.layout['bus:main'] local n = 0 if b then for _, j in pairs(b.joins or {}) do if j.kind == 'tap' then n = n + 1 end end end return n"


def scenarios() -> list[dict]:
    return [{
        "name": "b1-bus-circuits",
        "stage": "crew-test",
        "minutes": 45,
        "agents": 1,
        "kind": "directive",
        "note": "A main bus (bus main, flowing south, taps on the east) carries iron and copper plates from endless "
                "chests; two lanes are spare. A player-style production order: take plates off the bus, build "
                "circuits at a rate, put them back on the bus. Met = circuits made at 27+/min for 3 samples and "
                "circuits arriving at the bus's far end.",
        "setup_lua": setup_lua(),
        "objectives": [{
            "name": "circuits-on-bus", "minutes": 45, "hold_samples": 3,
            "goal": "@{agent} we've got a main bus (bus main) carrying iron and copper plates. Build green circuits "
                    "for 30 a minute: take the iron and copper off the bus, and put the circuits back on the bus.",
            "score": [{"name": "circuits_per_min", "lua": "pm('electronic-circuit')", "target": 27},
                      {"name": "circuits_at_bus_end", "lua": ON_BUS, "target": 1}],
        }],
        "score": [{"name": "taps", "lua": TAPS}, {"name": "circuits_made", "lua": "st.get_input_count('electronic-circuit')"}],
    }]


if __name__ == "__main__":
    for sc in scenarios():
        p = ROOT / "bench" / "scenarios" / f"{sc['name']}.json"
        p.write_text(json.dumps(sc, indent=1))
        print(p)
