#!/usr/bin/env python3
"""Follow a live session: the players' chat to the serf, its orders, what it says and how each order ends, one line
each (for a Monitor while a player tests it in their own world).

    .venv/bin/python bench/live_watch.py ~/.local/state/jev/<session>/actor.jsonl
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

KINDS = {"chat", "order", "say", "order_end", "error", "left", "joined", "limit_wait", "reopen", "preempt"}


def line(r: dict) -> str | None:
    k = r.get("kind")
    if k not in KINDS:
        return None
    t = time.strftime("%H:%M:%S", time.localtime(r.get("t", time.time())))
    if k == "chat":
        if r.get("speaker") in ("serf", "project", "planner"):
            return None
        return f"[{t}] {r.get('speaker')}: {r.get('msg')}  ({r.get('kind_')}, {r.get('playbook')})"
    if k == "order":
        return f"[{t}] ORDER {r.get('order')}: {str(r.get('text'))[:300]}"
    if k == "say":
        return f"[{t}] serf: {str(r.get('text'))[:300]}"
    if k == "order_end":
        return f"[{t}] END order {r.get('order')}: {r.get('status')} after {r.get('secs', 0) / 60:.1f} min, {r.get('plans')} plans"
    return f"[{t}] {k}: {json.dumps({x: y for x, y in r.items() if x not in ('t', 'kind')})[:300]}"


def main() -> None:
    p = Path(sys.argv[1]).expanduser()
    with open(p) as f:
        f.seek(0, 2)
        while True:
            s = f.readline()
            if not s:
                time.sleep(1)
                continue
            try:
                out = line(json.loads(s))
            except ValueError:
                continue
            if out:
                print(out, flush=True)


if __name__ == "__main__":
    main()
