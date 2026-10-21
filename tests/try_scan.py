"""Start an instance from a scenario's stage, run its setup, spawn the agent and dump a scan of the goal area."""
import asyncio, json, re, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
from instance import Instance
from jev.game import Game
from jev.rcon import Rcon, Crew

PRELUDE = open(ROOT / "bench" / "prelude.lua").read() if (ROOT / "bench" / "prelude.lua").exists() else ""

async def main(scn_path, k, out):
    scn = json.loads(Path(scn_path).read_text())
    inst = Instance(k, scn["stage"])
    await asyncio.to_thread(inst.start, 240)
    try:
        g = await Game.connect(inst.host, inst.rcon_port, inst.password)
        setup = await g.call("eval", code=PRELUDE + scn["setup_lua"], timeout=60)
        setup = setup.get("result")
        print("setup:", setup)
        await g.start()
        me = await g.me(); print("me:", me["position"], list((me.get("inventory") or {}).items())[:8])
        center = None
        if isinstance(setup, dict):
            if "gx" in setup: center = (setup["gx"], setup["gy"])
        t = time.time(); sc = await g.scan(center=center, radius=20); ms = (time.time()-t)*1000
        print(f"scan {ms:.0f} ms: {len(sc['ents'])} ents, grids {sc['grids']}, res {list(sc['res'])}, chars {sc['chars']}")
        Path(out).write_text(json.dumps({"setup": setup, "me": me, "scan": sc}, indent=1))
        await g.stop()
    finally:
        await asyncio.to_thread(inst.stop)

asyncio.run(main(sys.argv[1], int(sys.argv[2]), sys.argv[3]))
