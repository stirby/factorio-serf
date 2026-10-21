#!/usr/bin/env python3
"""Encoding lab: what to do after a failed step (decide.recovery). Hand-labelled real cases from bench runs.
    .venv/bin/python lab/eval_recovery.py [variant ...]"""
import asyncio, json, re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from jev import decide  # noqa: E402
from jev.typesafe import Jev, choice  # noqa: E402

DATA = ROOT / "lab" / "data" / "recovery.jsonl"


async def v_current(jev, row):
    opts = {k: decide.RECOVERY[k] for k in row["options"]}
    st = row["state"]
    return await decide.recovery(jev, st["goal"], st["step"], st["error_message"], st["times_tried"], opts)


RECOVERY2 = {
    "retry": {"when": "the problem is temporary: the character itself or something moving was in the way, it timed "
                      "out, it got stuck on the way; trying again can work",
              "not_when": "the message says something doesn't exist or can't be done"},
    "get_items": {"when": "the character lacks an item that can still be fetched or crafted",
                  "not_when": "the message says no chest has it and it can't be hand-crafted"},
    "skip": {"when": "the step is already done or no longer needed: already researched, already built, the thing "
                     "to remove is already gone"},
    "replan": {"when": "the step can't work as written: wrong or blocked position, impossible item, no path, "
                       "too far, a tech that unlocks another way, nothing exists to use"},
}


def facts(msg: str) -> dict:
    m = msg.lower()
    return {"blocked_only_by_the_character": bool(re.search(r"blocked by character@", m)) and
            not re.search(r"blocked by (?!character)[a-z-]+@", m.replace("entity-ghost", "")),
            "timed_out": "timed out" in m or "stuck" in m,
            "already_done": "already" in m,
            "item_exists_nowhere": "no chest or machine output" in m and "can't hand-craft" in m}


async def v_facts(jev, row):
    st = row["state"]
    opts = {k: RECOVERY2[k] for k in row["options"]}
    state = {"goal": st["goal"], "step": st["step"], "error_message": st["error_message"],
             "times_tried": st["times_tried"], "facts_from_code": facts(st["error_message"])}
    a = await jev.ask(state, {"next": choice("The `step` failed with `error_message`. What should the character "
                                             "do next?", opts)}, kind="lab_recovery")
    return a["next"].choice, a["next"].confidence

VARIANTS = {"current": v_current, "facts": v_facts}  # "current" is now the facts encoding (decide.recovery)


async def main():
    rows = [json.loads(l) for l in DATA.read_text().splitlines() if l.strip()]
    jev = Jev(log_path=ROOT / "lab" / "runs" / "recovery.jsonl")
    for name in sys.argv[1:] or list(VARIANTS):
        res = await asyncio.gather(*(VARIANTS[name](jev, r) for r in rows))
        ok = sum(1 for r, (c, _) in zip(rows, res) if c == r["gold"])
        conf_ok = sum(1 for r, (c, p) in zip(rows, res) if p >= 0.7 and c == r["gold"])
        conf_n = sum(1 for _, (c, p) in zip(rows, res) if p >= 0.7)
        print(f"[{name}] {ok}/{len(rows)} (conf>=0.7: {conf_ok}/{conf_n})")
        for r, (c, p) in zip(rows, res):
            if c != r["gold"]:
                print(f"    {c}({p:.2f}) != {r['gold']}: {r['state']['error_message'][:110]}")
    await jev.close()

asyncio.run(main())
