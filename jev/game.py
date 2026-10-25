"""The game link: RCON calls to the mod, a poll loop that turns chat and job results into events, and helpers to run
one action and wait for its result."""
from __future__ import annotations

import asyncio
import logging
import time

from .rcon import Crew, GameError, Rcon, RconError

log = logging.getLogger("jev.game")

# ops that read one surface and take it as `surface` (most default to nauvis): they get the character's own planet
# (live test on Vulcanus: "what's in storage" listed Nauvis's chests, so a prefetch went after drills Vulcanus didn't
# have)
SURFACE_OPS = {"query", "audit", "alerts", "vitals", "ghosts", "blockers", "diagnose", "copy", "paste", "order",
               "network", "find_space", "zone", "sources", "check", "belt_items", "progress", "calc", "tags"}


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
        self.away = False  # a player sent the character away (/serf leave); /serf join brings it back
        self.surface: str | None = None  # the character's planet, from its last self report or hop

    @classmethod
    async def connect(cls, host: str, port: int, password: str, name: str = "serf") -> "Game":
        rcon = Rcon(host, port, password)
        await rcon.connect()
        return cls(Crew(rcon), name)

    async def call(self, op: str, timeout: float = 30, **kw):
        if op in SURFACE_OPS and "surface" not in kw and self.surface:
            kw["surface"] = self.surface
        r = await self.crew.call(op, timeout=timeout, **kw)
        if op == "hop" and isinstance(r, dict) and r.get("surface"):
            self.surface = r["surface"]
        return r

    async def start(self, spawn: bool = True, **spawn_args) -> None:
        """Spawn (or take over) the character. Over RCON pass client="rcon" (the default); over UDP the mod sets
        the client and owner from the packet, so pass nothing."""
        if spawn:
            args = {"client": "rcon", **spawn_args} if not hasattr(self.crew, "port") else dict(spawn_args)
            d = await self.call("spawn", name=self.name, **args)
            self.away = bool(isinstance(d, dict) and d.get("away"))
            if not self.away:
                try:
                    await self.me()  # its planet, for the surface ops
                except Exception:  # noqa: BLE001
                    pass
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

    QUEUE_WAIT = 600.0  # longest an action waits in the mod's queue behind other jobs before giving up
    CRAFT_CAP = 18 * 60.0  # a fetch or craft still crafting runs on past its timeout up to this (the mod stops jobs at 20 min)

    async def run(self, action: dict, timeout: float = 300, replace: bool = False,
                  queue_timeout: float | None = None) -> dict:
        """Queue one action and wait for its result: {ok, msg, ...}.

        The character does one job at a time and several tasks (the plan, keepers, restocks) queue into the same
        mod queue, so an action can wait behind another task's long job (p2: a restock insert waited 240 s behind a
        fetch hand-crafting 557 pipes and was reported as "timed out", though it never started). So `timeout` is how
        long the job may RUN; waiting in the queue counts separately, up to queue_timeout (default max(timeout, 10
        min)). Either way only this job is withdrawn, never the job of whoever is running ahead of it."""
        op = action.get("op")
        try:
            ids = await self.act([action], replace=replace)
        except GameError as e:
            return {"ok": False, "msg": str(e), "op": op}
        if not ids:
            return {"ok": False, "msg": "not queued", "op": op}
        jid = ids[0]
        try:
            return await self._wait_run(jid, op, timeout, queue_timeout)
        except asyncio.CancelledError:
            # our caller was stopped (an order cancelled, a task torn down): withdraw the job, or it runs on in the
            # mod with nobody waiting and everything queued behind it times out
            try:
                await asyncio.shield(self.cancel(f"{op}: its caller stopped", job=jid))
            except Exception:  # noqa: BLE001
                pass
            raise

    async def _wait_run(self, jid: int, op, timeout: float, queue_timeout: float | None) -> dict:
        qcap = queue_timeout if queue_timeout is not None else max(timeout, self.QUEUE_WAIT)
        t0 = time.monotonic()
        ran = None  # how long the mod says our job has been running
        ahead: dict = {}
        last_craft = None  # the crafting queue at the last extension
        while True:
            r = await self.wait_job(jid, min(10.0, max(1.0, timeout)))
            if not r.get("timeout"):
                return r
            st = await self._job_state(jid)
            if st is None:  # couldn't ask; fall back to wall-clock time since queueing
                if time.monotonic() - t0 > qcap + timeout:
                    break
                continue
            if st.get("running"):
                ran = st.get("secs", 0)
                craft = st.get("crafting")
                if ran >= timeout and op in ("fetch", "craft") and craft and craft != last_craft \
                        and ran < self.CRAFT_CAP:
                    # still hand-crafting, and getting on with it since the last look: a long craft isn't stuck
                    # (c1: 110 advanced circuits at 6 s each timed out at 300 s, five times in a row)
                    last_craft = craft
                    timeout = ran + 60
                elif ran >= timeout:
                    await self.cancel(f"{op} timed out", job=jid)
                    return {"id": jid, "ok": False, "op": op, "timeout": True,
                            "msg": f"timed out after {timeout:.0f}s"}
            else:
                ahead = st.get("ahead") or ahead
                if time.monotonic() - t0 >= qcap:
                    await self.cancel(f"{op} waited too long in the queue", job=jid)
                    what = ahead.get("what") or ahead.get("op") or "other jobs"
                    behind = f"job {ahead.get('id')} ({what}, running {ahead.get('secs', '?')}s)" if ahead else what
                    return {"id": jid, "ok": False, "op": op, "timeout": True, "queued": True,
                            "msg": f"timed out after {qcap:.0f}s waiting in the queue: never started, the character was "
                                   f"busy with {behind}" + (f" and {st['queued'] - 1} more queued ahead"
                                                            if st.get("queued", 0) > 1 else "")}
        await self.cancel(f"{op} timed out", job=jid)
        return {"id": jid, "ok": False, "op": op, "timeout": True, "msg": f"timed out after {timeout:.0f}s"}

    async def _job_state(self, jid: int) -> dict | None:
        """Our job running ({running, secs}) or not yet ({ahead: the running job, queued: queue length}); None if the
        mod couldn't be asked."""
        try:
            me = await self.call("self", agent=self.name, timeout=15)
        except (GameError, RconError, asyncio.TimeoutError):
            return None
        job = me.get("job") or {}
        if job.get("id") == jid:
            return {"running": True, "secs": job.get("secs", 0), "crafting": me.get("crafting")}
        return {"running": False, "ahead": job, "queued": me.get("queued", 0)}

    async def cancel(self, reason: str = "replanned", job: int | None = None) -> None:
        """Cancel the character's running job and everything queued, or only `job` (by id)."""
        kw = {"job": job} if job is not None else {}
        try:
            await self.call("cancel", agent=self.name, reason=reason, **kw)
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
        d = await self.call("self", agent=self.name)
        if isinstance(d, dict) and d.get("surface"):
            self.surface = d["surface"]
        return d

    async def scan(self, center=None, radius: int = 24, tiles: bool = False) -> dict:
        kw = {"radius": radius, "agent": self.name}
        if tiles:
            kw["tiles"] = True
        if center is not None:
            kw["center"] = list(center)
        return await self.call("scan", timeout=30, **kw)

    async def eval(self, code: str):
        return (await self.call("eval", code=code, timeout=60)).get("result")
