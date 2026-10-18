#!/usr/bin/env python3
"""Run (scenario, variant) jobs in parallel, each in its own server instance, via tests/bench.py subprocesses.

    .venv/bin/python experiments/run_matrix.py -j s4-ghost-build:baseline -j s2-green-science:advisor -P 2
    .venv/bin/python experiments/run_matrix.py --jobs matrix.json -P 3 --repeat 2
    .venv/bin/python experiments/run_matrix.py -j s1-red-science -P 1 --dry          # no agents, no LLM usage
    .venv/bin/python experiments/run_matrix.py --note "switched foreman prompt to v2"

Jobs file: [{"scenario": "s1-red-science", "variant": "baseline", "minutes": 20, "agents": 2, "model": "..."}].
A scenario is a name in experiments/scenarios/ or a path. Each finished run appends a line to
experiments/results.jsonl; experiments/log.jsonl gets run_start / run_end / note events.
Instances 1..P are used (override with --base-instance). Ctrl-C stops every running bench cleanly.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))
from bench import RUNS, log_event, record  # noqa: E402

PY = str(ROOT / ".venv/bin/python")


def scenario_path(s: str) -> Path:
    p = Path(s)
    if p.exists():
        return p.resolve()
    p = HERE / "scenarios" / (s if s.endswith(".json") else s + ".json")
    if not p.exists():
        raise SystemExit(f"no scenario {s} ({p})")
    return p


def parse_jobs(a) -> list[dict]:
    jobs = []
    if a.jobs:
        jobs += json.loads(Path(a.jobs).read_text())
    for j in a.job or []:
        scn, _, var = j.partition(":")
        jobs.append({"scenario": scn, "variant": var or "baseline"})
    out = []
    for r in range(a.repeat):
        for j in jobs:
            j = dict(j)
            for k in ("minutes", "agents", "model"):
                if getattr(a, k) is not None and k not in j:
                    j[k] = getattr(a, k)
            j["rep"] = r
            out.append(j)
    return out


class Matrix:
    def __init__(self, a):
        self.a = a
        self.free = asyncio.Queue()
        for k in range(a.base_instance, a.base_instance + a.parallel):
            self.free.put_nowait(k)
        self.procs: set[asyncio.subprocess.Process] = set()
        self.stopping = False

    async def one(self, j: dict) -> dict:
        k = await self.free.get()
        try:
            if self.stopping:
                return {"skipped": j}
            scn = scenario_path(j["scenario"])
            name = json.loads(scn.read_text())["name"]
            run_id = (time.strftime("%Y%m%d-%H%M%S") + f"-{name}-{j.get('variant', 'baseline')}-i{k}"
                      + ("-dry" if self.a.dry else ""))
            rdir = RUNS / run_id
            rdir.mkdir(parents=True, exist_ok=True)
            cmd = [PY, str(ROOT / "tests/bench.py"), "--scenario", str(scn), "--variant", j.get("variant", "baseline"),
                   "--instance", str(k), "--run-id", run_id, "--no-record"]
            for key, flag in (("minutes", "--minutes"), ("agents", "--agents"), ("model", "--model")):
                if j.get(key) is not None:
                    cmd += [flag, str(j[key])]
            if self.a.dry:
                cmd += ["--dry"] + (["--selftest"] if self.a.selftest else [])
            if self.a.variants:
                cmd += ["--variants", self.a.variants]
            minutes = float(j.get("minutes") or json.loads(scn.read_text()).get("minutes", 10))
            limit = (0 if self.a.dry and not j.get("minutes") else minutes * 60) + 1200
            t0 = time.time()
            log_event("run_start", run_id=run_id, scenario=name, variant=j.get("variant", "baseline"), instance=k,
                      job=j, dry=self.a.dry)
            print(f"[matrix] start {run_id} (instance {k})", flush=True)
            with open(rdir / "bench.log", "w") as logf:
                p = await asyncio.create_subprocess_exec(*cmd, stdout=logf, stderr=asyncio.subprocess.STDOUT,
                                                         cwd=ROOT, start_new_session=True)
                self.procs.add(p)
                try:
                    rc = await asyncio.wait_for(p.wait(), limit)
                except asyncio.TimeoutError:
                    rc = await self.kill(p)
                finally:
                    self.procs.discard(p)
            res_p = rdir / "result.json"
            res = json.loads(res_p.read_text()) if res_p.exists() else {
                "run_id": run_id, "scenario": name, "variant": j.get("variant"), "instance": k,
                "errors": [f"bench exited {rc} without result.json (see {rdir / 'bench.log'})"]}
            res.setdefault("start", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t0)))
            res["exit_code"] = rc
            line = record(res, append=not self.a.dry)  # dry runs are harness checks, not results
            log_event("run_end", run_id=run_id, scenario=name, variant=j.get("variant"), instance=k, exit_code=rc,
                      secs=round(time.time() - t0, 1), score=line.get("score"), cost_usd=line.get("cost_usd"),
                      errors=line.get("errors"))
            print(f"[matrix] done {run_id}: score {line.get('score')} cost {line.get('cost_usd')} rc {rc}", flush=True)
            return line
        finally:
            self.free.put_nowait(k)

    async def kill(self, p) -> int:
        """SIGTERM lets bench stop its orchestrator and server; SIGKILL after a grace period."""
        try:
            os.killpg(p.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            return await asyncio.wait_for(p.wait(), 180)
        except asyncio.TimeoutError:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            return await p.wait()

    def interrupt(self) -> None:
        if self.stopping:
            return
        self.stopping = True
        print("[matrix] stopping: signalling running benches (they clean up their servers)", flush=True)
        for p in list(self.procs):
            asyncio.ensure_future(self.kill(p))

    async def run(self, jobs: list[dict]) -> list[dict]:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self.interrupt)
        return await asyncio.gather(*(self.one(j) for j in jobs))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-j", "--job", action="append", help="scenario[:variant]; repeatable")
    p.add_argument("--jobs", help="JSON list of jobs")
    p.add_argument("-P", "--parallel", type=int, default=2)
    p.add_argument("--base-instance", type=int, default=1)
    p.add_argument("--repeat", type=int, default=1)
    p.add_argument("--minutes", type=float)
    p.add_argument("--agents", type=int)
    p.add_argument("--model")
    p.add_argument("--variants")
    p.add_argument("--dry", action="store_true")
    p.add_argument("--selftest", action="store_true")
    p.add_argument("--note", help="append a note event to experiments/log.jsonl")
    a = p.parse_args()
    if a.note:
        log_event("note", text=a.note)
    jobs = parse_jobs(a)
    if not jobs:
        if not a.note:
            p.error("no jobs (use -j or --jobs)")
        return
    lines = asyncio.run(Matrix(a).run(jobs))
    for ln in lines:
        print(json.dumps({k: ln.get(k) for k in ("run_id", "score", "success", "cost_usd", "errors")}))


if __name__ == "__main__":
    main()
