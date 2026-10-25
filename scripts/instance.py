#!/usr/bin/env python3
"""Isolated headless Factorio instances for experiments.

Instance K gets its own write-data dir server/instances/K/ (Factorio locks write-data, so two servers can't
share one), game port 34200+K and RCON 27100+K, both bound to 127.0.0.1, and a random RCON password. The stage
save is *copied* in; the original in server/factorio/saves is never written.

    scripts/instance.py start 1 crew-e2e4      # start instance 1 from that stage; prints host/port/password file
    scripts/instance.py stop 1 | status [K] | log 1

    from scripts.instance import Instance
    with Instance(1, "crew-e2e4") as inst:     # stops on exit, even on exceptions
        print(inst.rcon_port, inst.password)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from jev.peace import biters_off  # noqa: E402
from jev.rcon import Crew, Rcon  # noqa: E402

INSTALL = ROOT / "server/factorio"
BIN = INSTALL / "bin/x64/factorio"
INSTANCES = ROOT / "server/instances"
MOD_SRC = ROOT / "mod/factorio-serf"
GAME_PORT_BASE, RCON_PORT_BASE = 34200, 27100
# The mod's localhost UDP link (--enable-lua-udp), as a player's own serf app uses it. Off by default: in 2.0.77 a
# headless server crashes ("Trying to add invalid input action to the closure") when a Lua UDP packet arrives.
UDP_PORT_BASE = 27300
BENCH_SETTINGS = ROOT / "server/bench-mod-settings.dat"
REQUIRED_MODS = ["base", "space-age", "quality", "elevated-rails", "factorio-serf"]
INGAME = "changing state from(CreatingGame) to(InGame)"


def _run_sync(coro_fn, timeout: float):
    """Run an async function to completion from sync code, even if an event loop is already running here."""
    box: dict = {}

    def target():
        try:
            box["v"] = asyncio.run(asyncio.wait_for(coro_fn(), timeout))
        except BaseException as e:  # noqa: BLE001
            box["e"] = e
    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout + 5)
    if "e" in box:
        raise box["e"]
    if "v" not in box:
        raise TimeoutError("timed out")
    return box["v"]


def _port_free(port: int, kind: int) -> bool:
    s = socket.socket(socket.AF_INET, kind)
    try:
        # TIME_WAIT sockets left by a just-stopped server aren't a real conflict (the server can bind through them).
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


class Instance:
    def __init__(self, k: int, stage: str | Path | None = None, mods: str = "bench", udp: bool = False,
                 biters: bool = False):
        if not 0 <= int(k) < 100:
            raise ValueError("instance id must be 0..99")
        self.k = int(k)
        self.stage = stage
        self.mods = mods  # "bench": pinned vanilla Space Age + the crew mod; "live": the live server's mods too
        self.biters = biters  # True only when the player asks for them (a live session in their world)
        self.dir = INSTANCES / str(self.k)
        self.game_port = GAME_PORT_BASE + self.k
        self.rcon_port = RCON_PORT_BASE + self.k
        self.udp_port = UDP_PORT_BASE + self.k
        self.udp = udp
        self.host = "127.0.0.1"
        self.log = self.dir / "server.log"
        self.pidfile = self.dir / "server.pid"
        self.pwfile = self.dir / "rcon-password"
        self.proc: subprocess.Popen | None = None

    # ------------------------------------------------------------------ info
    @property
    def password(self) -> str:
        return self.pwfile.read_text().strip()

    @property
    def save_path(self) -> Path:
        return self.dir / "saves" / f"{Path(str(self.stage)).stem}.zip"

    def pid(self) -> int | None:
        try:
            pid = int(self.pidfile.read_text().strip())
        except (OSError, ValueError):
            return None
        try:  # only trust the pid if it is still *our* factorio (pids get reused)
            cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        except OSError:
            return None
        return pid if str(self.dir) in cmd and "factorio" in cmd else None

    def running(self) -> bool:
        return self.pid() is not None

    def info(self) -> dict:
        return {"instance": self.k, "running": self.running(), "pid": self.pid(), "dir": str(self.dir),
                "host": self.host, "game_port": self.game_port, "rcon_port": self.rcon_port,
                "password_file": str(self.pwfile), "save": str(self.save_path) if self.stage else None}

    # ------------------------------------------------------------------ setup
    def _stage_source(self) -> Path:
        p = Path(str(self.stage))
        if not p.suffix:
            p = INSTALL / "saves" / f"{p.name}.zip"
        if not p.exists():
            raise FileNotFoundError(f"stage save not found: {p}")
        return p

    def prepare(self) -> None:
        if self.stage is None:
            raise ValueError("no stage save given")
        src = self._stage_source()
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "config").mkdir(exist_ok=True)
        (self.dir / "config/config.ini").write_text(
            f"[path]\nread-data={INSTALL / 'data'}\nwrite-data={self.dir}\n[general]\nlocale=auto\n")
        mods = self.dir / "mods"
        mods.mkdir(exist_ok=True)
        for old in mods.iterdir():  # a previous run's mod links
            if old.is_symlink():
                old.unlink()
        link = mods / "factorio-serf"
        if link.exists():
            link.unlink()
        link.symlink_to(MOD_SRC)
        if self.mods == "live":
            # The user's world needs the user's mods (a copy of their save runs here, never the original).
            live = INSTALL / "mods"
            for z in live.glob("*.zip"):
                (mods / z.name).symlink_to(z)
            ml = json.loads((live / "mod-list.json").read_text())
            ml["mods"] = [m for m in ml["mods"] if m["name"] not in ("claude-crew", "factorio-serf")]
            ml["mods"].append({"name": "factorio-serf", "enabled": True})  # the mod's old name was claude-crew
            (mods / "mod-list.json").write_text(json.dumps(ml, indent=2))
            if (live / "mod-settings.dat").exists():
                shutil.copy2(live / "mod-settings.dat", mods / "mod-settings.dat")
        # Benchmarks run vanilla Space Age + the crew mod, whatever the live server has installed, so results stay
        # comparable when the live server picks up the user's mods.
        if self.mods != "live":
            ml = {"mods": [{"name": n, "enabled": True} for n in REQUIRED_MODS]}
            (mods / "mod-list.json").write_text(json.dumps(ml, indent=2))
            if BENCH_SETTINGS.exists():
                shutil.copy2(BENCH_SETTINGS, mods / "mod-settings.dat")
        saves = self.dir / "saves"
        if saves.exists():
            shutil.rmtree(saves)
        saves.mkdir()
        shutil.copy2(src, self.save_path)  # copy; the stage original is only read
        (self.dir / "server-settings.json").write_text(json.dumps({
            "name": f"Serf bench {self.k}", "description": "experiment instance",
            "visibility": {"public": False, "lan": False}, "require_user_verification": False,
            "max_players": 0, "auto_pause": False, "auto_pause_when_players_connect": False,
            "only_admins_can_pause_the_game": True,
            "autosave_interval": 100000, "autosave_slots": 1, "autosave_only_on_server": True,  # effectively off
            "non_blocking_saving": False, "allow_commands": "admins-only",
        }, indent=2))
        self.pwfile.write_text(secrets.token_urlsafe(18) + "\n")
        self.pwfile.chmod(0o600)

    # ------------------------------------------------------------------ lifecycle
    def start(self, timeout: float = 180) -> "Instance":
        if self.running():
            raise RuntimeError(f"instance {self.k} already running (pid {self.pid()}); stop it first")
        for port, kind, what in ((self.game_port, socket.SOCK_DGRAM, "game"), (self.rcon_port, socket.SOCK_STREAM, "rcon")):
            if not _port_free(port, kind):
                raise RuntimeError(f"{what} port {port} is in use")
        self.prepare()
        cmd = [str(BIN), "-c", str(self.dir / "config/config.ini"),
               "--start-server", str(self.save_path),
               "--server-settings", str(self.dir / "server-settings.json"),
               "--bind", f"127.0.0.1:{self.game_port}",
               "--rcon-bind", f"127.0.0.1:{self.rcon_port}", "--rcon-password", self.password]
        if self.udp:
            cmd += ["--enable-lua-udp", str(self.udp_port)]
        logf = open(self.log, "w")
        self.proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                     cwd=self.dir, start_new_session=True)
        logf.close()
        self.pidfile.write_text(str(self.proc.pid))
        try:
            self.wait_ready(timeout)
            if not self.biters:
                self.biters_removed = self.biters_off()  # every test world runs without biters
        except BaseException:
            self.stop()
            raise
        return self

    def wait_ready(self, timeout: float = 180) -> None:
        deadline = time.time() + timeout
        while True:
            # with our own handle, trust it: right after the spawn /proc/<pid>/cmdline can still show the parent
            # python (before exec), so running() said "exited" while the server was coming up, and it was left running
            dead = self.proc.poll() is not None if self.proc else not self.running()
            if dead:
                raise RuntimeError(f"instance {self.k} exited during startup:\n" + self.tail(25))
            try:
                if INGAME in self.log.read_text(errors="replace"):
                    break
            except OSError:
                pass
            if time.time() > deadline:
                raise TimeoutError(f"instance {self.k} not InGame after {timeout}s:\n" + self.tail(25))
            time.sleep(0.5)
        last = None
        while time.time() < deadline:
            try:
                pong = self.ping()
                if pong.get("version"):
                    return
                last = f"mod not loaded: {pong}"
            except Exception as e:  # noqa: BLE001
                last = repr(e)
            time.sleep(1)
        raise TimeoutError(f"instance {self.k} RCON never answered ping ({last})")

    def ping(self) -> dict:
        async def go():
            r = Rcon(self.host, self.rcon_port, self.password)
            try:
                await r.connect()
                return await Crew(r).call("ping")
            finally:
                await r.close()
        return _run_sync(go, 15)

    def biters_off(self) -> dict:
        async def go():
            r = Rcon(self.host, self.rcon_port, self.password)
            try:
                await r.connect()
                return await biters_off(Crew(r))
            finally:
                await r.close()
        return _run_sync(go, 120)

    def stop(self, timeout: float = 30) -> bool:
        """SIGINT, then SIGTERM, then SIGKILL. Returns True if it was running."""
        pid = self.pid() or (self.proc.pid if self.proc and self.proc.poll() is None else None)
        if pid is None:
            self.pidfile.unlink(missing_ok=True)
            return False
        for sig, wait in ((signal.SIGINT, timeout), (signal.SIGTERM, 10), (signal.SIGKILL, 5)):
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                break
            end = time.time() + wait
            while time.time() < end:
                if self.proc and self.proc.poll() is not None:
                    break
                if not self.proc:
                    try:
                        os.waitpid(pid, os.WNOHANG)
                    except ChildProcessError:
                        pass
                    if self.pid() is None:
                        break
                time.sleep(0.25)
            else:
                continue
            break
        if self.proc:
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                pass
        self.pidfile.unlink(missing_ok=True)
        return True

    def tail(self, n: int = 40) -> str:
        try:
            return "\n".join(self.log.read_text(errors="replace").splitlines()[-n:])
        except OSError:
            return ""

    def __enter__(self) -> "Instance":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()


def stop(k: int) -> bool:
    return Instance(k).stop()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("k", type=int)
    s.add_argument("stage", help="save name in server/factorio/saves (no .zip) or a path")
    s.add_argument("--timeout", type=float, default=180)
    sub.add_parser("stop").add_argument("k", type=int)
    st = sub.add_parser("status")
    st.add_argument("k", type=int, nargs="?")
    lg = sub.add_parser("log")
    lg.add_argument("k", type=int)
    lg.add_argument("-n", type=int, default=40)
    a = p.parse_args()
    if a.cmd == "start":
        inst = Instance(a.k, a.stage).start(a.timeout)
        print(json.dumps(inst.info(), indent=1))
    elif a.cmd == "stop":
        print("stopped" if stop(a.k) else "not running")
    elif a.cmd == "status":
        ks = [a.k] if a.k is not None else sorted(int(d.name) for d in INSTANCES.glob("*") if d.name.isdigit())
        for k in ks:
            print(json.dumps(Instance(k).info()))
    elif a.cmd == "log":
        print(Instance(a.k).tail(a.n))


if __name__ == "__main__":
    main()
