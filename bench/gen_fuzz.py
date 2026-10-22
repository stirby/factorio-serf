#!/usr/bin/env python3
"""Variants of the quick-build test, to find what the actor's own paths get wrong: belt direction, product (one belt,
two belts, furnaces), the stated count, how the order is worded, rocks near the belt. Writes bench/scenarios/
f-quick-NN.json (deterministic for a seed). Each is scored by what belt-fed machines in the fixture made and what reached
a chest.

    .venv/bin/python bench/gen_fuzz.py 12 [seed]"""
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DIRS = {"east": (1, 0), "west": (-1, 0), "south": (0, 1), "north": (0, -1)}
LEFT = {"east": "north", "north": "west", "west": "south", "south": "east"}
# product -> (machine kind, belt items per belt (first belt, optional second), how people say it)
PRODUCTS = {
    "iron-gear-wheel": ("asm", [["iron-plate"]], ["gears", "iron gears", "gear wheels"]),
    "pipe": ("asm", [["iron-plate"]], ["pipes"]),
    "iron-chest": ("asm", [["iron-plate"]], ["iron chests"]),
    "steel-plate": ("furnace", [["iron-plate", "coal"]], ["steel"]),
    "iron-plate": ("furnace", [["iron-ore", "coal"]], ["iron plates", "plates"]),
    "automation-science-pack": ("asm", [["copper-plate"], ["iron-plate"]], ["red science", "automation science"]),
    "electronic-circuit": ("asm", [["iron-plate"], ["copper-plate"]], ["green circuits", "circuits"]),
    "copper-cable": ("asm", [["copper-plate"]], ["copper cable", "cable", "wire"]),
    "firearm-magazine": ("asm", [["iron-plate"]], ["ammo", "magazines", "yellow ammo"]),
    "stone-brick": ("furnace", [["stone", "coal"]], ["bricks", "stone bricks"]),
    "copper-plate": ("furnace", [["copper-ore", "coal"]], ["copper plates", "copper"]),
}
WORDING = ["@{{agent}} make {what} off the belt at [gps={bx},{by}]{count}{chest}",
           "@{{agent}} {what} please, off that belt [gps={bx},{by}]{count}",
           "@{{agent}} can you automate {what} from the belt at [gps={bx},{by}]?{count}{chest}",
           "@{{agent}} I need {what} made from this belt [gps={bx},{by}]{count}, into chests",
           "@{{agent}} set up {what} production off [gps={bx},{by}]{count}",
           "@{{agent}} yo can you make some {what} here [gps={bx},{by}]{count}",
           "@{{agent}} {what} from [gps={bx},{by}] pls{count}{chest}"]


def setup_lua(direction: str, feeds: list[list[str]], clutter: bool, length: int = 30, decoy: bool = False) -> str:
    """A straight belt of `length` tiles (and a second one 6 tiles to its left for two-belt products) running
    `direction`, fed from infinity chests at its upstream end, an always-on power source, poles along the start. A
    decoy: another belt 9 tiles to the right carrying stone."""
    dx, dy = DIRS[direction]
    lx, ly = DIRS[LEFT[direction]]
    lines = [f"local dx, dy, lx, ly = {dx}, {dy}, {lx}, {ly}"]
    lines.append('''local s, f = game.surfaces.nauvis, game.forces.player
local function free(x, y, w, h)
  local a = { { x, y }, { x + w, y + h } }
  if s.count_tiles_filtered { area = a, collision_mask = "water_tile" } > 0 then return false end
  return s.count_entities_filtered { area = a, type = { "tree", "simple-entity", "resource", "corpse", "fish" },
    invert = true } == 0 and s.count_entities_filtered { area = a, type = "resource" } == 0
end
local fx, fy
for r = 60, 400, 4 do
  for _, d in pairs { { 1, 0 }, { 0, 1 }, { -1, 0 }, { 0, -1 }, { 1, 1 }, { -1, 1 }, { 1, -1 }, { -1, -1 } } do
    if not fx and free(d[1] * r, d[2] * r, 80, 80) then fx, fy = d[1] * r, d[2] * r end
  end
end
if not fx then error("no free area") end
local cx, cy = math.floor(fx) + 40, math.floor(fy) + 40
for _, e in pairs(s.find_entities_filtered { area = { { cx - 38, cy - 38 }, { cx + 38, cy + 38 } },
  type = { "tree", "simple-entity", "corpse", "fish", "item-entity" } }) do e.destroy() end
local D = defines.direction
local dirname = dx == 1 and "east" or dx == -1 and "west" or dy == 1 and "south" or "north"
-- belt k: starts at (sx, sy) and runs 30 tiles in the direction; across offset 6*k to the left
local function at(along, across) return cx + dx * (along - 15) + lx * across + 0.5, cy + dy * (along - 15) + ly * across + 0.5 end
local function put(name, x, y, dir, extra)
  local spec = { name = name, position = { x, y }, direction = dir, force = f }
  for k, v in pairs(extra or {}) do spec[k] = v end
  local e = s.create_entity(spec)
  if not e then error("could not place " .. name .. " at " .. x .. "," .. y) end
  return e
end
local out = {}''')
    for k, items in enumerate(feeds):
        lines.append(f"for a = 0, {length - 1} do local x, y = at(a, {6 * k}) put('transport-belt', x, y, D[dirname]) end")
        for j, item in enumerate(items):
            # which side its feeder sits on (the item lands on the far lane): with two belts the first belt's item
            # comes from the outer side, so the lane facing the second belt stays free for made-on-site items
            side = (-1 if k == 0 else 1) if len(feeds) > 1 else (1 if j == 0 else -1)
            lines.append(f"""do
  local chx, chy = at(0, {6 * k} + {2 * side})
  local c = put('infinity-chest', chx, chy)
  c.set_infinity_container_filter(1, {{ name = '{item}', count = 100, mode = 'exactly' }})
  local inx, iny = at(0, {6 * k} + {side})
  local dname = {side} == 1 and (lx == 1 and 'east' or lx == -1 and 'west' or ly == 1 and 'south' or 'north')
    or (lx == 1 and 'west' or lx == -1 and 'east' or ly == 1 and 'north' or 'south')
  put('fast-inserter', inx, iny, D[dname])
end""")
        lines.append(f"do local px, py = at(1, {6 * k} - 1) put('small-electric-pole', px, py) end")
    lines.append('''do
  local ex, ey = at(-3, -2)
  local e = put('electric-energy-interface', ex, ey)
  e.power_production, e.electric_buffer_size = 300000, 30000000
  local px, py = at(-1, -1)
  put('small-electric-pole', px, py)
  local qx, qy = at(-1, 4)
  put('small-electric-pole', qx, qy)
end''')
    if decoy:
        lines.append(f"""for a = 0, {length - 1} do local x, y = at(a, -9) put('transport-belt', x, y, D[dirname]) end
do
  local chx, chy = at(0, -11)
  local c = put('infinity-chest', chx, chy)
  c.set_infinity_container_filter(1, {{ name = 'stone', count = 100, mode = 'exactly' }})
  local inx, iny = at(0, -10)
  put('fast-inserter', inx, iny, D[lx == 1 and 'west' or lx == -1 and 'east' or ly == 1 and 'north' or 'south'])
end""")
    if clutter:
        lines.append('''for i = 1, 6 do local x, y = at(4 + 3 * i, -4 - (i % 3)) pcall(function() s.create_entity { name = 'big-rock', position = { x, y } } end) end''')
    lines.append('''local bx, by = at(0, 0)
storage.bench_fuzz = { area = { { cx - 38, cy - 38 }, { cx + 38, cy + 38 } } }
return { bx = math.floor(bx), by = math.floor(by) }''')
    return "\n".join(lines)


HELPERS = ("local A=storage.bench_fuzz.area local function fedok(m) local n=0 for _,i in pairs(s.find_entities_filtered"
           "{type='inserter',force=f,area={{m.position.x-3,m.position.y-3},{m.position.x+3,m.position.y+3}}}) do "
           "if i.drop_target==m then local p=i.pickup_target if p then if p.type=='infinity-container' or "
           "p.type=='character' or p.type=='container' or p.type=='logistic-container' then return false end n=n+1 end "
           "end end return n>0 end local function made(rn, ty) local t=0 for _,m in pairs(s.find_entities_filtered"
           "{area=A,force=f,type=ty or 'assembling-machine'}) do local r=m.get_recipe() if (ty=='furnace' or "
           "(r and r.name==rn)) and fedok(m) then t=t+m.products_finished end end return t end local function "
           "inchest(item) local t=0 for _,c in pairs(s.find_entities_filtered{area=A,force=f,type={'container',"
           "'logistic-container'}}) do t=t+c.get_item_count(item) end return t end ")


def main(n: int, seed: int):
    rnd = random.Random(seed)
    names = []
    for i in range(1, n + 1):
        prod = rnd.choice(list(PRODUCTS))
        kind, feeds, says = PRODUCTS[prod]
        direction = rnd.choice(list(DIRS))
        count = rnd.choice([None, 2, 3, "a couple of"])
        clutter = rnd.random() < 0.5
        what = rnd.choice(says)
        length = rnd.choice([20, 30, 30, 40])
        decoy = rnd.random() < 0.3
        mach = "furnaces" if kind == "furnace" else "assemblers"
        ctext = "" if count is None else (f", {count} {mach}" if isinstance(count, int) else f", {count} {mach}")
        goal = rnd.choice(WORDING).format(what=what, bx="{bx}", by="{by}", count=ctext,
                                          chest=rnd.choice(["", ", into a chest"]))
        made = "made(nil, 'furnace')" if kind == "furnace" else f"made('{prod}')"
        target = {"automation-science-pack": 3, "electronic-circuit": 10, "steel-plate": 3,
                  "firearm-magazine": 5, "stone-brick": 5}.get(prod, 15)
        name = f"f-quick-{i:02d}" if seed <= 3 else f"f-quick-s{seed}-{i:02d}"  # later seeds don't overwrite
        scn = {"name": name, "stage": "stage-s3-steel-oil-ready", "minutes": 12, "agents": 1, "kind": "directive",
               "group": "fuzz",
               "note": f"Variant {i} (seed {seed}): {what} off a belt running {direction}"
                       f"{' (two belts)' if len(feeds) > 1 else ''}{', rocks nearby' if clutter else ''}, "
                       f"{length} tiles{', a stone belt beside it' if decoy else ''}; order: "
                       f"{goal}",
               "setup_lua": setup_lua(direction, feeds, clutter, length, decoy),
               "objectives": [{"name": "made", "minutes": 10, "hold_samples": 1, "goal": goal, "answer": "Your call.",
                               "score": [{"name": "made", "lua": HELPERS + "return " + made, "target": target},
                                         {"name": "in_chest", "lua": HELPERS + f"return inchest('{prod}')",
                                          "target": max(1, target // 3)}]}],
               "score": []}
        (ROOT / "bench" / "scenarios" / f"{name}.json").write_text(json.dumps(scn, indent=1) + "\n")
        names.append(name)
        print(f"{name}: {prod:24} {direction:5} count={count!s:12} clutter={clutter!s:5} len={length} "
              f"decoy={decoy!s:5} {goal[9:90]}")
    suite = "fuzz" if seed <= 3 else f"fuzz-s{seed}"
    (ROOT / "bench" / "suites" / f"{suite}.json").write_text(json.dumps(names, indent=1) + "\n")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 12, int(sys.argv[2]) if len(sys.argv) > 2 else 1)
