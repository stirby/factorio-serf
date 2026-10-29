#!/usr/bin/env python3
"""Jev's effort picks (shadow mode) next to how each order went: did the orders it called low or medium go through on
the first plan, and did the ones it called max need more? The user's idea: Jev "for deciding thinking effort on a given
task". Jev decides nothing until this shows its picks would have helped.

    .venv/bin/python bench/effort_shadow.py ~/.local/state/jev/*/actor.jsonl
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

LEVELS = ("low", "medium", "high", "max")


def rows(paths: list[str]) -> list[dict]:
    out = []
    for p in paths:
        picks, ends, texts, ups = {}, {}, {}, set()
        for line in Path(p).expanduser().read_text().splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            k = r.get("kind")
            if k == "effort_shadow":
                picks[r["order"]] = r
            elif k == "order_end":
                ends[r["order"]] = r
            elif k == "effort_up":
                ups.add(r["order"])
            elif k == "order_start" or (k == "chat" and r.get("action") == "new_job"):
                texts.setdefault(r.get("order"), r.get("msg") or r.get("text"))
        for oid, pk in picks.items():
            e = ends.get(oid)
            if e:
                out.append({"log": Path(p).parent.name, "order": oid, "pick": pk["pick"], "conf": pk["conf"],
                            "status": e["status"], "plans": e.get("plans", 0), "mins": round(e["secs"] / 60, 1),
                            "escalated": oid in ups})
    return out


def main() -> None:
    rs = rows(sys.argv[1:])
    if not rs:
        print("no orders with a shadow pick yet")
        return
    by = defaultdict(list)
    for r in rs:
        by[r["pick"]].append(r)
    print(f"{'pick':8} {'orders':>6} {'1st plan ok':>11} {'avg plans':>9} {'failed':>6} {'avg min':>7}")
    for lv in LEVELS:
        g = by.get(lv) or []
        if not g:
            continue
        first = sum(1 for r in g if r["status"] == "done" and r["plans"] <= 1)
        print(f"{lv:8} {len(g):6} {first:11} {sum(r['plans'] for r in g) / len(g):9.1f} "
              f"{sum(1 for r in g if r['status'] == 'failed'):6} {sum(r['mins'] for r in g) / len(g):7.1f}")
    print("\nJev's pick would have helped where low/medium orders passed on the first plan and max ones needed more.")


if __name__ == "__main__":
    main()
