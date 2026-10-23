#!/usr/bin/env python3
"""Orders a planner can't do in one plan (b11): the build needs research first, so the plan comes in parts and the
second part can only be designed once the first is done. p11's planner researched electric mining drills, didn't
say more was coming, and the order closed "done" with the drills never placed.

    .venv/bin/python bench/gen_parts_scenarios.py   -> bench/scenarios/b11-research-build.json
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMMON = (ROOT / "bench" / "scenarios" / "lua" / "x-common.lua").read_text()

SETUP = r"""
-- electric mining drills are NOT researched (25 red packs); labs, packs and parts are by spawn, the ore isn't
for _, t in pairs { 'electric-mining-drill' } do f.technologies[t].researched = false end
local sp = f.get_spawn_position(s)
local ore = s.find_entities_filtered { name = 'iron-ore', position = sp, radius = 250, limit = 1 }[1]
if not ore then error('no iron ore near spawn') end
local W, H = 14, 10
local ox, oy = find_near(sp.x + 6, sp.y + 6, W, H, 80)
clear(ox, oy, W, H)
local X, Y = ox + 2, oy + 2
grid(X + 0.5, Y + 6.5, 3000000)
put('lab', X + 3.5, Y + 1.5)
put('lab', X + 7.5, Y + 1.5)
put('small-electric-pole', X + 5.5, Y + 1.5)
put('small-electric-pole', X + 2.5, Y + 4.5)
local c = put('steel-chest', X + 10.5, Y + 4.5)
for n, k in pairs { ['automation-science-pack'] = 40, ['iron-plate'] = 200, ['iron-gear-wheel'] = 60,
  ['electronic-circuit'] = 40, ['iron-chest'] = 6, ['small-electric-pole'] = 60, ['medium-electric-pole'] = 20,
  ['copper-cable'] = 100 } do c.insert { name = n, count = k } end
storage.bench_parts = { ore = ore.position }
return { ox = math.floor(ore.position.x), oy = math.floor(ore.position.y), cx = math.floor(X + 10), cy = math.floor(Y + 4),
  lx = math.floor(X + 3), ly = math.floor(Y + 1) }
"""

DRILLS = ("local o = storage.bench_parts.ore local n = 0 for _, d in pairs(game.surfaces.nauvis.find_entities_filtered "
          "{ name = 'electric-mining-drill', position = o, radius = 40 }) do if d.status == "
          "defines.entity_status.working or d.status == defines.entity_status.waiting_for_space_in_destination then "
          "n = n + 1 end end return n")


def main() -> None:
    scn = {
        "name": "b11-research-build", "stage": "crew-test", "minutes": 35, "agents": 1, "kind": "directive",
        "note": "Electric mining drills aren't researched; labs (powered), red packs and drill parts are by spawn, the "
                "iron ore is ~80 tiles away with no power. The order needs research, then the build: two plans, the "
                "second designed after the first is done. Met = 4 electric drills on that ore working, 2 samples.",
        "setup_lua": COMMON + SETUP,
        "objectives": [{
            "name": "drills-running", "minutes": 32, "hold_samples": 2,
            "goal": "@{agent} put 4 electric mining drills on the iron ore at [gps={ox},{oy}], each dropping into an "
                    "iron chest, and get them running. What you need is in the chest at [gps={cx},{cy}].",
            "answer": "Your call. Everything you need is in or by that chest.",
            "score": [{"name": "electric_drills_working", "target": 4, "lua": DRILLS}]}],
        "score": [],
    }
    out = ROOT / "bench" / "scenarios" / "b11-research-build.json"
    out.write_text(json.dumps(scn, indent=1))
    print(out)


if __name__ == "__main__":
    main()
