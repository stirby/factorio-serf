#!/usr/bin/env python3
"""Builds the LAB stage, server/factorio/saves/stage-lab.zip: a new map (no enemies, cliffs, little water), flattened
to a clean landfill square around spawn by make_stage_lab.lua, with mid-game research. The lab scenarios (x-*) put
their fixtures on it: infinity-fed input belts, a grid corner, a supply chest (lab-common.lua).

    .venv/bin/python experiments/scenarios/lua/lab/make_stage_lab.py [--instance 50] [--seed 4242]

Uses the bench mod set (vanilla Space Age + factorio-serf) on an isolated instance; the stage is only written at
the end. Rebuild it whenever the research list or the lab size changes.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT))
from crew.rcon import Crew, Rcon  # noqa: E402
from scripts.instance import BIN, INSTALL, Instance  # noqa: E402

STAGE = INSTALL / "saves" / "stage-lab.zip"
MAP_GEN = {
    "width": 0, "height": 0, "starting_area": 2, "peaceful_mode": True,
    "autoplace_controls": {
        "coal": {"frequency": 0.5, "size": 1, "richness": 1}, "stone": {"frequency": 0.5, "size": 1, "richness": 1},
        "copper-ore": {"frequency": 0.5, "size": 1, "richness": 1},
        "iron-ore": {"frequency": 0.5, "size": 1, "richness": 1},
        "uranium-ore": {"frequency": 0.17, "size": 0.17, "richness": 1},
        "crude-oil": {"frequency": 0.5, "size": 1, "richness": 1},
        "water": {"frequency": 0.17, "size": 0.17}, "trees": {"frequency": 0.17, "size": 0.17},
        "enemy-base": {"frequency": 0, "size": 0}, "rocks": {"frequency": 0.17, "size": 0.17},
    },
    "cliff_settings": {"name": "cliff", "cliff_elevation_0": 10, "cliff_elevation_interval": 40, "richness": 0},
    "starting_points": [{"x": 0, "y": 0}], "seed": 4242,
}


async def build(inst: Instance) -> dict:
    r = Rcon(inst.host, inst.rcon_port, inst.password)
    await r.connect()
    try:
        crew = Crew(r)
        out = await crew.call("eval", timeout=240, code=(HERE / "make_stage_lab.lua").read_text())
        await r.command("/server-save stage-lab", timeout=120)
        saved = inst.dir / "saves" / "stage-lab.zip"
        for _ in range(60):  # the save is written as stage-lab.tmp.zip first
            if saved.exists():
                break
            await asyncio.sleep(2)
        return out
    finally:
        await r.close()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--instance", type=int, default=50)
    p.add_argument("--seed", type=int, default=4242)
    a = p.parse_args()
    MAP_GEN["seed"] = a.seed
    inst = Instance(a.instance, "stage-s3-steel-oil-ready")  # any stage: prepare() sets up config and mods
    inst.prepare()
    tmp = Path(tempfile.mkdtemp(prefix="lab-stage-"))  # not inside the instance: start() fails on a save there
    fresh = tmp / "lab-fresh.zip"
    mg = tmp / "lab-map-gen.json"
    mg.write_text(json.dumps(MAP_GEN))
    subprocess.run([str(BIN), "-c", str(inst.dir / "config/config.ini"), "--create", str(fresh),
                    "--map-gen-settings", str(mg)], check=True, stdout=subprocess.DEVNULL)
    inst = Instance(a.instance, fresh)
    inst.start(240)
    try:
        out = asyncio.run(build(inst))
        print("lab:", out)
    finally:
        inst.stop()
    shutil.copy2(inst.dir / "saves" / "stage-lab.zip", STAGE)
    shutil.rmtree(tmp, ignore_errors=True)
    print("wrote", STAGE)


if __name__ == "__main__":
    main()
