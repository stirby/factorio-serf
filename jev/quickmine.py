"""Mining without the planner: "set up an iron mine on the patch at [gps] and belt the ore to [gps]". Jev says whether
the order asks for mining and which ore; code reads exact numbers (a rate or a drill count) off the text, lays two rows
of electric drills facing a belt through the richest band of the patch, with pole rows beside them, and the belt fast
path takes the ore on to the place the order names."""
from __future__ import annotations

import math
import re

from .typesafe import Jev, choice, noul

DRILL_PER_MIN = 30  # an electric mining drill: 0.5 ore/s


def wanted_drills(order: str) -> int:
    """From the text: '60 ore a minute' -> enough drills with a margin; '6 drills' -> 6; else 6."""
    m = re.search(r"(\d+)\s*(?:ore\s*)?(?:a|per|/)\s*min", order, re.I)
    if m:
        return max(2, math.ceil(int(m.group(1)) * 1.3 / DRILL_PER_MIN))
    m = re.search(r"(\d+)\s*(?:electric\s+)?(?:mining\s+)?drills?\b", order, re.I)
    if m:
        return max(1, min(24, int(m.group(1))))
    return 6


def layout(tiles: set, n: int, toward_x: float, pole: str = "small-electric-pole") -> dict | None:
    """Two rows of drills (3x3) facing a belt along the patch's richest 7-tile band: upper ones face south, lower ones
    north, both dropping onto the belt row; poles in a row above and below, joined at the belt's upstream end. Tiles
    are ore tile corners (x, y). Returns {"ents", "belt_end", "direction", "center"} or None."""
    if len(tiles) < 9:
        return None
    xs, ys = [t[0] for t in tiles], [t[1] for t in tiles]
    rows = range(min(ys) + 1, max(ys)) if max(ys) - min(ys) >= 2 else [min(ys)]
    yb = max(rows, key=lambda y: (sum(1 for t in tiles if y - 3 <= t[1] <= y + 3), -abs(y - sum(ys) / len(ys))))
    cands = []
    for x0 in range(min(xs), max(xs) - 1):
        up = sum(1 for dx in range(3) for dy in (-3, -2, -1) if (x0 + dx, yb + dy) in tiles)
        lo = sum(1 for dx in range(3) for dy in (1, 2, 3) if (x0 + dx, yb + dy) in tiles)
        cands.append((x0, up, lo))
    # columns every 3 tiles from the offset that covers the most ore
    best = max(range(3), key=lambda off: sum(u + lo for x0, u, lo in cands if (x0 - min(xs)) % 3 == off))
    drills = []
    for x0, up, lo in cands:
        if (x0 - min(xs)) % 3 != best:
            continue
        if up >= 3:
            drills.append((up, x0, "up"))
        if lo >= 3:
            drills.append((lo, x0, "lo"))
    drills = sorted(drills, reverse=True)[:n]
    if not drills:
        return None
    bx0 = min(d[1] for d in drills)
    bx1 = max(d[1] for d in drills) + 2
    direction = "east" if toward_x >= (bx0 + bx1) / 2 else "west"
    ents = []
    for _, x0, side in drills:
        if side == "up":
            ents.append({"name": "electric-mining-drill", "x": x0 + 1.5, "y": yb - 1.5, "direction": "south"})
        else:
            ents.append({"name": "electric-mining-drill", "x": x0 + 1.5, "y": yb + 2.5, "direction": "north"})
    for x in range(bx0, bx1 + 1):
        ents.append({"name": "transport-belt", "x": x + 0.5, "y": yb + 0.5, "direction": direction})
    for x in range(bx0, bx1 + 1, 6):
        ents.append({"name": pole, "x": x + 1.5, "y": yb - 3.5})
        ents.append({"name": pole, "x": x + 1.5, "y": yb + 4.5})
    up_x = bx0 - 1 if direction == "east" else bx1 + 1  # the upstream end: the poles' join, out of the belt's way
    ents.append({"name": pole, "x": up_x + 0.5, "y": yb + 0.5})
    end_x = bx1 if direction == "east" else bx0
    return {"ents": ents, "belt_end": [end_x + 0.5, yb + 0.5], "direction": direction, "drills": len(drills),
            "center": [(bx0 + bx1) / 2 + 0.5, yb + 0.5]}


FLIP = {"east": "south", "south": "east", "west": "north", "north": "west"}  # mirrored over the diagonal


def best_layout(tiles: set, n: int, toward: tuple, pole: str = "small-electric-pole") -> dict | None:
    """layout() along x, or along y (the patch mirrored over the diagonal, laid out, mirrored back): whichever places
    more drills; on a tie, the one whose belt heads more toward `toward`."""
    cands = []
    a = layout(tiles, n, toward[0], pole)
    if a:
        cands.append(a)
    t = layout({(y, x) for x, y in tiles}, n, toward[1], pole)
    if t:
        ents = []
        for e in t["ents"]:
            f = {**e, "x": e["y"], "y": e["x"]}
            if "direction" in e:
                f["direction"] = FLIP[e["direction"]]
            ents.append(f)
        cands.append({"ents": ents, "belt_end": [t["belt_end"][1], t["belt_end"][0]],
                      "direction": FLIP[t["direction"]], "drills": t["drills"],
                      "center": [t["center"][1], t["center"][0]]})
    if not cands:
        return None
    vec = {"east": (1, 0), "west": (-1, 0), "south": (0, 1), "north": (0, -1)}

    def heads(c):
        v = vec[c["direction"]]
        dx, dy = toward[0] - c["center"][0], toward[1] - c["center"][1]
        return (v[0] * dx + v[1] * dy) / (math.hypot(dx, dy) or 1)
    return max(cands, key=lambda c: (c["drills"], heads(c)))


async def read_order(jev: Jev, order: str, ores: list[str]) -> tuple[float, str | None, float]:
    opts = {o: o.replace("-", " ") for o in ores}
    opts["none_of_these"] = "another resource, or not about mining"
    a = await jev.ask({"order": order, "ore_patches_there": ores}, {
        "mine": noul("Does `order` ask to set up mining: drills on an ore patch?",
                     "yes: 'set up an iron mine on the patch at [gps]', 'put drills on that copper and belt it to the "
                     "furnaces', 'mine the coal here'",
                     "no: hand-mining a few items, building furnaces or assemblers, fixing drills that stopped"),
        "ore": choice("Which ore should be mined?", opts),
    }, kind="quickmine")
    ore = a["ore"].choice
    return a["mine"].p, (None if ore == "none_of_these" else ore), float(a["ore"].probs.get(ore) or 0)
