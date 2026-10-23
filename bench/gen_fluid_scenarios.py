#!/usr/bin/env python3
"""Fluid-line repair scenarios (b9): a refinery starved of crude by a broken line, two faults in a row. The serf has to
find the breaks (the `pipes` tracer, or the audit's words) and mend them, not lay a second line.

    .venv/bin/python bench/gen_fluid_scenarios.py   -> bench/scenarios/b9-crude-fix.json, b10-far-crude.json
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMMON = (ROOT / "bench" / "scenarios" / "lua" / "x-common.lua").read_text()

SETUP = r"""
for _, t in pairs { 'automation', 'logistics', 'electronics', 'steel-processing', 'oil-gathering', 'oil-processing',
  'fluid-handling', 'electric-energy-distribution-1' } do if f.technologies[t] then f.technologies[t].researched = true end end
local W, H = 30, 44
local ox, oy
if LAB then ox, oy = find_near(-60, -60, W, H, 160) else ox, oy = find_ring(W, H, 40, 260) end
clear(ox, oy, W, H)
local X, Y = ox + 10, oy + 6
local b = {}
storage.bench_crude = b
b.ref = put('oil-refinery', X + 0.5, Y + 0.5, D.north)
b.ref.set_recipe('basic-oil-processing')
grid(X + 6, Y + 1, 3000000)
put('medium-electric-pole', X + 4.5, Y + 3.5)
-- where the recipe's crude goes in and its petroleum comes out
local cin, pout
for i = 1, #b.ref.fluidbox do
  local okP, kind = pcall(function() return b.ref.fluidbox.get_prototype(i).production_type end)
  if not okP then kind = nil end
  local okF, fil = pcall(b.ref.fluidbox.get_filter, i)
  if not okF then fil = nil end
  for _, c in pairs(b.ref.fluidbox.get_pipe_connections(i)) do
    if kind == 'input' and fil and fil.name == 'crude-oil' then cin = c.target_position end
    if kind == 'output' and fil and fil.name == 'petroleum-gas' then pout = c.target_position end
  end
end
if not (cin and pout) then error('refinery ports not found') end
local sinkp = put('infinity-pipe', pout.x, pout.y)
sinkp.set_infinity_pipe_filter { name = 'petroleum-gas', percentage = 0, mode = 'exactly' }
-- the crude line runs straight south from the port to a well 30 tiles away (an endless crude source)
local px, py = cin.x, cin.y
for k = 0, 29 do
  local y = py + k
  if k == 10 then
    -- fault 1: a missing pipe
  elseif k == 18 then
    put('pipe-to-ground', px, y, D.north)
  elseif k > 18 and k < 22 then
    -- underground
  elseif k == 22 then
    put('pipe-to-ground', px, y, D.north)  -- fault 2: the exit faces the wrong way (an exit here faces south)
  else
    put('pipe', px, y)
  end
end
local well = put('infinity-pipe', px, py + 30)
well.set_infinity_pipe_filter { name = 'crude-oil', percentage = 1, mode = 'at-least' }
do  -- spares, as a base would have
  local c = put('steel-chest', X - 6.5, Y + 4.5)
  for n, k in pairs { ['pipe'] = 50, ['pipe-to-ground'] = 10, ['medium-electric-pole'] = 10 } do c.insert { name = n, count = k } end
end
return { rx = math.floor(b.ref.position.x), ry = math.floor(b.ref.position.y) }
"""

WORKING = ("local r = storage.bench_crude.ref return (r.valid and r.status == defines.entity_status.working) and 1 or 0")


# b10: the well is 450 tiles from the refinery, over flat ground: one plain pipe is a segment too long to flow, so the
# line needs pumps (in the chest) with power beside them (poles in the chest; power only at the refinery end)
SETUP_FAR = r"""
for _, t in pairs { 'automation', 'logistics', 'electronics', 'steel-processing', 'oil-gathering', 'oil-processing',
  'fluid-handling', 'electric-energy-distribution-1' } do if f.technologies[t] then f.technologies[t].researched = true end end
local L, H = 470, 24
local ox, oy = 40, -12
if not LAB then
  local sp = f.get_spawn_position(s)
  ox, oy = math.floor(sp.x) + 40, math.floor(sp.y) - 12
end
gen(ox - 4, oy - 4, L + 8, H + 8)
local tiles = {}
for x = ox - 4, ox + L + 4 do for y = oy - 4, oy + H + 4 do tiles[#tiles + 1] = { name = 'refined-concrete', position = { x, y } } end end
s.set_tiles(tiles)
for _, e in pairs(s.find_entities_filtered { area = { { ox - 4, oy - 4 }, { ox + L + 4, oy + H + 4 } } }) do
  if e.type ~= 'character' then e.destroy() end
end
local X, Y = ox + L - 12, oy + 12
local b = {}
storage.bench_crude = b
b.ref = put('oil-refinery', X + 0.5, Y + 0.5, D.east)
b.ref.set_recipe('basic-oil-processing')
grid(X - 2, Y + 5, 3000000)
put('medium-electric-pole', X + 0.5, Y + 4.5)
local cin, pout
for i = 1, #b.ref.fluidbox do
  local okP, kind = pcall(function() return b.ref.fluidbox.get_prototype(i).production_type end)
  if not okP then kind = nil end
  local okF, fil = pcall(b.ref.fluidbox.get_filter, i)
  if not okF then fil = nil end
  for _, c in pairs(b.ref.fluidbox.get_pipe_connections(i)) do
    if kind == 'input' and fil and fil.name == 'crude-oil' then cin = c.target_position end
    if kind == 'output' and fil and fil.name == 'petroleum-gas' then pout = c.target_position end
  end
end
if not (cin and pout) then error('refinery ports not found') end
local sinkp = put('infinity-pipe', pout.x, pout.y)
sinkp.set_infinity_pipe_filter { name = 'petroleum-gas', percentage = 0, mode = 'exactly' }
b.cin = cin
local wx, wy = cin.x - 450, cin.y
local well = put('infinity-pipe', wx, wy)
well.set_infinity_pipe_filter { name = 'crude-oil', percentage = 1, mode = 'at-least' }
b.well = well
do
  local c = put('steel-chest', X - 3.5, Y - 3.5)
  for n, k in pairs { ['pipe'] = 600, ['pipe-to-ground'] = 40, ['pump'] = 6, ['medium-electric-pole'] = 100,
    ['big-electric-pole'] = 30 } do c.insert { name = n, count = k } end
end
return { rx = math.floor(b.ref.position.x), ry = math.floor(b.ref.position.y), wx = math.floor(wx), wy = math.floor(wy) }
"""


def main() -> None:
    scn = {
        "name": "b9-crude-fix", "stage": "crew-test", "minutes": 20, "agents": 1, "kind": "directive",
        "note": "A refinery starved of crude: its line from the well has a missing pipe and, further on, an underground "
                "exit facing the wrong way. Met = the refinery working for 2 samples. Measures whether the serf finds "
                "breaks in a fluid line (the pipes tracer) instead of laying a new one.",
        "setup_lua": COMMON + SETUP,
        "objectives": [{
            "name": "crude-flows", "minutes": 18, "hold_samples": 2,
            "goal": "@{agent} the oil refinery at [gps={rx},{ry}] gets no crude oil. Fix it please.",
            "answer": "Your call. Everything it needs is there; the well is fine.",
            "score": [{"name": "refinery_working", "target": 1, "lua": WORKING}]}],
        "score": [],
    }
    out = ROOT / "bench" / "scenarios" / "b9-crude-fix.json"
    out.write_text(json.dumps(scn, indent=1))
    print(out)
    far = {
        "name": "b10-far-crude", "stage": "crew-test", "minutes": 60, "agents": 1, "kind": "directive",
        "note": "Crude 450 tiles from the refinery over flat ground. One plain pipe that long is a segment too long to "
                "flow (2.0: over 320 tiles nothing comes out), so it takes pumps with power beside them; pumps, poles "
                "and pipes are in the chest by the refinery, power only there. Met = the refinery working for 2 "
                "samples.",
        "setup_lua": COMMON + SETUP_FAR,
        "objectives": [{
            "name": "crude-arrives", "minutes": 55, "hold_samples": 2,
            "goal": "@{agent} the oil refinery at [gps={rx},{ry}] needs crude from the well at [gps={wx},{wy}] (it never "
                    "runs dry). Get it there please; what you need is in the chest by the refinery.",
            "answer": "Your call. Everything it needs is in that chest; the well is fine.",
            "score": [{"name": "refinery_working", "target": 1, "lua": WORKING}]}],
        "score": [],
    }
    out = ROOT / "bench" / "scenarios" / "b10-far-crude.json"
    out.write_text(json.dumps(far, indent=1))
    print(out)


if __name__ == "__main__":
    main()
