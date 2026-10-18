"""One crew member: an event inbox, a model backend, and the glue that keeps it responsive."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from typing import TYPE_CHECKING

from . import ui
from .backends import make_backend
from .config import AgentConfig
from .prompt import briefing, system_prompt

if TYPE_CHECKING:
    from .orchestrator import Orchestrator

log = logging.getLogger("crew.agent")

CONTEXT_RESET_TOKENS = 80_000  # average context per step that triggers a fresh session


class Agent:
    def __init__(self, cfg: AgentConfig, orch: "Orchestrator"):
        self.cfg = cfg
        self.name = cfg.name
        self.orch = orch
        self.link = orch.link
        self.board = orch.board
        self.dir = orch.cfg.state_dir / "agents" / cfg.name
        self.dir.mkdir(parents=True, exist_ok=True)
        self.transcript = (self.dir / "transcript.jsonl").open("a")
        self.notes = (self.dir / "notes.md").read_text() if (self.dir / "notes.md").exists() else ""
        self.status_text = ""
        self.mode = "idle"
        self.inbox: asyncio.Queue[str] = asyncio.Queue()
        self.interrupted = asyncio.Event()
        self._interrupts: list[str] = []
        self.ambient: list[str] = []
        self.pending_jobs: set[int] = set()
        self.finished: dict[int, dict] = {}
        self.in_turn = False
        self.mode_set_this_turn = False
        self.autonomous = 0
        self.turn_times: deque[float] = deque()
        self.peer_wakes: deque[float] = deque()
        self.last_position = None
        self.total_cost = 0.0
        self.error_streak = 0
        self.idle_since = time.time()
        self.last_free_wake = 0.0
        self.retired = False
        self.fresh = False
        self.last_vitals = 0.0
        from .tools import CONSULT, TOOLS
        tools = list(TOOLS)
        if not orch.cfg.flag("work_tool"):
            tools = [t for t in tools if t.name != "work"]
        consult = bool(orch.advisor and (orch.cfg.advisor_for == "all" or cfg.role == "foreman"))
        if consult:
            tools.append(CONSULT)
        fm = getattr(orch, "foreman_brain", None)
        if fm:
            from .foreman import ASK_FOREMAN
            tools.append(ASK_FOREMAN)
        self.backend = make_backend(self, system_prompt(cfg.name, cfg.role, cfg.personality,
                                                        orch.advisor.name if consult else None, cfg.focus,
                                                        orch.cfg.flags, foreman=fm.name if fm else None),
                                    self.dir / "cwd", tools)
        self._task: asyncio.Task | None = None

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        await self.backend.start()
        self._task = asyncio.create_task(self._loop(), name=f"agent-{self.name}")

    async def apply(self, cfg: AgentConfig) -> list[str]:
        """Live config change. Returns what changed."""
        changed = []
        if cfg.model != self.cfg.model:
            await self.backend.set_model(cfg.model)
            changed.append(f"model {self.cfg.model} -> {cfg.model}")
        for field in ("max_turns_per_hour", "max_autonomous_turns", "effort", "role", "personality"):
            if getattr(cfg, field) != getattr(self.cfg, field):
                changed.append(f"{field} -> {getattr(cfg, field)}")
        if cfg.backend != self.cfg.backend:
            changed.append("backend change needs a restart (ignored)")
            cfg.backend = self.cfg.backend
        self.cfg = cfg  # role/personality are baked into the running session's prompt; they apply on restart
        return changed

    async def close(self) -> None:
        if self._task:
            self._task.cancel()
        await self.backend.close()
        self.transcript.close()

    def crew_names(self) -> list[str]:
        return list(self.orch.agents)

    # ------------------------------------------------------------------ inputs
    def wake(self, event: str, urgent: bool = True) -> None:
        """Start a turn, or if one is running, surface the event in the next tool result.
        Urgent events (humans) also cut a blocking act/wait short."""
        if self.in_turn:
            self._interrupts.append(("!" if urgent else "") + event)
            if urgent:
                self.interrupted.set()
        else:
            self.inbox.put_nowait(event)

    def hear(self, line: str, wake: bool, urgent: bool = True) -> None:
        if wake:
            self.wake(line, urgent)
        else:
            self.ambient.append(line)
            del self.ambient[:-30]

    def nudge(self, event: str) -> None:
        """Delayed follow-up; skipped if the agent already got busy (e.g. from a task assignment)."""
        if not self.in_turn and self.inbox.empty() and self.mode != "working":
            self.inbox.put_nowait(event)
        elif self.in_turn:
            self._interrupts.append(event)

    def on_result(self, r: dict) -> None:
        if r["id"] not in self.pending_jobs:
            return
        self.finished[r["id"]] = r
        if not self.in_turn:
            self.pending_jobs.discard(r["id"])
            self.finished.pop(r["id"], None)
            status = "OK" if r.get("ok") else "FAILED"
            self.inbox.put_nowait(f"your job #{r['id']} {r['op']} finished: {status} {r.get('msg', '')}")

    def on_event(self, ev: dict) -> None:
        if ev["type"] == "died":
            self.pending_jobs.clear()
            self.wake(f"YOU DIED at {ev.get('position')}. You'll respawn at spawn with an empty inventory; "
                      "your corpse there holds your items.")
        elif ev["type"] == "respawned":
            self.wake(f"you respawned at {ev.get('position')}")

    def drain_interrupts(self) -> str:
        self.interrupted.clear()
        if not self._interrupts:
            return ""
        lines, self._interrupts = self._interrupts, []
        human = [x[1:] for x in lines if x.startswith("!")]
        other = [x for x in lines if not x.startswith("!")]
        out = []
        if human:
            out.append("[NEW for you while you were working -- reply first if a human asked something]")
            out += [f"- {x}" for x in human]
        if other:
            out.append("[crew updates]")
            out += [f"- {x}" for x in other]
        return "\n".join(out)

    # ------------------------------------------------------------------ outputs used by tools
    async def say(self, text: str) -> None:
        await self.link.call("say", agent=self.name, text=text)
        ui.chat(self.name, text)
        self.orch.agent_said(self.name, text)

    async def set_status(self, text: str, mode: str) -> None:
        self.status_text, self.mode, self.mode_set_this_turn = text, mode, True
        try:
            await self.link.call("status", agent=self.name, text=text)
        except Exception:
            pass
        ui.status(self.name, text, mode)

    async def notify_peer(self, name: str, text: str, wake: bool = True) -> None:
        peer = self.orch.agents.get(name)
        if peer:
            peer.hear(f"(crew) {text}", wake=wake, urgent=False)

    def set_notes(self, text: str) -> None:
        self.notes = text.strip()[:4000]
        (self.dir / "notes.md").write_text(self.notes)

    def note_activity(self, text: str) -> None:
        pass

    def allow_peer_wake(self) -> bool:
        """Crew-to-crew wakeups are rate limited so two agents can't ping-pong forever."""
        now = time.time()
        while self.peer_wakes and now - self.peer_wakes[0] > 60:
            self.peer_wakes.popleft()
        if len(self.peer_wakes) >= 4:
            return False
        self.peer_wakes.append(now)
        return True

    # ------------------------------------------------------------------ logging
    def _record(self, kind: str, **kw) -> None:
        self.transcript.write(json.dumps({"t": time.time(), "kind": kind, **kw}, default=str) + "\n")
        self.transcript.flush()

    def log_tool(self, name: str, args: dict) -> None:
        ui.tool(self.name, name, args)
        self._record("tool", name=name, args=args)

    def log_tool_result(self, name: str, out: str) -> None:
        ui.tool_result(self.name, name, out)
        self._record("result", name=name, out=out)

    def log_thought(self, text: str) -> None:
        ui.thought(self.name, text)
        self._record("thought", text=text)

    # ------------------------------------------------------------------ main loop
    def _budget_ok(self) -> bool:
        now = time.time()
        while self.turn_times and now - self.turn_times[0] > 3600:
            self.turn_times.popleft()
        return len(self.turn_times) < self.cfg.max_turns_per_hour

    async def _loop(self) -> None:
        while True:
            first = await self.inbox.get()
            events = [first]
            await asyncio.sleep(0.3)  # let a burst of related events land together
            while not self.inbox.empty():
                events.append(self.inbox.get_nowait())
            if not any(e.startswith("(continue)") for e in events):
                self.autonomous = 0  # something external happened
            leftovers = [f"job #{r['id']} {r['op']} finished: {'OK' if r.get('ok') else 'FAILED'} {r.get('msg', '')}"
                         for r in self.finished.values()]
            self.pending_jobs.difference_update(self.finished)
            self.finished.clear()
            events = leftovers + events

            if not self._budget_ok():
                ui.info(f"{self.name}: hourly turn budget reached; pausing")
                await self.link.call("status", agent=self.name, text="paused: hourly turn budget reached")
                await asyncio.sleep(60)
                self.inbox.put_nowait(first)
                continue
            self.turn_times.append(time.time())

            try:
                from .tools import open_work, vitals_line
                work = await open_work(self)
                if self.orch.cfg.flag("vitals"):
                    v = await vitals_line(self)
                    work = v + ("\n" + work if work else "") if v else work
            except Exception:
                work = ""
            prompt = briefing(self, events, work)
            if self.fresh:
                self.fresh = False
                prompt = ("(Fresh session: your earlier conversation was cleared to keep things fast. Your notes, "
                          "the roadmap and the board below are your memory; check `look`/`board` if unsure.)\n"
                          + prompt)
            self._record("prompt", text=prompt)
            ui.turn_start(self.name, events)
            self.in_turn, self.mode_set_this_turn = True, False
            t0 = time.time()
            try:
                stats = await self.backend.turn(prompt)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.exception("%s turn crashed", self.name)
                stats = None
                ui.info(f"{self.name}: turn failed: {e!r}")
                await asyncio.sleep(5)
            finally:
                self.in_turn = False
            if stats and stats.error == "error_max_turns":
                # A long, productive turn hit the step cap: not a failure. Keep going right away.
                stats.error = None
                self.inbox.put_nowait("(continue) you hit the step limit for one turn; carry on where you left off.")
            if stats and stats.error:
                # Usage limits, API trouble, etc.: back off instead of hammering.
                self.error_streak += 1
                delay = min(60 * 2 ** (self.error_streak - 1), 1800)
                ui.info(f"{self.name}: turn error ({stats.error}); backing off {delay}s")
                self.inbox.put_nowait("(continue) your last turn ended with an error; pick up where you left off.")
                await asyncio.sleep(delay)
            elif stats:
                self.error_streak = 0
            if stats and stats.steps and stats.input_tokens / max(stats.steps, 1) > CONTEXT_RESET_TOKENS:
                # Every step re-reads the whole context; past this size it's mostly cost, not memory.
                self._record("reset", avg_context=round(stats.input_tokens / stats.steps))
                ui.info(f"{self.name}: context ~{stats.input_tokens // stats.steps // 1000}k tokens/step; "
                        "starting a fresh session (notes and board carry over)")
                try:
                    await self.backend.reset()
                    self.fresh = True
                except Exception as e:
                    log.warning("%s: session reset failed: %r", self.name, e)
            if stats:
                self.total_cost += stats.cost_usd
                self._record("turn", secs=round(time.time() - t0, 1), steps=stats.steps, cost=stats.cost_usd,
                             input_tokens=stats.input_tokens, output_tokens=stats.output_tokens, error=stats.error)
                ui.turn_end(self.name, time.time() - t0, stats, self.total_cost)

            # Anything that arrived after the last tool call still needs handling.
            if self._interrupts:
                for x in self._interrupts:
                    self.inbox.put_nowait(x.lstrip("!"))
                self._interrupts.clear()
                self.interrupted.clear()
                continue
            if not self.mode_set_this_turn:
                self.mode = "idle"
            if self.mode == "idle":
                self.idle_since = time.time()
            if self.mode == "working":
                self.autonomous += 1
                if self.autonomous > self.cfg.max_autonomous_turns:
                    await self.set_status("waiting for direction (autonomy limit)", "idle")
                    await self.say("I've been at it a while on my own; pausing until someone gives me direction.")
                    continue
                self.inbox.put_nowait(f"(continue) keep working on: {self.status_text or 'your current task'}. "
                                      "Check results/board, act, and set status idle when done.")
