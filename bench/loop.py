#!/usr/bin/env python3
"""Continuous test loop: run a suite in cycles, P at a time, until a time or a budget is reached. Each run is a
separate process (bench/run.py) on its own instance, using the code as it is when that run starts, so fixes made
between runs are picked up by the next ones. All runs of a loop share one library (lessons, designs) so the
thinker's own layer grows over the loop.

    .venv/bin/python bench/loop.py --suite bench/suites/core.json --tag loop1 -P 6 --until 23:00 --budget 60
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def until_ts(s: str) -> float:
    h, m = map(int, s.split(":"))
    now = dt.datetime.now()
    t = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if t <= now:
        t += dt.timedelta(days=1)
    return t.timestamp()


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--suite", required=True)
    p.add_argument("--tag", required=True)
    p.add_argument("-P", type=int, default=5)
    p.add_argument("--base", type=int, default=60)
    p.add_argument("--until", default=None)
    p.add_argument("--budget", type=float, default=50.0, help="notional USD (Opus cost as the SDK reports it)")
    p.add_argument("--cycles", type=int, default=99)
    p.add_argument("--library", default=None, help="shared library dir (default bench/libraries/<tag>)")
    a = p.parse_args()
    suite = json.loads(Path(a.suite).read_text())
    end = until_ts(a.until) if a.until else time.time() + 24 * 3600
    lib = Path(a.library) if a.library else ROOT / "bench" / "libraries" / a.tag
    lib.mkdir(parents=True, exist_ok=True)
    os.environ["JEV_LIBRARY"] = str(lib)
    log = ROOT / "bench" / "runs" / f"loop-{a.tag}.log"
    spent = 0.0
    q: asyncio.Queue = asyncio.Queue()
    for i in range(a.P):
        q.put_nowait(a.base + i)

    def say(msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        with open(log, "a") as f:
            f.write(line + "\n")

    async def one(name: str, cycle: int) -> dict:
        nonlocal spent
        k = await q.get()
        try:
            if time.time() > end or spent >= a.budget:
                return {}
            rid = time.strftime("%Y%m%d-%H%M%S") + f"-{name}-{a.tag}-c{cycle}-i{k}"
            cmd = [str(ROOT / ".venv/bin/python"), str(ROOT / "bench/run.py"), "--scenario",
                   str(ROOT / "bench/scenarios" / f"{name}.json"), "--instance", str(k), "--tag", a.tag, "--run-id", rid]
            with open(ROOT / "bench" / "runs" / f"{rid}.log", "w") as f:
                pr = await asyncio.create_subprocess_exec(*cmd, stdout=f, stderr=asyncio.subprocess.STDOUT)
                await pr.wait()
            rp = ROOT / "bench" / "runs" / rid / "result.json"
            r = json.loads(rp.read_text()) if rp.exists() else {"scenario": name, "errors": ["no result"]}
            spent += r.get("cost_usd") or 0
            say(f"c{cycle} {name:20} {'OK ' if r.get('success') else 'no '} {r.get('elapsed_s', 0) / 60:5.1f}m "
                f"${r.get('cost_usd', 0):.3f} plans={(r.get('actor') or {}).get('plans')} spent=${spent:.2f}")
            return r
        finally:
            q.put_nowait(k)

    say(f"loop {a.tag}: suite {a.suite}, P={a.P}, budget ${a.budget}, until {a.until}, library {lib}")
    for cycle in range(1, a.cycles + 1):
        if time.time() > end or spent >= a.budget:
            break
        names = suite["tests"] * suite.get("repeat", 1)
        rs = await asyncio.gather(*(one(n, cycle) for n in names))
        rs = [r for r in rs if r]
        ok = sum(1 for r in rs if r.get("success"))
        say(f"cycle {cycle}: {ok}/{len(rs)} met, spent ${spent:.2f}")
    say("loop done")


if __name__ == "__main__":
    asyncio.run(main())
