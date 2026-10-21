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
    o0 = orig[0]
    found = []
    for q in new:
        d = (q[0] - o0[0], q[1] - o0[1])
        if abs(d[0]) < 1 and abs(d[1]) < 1:
            continue  # that's the original itself
        if all(any(abs(p[0] + d[0] - n[0]) <= tol and abs(p[1] + d[1] - n[1]) <= tol for n in new) for p in orig):
            if not any(abs(d[0] - e[0]) < 1 and abs(d[1] - e[1]) < 1 for e in found):
                found.append(d)
    covered = {i for i, n in enumerate(new) for d in found for p in orig
               if abs(p[0] + d[0] - n[0]) <= tol and abs(p[1] + d[1] - n[1]) <= tol}
    return found if len(covered) == len(new) else []


def built_by(w: World, box: tuple, me: str) -> list[dict]:
    """What `me` built inside box (x0, y0, x1, y1), as layout entries."""
    x0, y0, x1, y1 = box
    out = []
    for e in w.ents.values():
        if e.get("by") != me or e["u"] <= 0 or not (x0 <= e["x"] <= x1 and y0 <= e["y"] <= y1):
            continue
        d = {"name": e["n"], "x": e["x"], "y": e["y"]}
        if e.get("d"):
            d["direction"] = e["d"]
        if e.get("r") and e.get("t") == "assembling-machine":
            d["recipe"] = e["r"]
        if e.get("ug"):
            d["type"] = e["ug"]
        out.append(d)
    return out


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
