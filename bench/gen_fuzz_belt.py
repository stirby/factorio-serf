#!/usr/bin/env python3
"""Variants of the "belt it over there" order, to find what the belt fast path (jev/quickbelt.py) gets wrong: what
the far end is (a chest, a furnace, an assembler, a boiler, the input belt of a furnace row, an inserter picking off
the ground), which way the source belt runs, how far and in which direction the far end is, what's in between (a busy
belt, a pipe, a wall, trees) and how the order is worded (either point first). Writes bench/scenarios/f-belt-NN.json
(deterministic for a seed) and bench/suites/fuzz-belt.json. Each is scored by what reached the far end.

    .venv/bin/python bench/gen_fuzz_belt.py 12 [seed]"""
import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMMON = (ROOT / "bench" / "scenarios" / "lua" / "x-common.lua").read_text()

DIRS = {"east": (1, 0), "west": (-1, 0), "south": (0, 1), "north": (0, -1)}
OPP = {"east": "west", "west": "east", "north": "south", "south": "north"}
# sink kind -> (item on the source belt, how people name the far end, score lua on storage.bench_belt, target)
SINKS = {
    "chest": ("iron-plate", ["the chest", "that chest", "the iron chest"],
              "local b=storage.bench_belt return b.sink.valid and b.sink.get_item_count('iron-plate') or 0", 10),
    "furnace": ("iron-ore", ["the furnace", "that stone furnace"],
                "local b=storage.bench_belt return b.sink.valid and b.sink.products_finished or 0", 3),
    "assembler": ("iron-plate", ["the gear assembler", "the assembler", "that assembling machine"],
                  "local b=storage.bench_belt return b.sink.valid and b.sink.products_finished or 0", 5),
    "boiler": ("coal", ["the boiler", "that boiler"],
               "local b=storage.bench_belt local i=b.sink.valid and b.sink.get_fuel_inventory() return i and "
               "i.get_item_count('coal') or 0", 5),
    "row": ("iron-ore", ["the furnaces", "the smelter row", "the furnace row's input belt"],
            "local b=storage.bench_belt local n=0 for _,e in pairs(b.row) do if e.valid then n=n+e.products_finished "
            "end end return n", 3),
    "ground": ("copper-plate", ["the inserter into the chest", "the chest with the inserter"],
               "local b=storage.bench_belt return b.sink.valid and b.sink.get_item_count('copper-plate') or 0", 10),
}
WORDING = [
    "@{{agent}} belt the {item} from [gps={{sx}},{{sy}}] to {sink} at [gps={{tx}},{{ty}}]",
    "@{{agent}} get that {item} over to {sink} [gps={{tx}},{{ty}}] from the belt at [gps={{sx}},{{sy}}]",
    "@{{agent}} {sink} at [gps={{tx}},{{ty}}] needs {item}, it's on the belt at [gps={{sx}},{{sy}}]",
    "@{{agent}} connect the belt end at [gps={{sx}},{{sy}}] to {sink} at [gps={{tx}},{{ty}}]",
    "@{{agent}} run a belt from [gps={{sx}},{{sy}}] to {sink} [gps={{tx}},{{ty}}] so it gets {item}",
]
ITEM_WORDS = {"iron-plate": "iron plates", "iron-ore": "iron ore", "coal": "coal", "copper-plate": "copper"}


def build(rnd: random.Random, kind: str, src_dir: str, dist: int, angle: float, src_len: int, obstacle: str):
    """Entities (name, x, y, extra) relative to (0, 0) at the source belt's end, plus the far point and score keys."""
    item = SINKS[kind][0]
    ents = []
    dx, dy = DIRS[src_dir]
    for k in range(src_len):  # the source belt, ending at (0, 0)
        ents.append(("transport-belt", -dx * k + 0.5, -dy * k + 0.5, {"direction": src_dir}))
    # burner inserters with fuel of their own: no power needed at the source
    ents.append(("burner-inserter", -dx * src_len + 0.5, -dy * src_len + 0.5, {"direction": OPP[src_dir],
                                                                            "fuel": "coal"}))
    ents.append(("SOURCE", -dx * (src_len + 1) + 0.5, -dy * (src_len + 1) + 0.5, {"item": item}))
    # what a belt job needs, beside the source (the lab stage has no storage)
    ents.append(("SUPPLY", -dx * (src_len + 1) + dy * 2 + 0.5, -dy * (src_len + 1) - dx * 2 + 0.5, {}))
    tx, ty = round(math.cos(angle) * dist), round(math.sin(angle) * dist)
    grid = (tx + 4, ty + 4)
    if kind == "chest":
        ents.append(("iron-chest", tx + 0.5, ty + 0.5, {"sink": True}))
    elif kind == "furnace":
        ents.append(("stone-furnace", tx + 1, ty + 1, {"sink": True, "fuel": "wood"}))
    elif kind == "assembler":
        ents.append(("assembling-machine-1", tx + 0.5, ty + 0.5, {"sink": True, "recipe": "iron-gear-wheel"}))
        ents.append(("small-electric-pole", tx + 2.5, ty - 1.5, {}))
        # something takes its gears away: an assembler with a full output stops after a few crafts
        ents.append(("inserter", tx + 2.5, ty + 0.5, {"direction": "west"}))
        ents.append(("iron-chest", tx + 3.5, ty + 0.5, {}))
        grid = (tx + 6, ty - 3)
    elif kind == "boiler":
        ents.append(("boiler", tx + 0.5, ty + 1, {"sink": True, "direction": "north"}))
    elif kind == "row":
        # three furnaces with inserters off an input belt that starts at (tx, ty) and runs away from the source
        rd = max(DIRS, key=lambda d: DIRS[d][0] * math.cos(angle) + DIRS[d][1] * math.sin(angle))
        rx, ry = DIRS[rd]
        lx, ly = ry, -rx  # a side of it

        def c(a):
            return tx + rx * a + 0.5, ty + ry * a + 0.5
        for k in range(10):
            ents.append(("transport-belt", *c(k), {"direction": rd}))
        side = {(0, -1): "north", (0, 1): "south", (1, 0): "east", (-1, 0): "west"}[(-lx, -ly)]
        for a in (2, 5, 8):
            cx, cy = c(a)
            ents.append(("inserter", cx + lx, cy + ly, {"direction": side}))
            ents.append(("stone-furnace", cx + lx * 2.5 + rx * 0.5, cy + ly * 2.5 + ry * 0.5, {"row": True, "fuel": "wood"}))
        for a in (4, 7):
            cx, cy = c(a)
            ents.append(("small-electric-pole", cx + lx, cy + ly, {}))
        cx, cy = c(4)
        grid = (cx - lx * 4 - 0.5, cy - ly * 4 - 0.5)
    elif kind == "ground":
        # an inserter that picks up from bare ground (west of it) into a chest
        ents.append(("iron-chest", tx + 2.5, ty + 0.5, {"sink": True}))
        ents.append(("inserter", tx + 1.5, ty + 0.5, {"direction": "west"}))
        ents.append(("small-electric-pole", tx + 1.5, ty - 0.5, {}))
        grid = (tx + 1, ty - 4)
    if obstacle != "none":
        mx, my = round(tx / 2), round(ty / 2)
        # across the straight line between the ends, 24 long
        horiz = abs(tx) >= abs(ty)
        for k in range(-12, 12):
            x, y = (mx + 0.5, my + k + 0.5) if horiz else (mx + k + 0.5, my + 0.5)
            if obstacle == "belt":
                ents.append(("transport-belt", x, y, {"direction": "south" if horiz else "east"}))
            elif obstacle == "pipe":
                ents.append(("pipe", x, y, {}))
            elif obstacle == "wall":
                ents.append(("stone-wall", x, y, {}))
            elif obstacle == "trees" and rnd.random() < 0.4:
                ents.append(("tree-01", x + rnd.choice([-2, 0, 2]), y, {}))
        if obstacle == "belt":  # a busy one: stone fed in at its start
            x, y = (mx + 0.5, my - 13.5) if horiz else (mx - 13.5, my + 0.5)
            ents.append(("burner-inserter", x, y, {"direction": "north" if horiz else "west", "fuel": "coal"}))
            x, y = (mx + 0.5, my - 14.5) if horiz else (mx - 14.5, my + 0.5)
            ents.append(("SOURCE", x, y, {"item": "stone"}))
    return item, ents, (tx, ty), grid


def setup_lua(ents, grid, target) -> str:
    xs = [e[1] for e in ents] + [grid[0]]
    ys = [e[2] for e in ents] + [grid[1]]
    x0, y0 = math.floor(min(xs)) - 4, math.floor(min(ys)) - 4
    w, h = math.ceil(max(xs)) + 4 - x0, math.ceil(max(ys)) + 4 - y0
    lines = [COMMON, f"""
local W, H = {w}, {h}
local ox, oy
if LAB then ox, oy = find_near(-60, 60, W, H, 120) else ox, oy = find_ring(W, H, 40, 200) end
clear(ox, oy, W, H)
local X, Y = ox - ({x0}), oy - ({y0})
local b = {{ row = {{}} }}
storage.bench_belt = b"""]
    for name, x, y, extra in ents:
        if name == "SUPPLY":
            lines.append(f'do local c = put("steel-chest", X + {x}, Y + {y}) for n, k in pairs {{ ["transport-belt"] = 200, '
                         '["underground-belt"] = 20, ["inserter"] = 10, ["burner-inserter"] = 10, '
                         '["small-electric-pole"] = 30, ["coal"] = 50 } do c.insert { name = n, count = k } end end')
            continue
        if name == "SOURCE":
            lines.append(f'source(X + {x}, Y + {y}, {{ "{extra["item"]}" }})')
            continue
        args = f'"{name}", X + {x}, Y + {y}'
        if extra.get("direction"):
            args += f', D.{extra["direction"]}'
        if name.startswith("tree"):
            lines.append(f'pcall(function() s.create_entity {{ name = "{name}", position = {{ X + {x}, Y + {y} }} }} end)')
            continue
        lines.append(f'do local e = put({args})')
        if extra.get("recipe"):
            lines.append(f'  e.set_recipe("{extra["recipe"]}")')
        if extra.get("fuel"):
            lines.append(f'  e.insert {{ name = "{extra["fuel"]}", count = 50 }}')
        if extra.get("sink"):
            lines.append("  b.sink = e")
        if extra.get("row"):
            lines.append("  table.insert(b.row, e)")
        lines.append("end")
    lines.append(f"grid(X + {grid[0]}, Y + {grid[1]}, 3000000)")
    lines.append(f'put("small-electric-pole", X + {grid[0] + 1.5}, Y + {grid[1] + 0.5})')
    lines.append(f"return {{ sx = math.floor(X), sy = math.floor(Y), tx = math.floor(X + {target[0]}), "
                 f"ty = math.floor(Y + {target[1]}) }}")
    return "\n".join(lines)


def main(n: int, seed: int):
    rnd = random.Random(seed)
    names = []
    for i in range(1, n + 1):
        kind = rnd.choice(list(SINKS))
        src_dir = rnd.choice(list(DIRS))
        dist = rnd.choice([14, 24, 40, 70])
        angle = rnd.choice(range(8)) * math.pi / 4 + rnd.uniform(-0.3, 0.3)
        src_len = rnd.choice([2, 4, 8])
        obstacle = rnd.choice(["none", "belt", "pipe", "wall", "trees"]) if dist >= 24 else "none"
        item, ents, (tx, ty), grid = build(rnd, kind, src_dir, dist, angle, src_len, obstacle)
        lua = setup_lua(ents, grid, (tx, ty))
        sink = rnd.choice(SINKS[kind][1])
        goal = rnd.choice(WORDING).format(item=ITEM_WORDS[item], sink=sink)
        if goal.startswith("@{agent} the") or goal.startswith("@{agent} that"):
            goal = goal.replace("@{agent} t", "@{agent} T", 1)
        name = f"f-belt-{i:02d}"
        scn = {"name": name, "stage": rnd.choice(["stage-lab", "stage-s3-steel-oil-ready"]), "minutes": 10,
               "agents": 1, "kind": "directive", "group": "fuzz",
               "note": f"Belt variant {i} (seed {seed}): {item} from a {src_len}-tile belt running {src_dir} to a "
                       f"{kind} {dist} tiles away, {obstacle} in between; order: {goal}",
               "setup_lua": lua,
               "objectives": [{"name": "delivered", "minutes": 8, "hold_samples": 1, "goal": goal,
                               "answer": "Your call.",
                               "score": [{"name": "delivered", "lua": SINKS[kind][2], "target": SINKS[kind][3]}]}],
               "score": []}
        (ROOT / "bench" / "scenarios" / f"{name}.json").write_text(json.dumps(scn, indent=1) + "\n")
        names.append(name)
        print(f"{name}: {kind:9} src {src_dir:5} len {src_len} dist {dist:2} angle {math.degrees(angle):4.0f} "
              f"{obstacle:5} {goal[9:90]}")
    (ROOT / "bench" / "suites" / "fuzz-belt.json").write_text(json.dumps(names, indent=1) + "\n")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 12, int(sys.argv[2]) if len(sys.argv) > 2 else 1)
