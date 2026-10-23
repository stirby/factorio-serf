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
STOCK = {"assembling-machine-2": 20, "stone-furnace": 30, "inserter": 80, "fast-inserter": 20, "transport-belt": 400,
         "underground-belt": 40, "splitter": 10, "small-electric-pole": 60, "medium-electric-pole": 30,
         "iron-chest": 10}
TECHS = ["automation", "automation-2", "logistics", "electronics", "fast-inserter", "electric-energy-distribution-1"]


def setup_lua(lanes: list[str] = LANES, techs_extra: tuple = ()) -> str:
    """A bus of `lanes` (spares empty, the rest fed from endless chests), registered as bus main."""
    LANES = lanes  # noqa: N806
    TECHS = globals()["TECHS"] + list(techs_extra)  # noqa: N806
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



def setup_lua_b2() -> str:
    """No bus yet: an iron and a copper plate line (from endless chests, as if from smelting) end side by side at the
    north edge of a clear area; four labs stand unpowered-by-packs in the south-east; materials in a chest."""
    stock = ",".join(f"['{k}']={v}" for k, v in dict(STOCK, lab=0).items() if v)
    techs = ",".join(f"'{t}'" for t in TECHS)
    return f"""
for _, t in pairs {{ {techs} }} do if f.technologies[t] then f.technologies[t].researched = true end end
for _, t in pairs {{ 'military', 'optics', 'turrets', 'stone-wall', 'weapon-shooting-speed-1', 'physical-projectile-damage-1' }} do
  if f.technologies[t] and not f.technologies[t].researched then f.add_research(t) end
end
local sp = f.get_spawn_position(s)
local function clear(x0, y0)
  local area = {{ {{ x0 - 4, y0 - 8 }}, {{ x0 + 76, y0 + 76 }} }}
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
for _, t in pairs(s.find_entities_filtered {{ area = {{ {{ ox - 4, oy - 8 }}, {{ ox + 76, oy + 76 }} }}, type = {{ 'tree', 'simple-entity' }} }}) do t.destroy() end
local eei = s.create_entity {{ name = 'electric-energy-interface', position = {{ ox - 3, oy - 2 }}, force = f }}
eei.power_production = 1e7
eei.electric_buffer_size = 1e8
-- two plate lines running east along the north edge, 12 tiles long, ending at x = ox + 11
for row, item in pairs {{ [0] = 'iron-plate', [2] = 'copper-plate' }} do
  local y = oy - 4 + row + 0.5
  for k = 0, 11 do s.create_entity {{ name = 'transport-belt', position = {{ ox + k + 0.5, y }}, direction = defines.direction.east, force = f }} end
  local ch = s.create_entity {{ name = 'infinity-chest', position = {{ ox - 1.5, y }}, force = f }}
  ch.set_infinity_container_filter(1, {{ name = item, count = 100, index = 1 }})
  s.create_entity {{ name = 'fast-inserter', position = {{ ox - 0.5, y }}, direction = defines.direction.west, force = f }}
end
s.create_entity {{ name = 'medium-electric-pole', position = {{ ox - 0.5, oy - 1.5 }}, force = f }}
-- labs in the south-east, on a pole line from the same supply
for k = 0, 3 do s.create_entity {{ name = 'lab', position = {{ ox + 50.5 + 4 * k, oy + 50.5 }}, force = f }} end
for k = 0, 7 do s.create_entity {{ name = 'medium-electric-pole', position = {{ ox - 0.5 + 8 * k, oy - 1.5 }}, force = f }} end
for k = 1, 6 do s.create_entity {{ name = 'medium-electric-pole', position = {{ ox + 55.5, oy - 1.5 + 8 * k }}, force = f }} end
for k = 0, 2 do s.create_entity {{ name = 'medium-electric-pole', position = {{ ox + 47.5 + 8 * k, oy + 47.5 }}, force = f }} end
local chest = s.create_entity {{ name = 'steel-chest', position = {{ ox + 20.5, oy - 6.5 }}, force = f }}
for n, k in pairs {{ {stock} }} do chest.insert {{ name = n, count = k }} end
local c = storage.agents and storage.agents['serf'] and storage.agents['serf'].char
if c and c.valid then c.teleport {{ ox + 18, oy - 6 }} end
return {{ origin = {{ ox, oy }}, iron_end = {{ ox + 11.5, oy - 3.5 }}, copper_end = {{ ox + 11.5, oy - 1.5 }}, labs = {{ ox + 50.5, oy + 50.5 }} }}
"""



def setup_lua_b4(feed_rows: int = 4, coal: bool = False, oil: bool = False, extra_techs: tuple = (),
                 extra_stock: dict | None = None) -> str:
    """A long bus (iron, copper, 6 spare) fed hard at its head (4 fast inserters per lane, ~550/min each), with a sink
    past the end of every lane (an inserter into an endless chest that deletes packs and intermediates), so products
    put on the bus never back up. Rows 0-3 hold the feeders (registered as a feed join). coal: lane 2 carries coal,
    fed at rows 4-7 from its west gap. oil: endless crude and water pipe ends east of the bus."""
    lanes = ["iron-plate", "copper-plate"] + (["coal"] if coal else []) + ["spare"] * (5 if coal else 6)
    if coal:
        feed_rows = max(feed_rows, 8)
    n = 100
    b = Bus(name="main", x=0.5, y=0.5, direction="south", side="east", lanes=lanes, length=n)
    belts = ",".join(f"{{{e['x'] - 0.5:g},{e['y'] - 0.5:g}}}" for e in b.lay())
    ends = ",".join(f"{{{b.u(i)}}}" for i in range(len(lanes)))
    stock = ",".join(f"['{k}']={v}" for k, v in {
        "assembling-machine-2": 40, "inserter": 150, "fast-inserter": 40, "transport-belt": 800,
        "underground-belt": 80, "splitter": 20, "small-electric-pole": 80, "medium-electric-pole": 40,
        "iron-chest": 20, "long-handed-inserter": 30,
        **({"oil-refinery": 4, "chemical-plant": 4, "pipe": 150, "pipe-to-ground": 30, "pump": 4} if oil else {}),
        **(extra_stock or {})}.items())
    techs = ",".join(f"'{t}'" for t in TECHS + ["logistic-science-pack"] + (
        ["fluid-handling", "oil-gathering", "oil-processing", "plastics", "sulfur-processing"] if oil else []) +
        list(extra_techs))
    coal_lua = """-- coal onto lane 2 (u=4) at rows 4-7 from its west gap
for row = 4, 7 do
  local y = oy + row + 0.5
  local cc = s.create_entity {{ name = 'infinity-chest', position = {{ ox + 2.5, y }}, force = f }}
  cc.set_infinity_container_filter(1, {{ name = 'coal', count = 100, index = 1 }})
  s.create_entity {{ name = 'fast-inserter', position = {{ ox + 3.5, y }}, direction = defines.direction.west, force = f }}
end""".replace("{{", "{").replace("}}", "}") if coal else ""
    oil_lua = """-- crude and water arrive in pipes east of the bus, as if piped from pumpjacks and an offshore pump
local crude = s.create_entity {{ name = 'infinity-pipe', position = {{ ox + 30.5, oy + 60.5 }}, force = f }}
crude.set_infinity_pipe_filter {{ name = 'crude-oil', percentage = 1, mode = 'at-least' }}
local water = s.create_entity {{ name = 'infinity-pipe', position = {{ ox + 36.5, oy + 60.5 }}, force = f }}
water.set_infinity_pipe_filter {{ name = 'water', percentage = 1, mode = 'at-least' }}""".replace("{{", "{").replace("}}", "}") if oil else ""
    oil_ret = (", crude = string.format('%g,%g', ox + 30.5, oy + 60.5), "
               "water = string.format('%g,%g', ox + 36.5, oy + 60.5)") if oil else ""
    # (spliced into the f-string below as text, so single braces here)
    feed_joins = ", ".join(f"{{ kind = 'feed', lane = 0, at = {a}, ['end'] = {{ ox + 0.5, oy + 0.5 }} }}"
                           for a in range(0, feed_rows, 4))
    sink = ",".join(f"'{x}'" for x in ("automation-science-pack", "logistic-science-pack", "electronic-circuit",
                                         "iron-gear-wheel", "inserter", "transport-belt", "copper-cable",
                                         "plastic-bar", "sulfur", "coal", "chemical-science-pack", "steel-plate",
                                         "engine-unit", "advanced-circuit", "pipe"))
    return f"""
for _, t in pairs {{ {techs} }} do if f.technologies[t] then f.technologies[t].researched = true end end
local sp = f.get_spawn_position(s)
local function clear(x0, y0)
  local area = {{ {{ x0 - 6, y0 - 6 }}, {{ x0 + 90, y0 + {n + 8} }} }}
  return s.count_entities_filtered {{ area = area, force = 'player' }} == 0
     and s.count_entities_filtered {{ area = area, type = 'resource' }} == 0
     and s.count_tiles_filtered {{ area = area, collision_mask = 'water_tile' }} == 0
end
local ox, oy
for r = 20, 500, 10 do
  for _, d in ipairs {{ {{1, 0}}, {{0, 1}}, {{-1, 0}}, {{0, -1}}, {{1, 1}}, {{-1, 1}}, {{1, -1}}, {{-1, -1}} }} do
    local x0, y0 = math.floor(sp.x + d[1] * r), math.floor(sp.y + d[2] * r)
    if clear(x0, y0) then ox, oy = x0, y0 break end
  end
  if ox then break end
end
if not ox then return {{ error = 'no clear area' }} end
for _, t in pairs(s.find_entities_filtered {{ area = {{ {{ ox - 6, oy - 6 }}, {{ ox + 90, oy + {n + 8} }} }}, type = {{ 'tree', 'simple-entity' }} }}) do t.destroy() end
for _, p in pairs {{ {belts} }} do
  s.create_entity {{ name = 'transport-belt', position = {{ ox + p[1] + 0.5, oy + p[2] + 0.5 }}, direction = defines.direction.south, force = f }}
end
local eei = s.create_entity {{ name = 'electric-energy-interface', position = {{ ox - 4, oy + 1 }}, force = f }}
eei.power_production = 1e8
eei.electric_buffer_size = 1e9
-- feeders: iron (lane 0, u=0) from the west gap, copper (lane 1, u=1) from the east gap, one per row
for row = 0, {feed_rows - 1} do
  local y = oy + row + 0.5
  local ci = s.create_entity {{ name = 'infinity-chest', position = {{ ox - 1.5, y }}, force = f }}
  ci.set_infinity_container_filter(1, {{ name = 'iron-plate', count = 100, index = 1 }})
  s.create_entity {{ name = 'fast-inserter', position = {{ ox - 0.5, y }}, direction = defines.direction.west, force = f }}
  local cc = s.create_entity {{ name = 'infinity-chest', position = {{ ox + 3.5, y }}, force = f }}
  cc.set_infinity_container_filter(1, {{ name = 'copper-plate', count = 100, index = 1 }})
  s.create_entity {{ name = 'fast-inserter', position = {{ ox + 2.5, y }}, direction = defines.direction.east, force = f }}
end
for k = 0, {(feed_rows - 1) // 6} do
  s.create_entity {{ name = 'medium-electric-pole', position = {{ ox - 2.5, oy + 1.5 + 6 * k }}, force = f }}
  s.create_entity {{ name = 'medium-electric-pole', position = {{ ox + 4.5, oy + 1.5 + 6 * k }}, force = f }}
end
{coal_lua}
{oil_lua}
s.create_entity {{ name = 'medium-electric-pole', position = {{ ox + 1.5, oy - 3.5 }}, force = f }}
-- sinks past the end of every lane
local sinks = {{ {sink} }}
for _, e in pairs {{ {ends} }} do
  local x = ox + e[1] + 0.5
  s.create_entity {{ name = 'fast-inserter', position = {{ x, oy + {n} + 0.5 }}, direction = defines.direction.north, force = f }}
  local ch = s.create_entity {{ name = 'infinity-chest', position = {{ x, oy + {n} + 1.5 }}, force = f }}
  for i, it in pairs(sinks) do ch.set_infinity_container_filter(i, {{ name = it, count = 0, mode = 'exactly', index = i }}) end
end
for k = 0, 7 do s.create_entity {{ name = 'medium-electric-pole', position = {{ ox - 0.5 + 6 * k, oy + {n} + 2.5 }}, force = f }} end
for k = 0, 13 do s.create_entity {{ name = 'medium-electric-pole', position = {{ ox + 40.5, oy - 3.5 + 8 * k }}, force = f }} end
for k = 0, 4 do s.create_entity {{ name = 'medium-electric-pole', position = {{ ox + 8.5 + 8 * k, oy - 3.5 }}, force = f }} end
local chest = s.create_entity {{ name = 'steel-chest', position = {{ ox + 12.5, oy - 4.5 }}, force = f }}
for nm, k in pairs {{ {stock} }} do chest.insert {{ name = nm, count = k }} end
local chest2 = s.create_entity {{ name = 'steel-chest', position = {{ ox + 13.5, oy - 4.5 }}, force = f }}
chest2.insert {{ name = 'transport-belt', count = 400 }}
storage.layout = storage.layout or {{}}
storage.layout['bus:main'] = {{ name = 'main', x = ox + 0.5, y = oy + 0.5, direction = 'south', side = 'east',
  lanes = {{ {",".join(f"'{x}'" for x in lanes)} }}, length = {n}, starts = {{}},
  joins = {{ {feed_joins} }} }}
local c = storage.agents and storage.agents['serf'] and storage.agents['serf'].char
if c and c.valid then c.teleport {{ ox + 10, oy - 3 }} end
return {{ origin = {{ ox, oy }}{oil_ret} }}
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
    }, {
        "name": "b3-bus-steel",
        "stage": "crew-test",
        "minutes": 45,
        "agents": 1,
        "kind": "directive",
        "note": "A main bus carries iron plates, copper plates and coal (endless chests); one lane is spare. Steel "
                "off the bus: iron and coal taken off (two taps, one belt with a lane of each, or two belts), a "
                "furnace row, steel back onto the spare lane. Met = steel made at 13+/min for 3 samples and steel "
                "at the bus's far end.",
        "setup_lua": setup_lua(["iron-plate", "copper-plate", "coal", "spare"], ("steel-processing",)),
        "objectives": [{
            "name": "steel-on-bus", "minutes": 45, "hold_samples": 3,
            "goal": "@{agent} we need steel. Our main bus (bus main) has iron plates and coal on it: build steel "
                    "for 15 a minute off the bus and put the steel on the bus's spare lane.",
            "score": [{"name": "steel_per_min", "lua": "pm('steel-plate')", "target": 13},
                      {"name": "steel_at_bus_end", "lua": ON_BUS.replace("electronic-circuit", "steel-plate"),
                       "target": 1}],
        }],
        "score": [{"name": "taps", "lua": TAPS}, {"name": "steel_made", "lua": "st.get_input_count('steel-plate')"}],
    }, {
        "name": "b4-bus-science-45",
        "stage": "crew-test",
        "minutes": 120,
        "agents": 1,
        "kind": "directive",
        "note": "A large order on a pre-built bus (iron and copper fed at ~550/min each; 6 spare lanes, sinks past every "
                "lane end): red and green science at 45/min each, every intermediate (gears, circuits, inserters, "
                "belts) made off the bus. ~16 assemblers, several chains. Met = 40+/min of each pack for 3 samples.",
        "setup_lua": setup_lua_b4(),
        "objectives": [{
            "name": "red-green-45", "minutes": 120, "hold_samples": 3,
            "goal": "@{agent} our main bus (bus main) carries iron and copper plates and has spare lanes. Build red "
                    "and green science for 45 a minute each, making the gears, circuits, inserters and belts they "
                    "need off the bus too, and put the science packs onto the bus.",
            "score": [{"name": "red_per_min", "lua": "pm('automation-science-pack')", "target": 40},
                      {"name": "green_per_min", "lua": "pm('logistic-science-pack')", "target": 40}],
        }],
        "score": [{"name": "taps", "lua": TAPS},
                  {"name": "assemblers", "lua": "count('assembling-machine-2')"}],
    }, {
        "name": "b5-bus-science-double",
        "stage": "crew-test",
        "minutes": 180,
        "agents": 1,
        "kind": "directive",
        "note": "Scale test: b4's order (red and green science at 45/min each, all intermediates off the bus), then "
                "'double both'. The bus is fed at ~1100/min per plate lane (8 feeders). Does a bus-based build "
                "extend cleanly? Met = 40+/min each, then 80+/min each, 3 samples each.",
        "setup_lua": setup_lua_b4(8),
        "objectives": [{
            "name": "red-green-45", "minutes": 100, "hold_samples": 3,
            "goal": "@{agent} our main bus (bus main) carries iron and copper plates and has spare lanes. Build red "
                    "and green science for 45 a minute each, making the gears, circuits, inserters and belts they "
                    "need off the bus too, and put the science packs onto the bus.",
            "score": [{"name": "red_per_min", "lua": "pm('automation-science-pack')", "target": 40},
                      {"name": "green_per_min", "lua": "pm('logistic-science-pack')", "target": 40}],
        }, {
            "name": "double-it", "minutes": 80, "hold_samples": 3,
            "goal": "@{agent} nice. Now double it: red and green science at 90 a minute each, still all off the bus.",
            "score": [{"name": "red_per_min", "lua": "pm('automation-science-pack')", "target": 80},
                      {"name": "green_per_min", "lua": "pm('logistic-science-pack')", "target": 80}],
        }],
        "score": [{"name": "taps", "lua": TAPS},
                  {"name": "assemblers", "lua": "count('assembling-machine-2')"}],
    }, {
        "name": "b6-bus-oil",
        "stage": "crew-test",
        "minutes": 75,
        "agents": 1,
        "kind": "directive",
        "note": "Oil beside a bus: crude and water arrive in pipes (endless) east of a bus carrying iron, copper and "
                "coal; sinks past every lane end. The order: plastic and sulfur, both onto the bus. Tests the oil "
                "area (block or hand-piped) and two bus_in merges. Met = plastic 60+/min and sulfur 15+/min for 3 "
                "samples.",
        "setup_lua": setup_lua_b4(8, coal=True, oil=True),
        "objectives": [{
            "name": "plastic-sulfur", "minutes": 75, "hold_samples": 3,
            "goal": "@{agent} crude oil and water now arrive in the pipes at [gps={crude}] and [gps={water}]. Our main "
                    "bus (bus main) has iron, copper and coal on it. Build plastic and sulfur from the oil, at least "
                    "60 plastic and 15 sulfur a minute, and put both onto the bus.",
            "score": [{"name": "plastic_per_min", "lua": "pm('plastic-bar')", "target": 60},
                      {"name": "sulfur_per_min", "lua": "pm('sulfur')", "target": 15}],
        }],
        "score": [{"name": "taps", "lua": TAPS}, {"name": "refineries", "lua": "count('oil-refinery')"}],
    }, {
        "name": "b7-bus-blue",
        "stage": "crew-test",
        "minutes": 180,
        "agents": 1,
        "kind": "directive",
        "note": "How large a task: blue science at 30/min from raw plates, coal and piped crude on a bus, with every "
                "chain built (steel, gears, pipes, engines, green and advanced circuits, plastic, sulfur): ~35 "
                "assemblers, ~8 furnaces and an oil area from one order. Plate lanes fed at ~1100/min, sinks past "
                "every lane. Met = blue packs made at 27+/min for 3 samples.",
        "setup_lua": setup_lua_b4(8, coal=True, oil=True,
                                  extra_techs=("steel-processing", "engine", "advanced-circuit", "advanced-electronics",
                                               "chemical-science-pack", "lubricant"),
                                  extra_stock={"assembling-machine-2": 70, "stone-furnace": 30, "inserter": 250,
                                               "transport-belt": 1500, "underground-belt": 150, "splitter": 30,
                                               "fast-inserter": 60, "medium-electric-pole": 80}),
        "objectives": [{
            "name": "blue-30", "minutes": 180, "hold_samples": 3,
            "goal": "@{agent} crude oil and water arrive in the pipes at [gps={crude}] and [gps={water}], and our main "
                    "bus (bus main) has iron, copper and coal. Build chemical (blue) science for 30 a minute, making "
                    "everything it needs from those: steel, engines, green and advanced circuits, plastic, sulfur. "
                    "Put the packs onto the bus.",
            "score": [{"name": "blue_per_min", "lua": "pm('chemical-science-pack')", "target": 27}],
        }],
        "score": [{"name": "taps", "lua": TAPS}, {"name": "assemblers", "lua": "count('assembling-machine-2')"},
                  {"name": "engines_per_min", "lua": "pm('engine-unit')"},
                  {"name": "adv_circuits_per_min", "lua": "pm('advanced-circuit')"}],
    }, {
        "name": "b2-bus-red",
        "stage": "crew-test",
        "minutes": 50,
        "agents": 1,
        "kind": "directive",
        "note": "No bus yet: iron and copper plate lines end side by side at the north edge of a clear 80x80 area; "
                "4 labs in the south-east with research queued (red only). The order: lay a main bus from the plate "
                "lines (with spares), then red science at 30/min off it, into the labs. Met = red packs made at "
                "27+/min and reaching the labs for 3 samples, with a bus registered.",
        "setup_lua": setup_lua_b2(),
        "objectives": [{
            "name": "red-from-bus", "minutes": 50, "hold_samples": 3,
            "goal": "@{agent} our iron and copper plate lines end up at the north edge of the clear ground. Lay a "
                    "main bus from them going south (iron, copper, and some spare lanes for later), then build red "
                    "science for 30 a minute off the bus and feed it to the labs in the south-east.",
            "score": [{"name": "red_per_min", "lua": "pm('automation-science-pack')", "target": 27},
                      {"name": "packs_in_labs", "lua": "local n = 0 for _, l in pairs(s.find_entities_filtered { name = 'lab', force = f }) do n = n + l.get_inventory(defines.inventory.lab_input).get_item_count('automation-science-pack') end return n", "target": 1},
                      {"name": "buses", "lua": "local n = 0 for k in pairs(storage.layout or {}) do if tostring(k):sub(1, 4) == 'bus:' then n = n + 1 end end return n", "target": 1}],
        }],
        "score": [{"name": "taps", "lua": TAPS.replace("storage.layout['bus:main']", "(function() for k, v in pairs(storage.layout or {}) do if tostring(k):sub(1, 4) == 'bus:' then return v end end end)()")}],
    }]


if __name__ == "__main__":
    for sc in scenarios():
        p = ROOT / "bench" / "scenarios" / f"{sc['name']}.json"
        p.write_text(json.dumps(sc, indent=1))
        print(p)
