"""Agent tools, backend-agnostic: (name, description, JSON schema, async handler(agent, args) -> str)."""
from __future__ import annotations

import asyncio
import json
import time
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
(reach, inventory, crafting time). Each action walks into range by itself first. If one fails, the others still
run; add stop_on_fail=true to an action whose failure should cancel the ones after it.
Ops and their fields:
  move        x,y [radius]  | player=<name> | agent=<name>      walk there (pathfinding)
  mine        name=<iron-ore|coal|stone|copper-ore|tree|rock|entity name> count=N   (nearest; ore count = items)
              or x,y to mine that one thing (pick up a building: add force_pickup=true only if a human asked)
  craft       recipe count [wait=false to queue and move on]   hand-craft (intermediates are crafted automatically)
  place       name x y [direction=north|east|south|west]        build from inventory. Inserters: give
              pickup=[x,y] (the tile it takes from) or drop=[x,y] instead of a direction; that's always right
              underground-belt: place the entrance with type=input and the exit with type=output, both facing
              the direction items travel (max 4 tiles between them for yellow); the result says if they paired
  insert      x y item [count]                                  put items into a machine/chest (fuel goes to fuel slot)
  take        x y [item] [count]                                take output (or a specific item) from a machine/chest
  set_recipe  x y recipe                                        assembler recipe
  rotate      x y [direction] | [reverse=true]            reverse turns it around (180 degrees)
  research    tech [first=true | remove=true]                   add a lab tech to the research queue; first=true
              moves it (and its prerequisites) to the front; remove=true takes it out
  configure   x y requests={item:count} | filter=item|none [blacklist] | output_priority/input_priority=left|right|none
              requester/buffer chest requests, inserter filters (fast/bulk inserters), splitter filter/priorities;
              self=true requests={...} sets your own logistic requests (robots deliver once you're in a network)
  equip       armor=<armor item> and/or equipment=[items]       wear armor and fill its grid: exoskeletons for speed,
              personal-roboport + construction robots in inventory to build ghosts around you, batteries + power
  limit       x y slots                                         chest limit (the red X): inserters fill only the
              first N slots; slots=none clears it. Stops a chest hoarding what others need
  connect     item=<transport-belt|pipe|small-electric-pole|...> from=[x,y] to=[x,y] [end_direction] [join]
              routes a line around obstacles and places it (belts point along the route; poles spaced to reach)
  follow      player=<name> | agent=<name> [distance=3] [seconds=300]   stay near them until stopped
  build_ghosts [x y radius=32] [limit]       build ghosts (planned buildings) near a point with items you carry;
              reports what's missing. Ghosts placed by humans are their plans: build them first.
  blueprint   string=<blueprint string> x y [direction]  |  entities=[{name,x,y,direction,recipe}]
              lay ghosts (instant, like placing a blueprint); then build_ghosts. Good for big builds.
  clear_ghosts x y [radius=8] [name]        remove planned ghosts in an area at once (an abandoned plan, a wrong
              layout); don't mine ghosts one by one
  loot        [x y]                                         take everything back from the nearest corpse
  wait        seconds
Coordinates: tile (x,y) spans x..x+1; 1x1 and 3x3 entities sit at .5 centers, 2x2 at integer corners (the game snaps).
Directions: inserters TAKE from the side they face and drop on the opposite side; drills drop one tile in front
(the result tells you exactly where); belts move items toward their direction."""


async def t_look(agent: "Agent", a: dict) -> str:
    d = await agent.link.call("observe", agent=agent.name, radius=min(int(a.get("radius", 16)), 48))
    agent.last_position = d["self"]["position"]
    w = d.get("world") or {}
    if w.get("crew"):
        # Characters left in the save by earlier sessions stand there with nobody driving them: say so, or the
        # agent asks them for help and waits.
        live = set(agent.crew_names())
        parked = [c["name"] for c in w["crew"] if c["name"] not in live]
        w["crew"] = [c for c in w["crew"] if c["name"] in live]
        if parked:
            w["parked_characters"] = f"{', '.join(parked)}: left by earlier sessions; nobody is driving them"
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


async def _wait_jobs(agent: "Agent", ids: list[int], timeout: float, leave: int = 0) -> tuple[list[dict], list[int]]:
    """Wait for jobs; return early if a human addresses this agent, or once only `leave` jobs remain
    (so the model can plan the next batch while the character finishes the current one).
    Returns (results, still_running)."""
    futs = {i: agent.link.job_future(i) for i in ids}
    interrupt = asyncio.create_task(agent.interrupted.wait())
    try:
        pending = set(futs.values())
        deadline = asyncio.get_running_loop().time() + timeout
        while len(pending) > leave:
            if any(f.done() and not f.result().get("ok") for f in futs.values()):
                break  # a failure skips the rest; report it now
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


VITALS_EVERY = 180  # seconds between base readouts in tool results


async def vitals_line(agent: "Agent") -> str:
    try:
        v = await agent.link.call("vitals")
    except GameError:
        return ""
    agent.last_vitals = time.time()

    def kv(d):
        return " ".join(f"{k} {n}" for k, n in d.items()) or "none"
    research = (f"researching {v['research']} {v.get('progress', 0)}%" + (f" (+{v['queued']} queued)" if v.get("queued") else "")
                if v.get("research") else "NOTHING RESEARCHING")
    miss = v.get("labs_missing") or {}
    labs = f"labs {v['labs_working']}/{v['labs']} working" + (
        f", {v['labs_starved']} starved (missing " + ", ".join(f"{k.replace('-science-pack', '')} in {n}"
                                                             for k, n in miss.items()) + ")"
        if v.get("labs_starved") and miss else f", {v['labs_starved']} starved" if v.get("labs_starved") else "")
    return (f"[base] {research} | {labs} | science used/min {kv(v.get('science_used') or {})} "
            f"(made {kv(v.get('science_made') or {})}) | per min: " + kv(v.get("plates") or {}))


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
    if time.time() - getattr(agent, "last_vitals", 0) > VITALS_EVERY:
        v = await vitals_line(agent)
        if v:
            lines.append(v)
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
    mode = a.get("wait", "until_last")
    if mode is False or mode == "false":
        return f"queued jobs {ids}; you'll be told when they finish"
    leave = 1 if mode == "until_last" and len(ids) > 1 else 0
    results, running = await _wait_jobs(agent, ids, min(float(a.get("timeout", ACT_WAIT_MAX)), ACT_WAIT_MAX), leave)
    out = await _after(agent, results, running)
    if leave and running:
        out += "\n(your last action is still running: queue the next batch now; it starts right after)"
    return out


IDLE_WAIT_MAX = 20  # seconds a wait may last when the character has nothing at all to do


async def t_wait(agent: "Agent", a: dict) -> str:
    secs = min(float(a.get("seconds", 30)), ACT_WAIT_MAX)
    ids = sorted(agent.pending_jobs)
    if ids:
        leave = max(int(a.get("until_queue_below", 1)) - 1, 0)
        results, running = await _wait_jobs(agent, ids, secs, leave)
        return await _after(agent, results, running)
    crafting = False
    try:
        crafting = bool((await agent.link.call("self", agent=agent.name)).get("crafting"))
    except GameError:
        pass
    if not crafting:
        secs = min(secs, IDLE_WAIT_MAX)  # nothing running at all: the character is just standing there
    try:
        await asyncio.wait_for(agent.interrupted.wait(), timeout=secs)
    except asyncio.TimeoutError:
        pass
    out = f"waited {secs:.0f}s with no jobs running" + ("" if crafting else " and an empty crafting queue")
    if crafting:
        return out
    work = await open_work(agent)
    return (out + ". Your character is idle while you wait. Waiting for production? Queue "
            "crafts (wait=false) and do the next useful thing; you'll be interrupted when the answer lands."
            + (f"\n[open work]\n{work}" if work else ""))


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
    b = agent.board
    return (f"[roadmap]\n{b.render_roadmap()}\n[zones]\n{b.render_zones()}\n[tasks]\n"
            + b.render(for_agent=agent.name, limit=30))


async def t_post_task(agent: "Agent", a: dict) -> str:
    owner = a.get("assignee")
    if owner and owner not in agent.crew_names():
        return f"no crew member named {owner}; crew is {agent.crew_names()}"
    dw, zone = a.get("done_when"), a.get("zone")
    if isinstance(dw, str):
        dw = json.loads(dw)
    if isinstance(zone, str):
        zone = json.loads(zone)
    if zone is not None and len(zone) != 4:
        return "zone is [x1, y1, x2, y2]"
    t = agent.board.post(agent.name, a["title"], a.get("detail", ""), owner, dw, zone)
    if owner and owner != agent.name:
        await agent.notify_peer(owner, f"{agent.name} assigned you task #{t.id}: {t.title}"
                                       + (f" -- {t.detail}" if t.detail else ""))
    return f"posted task #{t.id}" + (" (the game checks done_when; it completes once that holds for 2 min)"
                                      if t.done_when else "")


async def t_update_task(agent: "Agent", a: dict) -> str:
    status = a.get("status")
    task = agent.board.tasks.get(int(a.get("id", 0)))
    if status == "done" and task and task.done_when:
        status = "verifying"  # the game decides; the check loop completes it or reopens it
    try:
        t = agent.board.update(agent.name, int(a["id"]), status, a.get("note"), a.get("assignee"))
    except KeyError as e:
        return str(e)
    if t.status == "verifying":
        c = t.check or {}
        return (f"task #{t.id} is verifying: it completes when its check holds for 2 min "
                f"(now: {'passing' if c.get('passed') else 'failing ' + json.dumps(c.get('results', []))[:300]}). "
                "Move on; you'll hear if it fails.")
    if t.created_by and t.created_by != agent.name and t.created_by in agent.crew_names() \
            and a.get("status") in ("done", "blocked"):
        await agent.notify_peer(t.created_by, f"{agent.name} marked task #{t.id} {t.status}: {t.title}"
                                              + (f" ({a['note']})" if a.get("note") else ""), wake=False)
    return f"task #{t.id} is {t.status}" + (f" @{t.owner}" if t.owner else "")


async def t_zone(agent: "Agent", a: dict) -> str:
    if a.get("release"):
        return "released" if agent.board.release_zone(a["name"]) else f"no zone {a['name']}"
    area = a.get("area")
    if isinstance(area, str):
        area = json.loads(area)
    if not area or len(area) != 4:
        return "area must be [x1, y1, x2, y2]"
    z, overlaps = agent.board.claim_zone(agent.name, a["name"], [float(v) for v in area], a.get("purpose", ""))
    msg = f"zone {z.name} is yours: {z.area}"
    if overlaps:
        msg += f". WARNING: overlaps {', '.join(overlaps)}; agree with them or move it"
    return msg + "\n[zones]\n" + agent.board.render_zones()


async def t_roadmap(agent: "Agent", a: dict) -> str:
    if a.get("goals"):
        goals = a["goals"]
        if isinstance(goals, str):
            goals = json.loads(goals)
        agent.board.set_roadmap(agent.name, [str(g) for g in goals])
    if a.get("mark") is not None:
        try:
            m = agent.board.mark_milestone(int(a["mark"]), a.get("status", "done"))
        except (IndexError, ValueError):
            return "no such milestone"
        if m["status"] == "done":
            agent.orch.milestone_done(agent.name, m["goal"])
    return agent.board.render_roadmap()


async def t_mark(agent: "Agent", a: dict) -> str:
    if a.get("remove") is not None:
        await agent.link.call("unmark", id=int(a["remove"]))
        return "mark removed"
    _num(a, "x", "y")
    kw = {k: a[k] for k in ("kind", "x", "y", "text", "requests") if k in a}
    m = await agent.link.call("mark", agent=agent.name, **kw)
    return f"mark #{m['id']} placed; everyone sees it on the map"


def _fmt_marks(marks: list[dict]) -> str:
    lines = []
    for m in marks:
        line = f"#{m['id']} {m['kind']} [gps={m['p'][0]},{m['p'][1]}] {m['text']} (by {m['by']})"
        if m.get("missing"):
            line += f" NEEDS {_j(m['missing'])}"
        elif m.get("contents") and m["kind"] in ("provider", "storage"):
            top = dict(sorted(m["contents"].items(), key=lambda kv: -kv[1])[:8])
            line += f" has {_j(top)}"
        if m.get("warning"):
            line += f" ({m['warning']})"
        lines.append(line)
    return "\n".join(lines) or "(no marks)"


async def open_work(agent: "Agent") -> str:
    """What needs doing right now, in the order an idle logistic robot would pick it up."""
    parts = []
    try:
        marks = (await agent.link.call("marks"))["marks"]
    except GameError:
        marks = []
    req = [m for m in marks if m["kind"] == "requester" and m.get("missing")]
    if req:
        parts.append("Unfilled requests (deliver from providers, your inventory, or craft):\n" + _fmt_marks(req))
    try:
        g = await agent.link.call("ghosts")
        if g.get("count"):
            parts.append(f"Unbuilt ghosts: {g['count']} (e.g. at [gps={g['example'][0]},{g['example'][1]}]), "
                         f"items needed: {_j(g['needs'])}")
    except GameError:
        pass
    tasks = [t for t in agent.board.active() if t.status == "open" or t.owner == agent.name]
    if tasks:
        parts.append("Tasks: " + "; ".join(f"#{t.id} {t.title}" + (f" @{t.owner}" if t.owner else " (open)")
                                         for t in tasks[:8]))
    nxt = [m for m in agent.board.roadmap if m["status"] != "done"][:2]
    if nxt:
        parts.append("Roadmap next: " + "; ".join(m["goal"] for m in nxt))
    return "\n".join(parts)


async def t_work(agent: "Agent", a: dict) -> str:
    w = await open_work(agent)
    return w or "nothing open: pick the biggest bottleneck you can see (use production) and fix it"


async def t_marks(agent: "Agent", a: dict) -> str:
    return _fmt_marks((await agent.link.call("marks"))["marks"])


async def t_designs(agent: "Agent", a: dict) -> str:
    from . import blueprint_lib
    return ("Proven designs (validated in game). Stamp one with `stamp`, then build it with build_ghosts.\n"
            + blueprint_lib.summary_text())


async def t_stamp(agent: "Agent", a: dict) -> str:
    from . import blueprint_lib
    _num(a, "x", "y")
    st = blueprint_lib.stamp(a["name"], a["x"], a["y"], a.get("rotation", 0), a.get("anchor"))
    bb = st["bbox"]
    (x1, y1), (x2, y2) = bb  # [[x1, y1], [x2, y2]]
    chk = await agent.link.call("blockers", x1=x1, y1=y1, x2=x2, y2=y2)
    if chk.get("blockers") or chk.get("water_tiles"):
        return (f"area x {x1}..{x2}, y {y1}..{y2} isn't clear: "
                + (f"blocked by {', '.join(chk['blockers'])}" if chk.get("blockers") else "")
                + (f" {chk['water_tiles']} water tiles" if chk.get("water_tiles") else "")
                + ". Pick another spot (map/find help) or rotate it.")
    d = await agent.link.call("act", agent=agent.name, actions=[{"op": "blueprint", "entities": st["entities"]}])
    r = await asyncio.wait_for(agent.link.job_future(d["job_ids"][0]), 20)
    if not r.get("ok"):
        return f"stamp failed: {r.get('msg')}"
    note = ""
    if chk.get("trees_or_rocks"):
        note = f"\n{chk['trees_or_rocks']} trees/rocks are in the area; mine them if build_ghosts reports blocked ghosts."
    return (f"stamped {a['name']} as {r.get('data', {}).get('ghosts')} ghosts.\n" + blueprint_lib.stamp_text(st)
            + note + "\nNext: get the items (depot/craft) and build_ghosts there; then connect its inputs/outputs.")


async def t_notes(agent: "Agent", a: dict) -> str:
    agent.set_notes(str(a.get("text", "")))
    return "notes saved (shown to you at the start of every turn)"


async def t_status(agent: "Agent", a: dict) -> str:
    mode = a.get("mode", "working")
    await agent.set_status(str(a.get("text", "")), "idle" if mode == "idle" else "working")
    owned = [t for t in agent.board.active() if t.owner == agent.name and t.status in ("open", "claimed")]
    if mode == "idle" and owned:
        return f"status set; you still own task #{owned[0].id}, so you'll keep working on it"
    return "status set" + ("; you'll sleep until there's work for you" if mode == "idle" else "")


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
    Tool("act", ACTION_DOC + "\nwait='until_last' (default) returns as soon as only the last action is still "
         "running, with results so far plus your position and inventory, so you plan and queue the next batch "
         "while your character keeps working. wait=true blocks until all finish (up to ~75s): use it when the next "
         "step depends on the last action's result. wait=false returns immediately. Results of jobs you didn't "
         "wait for arrive with your next tool call. New actions queue behind running ones; replace=true cancels "
         "what you were doing first. If a human messages you, it returns early.",
         _obj({"actions": {"type": "array", "items": {"type": "object", "properties": {
             "op": {"type": "string", "enum": ["move", "mine", "craft", "place", "insert", "take", "set_recipe",
                                               "rotate", "research", "limit", "configure", "equip", "connect", "follow", "build_ghosts", "blueprint", "clear_ghosts", "loot", "wait"]}}, "required": ["op"],
             "additionalProperties": True}},
             "wait": {"description": "true | false | 'until_last'"}, "replace": {"type": "boolean"}}, ["actions"]),
         t_act),
    Tool("wait", "Wait for your running jobs (or just wait). until_queue_below=2 returns when one job is left, "
         "so you can queue more without your character going idle. Returns early if a human messages you.",
         _obj({"seconds": {"type": "number", "description": "max 75"},
               "until_queue_below": {"type": "integer"}}), t_wait),
    Tool("stop", "Cancel all your queued and running actions.", _obj({"reason": {"type": "string"}}), t_stop),
    Tool("say", "Say something in game chat. Everyone sees it. Keep it short. Put locations as [gps=x,y].",
         _obj({"text": {"type": "string"}}, ["text"]), t_say),
    Tool("board", "Show the crew's shared task board.", _obj({}), t_board),
    Tool("post_task", "Add a task to the crew board, optionally assigning it to a crew member (they get pinged). "
         "Give outcomes with a check the game evaluates: done_when=[{\"rate\": {\"item\": \"copper-plate\", "
         "\"min\": 300}}] (base-wide per minute made; \"kind\": \"used\" for consumed), {\"working\": {\"name\": \"lab\", \"min\": 8}} or {\"exists\": "
         "{...}} (counted inside zone=[x1,y1,x2,y2], or add \"scope\": \"base\"), {\"ghosts_cleared\": true} (zone). "
         "The task completes only when the check holds for 2 minutes, so a momentary fix doesn't count.",
         _obj({"title": {"type": "string"}, "detail": {"type": "string"}, "assignee": {"type": "string"},
               "done_when": {"type": "array"}, "zone": {"type": "array"}}, ["title"]), t_post_task),
    Tool("update_task", "Update a board task: status claimed|done|blocked|cancelled|open, a progress note, "
         "or reassign.", _obj({"id": {"type": "integer"}, "status": {"type": "string"}, "note": {"type": "string"},
                               "assignee": {"type": "string"}}, ["id"]), t_update_task),
    Tool("zone", "Claim a construction site: the area you're about to build in, so parallel builders don't place "
         "on top of each other. e.g. name='iron-column-2' area=[x1,y1,x2,y2] purpose='12 furnaces'. Claims lapse "
         "after 30 min (claim again to renew); release=true frees it when you're done. Not territory: anyone may "
         "expand anywhere that isn't an active site.", _obj({"name": {"type": "string"}, "area": {"type": "array", "items": {"type": "number"}},
                                   "purpose": {"type": "string"}, "release": {"type": "boolean"}}, ["name"]), t_zone),
    Tool("roadmap", "The crew's shared milestones. goals=[...] sets the list (lead's job; keep existing wording to "
         "keep status); mark=<index> status=doing|done updates one. With no args, shows it.",
         _obj({"goals": {"type": "array", "items": {"type": "string"}}, "mark": {"type": "integer"},
               "status": {"type": "string", "enum": ["todo", "doing", "done"]}}), t_roadmap),
    Tool("designs", "List the crew's proven blueprint designs (smelting column, red/green science, lab row, "
         "gears+circuits, steam power) with size, throughput, inputs/outputs and build materials.", _obj({}),
         t_designs),
    Tool("stamp", "Lay a proven design as ghosts at x,y (its top-left corner), rotation 0/90/180/270 or a direction. "
         "Checks the area is clear first. For steam power use anchor='offshore-pump' with x,y and rotation from "
         "find name=water's offshore_pump_spots. Then build_ghosts and hook up its inputs/outputs.",
         _obj({"name": {"type": "string"}, **XY, "rotation": {}, "anchor": {"type": "string"}},
              ["name", "x", "y"]), t_stamp),
    Tool("mark", "Annotate the world for everyone, like logistic chests: kind=provider (shared surplus, take "
         "freely), requester (requests={item: count} to be delivered here), storage (overflow) or note "
         "(any label, e.g. 'main bus starts here'). Shows on the map for humans too. remove=<id> deletes one.",
         _obj({"kind": {"type": "string", "enum": ["provider", "requester", "storage", "note"]}, **XY,
               "text": {"type": "string"}, "requests": {"type": "object"}, "remove": {"type": "integer"}}), t_mark),
    Tool("marks", "All world marks with live chest contents and unfilled requests.", _obj({}), t_marks),
    Tool("work", "What needs doing now: unfilled requests, unbuilt ghosts, open tasks, next roadmap goals. "
         "Call it whenever you're between jobs instead of waiting for direction.", _obj({}), t_work),
    Tool("notes", "Replace your private notes: plans, coordinates of things you built, what's left to do. "
         "They're shown to you at the start of every turn, so keep them current and short.",
         _obj({"text": {"type": "string"}}, ["text"]), t_notes),
    Tool("status", "Set the one-line status shown under your name in everyone's Crew panel. mode='idle' only when "
         "you own no open task and there's nothing useful to do; you keep working while you own a task.",
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
    done = drain_finished(agent)
    if done:
        out += "\n\n" + done
    extra = agent.drain_interrupts()
    if extra:
        out += "\n\n" + extra
    agent.log_tool_result(name, out)
    return out


def drain_finished(agent: "Agent") -> str:
    """Jobs that finished while the model was busy with other tool calls: failures in full, successes counted."""
    fin = getattr(agent, "finished", None)
    if not fin:
        return ""
    results = list(fin.values())
    fin.clear()
    agent.pending_jobs.difference_update(r["id"] for r in results)
    bad = [r for r in results if not r.get("ok")]
    good = len(results) - len(bad)
    lines = [f"[earlier jobs] {good} finished OK" + (f", {len(bad)} FAILED:" if bad else "")]
    lines += _fmt_results(bad[:6])
    return "\n".join(lines)
