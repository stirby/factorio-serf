"""Live test cases: each order a player gives the serf in a real game, with a save of the world taken the moment it
was given (before the serf did anything) and how it went, so real asks become tests.

A case is a folder <out>/<id>/ holding save.zip and case.json (the order, who asked and where, then one entry per run
of it: outcome, minutes, plans, what the serf said, the player's follow-ups). Over RCON only: the save is the server's
own /server-save, written to the server's saves folder (a copy of the player's world: their own saves are never
touched) and moved here.

    .venv/bin/python -m jev.cli play --rcon 127.0.0.1:27170 --password-file server/instances/70/rcon-password \\
        --capture bench/live_cases
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import time
from pathlib import Path
from typing import Awaitable, Callable


def slug(text: str, n: int = 40) -> str:
    t = re.sub(r"\[[^\]]*\]", "", text.lower())
    t = re.sub(r"@\S+", "", t)
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:n].strip("-") or "order"


class Capture:
    def __init__(self, command: Callable[[str], Awaitable[str]], out: Path, server_saves: Path, world: str = "",
                 log_path: Path | None = None):
        self.command, self.out, self.server_saves = command, Path(out), Path(server_saves)
        self.world, self.log_path = world, log_path
        self.cases: dict[int, Path] = {}

    @staticmethod
    def _write(d: Path, case: dict) -> None:
        (d / "case.json").write_text(json.dumps(case, indent=1, default=str))

    async def order(self, o) -> None:
        """A player's new order: save the world now and write the case."""
        cid = time.strftime("%Y%m%d-%H%M%S") + f"-o{o.id}-" + slug(o.text)
        d = self.out / cid
        d.mkdir(parents=True, exist_ok=True)
        case = {"id": cid, "asked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "t": time.time(), "speaker": o.speaker,
                "order": o.text, "points": o.points, "speaker_at": getattr(o, "speaker_at", None),
                "playbook": o.playbook, "world": self.world, "runs": []}
        name = "live-" + cid.split("-o")[0] + f"-o{o.id}"
        try:
            case["save"], case["save_secs"] = "save.zip", await self._save(name, d / "save.zip")
        except Exception as e:  # noqa: BLE001
            case["save_error"] = repr(e)[:300]
        self.cases[o.id] = d
        self._write(d, case)

    async def _save(self, name: str, to: Path) -> float:
        """/server-save `name`, then move the file to `to` once it has settled; the seconds it took."""
        t0 = time.time()
        await self.command(f"/server-save {name}")
        src = self.server_saves / f"{name}.zip"
        last = -1
        for _ in range(120):  # done when the command returns (saving blocks), but wait for the file to settle
            if src.exists():
                size = src.stat().st_size
                if size == last and size > 0:
                    break
                last = size
            await asyncio.sleep(0.5)
        shutil.move(str(src), to)
        return round(time.time() - t0, 1)

    async def flag(self, speaker: str, note: str, ctx: dict) -> str:
        """A player's "!" line: <out>/flags/<time>-<note>/ with save.zip, flag.json (the note, what the serf was
        doing) and log.jsonl (the last 10 minutes of actor.jsonl). Returns the folder's name."""
        fid = time.strftime("%Y%m%d-%H%M%S") + "-" + slug(note or "flag", 30)
        d = self.out / "flags" / fid
        d.mkdir(parents=True, exist_ok=True)
        rec = {"id": fid, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "t": time.time(), "speaker": speaker,
               "note": note, "world": self.world, **ctx}
        try:
            rec["save"], rec["save_secs"] = "save.zip", await self._save("live-" + fid.split("-", 2)[0] + "-"
                                                                         + fid.split("-", 2)[1] + "-flag", d / "save.zip")
        except Exception as e:  # noqa: BLE001
            rec["save_error"] = repr(e)[:300]
        if self.log_path and self.log_path.exists():
            since = time.time() - 600
            keep = []
            for line in self.log_path.read_text(errors="ignore").splitlines()[-20000:]:
                try:
                    if json.loads(line).get("t", 0) >= since:
                        keep.append(line)
                except ValueError:
                    continue
            (d / "log.jsonl").write_text("\n".join(keep) + "\n")
        (d / "flag.json").write_text(json.dumps(rec, indent=1, default=str))
        return fid

    def _said(self, since: float) -> list[str]:
        out: list[str] = []
        if not (self.log_path and self.log_path.exists()):
            return out
        for line in self.log_path.read_text(errors="ignore").splitlines()[-5000:]:
            if '"kind": "say"' not in line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("t", 0) >= since:
                out.append(str(r.get("text", ""))[:400])
        return out

    async def end(self, o, secs: float) -> None:
        """The order ended (again, if a player reopened it): one more run in its case."""
        d = self.cases.get(o.id)
        if not d:
            return
        try:
            case = json.loads((d / "case.json").read_text())
        except (OSError, ValueError):
            return
        since = case["runs"][-1]["t"] if case.get("runs") else case.get("t", 0)
        case["runs"].append({"t": time.time(), "ended_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "status": o.status,
                             "minutes": round(secs / 60, 1), "plans": o.plans, "reopened": o.reopened,
                             "notes": list(o.notes), "said": self._said(since)[-15:],
                             "last_report": o.history[-1][:800] if o.history else None})
        self._write(d, case)
