"""Play: put the Jev+Opus character into a running game and let it take orders from chat.

    # single player (or a multiplayer client): start Factorio with --enable-lua-udp 27200, load a game
    .venv/bin/python -m jev.cli play --udp 27200
    # a server you run: RCON
    .venv/bin/python -m jev.cli play --rcon 127.0.0.1:27015 --password-file server/rcon-password
Options: --name serf, --no-think (Jev + code only, no Opus), --effort for the thinker.
Logs go to ~/.local/state/jev/<time>/ (actor.jsonl, jev.jsonl). The library (lessons, designs) is JEV_LIBRARY or
<repo>/library. Ctrl-C stops it; the character stays in the game.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import time
from pathlib import Path

from .actor import Actor
from .game import Game
from .rcon import Crew, Rcon
from .typesafe import reader


async def play(a) -> None:
    if a.rcon:
        host, port = a.rcon.rsplit(":", 1)
        pw = Path(a.password_file).read_text().strip() if a.password_file else a.password
        r = Rcon(host, int(port), pw)
        await r.connect()
        g = Game(Crew(r), a.name)
        spawn = {"client": "rcon"}
    else:
        from .udp import UdpCrew
        u = UdpCrew(a.udp)
        await u.connect()
        g = Game(u, a.name)
        spawn = {}
    state = Path.home() / ".local" / "state" / "jev" / time.strftime("%Y%m%d-%H%M%S")
    state.mkdir(parents=True, exist_ok=True)
    jev = reader(log_path=state / "jev.jsonl")
    await g.start(**spawn)
    actor = Actor(g, jev, state, a.name, think=not a.no_think, thinker_effort=a.effort)
    await actor.start()
    await g.say(f"{a.name} here (Jev acting, {'Opus planning' if not a.no_think else 'no planner'}). "
                f"Talk to me with @{a.name}.")
    print(f"{a.name} is in the game. Logs: {state}. Ctrl-C to stop.", flush=True)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    print("stopping...", flush=True)
    await actor.stop()
    await g.stop()
    await jev.close()
    print(f"jev: {jev.stats.as_dict()}", flush=True)
    if actor.thinker:
        print(f"thinker: {actor.thinker.stats}", flush=True)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("play")
    pl.add_argument("--udp", type=int, nargs="?", const=27200, default=27200)
    pl.add_argument("--rcon", help="host:port")
    pl.add_argument("--password-file")
    pl.add_argument("--password")
    pl.add_argument("--name", default="serf")
    pl.add_argument("--no-think", action="store_true")
    pl.add_argument("--effort")
    pl.add_argument("--reader", choices=["jev", "sonnet"], help="who reads orders and makes quick decisions "
                    "(default jev; sonnet = Claude Sonnet in its place)")
    a = p.parse_args()
    if getattr(a, "reader", None):
        os.environ["JEV_READER"] = a.reader
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    asyncio.run(play(a))


if __name__ == "__main__":
    main()
