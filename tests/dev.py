"""Dev helper: connect to a running instance K (scripts/instance.py start K <stage>), optionally run a scenario's
setup, and give a Game. Used by quick experiments.

    .venv/bin/python tests/dev.py setup K scenario.json       # run setup_lua, print its result (saved to instance dir)
"""
import asyncio, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
from instance import Instance  # noqa: E402
from jev.game import Game  # noqa: E402

PRELUDE = (ROOT / "bench" / "prelude.lua").read_text()


def chunk(lua: str) -> str:
    import re
    return PRELUDE + (lua if re.search(r"\breturn\b", lua) else f"return ({lua})")


async def connect(k: int, name: str = "serf") -> Game:
    inst = Instance(k)
    return await Game.connect(inst.host, inst.rcon_port, inst.password, name)


async def setup(k: int, scn_path: str):
    g = await connect(k)
    scn = json.loads(Path(scn_path).read_text())
    res = (await g.call("eval", code=chunk(scn["setup_lua"]), timeout=60)).get("result")
    (Instance(k).dir / "setup.json").write_text(json.dumps(res))
    print(json.dumps(res))


if __name__ == "__main__":
    if sys.argv[1] == "setup":
        asyncio.run(setup(int(sys.argv[2]), sys.argv[3]))
