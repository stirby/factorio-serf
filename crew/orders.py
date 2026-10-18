"""Order graph and scheduler (docs/architecture.md).

The coordinator writes requests and orders; the scheduler (plain code) promotes orders whose dependencies are done
and whose zone is free, hands them to free actors, and tells the coordinator when an order is blocked, when a
request is finished, or when actors sit idle with nothing ready. Actors only report their own order's progress.
State lives in orders.json in the crew's state dir, one file per world.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from . import ui

if TYPE_CHECKING:
    from .orchestrator import Orchestrator

PLAN_KINDS = ("paste", "stamp", "ghosts", "connect", "task")
OPEN = ("pending", "ready", "active")
IDLE_NUDGE_S = 45  # actors idle this long with nothing ready -> wake the coordinator


@dataclass
class Order:
    id: int
    title: str
    plan: dict
    zone: list | None = None
    done_when: list = field(default_factory=list)
    after: list = field(default_factory=list)
    request: int | None = None
    owner_hint: str | None = None
    notes: str = ""
    status: str = "pending"
    owner: str | None = None
    progress: dict = field(default_factory=dict)
    attempts: int = 0
    model_calls: int = 0
    laid: bool = False
    blocker: dict = field(default_factory=dict)
    result: str = ""
    history: list = field(default_factory=list)
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None

    def log(self, text: str) -> None:
        self.history.append(f"{time.strftime('%H:%M:%S')} {text}")
        del self.history[:-20]

    def card(self) -> str:
        """The fixed-shape text an actor's model gets."""
        z = f"x {self.zone[0]}..{self.zone[2]}, y {self.zone[1]}..{self.zone[3]}" if self.zone else "none"
        lines = [f"order #{self.id}" + (f" (request R{self.request})" if self.request else "") + f": {self.title}",
                 f"  plan: {json.dumps(self.plan)}", f"  zone: {z}",
                 f"  done_when: {json.dumps(self.done_when)}"]
        if self.notes:
            lines.append(f"  notes: {self.notes}")
        if self.after:
            lines.append(f"  after: {self.after}")
        return "\n".join(lines)


@dataclass
class Request:
    id: int
    text: str
    by: str = ""
    done_when: list = field(default_factory=list)
    status: str = "open"
    created: float = field(default_factory=time.time)
    finished: float | None = None
    result: str = ""


def _overlap(a, b) -> bool:
    if not a or not b:
        return False
    ax1, ay1, ax2, ay2 = min(a[0], a[2]), min(a[1], a[3]), max(a[0], a[2]), max(a[1], a[3])
    bx1, by1, bx2, by2 = min(b[0], b[2]), min(b[1], b[3]), max(b[0], b[2]), max(b[1], b[3])
    return ax1 < bx2 and bx1 < ax2 and ay1 < by2 and by1 < ay2


class OrderBook:
    def __init__(self, path: Path):
        self.path = path
        self.orders: dict[int, Order] = {}
        self.requests: dict[int, Request] = {}
        self.next_order, self.next_request = 1, 1
        if path.exists():
            d = json.loads(path.read_text())
            for o in d.get("orders", []):
                self.orders[o["id"]] = Order(**o)
            for r in d.get("requests", []):
                self.requests[r["id"]] = Request(**r)
            self.next_order = d.get("next_order", max(self.orders, default=0) + 1)
            self.next_request = d.get("next_request", max(self.requests, default=0) + 1)
            # after a restart nobody is executing anything: active orders go back to ready
            for o in self.orders.values():
                if o.status == "active":
                    o.status, o.owner = "ready", None
                    o.log("requeued after restart")

    def save(self) -> None:
        d = {"next_order": self.next_order, "next_request": self.next_request,
             "orders": [asdict(o) for o in self.orders.values()],
             "requests": [asdict(r) for r in self.requests.values()]}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=1))
        tmp.replace(self.path)

    # ------------------------------------------------------------------ writes (coordinator)
    def add_request(self, text: str, by: str = "", done_when: list | None = None) -> Request:
        r = Request(self.next_request, text, by, done_when or [])
        self.requests[r.id] = r
        self.next_request += 1
        self.save()
        return r

    def add_order(self, title: str, plan: dict, zone=None, done_when=None, after=None, request=None,
                  owner_hint=None, notes="") -> Order:
        kind = (plan or {}).get("kind")
        if kind not in PLAN_KINDS:
            raise ValueError(f"plan.kind must be one of {PLAN_KINDS}")
        if kind in ("paste", "stamp") and not ({"name", "x", "y"} <= set(plan)):
            raise ValueError(f"{kind} plan needs name, x, y")
        if kind == "connect" and not ({"from", "to"} <= set(plan)):
            raise ValueError("connect plan needs from=[x,y], to=[x,y] (and item)")
        if kind in ("paste", "stamp", "ghosts") and not zone:
            raise ValueError(f"a {kind} order needs zone=[x1,y1,x2,y2]")
        if zone is not None:
            if len(zone) != 4:
                raise ValueError("zone is [x1, y1, x2, y2]")
            zone = [float(v) for v in zone]
        for a in after or []:
            if int(a) not in self.orders:
                raise ValueError(f"after: no order #{a}")
        if request is not None and int(request) not in self.requests:
            raise ValueError(f"no request R{request}")
        if not done_when:
            done_when = [{"ghosts_cleared": True}] if kind in ("paste", "stamp", "ghosts") else []
        o = Order(self.next_order, title, plan, zone, done_when, [int(a) for a in after or []],
                  int(request) if request is not None else None, owner_hint, notes)
        o.log("created")
        self.orders[o.id] = o
        self.next_order += 1
        self.save()
        return o

    def cancel(self, oid: int, why: str = "") -> Order:
        o = self.orders[oid]
        o.status = "cancelled"
        o.log(f"cancelled {why}")
        self.save()
        return o

    # ------------------------------------------------------------------ views
    def open_orders(self) -> list[Order]:
        return [o for o in self.orders.values() if o.status in OPEN or o.status == "blocked"]

    def render(self, limit: int = 25) -> str:
        lines = []
        for r in self.requests.values():
            if r.status == "open":
                mine = [o for o in self.orders.values() if o.request == r.id]
                done = sum(o.status == "done" for o in mine)
                lines.append(f"R{r.id} \"{r.text[:80]}\" ({r.by}): {done}/{len(mine)} orders done"
                             + (f", check {json.dumps(r.done_when)}" if r.done_when else ""))
        shown = [o for o in self.orders.values() if o.status not in ("done", "cancelled")]
        recent = sorted((o for o in self.orders.values() if o.status == "done"), key=lambda o: o.finished or 0)[-5:]
        for o in sorted(shown, key=lambda o: o.id)[:limit]:
            prog = f" {o.progress.get('built', 0)} built, {o.progress.get('ghosts_left', '?')} ghosts left" if o.status == "active" else ""
            blk = f" BLOCKED: {o.result}" if o.status == "blocked" else ""
            dep = f" after {o.after}" if o.after and o.status == "pending" else ""
            lines.append(f"#{o.id} [{o.status}{' ' + o.owner if o.owner else ''}] {o.title}{dep}{prog}{blk}")
        for o in recent:
            lines.append(f"#{o.id} [done {o.owner}] {o.title}: {o.result[:100]}")
        return "\n".join(lines) or "no orders yet"


class Scheduler:
    """Promotes, dispatches, and reports. Never calls a model."""

    def __init__(self, orch: "Orchestrator", book: OrderBook):
        self.orch = orch
        self.book = book
        self.idle_since: float | None = None
        self.nudged = 0.0

    def actors(self):
        return [a for a in self.orch.agents.values() if getattr(a, "is_actor", False)]

    def _promote(self) -> None:
        active_zones = [o.zone for o in self.book.orders.values() if o.status == "active"]
        for o in sorted(self.book.orders.values(), key=lambda o: o.id):
            if o.status != "pending":
                continue
            deps = [self.book.orders.get(a) for a in o.after]
            if any(d is None or d.status in ("failed", "cancelled") for d in deps):
                o.status = "blocked"
                o.result = "a dependency failed or was cancelled"
                o.log(o.result)
                self._tell_coordinator(f"order #{o.id} can't start: {o.result}", wake=True)
                continue
            if all(d.status == "done" for d in deps):
                o.status = "ready"
                o.log("ready")

    def _dispatch(self) -> None:
        free = [a for a in self.actors() if a.order is None and a.available()]
        if not free:
            return
        busy_zones = [o.zone for o in self.book.orders.values() if o.status == "active"]
        for o in sorted(self.book.orders.values(), key=lambda o: o.id):
            if o.status != "ready" or not free:
                continue
            if any(_overlap(o.zone, z) for z in busy_zones):
                continue
            pick = next((a for a in free if a.name == o.owner_hint), None)
            if pick is None:
                c = ((o.zone[0] + o.zone[2]) / 2, (o.zone[1] + o.zone[3]) / 2) if o.zone else None
                pick = min(free, key=lambda a: a.distance_to(c)) if c else free[0]
            free.remove(pick)
            busy_zones.append(o.zone)
            o.status, o.owner, o.started = "active", pick.name, time.time()
            o.log(f"dispatched to {pick.name}")
            ui.info(f"order #{o.id} -> {pick.name}: {o.title}")
            pick.assign(o)
        self.book.save()

    def _requests(self) -> None:
        for r in self.book.requests.values():
            if r.status != "open":
                continue
            mine = [o for o in self.book.orders.values() if o.request == r.id]
            if mine and all(o.status in ("done", "cancelled") for o in mine):
                r.status, r.finished = "orders_done", time.time()
                summary = "; ".join(f"#{o.id} {o.title}: {o.result[:80]}" for o in mine if o.status == "done")
                self._tell_coordinator(f"REQUEST R{r.id} \"{r.text}\": all orders done ({summary}). Check the "
                                       "request's goal with data, then report to the human in chat (or add orders "
                                       "if the goal isn't met).", wake=True)
        self.book.save()

    def _idle(self) -> None:
        acts = self.actors()
        idle = [a for a in acts if a.order is None and a.available()]
        ready = [o for o in self.book.orders.values() if o.status in ("ready", "pending")]
        if acts and idle and not ready:
            self.idle_since = self.idle_since or time.time()
            if time.time() - self.idle_since > IDLE_NUDGE_S and time.time() - self.nudged > 240:
                self.nudged = time.time()
                self._tell_coordinator(f"{len(idle)} actor(s) idle with no ready orders: "
                                       f"{', '.join(a.name for a in idle)}. Give them orders.", wake=True)
        else:
            self.idle_since = None

    def _tell_coordinator(self, text: str, wake: bool) -> None:
        fm = self.orch.foreman_brain
        if fm:
            fm.note(text, wake=wake)
        ui.info(f"scheduler: {text[:160]}")

    def order_finished(self, o: Order) -> None:
        """Called by an actor when its order is done or blocked."""
        if o.status == "blocked":
            self._tell_coordinator(f"ORDER #{o.id} BLOCKED ({o.owner}): {o.result}. Blocker: "
                                   f"{json.dumps(o.blocker)[:600]}. Fix the plan (new order, different spot, "
                                   "supply the items) or cancel it.", wake=True)
        self.book.save()

    async def run(self) -> None:
        while True:
            try:
                self._promote()
                self._dispatch()
                self._requests()
                self._idle()
            except Exception as e:  # never let bookkeeping kill the crew
                ui.info(f"scheduler error: {e!r}")
            await asyncio.sleep(3)
