"""'Two more just like it': copies of something the character built for an earlier order, without the planner. Jev says
whether the order asks for more of the same; code matches the new order's points against the earlier order's points
(the same shape, shifted: an ore belt and its chest, say) to find where each copy goes, then lays what the character
built there, shifted, as one ghost layout per copy."""
from __future__ import annotations

from .typesafe import Jev, noul
from .world import World


def offsets(orig: list, new: list, tol: float = 1.5, spacing: float = 0) -> list[tuple[float, float]]:
    """Shifts d such that every original point moved by d lands on a new point, covering the new points; [] if the
    new points aren't copies of the original shape. With spacing (the build's size), an order that names only one
    point per copy ("ore belts at A, B, C and D, each with its chest at the bottom") works too: each new point is the
    original's first point moved, provided they're at least that far apart (copies can't overlap)."""
    if not orig or not new:
        return []
    full = _offsets(orig, new, tol)
    if full or not spacing:
        return full
    o0 = orig[0]
    if all(max(abs(a[0] - b[0]), abs(a[1] - b[1])) >= spacing for i, a in enumerate(new) for b in new[i + 1:]):
        return [(q[0] - o0[0], q[1] - o0[1]) for q in new
                if not (abs(q[0] - o0[0]) < 1 and abs(q[1] - o0[1]) < 1)]
    return []


def _offsets(orig: list, new: list, tol: float) -> list[tuple[float, float]]:
    """Shifts that put 2+ of the original points on new points (the earlier order may also have named shared things,
    a supply chest or a grid pole, that the new one doesn't repeat), chosen until every new point is covered."""
    def near(a, b):
        return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol
    cands: dict = {}
    for p in orig:
        for q in new:
            d = (q[0] - p[0], q[1] - p[1])
            if abs(d[0]) < 1 and abs(d[1]) < 1 or any(near(d, e) for e in cands):
                continue
            cands[d] = frozenset(i for i, n in enumerate(new) for pp in orig if near((pp[0] + d[0], pp[1] + d[1]), n))
    chosen, covered = [], set()
    for d, hits in sorted(cands.items(), key=lambda kv: (-len(kv[1]), abs(kv[0][0]) + abs(kv[0][1]))):
        if len(hits) >= 2 and not hits & covered:  # copies are disjoint: one that shares a point would overlap
            chosen.append(d)
            covered |= hits
    return chosen if chosen and len(covered) == len(new) else []


def entry(e: dict) -> dict:
    """A scanned entity as a layout entry (name, position, direction, recipe, underground type)."""
    d = {"name": e["n"], "x": e["x"], "y": e["y"]}
    if e.get("d"):
        d["direction"] = e["d"]
    if e.get("r") and e.get("t") == "assembling-machine":
        d["recipe"] = e["r"]
    if e.get("ug"):
        d["type"] = e["ug"]
    return d


def layout_entries(ents: dict) -> dict:
    return {u: entry(e) for u, e in ents.items()}


def built_by(w: World, box: tuple, me: str) -> list[dict]:
    """What `me` built inside box (x0, y0, x1, y1), as layout entries."""
    x0, y0, x1, y1 = box
    return [entry(e) for e in w.ents.values()
            if e.get("by") == me and e["u"] > 0 and x0 <= e["x"] <= x1 and y0 <= e["y"] <= y1]


def shifted(ents: list[dict], d: tuple) -> list[dict]:
    return [{**e, "x": e["x"] + d[0], "y": e["y"] + d[1]} for e in ents]


async def read_order(jev: Jev, order: str) -> float:
    a = await jev.ask({"order": order}, {
        "copy": noul("Does `order` ask for more of something already built, the same again at the places it points "
                     "at?",
                     "yes: 'two more just like it at [gps] and [gps]', 'another one of those over here', 'same "
                     "again at [gps]', 'now four more'",
                     "no: a new kind of build, fixing, moving items, a question"),
    }, kind="quickcopy")
    return a["copy"].p
