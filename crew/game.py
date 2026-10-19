"""Connection to the game: one link (RCON for a server operator, localhost UDP for a player's own app), a poller
that fans out chat/results/events, and futures for job results so tools can block on "walk there and mine 20 iron"."""
from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from typing import Awaitable, Callable

from .rcon import Crew, GameError, Rcon, RconError
from .udp import UdpCrew

log = logging.getLogger("crew.game")

POLL_SECS = 0.4


class GameLink:
    def __init__(self, host: str, port: int, password: str, transport: str = "rcon", udp_port: int = 27200,
                 client: str = "rcon", hosts: bool = False):
        if transport == "udp":
            self.rcon = None
            self.api = UdpCrew(udp_port)
            self.where = f"UDP port {udp_port} (Factorio's --enable-lua-udp)"
        else:
            self.rcon = Rcon(host, port, password)
            self.api = Crew(self.rcon)
            self.where = f"RCON {host}:{port}"
        # Who we are to the mod: RCON names itself; over UDP the mod knows us by player. `hosts`: take
        # /serf add from players who don't run their own app.
        self.poll_args = {"hosts": hosts} | ({"client": client} if transport != "udp" else {})
        self.client: str | None = None  # as the mod knows us (from poll)
        self.you: str | None = None  # the player whose game we're attached to (UDP)
        self.on_chat: list[Callable[[dict], Awaitable[None]]] = []
        self.on_result: list[Callable[[str, dict, bool], Awaitable[None]]] = []  # (agent, result, claimed)
        self.on_event: list[Callable[[dict], Awaitable[None]]] = []
        self._waiters: dict[int, asyncio.Future] = {}
        self._recent: OrderedDict[int, dict] = OrderedDict()  # results that arrived before anyone waited
        self.connected = asyncio.Event()
        self.tick = 0
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        await self._connect()
        self._task = asyncio.create_task(self._poll_loop(), name="game-poll")

    async def _connect(self) -> None:
        delay = 1.0
        while True:
            try:
                await self.api.connect()
                ping = await self.api.call("ping")
                if not ping.get("version"):
                    raise GameError("claude-crew mod is not loaded in this game")
                log.info("connected to game, mod %s, tick %s", ping["version"], ping["pong"])
                self.connected.set()
                return
            except (OSError, RconError, asyncio.TimeoutError) as e:
                log.warning("can't reach the game over %s (%s); retrying in %.0fs", self.where, e, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 15)

    async def call(self, op: str, **kw):
        try:
            return await self.api.call(op, **kw)
        except RconError:
            self.connected.clear()
            raise

    async def _poll_loop(self) -> None:
        while True:
            try:
                if not self.connected.is_set():
                    await self.api.close()
                    await self._connect()
                data = await self.api.call("poll", **self.poll_args)
                self.tick = data.get("tick", self.tick)
                self.client, self.you = data.get("client", self.client), data.get("you", self.you)
                for msg in data.get("chat") or []:
                    for cb in self.on_chat:
                        await cb(msg)
                for agent, results in (data.get("results") or {}).items():
                    for r in results:
                        r["agent"] = agent
                        fut = self._waiters.pop(r["id"], None)
                        claimed = bool(fut and not fut.done())
                        if claimed:
                            fut.set_result(r)
                        # Keep every result: a wait that timed out leaves no one holding the future, and the
                        # next wait on that job must still resolve instead of sitting out its timeout.
                        self._recent[r["id"]] = r
                        while len(self._recent) > 1000:
                            self._recent.popitem(last=False)
                        for cb in self.on_result:
                            await cb(agent, r, claimed)
                for ev in data.get("events") or []:
                    for cb in self.on_event:
                        await cb(ev)
            except RconError as e:
                log.warning("lost game connection: %s", e)
                self.connected.clear()
            except GameError as e:
                log.error("poll failed: %s", e)
            except Exception:
                log.exception("poll loop error")
            await asyncio.sleep(POLL_SECS)

    def job_future(self, job_id: int) -> asyncio.Future:
        if job_id in self._recent:
            fut = asyncio.get_running_loop().create_future()
            fut.set_result(self._recent[job_id])
            return fut
        fut = self._waiters.get(job_id)
        if not fut:
            fut = asyncio.get_running_loop().create_future()
            self._waiters[job_id] = fut
        return fut

    def forget(self, job_ids) -> None:
        for i in job_ids:
            self._waiters.pop(i, None)
