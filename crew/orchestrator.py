"""Wires the game link, the chat router, the board and the agents together."""
from __future__ import annotations

import asyncio
import logging

from . import ui
from . import progress
from .advisor import Advisor
from .agent import Agent
from .board import Board
from . import config as config_mod
from .config import AgentConfig, CrewConfig
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
        self.foreman: str | None = cfg.foreman_name()
        self.advisor: Advisor | None = Advisor(cfg.advisor, self) if cfg.advisor else None

    async def start(self) -> None:
        ui.info(f"connecting to {self.cfg.server.host}:{self.cfg.server.rcon_port} ...")
        await self.link.start()
        self.link.on_chat.append(self._on_chat)
        self.link.on_result.append(self._on_result)
        self.link.on_event.append(self._on_event)
        for ac in self.cfg.agents:
            await self._add_agent(ac)
        names = ", ".join(self.agents)
        if self.advisor:
            ui.info(f"{self.cfg.advisor_for} can consult {self.advisor.name} ({self.advisor.cfg.model}, "
                    f"effort {self.advisor.cfg.effort})")
        ui.info(f"crew ready: {names}. Talk to them in game chat: @{next(iter(self.agents))} ..., @all ...")
        hello = self.agents[self.foreman or next(iter(self.agents))]
        try:
            await self.link.call("say", agent=hello.name,
                                 text=f"Claude Crew online ({names}). Address us with @name or @all.")
        except GameError:
            pass
        if self.cfg.source:
            asyncio.create_task(self._watch_config(), name="config-watch")
        asyncio.create_task(progress.metrics_loop(self.link.call, self.cfg.state_dir / "metrics.jsonl"),
                            name="metrics")

    async def _add_agent(self, ac: AgentConfig) -> Agent:
        existing = {a["name"]: a for a in (await self.link.call("list"))["agents"]}
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
        await agent.start()
        return agent

    async def _watch_config(self) -> None:
        """Apply crew.toml edits live: models, limits, new agents, removed agents."""
        path = self.cfg.source
        mtime = path.stat().st_mtime
        while True:
            await asyncio.sleep(3)
            try:
                m = path.stat().st_mtime
                if m == mtime:
                    continue
                mtime = m
                new = config_mod.load(path)
            except Exception as e:
                ui.info(f"crew.toml not applied ({e!r}); fix it and save again")
                continue
            wanted = {a.name: a for a in new.agents}
            for name, ac in wanted.items():
                if name in self.agents:
                    for change in await self.agents[name].apply(ac):
                        ui.info(f"{name}: {change}")
                else:
                    agent = await self._add_agent(ac)
                    await agent.say(f"{name} reporting in. What should I work on?")
            for name in [n for n in self.agents if n not in wanted]:
                agent = self.agents.pop(name)
                await agent.close()
                try:
                    await self.link.call("cancel", agent=name, reason="off duty")
                    await self.link.call("status", agent=name, text="off duty")
                except GameError:
                    pass
                ui.info(f"{name}: off duty (character stays in the game)")
            self.cfg.agents = new.agents
            self.foreman = new.foreman_name()

    async def stop(self) -> None:
        for a in self.agents.values():
            await a.close()
        if self.advisor:
            await self.advisor.close()

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
        if r.direct and player != "tester":
            action = ({"op": "follow", "player": player} if r.direct == "follow"
                      else {"op": "move", "player": player, "radius": 3})
            for name in r.targets:
                try:
                    await self.link.call("act", agent=name, actions=[action], replace=True)
                except GameError as e:
                    log.warning("direct %s for %s failed: %s", r.direct, name, e)
            ui.info(f"{', '.join(sorted(r.targets))}: {r.direct} {player} (instant)")
            line += f" [already done for you: you started to {r.direct} {player}; just acknowledge]"
        planner_first = self.foreman in r.targets and len(r.targets) > 1 and not r.stop
        for name, agent in self.agents.items():
            if planner_first and name != self.foreman:
                # Let the foreman plan first; others see the message now and get nudged once the plan exists.
                agent.hear(line, wake=False)
                asyncio.get_running_loop().call_later(20, agent.nudge,
                                                     f"(follow-up) {player} asked the whole crew: \"{text}\". "
                                                     f"Check the board for the foreman's plan and your task.")
            else:
                agent.hear(line, wake=name in r.targets)

    def agent_said(self, speaker: str, text: str) -> None:
        r = route(text, [n for n in self.agents], self.foreman)
        for name, agent in self.agents.items():
            if name == speaker:
                continue
            wake = name in r.targets and agent.allow_peer_wake()
            agent.hear(f'{speaker} (crew): "{text}"', wake=wake, urgent=False)

    async def _snapshot(self, label: str) -> None:
        try:
            e = await progress.snapshot(self.link.call, self.link.rcon.command, label)
            ui.info(f"snapshot {e['save']} ({e.get('research_count')} techs, {e.get('minutes')} game-min)")
        except Exception as ex:
            log.warning("snapshot failed: %r", ex)

    def milestone_done(self, by: str, goal: str) -> None:
        ui.info(f"MILESTONE by {by}: {goal}")
        asyncio.create_task(self._snapshot(f"milestone-{goal}"))
        for name, agent in self.agents.items():
            if name != by:
                agent.hear(f"MILESTONE DONE ({by}): {goal}", wake=False)

    async def _on_result(self, agent: str, r: dict, claimed: bool) -> None:
        a = self.agents.get(agent)
        if a:
            a.on_result(r)

    async def _on_event(self, ev: dict) -> None:
        if ev["type"] == "research_finished":
            unlocks = ", ".join(ev.get("unlocks") or []) or "no new recipes"
            line = f"RESEARCH FINISHED: {ev['tech']} (unlocks: {unlocks})"
            ui.info(line)
            asyncio.create_task(self._snapshot(f"research-{ev['tech']}"))
            planner = self.foreman or next(iter(self.agents), None)
            for name, agent in self.agents.items():
                # Everyone learns about it; the planner gets woken to re-plan.
                agent.hear(line, wake=name == planner, urgent=False)
            return
        a = self.agents.get(ev.get("agent", ""))
        if a:
            ui.info(f"{ev['agent']}: {ev['type']} at {ev.get('position')}")
            a.on_event(ev)
