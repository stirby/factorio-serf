"""The thinker: Opus, asynchronous. It never sits in the action loop. It is woken with a request (a new order the
actor couldn't handle alone, or a report that a plan failed or didn't reach its goal), looks at the world through
a few read tools, and answers by submitting a plan (and optionally a chat line). The actor runs the plan.

Backend: the Claude Agent SDK on the local Claude Code login (subscription), one persistent session per run, so the
thinker remembers earlier orders and plans.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

log = logging.getLogger("jev.thinker")

MODEL = "claude-opus-5-5"

SYSTEM = """You are the planner ("thinker") for a Factorio 2.0 character called {name} that plays next to human players and takes orders from chat. A fast, cheap decision model (the "actor") runs your plans step by step in real game time, handles small problems itself, and wakes you only for new orders it can't handle, and for plans that failed or didn't reach their goal. Your job: read the situation, then submit ONE complete plan with submit_plan. Be quick and decisive: the character idles while you think. Usually: one or two look calls, then submit_plan. Don't ask the player questions unless the order is truly ambiguous; when a choice is yours, pick something sensible.

The character obeys normal player rules (walks, has reach, real inventory, real crafting time). The actor does the obvious prerequisites itself: before placing or inserting anything it fetches the items (from chests and machine outputs, otherwise hand-crafts them from what it has). You don't need fetch steps unless you want to stock up first.

Step ops (each step is an object {{"do": op, ...}}):
  place name x y [direction] [recipe]       build one entity. Inserters: give pickup=[x,y] (tile it takes from) or drop=[x,y] instead of direction; that's always right. Assemblers: add recipe.
  rotate x y direction                      turn a belt/inserter/etc to face north|east|south|west
  set_recipe x y recipe
  connect item from=[x,y] to=[x,y] [end_direction]   route and build a line around obstacles: transport-belt, pipe, small-electric-pole/medium-electric-pole. Belts point along the route; they go under crossings and water with undergrounds. from = the last belt of an existing line (or the tile next to it) continues it; to = an existing belt joins it from behind or the side. Poles hop by wire reach.
  ghosts entities=[{{name,x,y,direction,recipe}}]   lay out a whole design as planned ghosts, then build all of them (items fetched automatically). Best for any build of more than ~3 entities. In ghosts, an inserter's direction is the side it PICKS UP FROM (direction north = takes from the tile north of it, drops on the tile south of it).
  stamp string x y [direction]              lay a blueprint string as ghosts and build it
  design name x y                           build a saved design (save_design) with its 0,0 anchor at x,y
  build_ghosts [x y radius]                 build planned ghosts (also the players' own)
  insert x y item [count] | take x y [item] [count] | empty_chest x y
  refuel x y [fuel]                         put fuel into a burner (fetches coal)
  power x y [from=[x,y]] [item]             run poles from the nearest powered pole (or from) to x,y
  fetch item count | craft recipe count | mine name count | mine_at x y (pick up one entity)
  research tech | move x y | follow player [seconds] | wait seconds | say text
  configure x y requests={{..}}|filter=item | limit x y slots

Geometry: tile (x,y) spans x..x+1. 1x1 and 3x3 entities sit at .5 centers (e.g. 10.5,4.5); 2x2 entities at integer corners (e.g. 10,4). An assembling machine is 3x3, stone/steel furnace 2x2, electric mining drill 3x3 (drops one tile in front, the direction it faces), burner drill 2x2, boiler 3x2, steam engine 3x5, small pole reaches wires 7.5 tiles and powers a 5x5 area, medium pole 9 tiles / 7x7. Inserters move items from the tile on one side to the tile on the opposite side; belts carry two lanes; a yellow belt carries 15 items/s. An inserter taking from a belt and dropping into a machine needs the machine's edge right next to it. Underground belts: max 4 tiles between entrance and exit for yellow.

Plans must be complete: every step needed to reach the goal, in order. Prefer reusing what exists (belts, poles, chests). Keep builds compact and away from existing stuff (check the area first). Never hand-feed machines when the order says to automate: build inserters and belts.

submit_plan fields: goal (what done looks like, one line), steps, expect (machine-checkable conditions: {{"check":"working","recipe":R,"count":N,"near":[x,y],"radius":r}}, {{"check":"has_item","x":..,"y":..,"item":I,"count":N}} (a chest or machine holds it), {{"check":"powered","near":[x,y],"radius":r}}, {{"check":"belt_carries","x":..,"y":..,"item":I}}), say (short chat line to the player now, optional), done_text (chat line when verified).
Chat lines are short and plain, like a player in game chat.
After submit_plan, end your turn immediately: no summary, no commentary (nobody reads it; the actor is already working).
Only use items that exist: the order message lists what's in storage chests and what the character carries; anything else must be hand-craftable from those (wooden chests need wood; use iron chests when there's no wood).
Belts: to take items off an existing belt, put the inserter (and the machine) right next to that belt; don't extend a belt backwards from its end. A branch needs a splitter or a side-load. connect's `from` continues a line only from its last belt, in the direction it already runs."""

TOOLS = [
    ("area", "What's in an area: machines with state and why they're stopped, belt lines (direction, items, where "
             "they start/end and why), chests, power grids, ore, water, planned ghosts, and detected faults with "
             "suggested fixes. Coordinates are exact.",
     {"type": "object", "properties": {"x": {"type": "number"}, "y": {"type": "number"},
                                       "radius": {"type": "integer", "description": "default 20, max 64"}},
      "required": ["x", "y"]}),
    ("find", "Nearest entities or resources by name (iron-ore, coal, water, stone-furnace...) or where an item is "
             "stored (chests and machine outputs) with counts.",
     {"type": "object", "properties": {"name": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["name"]}),
    ("recipe", "A recipe's ingredients, products, time and the machine category.",
     {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}),
    ("free_space", "Free ground for a w x h block near x,y (no buildings, water, cliffs, ore).",
     {"type": "object", "properties": {"w": {"type": "integer"}, "h": {"type": "integer"}, "x": {"type": "number"},
                                       "y": {"type": "number"}}, "required": ["w", "h", "x", "y"]}),
    ("me", "The character: position, inventory, current job.", {"type": "object", "properties": {}}),
    ("save_design", "Save a layout to reuse with a {\"do\": \"design\", \"name\", \"x\", \"y\"} step: entities "
                    "relative to an anchor at 0,0 (an integer tile corner; keep .5 centers as .5). Use it when an "
                    "order asks for the same thing more than once, or for something worth repeating.",
     {"type": "object", "properties": {"name": {"type": "string"}, "note": {"type": "string"},
                                       "entities": {"type": "array", "items": {"type": "object"}}},
      "required": ["name", "entities"]}),
    ("save_lesson", "Save one general rule for your future self (no coordinates): what would have made a first plan "
                    "work. Only when asked for a lesson.",
     {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}),
    ("say", "Say a line in game chat now.", {"type": "object", "properties": {"text": {"type": "string"}},
                                             "required": ["text"]}),
    ("submit_plan", "Submit the plan for the actor to run now (replaces any running plan for this order). End your "
                    "turn after this.",
     {"type": "object", "properties": {
         "goal": {"type": "string"},
         "steps": {"type": "array", "items": {"type": "object"}},
         "expect": {"type": "array", "items": {"type": "object"}},
         "say": {"type": "string"},
         "done_text": {"type": "string"},
         "force": {"type": "boolean", "description": "run it even though the checker reported problems"}},
      "required": ["goal", "steps"]}),
]


@dataclass
class ThinkStats:
    turns: int = 0
    cost_usd: float = 0.0
    secs: float = 0.0
    tool_calls: int = 0
    errors: int = 0
    usage_limited: bool = False


@dataclass
class Request:
    kind: str  # "order" | "report" | "question"
    text: str
    order_id: int | None = None
    t: float = field(default_factory=time.time)


class Thinker:
    def __init__(self, name: str, tools: dict[str, Callable[[dict], Awaitable[str]]],
                 on_plan: Callable[[dict, Request], Awaitable[None]], workdir: Path, log_fn=None,
                 model: str = MODEL, effort: str | None = None,
                 lint_fn: Callable[[dict], Awaitable[list[str]]] | None = None):
        self.name, self.tools, self.on_plan = name, tools, on_plan
        self.lint_fn = lint_fn
        self.lint_rounds = 0
        self.workdir, self.model, self.effort = workdir, model, effort
        self.log_fn = log_fn or (lambda rec: None)
        self.queue: asyncio.Queue[Request] = asyncio.Queue()
        self.stats = ThinkStats()
        self.busy = False
        self.current: Request | None = None
        self.client = None
        self._task: asyncio.Task | None = None
        self._plan_submitted = False

    async def start(self) -> None:
        from claude_agent_sdk import ClaudeAgentOptions, create_sdk_mcp_server, tool

        sdk_tools = []
        for tname, desc, schema in TOOLS:
            def make(n):
                async def handler(args):
                    t0 = time.time()
                    try:
                        if n == "submit_plan":
                            out = await self._submit(args)
                        elif n == "save_design":
                            from .library import save_design
                            out = save_design(args.get("name", ""), args.get("entities") or [], args.get("note", ""))
                        elif n == "save_lesson":
                            from .library import save_lesson
                            out = save_lesson(args.get("text", ""), {"order": getattr(self.current, "order_id", None)})
                        else:
                            out = await self.tools[n](args)
                    except Exception as e:  # noqa: BLE001
                        out = f"error: {e!r}"
                    self.stats.tool_calls += 1
                    self.log_fn({"t": t0, "kind": "thinker_tool", "tool": n, "args": args, "out": str(out)[:4000],
                                 "secs": round(time.time() - t0, 2)})
                    return {"content": [{"type": "text", "text": str(out)}]}
                return handler
            sdk_tools.append(tool(tname, desc, schema)(make(tname)))
        server = create_sdk_mcp_server("game", tools=sdk_tools)
        self.workdir.mkdir(parents=True, exist_ok=True)
        from .library import lessons
        system = SYSTEM.format(name=self.name)
        learned = lessons()
        from .library import designs
        ds = designs()
        if ds:
            system += "\n\nSaved designs (build one with {\"do\": \"design\", \"name\": N, \"x\": X, \"y\": Y}; X,Y = where its 0,0 anchor goes):\n" + \
                "\n".join(f"- {n}: {d.get('note') or ''} ({len(d['entities'])} entities)" for n, d in ds.items())
        if learned:
            system += "\n\nLessons from earlier games (rules you wrote after plans that failed):\n" + \
                "\n".join(f"- {x}" for x in learned)
        kw = dict(system_prompt=system, mcp_servers={"game": server}, tools=[],
                  allowed_tools=[f"mcp__game__{t[0]}" for t in TOOLS], setting_sources=[], model=self.model,
                  cwd=str(self.workdir), max_turns=30,
                  stderr=lambda line: log.debug("[thinker cli] %s", line))
        if self.effort:
            kw["effort"] = self.effort
        from claude_agent_sdk import ClaudeSDKClient
        self.client = ClaudeSDKClient(ClaudeAgentOptions(**kw))
        await self.client.connect()
        self._session_cost = 0.0
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except BaseException:
                pass
        if self.client:
            try:
                await self.client.disconnect()
            except Exception:
                pass

    def ask(self, req: Request) -> None:
        self.queue.put_nowait(req)

    async def _submit(self, args: dict) -> str:
        steps = args.get("steps") or []
        if not isinstance(steps, list) or not all(isinstance(s, dict) and s.get("do") for s in steps):
            return "rejected: steps must be a list of objects with a 'do' op"
        if self.lint_fn and not args.get("force") and self.lint_rounds < 2:
            try:
                problems = await self.lint_fn(args)
            except Exception as e:  # noqa: BLE001
                problems = []
                log.warning("lint failed: %r", e)
            if problems:
                self.lint_rounds += 1
                self.log_fn({"t": time.time(), "kind": "lint", "problems": problems})
                return ("NOT started yet. The plan checker found problems:\n- " + "\n- ".join(problems) +
                        "\nFix them and call submit_plan again (or resubmit with force=true if a warning is wrong).")
        self._plan_submitted = True
        await self.on_plan(args, self.current)
        return f"plan accepted ({len(steps)} steps); the actor is running it now. End your turn."

    async def _loop(self) -> None:
        while True:
            req = await self.queue.get()
            # fold anything else already waiting into this turn
            extra = []
            while not self.queue.empty():
                extra.append(self.queue.get_nowait())
            self.current = req
            self.busy = True
            prompt = req.text + "".join(f"\n\nAlso: {x.text}" for x in extra)
            try:
                await self._turn(prompt, req)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                self.stats.errors += 1
                log.exception("thinker turn failed")
                self.log_fn({"t": time.time(), "kind": "thinker_error", "error": repr(e)})
            finally:
                self.busy = False
                self.current = None

    async def _turn(self, prompt: str, req: Request) -> None:
        from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock

        t0 = time.time()
        self._plan_submitted = False
        self.lint_rounds = 0
        interrupted = False
        self.log_fn({"t": t0, "kind": "thinker_prompt", "req": req.kind, "order": req.order_id, "text": prompt})
        await self.client.query(prompt)
        texts = []
        async for msg in self.client.receive_response():
            if isinstance(msg, AssistantMessage):
                for b in msg.content:
                    if isinstance(b, TextBlock) and b.text.strip():
                        texts.append(b.text)
                        if self._plan_submitted and not interrupted:
                            interrupted = True  # the plan is in; the commentary after it only costs time
                            try:
                                await self.client.interrupt()
                            except Exception:  # noqa: BLE001
                                pass
                        if "usage limit" in b.text.lower() or "hit your session limit" in b.text:
                            self.stats.usage_limited = True
            elif isinstance(msg, ResultMessage):
                total = msg.total_cost_usd or 0.0
                cost = max(0.0, total - self._session_cost)
                self._session_cost = total
                self.stats.cost_usd += cost
                self.stats.turns += 1
                secs = time.time() - t0
                self.stats.secs += secs
                u = msg.usage or {}
                self.log_fn({"t": time.time(), "kind": "thinker_turn", "req": req.kind, "order": req.order_id,
                             "secs": round(secs, 1), "cost": round(cost, 4), "plan": self._plan_submitted,
                             "text": "\n".join(texts)[-2000:], "error": msg.subtype if msg.is_error else None,
                             "in": u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
                             + u.get("cache_creation_input_tokens", 0), "out": u.get("output_tokens", 0)})
        if not self._plan_submitted:
            # a turn without a plan (e.g. it only answered a question): tell the actor so it doesn't wait forever
            await self.on_plan({"goal": None, "steps": [], "no_plan": True, "text": "\n".join(texts)[-500:]}, req)
