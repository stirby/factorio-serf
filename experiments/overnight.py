#!/usr/bin/env python3
"""The overnight loop's runner: many short task runs in parallel, one shared library the serfs grow, metrics per
cycle, and a held-out check at both ends of the night. The core harness is NOT changed while it runs.

    .venv/bin/python experiments/overnight.py [--suite experiments/suites/night.json] [--until 07:30]
        [-P 6] [--repeat 2] [--budget 250] [--base-instance 1] [--night NAME]

Night layout (experiments/nights/<night>/):
  library/          designs, lessons, skills, friction.jsonl: what the serfs built (shared by every train run)
  events.jsonl      phase starts/ends, usage-limit pauses, budget stops
  runs.jsonl        one line per run: waste.py metrics + phase + cycle
Phases: holdout-before (fresh empty library each run) -> train cycles (shared library, debrief on) with a long
task every `long_every` cycles -> holdout-after (the night's library, read-only). The difference between the two
holdout phases is what the agent layer bought; nothing else changes overnight.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "experiments"))
from waste import metrics  # noqa: E402

PY = str(ROOT / ".venv/bin/python")
RUNS = ROOT / "experiments" / "runs"


class Night:
    def __init__(self, a):
        self.a = a
        self.dir = ROOT / "experiments" / "nights" / a.night
        self.lib = self.dir / "library"
        self.lib.mkdir(parents=True, exist_ok=True)
        self.suite = json.loads(Path(a.suite).read_text())
        self.spent = sum(json.loads(l).get("cost") or 0 for l in self._lines("runs.jsonl"))
        self.until = self._until(a.until)

    def _lines(self, name: str) -> list[str]:
        p = self.dir / name
        return [l for l in p.read_text().splitlines() if l.strip()] if p.exists() else []

    @staticmethod
    def _until(hhmm: str) -> float:
        h, m = map(int, hhmm.split(":"))
        now = datetime.now()
        t = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if t <= now:
            t += timedelta(days=1)
        return t.timestamp()

    def event(self, kind: str, **kw) -> None:
        line = {"t": time.time(), "at": time.strftime("%H:%M:%S"), "event": kind, **kw}
        with open(self.dir / "events.jsonl", "a") as f:
            f.write(json.dumps(line) + "\n")
        print(f"[night {line['at']}] {kind} {json.dumps(kw)[:200]}", flush=True)

    def time_left(self) -> float:
        return self.until - time.time()

    def phase(self, name: str, jobs: list[dict], env: dict, cycle: int | None = None) -> list[dict]:
        """One run_matrix call. Returns the metrics of its runs."""
        jf = self.dir / f"jobs-{name}.json"
        jf.write_text(json.dumps(jobs))
        e = dict(os.environ)
        for k in ("SERF_NIGHT_LIBRARY", "SERF_LIBRARY_FROZEN", "SERF_DEBRIEF"):
            e.pop(k, None)
        e.update(env)
        self.event("phase_start", phase=name, cycle=cycle, jobs=len(jobs))
        t0 = time.time()
        p = subprocess.run([PY, str(ROOT / "experiments/run_matrix.py"), "--jobs", str(jf), "-P", str(self.a.parallel),
                            "--base-instance", str(self.a.base_instance)], cwd=ROOT, env=e,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        (self.dir / f"matrix-{name}.log").write_text(p.stdout)
        out = []
        for run_id in re.findall(r"\[matrix\] done (\S+):", p.stdout):
            try:
                m = metrics(RUNS / run_id)
            except Exception as ex:  # noqa: BLE001
                m = {"run": run_id, "errors": [f"metrics failed: {ex}"]}
            res = RUNS / run_id / "result.json"
            if res.exists():
                r = json.loads(res.read_text())
                m["debrief"] = r.get("debrief")
            m.update(phase=name, cycle=cycle)
            out.append(m)
            with open(self.dir / "runs.jsonl", "a") as f:
                f.write(json.dumps(m) + "\n")
            self.spent += m.get("cost") or 0
        limited = [m["run"] for m in out if m.get("usage_limit")]
        met = sum(1 for m in out if m.get("success"))
        self.event("phase_end", phase=name, cycle=cycle, runs=len(out), success=met, spent=round(self.spent, 2),
                   minutes=round((time.time() - t0) / 60, 1), usage_limited=len(limited))
        if limited:
            self.event("usage_limit_pause", minutes=self.a.pause)
            time.sleep(self.a.pause * 60)
        return out

    def jobs(self, names: list[str], repeat: int = 1, variant: str | None = None) -> list[dict]:
        return [{"scenario": n, "variant": variant or self.a.variant} for n in names for _ in range(repeat)]

    def snapshot_library(self, tag: str) -> None:
        """A copy of the library at this point, so the review can diff what the serfs built during the night."""
        dst = self.dir / f"library-{tag}"
        subprocess.run(["rm", "-rf", str(dst)])
        subprocess.run(["cp", "-r", str(self.lib), str(dst)])

    def run(self) -> None:
        s, a = self.suite, self.a
        self.event("night_start", suite=a.suite, until=time.strftime("%H:%M", time.localtime(self.until)),
                   parallel=a.parallel, budget=a.budget)
        # holdout_variant: who plays the held-out tasks. A different model from the trainers tests whether their
        # library helps someone else (e.g. Opus builds scripts, Sonnet uses them).
        hv = s.get("holdout_variant")
        if s.get("holdout_before", True) and not a.skip_holdout_before and not any(json.loads(l).get("phase") == "holdout-before"
                                                 for l in self._lines("runs.jsonl")):
            self.phase("holdout-before", self.jobs(s["holdout"], s.get("holdout_repeat", 1), variant=hv), {"SERF_DEBRIEF": "1"})
        cycle = 1 + max([json.loads(l).get("cycle") or 0 for l in self._lines("runs.jsonl")] or [0])
        cycle_min = s.get("cycle_minutes_estimate", 45)
        holdout_min = s.get("holdout_minutes_estimate", 20)
        while self.time_left() > (cycle_min + holdout_min) * 60:
            if self.spent >= a.budget:
                self.event("budget_stop", spent=round(self.spent, 2))
                break
            names = list(s["train"])
            if s.get("long") and cycle % s.get("long_every", 3) == 0:
                # first, so the long run overlaps the short ones instead of trailing the cycle
                names.insert(0, s["long"][(cycle // s.get("long_every", 3) - 1) % len(s["long"])])
            self.phase(f"train-{cycle}", self.jobs(names, a.repeat),
                       {"SERF_NIGHT_LIBRARY": str(self.lib), "SERF_DEBRIEF": "1"}, cycle)
            self.snapshot_library(f"after-{cycle}")
            cycle += 1
        self.phase("holdout-after", self.jobs(s["holdout"], s.get("holdout_repeat", 1), variant=hv),
                   {"SERF_NIGHT_LIBRARY": str(self.lib), "SERF_LIBRARY_FROZEN": "1", "SERF_DEBRIEF": "1"})
        self.event("night_end", spent=round(self.spent, 2))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--suite", default=str(ROOT / "experiments/suites/night.json"))
    p.add_argument("--night", default=time.strftime("%Y%m%d"))
    p.add_argument("--until", default="07:30")
    p.add_argument("-P", "--parallel", type=int, default=6)
    p.add_argument("--repeat", type=int, default=2)
    p.add_argument("--budget", type=float, default=250, help="API-equivalent $ for the whole night")
    p.add_argument("--pause", type=float, default=30, help="minutes to pause after a usage-limit hit")
    p.add_argument("--base-instance", type=int, default=1)
    p.add_argument("--variant", default="sonnet")
    p.add_argument("--skip-holdout-before", action="store_true")
    Night(p.parse_args()).run()


if __name__ == "__main__":
    main()
