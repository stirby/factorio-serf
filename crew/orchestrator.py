"""Wires the game link, the chat router, the board and the agents together."""
from __future__ import annotations

import asyncio
import json
import time
import logging

from . import ui
from . import progress
from .agent import Agent, model_label
from .board import Board
from .foreman import Foreman
from . import config as config_mod
from .config import AgentConfig, CrewConfig
from .game import GameLink
from .rcon import GameError
from .router import route

log = logging.getLogger("crew")
CHECK_EVERY = 20  # seconds between task check evaluations
CHECK_HOLD = 120  # a task's done_when must hold this long


class Orchestrator:
    def __init__(self, cfg: CrewConfig):
        self.cfg = cfg
        cfg.state_dir.mkdir(parents=True, exist_ok=True)
        self.link = GameLink(cfg.server.host, cfg.server.rcon_port, cfg.server.rcon_password)
        self.board = Board(cfg.state_dir / "board.json")
        self.agents: dict[str, Agent] = {}
        self.foreman: str | None = cfg.foreman_name()
        self.foreman_brain: Foreman | None = Foreman(cfg.foreman, self) if cfg.foreman else None
        self.spend: list[tuple[float, float]] = []  # (time, usd) per finished turn, every model

    def record_spend(self, usd: float) -> None:
        if usd:
            self.spend.append((time.time(), usd))

    def spent_last_hour(self) -> float:
        cutoff = time.time() - 3600
        self.spend = [s for s in self.spend if s[0] > cutoff]
        return sum(u for _, u in self.spend)

    def spend_ok(self) -> bool:
        cap = self.cfg.usd_per_hour
        return not cap or self.spent_last_hour() < cap

    async def start(self) -> None:
        ui.info(f"connecting to {self.cfg.server.host}:{self.cfg.server.rcon_port} ...")
        await self.link.start()
        self.link.on_chat.append(self._on_chat)
        self.link.on_result.append(self._on_result)
        self.link.on_event.append(self._on_event)
        for ac in self.cfg.agents:
            await self._add_agent(ac)
        names = ", ".join(self.agents)
        if self.foreman_brain:
            await self.foreman_brain.start()
            fm = self.foreman_brain.cfg
            ui.info(f"foreman {fm.name} ({fm.model}, effort {fm.effort}) leads; workers ask it with ask_foreman")
        ui.info(f"crew ready: {names}. Talk to them in game chat: @{next(iter(self.agents))} ..., @all ...")
        hello = self.agents.get(self.foreman or "") or next(iter(self.agents.values()))
        try:
            await self.link.call("brand", title=self.cfg.panel_title(), kind=self.cfg.kind)
            if len(self.agents) == 1 and not self.foreman_brain:
                text = (f"{hello.name} online ({self.cfg.panel_title()}, {model_label(hello.cfg.model)}). "
                        f"Talk to me with @{hello.name}.")
            else:
                text = f"Claude Crew online ({names}). Address us with @name or @all."
            await self.link.call("say", agent=hello.name, text=text)
        except GameError:
            pass
        if self.cfg.source:
            asyncio.create_task(self._watch_config(), name="config-watch")
        asyncio.create_task(progress.metrics_loop(self.link.call, self.cfg.state_dir / "metrics.jsonl"),
                            name="metrics")
        asyncio.create_task(self._alert_watch(), name="alerts")
        asyncio.create_task(self._idle_sweep(), name="idle-sweep")
        asyncio.create_task(self._task_checks(), name="task-checks")

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
        if self.foreman_brain:
            await self.foreman_brain.close()

    async def announce(self, speaker: str, text: str) -> None:
        """Chat line from someone without a character (the foreman)."""
        safe = text.replace("]==]", "] ==]")[:600]
        try:
            await self.link.call("eval", code=f"game.print({{'', '[color=1,0.8,0.3]{speaker}[/color]: ' .. [==[{safe}]==]}})")
        except GameError as e:
            log.warning("announce failed: %s", e)
        for agent in self.agents.values():
            agent.hear(f'{speaker} (foreman, chat): "{text}"', wake=False)

    # ------------------------------------------------------------------ routing
    async def _on_chat(self, msg: dict) -> None:
        text, player = msg.get("message", ""), msg.get("player", "?")
        ui.human(player, text)
        fm = self.foreman_brain
        r = route(text, list(self.agents) + ([fm.name] if fm else []), self.foreman)
        line = f'{player} (at {msg.get("position")}): "{text}"'
        if fm and r.targets and not r.stop and not r.direct and set(r.targets) >= set(self.agents):
            # "@all fix our iron" / "bots, ...": a crew-wide order goes to the lead, who assigns it; workers see it.
            r.targets = {fm.name}
        if fm:
            if fm.name in r.targets:
                r.targets.discard(fm.name)
                fm.human(player, text)
            elif r.targets:
                fm.note(f"(chat to {', '.join(sorted(r.targets))}) {player}: \"{text}\"")
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
        for name, agent in self.agents.items():
            agent.hear(line, wake=name in r.targets)

    def agent_said(self, speaker: str, text: str) -> None:
        fm = self.foreman_brain
        r = route(text, [n for n in self.agents] + ([fm.name] if fm else []), self.foreman)
        if fm and fm.name in r.targets:
            r.targets.discard(fm.name)
            fm.ask(speaker, text)
        elif fm:
            fm.note(f'{speaker} said in chat: "{text}"')
        for name, agent in self.agents.items():
            if name == speaker:
                continue
            # With a foreman, workers build instead of chatting: crew lines are context, never a wake-up.
            wake = name in r.targets and not fm and agent.allow_peer_wake()
            agent.hear(f'{speaker} (crew): "{text}"', wake=wake, urgent=False)

    async def _idle_sweep(self) -> None:
        """Agents idle for a while get woken with whatever work is open (requests, ghosts, tasks, roadmap)."""
        from .tools import open_work
        while True:
            await asyncio.sleep(30)
            now = time.time()
            for agent in list(self.agents.values()):
                if (agent.in_turn or not agent.inbox.empty() or agent.mode != "idle"
                        or now - agent.idle_since < 90 or now - agent.last_free_wake < 180):
                    continue
                try:
                    work = await open_work(agent)
                except Exception:
                    continue
                if work:
                    agent.last_free_wake = now
                    agent.inbox.put_nowait("(idle check) You've been idle; there's open work. Pick the most valuable "
                                           "item you can do now, tell the crew in one line, and do it.")

    async def _task_checks(self) -> None:
        """Board tasks with done_when: the game evaluates them; done only after the check holds for CHECK_HOLD."""
        while True:
            await asyncio.sleep(CHECK_EVERY)
            for t in self.board.checked():
                try:
                    d = await self.link.call("check", zone=t.zone, conds=t.done_when)
                except GameError:
                    continue
                now = time.time()
                held = t.check.get("held_since") if d.get("passed") else None
                if d.get("passed") and not held:
                    held = now
                t.check = {"passed": bool(d.get("passed")), "results": d.get("results") or [], "held_since": held,
                           "at": now}
                bad = [r["impossible"] for r in t.check["results"] if r.get("impossible")]
                if bad:
                    t.status = "blocked"
                    t.notes.append(f"check: can't pass ({'; '.join(bad)}); the check needs fixing")
                    self._tell_lead(f"task #{t.id} '{t.title}': its check can't pass ({'; '.join(bad)}). "
                                    "Fix done_when (or add scope: base).")
                elif held and now - held >= CHECK_HOLD:
                    t.status = "done"
                    t.notes.append("check: held 2 min, done")
                    ui.info(f"task #{t.id} done (check held): {t.title}")
                    if t.owner in self.agents:
                        self.agents[t.owner].hear(f"(board) task #{t.id} '{t.title}' is DONE: its check held for "
                                                  "2 minutes. Pick your next work.", wake=True, urgent=False)
                    self._tell_lead(f"task #{t.id} '{t.title}' done ({t.owner}): check held 2 min.")
                elif t.status == "verifying" and not d.get("passed") and now - t.updated > CHECK_HOLD:
                    t.status = "claimed"
                    t.notes.append("check: still failing after it was marked done; reopened")
                    if t.owner in self.agents:
                        self.agents[t.owner].hear(f"(board) task #{t.id} '{t.title}' was marked done but its check "
                                                  f"still fails: {json.dumps(t.check['results'])[:300]}. Keep going "
                                                  "or mark it blocked with what's needed.", wake=True, urgent=False)
            self.board.save()

    def worker_idle(self, agent) -> None:
        """A worker ran out of work: the lead should hand it something (rate limited per worker)."""
        now = time.time()
        if now - getattr(agent, "last_idle_report", 0) < 180:
            return
        agent.last_idle_report = now
        self._tell_lead(f"{agent.name} is idle with no task; give it one.", wake=True)

    def _tell_lead(self, text: str, wake: bool = True) -> None:
        if self.foreman_brain:
            self.foreman_brain.note(text, wake=wake)

    def _owner(self, focus: str) -> list:
        """Agents whose domain matches, else the lead, else everyone."""
        hit = [a for a in self.agents.values() if a.cfg.focus == focus]
        if hit:
            return hit
        lead = self.agents.get(self.foreman or "")
        return [lead] if lead else list(self.agents.values())

    async def _alert_watch(self) -> None:
        """Like the game's alert icons: notice outages and starvation and wake whoever owns that domain."""
        last: dict[str, float] = {}
        while True:
            await asyncio.sleep(60)
            try:
                a = await self.link.call("alerts")
            except Exception:
                continue
            p = a.get("problems") or {}
            found = []

            def add(key, focus, text):
                found.append((key, focus, text))

            def where(k):
                at = p[k]["at"]
                return ", ".join(f"[gps={x},{y}]" for x, y in at)
            if "boiler:no_fuel" in p:
                add("boiler", "infrastructure", f"POWER RISK: {p['boiler:no_fuel']['n']} boiler(s) out of fuel at "
                    f"{where('boiler:no_fuel')}. Everything electric stops when steam runs out.")
            low = sum(v["n"] for k, v in p.items() if k.endswith(":no_power") or k.endswith(":low_power"))
            if low >= max(5, 0.1 * (a.get("checked") or 0)):
                k = next(k for k in p if k.endswith("power"))
                add("power", "infrastructure", f"BROWNOUT: {low} machines have no or low power (e.g. {where(k)}). "
                    "Check boiler fuel and steam capacity.")
            nf = p.get("furnace:no_fuel", {}).get("n", 0) + p.get("mining-drill:no_fuel", {}).get("n", 0)
            if nf >= 4:
                k = "furnace:no_fuel" if "furnace:no_fuel" in p else "mining-drill:no_fuel"
                add("fuel", "resources", f"FUEL: {nf} furnaces/drills are out of fuel (e.g. {where(k)}). "
                    "Get coal to them on a belt.")
            starved = p.get("lab:starved", {}).get("n", 0)
            if a.get("labs") and a.get("researching") and starved >= max(2, a["labs"] // 2):
                feed = p.get("assembling-machine:starved")
                add("labs-starved", "production", f"SCIENCE STARVED: {starved} of {a['labs']} labs are missing "
                    f"science packs (e.g. {where('lab:starved')})."
                    + (f" {feed['n']} science assembler(s) lack ingredients (e.g. {where('assembling-machine:starved')}): "
                       "trace their inputs back to the shortage and fix the supply, not the symptom." if feed else
                       " Science production can't keep up: add science assemblers or fix their output."))
            if a.get("labs") and not a.get("researching"):
                add("research", "production", "LABS IDLE: nothing is being researched. Queue research now.")
            now = time.time()
            for key, focus, text in found:
                if now - last.get(key, 0) < 300:
                    continue
                last[key] = now
                ui.info(f"alert: {text}")
                if self.foreman_brain:
                    self.foreman_brain.note(f"(alert, sent to the {focus} owner) {text}")
                for agent in self._owner(focus):
                    agent.wake(f"(alert) {text}", urgent=True)

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
        if self.foreman_brain:
            self.foreman_brain.note(f"MILESTONE DONE ({by}): {goal}")

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
            if self.foreman_brain:
                self.foreman_brain.note(line + ". Re-plan: queue the next research and point the crew at it.",
                                        wake=True)
            planner = self.foreman or next(iter(self.agents), None)
            for name, agent in self.agents.items():
                # Everyone learns about it; the planner gets woken to re-plan.
                agent.hear(line, wake=name == planner, urgent=False)
            return
        a = self.agents.get(ev.get("agent", ""))
        if a:
            ui.info(f"{ev['agent']}: {ev['type']} at {ev.get('position')}")
            a.on_event(ev)
