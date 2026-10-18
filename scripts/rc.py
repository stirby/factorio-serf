#!/usr/bin/env python3
"""Dev helper: scripts/rc.py <op> [json-args]   or   scripts/rc.py --raw '/command'"""
import asyncio, json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from crew.rcon import Rcon, Crew

async def main():
    pw = (Path(__file__).resolve().parent.parent / "server/rcon-password").read_text().strip()
    r = Rcon("127.0.0.1", int(os.environ.get("FACTORIO_RCON_PORT", 27015)), pw)
    await r.connect()
    if sys.argv[1] == "--raw":
        print(await r.command(sys.argv[2]))
    else:
        args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
        print(json.dumps(await Crew(r).call(sys.argv[1], **args), indent=1))
    await r.close()

asyncio.run(main())
