#!/usr/bin/env python3
"""Variants of the mining order, to find what the mine and belt fast paths get wrong: which ore, the patch's size
and shape, how far the ore has to go and in which direction, whether the far end is a belt stub or a bare chest,
small or medium poles, a rate or a drill count or nothing, and how the order is worded. Writes bench/scenarios/
f-mine-NN.json (deterministic for a seed) and bench/suites/fuzz-mine.json. Each is scored by ore arriving in the
chest and drills on the patch working.

    .venv/bin/python bench/gen_fuzz_mine.py 10 [seed]"""
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMMON = (ROOT / "bench" / "scenarios" / "lua" / "x-common.lua").read_text()

ORES = {"iron-ore": ["iron", "iron ore"], "copper-ore": ["copper", "copper ore"], "coal": ["coal"],
        "stone": ["stone"]}
DIRS = [(1, 0), (0, 1), (-1, 0), (0, -1), (0.7, 0.7), (-0.7, 0.7), (0.7, -0.7), (-0.7, -0.7)]
WORDING = [
    "@{{agent}} set up {a} {ore} mine on the patch at [gps={{patch}}] and belt the ore back to {dest}{want}{power}"
    "{supply}",
    "@{{agent}} put drills on the {ore} at [gps={{patch}}] and bring it by belt to {dest}{want}{supply}",
    "@{{agent}} mine the {ore} here [gps={{patch}}] and belt it to {dest}{want}{supply}",
    "@{{agent}} we need {ore} at {dest}: set up drills on the patch at [gps={{patch}}] and run a belt over{want}"
    "{supply}",
    "@{{agent}} can you get {a} {ore} mine going at [gps={{patch}}]? belt the ore to {dest}{want}{power}{supply}",
]


def setup_lua(ore: str, w: int, h: int, ellipse: bool, dist: int, d: tuple, stub: bool, pole: str) -> str:
    dx, dy = d
    poles = 45 if pole == "medium-electric-pole" else 90
    return COMMON + f"""
-- f-mine setup: a delivery point (a steel chest{' filled by a fast inserter from the end of a 3-tile belt stub' if stub
    else ''}, a grid corner, a supply chest) and a fresh {w}x{h} {ore} patch ~{dist} tiles away.
local ddx, ddy
if LAB then ddx, ddy = find_near(-140, -4, 10, 8, 60) else ddx, ddy = find_ring(10, 8, 30, 140) end
clear(ddx, ddy, 10, 8)
local X, Y = ddx + 1, ddy + 1
local chest = put("steel-chest", X + 0.5, Y + 0.5)
{'put("fast-inserter", X + 1.5, Y + 0.5, D.east) for x = 2, 4 do put("transport-belt", X + x + 0.5, Y + 0.5, D.west) end'
     if stub else ''}
grid(X + 1, Y + 3, 3000000)
local pole = put("{pole}", X + 2.5, Y + 2.5)
local supply = put("steel-chest", X + 0.5, Y + 4.5)
for name, n in pairs {{ ["electric-mining-drill"] = 12, ["transport-belt"] = 400, ["underground-belt"] = 20,
  ["{pole}"] = {poles}, ["splitter"] = 4, ["fast-inserter"] = 4, ["inserter"] = 6 }} do
  supply.insert {{ name = name, count = n }}
end
local W, H = {w}, {h}
local px, py
local ok, x, y = pcall(find_near, X + {dx} * {dist}, Y + {dy} * {dist}, W + 4, H + 4, 60)
if ok then px, py = x, y end
if not px then
  for _, d in pairs {{ {{ 1, 0 }}, {{ 0, 1 }}, {{ 0, -1 }}, {{ -1, 0 }} }} do
    ok, x, y = pcall(find_near, X + d[1] * {dist}, Y + d[2] * {dist}, W + 4, H + 4, 60)
    if ok then px, py = x, y break end
  end
end
if not px then error("no open ground for the ore patch") end
clear(px, py, W + 4, H + 4)
local cx, cy = px + 2 + W / 2, py + 2 + H / 2
for x = px + 2, px + 1 + W do
  for y = py + 2, py + 1 + H do
    local ex, ey = (x + 0.5 - cx) / (W / 2), (y + 0.5 - cy) / (H / 2)
    if {'true' if not ellipse else 'false'} or ex * ex + ey * ey <= 1.05 then
      s.create_entity {{ name = "{ore}", position = {{ x + 0.5, y + 0.5 }}, amount = 3000 }}
    end
  end
end
storage.bench_mine = {{ chest = chest, pole = pole, patch = {{ {{ px, py }}, {{ px + W + 4, py + H + 4 }} }}, X = X, Y = Y }}
return {{ patch = gps(cx, cy), chest = gps(X + {'4' if stub else '0'}, Y), supply = gps(X, Y + 4),
  dist = math.floor(math.sqrt((cx - X) ^ 2 + (cy - Y) ^ 2)) }}"""


def main(n: int, seed: int):
    rnd = random.Random(seed)
    names = []
    for i in range(1, n + 1):
        ore = rnd.choice(list(ORES))
        w, h = rnd.choice([6, 8, 10, 12, 16]), rnd.choice([6, 8, 10, 12, 16])
        ellipse = rnd.random() < 0.5
        dist = rnd.choice([40, 80, 150, 250])
        d = rnd.choice(DIRS)
        stub = rnd.random() < 0.6
        pole = rnd.choice(["small-electric-pole", "medium-electric-pole"])
        want = rnd.choice(["", "rate", "drills"])
        stage = rnd.choice(["stage-lab", "stage-s3-steel-oil-ready"])
        if want == "rate":
            rate = rnd.choice([30, 60, 90])
            wtext, target, need = f", I want at least {rate} ore a minute", min(rate * 0.8, 90), 2
        elif want == "drills":
            k = rnd.choice([2, 4, 6])
            wtext, target, need = f", {k} drills", min(k * 18, 90), min(k, 2)
        else:
            wtext, target, need = "", 30, 2
        dest = ("the belt end at [gps={chest}], it feeds that chest" if stub and rnd.random() < 0.5
                else "the chest at [gps={chest}]")
        goal = rnd.choice(WORDING).format(
            a="an" if ore[0] in "aeiou" or ore.startswith("iron") else "a", ore=rnd.choice(ORES[ore]),
            dest=dest, want=wtext, power=rnd.choice(["", ". Power it from the grid there"]),
            supply=rnd.choice(["", ". Drills, belts and poles are in the chest at [gps={supply}]"]))
        name = f"f-mine-{i:02d}" if seed == 1 else f"f-mine-s{seed}-{i:02d}"  # seeds don't overwrite each other
        scn = {"name": name, "stage": stage, "minutes": 14 + dist // 20, "agents": 1, "kind": "directive",
               "group": "fuzz",
               "note": f"Mine variant {i} (seed {seed}): {w}x{h} {'round' if ellipse else 'square'} {ore} patch "
                       f"~{dist} tiles away, {'belt stub' if stub else 'bare chest'}, {pole}s, {stage}; order: {goal}",
               "setup_lua": setup_lua(ore, w, h, ellipse, dist, d, stub, pole),
               "objectives": [{
                   "name": "mine", "minutes": 12 + dist // 20, "hold_samples": 2, "goal": goal,
                   "answer": "Your call. Power it from the grid at the chest.",
                   "score": [
                       {"name": "ore_per_min", "target": round(target), "rate": True,
                        "lua": f"local c=storage.bench_mine.chest return c.valid and c.get_item_count('{ore}') or 0"},
                       # working on any grid: the base's is as good as the one at the chest
                       {"name": "drills_working", "target": need,
                        "lua": "local b=storage.bench_mine local n=0 for _,e in pairs(s.find_entities_filtered{"
                               "area=b.patch, name='electric-mining-drill'}) do if e.status=="
                               "defines.entity_status.working then n=n+1 end end return n"}]}],
               "score": []}
        (ROOT / "bench" / "scenarios" / f"{name}.json").write_text(json.dumps(scn, indent=1) + "\n")
        names.append(name)
        print(f"{name}: {ore:10} {w:2}x{h:<2} {'round ' if ellipse else 'square'} {dist:3} {str(d):12} "
              f"{'stub' if stub else 'chest'} {pole[:5]} {stage[6:9]} {goal[9:100]}")
    suite = "fuzz-mine" if seed == 1 else f"fuzz-mine-s{seed}"
    (ROOT / "bench" / "suites" / f"{suite}.json").write_text(json.dumps(names, indent=1) + "\n")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 10, int(sys.argv[2]) if len(sys.argv) > 2 else 1)
