"""The game link: RCON calls to the mod, a poll loop that turns chat and job results into events, and helpers to run
one action and wait for its result."""
from __future__ import annotations

import asyncio
import logging
import time

from .rcon import Crew, GameError, Rcon, RconError

log = logging.getLogger("jev.game")


class Game:
    def __init__(self, crew: Crew, name: str = "serf", poll_secs: float = 0.25):
        self.crew, self.name, self.poll_secs = crew, name, poll_secs
        self.chat: asyncio.Queue = asyncio.Queue()
        self.events: asyncio.Queue = asyncio.Queue()
        self._waiters: dict[int, asyncio.Future] = {}
        self._results: dict[int, dict] = {}  # results that arrived before anyone waited for them
        self._task: asyncio.Task | None = None
        self.tick = 0
        self.last_poll = 0.0

    @classmethod
    async def connect(cls, host: str, port: int, password: str, name: str = "serf") -> "Game":
        rcon = Rcon(host, port, password)
        await rcon.connect()
        return cls(Crew(rcon), name)

    async def call(self, op: str, timeout: float = 30, **kw):
        return await self.crew.call(op, timeout=timeout, **kw)

    async def start(self, spawn: bool = True, **spawn_args) -> None:
        if spawn:
            await self.call("spawn", name=self.name, client="rcon", **spawn_args)
        await self.call("poll")  # start the feed now: no stale chat
        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except BaseException:
                pass
        try:
            await self.call("cancel", agent=self.name, reason="stopped")
        except Exception:
            pass

    async def _poll_loop(self) -> None:
        while True:
            try:
                d = await self.call("poll", timeout=15)
                self.last_poll = time.time()
                self.tick = d.get("tick", self.tick)
                for c in d.get("chat") or []:
                    await self.chat.put(c)
                for ev in d.get("events") or []:
                    await self.events.put(ev)
                for name, rs in (d.get("results") or {}).items():
                    if name != self.name:
                        continue
                    for r in rs:
                        data = r.pop("data", None)
                        if isinstance(data, dict):
                            for k, v in data.items():
                                r.setdefault(k, v)
                        jid = r.get("id")
                        fut = self._waiters.pop(jid, None)
                        if fut and not fut.done():
                            fut.set_result(r)
                        else:
                            self._results[jid] = r
            except asyncio.CancelledError:
                raise
            except (GameError, RconError, asyncio.TimeoutError) as e:
                log.warning("poll failed: %r", e)
                await asyncio.sleep(1)
            await asyncio.sleep(self.poll_secs)

    # ------------------------------------------------------------------ actions
    async def act(self, actions: list[dict], replace: bool = False) -> list[int]:
        d = await self.call("act", agent=self.name, actions=actions, replace=replace)
        return d.get("job_ids") or []

    async def wait_job(self, jid: int, timeout: float = 300) -> dict:
        if jid in self._results:
            return self._results.pop(jid)
        fut = asyncio.get_running_loop().create_future()
        self._waiters[jid] = fut
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            self._waiters.pop(jid, None)
            return {"id": jid, "ok": False, "msg": f"timed out after {timeout:.0f}s", "timeout": True}

    async def run(self, action: dict, timeout: float = 300, replace: bool = False) -> dict:
        """Queue one action and wait for its result: {ok, msg, ...}."""
        try:
            ids = await self.act([action], replace=replace)
        except GameError as e:
            return {"ok": False, "msg": str(e), "op": action.get("op")}
        if not ids:
            return {"ok": False, "msg": "not queued", "op": action.get("op")}
        return await self.wait_job(ids[0], timeout)

    async def cancel(self, reason: str = "replanned") -> None:
        try:
            await self.call("cancel", agent=self.name, reason=reason)
        except GameError:
            pass

    async def say(self, text: str) -> None:
        try:
            await self.call("say", agent=self.name, text=text[:500])
        except GameError as e:
            log.warning("say failed: %r", e)

    async def status(self, **kw) -> None:
        try:
            await self.call("status", agent=self.name, **kw)
        except GameError:
            pass

    # ------------------------------------------------------------------ reading
    async def me(self) -> dict:
        return await self.call("self", agent=self.name)

    async def scan(self, center=None, radius: int = 24) -> dict:
        kw = {"radius": radius, "agent": self.name}
        if center is not None:
            kw["center"] = list(center)
        return await self.call("scan", timeout=30, **kw)

    async def eval(self, code: str):
        return (await self.call("eval", code=code, timeout=60)).get("result")
