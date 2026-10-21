#!/usr/bin/env python3
"""Encoding lab: is an order "belt items from one named place to another" (jev/quickbelt.read_order)?
    .venv/bin/python lab/eval_belt.py"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from jev import quickbelt  # noqa: E402
from jev.typesafe import Jev  # noqa: E402

CASES = [
    ("@serf the boiler at [gps=-8,64] keeps running out of coal. Belt coal to it from the drills at [gps=-40,64] so "
     "it stays fed.", True),
    ("@serf the drills at [gps=70,-45] are backing up. Belt their ore to the furnaces at [gps=110,-38] (their input "
     "belt is already there).", True),
    ("@serf I need copper plates in the chest at [gps=-11,82]. They come out on the belt at [gps=-45,82]; get them "
     "across, and don't break the main bus in between.", True),
    ("@serf run the gears from [gps=1,1] over to the science at [gps=40,1]", True),
    ("@serf can you belt the stone from [gps=0,0] to the furnaces at [gps=30,0]", True),
    ("@serf hook the coal belt at [gps=5,5] up to the boilers at [gps=40,9]", True),
    ("@serf build 8 furnaces off the ore belt at [gps=4,4] and send the plates on a belt to the chest at [gps=40,4]",
     False),
    ("@serf I need 20 inserters in the chest at [gps=5,5]", False),
    ("@serf power the assemblers at [gps=3,3] from the pole at [gps=40,3]", False),
    ("@serf the furnaces at [gps=1,1] ran out of coal, there's coal in the chest at [gps=20,20]", False),
    ("@serf set up an iron mine on the patch at [gps=119,5] and belt the ore back to the belt end at [gps=-136,-3]",
     False),
    ("@serf bring 50 plates from the chest at [gps=1,1] to the one at [gps=30,1]", False),
    ("@serf make gears off the belt at [gps=1,1], into a chest at [gps=10,5]", False),
]


async def main():
    jev = Jev(log_path=ROOT / "lab" / "runs" / "belt.jsonl")
    ps = await asyncio.gather(*(quickbelt.read_order(jev, o) for o, _ in CASES))
    ok = 0
    for (o, want), p in zip(CASES, ps):
        good = (p >= 0.7) == want
        ok += good
        if not good:
            print(f"  MISS p={p:.2f} want={want}: {o[:110]}")
    print(f"quickbelt: {ok}/{len(CASES)}   jev ${jev.stats.as_dict()['cost_usd']}")
    await jev.close()

asyncio.run(main())
