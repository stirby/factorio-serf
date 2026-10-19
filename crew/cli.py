"""crew: run Claude agents as players in a Factorio game that has the claude-crew mod.

  crew up                         run the crew (reads ./crew.toml if present)
  crew up -n 3 --model claude-opus-5-5 --server <server-ip>:27015 --password ...
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
        "join": getattr(args, "join", False),
    })
    if getattr(args, "host_serfs", False):
        cfg.host_serfs = True
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
    up.add_argument("--host-serfs", action="store_true",
                    help="players without their own serf app can /serf add; those serfs run on this login")
    up.add_argument("--join", action="store_true", help="spawn no agents at start: only /serf add brings them")
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


SERF_DOC = """serf: bring an AI teammate into your own Factorio game. No server needed.

  serf              connect to your running game; then type /serf add in game
  serf key          save an Anthropic API key (if you don't use a Claude login)
  serf --model claude-opus-5-5

Setup, once: the claude-crew mod enabled, and Factorio started with the launch option
  --enable-lua-udp 27200      (Steam: right-click Factorio > Properties > Launch options)
Model access: your Claude Code login (`claude login`), or an API key (`serf key`).
Settings (optional): ~/.config/claude-crew/serf.toml, same keys as crew.toml ([defaults] model, effort, ...).
"""

SERF_TOML = Path("~/.config/claude-crew/serf.toml").expanduser()


def _serf_key() -> None:
    import getpass
    key = getpass.getpass("Anthropic API key (input hidden): ").strip()
    if not key.startswith("sk-"):
        sys.exit("That doesn't look like an Anthropic key (sk-ant-...). Nothing saved.")
    path = config_mod.ENV_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [l for l in (path.read_text().splitlines() if path.exists() else [])
             if not l.strip().startswith("ANTHROPIC_API_KEY=")]
    path.write_text("\n".join(lines + [f"ANTHROPIC_API_KEY={key}"]) + "\n")
    path.chmod(0o600)
    print(f"saved to {path} (only you can read it). serf will use it when there's no Claude login.")


def _has_claude_login() -> bool:
    """Claude Code installed: the claude-code backend uses its login (keychain on macOS, so don't look for files)."""
    import shutil
    return bool(shutil.which("claude"))


async def _serf(args) -> None:
    from .orchestrator import Orchestrator
    from .udp import UdpCrew
    from .rcon import RconError
    cfg = config_mod.load(SERF_TOML if SERF_TOML.exists() else None,
                          {"udp": args.port, "join": True, "model": args.model})
    if "backend" not in cfg.defaults:
        if _has_claude_login():
            cfg.defaults["backend"] = "claude-code"
        elif os.environ.get("ANTHROPIC_API_KEY"):
            cfg.defaults["backend"] = "api"
        else:
            sys.exit("No model access yet: run `claude login` (Claude subscription) or `serf key` (API key).")
    # One board and notes per world: find out which world is loaded first.
    probe, waited = UdpCrew(args.port), False
    while True:
        try:
            await probe.connect()
            seed = (await probe.call("ping")).get("seed")
            await probe.close()
            break
        except RconError:
            if not waited:
                ui.info(f"waiting for Factorio on UDP port {args.port}: load a game with the claude-crew mod; "
                        f"Factorio must be started with --enable-lua-udp {args.port}")
                waited = True
            await asyncio.sleep(3)
    cfg.state_dir = Path(f"~/.local/state/serf/world-{seed}").expanduser()
    orch = Orchestrator(cfg)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await orch.start()
    await stop.wait()
    ui.info("bye (your serf waits in the game until you run serf again)")
    await orch.stop()


def serf_main() -> None:
    p = argparse.ArgumentParser(prog="serf", description=SERF_DOC, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", nargs="?", choices=["run", "key"], default="run")
    p.add_argument("--port", type=int, default=27200, help="the port in Factorio's --enable-lua-udp (default 27200)")
    p.add_argument("--model", help="e.g. claude-opus-5-5 (default: Sonnet)")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    if args.cmd == "key":
        _serf_key()
        return
    asyncio.run(_serf(args))


if __name__ == "__main__":
    main()
