#!/usr/bin/env python3
"""A fresh world for a campaign: Space Age (the bench's mods), default resources, no enemy bases, peaceful. Writes
server/factorio/saves/<name>.zip and never overwrites an existing save.

    .venv/bin/python scripts/new_world.py campaign-w1 [seed]

Every server started from it still runs the biters-off script (scripts/instance.py), so a world that somehow had
enemies is cleaned on start."""
from __future__ import annotations

import json
import random
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from instance import BENCH_SETTINGS, BIN, INSTALL, INSTANCES, MOD_SRC, REQUIRED_MODS  # noqa: E402


def create(name: str, seed: int) -> Path:
    out = INSTALL / "saves" / f"{name}.zip"
    if out.exists():
        raise FileExistsError(f"{out} exists; pick another name")
    work = INSTANCES / "create"
    if work.exists():
        shutil.rmtree(work)
    (work / "config").mkdir(parents=True)
    (work / "config/config.ini").write_text(f"[path]\nread-data={INSTALL / 'data'}\nwrite-data={work}\n"
                                            "[general]\nlocale=auto\n")
    mods = work / "mods"
    mods.mkdir()
    (mods / "factorio-serf").symlink_to(MOD_SRC)
    (mods / "mod-list.json").write_text(json.dumps({"mods": [{"name": n, "enabled": True} for n in REQUIRED_MODS]}))
    if BENCH_SETTINGS.exists():
        shutil.copy2(BENCH_SETTINGS, mods / "mod-settings.dat")
    mgs = json.loads((INSTALL / "data/map-gen-settings.example.json").read_text())
    mgs["seed"] = seed
    mgs["peaceful_mode"] = True
    ac = mgs.setdefault("autoplace_controls", {})
    ac["enemy-base"] = {"frequency": 0, "size": 0, "richness": 0}
    (work / "mgs.json").write_text(json.dumps(mgs, indent=1))
    ms = json.loads((INSTALL / "data/map-settings.example.json").read_text())
    ms.setdefault("enemy_evolution", {})["enabled"] = False
    ms.setdefault("enemy_expansion", {})["enabled"] = False
    (work / "ms.json").write_text(json.dumps(ms, indent=1))
    tmp = work / f"{name}.zip"
    r = subprocess.run([str(BIN), "-c", str(work / "config/config.ini"), "--create", str(tmp),
                        "--map-gen-settings", str(work / "mgs.json"), "--map-settings", str(work / "ms.json")],
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0 or not tmp.exists():
        raise RuntimeError(f"create failed ({r.returncode}):\n{r.stdout[-2000:]}\n{r.stderr[-1000:]}")
    shutil.copy2(tmp, out)
    return out


if __name__ == "__main__":
    nm = sys.argv[1]
    sd = int(sys.argv[2]) if len(sys.argv) > 2 else random.randrange(1, 2 ** 31)
    print(create(nm, sd), "seed", sd)
