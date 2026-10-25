#!/usr/bin/env python3
"""Follow a live session: the players' chat to the serf, its orders, what it says and how each order ends, one line
each (for a Monitor while a player tests it in their own world).

    .venv/bin/python bench/live_watch.py ~/.local/state/jev/<session>/actor.jsonl
    .venv/bin/python bench/live_watch.py --latest     # the newest session, switching when the serf restarts
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

KINDS = {"chat", "order", "say", "order_end", "error", "left", "joined", "limit_wait", "reopen", "preempt", "flag",
         "dropped", "added_to_queued", "ping", "ping_for", "step"}


def line(r: dict) -> str | None:
    k = r.get("kind")
    if k not in KINDS:
        return None
    t = time.strftime("%H:%M:%S", time.localtime(r.get("t", time.time())))
    if k == "chat":
        if r.get("speaker") in ("serf", "project", "planner"):
            return None
        return f"[{t}] {r.get('speaker')}: {r.get('msg')}  ({r.get('kind_')}, {r.get('playbook')})"
    if k == "error" and r.get("where") == "board" and "unknown op" in str(r.get("error")):
        return None  # a mod before 0.3.4 (no tasks window): expected until the server restarts
    if k == "step":  # only a plan's say steps (what the player reads); the rest is in the log
        st = r.get("step") or {}
        return f"[{t}] serf (plan): {str(st.get('text'))[:300]}" if st.get("do") == "say" else None
    if k == "flag":
        cur = r.get("current") or {}
        return (f"[{t}] FLAG {r.get('speaker')}: {r.get('note')}  (doing: "
                + (f"#{cur.get('id')} {str(cur.get('text'))[:80]}" if cur else "nothing") + ")")
    if k == "order":
        return f"[{t}] ORDER {r.get('order')}: {str(r.get('text'))[:300]}"
    if k == "say":
        return f"[{t}] serf: {str(r.get('text'))[:300]}"
    if k == "order_end":
        return f"[{t}] END order {r.get('order')}: {r.get('status')} after {r.get('secs', 0) / 60:.1f} min, {r.get('plans')} plans"
    return f"[{t}] {k}: {json.dumps({x: y for x, y in r.items() if x not in ('t', 'kind')})[:300]}"


STATE = Path.home() / ".local" / "state" / "jev"


def newest() -> Path | None:
    logs = [d / "actor.jsonl" for d in STATE.iterdir() if (d / "actor.jsonl").exists()] if STATE.exists() else []
    return max(logs, key=lambda p: p.parent.name) if logs else None


def main() -> None:
    latest = sys.argv[1] == "--latest"
    p = newest() if latest else Path(sys.argv[1]).expanduser()
    while p is None:
        time.sleep(2)
        p = newest()
    f = open(p)
    f.seek(0, 2)
    idle = 0
    while True:
        s = f.readline()
        if not s:
            time.sleep(1)
            idle += 1
            if latest and idle % 3 == 0:
                q = newest()
                if q and q != p:  # the serf restarted: a new session
                    p, f = q, open(q)
                    print(f"--- serf restarted: following {q.parent.name}", flush=True)
            continue
        idle = 0
        try:
            out = line(json.loads(s))
        except ValueError:
            continue
        if out:
            print(out, flush=True)


if __name__ == "__main__":
    main()
