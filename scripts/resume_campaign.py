#!/usr/bin/env python3
"""Move a running campaign onto the current code without losing its world: stop it, close its current generation at
its latest half-hourly save, and start the next generation from that save (a fresh process, so the current code).

    .venv/bin/python scripts/resume_campaign.py <name> <campaign.py args...>
e.g. scripts/resume_campaign.py p2 --world stage-s3-steel-oil-ready --gen-hours 4 --gens 8 --instance 87 --mode project

If the generation that's running has no save yet, it is simply started again from where it started. Never touches a
save it didn't make: the latest save is copied to server/factorio/saves/campaign-<name>-gNN-recover.zip."""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from instance import INSTALL, INSTANCES  # noqa: E402


def pids(pattern: str) -> list[int]:
    out = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True).stdout.split()
    return [int(p) for p in out if int(p) != os.getpid()]


def main() -> None:
    name, args = sys.argv[1], sys.argv[2:]
    k = args[args.index("--instance") + 1]
    camp = ROOT / "bench" / "campaigns" / name
    state_path = camp / "campaign.json"
    if state_path.exists():
        state = json.loads(state_path.read_text())
    else:  # still in its first generation: campaign.py writes this file when a generation ends
        world = args[args.index("--world") + 1]
        state = {"name": name, "stage": world, "gen": 0, "gens": [], "worlds": [world]}
    running = state["gen"] + 1
    for p in pids(f"bench/[c]ampaign.py --name {name} --"):
        os.kill(p, signal.SIGTERM)
    time.sleep(5)
    for p in pids(f"instances/{k}/[c]onfig"):
        os.kill(p, signal.SIGTERM)
    time.sleep(3)
    saves = sorted((camp / "saves").glob(f"{name}-g{running:02d}-t*.zip"), key=lambda q: q.stat().st_mtime)
    gdir = camp / f"gen-{running:02d}"
    if saves:
        stage = f"campaign-{name}-g{running:02d}-recover"
        shutil.copy2(saves[-1], INSTALL / "saves" / f"{stage}.zip")
        probes = [json.loads(x) for x in (gdir / "progress.jsonl").read_text().splitlines() if '"level"' in x]
        summ = {"gen": running, "stage": state["stage"], "hours": round((probes[-1]["t"] - probes[0]["t"]) / 3600, 2),
                "level_start": probes[0]["level"], "level_end": probes[-1]["level"],
                "milestones": probes[-1]["milestones"], "techs": probes[-1]["techs"], "fix_share": 0,
                "stopped_by_hand": f"moved onto the current code at {time.strftime('%H:%M')}; carried on from "
                                   f"{saves[-1].name}", "final_save": str(saves[-1])}
        (gdir / "summary.json").write_text(json.dumps(summ, indent=1))
        state["gens"].append(summ)
        state["gen"] = running
        state["stage"] = stage
        state_path.write_text(json.dumps(state, indent=1))
        print(f"{name}: generation {running} closed at {saves[-1].name}; next starts from {stage}")
        # score the closed generation like campaign.py does when one ends by itself: the base left alone
        subprocess.Popen([str(ROOT / ".venv/bin/python"), str(ROOT / "scripts" / "audit_base.py"), str(saves[-1]),
                          "--minutes", "5", "--instance", "auto", "--label", f"g{running}",
                          "--append", str(camp / "audits.jsonl")],
                         cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    else:
        if gdir.exists():
            gdir.rename(camp / f"gen-{running:02d}-aborted-{time.strftime('%H%M')}")
        print(f"{name}: generation {running} had no save yet; starting it again from {state['stage']}")
    log = ROOT / "bench" / "runs" / f"camp_{name}.out"
    with open(log, "a") as f:
        f.write(time.strftime("%H:%M:%S") + f" relaunching {name} on the current code\n")
        subprocess.Popen([str(ROOT / ".venv/bin/python"), "bench/campaign.py", "--name", name, *args], cwd=ROOT,
                         stdout=f, stderr=subprocess.STDOUT, start_new_session=True)


if __name__ == "__main__":
    main()
