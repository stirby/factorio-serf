#!/usr/bin/env python3
"""A live test session in a player's own world: a copy of their newest save on a local server (slot 70, biters off,
the player's mods), the serf on it capturing every order and every "!" flag, and a log a developer can watch.

    .venv/bin/python bench/live_session.py up [SAVE]         # copy SAVE (default: the newest in ~/.factorio/saves)
                                                             # and (re)start slot 70, then the serf
    .venv/bin/python bench/live_session.py serf [--note TEXT] [--force]   # restart only the serf (seconds; the
                                                             # character stays, the player stays connected)
    .venv/bin/python bench/live_session.py status

The player joins with Multiplayer > Connect to address > localhost:34270. Their saves are only read: the copy goes to
bench/live_cases/worlds/ (git-ignored) and the server runs a copy of that. Restarting the server refuses while anyone
is online (it would kick them); restarting the serf refuses while it has a job (unless --force). The serf's output goes
to server/instances/70/serf.log; its log to ~/.local/state/jev/<time>/actor.jsonl (bench/live_watch.py follows it).
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from instance import Instance  # noqa: E402
from jev.rcon import Crew, Rcon  # noqa: E402

SLOT = 70
SAVES = Path.home() / ".factorio" / "saves"
WORLDS = ROOT / "bench" / "live_cases" / "worlds"
CASES = ROOT / "bench" / "live_cases"


def inst() -> Instance:
    return Instance(SLOT, mods="live")


async def _rcon(cmd: str | None = None, op: str | None = None, **kw):
    i = inst()
    r = Rcon(i.host, i.rcon_port, i.password)
    await r.connect()
    try:
        return await (r.command(cmd) if cmd else Crew(r).call(op, **kw))
    finally:
        await r.close()


def online() -> int:
    out = asyncio.run(_rcon("/players online"))
    m = re.search(r"Online players \((\d+)\)", out)
    return int(m.group(1)) if m else 0


def serf_pid() -> int | None:
    f = inst().dir / "serf.pid"
    try:
        pid = int(f.read_text().strip())
        cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
    except (OSError, ValueError):
        return None
    return pid if "jev.cli" in cmd and f":{inst().rcon_port}" in cmd else None


def stop_serf() -> None:
    pid = serf_pid()
    if not pid:
        return
    os.kill(pid, signal.SIGINT)  # the app cancels its jobs and leaves the character standing
    for _ in range(40):
        if not serf_pid():
            return
        time.sleep(0.5)
    os.kill(pid, signal.SIGTERM)


def start_serf(note: str | None) -> None:
    i = inst()
    cmd = [str(ROOT / ".venv/bin/python"), "-m", "jev.cli", "play", "--rcon", f"{i.host}:{i.rcon_port}",
           "--password-file", str(i.pwfile), "--capture", str(CASES)]
    if note:
        cmd += ["--note", note]
    log = open(i.dir / "serf.log", "a")
    log.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} start{' (' + note + ')' if note else ''}\n")
    log.flush()
    p = subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                         start_new_session=True)
    log.close()
    (i.dir / "serf.pid").write_text(str(p.pid))
    for _ in range(60):  # up once it prints where its logs are
        time.sleep(0.5)
        tail = (i.dir / "serf.log").read_text(errors="replace")[-2000:]
        if "is in the game" in tail or "is away" in tail:
            print(tail.strip().splitlines()[-1])
            return
        if p.poll() is not None:
            raise SystemExit("the serf app exited:\n" + tail)
    print("the serf app is still starting; see", i.dir / "serf.log")


def busy() -> str | None:
    """What the serf is doing, if anything but following or standing."""
    try:
        d = asyncio.run(_rcon(op="list"))
    except Exception:  # noqa: BLE001
        return None
    for a in d.get("agents") or []:
        job = a.get("job")
        if a.get("name") == "serf" and job and "follow" not in str(job):
            return str(job)
    return None


def up(save: str | None) -> None:
    if save:
        src = Path(save).expanduser()
        if not src.exists():
            src = SAVES / (save if save.endswith(".zip") else save + ".zip")
    else:
        src = max(SAVES.glob("*.zip"), key=lambda p: p.stat().st_mtime)
    if not src.exists():
        raise SystemExit(f"no save {src}")
    i = inst()
    if i.running():
        n = online()
        if n:
            raise SystemExit(f"{n} player(s) on slot {SLOT}: restarting would kick them")
        stop_serf()
        i.stop()
    WORLDS.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d-%H%M", time.localtime(src.stat().st_mtime))
    name = "user-" + stamp + "-" + re.sub(r"[^a-z0-9]+", "-", src.stem.lower()).strip("-")
    copy = WORLDS / f"{name}.zip"
    shutil.copy2(src, copy)  # the player's file is only read
    print(f"world: {src.name} ({time.strftime('%m-%d %H:%M', time.localtime(src.stat().st_mtime))}) -> {copy.name}")
    i = Instance(SLOT, copy, mods="live")
    i.start(300)
    print(f"slot {SLOT} up (biters removed: {getattr(i, 'biters_removed', '?')}); join localhost:{i.game_port}")
    start_serf(None)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("up")
    u.add_argument("save", nargs="?")
    s = sub.add_parser("serf")
    s.add_argument("--note")
    s.add_argument("--force", action="store_true")
    sub.add_parser("status")
    a = ap.parse_args()
    if a.cmd == "up":
        up(a.save)
    elif a.cmd == "serf":
        if not inst().running():
            raise SystemExit(f"slot {SLOT} isn't running: live_session.py up")
        job = busy()
        if job and not a.force:
            raise SystemExit(f"the serf is busy ({job}); --force to restart anyway")
        stop_serf()
        start_serf(a.note)
    else:
        i = inst()
        print(f"slot {SLOT}: {'running' if i.running() else 'stopped'}; serf app: "
              f"{'running pid ' + str(serf_pid()) if serf_pid() else 'stopped'}")
        if i.running():
            print(f"players online: {online()}; serf job: {busy() or 'none'}")


if __name__ == "__main__":
    main()
