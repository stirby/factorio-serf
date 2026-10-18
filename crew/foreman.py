"""The foreman: a characterless lead every worker can ask without waiting.

Workers keep building while they ask (`ask_foreman` returns at once); questions queue up and the foreman answers
them in batches with `reply`, which lands in the asker's next tool result. One persistent session, so decisions
stay consistent across the crew. It sees the world through read-only tools (from a worker's position, or any x,y)
and owns the roadmap and the board. It also takes human chat that isn't for one worker, and reviews the base when
research finishes, an alert fires, or nobody has asked anything for a while.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from typing import TYPE_CHECKING

from . import ui
from .backends import make_backend
from .config import AgentConfig
from . import late_tools  # noqa: F401  (registers diagnose/copy/paste/order/network)
from .tools import BY_NAME, Tool, _obj

if TYPE_CHECKING:
    from .orchestrator import Orchestrator

SYSTEM = """You are {name}, the foreman of the Claude Crew: AI players in a live multiplayer Factorio 2.0 game
(Space Age installed) playing alongside humans. You have no character. The workers ({crew}) each have one and
build by hand under normal player rules; you decide and direct, they execute. You never wait on anyone and
nobody waits on you: workers keep building while their question sits in your queue, so answer fast.

What you do:
- Answer worker questions with a decision they can act on now: who does what, where (exact coordinates), which
  design (`designs`; tell them to `stamp` it at x,y rotation r), which ratio. One reply per asker with
  `reply`; answer every question in the batch. Short and specific beats thorough.
- Own the plan: keep `roadmap` to 5-8 measurable milestones in progression order (research is the clock: labs
  should never be idle). Mark them done only when measured. Post work as board tasks with an owner, one coherent
  chunk each (coordinates, item counts).
- Prevent collisions: check `board` zones and tasks before assigning; give each worker a domain and outcomes
  ("copper 2/s into the depot at [gps=x,y]"), not step lists. Settle conflicts between workers decisively.
- Diagnose from data: `diagnose item=<x>` first for any shortage ("fix our iron"): it gives made vs used,
  every producer/consumer by status with sites, and the likely cause; then diagnose the ingredient it points
  at. `production`, `inspect`, `map`, `find`, `network` fill in. Starved labs or zero plate flow are
  emergencies; assign someone at once.
- Scale what works: `copy` a working build (a smelting column, a science block) and `paste` it as ghosts where it
  should go, then assign a worker to feed and connect it (robots build ghosts if there's a roboport network with
  the items; otherwise the worker builds them). `order` upgrades (belts, furnaces, assemblers) and clears areas.
- Watch your workers, not just the base: [workers] shows each one's recent calls, how much of it is building,
  and its failures. Some workers run on smaller models: when one spins (few builds, repeated failures, long
  waits, a wrong tactic like hand-feeding or waiting on one furnace), step in with step-level instructions:
  exact coordinates, which design to paste or stamp where, what to carry. Give each worker a concrete next job
  when it reports done.
- Humans outrank you. When a human gives an order, turn it into a plan and tasks immediately, reply to them in
  chat (`reply` to="chat") in one line, and tell the workers their part.
- Use `notes` for what you need to remember between turns (plans, who's on what, coordinates).
- Be fast: a few tool calls to look, then decide. A good answer in one minute beats a perfect one in five.

Game facts: burner drill 0.25 ore/s, electric drill 0.5/s, stone furnace 0.3125 plates/s, steel furnace 0.625/s,
assembler-1 speed 0.5 / asm-2 0.75, red science 5s (1 copper + 1 gear), green 6s (inserter + belt), blue 12s for 2
(2 engines + 3 red circuits + 1 sulfur), yellow belt 15/s (7.5 per lane), 1 offshore pump : 20 boilers : 40 steam
engines (900 kW each). Inserters take from the side they face and drop opposite. 1x1 and 3x3 at .5 centers,
2x2 at integer corners.
"""

FOREMAN_TOOLS = ["map", "find", "inspect", "recipes", "techs", "production", "board", "post_task", "update_task",
                 "roadmap", "marks", "mark", "designs", "work", "notes", "reply", "research",
                 "diagnose", "copy", "paste", "order", "network"]
BATCH_WAIT = 12  # seconds to collect more worker questions before a turn (humans don't wait)
REVIEW_EVERY = 300  # seconds without any turn before the foreman reviews the base and its workers
MAX_STEPS = 18


class _Link:
    """The game link, with the foreman's viewpoint swapped for a live worker (observe calls need a character)."""

    def __init__(self, fm: "Foreman"):
        self._fm = fm

    async def call(self, op, **kw):
        if kw.get("agent") == self._fm.name:
            kw["agent"] = self._fm.viewpoint()
        return await self._fm.orch.link.call(op, **kw)

    def job_future(self, job_id):
        return self._fm.orch.link.job_future(job_id)


class Foreman:
    def __init__(self, cfg: AgentConfig, orch: "Orchestrator"):
        self.cfg = cfg
        self.name = cfg.name
        self.orch = orch
        self.board = orch.board
        self.link = _Link(self)
        self.dir = orch.cfg.state_dir / "agents" / cfg.name
        self.dir.mkdir(parents=True, exist_ok=True)
        self.transcript = (self.dir / "transcript.jsonl").open("a")
        self.notes_path = self.dir / "notes.txt"
        self.notes = self.notes_path.read_text() if self.notes_path.exists() else ""
        self.queue: deque[dict] = deque()  # pending questions / human chat / events
        self.open_q: dict[int, dict] = {}  # questions shown to the model and not replied to yet
        self.next_q = 1
        self.event = asyncio.Event()
        self.in_turn = False
        self.last_turn = time.time()
        self.last_vitals = 0.0
        self.total_cost = 0.0
        self.turn_times: deque[float] = deque()
        self.last_position = None
        self.pending_jobs: set[int] = set()
        self.finished: dict = {}
        tools = [RESEARCH if n == "research" else BY_NAME[n] for n in FOREMAN_TOOLS]
        orders_mode = orch.cfg.flag("orders", False)
        if orders_mode:
            tools += ORDER_TOOLS
        crew = ", ".join(a.name for a in orch.cfg.agents)
        system = SYSTEM.format(name=self.name, crew=crew) + (ORDERS_PROMPT if orders_mode else "")
        self.backend = make_backend(self, system, self.dir / "cwd", tools, max_steps=MAX_STEPS)
        self._task: asyncio.Task | None = None
        self._review: asyncio.Task | None = None

    # ------------------------------------------------------------------ what tools expect of an "agent"
    def viewpoint(self) -> str:
        names = list(self.orch.agents)
        return names[0] if names else self.name

    def crew_names(self):
        return list(self.orch.agents)

    async def notify_peer(self, name, text, wake=True):
        peer = self.orch.agents.get(name)
        if peer:
            peer.hear(f"(foreman) {text}", wake=wake, urgent=False)

    def hear(self, line: str, wake: bool = False, urgent: bool = False) -> None:
        self.note(line)

    def set_notes(self, text: str) -> None:
        self.notes = text[:3000]
        self.notes_path.write_text(self.notes)

    def drain_interrupts(self) -> str:
        """New questions that arrived mid-turn show up in the next tool result, so one turn can answer them."""
        if not self.queue:
            return ""
        return "[new while you were working]\n" + self._render_items(self._take_all(mid=True))

    def record(self, kind, **kw):
        self.transcript.write(json.dumps({"t": time.time(), "kind": kind, **kw}, default=str) + "\n")
        self.transcript.flush()

    def log_tool(self, name, args):
        ui.tool(self.name, name, args)
        self.record("tool", name=name, args=args)

    def log_tool_result(self, name, out):
        ui.tool_result(self.name, name, out)
        self.record("result", name=name, out=out)

    def log_thought(self, text):
        ui.thought(self.name, text)
        self.record("thought", text=text)
        self._last_text = text

    # ------------------------------------------------------------------ inputs
    def ask(self, asker: str, question: str, context: str = "") -> int:
        qid = self.next_q
        self.next_q += 1
        self.queue.append({"kind": "q", "id": qid, "from": asker, "text": question, "context": context,
                           "t": time.time()})
        ui.info(f"{asker} asks {self.name} (#{qid}): {question[:120]}")
        self.event.set()
        return qid

    def human(self, player: str, text: str) -> None:
        self.queue.append({"kind": "human", "from": player, "text": text, "t": time.time()})
        self.event.set()

    def note(self, text: str, wake: bool = False) -> None:
        """Events (research done, alerts, milestones): context for the next turn; wake=True starts one."""
        self.queue.append({"kind": "event", "text": text, "t": time.time(), "wake": wake})
        if wake:
            self.event.set()

    def _take_all(self, mid: bool = False) -> list[dict]:
        items = list(self.queue)
        self.queue.clear()
        for it in items:
            if it["kind"] == "q":
                it["mid"] = mid
                self.open_q[it["id"]] = it
        return items

    @staticmethod
    def _render_items(items: list[dict]) -> str:
        out = []
        for it in items:
            age = int(time.time() - it["t"])
            if it["kind"] == "q":
                out.append(f"- Q#{it['id']} from {it['from']} ({age}s ago): {it['text']}"
                           + (f"\n  context: {it['context']}" if it.get("context") else ""))
            elif it["kind"] == "human":
                out.append(f"- HUMAN {it['from']} in chat: \"{it['text']}\"")
            else:
                out.append(f"- {it['text']}")
        return "\n".join(out)

    def answered(self, ids: list[int] | None, to: str) -> None:
        if ids:
            for i in ids:
                self.open_q.pop(int(i), None)
        else:  # no ids given: a reply to someone answers all their open questions
            for i in [i for i, q in self.open_q.items() if q["from"] == to]:
                self.open_q.pop(i, None)

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        await self.backend.start()
        self._task = asyncio.create_task(self._loop(), name="foreman")
        self._review = asyncio.create_task(self._review_loop(), name="foreman-review")

    async def close(self) -> None:
        for t in (self._task, self._review):
            if t:
                t.cancel()
        await self.backend.close()
        self.transcript.close()

    async def _review_loop(self) -> None:
        while True:
            await asyncio.sleep(60)
            if not self.in_turn and not self.queue and time.time() - self.last_turn > REVIEW_EVERY:
                self.note("(periodic review) Nobody has asked anything for a while. Check the [base] line, idle "
                          "workers and the roadmap; re-balance or assign the biggest bottleneck. If all is well, "
                          "do nothing.", wake=True)

    def _budget_ok(self) -> bool:
        now = time.time()
        while self.turn_times and now - self.turn_times[0] > 3600:
            self.turn_times.popleft()
        return len(self.turn_times) < self.cfg.max_turns_per_hour and self.orch.spend_ok()

    async def _loop(self) -> None:
        while True:
            await self.event.wait()
            self.event.clear()
            if not self.queue or not any(it["kind"] != "event" or it.get("wake") for it in self.queue):
                continue
            if not self._budget_ok():
                ui.info(f"{self.name}: turn budget reached; questions wait")
                await asyncio.sleep(60)
                self.event.set()
                continue
            # Workers don't wait on answers, so collect a few questions per turn; humans go straight through.
            if not any(it["kind"] == "human" for it in self.queue):
                oldest = min(it["t"] for it in self.queue)
                while (time.time() - oldest < BATCH_WAIT
                       and sum(it["kind"] == "q" for it in self.queue) < 3
                       and not any(it["kind"] == "human" for it in self.queue)):
                    await asyncio.sleep(1)
            items = self._take_all()
            prompt = await self._briefing(items)
            self.in_turn = True
            self._last_text = ""
            t0 = time.time()
            self.turn_times.append(t0)
            self.record("prompt", text=prompt)
            try:
                stats = await self.backend.turn(prompt)
            except Exception as e:
                ui.info(f"{self.name}: turn failed ({e!r})")
                stats = None
            finally:
                self.in_turn = False
                self.last_turn = time.time()
            if stats:
                self.total_cost += stats.cost_usd
                self.orch.record_spend(stats.cost_usd)
                self.record("turn", secs=round(time.time() - t0, 1), steps=stats.steps, cost=stats.cost_usd,
                            error=stats.error, input_tokens=stats.input_tokens)
                ui.turn_end(self.name, time.time() - t0, stats, self.total_cost)
                if stats.steps and stats.input_tokens / max(stats.steps, 1) > 80_000:
                    await self.backend.reset()  # roadmap, board and notes carry the context
                    self.record("reset")
            # A question that only arrived mid-turn gets a turn of its own; anything else it didn't answer gets
            # its closing words, so no worker is left hanging.
            text = getattr(self, "_last_text", "") or "no answer this time; decide yourself and carry on"
            for q in list(self.open_q.values()):
                if q.get("mid") and not q.get("requeued"):
                    q["requeued"] = True
                    self.queue.append(q)
                else:
                    self.deliver(q["from"], f"(re your Q#{q['id']}) {text}")
            self.open_q.clear()
            if self.queue:
                self.event.set()

    def deliver(self, to: str, text: str) -> None:
        agent = self.orch.agents.get(to)
        if agent:
            agent.hear(f"{self.name} (foreman): {text}", wake=True, urgent=False)

    async def _briefing(self, items: list[dict]) -> str:
        from .tools import vitals_line
        parts = ["[queue]", self._render_items(items)]
        try:
            v = await vitals_line(self)
            if v:
                parts.append(v)
        except Exception:
            pass
        crew = []
        for a in self.orch.agents.values():
            idle = int(time.time() - a.idle_since) if a.mode == "idle" and not a.in_turn else 0
            health = a.health_line() if hasattr(a, "health_line") else ""
            crew.append(f"- {a.name} ({a.cfg.focus or 'general'}; {a.cfg.model}): {a.status_text or 'no status'}"
                        + (f" [IDLE {idle // 60} min]" if idle > 60 else "") + (f"\n    {health}" if health else ""))
        parts.append("[workers]\n" + "\n".join(crew))
        if getattr(self.orch, "book", None):
            parts.append("[orders]\n" + self.orch.book.render())
        parts.append("[roadmap]\n" + self.board.render_roadmap())
        parts.append("[zones]\n" + self.board.render_zones())
        parts.append("[board]\n" + self.board.render(limit=15))
        if self.notes:
            parts.append("[your notes]\n" + self.notes)
        return "\n".join(parts)


async def _t_reply(fm, a: dict) -> str:
    to, text = str(a.get("to", "")).strip(), str(a.get("text", "")).strip()
    if not text:
        return "empty reply"
    ids = a.get("q") or None
    if to == "chat":
        await fm.orch.announce(fm.name, text)
        fm.answered(ids, to)
        return "said in chat"
    if to == "all":
        for name in fm.orch.agents:
            fm.deliver(name, text)
        fm.answered(ids, to)
        return f"sent to {', '.join(fm.orch.agents)}"
    if to not in fm.orch.agents:
        return f"no worker {to!r}; crew: {', '.join(fm.orch.agents)}"
    fm.deliver(to, text)
    fm.answered(ids, to)
    return f"sent to {to}"


REPLY = Tool("reply", "Answer a worker (to=<name>), everyone (to='all'), or the humans in game chat (to='chat'). "
             "Workers get it in their next tool result while they keep working. Pass q=[ids] for the questions "
             "you're answering (a reply to a worker without q answers all their open questions).",
             _obj({"to": {"type": "string"}, "text": {"type": "string"},
                   "q": {"type": "array", "items": {"type": "integer"}}}, ["to", "text"]), _t_reply)
BY_NAME["reply"] = REPLY


async def t_ask_foreman(agent, a: dict) -> str:
    fm = agent.orch.foreman_brain
    if not fm:
        return "there is no foreman; decide yourself"
    q = str(a.get("question", "")).strip()
    if not q:
        return "ask a question"
    qid = fm.ask(agent.name, q, str(a.get("context", "")))
    ahead = len(fm.queue) - 1 + (1 if fm.in_turn else 0)
    return (f"asked (Q#{qid}{f', {ahead} ahead of you' if ahead > 0 else ''}). The answer arrives in a later "
            "tool result; keep your character busy meanwhile.")


ASK_FOREMAN = Tool("ask_foreman", "Ask the foreman (the crew's lead, no character; sees the map, owns the plan) for a "
                   "decision you can't make inside your own domain: it touches another worker's build or stock, "
                   "changes the plan or research order, or your work is done and `work` shows nothing worth doing. "
                   "Returns at once; the answer arrives in a later tool result while you keep working. Put your "
                   "proposal in it. Don't ask permission for things in your domain, and don't send status here "
                   "(use report).",
                   _obj({"question": {"type": "string"},
                         "context": {"type": "string", "description": "what you see / what you propose"}},
                        ["question"]), t_ask_foreman)
BY_NAME["ask_foreman"] = ASK_FOREMAN


async def t_report(agent, a: dict) -> str:
    fm = agent.orch.foreman_brain
    text = str(a.get("text", "")).strip()
    if not fm or not text:
        return "nothing to report" if text else "empty report"
    fm.note(f"{agent.name} reports: {text}")
    return "reported (the foreman reads it on its next turn; no reply needed)"


REPORT = Tool("report", "Tell the foreman what you finished, measured or found (one or two lines, with numbers and "
              "coordinates). It doesn't interrupt anyone and needs no reply; keep working.",
              _obj({"text": {"type": "string"}}, ["text"]), t_report)
BY_NAME["report"] = REPORT


async def t_research(fm, a: dict) -> str:
    args = {k: a[k] for k in ("tech", "first", "remove") if k in a}
    r = await fm.link.call("research", **args)
    return ("OK " if r.get("ok") else "FAILED ") + str(r.get("msg", ""))


RESEARCH = Tool("research", "Change the research queue: tech=<name> adds it; first=true moves it and its "
                "prerequisites to the front; remove=true takes it out. The result shows the queue.",
                _obj({"tech": {"type": "string"}, "first": {"type": "boolean"}, "remove": {"type": "boolean"}},
                     ["tech"]), t_research)
BY_NAME.setdefault("research", RESEARCH)


# ---------------------------------------------------------------------- orders mode (docs/architecture.md)
ORDERS_PROMPT = """
# Orders: how you direct the crew
The workers are actors: characters with deterministic controllers and small models. They don't take prose
instructions; they execute ORDERS from the scheduler, one at a time, and their controller fetches items from
chests, crafts, clears marked trees, refuels burners and builds ghosts on its own. You write the orders.
- For a human goal, `request` it first (text + optional measurable done_when), then split it into orders that each
  have ONE verifiable result. Independent orders run in parallel on different actors; use after=[ids] only for
  real dependencies. Zones of active orders never overlap.
- Order plans: paste (a `copy` name, x, y, direction: the controller lays it), stamp (a library design from
  `designs`), ghosts (ghosts already in the zone: you pasted them, or a human did), connect (item, from, to: a belt,
  pipe or pole line), task (short free text for the actor's small model, for jobs that need judgement, e.g.
  "fuel the 6 furnaces in the zone from the coal chest at [gps=..]").
- Every order needs a zone [x1,y1,x2,y2] covering the build (except connect). done_when is a list of checks the
  game evaluates: {"ghosts_cleared": true}, {"working": {"name": "stone-furnace", "min": 12}},
  {"exists": {"name": "lab", "min": 4}}, {"rate": {"item": "iron-plate", "min": 900}}. Default: ghosts_cleared.
- Prefer copy/paste of builds that already work here, and library designs. Check the spot is clear (map) before
  pasting. Supply materials: actors fetch from any chest, so the mall and depot chests are what keep them fast.
- Keep every actor busy: when you're told actors are idle, give them orders (the next roadmap step, the biggest
  bottleneck from diagnose). A blocked order comes back with its blocker: fix the plan (other spot, supply items,
  a connect order) or cancel it.
"""


def _book(fm):
    book = getattr(fm.orch, "book", None)
    if book is None:
        raise ValueError("orders mode is off")
    return book


async def t_request(fm, a: dict) -> str:
    r = _book(fm).add_request(str(a.get("text", "")), str(a.get("by", "")), a.get("done_when") or [])
    return f"request R{r.id} created. Now add its orders with order request={r.id}."


async def t_order(fm, a: dict) -> str:
    plan = a.get("plan")
    if isinstance(plan, str):
        plan = json.loads(plan)
    o = _book(fm).add_order(str(a.get("title", "")), plan or {}, a.get("zone"), a.get("done_when"), a.get("after"),
                            a.get("request"), a.get("owner"), str(a.get("notes", "")))
    return f"queued:\n{o.card()}"


async def t_orders(fm, a: dict) -> str:
    return _book(fm).render(limit=40)


async def t_cancel_order(fm, a: dict) -> str:
    book = _book(fm)
    o = book.cancel(int(a["id"]), str(a.get("why", "")))
    for actor in fm.orch.agents.values():
        if getattr(actor, "order", None) is o:
            actor.stop_order("the foreman")
            actor.paused_until = 0
    return f"cancelled #{o.id}"


ORDER_TOOLS = [
    Tool("request", "Record a human goal as a request: text, by (who asked), optional done_when checks for the whole "
         "goal (e.g. [{\"rate\": {\"item\": \"iron-plate\", \"min\": 900}}]). Then split it into orders.",
         _obj({"text": {"type": "string"}, "by": {"type": "string"}, "done_when": {"type": "array"}}, ["text"]),
         t_request),
    Tool("order", "Queue one order for the actors. title; plan={kind: paste|stamp|ghosts|connect|task, ...}: paste "
         "{name, x, y, direction}, stamp {name, x, y, rotation}, ghosts {}, connect {item, from:[x,y], to:[x,y]}, "
         "task {text}; zone=[x1,y1,x2,y2] (required except connect); done_when=[checks] (default ghosts_cleared); "
         "after=[order ids]; request=<id>; owner=<actor name> (optional hint); notes (inputs/outputs to hook up).",
         _obj({"title": {"type": "string"}, "plan": {"type": "object"}, "zone": {"type": "array"},
               "done_when": {"type": "array"}, "after": {"type": "array"}, "request": {"type": "integer"},
               "owner": {"type": "string"}, "notes": {"type": "string"}}, ["title", "plan"]), t_order),
    Tool("orders", "The order graph: open requests, every order with status/owner/progress, blocked orders with their "
         "blocker, and recently finished ones.", _obj({}), t_orders),
    Tool("cancel_order", "Cancel an order (id); its actor stops and becomes free.",
         _obj({"id": {"type": "integer"}, "why": {"type": "string"}}, ["id"]), t_cancel_order),
]
for _t in ORDER_TOOLS:
    BY_NAME[_t.name] = _t
