"""Agent tools, backend-agnostic: (name, description, JSON schema, async handler(agent, args) -> str)."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from .rcon import GameError, RconError

if TYPE_CHECKING:
    from .agent import Agent

ACT_WAIT_MAX = 75  # seconds a single act/wait call may block before returning progress


@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    handler: Callable[["Agent", dict], Awaitable[str]]


def _j(x: Any) -> str:
    return json.dumps(x, separators=(",", ":"), ensure_ascii=False)


def _num(d: dict, *keys):
    for k in keys:
        if k in d and isinstance(d[k], str):
            try:
                d[k] = float(d[k])
            except ValueError:
                pass


ACTION_DOC = """Queue actions for your character; they run in order, in real game time, obeying normal player rules
(reach, inventory, crafting time). Each action walks into range by itself first. If one fails, the rest are skipped.
Ops and their fields:
  move        x,y [radius]  | player=<name> | agent=<name>      walk there (pathfinding)
  mine        name=<iron-ore|coal|stone|copper-ore|tree|rock|entity name> count=N   (nearest; ore count = items)
              or x,y to mine that one thing (pick up a building: add force_pickup=true only if a human asked)
  craft       recipe count [wait=false to queue and move on]   hand-craft (intermediates are crafted automatically)
  place       name x y [direction=north|east|south|west]        build from inventory
  insert      x y item [count]                                  put items into a machine/chest (fuel goes to fuel slot)
  take        x y [item] [count]                                take output (or a specific item) from a machine/chest
  set_recipe  x y recipe                                        assembler recipe
  rotate      x y [direction] | [reverse=true]
  research    tech                                              add a lab tech to the research queue
  connect     item=<transport-belt|pipe|small-electric-pole|...> from=[x,y] to=[x,y] [end_direction]
              routes a line around obstacles and places it (belts point along the route; poles spaced to reach)
  follow      player=<name> | agent=<name> [distance=3] [seconds=300]   stay near them until stopped
  wait        seconds
Coordinates: tile (x,y) spans x..x+1; 1x1 and 3x3 entities sit at .5 centers, 2x2 at integer corners (the game snaps).
Directions: inserters TAKE from the side they face and drop on the opposite side; drills drop one tile in front
(the result tells you exactly where); belts move items toward their direction."""


async def t_look(agent: "Agent", a: dict) -> str:
    d = await agent.link.call("observe", agent=agent.name, radius=min(int(a.get("radius", 16)), 48))
    agent.last_position = d["self"]["position"]
    return _j(d)


async def t_map(agent: "Agent", a: dict) -> str:
    _num(a, "x", "y")
    kw = {"agent": agent.name, "radius": min(int(a.get("radius", 12)), 24)}
    if "x" in a and "y" in a:
        kw["center"] = [a["x"], a["y"]]
    d = await agent.link.call("map", **kw)
    legend = ", ".join(f"{k}={v}" for k, v in sorted(d["legend"].items()))
    x0, y0 = d["top_left"]
    width = len(d["rows"][0]) if d["rows"] else 0
    header = "     " + "".join(str((x0 + i) % 10) for i in range(width))
    rows = [f"{y0 + j:>4} {r}" for j, r in enumerate(d["rows"])]
    return (f"Map, top-left tile ({x0},{y0}). Header digit = x mod 10, left column = y.\n{d['note']}\n"
            f"legend: {legend}\n{header}\n" + "\n".join(rows))


async def t_find(agent: "Agent", a: dict) -> str:
    kw = {k: a[k] for k in ("name", "type", "limit", "max_radius") if k in a}
    return _j(await agent.link.call("find", agent=agent.name, **kw))


async def t_inspect(agent: "Agent", a: dict) -> str:
    _num(a, "x", "y")
    return _j(await agent.link.call("inspect", agent=agent.name, x=a["x"], y=a["y"], radius=a.get("radius", 1)))


async def t_recipes(agent: "Agent", a: dict) -> str:
    kw = {k: a[k] for k in ("filter", "detail") if k in a}
    return _j(await agent.link.call("recipes", agent=agent.name, **kw))


async def t_techs(agent: "Agent", a: dict) -> str:
    kw = {k: a[k] for k in ("filter",) if k in a}
    w = await agent.link.call("world", agent=agent.name)
    t = await agent.link.call("techs", agent=agent.name, **kw)
    return _j({"researching": w.get("research"), "queue": w.get("research_queue"), **t})


async def t_production(agent: "Agent", a: dict) -> str:
    return _j(await agent.link.call("production", agent=agent.name))


async def _wait_jobs(agent: "Agent", ids: list[int], timeout: float) -> tuple[list[dict], list[int]]:
    """Wait for jobs; return early if a human addresses this agent. Returns (results, still_running)."""
    futs = {i: agent.link.job_future(i) for i in ids}
    interrupt = asyncio.create_task(agent.interrupted.wait())
    try:
        pending = set(futs.values())
        deadline = asyncio.get_running_loop().time() + timeout
        while pending:
            left = deadline - asyncio.get_running_loop().time()
            if left <= 0:
                break
            done, pending = await asyncio.wait(pending | {interrupt}, timeout=left,
                                               return_when=asyncio.FIRST_COMPLETED)
            pending.discard(interrupt)
            if interrupt in done:
                break
    finally:
        interrupt.cancel()
    results, running = [], []
    for i, f in futs.items():
        if f.done():
            results.append(f.result())
            agent.pending_jobs.discard(i)
            agent.finished.pop(i, None)
        else:
            running.append(i)
    return results, running


def _fmt_results(results: list[dict]) -> list[str]:
    out = []
    for r in results:
        line = f"#{r['id']} {r['op']}: {'OK' if r.get('ok') else 'FAILED'} {r.get('msg', '')}"
        data = r.get("data")
        if data and isinstance(data, dict):
            extra = {k: v for k, v in data.items() if k not in ("unit_number",)}
            if extra:
                line += " " + _j(extra)
        out.append(line)
    return out


async def _after(agent: "Agent", results: list[dict], running: list[int]) -> str:
    lines = _fmt_results(results)
    if running:
        lines.append(f"still running: jobs {running} (call wait to keep waiting, or stop to cancel)")
    try:
        me = await agent.link.call("self", agent=agent.name)
        agent.last_position = me["position"]
        inv = me.get("inventory") or {}
        top = dict(sorted(inv.items(), key=lambda kv: -kv[1])[:20])
        lines.append(f"you: pos {me['position']}, inventory {_j(top)}"
                     + (f", crafting {me['crafting']}" if me.get("crafting") else ""))
    except GameError as e:
        lines.append(f"(status unavailable: {e})")
    return "\n".join(lines)


async def t_act(agent: "Agent", a: dict) -> str:
    actions = a.get("actions")
    if isinstance(actions, str):
        actions = json.loads(actions)
    if not actions:
        return "no actions given"
    for act in actions:
        _num(act, "x", "y", "count", "radius", "seconds")
        if "count" in act and isinstance(act["count"], float):
            act["count"] = int(act["count"])
    d = await agent.link.call("act", agent=agent.name, actions=actions, replace=bool(a.get("replace")))
    ids = d["job_ids"]
    agent.pending_jobs.update(ids)
    agent.note_activity(f"{len(ids)} action(s): " + ", ".join(x.get("op", "?") for x in actions))
    if a.get("wait") is False:
        return f"queued jobs {ids}; you'll be told when they finish"
    results, running = await _wait_jobs(agent, ids, min(float(a.get("timeout", ACT_WAIT_MAX)), ACT_WAIT_MAX))
    return await _after(agent, results, running)


async def t_wait(agent: "Agent", a: dict) -> str:
    secs = min(float(a.get("seconds", 30)), ACT_WAIT_MAX)
    ids = sorted(agent.pending_jobs)
    if ids:
        results, running = await _wait_jobs(agent, ids, secs)
        return await _after(agent, results, running)
    try:
        await asyncio.wait_for(agent.interrupted.wait(), timeout=secs)
    except asyncio.TimeoutError:
        pass
    return f"waited up to {secs:.0f}s (no jobs running)"


async def t_stop(agent: "Agent", a: dict) -> str:
    await agent.link.call("cancel", agent=agent.name, reason=a.get("reason", "stopped by agent"))
    agent.link.forget(agent.pending_jobs)
    agent.pending_jobs.clear()
    return "all your jobs are cancelled"


async def t_say(agent: "Agent", a: dict) -> str:
    text = str(a.get("text", "")).strip()
    if not text:
        return "nothing to say"
    await agent.say(text)
    return "said"


async def t_board(agent: "Agent", a: dict) -> str:
    return agent.board.render(for_agent=agent.name, limit=30)


async def t_post_task(agent: "Agent", a: dict) -> str:
    owner = a.get("assignee")
    if owner and owner not in agent.crew_names():
        return f"no crew member named {owner}; crew is {agent.crew_names()}"
    t = agent.board.post(agent.name, a["title"], a.get("detail", ""), owner)
    if owner and owner != agent.name:
        await agent.notify_peer(owner, f"{agent.name} assigned you task #{t.id}: {t.title}"
                                       + (f" -- {t.detail}" if t.detail else ""))
    return f"posted task #{t.id}"


async def t_update_task(agent: "Agent", a: dict) -> str:
    try:
        t = agent.board.update(agent.name, int(a["id"]), a.get("status"), a.get("note"), a.get("assignee"))
    except KeyError as e:
        return str(e)
    if t.created_by and t.created_by != agent.name and t.created_by in agent.crew_names() \
            and a.get("status") in ("done", "blocked"):
        await agent.notify_peer(t.created_by, f"{agent.name} marked task #{t.id} {t.status}: {t.title}"
                                              + (f" ({a['note']})" if a.get("note") else ""), wake=False)
    return f"task #{t.id} is {t.status}" + (f" @{t.owner}" if t.owner else "")


async def t_notes(agent: "Agent", a: dict) -> str:
    agent.set_notes(str(a.get("text", "")))
    return "notes saved (shown to you at the start of every turn)"


async def t_status(agent: "Agent", a: dict) -> str:
    mode = a.get("mode", "working")
    if mode not in ("working", "idle"):
        return "mode must be working or idle"
    await agent.set_status(str(a.get("text", "")), mode)
    return f"status set; mode={mode}" + ("" if mode == "working" else " (you'll sleep until someone needs you)")


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or []}


XY = {"x": {"type": "number"}, "y": {"type": "number"}}

TOOLS: list[Tool] = [
    Tool("look", "See yourself (position, inventory, current job), the world (research, players, crew) and "
         "what's around you: buildings with status/recipe/fuel/contents, ore patches, trees, rocks, enemies.",
         _obj({"radius": {"type": "integer", "description": "tiles, default 16, max 48"}}), t_look),
    Tool("map", "ASCII map of the area around you (or around x,y). Best for planning where to build.",
         _obj({"radius": {"type": "integer", "description": "default 12, max 24"}, **XY}), t_map),
    Tool("find", "Find the nearest entities/resources by prototype name (e.g. iron-ore, coal, crude-oil, "
         "stone-furnace) or type (e.g. tree, resource, assembling-machine), searching outward. "
         "name='water' finds the nearest water and returns ready offshore_pump_spots (position + direction).",
         _obj({"name": {"type": "string"}, "type": {"type": "string"}, "limit": {"type": "integer"},
               "max_radius": {"type": "integer"}}), t_find),
    Tool("inspect", "Details of whatever is at x,y: inventories, recipe, progress, status, ore amount.",
         _obj({**XY, "radius": {"type": "number"}}, ["x", "y"]), t_inspect),
    Tool("recipes", "Recipes your force can use now. filter = substring; detail=true adds ingredients/time.",
         _obj({"filter": {"type": "string"}, "detail": {"type": "boolean"}}), t_recipes),
    Tool("techs", "Research state and what can be researched next. Trigger techs unlock by doing "
         "something (e.g. craft 10 copper plates); others need science packs in labs.",
         _obj({"filter": {"type": "string"}}), t_techs),
    Tool("production", "Items per minute produced/consumed by the whole base on your surface.", _obj({}), t_production),
    Tool("act", ACTION_DOC + "\nBy default this blocks until the actions finish (up to ~75s) and returns results "
         "plus your position and inventory. wait=false returns immediately. replace=true cancels what you were "
         "doing first. If a human messages you while you wait, it returns early so you can answer.",
         _obj({"actions": {"type": "array", "items": {"type": "object", "properties": {
             "op": {"type": "string", "enum": ["move", "mine", "craft", "place", "insert", "take", "set_recipe",
                                               "rotate", "research", "connect", "follow", "wait"]}}, "required": ["op"],
             "additionalProperties": True}},
             "wait": {"type": "boolean"}, "replace": {"type": "boolean"}}, ["actions"]), t_act),
    Tool("wait", "Wait for your running jobs to finish (or just wait). Returns early if a human messages you.",
         _obj({"seconds": {"type": "number", "description": "max 75"}}), t_wait),
    Tool("stop", "Cancel all your queued and running actions.", _obj({"reason": {"type": "string"}}), t_stop),
    Tool("say", "Say something in game chat. Everyone sees it. Keep it short. Put locations as [gps=x,y].",
         _obj({"text": {"type": "string"}}, ["text"]), t_say),
    Tool("board", "Show the crew's shared task board.", _obj({}), t_board),
    Tool("post_task", "Add a task to the crew board, optionally assigning it to a crew member (they get pinged).",
         _obj({"title": {"type": "string"}, "detail": {"type": "string"}, "assignee": {"type": "string"}},
              ["title"]), t_post_task),
    Tool("update_task", "Update a board task: status claimed|done|blocked|cancelled|open, a progress note, "
         "or reassign.", _obj({"id": {"type": "integer"}, "status": {"type": "string"}, "note": {"type": "string"},
                               "assignee": {"type": "string"}}, ["id"]), t_update_task),
    Tool("notes", "Replace your private notes: plans, coordinates of things you built, what's left to do. "
         "They're shown to you at the start of every turn, so keep them current and short.",
         _obj({"text": {"type": "string"}}, ["text"]), t_notes),
    Tool("status", "Set the one-line status shown under your name in everyone's Crew panel, and your mode: "
         "'working' = you'll be woken again to keep going on your own; 'idle' = sleep until someone needs you.",
         _obj({"text": {"type": "string"}, "mode": {"type": "string", "enum": ["working", "idle"]}}, ["text"]),
         t_status),
]

BY_NAME = {t.name: t for t in TOOLS}


async def run_tool(agent: "Agent", name: str, args: dict) -> str:
    """Run a tool and append anything that arrived meanwhile (human chat, crew pings)."""
    tool = BY_NAME.get(name)
    if not tool:
        return f"unknown tool {name}"
    agent.log_tool(name, args)
    try:
        out = await tool.handler(agent, args or {})
    except GameError as e:
        out = f"game error: {e}"
    except RconError as e:
        out = f"lost connection to the game ({e}); try again in a few seconds"
    except (KeyError, ValueError, TypeError, json.JSONDecodeError) as e:
        out = f"bad arguments for {name}: {e!r}"
    extra = agent.drain_interrupts()
    if extra:
        out += "\n\n" + extra
    agent.log_tool_result(name, out)
    return out
