#!/usr/bin/env python3
"""Reader comparison on a held-out set of hard player messages (lab/data/hard_orders.json, written blind to the
questions, examples and code checks by a separate agent). Each message goes through the same reading functions the
actor uses; scored twice: "guarded" (with code's checks, what the actor does) and "raw" (the reader's own pick).

    .venv/bin/python lab/eval_hard.py                 # Jev
    JEV_READER=sonnet .venv/bin/python lab/eval_hard.py
Writes lab/runs/hard-<reader>.json with every item's result."""
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from jev import decide, quickbelt, quickbuild, quickcopy, quickmine  # noqa: E402
from jev.typesafe import JevError, reader  # noqa: E402

IRON = ["firearm-magazine", "iron-chest", "iron-gear-wheel", "iron-stick", "light-armor", "pipe"]
SCENES = {  # options, what the belts carry
    "IRON": (IRON, ["iron-plate"]),
    "IRON_COAL": (IRON + ["steel-plate"], ["coal", "iron-plate"]),
    "ORE": (["iron-plate"], ["coal", "iron-ore"]),
    "COPPER": (["copper-cable"], ["copper-plate"]),
    "COPPER_ORE": (["copper-plate"], ["coal", "copper-ore"]),
    "STONE": (["stone-brick", "stone-furnace"], ["coal", "stone"]),
    "TWO": (IRON + ["copper-cable", "electronic-circuit", "automation-science-pack"], ["copper-plate", "iron-plate"]),
}
ORES = ["iron-ore", "copper-ore", "coal", "stone"]


def pts(text):
    return [(float(a), float(b)) for a, b in re.findall(r"gps=(-?[0-9.]+),(-?[0-9.]+)", text)]


async def one_quick(jev, it):
    """As the actor does: chat triage first (a new job for me?), then the quick-build reading."""
    opts, carried = SCENES[it["scene"]]
    c = await decide.chat(jev, "serf", "otterplex", "@serf " + it["order"], None, None)
    if c.kind != "new_job":
        return {"guarded": not it["accept"], "raw": not it["accept"], "conf_wrong": False,
                "got": {"triage": c.kind, "kind_conf": round(c.kind_conf, 2)}}
    r = await quickbuild.read_order(jev, it["order"], opts, carried)
    p = pts(it["order"])
    far = any(((q[0] - p[0][0]) ** 2 + (q[1] - p[0][1]) ** 2) ** 0.5 > 40 for q in p) if p else False
    belt_to = bool(quickbuild.OUTPUT_BELT.search(it["order"])) and len(p) > 1
    acc = quickbuild.accept(r, far, one_point=len(p) == 1, belt_to_place=belt_to)
    raw = {**r, "product": r["product_raw"], "product_p": r["product_p_raw"]}
    acc_raw = quickbuild.accept(raw, far, one_point=len(p) == 1)

    def ok(a, rr, cnt):
        if a != it["accept"]:
            return False
        return not a or (rr["product"] == it["product"] and cnt == it["count"] and rr["output"] == it["output"])
    cnt = r["count"] if r["count_p"] >= 0.5 else "not_said"
    return {"guarded": ok(acc, r, cnt), "raw": ok(acc_raw, raw, r["count_raw"]),
            "conf_wrong": acc != it["accept"] and acc and r["product_p"] >= 0.8,
            "got": {"accept": acc, "build": round(r["build"], 2), "product": r["product"], "p": round(r["product_p"], 2), "count": cnt,
                    "output": r["output"], "raw_product": r["product_raw"], "raw_p": round(r["product_p_raw"], 2)}}


async def one_noul(p, gold, th=0.7):
    return {"guarded": (p >= th) == gold, "raw": (p >= th) == gold, "conf_wrong": (p >= 0.85 and not gold) or
            (p <= 0.15 and gold), "brier": (p - (1.0 if gold else 0.0)) ** 2, "got": round(p, 2)}


async def one(jev, kind, it):
    t0 = time.time()
    try:
        if kind == "quick":
            r = await one_quick(jev, it)
        elif kind == "belt":
            r = await one_noul(await quickbelt.read_order(jev, it["order"]), it["move"])
        elif kind == "copy":
            r = await one_noul(await quickcopy.read_order(jev, it["order"]), it["copy"])
        elif kind == "mine":
            p, ore, op = await quickmine.read_order(jev, it["order"], ORES)
            take = p >= 0.7 and ore is not None and op >= 0.6
            good = take == it["mine"] and (not take or ore == it["ore"])
            r = {"guarded": good, "raw": good, "conf_wrong": (p >= 0.85) != it["mine"] and p >= 0.85,
                 "brier": (p - (1.0 if it["mine"] else 0.0)) ** 2, "got": {"p": round(p, 2), "ore": ore}}
        else:  # chat
            msg = it["message"]
            c = await decide.chat(jev, "serf", "otterplex", msg, None, None)
            explicit = bool(re.match(r"^\W*@serf\b", msg, re.I))
            addressed = explicit or c.addressed >= 0.5
            kind_ok = (not it["addressed"]) or c.kind == it["kind"]
            r = {"guarded": addressed == it["addressed"] and kind_ok,
                 "raw": (c.addressed >= 0.5) == it["addressed"] and kind_ok,
                 "conf_wrong": (not kind_ok and c.kind_conf >= 0.8) or ((c.addressed >= 0.85) != it["addressed"]
                                                                        and c.addressed >= 0.85),
                 "brier": (c.addressed - (1.0 if it["addressed"] else 0.0)) ** 2,
                 "got": {"addressed": round(c.addressed, 2), "kind": c.kind, "kind_conf": round(c.kind_conf, 2)}}
    except JevError as e:
        r = {"guarded": False, "raw": False, "conf_wrong": False, "error": str(e)[:200]}
    r["secs"] = round(time.time() - t0, 2)
    r["item"] = it
    return r


async def main():
    data = json.loads((ROOT / "lab" / "data" / "hard_orders.json").read_text())
    name = os.environ.get("JEV_READER", "jev")
    jev = reader(log_path=ROOT / "lab" / "runs" / f"hard-{name}.jsonl")
    out, lines = {}, []
    for kind in ("quick", "belt", "mine", "copy", "chat"):
        res = await asyncio.gather(*(one(jev, kind, it) for it in data.get(kind) or []))
        out[kind] = res
        n = len(res)
        if not n:
            continue
        g = sum(r["guarded"] for r in res)
        rw = sum(r["raw"] for r in res)
        cw = sum(bool(r.get("conf_wrong")) for r in res)
        br = [r["brier"] for r in res if "brier" in r]
        lines.append(f"{kind:6} guarded {g}/{n}  raw {rw}/{n}  confident-wrong {cw}"
                     + (f"  brier {sum(br) / len(br):.3f}" if br else "")
                     + f"  secs/msg {sum(r['secs'] for r in res) / n:.1f}")
    st = jev.stats.as_dict()
    lines.append(f"total: {st['calls']} calls, ${st['cost_usd']:.3f}, mean {st['ms_mean']} ms, errors {st['errors']}")
    print(f"reader: {name}")
    print("\n".join(lines))
    (ROOT / "lab" / "runs" / f"hard-{name}.json").write_text(json.dumps({"summary": lines, "results": out}, indent=1,
                                                                         default=str))
    await jev.close()

asyncio.run(main())
