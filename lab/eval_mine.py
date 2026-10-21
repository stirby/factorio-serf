#!/usr/bin/env python3
"""Encoding lab: is it a mining order, and which ore (jev/quickmine.read_order)?
    .venv/bin/python lab/eval_mine.py"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from jev import quickmine  # noqa: E402
from jev.typesafe import Jev  # noqa: E402

CASES = [("@serf set up an iron mine on the patch at [gps=119,5] and belt the ore back to the belt end at "
          "[gps=-136,-3], it feeds that chest. I want at least 60 ore a minute.", ["iron-ore"], "iron-ore"),
         ("@serf put drills on that copper patch [gps=4,4] and belt it to the furnaces at [gps=40,4]",
          ["copper-ore", "stone"], "copper-ore"),
         ("@serf mine the coal here [gps=1,1] onto a belt", ["coal"], "coal"),
         ("@serf we need stone, set up some drills at [gps=2,2]", ["stone", "iron-ore"], "stone"),
         ("@serf the drills at [gps=70,-45] are backing up. Belt their ore to the furnaces at [gps=110,-38]",
          ["iron-ore"], None),
         ("@serf build 8 stone furnaces off the ore belt at [gps=4,4]", ["iron-ore"], None),
         ("@serf the drills at [gps=3,3] stopped, get them going", ["iron-ore"], None),
         ("@serf grab me 50 iron ore", ["iron-ore"], None)]


async def main():
    jev = Jev(log_path=ROOT / "lab" / "runs" / "mine.jsonl")
    rs = await asyncio.gather(*(quickmine.read_order(jev, o, ores) for o, ores, _ in CASES))
    ok = 0
    for (o, ores, want), (p, ore, op) in zip(CASES, rs):
        got = ore if p >= 0.7 and ore and op >= 0.6 else None
        ok += got == want
        if got != want:
            print(f"  MISS p={p:.2f} ore={ore}({op:.2f}) want={want}: {o[:90]}")
    print(f"quickmine: {ok}/{len(CASES)}   jev ${jev.stats.as_dict()['cost_usd']}")
    await jev.close()

asyncio.run(main())
