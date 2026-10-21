#!/usr/bin/env python3
"""Encoding lab: chat triage. Runs each encoding variant over lab/data/chat.jsonl (hand-labelled lines, most of
them real chat from live games) and reports accuracy, accuracy when confident, and coverage.

    .venv/bin/python lab/eval_chat.py [variant ...]      # default: all variants

A variant is a function (jev, row) -> {"addressed": p, "kind": (choice, conf), "playbook": (choice, conf)}.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from jev import decide  # noqa: E402
from jev.typesafe import Jev, choice, noul  # noqa: E402

import os
DATA = ROOT / "lab" / "data" / os.environ.get("CHAT_SET", "chat.jsonl")


def explicit(msg: str, me: str = "serf") -> bool:
    m = msg.lower()
    return f"@{me}" in m or "@all" in m


async def v_current(jev, row):
    c = await decide.chat(jev, "serf", row["speaker"], row["message"], row.get("doing"), None)
    return {"addressed": c.addressed, "kind": (c.kind, c.kind_conf), "playbook": (c.playbook, c.playbook_conf)}


async def v_split(jev, row):
    """Kind and playbook as separate narrow questions with structured criteria; addressing by code first."""
    state = {"me": "serf", "speaker": row["speaker"], "message": row["message"],
             "what_i_am_doing": row.get("doing") or "nothing"}
    kinds = {
        "new_job": {"means": "asks for new work in the game", "examples": ["automate gears here", "build 8 furnaces",
                    "the boiler is out of coal, fix it", "follow me", "bring me 50 plates"]},
        "more_info": {"means": "about the work in `what_i_am_doing`: a correction, a hint, a constraint, pointing out a "
                      "problem with it, or a push to keep going", "examples": ["put it on the other side",
                      "you see the problem there?", "not done yet, keep going", "use the logistic network for that"]},
        "question": {"means": "wants an answer in words, not work", "examples": ["what are you doing?",
                     "can you read my pings?", "how much copper do we make?"]},
        "stop": {"means": "stop, cancel, drop it, stop following", "examples": ["stop", "leave that one for now"]},
        "approval": {"means": "a yes or 'your call' answer to something the character asked",
                     "examples": ["yes do it", "your call", "sounds good"]},
        "chatter": {"means": "thanks, praise, greetings, small talk", "examples": ["thanks!", "gg", "how u doin",
                    "nice work"]},
    }
    qs = {
        "addressed": noul("Is `message` meant for `me`: it names serf, says @all or everyone, or talks to whoever is "
                          "listening, rather than to another named player or bot?"),
        "kind": choice("What does `message` do?", kinds),
        "playbook": choice("If `message` asks for new work, which kind of work?", decide.PLAYBOOKS),
    }
    a = await jev.ask(state, qs, kind="lab_chat")
    return {"addressed": a["addressed"].p, "kind": (a["kind"].choice, a["kind"].confidence),
            "playbook": (a["playbook"].choice, a["playbook"].confidence)}


PLAYBOOKS2 = {
    "fix": {"what": "something that used to work has stopped, is slow, starving, out of fuel, without power, backed "
                    "up or broken, and the player only says WHAT is wrong, leaving how to fix it to the character",
            "not_for": "orders that say what to build or connect (belt X to Y, hook up power, build, automate), even "
                       "when they mention a problem",
            "examples": ["red science stopped at [gps]. can you get it going?", "the smelters ran out of coal",
                         "power keeps dipping, sort it out"]},
    "deliver": {"what": "bring a stated number of specific items to a chest or to the player",
                "not_for": "automating production of those items",
                "examples": ["I need 20 inserters in the chest at [gps]", "bring me 50 iron plates"]},
    "plan": {"what": "anything else: build or automate something new, belt or power something from A to B, set up "
                     "mining, expand, design a layout, follow someone, a puzzle",
             "examples": ["belt coal to the boiler from the drills", "automate gears here", "hook these up to the grid",
                          "follow me"]},
}


async def v_split2(jev, row):
    state = {"me": "serf", "speaker": row["speaker"], "message": row["message"],
             "what_i_am_doing": row.get("doing") or "nothing"}
    a = await jev.ask(state, {
        "addressed": noul("Is `message` meant for `me`: it names serf, says @all or everyone, or talks to whoever is "
                          "listening, rather than to another named player or bot?"),
        "kind": choice("What does `message` do?", KINDS2),
        "playbook": choice("If `message` asks for new work, which kind of work?", PLAYBOOKS2)}, kind="lab_chat")
    return {"addressed": a["addressed"].p, "kind": (a["kind"].choice, a["kind"].confidence),
            "playbook": (a["playbook"].choice, a["playbook"].confidence)}


KINDS2 = {
    "new_job": {"means": "asks for new work in the game", "examples": ["automate gears here", "build 8 furnaces",
                "the boiler is out of coal, fix it", "follow me", "bring me 50 plates"]},
    "more_info": {"means": "about the work in `what_i_am_doing`: a correction, a hint, a constraint, pointing out a "
                  "problem with it, or a push to keep going", "examples": ["put it on the other side",
                  "you see the problem there?", "not done yet, keep going", "use the logistic network for that"]},
    "question": {"means": "wants an answer in words, not work", "examples": ["what are you doing?",
                 "can you read my pings?", "how much copper do we make?"]},
    "stop": {"means": "stop, cancel, drop it, stop following", "examples": ["stop", "leave that one for now"]},
    "approval": {"means": "go-ahead or 'your call' (possibly with a hint) answering something the character asked",
                 "examples": ["yes do it", "your call", "your call on the layout, one is enough", "sounds good"]},
    "chatter": {"means": "thanks, praise, greetings, small talk, the speaker thinking out loud",
                "examples": ["thanks!", "gg", "how u doin", "nice work", "nvm I see it now"]},
}

VARIANTS = {"current": v_current, "split": v_split, "split2": v_split2}


async def run_variant(name, fn, rows, jev):
    res = await asyncio.gather(*(fn(jev, r) for r in rows))
    n_addr = n_addr_ok = n_addr_code = 0
    kind_tot = kind_ok = kind_conf_n = kind_conf_ok = 0
    pb_tot = pb_ok = 0
    misses = []
    for r, out in zip(rows, res):
        g = r["gold"]
        n_addr += 1
        pa = out["addressed"] >= 0.5
        n_addr_ok += pa == bool(g["addressed"])
        code = explicit(r["message"]) or pa
        n_addr_code += code == bool(g["addressed"])
        if g["addressed"] and g["kind"]:
            k, kc = out["kind"]
            kind_tot += 1
            kind_ok += k == g["kind"]
            if kc >= 0.7:
                kind_conf_n += 1
                kind_conf_ok += k == g["kind"]
            if k != g["kind"]:
                misses.append(f"kind {k}({kc:.2f}) != {g['kind']}: {r['message'][:90]}")
        if g.get("playbook"):
            p, pc = out["playbook"]
            pb_tot += 1
            pb_ok += p == g["playbook"]
            if p != g["playbook"]:
                misses.append(f"playbook {p}({pc:.2f}) != {g['playbook']}: {r['message'][:90]}")
        if (out["addressed"] >= 0.5) != bool(g["addressed"]):
            misses.append(f"addressed {out['addressed']:.2f} != {g['addressed']}: {r['message'][:90]}")
    print(f"[{name}] addressed {n_addr_ok}/{n_addr} (with @-rule {n_addr_code}/{n_addr}) | kind {kind_ok}/{kind_tot} "
          f"(conf>=0.7: {kind_conf_ok}/{kind_conf_n}) | playbook {pb_ok}/{pb_tot}")
    for m in misses:
        print("   ", m)
    return {"variant": name, "addressed": n_addr_ok / n_addr, "kind": kind_ok / max(1, kind_tot),
            "playbook": pb_ok / max(1, pb_tot), "kind_conf_cov": kind_conf_n / max(1, kind_tot)}


async def main():
    rows = [json.loads(l) for l in DATA.read_text().splitlines() if l.strip()]
    names = sys.argv[1:] or list(VARIANTS)
    jev = Jev(log_path=ROOT / "lab" / "runs" / "chat.jsonl")
    out = []
    for n in names:
        out.append(await run_variant(n, VARIANTS[n], rows, jev))
    print(f"jev: {jev.stats.as_dict()}")
    await jev.close()
    with open(ROOT / "lab" / "results.jsonl", "a") as f:
        for o in out:
            f.write(json.dumps({"task": "chat", **o}) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
