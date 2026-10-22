#!/usr/bin/env python3
"""Encoding lab: the quick-build order reader (jev/quickbuild.read_order) on hand-labelled orders. A case passes when
accept() matches the label and, for accepted ones, product/count/output match too.
    .venv/bin/python lab/eval_quick.py"""
import asyncio
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from jev import quickbuild  # noqa: E402
from jev.typesafe import Jev  # noqa: E402

CARRY = {}  # options list id -> what the belts carry
IRON = ["firearm-magazine", "iron-chest", "iron-gear-wheel", "iron-stick", "light-armor", "pipe"]
IRON_COAL = IRON + ["steel-plate"]
ORE = ["iron-plate"]
COPPER = ["copper-cable"]
COPPER_ORE = ["copper-plate"]
STONE = ["stone-brick", "stone-furnace"]
IRON_COPPER = IRON + COPPER + ["automation-science-pack", "electronic-circuit"]  # (two-stage: feeders)
MALL = IRON + ["inserter"]
CARRY.update({id(IRON): ["iron-plate"], id(IRON_COAL): ["coal", "iron-plate"], id(ORE): ["coal", "iron-ore"],
              id(COPPER): ["copper-plate"], id(IRON_COPPER): ["copper-plate", "iron-plate"],
              id(MALL): ["electronic-circuit", "iron-gear-wheel", "iron-plate"]})

# (order, options, accept?, product, count, output)
CASES = [
    ("@serf There's an iron plate belt starting at [gps=10,4] and running east, and a power pole at [gps=12,20]. "
     "Make gears from it automatically, into a chest, around [gps=31,17].", IRON, True, "iron-gear-wheel", "not_said",
     "chest"),
    ("@serf The belt at [gps=10,4] carries iron plates and coal (one lane each), running east; power pole at "
     "[gps=12,20]. Make steel from it with 4 stone furnaces, steel into a chest. Fuel them from the belt too, not by "
     "hand.", IRON_COAL, True, "steel-plate", "4", "chest"),
    ("@serf The belt at [gps=10,4] carries iron plates and gears (one lane each), and the one at [gps=10,10] carries "
     "circuits; both run east. Power pole at [gps=12,20]. Set up an assembler making inserters into a chest, fed from "
     "these belts.", MALL, True, "inserter", "1", "chest"),
    ("@serf make gears off this belt [gps=3,3]", IRON, True, "iron-gear-wheel", "not_said", "chest"),
    # variants (bench/gen_fuzz.py seed 3): plates said as the metal alone
    ("@serf I need copper made from this belt [gps=112,-47], a couple of furnaces, into chests", COPPER_ORE, True,
     "copper-plate", "2", "chest"),
    ("@serf iron plates please, off that belt [gps=1,1], a couple of furnaces", ORE, True, "iron-plate", "2", "chest"),
    ("@serf set up ammo production off [gps=141,-46]", IRON, True, "firearm-magazine", "not_said", "chest"),
    ("@serf can you automate wire from the belt at [gps=5,5]", COPPER, True, "copper-cable", "not_said", "chest"),
    ("@serf can you automate wire from the belt at [gps=112,-47]?, into a chest", COPPER, True, "copper-cable",
     "not_said", "chest"),
    ("@serf yellow ammo please, off that belt [gps=5,5]", IRON, True, "firearm-magazine", "not_said", "chest"),
    ("@serf copper please, off that belt [gps=5,5]", COPPER_ORE, True, "copper-plate", "not_said", "chest"),
    ("@serf plates please, off that belt [gps=97,-32]", ORE, True, "iron-plate", "not_said", "chest"),
    ("@serf bricks please, off that belt [gps=112,-47], 3 furnaces", STONE, True, "stone-brick", "3", "chest"),
    ("@serf build 6 furnaces off the ore belt at [gps=5,5], plates into chests", ORE, True, "iron-plate", "6", "chest"),
    ("@serf make me a smelter column: 8 stone furnaces off the ore belt at [gps=12,8] (iron ore and coal on it), "
     "plates on a belt into the chest at [gps=16,30]. Materials are in the supply chest at [gps=0,8], grid pole at "
     "[gps=-7,14].", ORE, False, None, None, None),  # (sent on: the compose path takes it, not accept())
    ("@serf set up 3 assemblers making iron chests from the plate belt at [gps=1,1]", IRON, True, "iron-chest", "3",
     "chest"),
    ("@serf copper cable please, off the copper belt at [gps=2,2], put it on a belt", COPPER, True, "copper-cable",
     "not_said", "belt"),
    ("@serf we need ammo. 2 assemblers on the iron line at [gps=0,0] making yellow magazines", IRON, True,
     "firearm-magazine", "2", "chest"),
    ("@serf pipes off the iron belt at [gps=9,9] please, one machine is plenty", IRON, True, "pipe", "1", "chest"),
    ("@serf I need pipes made from this belt [gps=97,-32], 3 assemblers, into chests", IRON, True, "pipe", "3",
     "chest"),
    ("@serf I need plates made from this belt [gps=5,5], a couple of furnaces, into chests", ORE, True, "iron-plate", "2",
     "chest"),
    ("@serf pipes off the iron belt at [gps=-55,84] please, a couple of machines", IRON, True, "pipe", "2", "chest"),
    ("@serf could you smelt the ore on that belt [gps=85,-56]? 4 furnaces, plates into chests", ORE, True,
     "iron-plate", "4", "chest"),
    # not quick builds
    ("@serf Two belts start here: iron plates at [gps=10,4] and copper plates at [gps=10,10], both running east, and "
     "there's a power pole at [gps=12,20]. Automate red science off them: at least 3 assemblers, packs onto a belt or "
     "into a chest.", IRON_COPPER, True, "automation-science-pack", "3", "chest"),
    ("@serf Iron plates come along the belt at [gps=10,4] and copper plates along [gps=10,10], both running east; "
     "power pole at [gps=12,20]. Automate green circuits off them. 3 cable assemblers to 2 circuit assemblers is the "
     "usual ratio.", IRON_COPPER, True, "electronic-circuit", "2", "chest"),
    ("@serf build 8 stone furnaces off the ore belt at [gps=4,4] (it carries iron ore and coal), and send the plates "
     "on a belt to the chest at [gps=40,4].", ORE, False, None, None, None),
    ("@serf belt the gears from [gps=1,1] to the chest at [gps=30,1]", IRON, False, None, None, None),
    ("@serf make gears and pipes off this belt [gps=2,2]", IRON, False, None, None, None),
    ("@serf build a red science line: gears from the iron belt at [gps=2,2] into the science assemblers", IRON, False,
     None, None, None),
    ("@serf make steel at [gps=3,3] and send it to the mall chest at [gps=50,50]", IRON_COAL, False, None, None, None),
    ("@serf put drills on the iron patch at [gps=6,6] onto this belt", IRON, False, None, None, None),
    ("@serf I need copper plates in the chest at [gps=-11,82]. They come out on the belt at [gps=-45,82]; get them "
     "across, and don't break the main bus in between.", COPPER, False, None, None, None),
    ("@serf belt the iron plates from [gps=1,1] over to the mall at [gps=40,1]", IRON, False, None, None, None),
    ("@serf automate red science off these belts [gps=1,1] [gps=1,7]", IRON_COPPER, True, "automation-science-pack",
     "not_said", "chest"),
    ("@serf green circuits from the plate belts at [gps=4,4], 2 assemblers", IRON_COPPER, True, "electronic-circuit",
     "2", "chest"),
    ("@serf set up gear production feeding a row of red science assemblers off [gps=0,0]", IRON, False, None, None,
     None),
    ("@serf the boiler at [gps=1,2] needs more power, add steam engines", IRON, False, None, None, None),
]


HOLDOUT = [
    ("@serf throw down a couple of gear assemblers on the iron belt at [gps=7,7]", IRON, True, "iron-gear-wheel", "2",
     "chest"),
    ("@serf could you smelt the ore on that belt [gps=3,9]? 5 furnaces", ORE, True, "iron-plate", "5", "chest"),
    ("@serf iron sticks from the plate belt at [gps=1,1], into a chest", IRON, True, "iron-stick", "not_said", "chest"),
    ("@serf one assembler making firearm magazines off [gps=2,2] please", IRON, True, "firearm-magazine", "1", "chest"),
    ("@serf 3 furnaces making steel on the belt at [gps=5,5] (plates + coal)", IRON_COAL, True, "steel-plate", "3",
     "chest"),
    ("@serf make cables off the copper belt at [gps=4,4] and run them to the circuit build at [gps=40,4]", COPPER,
     False, None, None, None),
    ("@serf build gears at [gps=1,1] and belt them over to the science at [gps=30,30]", IRON, False, None, None, None),
    ("@serf red science please, plates are on the belts at [gps=1,1]", IRON_COPPER, True, "automation-science-pack",
     "not_said", "chest"),
    ("@serf what can you make from this belt [gps=1,1]?", IRON, False, None, None, None),
    ("@serf the gear machine at [gps=1,1] stopped, look at it", IRON, False, None, None, None),
    ("@serf make iron chests and pipes off the belt at [gps=2,2]", IRON, False, None, None, None),
]
if "--holdout" in sys.argv:
    CASES = HOLDOUT


def far_points(order: str) -> bool:
    import re
    pts = [(float(a), float(b)) for a, b in re.findall(r"gps=(-?[0-9.]+),(-?[0-9.]+)", order)]
    return any(((q[0] - pts[0][0]) ** 2 + (q[1] - pts[0][1]) ** 2) ** 0.5 > 40 for q in pts) if pts else False


async def main():
    jev = Jev(log_path=ROOT / "lab" / "runs" / "quick.jsonl")
    res = await asyncio.gather(*(quickbuild.read_order(jev, o, opts, CARRY.get(id(opts))) for o, opts, *_ in CASES))
    ok = 0
    for (o, opts, acc, prod, cnt, out), r in zip(CASES, res):
        a = quickbuild.accept(r, far_points(o), one_point=len(re.findall(r"\[gps=", o)) == 1)
        good = a == acc and (not acc or (r["product"] == prod and r["count"] == cnt and r["output"] == out))
        ok += good
        if not good:
            print(f"  MISS accept={a} (want {acc}) build={r['build']:.2f} chain={r['chain']:.2f} "
                  f"elsewhere={r['elsewhere']:.2f} belt={r['onto_belt']:.2f} product={r['product']}"
                  f"({r['product_p']:.2f}) count={r['count']}({r['count_p']:.2f})\n       {o[:120]}")
    print(f"quickbuild: {ok}/{len(CASES)}   jev ${jev.stats.as_dict()['cost_usd']}")
    # which question decides each case (for tuning): the gate with one question left out at a time
    for drop in ("build", "chain", "elsewhere"):
        neutral = {"build": 1.0, "chain": 0.0, "elsewhere": 0.0}[drop]
        n = sum(1 for (o, opts, acc, prod, cnt, out), r in zip(CASES, res)
                if quickbuild.accept({**r, drop: neutral}, far_points(o), one_point=len(re.findall(r"\[gps=", o)) == 1) == acc
                and (not acc or (r["product"] == prod and r["count"] == cnt and r["output"] == out)))
        print(f"  without {drop}: {n}/{len(CASES)}")
        for (o, opts, acc, *_), r in zip(CASES, res):
            if not acc and quickbuild.accept({**r, drop: neutral}, far_points(o), one_point=len(re.findall(r"\[gps=", o)) == 1):
                print(f"      would accept: {o[:90]}")
    await jev.close()

asyncio.run(main())
