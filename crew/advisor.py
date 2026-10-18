"""The foreman's right hand: a characterless senior engineer the foreman consults for designs and plans.

It has read-only game tools (seeing through the asking agent's position, plus any spot it maps) and the board,
so it can turn a design into concrete tasks for the crew. One persistent session, so it remembers the base.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING

from . import ui
from .backends import make_backend
from .config import AgentConfig
from .tools import BY_NAME, READ_ONLY

if TYPE_CHECKING:
    from .agent import Agent
    from .orchestrator import Orchestrator

SYSTEM = """You are {name}, the senior engineer and right hand of the foreman of the Claude Crew: AI players in a
live multiplayer Factorio 2.0 game (Space Age installed) playing alongside humans. You have no character; you
see the world through read-only tools (from the asking agent's position, plus `map`/`inspect` at any x,y) and
can post tasks to the crew's board. The crew builds by hand under normal player rules: walking, hand mining,
real inventory, reach. Their build actions: place (name x y direction), connect (routes belts/pipes/poles
around obstacles from=[x,y] to=[x,y]), insert, take, set_recipe, rotate, craft, mine, research.

Your job: answer the foreman's question with a design they can build without guessing.
- Look before you design: check the actual terrain, ore, water and existing buildings with map/inspect/find.
  Never place things on top of existing entities, water, or off the ore for drills.
- Be concrete: exact positions (1x1 and 3x3 at .5 centers, 2x2 at integer corners), directions, item counts
  to bring, and the build order. Inserters take from the side they face and drop opposite; drills drop one tile
  in front; belts move toward their direction.
- Do the math with real 2.0 numbers: burner drill 0.25 ore/s, electric drill 0.5 ore/s, stone furnace 0.3125
  plates/s (3.2s/plate), assembler-1 speed 0.5 / assembler-2 0.75, red science 5s (1 copper + 1 gear), green
  science 6s (1 inserter + 1 belt), yellow belt 15 items/s (7.5 per lane), 1 offshore pump : 20 boilers :
  40 steam engines (900 kW each), small pole wire reach 7.5 and 5x5 supply area, medium pole 9 / 7x7.
- Keep designs compact and expandable; leave walking gaps; prefer what the crew can build with what they have.
- If asked to delegate, post the build as board tasks (one coherent chunk per task, with coordinates and item
  lists) and assign them if told who. Say which task ids you created.
- Be fast. Answer within about a dozen tool calls: look at the few things that matter, then design. A good
  design in two minutes beats a perfect one in ten; the crew is waiting on you.
- Reply in plain text: a short summary first, then the spec. No essays.
"""


ADVISOR_MAX_STEPS = 14  # a consult that takes ten minutes stalls whoever asked


class _View:
    """What the read-only tools need: the asker's character as viewpoint, the advisor's identity for logs."""

    def __init__(self, advisor: "Advisor", asker: "Agent"):
        self.name = asker.name  # game calls observe from the asker's position
        self.link = asker.link
        self.board = asker.board
        self.orch = asker.orch
        self.last_position = None
        self.pending_jobs: set[int] = set()
        self.finished: dict = {}
        self._advisor = advisor

    def crew_names(self):
        return list(self.orch.agents)

    async def notify_peer(self, name, text, wake=True):
        peer = self.orch.agents.get(name)
        if peer:
            peer.hear(f"(crew) {text}", wake=wake, urgent=False)

    def drain_interrupts(self) -> str:
        return ""

    def log_tool(self, name, args):
        ui.tool(self._advisor.name, name, args)
        self._advisor.record("tool", name=name, args=args)

    def log_tool_result(self, name, out):
        ui.tool_result(self._advisor.name, name, out)
        self._advisor.record("result", name=name, out=out)

    def log_thought(self, text):
        ui.thought(self._advisor.name, text)
        self._advisor.record("thought", text=text)


class Advisor:
    def __init__(self, cfg: AgentConfig, orch: "Orchestrator"):
        self.cfg = cfg
        self.name = cfg.name
        self.orch = orch
        self.dir = orch.cfg.state_dir / "agents" / cfg.name
        self.dir.mkdir(parents=True, exist_ok=True)
        self.transcript = (self.dir / "transcript.jsonl").open("a")
        # One session per asker so consults run in parallel instead of queueing behind one lock.
        self.sessions: dict[str, dict] = {}
        self.total_cost = 0.0

    def record(self, kind, **kw):
        self.transcript.write(json.dumps({"t": time.time(), "kind": kind, **kw}, default=str) + "\n")
        self.transcript.flush()

    async def _session(self, asker: "Agent") -> dict:
        sess = self.sessions.get(asker.name)
        if sess is None:
            view = _View(self, asker)
            view.cfg = self.cfg
            tools = [BY_NAME[n] for n in READ_ONLY]
            backend = make_backend(view, SYSTEM.format(name=self.name), self.dir / f"cwd-{asker.name}", tools,
                                   max_steps=ADVISOR_MAX_STEPS)
            await backend.start()
            sess = {"view": view, "backend": backend, "lock": asyncio.Lock()}
            self.sessions[asker.name] = sess
        return sess

    async def ask(self, asker: "Agent", question: str, context: str) -> str:
        if not question.strip():
            return "ask a question"
        sess = await self._session(asker)
        async with sess["lock"]:  # one consult at a time per asker
            view, backend = sess["view"], sess["backend"]
            prompt = (f"{asker.name} asks: {question}\n" + (f"Context from {asker.name}: {context}\n" if context else "")
                      + f"[roadmap]\n{asker.board.render_roadmap()}\n[board]\n{asker.board.render(limit=20)}\n"
                      + f"[crew] {', '.join(self.orch.agents)}")
            self.record("prompt", asker=asker.name, text=prompt)
            ui.info(f"{asker.name} consults {self.name}: {question[:120]}")
            replies: list[str] = []
            orig = view.log_thought

            def capture(text):
                replies.append(text)
                orig(text)
            view.log_thought = capture
            t0 = time.time()
            try:
                stats = await backend.turn(prompt)
            finally:
                view.log_thought = orig
            self.total_cost += stats.cost_usd
            self.record("turn", asker=asker.name, secs=round(time.time() - t0, 1), steps=stats.steps,
                        cost=stats.cost_usd, error=stats.error)
            ui.turn_end(self.name, time.time() - t0, stats, self.total_cost)
            answer = replies[-1] if replies else ""
            if stats.error and not answer:
                return f"{self.name} couldn't answer ({stats.error}); try again shortly"
            return f"{self.name} says:\n{answer}"

    async def close(self):
        for sess in self.sessions.values():
            await sess["backend"].close()
        self.transcript.close()
