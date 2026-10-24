#!/usr/bin/env python3
"""Start a test slot on a copy of a stage or save, run Lua snippets from a file (parts split by a line
"--SPLIT--", with `wait` seconds between them), print each result, stop the slot. For fixture dry runs.

    .venv/bin/python scripts/ev_once.py crew-test 67 path/to/snippets.lua 20
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from instance import Instance  # noqa: E402
from jev.rcon import Crew, Rcon  # noqa: E402


async def main(save: str, k: int, code_file: str, wait: float) -> None:
    inst = Instance(k, save)
    await asyncio.to_thread(inst.start, 300)
    try:
        c = Crew(Rcon(inst.host, inst.rcon_port, inst.password))
        await c.connect()
        for part in Path(code_file).read_text().split("\n--SPLIT--\n"):
            print((await c.call("eval", code=part, timeout=120))["result"], flush=True)
            await asyncio.sleep(wait)
        await c.close()
    finally:
        await asyncio.to_thread(inst.stop)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], int(sys.argv[2]), sys.argv[3], float(sys.argv[4]) if len(sys.argv) > 4 else 0))
