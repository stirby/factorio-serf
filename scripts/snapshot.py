#!/usr/bin/env python3
"""Save the running game as a named stage and record what the base had (snapshots/manifest.jsonl).

    scripts/snapshot.py [label]       ->  server/factorio/saves/stage-<time>-<label>.zip
Load one later with: scripts/server.sh start stage-...
"""
import asyncio, json, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from crew.progress import snapshot  # noqa: E402
from crew.rcon import Crew, Rcon  # noqa: E402


async def main():
    r = Rcon("127.0.0.1", int(os.environ.get("FACTORIO_RCON_PORT", 27015)),
             (ROOT / "server/rcon-password").read_text().strip())
    await r.connect()
    print(json.dumps(await snapshot(Crew(r).call, r.command, sys.argv[1] if len(sys.argv) > 1 else "auto")))
    await r.close()

asyncio.run(main())
