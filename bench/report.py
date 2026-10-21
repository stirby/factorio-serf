#!/usr/bin/env python3
"""Jev+Opus vs the frozen serf, per scenario.

    .venv/bin/python bench/report.py [--tags sweep1,sweep2] [--md out.md]

Serf baseline: every run in factorio-serf's experiments/nights/*/runs.jsonl (Sonnet and Opus tracks). Jev side:
bench/runs/*/result.json (+ the actor log for order-to-done seconds).
"""
from __future__ import annotations

import argparse
import glob
import json
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERF = Path.home() / "dev" / "factorio-slave" / "experiments" / "nights"


def med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def serf_baseline() -> dict:
    out = defaultdict(lambda: {"runs": 0, "ok": 0, "min_ok": [], "cost": [], "tracks": set()})
    for f in glob.glob(str(SERF / "*" / "runs.jsonl")):
        track = "opus" if "opus" in f else "sonnet"
        for l in open(f):
            if not l.strip():
                continue
            r = json.loads(l)
            if r.get("usage_limit"):
                continue
            b = out[r["scenario"]]
            b["runs"] += 1
            b["ok"] += 1 if r.get("success") else 0
            if r.get("success"):
                b["min_ok"].append(r.get("minutes"))
            b["cost"].append(r.get("cost") or 0)
            b["tracks"].add(track)
    return out


def jev_runs(tags: list[str] | None) -> dict:
    out = defaultdict(list)
    for d in sorted(glob.glob(str(ROOT / "bench" / "runs" / "*" / "result.json"))):
        r = json.loads(Path(d).read_text())
        if tags and r.get("tag") not in tags:
            continue
        p = Path(d).parent / "actor.jsonl"
        secs = None
        if p.exists():
            ends = [json.loads(l) for l in p.read_text().splitlines() if '"order_end"' in l]
            done = [e for e in ends if e.get("status") == "done"]
            if done:
                secs = done[0]["secs"]
        r["order_secs"] = secs
        out[r["scenario"]].append(r)
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--tags")
    p.add_argument("--md")
    a = p.parse_args()
    tags = a.tags.split(",") if a.tags else None
    sb, jr = serf_baseline(), jev_runs(tags)
    rows = []
    hdr = ("| test | serf met | serf median min | serf $/run | jev met | jev median min | jev order→done s | "
           "jev $/run | Opus s/run | plans/run |")
    rows.append(hdr)
    rows.append("|" + "---|" * 10)
    tot = {"serf_cost": 0.0, "jev_cost": 0.0}
    for name in sorted(set(jr) | set(k for k in sb if k in jr)):
        s, j = sb.get(name), jr.get(name, [])
        ok = [x for x in j if x.get("success")]
        jmin = med([x.get("elapsed_s", 0) / 60 for x in ok]) if ok else None
        jsec = med([x.get("order_secs") for x in ok])
        jcost = statistics.mean([x.get("cost_usd") or 0 for x in j]) if j else 0
        think = statistics.mean([((x.get("thinker") or {}).get("secs") or 0) for x in j]) if j else 0
        plans = statistics.mean([((x.get("actor") or {}).get("plans") or 0) for x in j]) if j else 0
        if s and s["runs"]:
            sm = med(s["min_ok"])
            sc = statistics.mean(s["cost"])
            serf = (f"{s['ok']}/{s['runs']}", f"{sm:.1f}" if sm is not None else "-", f"${sc:.2f}")
        else:
            serf = ("-", "-", "-")
        rows.append(f"| {name} | {serf[0]} | {serf[1]} | {serf[2]} | {len(ok)}/{len(j)} | "
                    f"{f'{jmin:.1f}' if jmin is not None else '-'} | {f'{jsec:.0f}' if jsec is not None else '-'} | "
                    f"${jcost:.3f} | {think:.0f} | {plans:.1f} |")
    txt = "\n".join(rows)
    print(txt)
    if a.md:
        Path(a.md).write_text(txt + "\n")


if __name__ == "__main__":
    main()
