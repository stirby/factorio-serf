#!/usr/bin/env python3
"""Every N minutes, the health of each comparison run's base (read-only, over RCON): machines working, starved and
blocked shares, chests filled by hand, belt and pipe per machine, and the science the labs used per minute over
the interval (from the game's own counters). Appends to bench/runs/ab_watch.jsonl.

    .venv/bin/python bench/ab_watch.py p6:75 q6:77 p7:85 q7:87 [--every 30]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from jev import audit as base_audit  # noqa: E402
from jev.rcon import Crew, Rcon  # noqa: E402

SCIENCE = list(base_audit.SHORT)
LUA_USED = ("local st = game.forces.player.get_item_production_statistics(game.surfaces.nauvis) "
            "local out = {tick = game.tick} for _, n in ipairs {" + ",".join(f"'{s}'" for s in SCIENCE) + "} do "
            "out[n] = st.get_output_count(n) end return helpers.table_to_json(out)")


async def look(name: str, k: int, last: dict) -> dict | None:
    pw_file = ROOT / "server" / "instances" / str(k) / "rcon-password"
    try:
        c = Crew(Rcon("127.0.0.1", 27100 + k, pw_file.read_text().strip()))
        await c.connect()
    except Exception as e:  # noqa: BLE001  (between generations the server restarts)
        return {"run": name, "error": repr(e)[:120]}
    try:
        a = await c.call("audit", timeout=90)
        used = json.loads((await c.call("eval", code=LUA_USED, timeout=60))["result"])
    finally:
        await c.close()
    rec = {"run": name, "t": time.time(), **base_audit.numbers(a)}
    rec.pop("spm", None)  # the op's own figure was 60x off before 78215e8; use the counters instead
    prev = last.get(name)
    if prev and used["tick"] > prev["tick"]:
        mins = (used["tick"] - prev["tick"]) / 3600
        per = {s: (used.get(s, 0) - prev.get(s, 0)) / mins for s in SCIENCE}
        rec["spm"] = round(sum(v for v in per.values() if v > 0), 1)
        rec["science"] = {base_audit.SHORT[s]: round(v, 1) for s, v in per.items() if v > 0}
    last[name] = used
    return rec


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+", help="name:slot")
    ap.add_argument("--every", type=float, default=30)
    a = ap.parse_args()
    runs = [(r.split(":")[0], int(r.split(":")[1])) for r in a.runs]
    last: dict = {}
    out = ROOT / "bench" / "runs" / "ab_watch.jsonl"
    while True:
        for name, k in runs:
            try:
                rec = await look(name, k, last)
            except Exception as e:  # noqa: BLE001
                rec = {"run": name, "error": repr(e)[:160]}
            with open(out, "a") as f:
                f.write(json.dumps({"t": time.time(), **(rec or {})}) + "\n")
        await asyncio.sleep(a.every * 60)


if __name__ == "__main__":
    asyncio.run(main())
