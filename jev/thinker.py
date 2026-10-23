"""The thinker: Opus, asynchronous. It never sits in the action loop. It is woken with a request (a new order the
actor couldn't handle alone, or a report that a plan failed or didn't reach its goal), looks at the world through
a few read tools, and answers by submitting a plan (and optionally a chat line). The actor runs the plan.

Backend: the Claude Agent SDK on the local Claude Code login (subscription), one persistent session per run, so the
thinker remembers earlier orders and plans.
"""
from __future__ import annotations

import asyncio
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
  connect item from=[x,y] to=[x,y] [end_direction]   route and build a line around obstacles: transport-belt, pipe, small-electric-pole/medium-electric-pole. Belts point along the route; they go under crossings and water with undergrounds. from = the last belt of an existing line (or the tile next to it) continues it; to = an existing belt joins it from behind or the side. Poles hop by wire reach. Pipes between machines: give from_fluid / to_fluid (e.g. item=pipe from=[refinery x,y] to=[lube plant x,y] from_fluid=heavy-oil to_fluid=heavy-oil): the line starts at that machine's output for the fluid and ends at the other's input for it, whichever side rotation put them on, and keeps clear of pipes and machines holding other fluids (going under them). Use it for every fluid hookup between machines.
  row belt=[x,y] machine recipe count [side] [second_belt] [output] [inserter] [offset]   a row of machines along an existing belt, generated exactly: input inserters take from the belt at belt=[x,y] (a tile of it), machines sit on `side` (across the belt; omitted = whichever side is free), the row grows downstream from that tile, and a belt that ends early (a tap's split-off belt) is carried on under the whole row. second_belt=true: another input belt runs parallel on the far side at distance machine size+3 (6 for assemblers, 5 for furnaces) and gets its own inserters. output="chest" (default: an inserter + iron chest beside each machine) or "belt" (output inserters onto a new parallel belt beyond the machines; its end is reported so you can connect it on). Poles and grid power are included. Default to it for any line of identical machines off a belt (science, gears, circuits, furnace columns: machine=stone-furnace on an ore+coal belt), then add only what it doesn't cover (e.g. a connect from its output belt, or one extra machine). It's tested; hand-laid layouts are where most failed plans come from.
  bus name x y direction side lanes=[items] length   lay a main bus: straight lanes (items in order, "spare" keeps a lane free for a product added later) flowing `direction` from x,y (lane 0's first tile), in pairs with two free columns between pairs; taps come out on `side`. Registered by name: later orders see its lanes, heads and free rows. Feed a lane by connecting its supply line to the lane's head. Same name with a bigger length lengthens it. Belts already on a lane's tiles running the bus's way are taken into it (adopt an existing straight bus by laying it over those lanes).
  tap bus lane at [run]                     take a lane (item or index) off the bus at row `at` (rows count from the bus's start; or at=[x,y] on it): a splitter on the lane, the split-off belt goes under the other lanes and comes out past the bus's side, run tiles long (default 3); returns where that belt ends: build a row along it (the row carries the belt on as far as it needs), or connect it on. Keep taps and merges 4 rows apart.
  bus_in bus item at from=[x,y]             put a product onto the bus: the line ending at from (its last belt) comes in from the bus's side under the lanes and starts a lane at row at+1: the spare lane, or the lane already carrying that item
  ghosts entities=[{{name,x,y,direction,recipe}}]   lay out a whole design as planned ghosts, then build all of them (items fetched automatically). Best for any build of more than ~3 entities. Write repeated layouts compactly inside entities: {{"repeat": N, "dx": 2, "dy": 0, "entities": [...]}} lays the group N times shifted by (dx,dy) each time, and {{"line": "transport-belt", "from": [x,y], "to": [x,y], "direction": "east"}} is a straight run (one entity per tile). In ghosts, an inserter's direction is the side it PICKS UP FROM (direction north = takes from the tile north of it, drops on the tile south of it).
  stamp string x y [direction]              lay a blueprint string as ghosts and build it
  design name x y                           build a saved design (save_design) with its 0,0 anchor at x,y
  block name x y [rotation] [anchor]        build a built-in, game-tested block (list below): its rotated top-left corner goes at x,y (rotation 0/90/180/270 clockwise, or east/south/west); use block_info first to see exactly where its input and output belts end up
  merge_lanes left=[x,y] right=[x,y] at=[x,y] direction [to=[x,y]]   make one belt carrying two items, one per lane (what blocks like red-science-5 want): the belt line ending at `left` side-loads the new belt's left lane, the one ending at `right` its right lane (left/right facing `direction`); `at` is the new belt's first tile, `to` continues it there
  route pairs=[{{name, from:[x,y], to:[x,y]}}]   lay several separate belt lines at once without mixing (crossings go under with undergrounds); code solves the layout exactly. Use it for any set of 2+ belt lines that must not touch, e.g. belt puzzles or buses
  upgrade into [x y radius] [line=[x,y]] [cluster] [only=<old name>]   swap buildings for a better tier in place (radius=0: just the one at x,y; cluster=true: the group of same-kind machines nearest x,y) (keeps direction, recipe, belt contents): everything below `into` in its family within radius (default 8) of x,y, or along one belt line (line = a tile of it). into=fast-transport-belt also upgrades that line's undergrounds and splitters. Families: belts/undergrounds/splitters, assembling-machine-1..3, stone->steel-furnace, burner->inserter->fast-inserter, small->medium pole, chests. Items are fetched or crafted.
  clear x y [radius] [only=[names]] [trees] | clear line=[x,y]   pick up buildings, contents included: line=[x,y] takes exactly the one belt line through that tile (with its undergrounds); x y radius takes EVERYTHING of ours in that square (default 6, max 24; `only` limits it to those names), so neighbouring lines go too (a square with more than 2 separate belt lines is refused, with the lines listed, unless force=true); trees=true clears trees and rocks there instead. For one thing use mine_at.
  purge item x y                            take every `item` off the belts around x,y (wrong items on a belt, e.g. pipes from a wrong recipe); the belts stay
  build_ghosts [x y radius]                 build planned ghosts (also the players' own)
  insert x y item [count] | take x y [item] [count] | empty_chest x y
  refuel x y [fuel]                         put fuel into a burner (fetches coal)
  wait_research tech [minutes]              wait (default 15 min, max 30) until a tech is researched, queueing it if needed; steps after it can use what it unlocks (e.g. feed the labs, wait_research electric-mining-drill, then place the drills). It only waits: the labs need packs
  power x y [from=[x,y]] [item]             run poles from the nearest powered pole (or from) to x,y
  fetch item count | craft recipe count | mine name count | mine_at x y [name] (pick up one entity; with name, only that kind, never a neighbour when x,y is a tile off)
  research tech [first=true: to the front of the queue, with its unresearched prerequisites] [remove=true: take it out of the queue] (or tech="cheapest") | move x y | follow player [seconds] | wait seconds | say text
  configure x y requests={{..}}|filter=item | limit x y slots
  launch x y                                launch the rocket in the silo at x,y once it holds a finished rocket (walks there)

Geometry: tile (x,y) spans x..x+1. 1x1 and 3x3 entities sit at .5 centers (e.g. 10.5,4.5); 2x2 entities at integer corners (e.g. 10,4). An assembling machine is 3x3, stone/steel furnace 2x2, electric mining drill 3x3 (drops one tile in front, the direction it faces), burner drill 2x2, boiler 3x2, steam engine 3x5, small pole reaches wires 7.5 tiles and powers a 5x5 area, medium pole 9 tiles / 7x7. Inserters move items from the tile on one side to the tile on the opposite side; belts carry two lanes; a yellow belt carries 15 items/s. An inserter taking from a belt and dropping into a machine needs the machine's edge right next to it. Underground belts: max 4 tiles between entrance and exit for yellow.

What the actor does on its own (don't plan steps for these, and trust them over older lessons that say otherwise): a connect or power line of any length is laid in legs, and a pole line with a break finds the gap and closes it; power steps fetch or craft their poles; a plan's checks are polled through any wait steps at its end and finish as soon as they pass, waiting as long as items take to cross a new belt; before reporting a failed check it refuels burners and boilers and powers unpowered machines it can see; while idle it keeps the boilers of grids it built on fuelled and refills chests a plan stocked by hand; ghosts the game refuses fail the step at once with the blocker named.

Numbers worth knowing: 1 offshore pump feeds 20 boilers; 1 boiler (1.8 MW) feeds exactly 2 steam engines (0.9 MW each) and burns ~0.45 coal/s; steam engines must be chained end to end from the boiler's steam output and each needs a pole touching the grid. Yellow belt 15 items/s (7.5 per lane); inserter ~0.83 items/s, fast inserter ~2.3/s. Assembler 1 speed 0.5, assembler 2 speed 0.75; stone furnace speed 1 (iron/copper plate 3.2 s). Recipes (time, at speed 1): gear 2 iron 0.5 s; copper cable 1 copper -> 2 cables 0.5 s; green circuit 1 iron + 3 cables 0.5 s (3 cable assemblers : 2 circuit assemblers); red science 1 copper + 1 gear 5 s; green science 1 inserter + 1 belt 6 s; electric mining drill 0.5 ore/s; burner mining drill 0.25 ore/s. Hand-mining is slow (about one item every 1-2 s): for more than ~50 of an ore or coal, place a few burner or electric drills on the patch with a chest (or onto a belt) instead. Burners eat fuel: 1 coal lasts a stone furnace ~44 s, a burner drill ~27 s, a burner inserter a few minutes; 20 coal hand-loaded keeps a burner drill going ~9 min and a furnace ~15 min. Anything meant to run longer than that needs fuel delivered by belt or inserter (e.g. a coal lane on the ore belt into furnaces, or burner drills on coal feeding each other and a coal belt); hand refuelling many burners costs the character minutes of coal mining every round. On a fresh map: two burner drills on coal facing each other fuel each other for good (a burner drill drops its ore 1 tile out from its front edge, onto the tile there); burner drills on iron or copper drop straight into a stone furnace on that tile; a coal drill dropping into a chest gives a pile to refuel from. Smelt early plates by hand-feeding a furnace only until drills run.

Plans must be complete: every step needed to reach the goal, in order. An order that needs several production chains built one after another, each depending on the last (e.g. "automate green science" in a base that has no circuits yet, "get us to oil", "beat the game"), is a project: call start_project rather than one huge plan. For a big order (several separate builds), don't design everything before submitting: submit the first finished part with more=true so the actor starts building it, then design and submit the next part (the last one without more). Each part needs its own steps; put the expect checks where they belong. Prefer reusing what exists (belts, poles, chests). Keep builds compact and away from existing stuff (check the area first). Never hand-feed machines when the order says to automate: build inserters and belts.

submit_plan fields: goal (what done looks like, one line), steps, expect (machine-checkable conditions: {{"check":"working","recipe":R,"count":N,"near":[x,y],"radius":r}}, {{"check":"has_item","x":..,"y":..,"item":I,"count":N}} (a chest or machine holds it), {{"check":"powered","near":[x,y],"radius":r}}, {{"check":"belt_carries","x":..,"y":..,"item":I}}, {{"check":"fluid_reaches","x":..,"y":..,"fluid":F}} (the machine there gets F at an inlet; added by itself for every connect with to_fluid), {{"check":"rate","item":I,"per_min":N,"near":[x,y],"radius":r}} (the machines making I there make at least 85% of N a minute, measured over a minute: use it when the order names a rate)), say (short chat line to the player now, optional), done_text (chat line when verified).
Chat lines are short and plain, like a player in game chat.
After submit_plan, end your turn immediately: no summary, no commentary (nobody reads it; the actor is already working).
Only use items that exist: the order message lists what's in storage chests and what the character carries; anything else must be hand-craftable from those (wooden chests need wood; use iron chests when there's no wood).
Routing puzzles (many belts between pairs of points, crossings): don't work out paths by hand; use one route step with all the pairs (from = where items are put on, to = where they're picked up). It returns quickly.
Belts: to take items off an existing belt, put the inserter (and the machine) right next to that belt; don't extend a belt backwards from its end. A branch needs a splitter or a side-load. connect's `from` continues a line only from its last belt, in the direction it already runs.
Fuel for a furnace column: ore on one lane, coal on the other. Make that belt with one merge_lanes step (left = the end of the ore line, right = the end of the coal line, to = where the furnace row starts) and run the row along it. Don't hand-place side-loads onto a belt that already carries ore on both lanes: the coal lands on an ore lane and jams the furnaces (purge cleans a belt of a wrong item).

Size production like a player: when an order names a rate ("red science for 30/min"), call rates for it and build the machine counts it gives (rounded up), with inputs that can carry it: a belt carries 900 items a minute (yellow), so 2,000 iron plates a minute is three belts. Feed machines by belt or pipe from the supply the order names; a chest someone has to fill by hand isn't automation. Leave room beside a block to add more of the same.

Oil: a refinery on advanced oil processing makes heavy oil, light oil and petroleum together and stops as soon as any one of them backs up ("output is full: heavy-oil is backed up"). Give every output somewhere to go: chemical plants cracking heavy oil into light (heavy-oil-cracking, needs water) and light into petroleum (light-oil-cracking, needs water), or consumers (lubricant, solid fuel). Basic oil processing makes only petroleum and can't deadlock: the simple choice while all you need is plastic and sulfur. The plastic-sulfur-basic block is exactly that, tested: crude and water pipes in, a coal belt in, plastic and sulfur belts out (~108 plastic and 36 sulfur a minute, enough for ~30 blue science a minute); use it rather than piping refineries and chemical plants by hand."""

TOOLS = [
    ("area", "What's in an area: machines with state and why they're stopped, belt lines (direction, items, where "
             "they start/end and why), chests, power grids, ore, water, planned ghosts, and detected faults with "
             "suggested fixes. Coordinates are exact. With more than 30 machines it groups them (count, recipe, "
             "state, extent); look again with a smaller radius for each machine's detail.",
     {"type": "object", "properties": {"x": {"type": "number"}, "y": {"type": "number"},
                                       "radius": {"type": "integer", "description": "default 20, max 64"}},
      "required": ["x", "y"]}),
    ("find", "Nearest entities or resources by name (iron-ore, coal, crude-oil, water, stone-furnace...) or where an "
             "item is stored (chests and machine outputs) with counts. Searches out to `radius` tiles from the "
             "character (default 256; 1024 for crude-oil and uranium-ore); only explored ground can be searched.",
     {"type": "object", "properties": {"name": {"type": "string"}, "limit": {"type": "integer"},
                                       "radius": {"type": "integer", "description": "max 1024"}},
      "required": ["name"]}),
    ("recipe", "A recipe's ingredients, products, time and the machine category.",
     {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}),
    ("free_space", "Free ground for a w x h block near x,y (no buildings, water, cliffs, ore).",
     {"type": "object", "properties": {"w": {"type": "integer"}, "h": {"type": "integer"}, "x": {"type": "number"},
                                       "y": {"type": "number"}}, "required": ["w", "h", "x", "y"]}),
    ("me", "The character: position, inventory, current job.", {"type": "object", "properties": {}}),
    ("production", "Items per minute made and used by the whole base (last minute), biggest first.",
     {"type": "object", "properties": {}}),
    ("diagnose", "Why an item or fluid is short across the base: made vs used per minute, and every machine that makes "
                 "or uses it grouped by state (working, starved of X, output full, no power...) with positions.",
     {"type": "object", "properties": {"item": {"type": "string"}}, "required": ["item"]}),
    ("rates", "What a target rate takes, worked back to ore: machines per step (and which machine), oil refineries "
              "and crackers, raw ore, crude and water a minute, drills, pumpjacks and belts. Size every production "
              "build from it; margin 1.25 = 25% headroom (round up). targets {item: per_min} for several at once.",
     {"type": "object", "properties": {"item": {"type": "string"}, "per_min": {"type": "number"},
                                       "targets": {"type": "object"}, "margin": {"type": "number"},
                                       "assembler": {"type": "string", "description": "default assembling-machine-2"},
                                       "furnace": {"type": "string", "description": "default steel-furnace"}}}),
    ("audit", "The whole base's health: machines working, starved or blocked, grouped by what they make (what the "
              "starved lack, a position), chests filled by hand, belt and pipe per machine, and the science per "
              "minute the labs actually get.", {"type": "object", "properties": {}}),
    ("techs", "Research: what's being researched, the queue, and what can be researched next with its packs "
              "(trigger techs say what unlocks them instead).", {"type": "object", "properties": {}}),
    ("block_info", "Where a built-in block would sit if placed at x,y with that rotation: its footprint, where each "
                   "input belt enters and each output leaves (absolute tiles), and what it needs to build.",
     {"type": "object", "properties": {"name": {"type": "string"}, "x": {"type": "number"}, "y": {"type": "number"},
                                       "rotation": {}}, "required": ["name", "x", "y"]}),
    ("save_design", "Save a layout to reuse with a {\"do\": \"design\", \"name\", \"x\", \"y\"} step: entities "
                    "relative to an anchor at 0,0 (an integer tile corner; keep .5 centers as .5). Use it when an "
                    "order asks for the same thing more than once, or for something worth repeating.",
     {"type": "object", "properties": {"name": {"type": "string"}, "note": {"type": "string"},
                                       "entities": {"type": "array", "items": {"type": "object"}}},
      "required": ["name", "entities"]}),
    ("save_lesson", "Save one general rule for your future self (no coordinates): what would have made a first plan "
                    "work. Only when asked for a lesson. About the game, not about avoiding a step op: when an op "
                    "misbehaves (crashes, refuses a fair request), say so plainly; that goes to the harness's "
                    "maintainers, who fix it, instead of becoming a rule.",
     {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}),
    ("say", "Say a line in game chat now.", {"type": "object", "properties": {"text": {"type": "string"}},
                                             "required": ["text"]}),
    ("start_project", "For an order far bigger than one plan (a whole production chain from ore, several science "
                      "packs, oil to plastic, 'beat the game'): run it as a project instead. A project manager then "
                      "gives the character one order at a time until the goal is met, checking progress between "
                      "them. Call it instead of submit_plan, then end your turn.",
     {"type": "object", "properties": {"goal": {"type": "string", "description": "the goal in the player's words, "
                                                "with any places and limits they gave"}}, "required": ["goal"]}),
    ("submit_plan", "Submit the plan for the actor to run now (replaces any running plan for this order). End your "
                    "turn after this.",
     {"type": "object", "properties": {
         "goal": {"type": "string"},
         "steps": {"type": "array", "items": {"type": "object"}},
         "expect": {"type": "array", "items": {"type": "object"}},
         "say": {"type": "string"},
         "done_text": {"type": "string"},
         "watch": {"type": "array", "items": {"type": "string"},
                   "description": "optional: problems to keep an eye out for at this build afterwards, in words "
                                  "(e.g. 'the output chest is full', 'the boiler is out of coal')"},
         "force": {"type": "boolean", "description": "run it even though the checker reported problems"},
         "more": {"type": "boolean", "description": "true = this is one finished part of a bigger order and you will "
                                                    "submit the next part right after: the actor starts building it now "
                                                    "while you design the rest"}},
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
    limited_at: float = 0.0  # when the limit was last hit (it lifts after a while: tried again after RETRY_LIMIT)


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
                        elif n == "block_info":
                            from . import blueprints as bp
                            try:
                                out = bp.stamp_text(bp.stamp(args["name"], float(args["x"]), float(args["y"]),
                                                             args.get("rotation", 0)))
                            except Exception as e:  # noqa: BLE001
                                out = f"error: {e}"
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
        from . import blueprints as bp
        system += ("\n\nBuilt-in blocks (game-tested layouts; place with a block step, check ports with block_info; "
                   "a block's input belt must be fed by a belt that ends right at its input tile):\n" + bp.summary_text())
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
        self._options = ClaudeAgentOptions(**kw)
        await self._connect()
        self._task = asyncio.create_task(self._loop())

    async def _connect(self) -> None:
        from claude_agent_sdk import ClaudeSDKClient
        self.client = ClaudeSDKClient(self._options)
        await self.client.connect()
        self._session_cost = 0.0

    async def _restart(self) -> None:
        """A broken session (the CLI died, a stream error): start a fresh one. The conversation is lost; lessons,
        designs and the actor's reports carry what matters."""
        try:
            await self.client.disconnect()
        except Exception:  # noqa: BLE001
            pass
        try:
            await self._connect()
            self.log_fn({"t": time.time(), "kind": "thinker_restart"})
        except Exception as e:  # noqa: BLE001
            self.log_fn({"t": time.time(), "kind": "thinker_error", "error": f"restart failed: {e!r}"})

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
        # force skips the checker only after it has reported something this turn: a first submission is always
        # checked (Opus had taken to forcing big parts unchecked, and one ran a belt through a crash-site wreck)
        if self.lint_fn and self.lint_rounds < 2 and (not args.get("force") or self.lint_rounds == 0):
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
        self._last_more = bool(args.get("more"))
        await self.on_plan(args, self.current)
        if self._last_more:
            return (f"part accepted ({len(steps)} steps); the actor is building it now. Design the next part and "
                    "submit it (more=true again if there's still more after it; leave it out on the last part).")
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
                if "session limit" in repr(e).lower() or "usage limit" in repr(e).lower():
                    # the subscription's limit arrives as an error result, not as text: mark it, so orders wait for
                    # the retry instead of each burning its replans in seconds (11:20 limit: orders failed in bursts)
                    self.stats.usage_limited = True
                    self.stats.limited_at = time.time()
                await self._restart()
                # whoever waits on this request gets a no-plan answer instead of waiting forever
                try:
                    await self.on_plan({"goal": None, "steps": [], "no_plan": True, "error": repr(e)[:200]}, req)
                except Exception:  # noqa: BLE001
                    pass
            finally:
                self.busy = False
                self.current = None

    async def _turn(self, prompt: str, req: Request) -> None:
        from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

        t0 = time.time()
        self._plan_submitted = False
        self._last_more = False
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
                        if self._plan_submitted and not interrupted and not getattr(self, "_last_more", False):
                            interrupted = True  # the plan is in; the commentary after it only costs time
                            try:
                                await self.client.interrupt()
                            except Exception:  # noqa: BLE001
                                pass
                        if "usage limit" in b.text.lower() or "hit your session limit" in b.text:
                            self.stats.usage_limited = True
                            self.stats.limited_at = time.time()
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
