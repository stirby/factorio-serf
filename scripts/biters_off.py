#!/usr/bin/env python3
"""Biters off on the dev server (scripts/server.sh runs this on every start). TEST WORLDS ONLY: see crew/peace.py.
    scripts/biters_off.py          uses FACTORIO_RCON_PORT (default 27015) and server/rcon-password"""
import asyncio, json, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from crew.peace import biters_off  # noqa: E402
from crew.rcon import Crew, Rcon  # noqa: E402


async def main():
    pw = (ROOT / "server/rcon-password").read_text().strip()
    r = Rcon("127.0.0.1", int(os.environ.get("FACTORIO_RCON_PORT", 27015)), pw)
    await r.connect()
    try:
        print("biters off:", json.dumps(await biters_off(Crew(r))))
    finally:
        await r.close()

asyncio.run(main())
