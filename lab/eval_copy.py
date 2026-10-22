#!/usr/bin/env python3
"""Encoding lab: does an order ask for more of the same (jev/quickcopy.read_order)?
    .venv/bin/python lab/eval_copy.py"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from jev import quickcopy  # noqa: E402
from jev.typesafe import Jev  # noqa: E402

CASES = [("@serf nice. Two more just like it: ore belts at [gps=28,8] and [gps=44,8], chests at [gps=32,30] and "
          "[gps=48,30].", True),
         ("@serf perfect, now four more: ore belts at [gps=60,8], [gps=76,8], [gps=92,8] and [gps=108,8], each with its "
          "chest at the bottom.", True),
         ("@serf same again at [gps=5,5]", True),
         ("@serf another one of those over at [gps=40,4] please", True),
         ("@serf make gears off this belt [gps=1,1]", False),
         ("@serf the furnaces at [gps=1,1] stopped", False),
         ("@serf belt the coal from [gps=1,1] to the boiler at [gps=30,1]", False),
         ("@serf build 8 stone furnaces off the ore belt at [gps=4,4]", False),
         # the copy variants' wordings (bench/gen_fuzz_copy.py)
         ("@serf copy that to [gps=141,-30]", True),
         ("@serf same again on the belt at [gps=141,-30]", True),
         ("@serf three more of those: [gps=111,-18], [gps=111,-30], [gps=111,-42]", True),
         ("@serf do the same thing at [gps=1,1], [gps=1,13] and [gps=1,25]", True),
         ("@serf copy the blueprint in the chest at [gps=1,1]", False),
         ("@serf move that chest to [gps=4,4]", False)]


async def main():
    jev = Jev(log_path=ROOT / "lab" / "runs" / "copy.jsonl")
    ps = await asyncio.gather(*(quickcopy.read_order(jev, o) for o, _ in CASES))
    ok = 0
    for (o, want), p in zip(CASES, ps):
        ok += (p >= 0.7) == want
        if (p >= 0.7) != want:
            print(f"  MISS p={p:.2f} want={want}: {o[:100]}")
    print(f"quickcopy: {ok}/{len(CASES)}   jev ${jev.stats.as_dict()['cost_usd']}")
    await jev.close()

asyncio.run(main())
