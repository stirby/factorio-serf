"""Late-game tools: bottleneck diagnosis, copy/paste of existing builds, planners, the logistic network.

None needs the character in reach (a player does these from the map), so the foreman can use them too.
"""
from __future__ import annotations

import math

import json
import time
from typing import TYPE_CHECKING

from .rcon import GameError
from .tools import BY_NAME, XY, Tool, _j, _num, _obj, power_note, zone_box

if TYPE_CHECKING:
    from .agent import Agent

AREA = {"x1": {"type": "number"}, "y1": {"type": "number"}, "x2": {"type": "number"}, "y2": {"type": "number"}}


def load_copies(state_dir) -> dict:
    path = state_dir / "copies.json"
    return json.loads(path.read_text()) if path.exists() else {}


def _copies(agent) -> dict:
    if not hasattr(agent.orch, "copies"):
        agent.orch.copies = load_copies(agent.orch.cfg.state_dir)
    return agent.orch.copies


def _save_copies(agent) -> None:
    (agent.orch.cfg.state_dir / "copies.json").write_text(json.dumps(agent.orch.copies))


def _status_line(by: dict) -> str:
    return ", ".join(f"{k} {v['n']}" + (f" (e.g. {' '.join(f'[gps={p[0]},{p[1]}]' for p in v['at'][:2])})"
                                          if k != "working" else "")
                     for k, v in sorted(by.items(), key=lambda kv: -kv[1]["n"])) or "none"


async def t_diagnose(agent: "Agent", a: dict) -> str:
    d = await agent.link.call("diagnose", item=a.get("item", "iron-plate"), surface=a.get("surface", "nauvis"))
    p, c = d["producers"], d["consumers"]
    lines = [f"{d['item']} on {d['surface']}: made {d['made_per_min']}/min, used {d['used_per_min']}/min "
             f"(10-min avg {d['made_per_min_10m']} / {d['used_per_min_10m']})",
             f"producers {p['total']}: {_status_line(p['by_status'])}",
             "  sites: " + "; ".join(f"[gps={s['at'][0]},{s['at'][1]}] {s['working']}/{s['machines']} working"
                                     for s in p["sites"]),
             f"consumers {c['total']}: {_status_line(c['by_status'])}"]
    if d.get("ingredients"):
        lines.append("ingredients: " + "; ".join(f"{k} made {v['made_per_min']}/used {v['used_per_min']} per min"
                                                for k, v in d["ingredients"].items()))
    if d.get("ore_under_drills") is not None:
        lines.append(f"ore left under drills: {d['ore_under_drills']}, nearly dry drills: {d['drills_nearly_dry']}")
    lines.append("LIKELY CAUSE: " + d["hint"])
    return "\n".join(lines)


async def t_copy(agent: "Agent", a: dict) -> str:
    _num(a, "x1", "y1", "x2", "y2")
    d = await agent.link.call("copy", x1=a["x1"], y1=a["y1"], x2=a["x2"], y2=a["y2"], surface=a.get("surface", "nauvis"))
    name = str(a.get("name") or f"copy-{int(time.time()) % 100000}")
    lib = _copies(agent)
    lib[name] = {"string": d["string"], "size": d["size"], "needs": d["needs"], "by": agent.name,
                 "from": [a["x1"], a["y1"], a["x2"], a["y2"]]}
    _save_copies(agent)
    kept = ""
    if a.get("note"):
        from . import blueprint_lib
        try:
            info = await agent.link.call("blueprint_info", string=d["string"])
            blueprint_lib.save_learned(name, d["string"], info, str(a["note"]),
                                       {"by": agent.name, "world": agent.orch.cfg.state_dir.name,
                                        "area": [a["x1"], a["y1"], a["x2"], a["y2"]]})
            kept = (f" Saved to your design library as '{name}' ({info['size'][0]}x{info['size'][1]}): in any world, "
                    f"build kind=stamp name={name} x y builds it.")
        except (ValueError, GameError) as e:
            kept = f" Not saved to your library: {e}"
    return (f"copied {d['entities']} entities as '{name}' (size {d['size'][0]}x{d['size'][1]}): {_j(d['by_name'])}. "
            f"To build one more you need {_j(d['needs'])}. paste name='{name}' x y (x,y = where its centre goes)."
            + kept)


async def t_paste(agent: "Agent", a: dict) -> str:
    _num(a, "x", "y")
    lib = _copies(agent)
    c = lib.get(str(a.get("name", "")))
    string = c["string"] if c else a.get("string")
    if not string:  # one of your library designs
        from . import blueprint_lib
        try:
            dsg = blueprint_lib.get_design(str(a.get("name", "")))
            string = dsg.get("string")
        except KeyError:
            pass
    if not string:
        return f"no copy named {a.get('name')!r}; copies: {', '.join(lib) or 'none'}"
    d = await agent.link.call("paste", string=string, x=a["x"], y=a["y"], direction=a.get("direction", "north"),
                              surface=a.get("surface", "nauvis"))
    miss = d["of"] - d["placed"]
    return (f"placed {d['placed']} of {d['of']} ghosts" + (f" ({miss} blocked by existing buildings or water: check the "
                                                           "spot with map)" if miss else "")
            + f"; to build them you need {_j(d['needs'])}. Robots build ghosts inside a roboport network if the "
            "items are in its storage; otherwise build_ghosts with the items.")


async def t_order(agent: "Agent", a: dict) -> str:
    _num(a, "x1", "y1", "x2", "y2")
    kw = {k: a[k] for k in ("kind", "x1", "y1", "x2", "y2", "from", "to", "name", "trees", "surface") if k in a}
    d = await agent.link.call("order", **kw)
    return f"{a.get('kind')}: {_j(d)}. Robots carry it out in a roboport network; by hand, mine / build_ghosts."


async def t_calc(agent: "Agent", a: dict) -> str:
    d = await agent.link.call("calc", item=a["item"], per_minute=float(a.get("per_minute", 60)),
                              supplied=a.get("supplied") or [], assembler=a.get("assembler"), furnace=a.get("furnace"),
                              drill=a.get("drill"))
    lines = [f"{d['per_minute']:g}/min {d['item']}:"]
    for st in d["steps"]:
        ins = ", ".join(f"{i['item']} {i['per_minute']:.4g}/min" for i in st["inputs"])
        n = st["machines"]
        lines.append(f"- {st['item']} {st['per_minute']:.4g}/min: {n:.2f} -> {math.ceil(n - 1e-9)} x {st['machine']}"
                     f" ({st['recipe']}; in: {ins})" + (" [recipe has other products too]" if st.get("other_products") else ""))
    for r in d["raw"]:
        extra = f": {r['drills']:.1f} x {r['drill']}" if r.get("drills") else ""
        tag = " (supplied)" if r.get("supplied") else " (no unlocked recipe)" if r.get("no_recipe") else ""
        lines.append(f"- raw {r['item']} {r['per_minute']:.4g}/min{tag}{extra}")
    lines.append(d["note"])
    return "\n".join(lines)


async def t_find_space(agent: "Agent", a: dict) -> str:
    d = await agent.link.call("find_space", w=a["w"], h=a["h"], x=a.get("x", 0), y=a.get("y", 0),
                              radius=a.get("radius", 120), allow_resources=bool(a.get("allow_resources")))
    if not d["candidates"]:
        return f"no free {d['w']}x{d['h']} area within the search near {d['near']} (tried {d['searched']} spots): widen radius"
    out = [f"free {d['w']}x{d['h']} areas near [gps={d['near'][0]},{d['near'][1]}], nearest first:"]
    for c in d["candidates"]:
        tl, ce = c["top_left"], c["center"]
        out.append(f"- top-left ({tl[0]},{tl[1]}) to ({tl[0] + d['w']},{tl[1] + d['h']}), center [gps={ce[0]:g},{ce[1]:g}], "
                   f"{c['dist']} tiles away" + (f", {c['trees_rocks']} trees/rocks (build clears them)" if c["trees_rocks"] else ""))
    return "\n".join(out)


async def t_network(agent: "Agent", a: dict) -> str:
    d = await agent.link.call("network", surface=a.get("surface", "nauvis"))
    if not d["networks"]:
        return f"no logistic network on {a.get('surface', 'nauvis')} (no roboports). Ghosts waiting: {d['ghosts']}"
    lines = []
    for n in d["networks"]:
        lines.append(f"network {n['id']} ({n['roboports']} roboports near [gps={n['at'][0]},{n['at'][1]}]): construction "
                     f"robots {n['idle_construction']}/{n['construction_robots']} idle, logistic "
                     f"{n['idle_logistic']}/{n['logistic_robots']} idle; storage: {_j(n['storage_items'])}")
    lines.append(f"ghosts waiting to be built: {d['ghosts']}; marked for deconstruction: {d.get('marked_for_deconstruction')}")
    return "\n".join(lines)


BUILD_SECONDS = 120  # one build call works this long at most, then returns; call again to continue


async def t_build(agent: "Agent", a: dict) -> str:
    """One call, minutes of work: the controller lays the plan and does every physical step without the model."""
    from types import SimpleNamespace

    from . import blueprint_lib
    from .controller import Controller
    kind = a.get("kind", "ghosts")
    plan = {k: a[k] for k in ("kind", "name", "x", "y", "direction", "rotation", "anchor", "item", "from", "to",
                              "join", "end_direction") if k in a}
    plan["kind"] = kind
    zone = a.get("zone")
    if isinstance(zone, str):
        zone = json.loads(zone)
    if kind == "stamp" and not zone:
        _num(a, "x", "y")
        (x1, y1), (x2, y2) = blueprint_lib.stamp(a["name"], a["x"], a["y"], a.get("rotation", 0), a.get("anchor"))["bbox"]
        zone = [x1, y1, x2, y2]
    if kind == "paste" and not zone:
        _num(a, "x", "y")
        c = _copies(agent).get(str(a.get("name", "")))
        if not c and str(a.get("name", "")) in blueprint_lib.names():
            c = blueprint_lib.get_design(str(a["name"]))
        if not c:
            return f"no copy named {a.get('name')!r}; copies: {', '.join(_copies(agent)) or 'none'}"
        w, h = c.get("size") or [16, 16]
        zone = [a["x"] - w / 2 - 1, a["y"] - h / 2 - 1, a["x"] + w / 2 + 1, a["y"] + h / 2 + 1]
    if kind in ("ghosts", "paste", "stamp") and not zone:
        return "give zone=[x1,y1,x2,y2] around the ghosts to build"
    if kind == "line" and not ({"from", "to"} <= set(a)):
        return "a line needs from=[x,y], to=[x,y] and item (a belt/pipe/pole, or the cargo it carries)"
    order = SimpleNamespace(plan=plan, zone=zone, laid=False, state_dir=agent.orch.cfg.state_dir)
    if kind == "paste":
        order.plan["name"] = a["name"]
    ctl = Controller(agent.link, agent.name, stop=lambda: agent.interrupted.is_set(),
                     deadline=time.time() + float(a.get("seconds", BUILD_SECONDS)))
    out = await (ctl.connect(order) if kind == "line" else ctl.fulfill(order))
    text = f"{out.kind}: {out.detail}"
    box = zone_box(zone) if zone else None
    if box and out.kind in ("done", "paused"):
        pw = await power_note(agent, **box)
        if pw:
            text += "\n" + pw
    if out.blocker:
        text += f"\nblocker: {json.dumps(out.blocker)[:700]}"
    return text


LATE_TOOLS = [
    Tool("build", "Do a whole build in one call; a controller does every physical step without you: lays the plan as "
         "ghosts, fetches items from chests (and machine outputs), crafts what's missing, mines stone/coal/ore if "
         "nobody has any, clears marked trees and rocks, builds every ghost, refuels burners in the zone. kind: "
         "stamp (name=<design from `designs`>, x, y = top-left, rotation), paste (name=<a `copy`>, x, y = centre, "
         "direction), ghosts (build ghosts already in zone=[x1,y1,x2,y2]: yours, a human's or a teammate's), line "
         "(item=belt/pipe/pole or the cargo it carries, from=[x,y], to=[x,y]; long routes are split into legs; to = a belt feeds into it, "
         "from = a line's last belt continues it). "
         "Works up to ~2 min, then returns; call again to continue (it resumes from what's left). Returns done, "
         "paused, or exactly what blocks it. Use it for any build bigger than a few pieces.",
         _obj({"kind": {"type": "string", "enum": ["stamp", "paste", "ghosts", "line"]}, "name": {"type": "string"},
               "x": {"type": "number"}, "y": {"type": "number"}, "rotation": {}, "direction": {"type": "string"},
               "zone": {"type": "array"}, "item": {"type": "string"}, "from": {"type": "array"},
               "to": {"type": "array"}, "join": {"type": "boolean"}}, ["kind"]), t_build),
    Tool("diagnose", "Why is an item or fluid (petroleum-gas, steam, water...) short? Made vs used per minute, every machine that makes or uses it grouped by "
         "status (working, no_ingredients, full_output, no_power, no_minable_resources...) with sites and example "
         "positions, its ingredients' flow, and the likely cause. Start every bottleneck hunt here, then follow "
         "the cause upstream (diagnose the ingredient).",
         _obj({"item": {"type": "string"}, "surface": {"type": "string"}}, ["item"]), t_diagnose),
    Tool("copy", "Copy an existing build (an area) as a named blueprint, like ctrl+C, to paste more of a design "
         "that already works here (a smelting column, a science block). Returns its size and the items it needs. "
         "With a note (what it makes, its rate, where inputs enter and outputs leave), it also goes into your "
         "design library, kept across worlds: do that for every build you've verified works, so next time it's "
         "one `build kind=stamp` call.",
         _obj({**AREA, "name": {"type": "string"}, "note": {"type": "string"}}, ["x1", "y1", "x2", "y2"]), t_copy),
    Tool("paste", "Place a copied build (name) as ghosts with its centre at x,y, optionally rotated (direction). "
         "Instant, from anywhere, like placing a blueprint in map view. Robots build it in a roboport network; "
         "otherwise build_ghosts carrying the items. Check the spot is clear (map) first.",
         _obj({"name": {"type": "string"}, "x": {"type": "number"}, "y": {"type": "number"},
               "direction": {"type": "string"}}, ["name", "x", "y"]), t_paste),
    Tool("order", "Planners over an area: kind=deconstruct (optional name=<entity>, trees=true also clears trees and "
         "rocks), kind=upgrade from=<entity> to=<entity> (e.g. transport-belt -> fast-transport-belt, "
         "stone-furnace -> steel-furnace), kind=cancel. Robots do the work in a roboport network.",
         _obj({"kind": {"type": "string", "enum": ["deconstruct", "upgrade", "cancel"]}, **AREA,
               "from": {"type": "string"}, "to": {"type": "string"}, "name": {"type": "string"},
               "trees": {"type": "boolean"}}, ["kind", "x1", "y1", "x2", "y2"]), t_order),
    Tool("calc", "Ratio calculator from the game's recipes (what's unlocked now): machines and inputs for "
         "per_minute of an item, down to raw ore with drill counts. supplied = items you already have on a belt or "
         "bus (stops expanding there). Use it before building any production block, like a player with a calculator.",
         _obj({"item": {"type": "string"}, "per_minute": {"type": "number"},
               "supplied": {"type": "array", "items": {"type": "string"}},
               "assembler": {"type": "string"}, "furnace": {"type": "string"}, "drill": {"type": "string"}}, ["item"]),
         t_calc),
    Tool("find_space", "Free ground for a w x h block (tiles) near x,y: no buildings, water, cliffs, ghosts or ore "
         "(unless allow_resources). Faster than reading a map when you just need room for a build; then stamp/paste "
         "there.", _obj({"w": {"type": "integer"}, "h": {"type": "integer"}, **XY, "radius": {"type": "integer"},
                         "allow_resources": {"type": "boolean"}}, ["w", "h", "x", "y"]), t_find_space),
    Tool("network", "The logistic network(s): roboports, construction/logistic robots (idle/total), what's in "
         "storage, ghosts waiting, deconstruction pending. Check it before relying on robots to build.",
         _obj({"surface": {"type": "string"}}), t_network),
]
for _t in LATE_TOOLS:
    BY_NAME[_t.name] = _t
