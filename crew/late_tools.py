"""Late-game tools: bottleneck diagnosis, copy/paste of existing builds, planners, the logistic network.

None needs the character in reach (a player does these from the map), so the foreman can use them too.
"""
from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

from .tools import BY_NAME, Tool, _j, _num, _obj

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
    return (f"copied {d['entities']} entities as '{name}' (size {d['size'][0]}x{d['size'][1]}): {_j(d['by_name'])}. "
            f"To build one more you need {_j(d['needs'])}. paste name='{name}' x y (x,y = where its centre goes).")


async def t_paste(agent: "Agent", a: dict) -> str:
    _num(a, "x", "y")
    lib = _copies(agent)
    c = lib.get(str(a.get("name", "")))
    string = c["string"] if c else a.get("string")
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


LATE_TOOLS = [
    Tool("diagnose", "Why is an item short? Made vs used per minute, every machine that makes or uses it grouped by "
         "status (working, no_ingredients, full_output, no_power, no_minable_resources...) with sites and example "
         "positions, its ingredients' flow, and the likely cause. Start every bottleneck hunt here, then follow "
         "the cause upstream (diagnose the ingredient).",
         _obj({"item": {"type": "string"}, "surface": {"type": "string"}}, ["item"]), t_diagnose),
    Tool("copy", "Copy an existing build (an area) as a named blueprint, like ctrl+C, to paste more of a design "
         "that already works here (a smelting column, a science block). Returns its size and the items it needs.",
         _obj({**AREA, "name": {"type": "string"}}, ["x1", "y1", "x2", "y2"]), t_copy),
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
    Tool("network", "The logistic network(s): roboports, construction/logistic robots (idle/total), what's in "
         "storage, ghosts waiting, deconstruction pending. Check it before relying on robots to build.",
         _obj({"surface": {"type": "string"}}), t_network),
]
for _t in LATE_TOOLS:
    BY_NAME[_t.name] = _t
