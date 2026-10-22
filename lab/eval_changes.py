#!/usr/bin/env python3
"""Encoding lab: does a mid-job chat line change the plan? (decide.changes_plan) on hand-labelled cases."""
import asyncio, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from jev import decide  # noqa: E402
from jev.typesafe import reader  # noqa: E402

JOB = "build a gear assembler off the iron belt with the gears going into a chest"
CASES = [
    ("put the chest on the east side instead", 1), ("actually make it two assemblers", 1),
    ("use the copper belt not the iron one", 1), ("wait, build it further north, that spot is for the bus", 1),
    ("use iron chests not wooden ones", 1), ("make circuits instead of gears", 1),
    ("move it closer to the main bus", 1), ("don't use that belt, it's for the smelters", 1),
    ("nice, looking good", 0), ("how long will it take?", 0), ("keep going", 0), ("not done yet, keep at it", 0),
    ("thanks", 0), ("you're doing great", 0), ("are you almost done?", 0), ("lol that inserter", 0),
    ("brb getting food", 0), ("the power there is a bit low btw, the grid is maxed", 0),
    ("make sure it's powered", 0), ("ok", 0),
]


async def main():
    jev = reader(log_path=ROOT / "lab" / "runs" / "changes.jsonl")
    ps = await asyncio.gather(*(decide.changes_plan(jev, JOB, m) for m, _ in CASES))
    ok = 0
    for (m, g), p in zip(CASES, ps):
        hit = (p >= 0.6) == bool(g)
        ok += hit
        if not hit:
            print(f"  MISS p={p:.2f} gold={g}: {m}")
    print(f"changes_plan: {ok}/{len(CASES)}  jev {jev.stats.as_dict()['cost_usd']}")
    await jev.close()

asyncio.run(main())
