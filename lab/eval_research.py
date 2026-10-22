#!/usr/bin/env python3
"""Encoding lab: which available tech does a research order name (jev/decide.research)?
    .venv/bin/python lab/eval_research.py"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from jev import decide  # noqa: E402
from jev.typesafe import reader  # noqa: E402

# what the s3 stage can research
TECHS = ['automobilism', 'circuit-network', 'concrete', 'electric-energy-distribution-1', 'gate', 'heavy-armor',
         'landfill', 'military-science-pack', 'oil-processing', 'physical-projectile-damage-1', 'radar', 'railway',
         'repair-pack', 'research-speed-1', 'solar-energy', 'steel-axe', 'stronger-explosives-1', 'toolbelt',
         'weapon-shooting-speed-1']
UNLOCKS = {"electric-energy-distribution-1": ["medium-electric-pole", "big-electric-pole", "iron-stick"],
           "solar-energy": ["solar-panel"], "oil-processing": ["pumpjack", "oil-refinery", "chemical-plant"],
           "railway": ["rail", "locomotive", "cargo-wagon"], "concrete": ["concrete", "hazard-concrete"],
           "landfill": ["landfill"], "circuit-network": ["red-wire", "green-wire", "arithmetic-combinator"]}
CASES = [("@serf research oil processing next", "oil-processing"),
         ("@serf can you queue solar", "solar-energy"),
         ("@all let's get trains going, research railway", "railway"),
         ("@serf start the research for medium poles", "electric-energy-distribution-1"),
         ("@serf get us the steel axe tech", "steel-axe"),
         ("@serf research faster mining", None),  # mining productivity isn't available
         ("@serf research whatever helps", None),
         ("@serf research automation 2", None),  # not in the list
         ("@serf what are we researching?", None),
         ("@serf research landfill and concrete", None)]


async def main():
    jev = reader(log_path=ROOT / "lab" / "runs" / "research.jsonl")
    techs = [{"name": t, "unlocks": UNLOCKS.get(t, [])} for t in TECHS]
    res = await asyncio.gather(*(decide.research(jev, o, techs) for o, _ in CASES))
    ok = 0
    for (o, want), (t, p) in zip(CASES, res):
        got = t if t and p >= 0.7 else None
        ok += got == want
        if got != want:
            print(f"  MISS got={t}({p:.2f}) want={want}: {o}")
    print(f"research: {ok}/{len(CASES)}   jev ${jev.stats.as_dict()['cost_usd']}")
    await jev.close()

asyncio.run(main())
