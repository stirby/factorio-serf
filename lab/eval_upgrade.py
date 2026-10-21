#!/usr/bin/env python3
"""Encoding lab: upgrade orders (jev/decide.upgrade): what tier, whole belt line or one spot.
    .venv/bin/python lab/eval_upgrade.py"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from jev import decide  # noqa: E402
from jev.typesafe import Jev  # noqa: E402

# (order, into or None, line?)
CASES = [("@serf swap the belts on the iron line at [gps=1,1] for red ones", "fast-transport-belt", True),
         ("@serf upgrade that belt [gps=1,1] to fast belts, the whole thing", "fast-transport-belt", True),
         ("@serf put assembler 2s in place of the gear assemblers at [gps=4,4]", "assembling-machine-2", False),
         ("@serf replace the stone furnaces at [gps=3,3] with steel ones", "steel-furnace", False),
         ("@serf can you upgrade the inserters at [gps=2,2] to fast inserters", "fast-inserter", False),
         ("@serf swap the wooden chests at [gps=2,2] for steel chests", "steel-chest", False),
         ("@serf build 4 furnaces off this belt [gps=1,1]", None, False),
         ("@serf replace the broken belt at [gps=1,1]", None, False),
         ("@serf the gear assembler at [gps=1,1] stopped", None, False)]


async def main():
    jev = Jev(log_path=ROOT / "lab" / "runs" / "upgrade.jsonl")
    import re

    async def ask(o):  # the actor only asks Jev when the order says upgrade, swap or replace
        if not re.search(r"\b(upgrade|swap|replace|in place of|instead of)", o, re.I):
            return None, 0.0, 0.0
        return await decide.upgrade(jev, o)
    res = await asyncio.gather(*(ask(o) for o, *_ in CASES))
    ok = 0
    for (o, want, line), (t, p, pl) in zip(CASES, res):
        got = t if t and p >= 0.7 else None
        good = got == want and (not want or "belt" not in want or (pl >= 0.6) == line)
        ok += good
        if not good:
            print(f"  MISS got={t}({p:.2f}) line={pl:.2f} want={want}/{line}: {o}")
    print(f"upgrade: {ok}/{len(CASES)}   jev ${jev.stats.as_dict()['cost_usd']}")
    await jev.close()

asyncio.run(main())
