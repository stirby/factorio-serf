#!/usr/bin/env python3
"""Run many scenarios in parallel, one instance each.

    .venv/bin/python bench/batch.py --tag sweep1 -P 4 t-deliver t-starved t-gear-cell ...  [--repeat 2] [--no-think]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


async def one(name: str, inst: int, a, sem: asyncio.Queue) -> dict:
    k = await sem.get()
    try:
        scn = ROOT / "bench" / "scenarios" / f"{name}.json"
        rid = time.strftime("%Y%m%d-%H%M%S") + f"-{name}-{a.tag}-i{k}"
        cmd = [str(ROOT / ".venv/bin/python"), str(ROOT / "bench/run.py"), "--scenario", str(scn), "--instance", str(k),
               "--tag", a.tag, "--run-id", rid]
        if a.no_think:
            cmd.append("--no-think")
        if a.effort:
            cmd += ["--effort", a.effort]
        if a.minutes:
            cmd += ["--minutes", str(a.minutes)]
        logf = ROOT / "bench" / "runs" / f"{rid}.log"
        logf.parent.mkdir(parents=True, exist_ok=True)
        with open(logf, "w") as f:
            p = await asyncio.create_subprocess_exec(*cmd, stdout=f, stderr=asyncio.subprocess.STDOUT)
            await p.wait()
        res = ROOT / "bench" / "runs" / rid / "result.json"
        r = json.loads(res.read_text()) if res.exists() else {"run_id": rid, "scenario": name, "errors": ["no result"]}
        line = (f"{name:20} {'OK ' if r.get('success') else 'no '} {r.get('elapsed_s', 0) / 60:5.1f}m "
                f"${r.get('cost_usd', 0):.3f} think={((r.get('thinker') or {}).get('secs') or 0):.0f}s "
                f"plans={((r.get('actor') or {}).get('plans'))} idle={r.get('char_idle_pct')} err={r.get('errors')[:1] if r.get('errors') else ''}")
        print(line, flush=True)
        return r
    finally:
        sem.put_nowait(k)


def busy_slots() -> set[int]:
    """Instance numbers in use by any run (a server, or a run.py between servers): a run starting on a slot kills
    whatever server holds it, so batches must not share one."""
    import re
    import subprocess
    out = subprocess.run(["pgrep", "-af", "bench/[r]un.py|bin/x64/[f]actorio -c|bench/[l]oop.py|bench/[b]atch.py"],
                         capture_output=True, text=True).stdout
    used = {int(m) for m in re.findall(r"--instance (\d+)", out)}
    used |= {int(m) for m in re.findall(r"instances/(\d+)/", out)}
    # running loops and batches own their whole range, even between runs
    for line in out.splitlines():
        if "loop.py" in line or "batch.py" in line:
            b = re.search(r"--base (\d+)", line)
            n = re.search(r"-P (\d+)", line)
            if b:
                used |= set(range(int(b.group(1)), int(b.group(1)) + (int(n.group(1)) if n else 5)))
    return used


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("scenarios", nargs="+")
    p.add_argument("--tag", default="batch")
    p.add_argument("-P", type=int, default=4)
    p.add_argument("--base", type=int, default=60)
    p.add_argument("--repeat", type=int, default=1)
    p.add_argument("--no-think", action="store_true")
    p.add_argument("--effort")
    p.add_argument("--minutes", type=float)
    a = p.parse_args()
    sem: asyncio.Queue = asyncio.Queue()
    used, k, got = busy_slots(), a.base, []
    while len(got) < a.P and k <= 99:
        if k not in used and k != 20:  # (20 is the serf repo's)
            got.append(k)
        k += 1
    if got != list(range(a.base, a.base + a.P)):
        print(f"(slots {got}: others in use)", flush=True)
    for k in got:
        sem.put_nowait(k)
    jobs = [n for n in a.scenarios for _ in range(a.repeat)]
    rs = await asyncio.gather(*(one(n, 0, a, sem) for n in jobs))
    ok = sum(1 for r in rs if r.get("success"))
    cost = sum(r.get("cost_usd") or 0 for r in rs)
    print(f"== {ok}/{len(rs)} met, ${cost:.2f}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
