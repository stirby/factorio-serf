#!/usr/bin/env python3
"""Variants of "more of the same": parallel belts carrying the same items; the first order builds off one of them
(a quick build), the second asks for the same on one to three of the others. Finds what the copy fast path
(jev/quickcopy.py) gets wrong: the product, the belts' direction and spacing, how many copies, how the second order is
worded. Writes bench/scenarios/f-copy-NN.json (deterministic for a seed) and bench/suites/fuzz-copy.json. Met = the
first build makes something, then every copied belt has fed machines making it too.

    .venv/bin/python bench/gen_fuzz_copy.py 8 [seed]"""
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bench"))
from gen_fuzz import DIRS, LEFT  # noqa: E402

PRODUCTS = {  # product -> (machine kind, items on each belt, how people say it)
    "iron-gear-wheel": ("asm", ["iron-plate"], ["gears", "iron gears"]),
    "pipe": ("asm", ["iron-plate"], ["pipes"]),
    "copper-cable": ("asm", ["copper-plate"], ["copper cable", "cable"]),
    "firearm-magazine": ("asm", ["iron-plate"], ["ammo"]),
    "steel-plate": ("furnace", ["iron-plate", "coal"], ["steel"]),
    "iron-plate": ("furnace", ["iron-ore", "coal"], ["iron plates"]),
}
FIRST = ["@{{agent}} make {what} off the belt at [gps={{b0x}},{{b0y}}]{count}",
         "@{{agent}} set up {what} production off [gps={{b0x}},{{b0y}}]{count}"]
SECOND = {
    1: ["@{{agent}} copy that to [gps={{b1x}},{{b1y}}]",
        "@{{agent}} same again on the belt at [gps={{b1x}},{{b1y}}]"],
    2: ["@{{agent}} two more just like it at [gps={{b1x}},{{b1y}}] and [gps={{b2x}},{{b2y}}]",
        "@{{agent}} now the same on the belts at [gps={{b1x}},{{b1y}}] and [gps={{b2x}},{{b2y}}]"],
    3: ["@{{agent}} do the same thing at [gps={{b1x}},{{b1y}}], [gps={{b2x}},{{b2y}}] and [gps={{b3x}},{{b3y}}]",
        "@{{agent}} three more of those: [gps={{b1x}},{{b1y}}], [gps={{b2x}},{{b2y}}], [gps={{b3x}},{{b3y}}]"],
}


def setup_lua(direction: str, items: list[str], n: int, gap: int) -> str:
    """n parallel 30-tile belts running `direction`, `gap` tiles apart (to the left of each other), each fed at its
    upstream end from infinity chests (one item per side), always-on power, a pole by each belt's start."""
    dx, dy = DIRS[direction]
    lx, ly = DIRS[LEFT[direction]]
    lines = [f"local dx, dy, lx, ly = {dx}, {dy}, {lx}, {ly}", '''local s, f = game.surfaces.nauvis, game.forces.player
local function free(x, y, w, h)
  local a = { { x, y }, { x + w, y + h } }
  if s.count_tiles_filtered { area = a, collision_mask = "water_tile" } > 0 then return false end
  return s.count_entities_filtered { area = a, type = { "tree", "simple-entity", "resource", "corpse", "fish" },
    invert = true } == 0 and s.count_entities_filtered { area = a, type = "resource" } == 0
end
local fx, fy
for r = 60, 400, 4 do
  for _, d in pairs { { 1, 0 }, { 0, 1 }, { -1, 0 }, { 0, -1 }, { 1, 1 }, { -1, 1 }, { 1, -1 }, { -1, -1 } } do
    if not fx and free(d[1] * r, d[2] * r, 100, 100) then fx, fy = d[1] * r, d[2] * r end
  end
end
if not fx then error("no free area") end
local cx, cy = math.floor(fx) + 50, math.floor(fy) + 50
for _, e in pairs(s.find_entities_filtered { area = { { cx - 48, cy - 48 }, { cx + 48, cy + 48 } },
  type = { "tree", "simple-entity", "corpse", "fish", "item-entity" } }) do e.destroy() end
local D = defines.direction
local dirname = dx == 1 and "east" or dx == -1 and "west" or dy == 1 and "south" or "north"
local function at(along, across) return cx + dx * (along - 15) + lx * (across - 20) + 0.5,
  cy + dy * (along - 15) + ly * (across - 20) + 0.5 end
local function put(name, x, y, dir)
  local e = s.create_entity { name = name, position = { x, y }, direction = dir, force = f }
  if not e then error("could not place " .. name .. " at " .. x .. "," .. y) end
  return e
end
local out, areas = {}, {}''']
    for k in range(n):
        a = gap * k
        lines.append(f"for a = 0, 29 do local x, y = at(a, {a}) put('transport-belt', x, y, D[dirname]) end")
        for j, item in enumerate(items):
            side = 1 if j == 0 else -1
            lines.append(f"""do
  local chx, chy = at(0, {a} + {2 * side})
  local c = put('infinity-chest', chx, chy)
  c.set_infinity_container_filter(1, {{ name = '{item}', count = 100, mode = 'exactly' }})
  local inx, iny = at(0, {a} + {side})
  local dname = {side} == 1 and (lx == 1 and 'east' or lx == -1 and 'west' or ly == 1 and 'south' or 'north')
    or (lx == 1 and 'west' or lx == -1 and 'east' or ly == 1 and 'north' or 'south')
  put('fast-inserter', inx, iny, D[dname])
end""")
        lines.append(f"do local px, py = at(1, {a} - 1) put('small-electric-pole', px, py) end")
        lines.append(f"""do
  local x1, y1 = at(-2, {a} - {gap // 2})
  local x2, y2 = at(32, {a} + {gap // 2})
  areas[{k + 1}] = {{ {{ math.min(x1, x2), math.min(y1, y2) }}, {{ math.max(x1, x2), math.max(y1, y2) }} }}
  local bx, by = at(0, {a})
  out['b{k}x'], out['b{k}y'] = math.floor(bx), math.floor(by)
end""")
    lines.append(f'''do
  local ex, ey = at(-3, -3)
  local e = put('electric-energy-interface', ex, ey)
  e.power_production, e.electric_buffer_size = 600000, 60000000
  for k = 0, {n - 1} do local px, py = at(-1, {gap} * k - 1) put('small-electric-pole', px, py) end
  for k = 0, {n - 2} do for t = 1, {gap // 6} do local px, py = at(-1, {gap} * k - 1 + 6 * t)
    pcall(function() put('small-electric-pole', px, py) end) end end
end
storage.bench_copy = {{ areas = areas }}
return out''')
    return "\n".join(lines)


# fed machines in area k making the product (not hand-fed from a chest)
MADE = ("local A=storage.bench_copy.areas[{k}] local function fedok(m) local n=0 for _,i in pairs(s.find_entities_filtered"
        "{{type='inserter',force=f,area={{{{m.position.x-3,m.position.y-3}},{{m.position.x+3,m.position.y+3}}}}}}) do "
        "if i.drop_target==m then local p=i.pickup_target if p then if p.type=='infinity-container' or "
        "p.type=='container' then return false end n=n+1 end end end return n>0 end local t=0 for _,m in "
        "pairs(s.find_entities_filtered{{area=A,force=f,type={{'assembling-machine','furnace'}}}}) do local r=m.get_recipe() "
        "if (m.type=='furnace' or (r and r.name=='{prod}')) and fedok(m) then t=t+m.products_finished end end return t")


def main(n: int, seed: int):
    rnd = random.Random(seed)
    names = []
    for i in range(1, n + 1):
        prod = rnd.choice(list(PRODUCTS))
        kind, items, says = PRODUCTS[prod]
        direction = rnd.choice(list(DIRS))
        copies = rnd.choice([1, 2, 2, 3])
        gap = rnd.choice([12, 16, 20])
        what = rnd.choice(says)
        count = rnd.choice(["", ", 2 assemblers" if kind == "asm" else ", 3 furnaces"])
        first = rnd.choice(FIRST).format(what=what, count=count).replace("{{", "{").replace("}}", "}")
        second = rnd.choice(SECOND[copies]).replace("{{", "{").replace("}}", "}")
        target = 3 if prod == "steel-plate" else 5
        name = f"f-copy-{i:02d}"
        scn = {"name": name, "stage": "stage-s3-steel-oil-ready", "minutes": 16, "agents": 1, "kind": "directive",
               "group": "fuzz",
               "note": f"Copy variant {i} (seed {seed}): {what} off belts running {direction}, {gap} tiles apart, then "
                       f"{copies} cop{'y' if copies == 1 else 'ies'}; orders: {first} / {second}",
               "setup_lua": setup_lua(direction, items, copies + 1, gap),
               "objectives": [
                   {"name": "first", "minutes": 5, "hold_samples": 1, "goal": first, "answer": "Your call.",
                    "score": [{"name": "made", "lua": MADE.format(k=1, prod=prod), "target": target}]},
                   {"name": "copies", "minutes": 10, "hold_samples": 1, "goal": second, "answer": "Your call.",
                    "score": [{"name": f"made_{k}", "lua": MADE.format(k=k + 1, prod=prod), "target": target}
                              for k in range(1, copies + 1)]}],
               "score": []}
        (ROOT / "bench" / "scenarios" / f"{name}.json").write_text(json.dumps(scn, indent=1) + "\n")
        names.append(name)
        print(f"{name}: {prod:18} {direction:5} gap={gap} copies={copies} | {first[9:70]} | {second[9:80]}")
    (ROOT / "bench" / "suites" / "fuzz-copy.json").write_text(json.dumps(names, indent=1) + "\n")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 8, int(sys.argv[2]) if len(sys.argv) > 2 else 1)
