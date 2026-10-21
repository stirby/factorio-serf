#!/usr/bin/env python3
"""Variants of "something's wrong, fix it": a small working line (iron ore and coal on a belt -> 4 stone furnaces ->
plate belt -> chest -> gear assembler -> chest) with one or two faults put in, and a vague order pointing somewhere
near it. Finds what the fault model and the fix path miss. Writes bench/scenarios/f-fix-NN.json (deterministic for
a seed) and bench/suites/fuzz-fix.json. Met = gears reaching the last chest and the furnaces working, for 2 samples.

    .venv/bin/python bench/gen_fuzz_fix.py 10 [seed]"""
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMMON = (ROOT / "bench" / "scenarios" / "lua" / "x-common.lua").read_text()

# The line, all relative to (X, Y): ore belt y=0.5 running east (x 0..19), furnaces south of it, plate belt y=5.5
# running east to an inserter into the plate chest, then the gear assembler and the gear chest.
LINE = """
local W, H = 36, 14
local ox, oy
if LAB then ox, oy = find_near(-60, -60, W, H, 120) else ox, oy = find_ring(W, H, 40, 200) end
clear(ox, oy, W, H)
local X, Y = ox + 4, oy + 4
local b = { furnaces = {}, poles = {} }
storage.bench_fix = b
grid(X - 3, Y + 8, 3000000)
for x = 0, 19 do put("transport-belt", X + x + 0.5, Y + 0.5, D.east) end
-- ore onto the south lane from the north, coal onto the north lane from the south (separate lanes: no jam)
source(X + 0.5, Y - 1.5, { "iron-ore" })
put("fast-inserter", X + 0.5, Y - 0.5, D.north)  -- 4 stone furnaces eat ~75 ore/min: more than a burner moves
put("small-electric-pole", X - 0.5, Y - 0.5)
source(X + 1.5, Y + 2.5, { "coal" })
put("burner-inserter", X + 1.5, Y + 1.5, D.south).insert { name = "coal", count = 50 }
for i = 0, 3 do
  local fx = 3 + 3 * i
  b["in" .. i] = put("inserter", X + fx + 0.5, Y + 1.5, D.north)
  local fu = put("stone-furnace", X + fx + 1, Y + 3)
  fu.insert { name = "coal", count = 5 }
  table.insert(b.furnaces, fu)
  b["out" .. i] = put("inserter", X + fx + 0.5, Y + 4.5, D.north)
end
-- medium poles reach both inserter rows
b.poles[1] = put("medium-electric-pole", X + 5.5, Y + 1.5)
b.poles[2] = put("medium-electric-pole", X + 11.5, Y + 1.5)
for x = 3, 20 do b["belt" .. x] = put("transport-belt", X + x + 0.5, Y + 5.5, D.east) end
b.ins_chest = put("inserter", X + 21.5, Y + 5.5, D.west)
b.plates = put("iron-chest", X + 22.5, Y + 5.5)
b.ins_asm = put("inserter", X + 23.5, Y + 5.5, D.west)
b.asm = put("assembling-machine-1", X + 25.5, Y + 5.5)
b.asm.set_recipe("iron-gear-wheel")
b.ins_out = put("inserter", X + 27.5, Y + 5.5, D.west)
b.gears = put("iron-chest", X + 28.5, Y + 5.5)
b.pole_chest = put("small-electric-pole", X + 21.5, Y + 4.5)
b.pole_asm = put("small-electric-pole", X + 27.5, Y + 4.5)
put("small-electric-pole", X - 1.5, Y + 7.5)
put("small-electric-pole", X + 0.5, Y + 2.5)
put("small-electric-pole", X + 16.5, Y + 4.5)
"""
# fault -> (lua that breaks the line, what it is)
FAULTS = {
    "belt_gap": ("b.gap = {X + 8.5, Y + 0.5} s.find_entities_filtered{position=b.gap, name='transport-belt'}[1].destroy()",
                 "a missing tile in the ore belt before the third furnace"),
    "belt_reversed": ("b.belt12.direction = D.west", "a plate-belt tile turned to face back"),
    "no_chest_inserter": ("b.ins_chest.destroy()", "the inserter into the plate chest missing"),
    "wrong_recipe": ("b.asm.set_recipe('pipe')", "the gear assembler set to pipes"),
    "pole_missing": ("b.pole_asm.destroy()", "the pole by the gear assembler missing"),
    "chest_full": ("b.gears.insert{name='stone', count=1600}", "the gear chest full of stone"),
    "inserter_backwards": ("b.in1.direction = D.south", "the second furnace's input inserter facing backwards"),
    "furnace_no_fuel": ("for _, f in pairs(b.furnaces) do f.get_fuel_inventory().clear() end "
                        "for _, e in pairs(s.find_entities_filtered{area={{X+1,Y+1},{X+2,Y+2}}, name='burner-inserter'}) "
                        "do e.destroy() end", "no coal reaching the furnaces (its feeder gone, their fuel empty)"),
}
# faults that can't go together (one hides the other's symptom completely, or they touch the same thing)
CLASH = [{"no_chest_inserter", "belt_reversed"}, {"wrong_recipe", "chest_full"}, {"pole_missing", "wrong_recipe"},
         {"belt_gap", "furnace_no_fuel"}, {"inserter_backwards", "furnace_no_fuel"}]
WORDING = [
    ("@{agent} the smelter at [gps={fx},{fy}] isn't making much, can you take a look?", "smelter"),
    ("@{agent} no gears coming out of [gps={gx},{gy}], what's up with it?", "gears"),
    ("@{agent} something's wrong with the iron line at [gps={fx},{fy}], fix it please", "smelter"),
    ("@{agent} fix the gear setup at [gps={gx},{gy}]", "gears"),
    ("@{agent} production at [gps={fx},{fy}] is really slow. sort it out?", "smelter"),
    ("@{agent} the gear chest at [gps={gx},{gy}] should be filling up but it isn't", "gears"),
]


def main(n: int, seed: int):
    rnd = random.Random(seed)
    names = []
    for i in range(1, n + 1):
        k = rnd.choice([1, 1, 2])
        while True:
            faults = rnd.sample(sorted(FAULTS), k)
            if not any(set(c) <= set(faults) for c in CLASH):
                break
        goal, _ = rnd.choice(WORDING)
        stage = rnd.choice(["stage-lab", "stage-s3-steel-oil-ready"])
        lua = (COMMON + LINE + "\n".join(FAULTS[f][0] for f in faults) +
               "\nreturn { fx = math.floor(X + 9), fy = math.floor(Y + 3), gx = math.floor(X + 28), "
               "gy = math.floor(Y + 5) }")
        name = f"f-fix-{i:02d}"
        what = "; ".join(FAULTS[f][1] for f in faults)
        scn = {"name": name, "stage": stage, "minutes": 12, "agents": 1, "kind": "directive", "group": "fuzz",
               "note": f"Fix variant {i} (seed {seed}): {what}; order: {goal}",
               "faults": faults, "setup_lua": lua,
               "objectives": [{
                   "name": "fixed", "minutes": 10, "hold_samples": 2, "goal": goal,
                   "answer": "Your call. Everything it needs is there; don't hand-feed it.",
                   "score": [
                       {"name": "gears_per_min", "target": 10, "rate": True,
                        "lua": "local c=storage.bench_fix.gears return c.valid and c.get_item_count('iron-gear-wheel') "
                               "or 0"},
                       {"name": "furnaces_working", "target": 3,
                        "lua": "local n=0 for _,f in pairs(storage.bench_fix.furnaces) do if f.valid and f.status=="
                               "defines.entity_status.working then n=n+1 end end return n"}]}],
               "score": []}
        (ROOT / "bench" / "scenarios" / f"{name}.json").write_text(json.dumps(scn, indent=1) + "\n")
        names.append(name)
        print(f"{name}: {', '.join(faults):40} {stage[6:9]} {goal[9:80]}")
    (ROOT / "bench" / "suites" / "fuzz-fix.json").write_text(json.dumps(names, indent=1) + "\n")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 10, int(sys.argv[2]) if len(sys.argv) > 2 else 1)
