#!/usr/bin/env python3
"""The rocket rung's stage: stage-s7-bots-online with the rocket silo and every technology it needs researched (by
script; nothing is built), saved as server/factorio/saves/stage-s8-rocket-ready.zip. Never overwrites a save.

    .venv/bin/python scripts/make_rocket_stage.py [instance]"""
from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from instance import INSTALL, Instance  # noqa: E402

from jev.game import Game  # noqa: E402

NAME = "stage-s8-rocket-ready"
RESEARCH = """
local f = game.forces.player
local done = {}
local function learn(t)
  if t.researched or done[t.name] then return end
  done[t.name] = true
  for _, p in pairs(t.prerequisites) do learn(p) end
  t.researched = true
end
learn(f.technologies["rocket-silo"])
local n = 0 for _ in pairs(done) do n = n + 1 end
return {learned = n, silo = f.recipes["rocket-silo"].enabled, part = f.recipes["rocket-part"] and f.recipes["rocket-part"].enabled}
"""


async def main(k: int) -> None:
    out = INSTALL / "saves" / f"{NAME}.zip"
    if out.exists():
        raise SystemExit(f"{out} exists")
    inst = Instance(k, "stage-s7-bots-online")
    await asyncio.to_thread(inst.start, 300)
    try:
        g = await Game.connect(inst.host, inst.rcon_port, inst.password, "serf")
        print("research:", (await g.call("eval", code=RESEARCH, timeout=60)).get("result"))
        await g.call("eval", code=f'game.server_save("{NAME}") return true', timeout=120)
        src = inst.dir / "saves" / f"{NAME}.zip"
        for _ in range(60):
            if src.exists() and src.stat().st_size > 0:
                break
            await asyncio.sleep(1)
        await asyncio.sleep(3)
        shutil.copy2(src, out)
        print("saved", out)
    finally:
        await asyncio.to_thread(inst.stop)


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 97))
