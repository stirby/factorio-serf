"""crew: run Claude agents as players in a Factorio game that has the claude-crew mod.

  crew up                         run the crew (reads ./crew.toml if present)
  crew up -n 3 --model claude-opus-5-5 --server 192.168.1.20:27015 --password ...
  crew say "@claude-1 mine some iron"   send chat as a pretend player (testing without a client)
  crew status                     list agents in the game
  crew despawn claude-2           remove an agent's character
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
from pathlib import Path

from . import config as config_mod
from . import ui
from .rcon import Crew, Rcon


def _cfg(args) -> config_mod.CrewConfig:
    path = args.config
    if not path and Path("crew.toml").exists():
        path = "crew.toml"
    cfg = config_mod.load(path, {
        "server": args.server, "password": args.password, "model": getattr(args, "model", None),
        "backend": getattr(args, "backend", None), "count": getattr(args, "n", None),
    })
    if not cfg.server.rcon_password:
        sys.exit("No RCON password: set [server] rcon_password(_file) in crew.toml, FACTORIO_RCON_PASSWORD, "
                 "or pass --password.")
    return cfg


async def _up(args) -> None:
    from .orchestrator import Orchestrator
    cfg = _cfg(args)
    orch = Orchestrator(cfg)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await orch.start()
    await stop.wait()
    ui.info("shutting down (characters stay in the game)")
    await orch.stop()


async def _rcon(args) -> Crew:
    cfg = _cfg(args)
    r = Rcon(cfg.server.host, cfg.server.rcon_port, cfg.server.rcon_password)
    await r.connect()
    return Crew(r)


async def _say(args) -> None:
    crew = await _rcon(args)
    await crew.call("chat", player=args.player, message=" ".join(args.text))


async def _status(args) -> None:
    crew = await _rcon(args)
    for a in (await crew.call("list"))["agents"]:
        print(json.dumps(a))


async def _despawn(args) -> None:
    crew = await _rcon(args)
    await crew.call("despawn", agent=args.name)
    print(f"despawned {args.name}")


def main() -> None:
    p = argparse.ArgumentParser(prog="crew", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", "-c", help="crew.toml (default: ./crew.toml if present)")
    p.add_argument("--server", help="host:rcon_port (default 127.0.0.1:27015)")
    p.add_argument("--password", help="RCON password (or FACTORIO_RCON_PASSWORD)")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    up = sub.add_parser("up", help="run the crew")
    up.add_argument("-n", type=int, help="number of agents (claude-1..N unless named in config)")
    up.add_argument("--model", help="model for every agent, e.g. claude-opus-5-5")
    up.add_argument("--backend", choices=["claude-code", "api"], help="claude-code = your Claude login; api = API key")
    say = sub.add_parser("say", help="inject chat as a pretend player")
    say.add_argument("text", nargs="+")
    say.add_argument("--player", default="tester")
    sub.add_parser("status", help="list agents in game")
    d = sub.add_parser("despawn", help="remove an agent's character")
    d.add_argument("name")
    args = p.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    if args.verbose:
        os.environ["CREW_VERBOSE"] = "1"
        ui.VERBOSE = True
    fn = {"up": _up, "say": _say, "status": _status, "despawn": _despawn}[args.cmd]
    asyncio.run(fn(args))


if __name__ == "__main__":
    main()
