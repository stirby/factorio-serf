#!/usr/bin/env python3
"""Encoding lab: the smaller decisions, each on a handful of hand-labelled cases.
    .venv/bin/python lab/eval_small.py"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from jev import decide  # noqa: E402
from jev.typesafe import Jev  # noqa: E402

QUESTIONS = [("what are you working on?", "status"), ("where are u", "where"), ("how's it going with the gears?", "status"),
             ("what have you got on you", "carrying"), ("are you done yet", "status"), ("do you have any belts?", "carrying"),
             ("how much copper do we make per minute?", "other"), ("why did the labs stop?", "other"),
             ("can you read my pings", "other"), ("where's the nearest coal patch?", "other")]
SCOPE = [("@serf red science stopped at [gps=1,2]. Can you get it going again?", 0),
         ("@serf a bunch of my little furnace setups out around [gps=0,0] stopped, they're spread out about 150 tiles each way. Get them all running again.", 1),
         ("@serf the smelters at [gps=4,4] ran out of coal", 0),
         ("@serf all the outposts north of base are dead, can you check them all", 1),
         ("@serf power keeps dipping at [gps=5,5]", 0),
         ("@serf every mining site around here stopped, go fix them", 1)]
NOT_DONE = [("not done yet: chests full is 3, needs 8. Keep going on it.", 1),
            ("Every input's belt reaches an output chest, so the inserters are on.", 0),
            ("Level solved: every output chest holds 21 of its item.", 0),
            ("not done yet: it has to hold for a few minutes. Keep at it.", 1),
            ("it stopped again, the chest is full", 1), ("nice job", 0), ("thanks, that one's done.", 0),
            ("hmm the gears aren't coming out", 1)]
FIX_ALL = [("@serf science is really slow at the little lab setup at [gps=57,9]. Can you look at it and get it running "
            "properly?", 1),
           ("@serf my furnace setups around here stopped, get them all running again", 1),
           ("@serf something's off with the mall at [gps=3,3], sort it out", 1),
           ("@serf the boiler at [gps=1,2] keeps running out of coal", 0),
           ("@serf the gear assemblers at [gps=4,4] have no power. Hook them up to the grid", 0),
           ("@serf that belt at [gps=2,2] is facing the wrong way", 0)]
MULTI = [("@serf make gears off this belt [gps=1,1] and research solar", 1),
         ("@serf plates please, off that belt [gps=127,-32], a couple of furnaces", 0),
         ("@serf magazines please, off that belt [gps=1,1], a couple of assemblers", 0),
         ("@serf fix the boiler at [gps=1,1], then belt coal to it from the drills at [gps=30,1]", 1),
         ("@serf research oil processing and swap the belts at [gps=4,4] for red ones", 1),
         ("@serf build 8 stone furnaces off the ore belt at [gps=4,4], and send the plates on a belt to the chest at "
          "[gps=40,4]", 0),
         ("@serf automate red science off these belts [gps=1,1]", 0),
         ("@serf two more just like it at [gps=28,8] and [gps=44,8]", 0),
         ("@serf the drills at [gps=70,-45] are backing up. Belt their ore to the furnaces at [gps=110,-38]", 0)]
KITS = [("automate gears off this iron belt", "assembly"), ("build 8 stone furnaces off the ore belt", "smelting"),
        ("we need more power, the grid is maxed", "power"), ("set up drills on the iron patch north of base", "mining"),
        ("belt the copper over to the bus", "belts"), ("what are you doing?", "none"),
        ("research steel next", "none"), ("automate red science", "assembly")]


async def main():
    jev = Jev(log_path=ROOT / "lab" / "runs" / "small.jsonl")
    q = await asyncio.gather(*(decide.question_type(jev, m) for m, _ in QUESTIONS))
    ok = sum(1 for (m, g), (c, _) in zip(QUESTIONS, q) if c == g)
    print(f"question_type: {ok}/{len(QUESTIONS)}")
    for (m, g), (c, p) in zip(QUESTIONS, q):
        if c != g:
            print(f"    {c}({p:.2f}) != {g}: {m}")
    sc = await asyncio.gather(*(decide.scope(jev, m) for m, _ in SCOPE))
    ok = sum(1 for (m, g), p in zip(SCOPE, sc) if (p >= 0.6) == bool(g))
    print(f"scope: {ok}/{len(SCOPE)}")
    for (m, g), p in zip(SCOPE, sc):
        if (p >= 0.6) != bool(g):
            print(f"    p={p:.2f} gold={g}: {m[:80]}")
    nd = await asyncio.gather(*(decide.not_done(jev, "automate gears into a chest", m) for m, _ in NOT_DONE))
    ok = sum(1 for (m, g), p in zip(NOT_DONE, nd) if (p >= 0.6) == bool(g))
    print(f"not_done: {ok}/{len(NOT_DONE)}")
    for (m, g), p in zip(NOT_DONE, nd):
        if (p >= 0.6) != bool(g):
            print(f"    p={p:.2f} gold={g}: {m}")
    probs = ["a belt at 52.5,3.5 faces west, against the belts around it", "assembling-machine-1 A4 has no power",
             "wooden-chest C1 is full (800 stone)"]
    fa = await asyncio.gather(*(decide.fault(jev, m, [{"text": t} for t in probs]) for m, _ in FIX_ALL))
    ok = sum(1 for (m, g), r in zip(FIX_ALL, fa) if (r[3] >= 0.7) == bool(g))
    print(f"fix_all: {ok}/{len(FIX_ALL)}")
    for (m, g), r in zip(FIX_ALL, fa):
        if (r[3] >= 0.7) != bool(g):
            print(f"    p={r[3]:.2f} gold={g}: {m[:80]}")
    mc = await asyncio.gather(*(decide.chat(jev, "serf", "ops", m, None, None) for m, _ in MULTI))
    ok = sum(1 for (m, g), c in zip(MULTI, mc) if (c.multi >= 0.75) == bool(g))
    print(f"multi: {ok}/{len(MULTI)}")
    for (m, g), c in zip(MULTI, mc):
        if (c.multi >= 0.75) != bool(g):
            print(f"    p={c.multi:.2f} gold={g}: {m[:80]}")
    k = await asyncio.gather(*(decide.kit(jev, m) for m, _ in KITS))
    ok = sum(1 for (m, g), (c, _) in zip(KITS, k) if c == g)
    print(f"kit: {ok}/{len(KITS)}")
    for (m, g), (c, p) in zip(KITS, k):
        if c != g:
            print(f"    {c}({p:.2f}) != {g}: {m}")
    print(f"jev ${jev.stats.as_dict()['cost_usd']}")
    await jev.close()

asyncio.run(main())
