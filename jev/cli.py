"""Play: put the serf into a running game and let it take orders from chat.

    serf                                     # installed with pip or pipx: the same as play --udp 27200

    # single player (or a multiplayer client): start Factorio with --enable-lua-udp 27200, load a game
    .venv/bin/python -m jev.cli play --udp 27200
    # a server you run: RCON
    .venv/bin/python -m jev.cli play --rcon 127.0.0.1:27015 --password-file server/rcon-password
Options: --name serf, --no-think (Sonnet + code only, no Opus), --effort for the thinker, --capture DIR (players'
orders become test cases, and a "!" line in chat saves a flag for the developer: jev/capture.py), --note TEXT (said
after the greeting: what changed since the last restart).
Logs go to ~/.local/state/jev/<time>/ (actor.jsonl, quick.jsonl). The library (lessons, designs) is JEV_LIBRARY,
<repo>/library, or ~/.local/share/factorio-serf/library for an installed app. Ctrl-C stops it; the character
stays in the game.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
import time
from pathlib import Path

from .actor import MODELS, Actor
from .game import Game
from .rcon import Crew, GameError, Rcon
from .quick_reader import reader


async def play(a) -> None:
    if a.rcon:
        host, port = a.rcon.rsplit(":", 1)
        pw = Path(a.password_file).read_text().strip() if a.password_file else a.password
        r = Rcon(host, int(port), pw)
        await r.connect()
        g = Game(Crew(r), a.name or "serf", idle_when_empty=True)
        spawn = {"client": "rcon"}
    else:
        from .udp import UdpCrew
        u = UdpCrew(a.udp)
        await u.connect()
        g = Game(u, a.name or "serf")
        spawn = {}
    state = Path.home() / ".local" / "state" / "jev" / time.strftime("%Y%m%d-%H%M%S")
    state.mkdir(parents=True, exist_ok=True)
    jev = reader(log_path=state / "quick.jsonl")
    if a.quick_model:
        jev.model = MODELS.get(a.quick_model, a.quick_model)
    if a.rcon:
        await g.start(**spawn)
    else:
        await g.start(spawn=False)
        model = await own_serf(g, a.name)
        if model and not a.model:  # "/serf add sonnet"
            a.model = model
    if g.away:
        # sent away in an earlier session: it stays away until a player calls it back
        print(f"{g.name} is away (a player sent it off); waiting for /serf join", flush=True)
        while True:
            ev = await g.events.get()
            if ev.get("agent") == g.name and ev.get("type") == "joined":
                g.away = False
                break
    actor = Actor(g, jev, state, g.name, think=not a.no_think, thinker_effort=a.effort)
    actor.share = a.share
    if a.model:
        actor.set_model(MODELS.get(a.model, a.model))
    if a.rcon and a.password_file:  # a server's serf: its open orders survive a restart of this app
        actor.orders_path = Path(a.password_file).resolve().parent / f"{g.name}-orders.json"
    if a.capture:
        if not a.rcon:
            raise SystemExit("--capture needs --rcon (the save is the server's /server-save)")
        from .capture import Capture
        saves = Path(a.server_saves) if a.server_saves else Path(a.password_file).resolve().parent / "saves"
        world = next((z.stem for z in sorted(saves.glob("*.zip")) if not z.name.startswith("live-")), "")
        cap = Capture(r.command, Path(a.capture), saves, world=world, log_path=state / "actor.jsonl")
        actor.on_new_order, actor.on_order_end, actor.on_flag = cap.order, cap.end, cap.flag
        print(f"capturing players' orders as test cases in {a.capture} (world {world})", flush=True)
    await actor.start()
    who = f"{g.you}'s serf" if g.you else "a serf"
    talk = f"{g.you}: talk to me with @serf" if g.you else f"talk to me with @{g.name}"
    await g.say(f"{g.name} here, {who} ({actor.settings_words()}). {talk}; /serf leave sends me away, /serf join "
                f"brings me back. A line starting with ! is a note for the developers.")
    if a.note:  # live testing: what changed since the last restart
        await g.say(f"[update] {a.note}")
    print(f"{g.name} is in the game. Logs: {state}. Ctrl-C to stop.", flush=True)
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


async def own_serf(g: Game, wanted: str | None) -> str | None:
    """A player's own app: take over their serf in this world, or wait for /serf add and bring one in there. Returns
    the model a "/serf add sonnet" asked for."""
    def waiting():
        print(f"connected to {g.you or 'your game'}'s Factorio. In the game, type /serf add to bring in your serf.",
              flush=True)
    while True:
        ev = await g.pick_serf(wanted, waiting, not_names=MODELS)
        try:
            if ev is None:
                await g.spawn()
            else:
                await g.spawn(position=ev.get("position"), surface=ev.get("surface"))
            break
        except GameError as e:  # a name another player's serf has, or the server's limit
            wanted = None
            try:
                await g.call("tell", player=g.you, text=f"[serf] Couldn't bring in {g.name}: {e}")
            except Exception:  # noqa: BLE001
                pass
    while not g.chat.empty():  # what was said before it arrived isn't for it
        g.chat.get_nowait()
    asked = (ev or {}).get("name")
    return asked if asked in MODELS else None


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("play")
    pl.add_argument("--udp", type=int, nargs="?", const=27200, default=27200)
    pl.add_argument("--rcon", help="host:port")
    pl.add_argument("--password-file")
    pl.add_argument("--password")
    pl.add_argument("--name", help="the serf's name (default: what /serf add names, else serf, else <you>-serf)")
    pl.add_argument("--model", help="the planner's and chat reader's model: opus (default), sonnet, haiku, fable or a "
                    "full model id; '@serf use sonnet' in chat changes it")
    pl.add_argument("--quick-model", help="the model for quick questions (default sonnet)")
    pl.add_argument("--share", action="store_true", help="take orders from any player who names this serf (default: "
                    "only from you; each player brings their own)")
    pl.add_argument("--capture", metavar="DIR", help="save each player's order with a save of the world as a test case "
                    "(jev/capture.py); RCON only")
    pl.add_argument("--server-saves", metavar="DIR", help="where the server writes /server-save (default: the "
                    "password file's folder + /saves, as for scripts/instance.py servers)")
    pl.add_argument("--note", help="said in game after the greeting (live testing: what changed since the restart)")
    pl.add_argument("--no-think", action="store_true")
    pl.add_argument("--effort", help="how hard the planner thinks: low, medium, high or max; '@serf set effort high' "
                    "in chat changes it")
    a = p.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    asyncio.run(play(a))


def serf() -> None:
    """The `serf` command of an installed app: `serf` alone plays over UDP 27200; `serf --name bob` and the like take
    play's options."""
    if len(sys.argv) < 2 or sys.argv[1].startswith("-"):
        sys.argv.insert(1, "play")
    main()


if __name__ == "__main__":
    main()
