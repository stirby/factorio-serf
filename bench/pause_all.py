#!/usr/bin/env python3
"""Pause the automated testing: each campaign saves its world as <name>-gNN-tpauseHHMM (in its saves folder, where
scripts/resume_campaign.py takes the newest -t* save from) and stops with its server; each bench run saves its world
as a stage (server/factorio/saves/<scenario>-<tag>-pauseHHMM.zip: a later run can start from it) and stops.
bench/resume_campaigns.sh puts the campaigns back.

    .venv/bin/python bench/pause_all.py p6:75 p7:85 ... --bench b16-rocket-with-research-r1:60 ...
"""
from __future__ import annotations

import argparse
import asyncio
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
sys.path.insert(0, str(ROOT))
from instance import INSTALL, Instance  # noqa: E402
from jev.rcon import Crew, Rcon  # noqa: E402

STAMP = time.strftime("%H%M")


async def server_save(k: int, name: str) -> Path | None:
    inst = Instance(k)
    c = Crew(Rcon(inst.host, inst.rcon_port, inst.password))
    await c.connect()
    try:
        await c.call("eval", code=f'game.server_save("{name}") return true', timeout=180)
    finally:
        await c.close()
    src = inst.dir / "saves" / f"{name}.zip"
    last = -1
    for _ in range(120):
        if src.exists():
            n = src.stat().st_size
            if n == last and n > 0:
                return src
            last = n
        await asyncio.sleep(1)
    return None


def pids(pattern: str) -> list[int]:
    out = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True).stdout.split()
    return [int(p) for p in out if int(p) != os.getpid()]


def stop(pattern: str, k: int) -> None:
    for pid in pids(pattern):
        os.kill(pid, signal.SIGTERM)
    time.sleep(5)
    for pid in pids(pattern):
        os.kill(pid, signal.SIGKILL)
    Instance(k).stop()


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("campaigns", nargs="*", help="name:slot")
    ap.add_argument("--bench", nargs="*", default=[], help="run-name:slot (scenario-tag:slot)")
    a = ap.parse_args()
    for spec in a.campaigns:
        name, k = spec.split(":")
        # the running generation, as resume_campaign.py counts it: the state's last finished one + 1 (the state is
        # written when a generation ends; a first generation has none yet)
        sp = ROOT / "bench" / "campaigns" / name / "campaign.json"
        gen = (json.loads(sp.read_text()).get("gen", 0) if sp.exists() else 0) + 1
        save = f"{name}-g{gen:02d}-tpause{STAMP}"
        src = await server_save(int(k), save)
        if src:
            dst = ROOT / "bench" / "campaigns" / name / "saves" / src.name
            shutil.copy2(src, dst)
            print(f"{name}: saved {dst.name}", flush=True)
        else:
            print(f"{name}: SAVE FAILED, not stopping it", flush=True)
            continue
        stop(f"campaign.py --name {name} ", int(k))
        print(f"{name}: stopped (slot {k})", flush=True)
    for spec in a.bench:
        run, k = spec.rsplit(":", 1)
        src = await server_save(int(k), f"{run}-pause{STAMP}")
        if src:
            dst = INSTALL / "saves" / src.name
            shutil.copy2(src, dst)
            print(f"{run}: world saved as stage {dst.stem}", flush=True)
        else:
            print(f"{run}: SAVE FAILED, not stopping it", flush=True)
            continue
        stop(f"bench/run.py.*--instance {k}( |$)", int(k))
        print(f"{run}: stopped (slot {k})", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
