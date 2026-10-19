"""Actors: a character plus a small, fast model that is called only for judgement (docs/architecture.md).

An actor owns one order at a time. The controller (crew/controller.py) does the physical work; the actor's model
is called, each time with a fresh context, only to start a free-text `task` order, to resolve an exception the
controller couldn't clear (2 attempts, then the order is blocked and goes back to the coordinator), or to answer
a human who talks to it. Checks are evaluated by the game (`check`), never by the model.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING

from . import ui
from .agent import Agent
from .backends import make_backend
from .controller import Controller
from .rcon import GameError
from .tools import BY_NAME

if TYPE_CHECKING:
    from .orders import Order

MODEL_ATTEMPTS = 2
VERIFY_TRIES = 8        # re-checks (15 s apart) for checks that need machines to start up
ACTOR_STEPS = 14

SYSTEM = """You are {name}, one of the crew's hands in a live multiplayer Factorio 2.0 game (Space Age installed),
playing alongside humans. A deterministic controller does your physical work: it lays the order's plan as ghosts,
fetches items from chests, crafts, walks, clears marked trees and rocks, refuels burners and builds ghosts. You are
called only when judgement is needed:
- to start a small free-text `task` order (turn it into connector ghosts or a few actions, inside the zone);
- to resolve an exception the controller couldn't clear (it tells you exactly what's stuck);
- to answer a human who talks to you.

Rules:
- Stay inside your order: its zone, its purpose. You may lay or fix connectors (belts, pipes, poles, inserters, a
  chest), move or rotate a misplaced piece, fetch or craft items, mine a blocker. You never lay out a production
  block, change research, or touch builds outside the zone (unless the order says so).
- Be brief: a handful of tool calls, then one line saying what you did or exactly what blocks you (item counts,
  a location). If it can't be solved inside the order, say what's needed; the coordinator handles it.
- Humans outrank everyone; answer them in one or two short lines with `say`.

Game facts: inserters take from the side they face and drop on the opposite side; belts move items toward their
direction; drills drop one tile in front; 1x1 and 3x3 entities sit at .5 centers, 2x2 at integer corners.
`act` op `blueprint entities=[...]` lays ghosts the controller will build; op `connect` routes a belt/pipe/pole line.
"""

ACTOR_TOOLS = ["look", "map", "find", "inspect", "recipes", "act", "say", "marks", "diagnose"]


class Actor(Agent):
    is_actor = True

    def __init__(self, cfg, orch):
        super().__init__(cfg, orch)
        tools = [BY_NAME[n] for n in ACTOR_TOOLS if n in BY_NAME]
        self.backend = make_backend(self, SYSTEM.format(name=cfg.name), self.dir / "cwd", tools,
                                    max_steps=ACTOR_STEPS)
        self.order: "Order | None" = None
        self._order_task: asyncio.Task | None = None
        self._chat_task: asyncio.Task | None = None
        self.paused_until = 0.0
        self.position = None
        self.messages: list[str] = []  # recent lines from the foreman/crew, given to the next model call

    # ------------------------------------------------------------------ scheduler interface
    def available(self) -> bool:
        return time.time() >= self.paused_until and not self.retired

    def distance_to(self, c) -> float:
        if not c or not self.position:
            return 1e9
        return abs(self.position[0] - c[0]) + abs(self.position[1] - c[1])

    def assign(self, order: "Order") -> None:
        self.order = order
        self.mode, self.idle_since = "working", time.time()
        self._order_task = asyncio.create_task(self._run_order(order), name=f"order-{order.id}-{self.name}")

    def stop_order(self, why: str) -> None:
        """A human said stop: drop the order back to ready and stand still for two minutes."""
        if self._order_task and not self._order_task.done():
            self._order_task.cancel()
        o = self.order
        if o and o.status == "active":
            o.status, o.owner = "ready", None
            o.log(f"stopped by {why}; back to ready")
            self.orch.book.save()
        self.order = None
        self.paused_until = time.time() + 120
        self.mode = "idle"

    # ------------------------------------------------------------------ inputs (orchestrator calls these)
    def hear(self, line: str, wake: bool, urgent: bool = True) -> None:
        if wake and urgent:  # a human talking to this actor
            if not (self._chat_task and not self._chat_task.done()):
                self._chat_task = asyncio.create_task(self._answer(line), name=f"chat-{self.name}")
            return
        self.messages.append(line)
        del self.messages[:-8]

    def wake(self, event: str, urgent: bool = True) -> None:
        self.hear(event, wake=True, urgent=urgent and not event.startswith("("))

    def nudge(self, event: str) -> None:
        pass

    async def _loop(self) -> None:
        while True:  # actors are driven by assign() and hear(); keep the inbox from growing
            await self.inbox.get()

    # ------------------------------------------------------------------ the order
    def _progress(self, **kw) -> None:
        if self.order:
            self.order.progress.update(kw)

    async def _set_status(self, text: str, mode: str = "working") -> None:
        try:
            await self.set_status(text, mode)
        except GameError:
            pass

    async def _run_order(self, o: "Order") -> None:
        ctl = Controller(self.link, self.name, self._progress)
        o.log(f"{self.name} started")
        await self._set_status(f"#{o.id} {o.title}"[:80])
        state_dir = self.orch.cfg.state_dir
        o.state_dir = state_dir  # for paste plans (not saved)
        exception = None
        try:
            if o.plan.get("kind") == "task":
                await self._model(o, "start", f"Start this order. Turn it into connector ghosts (act blueprint "
                                              f"entities=[...]) or a few actions, inside the zone.\n\n{o.card()}",
                                  await self._snapshot(o))
            for attempt in range(MODEL_ATTEMPTS + 1):
                out = await (ctl.connect(o) if o.plan.get("kind") == "connect" else ctl.fulfill(o))
                if out.ok:
                    passed, results = await self._verify(o)
                    if passed:
                        o.status, o.result = "done", f"{out.detail}; check passed {json.dumps(results)}"[:300]
                        break
                    bad = [r["impossible"] for r in results if r.get("impossible")]
                    if bad:  # the coordinator's check can't be met: send it back now, no retries or model calls
                        o.status = "blocked"
                        o.result = f"work done, but the check can't pass: {'; '.join(bad)}. Fix the check (or scope: base)"
                        o.blocker = {"detail": o.result, "results": results}
                        break
                    exception = f"the work is finished but the check fails: {json.dumps(results)}"
                else:
                    exception = out.detail + (f"\nblocker: {json.dumps(out.blocker)[:800]}" if out.blocker else "")
                o.blocker = {"detail": exception}
                if attempt >= MODEL_ATTEMPTS:
                    o.status, o.result = "blocked", exception.splitlines()[0][:300]
                    break
                o.attempts += 1
                await self._model(o, "exception", f"The controller is stuck on your order and needs you.\n\n"
                                                  f"{o.card()}\n\nWhat's wrong: {exception}\n\nFix it inside the "
                                                  "order (fetch/craft/mine/move/rotate/lay connector ghosts), then "
                                                  "stop; the controller will retry. If it can't be fixed inside the "
                                                  "order, say exactly what's needed.", await self._snapshot(o))
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - a crashed order must not kill the actor
            o.status, o.result = "blocked", f"controller error: {e!r}"[:300]
            o.blocker = {"detail": o.result}
        o.finished = time.time()
        o.log(f"{o.status}: {o.result[:120]}")
        self.order, self.mode, self.idle_since = None, "idle", time.time()
        try:
            me = await self.link.call("self", agent=self.name)
            self.position = me.get("position")
        except GameError:
            pass
        if o.status == "done":
            await self._say(f"done #{o.id} {o.title}" + (f" ({o.progress.get('built')} built)"
                                                        if o.progress.get("built") else ""))
        else:
            await self._say(f"blocked on #{o.id} {o.title}: {o.result[:120]}")
        await self._set_status(f"idle (last: #{o.id} {o.status})", "idle")
        self.orch.scheduler.order_finished(o)

    async def _verify(self, o: "Order") -> tuple[bool, list]:
        if not o.done_when:
            return True, []
        results: list = []
        for i in range(VERIFY_TRIES):
            d = await self.link.call("check", zone=o.zone, conds=o.done_when)
            results = d.get("results") or []
            if d.get("passed"):
                return True, results
            if any(r.get("impossible") for r in results):
                break  # the check itself is wrong; waiting or retrying won't help
            if all(r.get("check") == "ghosts_cleared" for r in results if not r.get("ok")):
                break  # unbuilt ghosts won't fix themselves by waiting
            await asyncio.sleep(15)
        return False, results

    async def _snapshot(self, o: "Order | None") -> str:
        parts = []
        try:
            me = await self.link.call("self", agent=self.name)
            self.position = me.get("position")
            parts.append(f"[you] at {me.get('position')}, inventory {json.dumps(me.get('inventory'))}")
            if o and o.zone:
                z = await self.link.call("zone", zone=o.zone)
                parts.append(f"[zone now] {z.get('ghosts')} ghosts left {json.dumps(z.get('by_name'))}; "
                             f"blockers {len(z.get('blockers') or [])}; low fuel {len(z.get('low_fuel') or [])}")
        except GameError as e:
            parts.append(f"(snapshot failed: {e})")
        if self.messages:
            parts.append("[recent messages]\n" + "\n".join(self.messages[-5:]))
        return "\n".join(parts)

    async def _model(self, o: "Order | None", why: str, prompt: str, snapshot: str) -> str:
        """One stateless model call."""
        await self.backend.reset()
        self.in_turn = True
        self._last_text = ""
        t0 = time.time()
        if o:
            o.model_calls += 1
            o.log(f"model call: {why}")
        try:
            stats = await self.backend.turn(prompt + "\n\n" + snapshot)
        except Exception as e:  # noqa: BLE001
            ui.info(f"{self.name}: model call failed ({e!r})")
            return ""
        finally:
            self.in_turn = False
        self.total_cost += stats.cost_usd
        self.orch.record_spend(stats.cost_usd)
        self._record("turn", secs=round(time.time() - t0, 1), steps=stats.steps, cost=stats.cost_usd,
                     input_tokens=stats.input_tokens, output_tokens=stats.output_tokens, error=stats.error, why=why)
        ui.turn_end(self.name, time.time() - t0, stats, self.total_cost)
        return getattr(self, "_last_text", "")

    def log_thought(self, text: str) -> None:
        super().log_thought(text)
        self._last_text = text

    async def _say(self, text: str) -> None:
        try:
            await self.link.call("say", agent=self.name, text=text)
            ui.chat(self.name, text)
        except GameError:
            pass

    async def _answer(self, line: str) -> None:
        card = self.order.card() if self.order else "no order right now (waiting for the next one)"
        await self._model(None, "chat", f"A human is talking to you: {line}\nAnswer with `say` in one or two short "
                                        f"lines (do what they ask if it's quick and inside your scope).\n\n[your "
                                        f"current order]\n{card}", await self._snapshot(self.order))
