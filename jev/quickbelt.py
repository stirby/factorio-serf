"""Belt items from one place to another without the planner: "belt coal to the boiler from the drills", "get the
copper from that belt end across to the chest". Jev says whether the order is that kind of job; code finds both ends
from what's at the two points the order names, either way round:

- the source is a belt line near one point that carries items and ends with nothing ahead (it gets continued);
- the destination is, near the other point, the start of a belt line that feeds machines (joined from behind), an
  inserter that picks up from bare ground (the belt ends under its pickup), or a machine/chest/boiler with a free side
  (an inserter is placed there, the belt ends behind it).

The game's line routing lays the belt (undergrounds under whatever is in the way), then the usual runner checks it."""
from __future__ import annotations

import math

from .typesafe import Jev, noul
from .world import World, grid_live, items_words

TAKES = ("container", "logistic-container", "boiler", "furnace", "assembling-machine", "lab", "burner-generator")


def _d(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def source(w: World, p) -> dict | None:
    """The belt line near p that carries items and ends with nothing ahead: its last tile and main item."""
    best = None
    for ln in w.lines:
        if not ln.items or ln.end_reason != "ends (nothing ahead)":
            continue
        d = min(_d((w.ents[u]["x"], w.ents[u]["y"]), p) for u in ln.belts if u in w.ents)
        if d <= 8 and (best is None or d < best[0]):
            best = (d, ln)
    if not best:
        return None
    ln = best[1]
    item = max(ln.items, key=ln.items.get)
    return {"from": list(ln.end), "item": item, "line": ln.id, "carries": items_words(ln.items, 3)}


def empty_source(w: World, p) -> bool:
    """An open-ended belt near p that carries nothing yet (it may be starting up): worth a second look."""
    return any(not ln.items and ln.end_reason == "ends (nothing ahead)" and
               min(_d((w.ents[u]["x"], w.ents[u]["y"]), p) for u in ln.belts if u in w.ents) <= 8
               for ln in w.lines if ln.belts)


def _free(w: World, x: float, y: float) -> bool:
    return w.at(x, y) is None and not w.off_view(x, y)


def sink(w: World, p, toward) -> dict | None:
    """Where a belt arriving from `toward` should end near p, and what else has to be placed there."""
    # an input belt that starts here and feeds machines (or is empty): join it from behind
    for ln in sorted(w.lines, key=lambda ln: _d(ln.start, p)):
        if _d(ln.start, p) > 10 or ln.start_reason != "starts here" or not ln.takers:
            continue
        return {"to": list(ln.start), "kind": "join", "what": f"the input belt starting at {ln.start[0]:g},{ln.start[1]:g}"}
    # an inserter that picks up from the bare ground: end the belt under its pickup
    for e in sorted(w.of_type("inserter"), key=lambda e: _d((e["x"], e["y"]), p)):
        if _d((e["x"], e["y"]), p) > 4 or not e.get("pk") or e.get("pku"):
            continue
        pk = e["pk"]
        tx, ty = math.floor(pk[0]) + 0.5, math.floor(pk[1]) + 0.5
        if _free(w, tx, ty):
            fed = w.ents.get(e.get("dpu")) or {}
            what = (f"the {fed['n'].replace('-', ' ')} at {fed['x']:g},{fed['y']:g}" if fed.get("n")
                    else f"the inserter at {e['x']:g},{e['y']:g}")
            return {"to": [tx, ty], "kind": "inserter", "what": what}
    # a machine, boiler or chest at p: an inserter on its side facing `toward`, the belt ending behind it
    tgt = min((e for e in w.ents.values() if e.get("t") in TAKES and e["u"] > 0 and _d((e["x"], e["y"]), p) <= 3),
              key=lambda e: _d((e["x"], e["y"]), p), default=None)
    if not tgt:
        return None
    wd, ht = tgt.get("w", 1), tgt.get("h", 1)
    x0, y0 = tgt["x"] - wd / 2, tgt["y"] - ht / 2
    cands = []
    for i in range(wd):
        cx = x0 + i + 0.5
        cands.append(((cx, y0 - 0.5), (cx, y0 - 1.5)))          # north side
        cands.append(((cx, y0 + ht + 0.5), (cx, y0 + ht + 1.5)))  # south side
    for j in range(ht):
        cy = y0 + j + 0.5
        cands.append(((x0 - 0.5, cy), (x0 - 1.5, cy)))          # west side
        cands.append(((x0 + wd + 0.5, cy), (x0 + wd + 1.5, cy)))  # east side
    cands = [c for c in cands if _free(w, *c[0]) and _free(w, *c[1])]
    if not cands:
        return None
    ins, belt = min(cands, key=lambda c: _d(c[1], toward))
    powered = any(e.get("t") == "electric-pole" and _d((e["x"], e["y"]), ins) <= 7 and
                  grid_live(w.grids.get(e.get("net")) or {}) for e in w.ents.values())
    # fuel into a burner (a boiler, a stone furnace): a burner inserter, which fuels itself from the coal it moves.
    # An electric one on a boiler's own grid stops when the boiler runs dry and never starts it again.
    burner_target = tgt.get("t") in ("boiler", "burner-generator") or tgt.get("n") in ("stone-furnace", "steel-furnace",
                                                                                       "burner-mining-drill")
    name = "burner-inserter" if burner_target or not powered else "inserter"
    return {"to": [belt[0], belt[1]], "kind": "new_inserter", "inserter": {"name": name, "x": ins[0], "y": ins[1],
            "pickup": [belt[0], belt[1]]}, "what": f"the {tgt['n'].replace('-', ' ')} at {tgt['x']:g},{tgt['y']:g}",
            "electric": powered and not burner_target}


def endpoints(wa: World, a, wb: World, b) -> dict | None:
    """Source near a and destination near b, or the other way round."""
    for (ws, ps), (wt, pt) in (((wa, a), (wb, b)), ((wb, b), (wa, a))):
        src = source(ws, ps)
        if not src:
            continue
        dst = sink(wt, pt, src["from"])
        if dst:
            return {**src, **dst}
    return None


async def read_order(jev: Jev, order: str) -> float:
    a = await jev.ask({"order": order}, {
        "move": noul("Does `order` ask for items to be carried by a new belt from one place it points at to another?",
                     "yes: 'belt coal to the boiler from the drills', 'belt their ore to the furnaces', 'get the "
                     "copper plates from that belt over to the chest at [gps]', 'run the gears to the science'",
                     "no: building machines, fixing or refuelling, power, bringing a number of items by hand, a "
                     "question"),
        "build": noul("Does `order` also ask for new machines, furnaces or mining drills to be built?",
                      "yes: 'build 8 furnaces ... and send the plates on a belt', 'set up an iron mine and belt the "
                      "ore back'",
                      "no: only a belt (and what it needs to deliver) between things that are already there"),
    }, kind="quickbelt")
    # a belt plus new machines is a build with a belt in it: the planner's job
    return a["move"].p if a["build"].p < 0.5 else 0.0
