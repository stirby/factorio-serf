#!/usr/bin/env python3
"""Lessons the planners wrote since a time, across the bench library and every campaign's, with the ones that make
claims about the harness flagged: a lesson that says an op fails, refuses or can't do something may be a bug to fix
(and, once fixed, a false rule to retire to lessons_retired.jsonl). Also lists tool_complaints.jsonl. Read-only.

    .venv/bin/python scripts/review_lessons.py [HH:MM | hours-ago]      # default: the last 12 hours
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from jev.library import OPS  # noqa: E402

CLAIM = re.compile(r"\b(" + "|".join(OPS) + r")\b[^.]{0,80}\b(can'?t|cannot|fails?|failed|refuses?|won'?t|doesn'?t|"
                   r"never|crash\w*|blocked|broken)\b|\b(the map|generated|ungenerated|edge of)\b", re.I)


def since_arg(a: list[str]) -> float:
    if not a:
        return time.time() - 12 * 3600
    if ":" in a[0]:
        t = time.mktime(time.strptime(time.strftime("%Y-%m-%d ") + a[0], "%Y-%m-%d %H:%M"))
        return t - 86400 if t > time.time() else t
    return time.time() - float(a[0]) * 3600


def main() -> None:
    since = since_arg(sys.argv[1:])
    libs = [ROOT / "library"] + sorted((ROOT / "bench" / "campaigns").glob("*/library"))
    for d in libs:
        name = "bench" if d == ROOT / "library" else d.parent.name
        rows = []
        for fn in ("lessons.jsonl", "tool_complaints.jsonl"):
            p = d / fn
            if p.exists():
                for ln in p.read_text().splitlines():
                    try:
                        r = json.loads(ln)
                    except ValueError:
                        continue
                    if r.get("t", 0) >= since:
                        rows.append((fn, r))
        if not rows:
            continue
        print(f"== {name} ({len(rows)})")
        for fn, r in rows:
            t = r.get("text", "")
            mark = "COMPLAINT" if fn.startswith("tool") else ("CLAIM    " if CLAIM.search(t) else "         ")
            print(f"  {mark} {time.strftime('%H:%M', time.localtime(r['t']))} {t[:220]}")


if __name__ == "__main__":
    main()
