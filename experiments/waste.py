#!/usr/bin/env python3
"""Per-run efficiency metrics from a bench run's transcript: where the calls and the minutes went.

    .venv/bin/python experiments/waste.py RUN_DIR [RUN_DIR...]      # one JSON line per run
    .venv/bin/python experiments/waste.py --table RUN_DIR...         # human-readable

Waste = calls that failed, calls that undid the serf's own work (mining what it placed this run, rotating
afterwards), and extra looks (every look after the first in an unbroken streak of inspect/map/look/find).
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

LOOKS = {"inspect", "map", "look", "find", "find_space", "production", "diagnose", "trace"}
FAIL_RE = re.compile(r"(FAILED [^{\n]{0,90}|exception: [^\n]{0,90}|error: [^\n]{0,90})")


def _norm(msg: str) -> str:
    """Failure message with coordinates and counts stripped, so the same failure groups together."""
    return re.sub(r"-?\d+(\.\d+)?", "N", msg).strip()[:90]


def _bucket(call: dict, text: str, failed: bool) -> str:
    """Where a tool call's wall time went."""
    name = call["name"]
    if failed:
        return "failed calls"
    if name in LOOKS:
        return "looking"
    if name == "wait":
        return "idle (nothing running)" if "no jobs running" in text else "waiting on jobs"
    if name == "act":
        ops = {x.get("op") for x in call["args"].get("actions", [])}
        if "wait" in ops:
            return "waiting on jobs"
        if ops <= {"move"}:
            return "walking"
        if ops & {"craft"} and ops <= {"craft", "move", "take"}:
            return "crafting/fetching"
        return "hand building"
    if name in ("build", "stamp"):
        return "blueprint/line building"
    if name.startswith("skill"):
        return "own scripts"
    return "other"


def metrics(run: Path) -> dict:
    res = json.loads((run / "result.json").read_text()) if (run / "result.json").exists() else {}
    tp = run / "state" / "agents" / "serf" / "transcript.jsonl"
    rows = [json.loads(l) for l in tp.read_text().splitlines() if l.strip()] if tp.exists() else []
    tools = [r for r in rows if r["kind"] == "tool"]
    out: dict = {
        "run": run.name, "scenario": res.get("scenario"), "commit": (res.get("git") or {}).get("commit"),
        "success": res.get("success"), "score": res.get("score"),
        "objectives": len(res.get("objectives") or []), "met": res.get("objectives_done"),
        "cost": round(res.get("cost_usd") or 0, 3), "usage_limit": bool(res.get("usage_limit_hit")),
        "errors": res.get("errors") or [],
        "minutes": round((res.get("elapsed_s") or 0) / 60, 1),
        "calls": len(tools),
    }
    # The time to meet each objective (from its start); the last met one is the run's useful length.
    out["obj_secs"] = {o["name"]: round(o.get("secs") or 0) for o in res.get("objectives") or [] if o.get("success")}

    think = idle = 0.0
    last = None
    pend = None
    failed: Counter = Counter()
    n_failed = n_undo = 0
    placed: set = set()
    by_tool: Counter = Counter()
    lost: Counter = Counter()  # seconds by where they went (the morning's "where was the time lost")
    ops_used: set = set()
    for r in rows:
        if r["kind"] == "tool":
            if last is not None:
                think += r["t"] - last
            pend = r
            by_tool[r["name"]] += 1
        elif r["kind"] == "result" and pend:
            text = str(r.get("out", ""))
            dt = r["t"] - pend["t"]
            if pend["name"] == "wait" and "no jobs running" in text:
                idle += dt
            fails = FAIL_RE.findall(text)
            lost[_bucket(pend, text, bool(fails))] += dt
            ops_used.add(pend["name"])
            if pend["name"] == "act":
                ops_used.update("act:" + str(x.get("op")) for x in pend["args"].get("actions", []))
            if fails:
                n_failed += 1
                for f in fails:
                    failed[_norm(f)] += 1
            if pend["name"] == "act":
                for s in pend["args"].get("actions", []):
                    op = s.get("op")
                    if op in ("place",) and "x" in s:
                        placed.add((round(float(s["x"])), round(float(s["y"]))))
                    elif op == "mine" and "x" in s and (round(float(s["x"])), round(float(s["y"]))) in placed:
                        n_undo += 1
                    elif op == "rotate":
                        n_undo += 1
            last, pend = r["t"], None
        elif r["kind"] == "turn":
            last = None

    streak = extra = 0
    for r in tools:
        if r["name"] in LOOKS:
            streak += 1
            extra += streak > 1
        else:
            streak = 0
    looks = sum(by_tool[k] for k in LOOKS)
    calls = max(1, len(tools))
    out.update({
        "think_min": round(think / 60, 1), "idle_min": round(idle / 60, 1),
        "failed_calls": n_failed, "undone": n_undo, "looks": looks, "extra_looks": extra,
        "waste": round((n_failed + n_undo + extra) / calls, 3),
        "cost_per_met": round(out["cost"] / out["met"], 3) if out["met"] else None,
        "top_failures": failed.most_common(6),
        "failure_kinds": sorted(failed),
        "ops_used": sorted(ops_used),
        "lost_min": {k: round(v / 60, 2) for k, v in lost.most_common()} | {"thinking": round(think / 60, 2)},
        "by_tool": dict(by_tool.most_common(12)),
    })
    return out


def main(argv: list[str]) -> None:
    table = "--table" in argv
    runs = [Path(a) for a in argv if a != "--table"]
    ms = [metrics(r) for r in runs]
    if not table:
        for m in ms:
            print(json.dumps(m))
        return
    cols = ["scenario", "met", "objectives", "minutes", "cost", "calls", "think_min", "idle_min", "failed_calls",
            "undone", "extra_looks", "waste"]
    print(" | ".join(cols))
    for m in ms:
        print(" | ".join(str(m.get(c)) for c in cols))
    agg: Counter = Counter()
    for m in ms:
        for msg, n in m["top_failures"]:
            agg[msg] += n
    if agg:
        print("\ntop failures:")
        for msg, n in agg.most_common(12):
            print(f"  {n:3d}  {msg}")


if __name__ == "__main__":
    main(sys.argv[1:])
