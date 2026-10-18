"""Wires the game link, the chat router, the board and the agents together."""
from __future__ import annotations

import asyncio
import logging

from . import ui
from .agent import Agent
from .board import Board
from .config import CrewConfig
from .game import GameLink
from .rcon import GameError
from .router import route

log = logging.getLogger("crew")


class Orchestrator:
    def __init__(self, cfg: CrewConfig):
        self.cfg = cfg
        cfg.state_dir.mkdir(parents=True, exist_ok=True)
        self.link = GameLink(cfg.server.host, cfg.server.rcon_port, cfg.server.rcon_password)
        self.board = Board(cfg.state_dir / "board.json")
        self.agents: dict[str, Agent] = {}
        self.foreman: str | None = next((a.name for a in cfg.agents if a.role == "foreman"), None)

    async def start(self) -> None:
        ui.info(f"connecting to {self.cfg.server.host}:{self.cfg.server.rcon_port} ...")
        await self.link.start()
        self.link.on_chat.append(self._on_chat)
        self.link.on_result.append(self._on_result)
        self.link.on_event.append(self._on_event)
        existing = {a["name"]: a for a in (await self.link.call("list"))["agents"]}
        for ac in self.cfg.agents:
            agent = Agent(ac, self)
            self.agents[ac.name] = agent
            kw = {"name": ac.name, "starter_kit": self.cfg.starter_kit}
            if self.cfg.spawn_near:
                kw["near_player"] = self.cfg.spawn_near
            if ac.color:
                kw["color"] = {"r": ac.color[0], "g": ac.color[1], "b": ac.color[2]}
            if ac.name not in existing or not existing[ac.name].get("alive"):
                sp = await self.link.call("spawn", **kw)
                ui.info(f"spawned {ac.name} at {sp['position']} ({ac.backend}, {ac.model})")
            else:
                ui.info(f"{ac.name} already in game at {existing[ac.name].get('position')} ({ac.backend}, {ac.model})")
        for agent in self.agents.values():
            await agent.start()
        names = ", ".join(self.agents)
        ui.info(f"crew ready: {names}. Talk to them in game chat: @{next(iter(self.agents))} ..., @all ...")
        hello = self.agents[self.foreman or next(iter(self.agents))]
        try:
            await self.link.call("say", agent=hello.name,
                                 text=f"Claude Crew online ({names}). Address us with @name or @all.")
        except GameError:
            pass

    async def stop(self) -> None:
        for a in self.agents.values():
            await a.close()

    # ------------------------------------------------------------------ routing
    async def _on_chat(self, msg: dict) -> None:
        text, player = msg.get("message", ""), msg.get("player", "?")
        ui.human(player, text)
        r = route(text, list(self.agents), self.foreman)
        line = f'{player} (at {msg.get("position")}): "{text}"'
        if r.stop:
            for name in r.targets:
                try:
                    await self.link.call("cancel", agent=name, reason=f"{player} said stop")
                except GameError:
                    pass
                self.agents[name].pending_jobs.clear()
            ui.info(f"hard stop for {', '.join(sorted(r.targets))}")
        for name, agent in self.agents.items():
            agent.hear(line, wake=name in r.targets)

    def agent_said(self, speaker: str, text: str) -> None:
        r = route(text, [n for n in self.agents], self.foreman)
        for name, agent in self.agents.items():
            if name == speaker:
                continue
            wake = name in r.targets and agent.allow_peer_wake()
            agent.hear(f'{speaker} (crew): "{text}"', wake=wake, urgent=False)

    async def _on_result(self, agent: str, r: dict, claimed: bool) -> None:
        a = self.agents.get(agent)
        if a:
            a.on_result(r)

    async def _on_event(self, ev: dict) -> None:
        if ev["type"] == "research_finished":
            unlocks = ", ".join(ev.get("unlocks") or []) or "no new recipes"
            line = f"RESEARCH FINISHED: {ev['tech']} (unlocks: {unlocks})"
            ui.info(line)
            planner = self.foreman or next(iter(self.agents), None)
            for name, agent in self.agents.items():
                # Everyone learns about it; the planner gets woken to re-plan.
                agent.hear(line, wake=name == planner, urgent=False)
            return
        a = self.agents.get(ev.get("agent", ""))
        if a:
            ui.info(f"{ev['agent']}: {ev['type']} at {ev.get('position')}")
            a.on_event(ev)
