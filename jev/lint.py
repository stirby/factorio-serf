"""Plan checker: simulate a plan's buildings on top of the scanned area and report layout mistakes before anything
is built (overlaps, inserters picking from or dropping onto nothing, machines nothing feeds, no power, items that
don't exist, belts continued backwards). The thinker gets the list in the same turn and can fix the plan at once.
"""
from __future__ import annotations

import math

from .world import BELT_T, DIRS, World, fmt_xy, grid_live

SIZE = {
    "assembling-machine-1": (3, 3), "assembling-machine-2": (3, 3), "assembling-machine-3": (3, 3),
    "stone-furnace": (2, 2), "steel-furnace": (2, 2), "electric-furnace": (3, 3), "lab": (3, 3),
    "electric-mining-drill": (3, 3), "burner-mining-drill": (2, 2), "chemical-plant": (3, 3),
    "oil-refinery": (5, 5), "pumpjack": (3, 3), "storage-tank": (3, 3), "solar-panel": (3, 3),
    "accumulator": (2, 2), "radar": (3, 3), "roboport": (4, 4), "big-electric-pole": (2, 2), "substation": (2, 2),
    "centrifuge": (3, 3), "beacon": (3, 3), "rocket-silo": (9, 9), "steam-engine": (3, 5), "boiler": (3, 2),
    "offshore-pump": (1, 2), "splitter": (2, 1), "fast-splitter": (2, 1), "express-splitter": (2, 1),
}
SUPPLY = {"small-electric-pole": 2.5, "medium-electric-pole": 3.5, "big-electric-pole": 2.0, "substation": 9.0}
ELECTRIC = {"assembling-machine-1", "assembling-machine-2", "assembling-machine-3", "electric-furnace", "lab",
            "electric-mining-drill", "inserter", "fast-inserter", "long-handed-inserter", "bulk-inserter",
            "filter-inserter", "chemical-plant", "oil-refinery", "pumpjack", "radar", "centrifuge", "beacon"}
INSERTERS = {"inserter", "fast-inserter", "long-handed-inserter", "bulk-inserter", "burner-inserter",
             "filter-inserter", "stack-inserter"}
ASSEMBLERS = {"assembling-machine-1", "assembling-machine-2", "assembling-machine-3", "chemical-plant"}
TAKES_ITEMS = {"assembling-machine", "furnace", "lab", "container", "logistic-container", "infinity-container",
               "boiler", "transport-belt", "underground-belt", "splitter", "rocket-silo", "car", "cargo-wagon",
               "burner-mining-drill", "mining-drill", "reactor", "burner-generator", "chemical-plant"}


REPLACE_GROUP = {}
for _grp, _names in {
    "belt": ["transport-belt", "fast-transport-belt", "express-transport-belt", "turbo-transport-belt",
             "underground-belt", "fast-underground-belt", "express-underground-belt", "turbo-underground-belt",
             "splitter", "fast-splitter", "express-splitter", "turbo-splitter"],
    "chest": ["wooden-chest", "iron-chest", "steel-chest"],
    "inserter": ["burner-inserter", "inserter", "fast-inserter", "long-handed-inserter", "bulk-inserter",
                 "filter-inserter", "stack-inserter"],
    "assembler": ["assembling-machine-1", "assembling-machine-2", "assembling-machine-3"],
    "furnace": ["stone-furnace", "steel-furnace"],
    "pole": ["small-electric-pole", "medium-electric-pole"],
    "pipe": ["pipe", "pipe-to-ground"],
}.items():
    for _n in _names:
        REPLACE_GROUP[_n] = _grp


# where a drill's output lands, facing north, from its center (the prototypes' vector_to_place_result)
DRILL_DROP = {"burner-mining-drill": (-0.5, -1.3), "electric-mining-drill": (0.0, -1.85)}


def drill_drop(e: dict) -> tuple[int, int]:
    vx, vy = DRILL_DROP[e["name"]]
    d = e.get("dir") if e.get("dir") in ("north", "east", "south", "west") else "north"
    vx, vy = {"north": (vx, vy), "east": (-vy, vx), "south": (-vx, -vy), "west": (vy, -vx)}[d]
    return math.floor(e["x"] + vx), math.floor(e["y"] + vy)

def size_of(name: str, direction: str | None = None) -> tuple[int, int]:
    w, h = SIZE.get(name, (1, 1))
    if direction in ("east", "west") and name in ("steam-engine", "boiler", "offshore-pump", "splitter",
                                                  "fast-splitter", "express-splitter"):
        w, h = h, w
    return w, h


def tiles_of(x: float, y: float, w: int, h: int) -> list[tuple[int, int]]:
    x0, y0 = math.floor(x - w / 2 + 0.01), math.floor(y - h / 2 + 0.01)
    return [(x0 + i, y0 + j) for i in range(w) for j in range(h)]


def plan_points(steps: list[dict]) -> list[tuple[float, float]]:
    pts = []
    for s in steps:
        if s.get("do") == "block":
            from . import blueprints as bp
            try:
                for e in bp.stamp_entities(s["name"], float(s["x"]), float(s["y"]), s.get("rotation", 0),
                                           s.get("anchor")):
                    pts.append((float(e["x"]), float(e["y"])))
            except (KeyError, TypeError, ValueError):
                pass
        if s.get("do") == "design":
            from .library import place_design
            for e in place_design(s.get("name", ""), s.get("x", 0), s.get("y", 0)) or []:
                pts.append((float(e["x"]), float(e["y"])))
        if s.get("do") == "row" and isinstance(s.get("belt"), (list, tuple)):
            n = int(s.get("count", 1))
            pts.append((float(s["belt"][0]) - 8, float(s["belt"][1]) - 8))
            pts.append((float(s["belt"][0]) + 6 * n + 8, float(s["belt"][1]) + 6 * n + 8))
            pts.append((float(s["belt"][0]) - 6 * n - 8, float(s["belt"][1]) - 6 * n - 8))
        for k in ("from", "to", "pickup", "drop", "at", "left", "right"):
            v = s.get(k)
            if isinstance(v, (list, tuple)) and len(v) == 2:
                pts.append((float(v[0]), float(v[1])))
        if "x" in s and "y" in s:
            try:
                pts.append((float(s["x"]), float(s["y"])))
            except (TypeError, ValueError):
                pass
        from .steps import expand
        for e in expand(s.get("entities") or []):
            try:
                pts.append((float(e["x"]), float(e["y"])))
            except (KeyError, TypeError, ValueError):
                pass
    return pts


def lint(steps: list[dict], w: World, available: set[str] | None = None, recipes: dict | None = None) -> list[str]:
    """Problems with the plan, as short sentences (empty = looks fine)."""
    out: list[str] = []
    recipes = recipes or {}
    occ: dict[tuple[int, int], str] = {}
    for t, u in w.tile.items():
        occ[t] = w.ents[u]["n"]
    planned: list[dict] = []  # {name, x, y, dir, pickup, drop, recipe, tiles}
    maybe_belt: set[tuple[int, int]] = set()
    power_targets: list[tuple[float, float]] = []
    removed: set[tuple[int, int]] = set()

    def add(name, x, y, direction=None, pickup=None, drop=None, recipe=None, src="place"):
        wdt, hgt = size_of(name, direction)
        tl = tiles_of(x, y, wdt, hgt)
        # alignment: odd sizes sit at .5, even sizes at integers
        for v, n in ((x, wdt), (y, hgt)):
            frac = abs(v - math.floor(v))
            if (n % 2 == 1 and abs(frac - 0.5) > 0.01) or (n % 2 == 0 and frac > 0.01):
                out.append(f"{name} at {fmt_xy((x, y))}: a {wdt}x{hgt} entity should sit at "
                           f"{'.5 centers' if n % 2 else 'integer corners'}; the game will shift it")
                break
        for t in tl:
            other = occ.get(t)
            same_group = other and REPLACE_GROUP.get(name) and REPLACE_GROUP.get(name) == REPLACE_GROUP.get(other)
            if other and t not in removed and not same_group:  # same family = upgrade in place (fast replace)
                out.append(f"{name} at {fmt_xy((x, y))} overlaps {other} at tile {t[0]},{t[1]}")
                break
        for t in tl:
            occ[t] = name
        e = {"name": name, "x": x, "y": y, "dir": direction, "pickup": pickup, "drop": drop, "recipe": recipe,
             "tiles": tl, "src": src}
        planned.append(e)
        return e

    for i, s in enumerate(steps):
        d = s.get("do")
        try:
            if d == "place":
                add(s["name"], float(s["x"]), float(s["y"]), s.get("direction"), s.get("pickup"), s.get("drop"),
                    s.get("recipe"))
            elif d == "ghosts":
                from .steps import expand
                for e in expand(s.get("entities") or []):
                    add(e["name"], float(e["x"]), float(e["y"]), e.get("direction"), None, None, e.get("recipe"),
                        src="ghosts")
            elif d == "design":
                from .library import place_design
                ents = place_design(s.get("name", ""), s["x"], s["y"])
                if ents is None:
                    out.append(f"step {i + 1}: no saved design {s.get('name')!r}")
                for e in ents or []:
                    add(e["name"], float(e["x"]), float(e["y"]), e.get("direction"), None, None, e.get("recipe"),
                        src="design")
            elif d == "row":
                from .rowgen import DIRS as RD, row_entities
                b = s.get("belt") or [0, 0]
                be = w.at(float(b[0]), float(b[1]))
                if not be:  # a belt an earlier step of this plan lays (a tap's split-off belt, a connect's end)
                    bt = (math.floor(float(b[0])), math.floor(float(b[1])))
                    pb = next((e for e in planned if "belt" in e["name"] and bt in e["tiles"] and e.get("dir")), None)
                    if pb:
                        be = {"x": pb["x"], "y": pb["y"], "d": pb["dir"]}
                if not be or be.get("d") not in RD:
                    out.append(f"step {i + 1} row: no belt at {b[0]},{b[1]}")
                else:
                    sides = [x for x in RD if RD[x][0] * RD[be["d"]][0] + RD[x][1] * RD[be["d"]][1] == 0]
                    sd = s.get("side") or min(sides, key=lambda x: sum(
                        1 for e in row_entities((be["x"], be["y"]), be["d"], x, s.get("machine", "assembling-machine-1"),
                                                s.get("recipe"), int(s.get("count", 1)), bool(s.get("second_belt")),
                                                s.get("output", "chest"))[0] if w.at(e["x"], e["y"])))
                    try:
                        ents, _ = row_entities((be["x"], be["y"]), be["d"], sd, s.get("machine", "assembling-machine-1"),
                                               s.get("recipe"), int(s.get("count", 1)), bool(s.get("second_belt")),
                                               s.get("output", "chest"), s.get("inserter", "inserter"),
                                               int(s.get("offset", 0)))
                    except ValueError as ex:
                        out.append(f"step {i + 1} row: {ex}")
                        ents = []
                    for e in ents:
                        add(e["name"], float(e["x"]), float(e["y"]), e.get("direction"), None, None, e.get("recipe"),
                            src="row")
                    if ents:
                        xs, ys = [e["x"] for e in ents], [e["y"] for e in ents]
                        power_targets.append(((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2))
            elif d == "block":
                from . import blueprints as bp
                try:
                    ents = bp.stamp_entities(s["name"], float(s["x"]), float(s["y"]), s.get("rotation", 0),
                                             s.get("anchor"))
                except KeyError as e:
                    out.append(f"step {i + 1}: {e}")
                    ents = []
                for e in ents:
                    add(e["name"], float(e["x"]), float(e["y"]), e.get("direction"), None, None, e.get("recipe"),
                        src="block")
            elif d == "mine_at":
                removed.add((math.floor(float(s["x"])), math.floor(float(s["y"]))))
            elif d == "connect":
                f, t = s.get("from"), s.get("to")
                if not (isinstance(f, (list, tuple)) and isinstance(t, (list, tuple))):
                    out.append(f"step {i + 1} connect needs from=[x,y] and to=[x,y]")
                    continue
                item = s.get("item", "")
                if "belt" in item or "pipe" in item:
                    # route unknown: mark the bounding box as maybe-belt so inserters next to it aren't flagged
                    x0, x1 = sorted((math.floor(f[0]), math.floor(t[0])))
                    y0, y1 = sorted((math.floor(f[1]), math.floor(t[1])))
                    for xx in range(x0 - 1, x1 + 2):
                        for yy in range(y0 - 1, y1 + 2):
                            maybe_belt.add((xx, yy))
                    if "belt" in item:
                        b = w.at(f[0], f[1])
                        if b and b["t"] in BELT_T and b.get("d") in DIRS:
                            ln = w.line_of.get(b["u"])
                            dx, dy = DIRS[b["d"]]
                            vx, vy = t[0] - f[0], t[1] - f[1]
                            if ln and b["u"] == ln.belts[-1] and dx * vx + dy * vy < -2:
                                out.append(f"connect from {fmt_xy(f)}: that belt is the end of a line running "
                                           f"{b['d']}; a line can't be continued backwards toward {fmt_xy(t)}. "
                                           "Take items off it with an inserter onto a new belt, or use a splitter")
                            elif ln and b["u"] != ln.belts[-1] and b["u"] != ln.belts[0]:
                                out.append(f"connect from {fmt_xy(f)}: that's the middle of belt line {ln.id}, "
                                           "not its end; the new line won't be fed. Use an inserter or splitter "
                                           "to branch")
                        # joining one line onto another mixes what they carry (p1: coal ended up on the plastic
                        # belt, and a new outpost line ran into a base belt)
                        src = w.line_of.get(b["u"]) if b and b.get("t") in BELT_T else None
                        e = w.at(t[0], t[1])
                        dst = w.line_of.get(e["u"]) if e and e.get("t") in BELT_T else None
                        si = set((src.items or {}) if src else ())
                        di = set((dst.items or {}) if dst else ())
                        if src is not dst and si and di and not si <= di:
                            out.append(f"connect from {fmt_xy(f)} to {fmt_xy(t)} would put "
                                       f"{', '.join(sorted(si - di))} onto belt line {dst.id}, which carries "
                                       f"{', '.join(sorted(di))}. End the new line beside it instead (or into a "
                                       "chest or machine), unless mixing them is the point")
                elif "pole" in item:
                    power_targets.append((float(t[0]), float(t[1])))
            elif d == "power":
                power_targets.append((float(s["x"]), float(s["y"])))
        except (KeyError, TypeError, ValueError) as e:
            out.append(f"step {i + 1} ({d}) is malformed: {e!r}")

    def thing_at(t: tuple[int, int]) -> str | None:
        if t in occ and t not in removed:
            return occ[t]
        return None

    for e in planned:
        n = e["name"]
        if available is not None and n not in available and recipes is not None and n not in recipes:
            # only when there's no recipe at all: craftable items can come from plates on belts or elsewhere
            out.append(f"{n} is not available: none in storage or inventory, and it has no recipe you can use")
        if n in DRILL_DROP:
            dt = drill_drop(e)
            if thing_at(dt) is None and dt not in maybe_belt:
                out.append(f"{n} at {fmt_xy((e['x'], e['y']))} drops its ore on tile {dt[0]},{dt[1]} where there is "
                           "nothing: it stops after one item. Put the chest, furnace or belt on that tile, or turn it")
        if n in INSERTERS:
            reach = 2 if n == "long-handed-inserter" else 1
            if e["pickup"]:
                pk = (math.floor(e["pickup"][0]), math.floor(e["pickup"][1]))
                ex, ey = math.floor(e["x"]), math.floor(e["y"])
                dp = (2 * ex - pk[0], 2 * ey - pk[1])
            elif e["drop"]:
                dp = (math.floor(e["drop"][0]), math.floor(e["drop"][1]))
                ex, ey = math.floor(e["x"]), math.floor(e["y"])
                pk = (2 * ex - dp[0], 2 * ey - dp[1])
            elif e["dir"] in DIRS:
                dx, dy = DIRS[e["dir"]]
                ex, ey = math.floor(e["x"]), math.floor(e["y"])
                pk, dp = (ex + dx * reach, ey + dy * reach), (ex - dx * reach, ey - dy * reach)
            else:
                out.append(f"{n} at {fmt_xy((e['x'], e['y']))} has no direction, pickup or drop")
                continue
            if thing_at(pk) is None and pk not in maybe_belt:
                out.append(f"{n} at {fmt_xy((e['x'], e['y']))} picks up from tile {pk[0]},{pk[1]} where there is "
                           "nothing")
            if thing_at(dp) is None and dp not in maybe_belt:
                out.append(f"{n} at {fmt_xy((e['x'], e['y']))} drops onto tile {dp[0]},{dp[1]} where there is "
                           "nothing (items would land on the ground)")
            e["pk"], e["dp"] = pk, dp
        if n in ASSEMBLERS:
            if not e["recipe"]:
                out.append(f"{n} at {fmt_xy((e['x'], e['y']))} has no recipe")
            elif recipes and e["recipe"] not in recipes:
                out.append(f"recipe {e['recipe']} is not available (not researched, or wrong name)")
    # machines nothing feeds
    for e in planned:
        if e["name"] in ASSEMBLERS or e["name"] in ("stone-furnace", "steel-furnace", "electric-furnace", "lab"):
            tl = set(e["tiles"])
            fed = any(x.get("dp") in tl for x in planned if x["name"] in INSERTERS)
            fed = fed or any(w.ents.get(u, {}).get("dpu") and (math.floor(w.ents[u]["dp"][0]), math.floor(w.ents[u]["dp"][1])) in tl
                             for u in [u for u, x in w.ents.items() if x["t"] == "inserter" and x.get("dp")])
            # a mining drill dropping straight into it feeds it too (burner drills onto furnaces)
            fed = fed or any(drill_drop(x) in tl for x in planned if x["name"] in DRILL_DROP)
            fed = fed or any(x.get("dp") and (math.floor(x["dp"][0]), math.floor(x["dp"][1])) in tl
                             for x in w.ents.values() if x.get("t") == "mining-drill")
            if not fed:
                out.append(f"nothing feeds the {e['name']} at {fmt_xy((e['x'], e['y']))} (no inserter drops into it)")
    # ingredients: every planned assembler needs an inserter bringing each ingredient from somewhere that has it
    def made_by(tile):
        """What a planned machine on that tile outputs (its recipe), if any."""
        for x in planned:
            if tile in x["tiles"] and x["name"] in ASSEMBLERS and x["recipe"]:
                return x["recipe"]
        return None
    added_to_line: dict = {}  # belt line id -> items planned inserters will drop onto it
    for x in planned:
        if x["name"] in INSERTERS and x.get("dp") and x.get("pk"):
            u = w.tile.get(x["dp"])
            ln = w.line_of.get(u) if u else None
            item = made_by(x["pk"])
            if ln and item:
                added_to_line.setdefault(ln.id, set()).add(item)

    def source_items(tile: tuple[int, int]) -> set[str] | None:
        """Items available at a tile an inserter picks from; None = unknown (a belt still to be routed, etc.)."""
        if tile in maybe_belt and tile not in w.tile:
            return None
        for x in planned:
            if tile in x["tiles"]:
                if x["name"] in ASSEMBLERS and x["recipe"]:
                    return {x["recipe"]}
                if x["name"] in ("stone-furnace", "steel-furnace", "electric-furnace"):
                    return {"iron-plate", "copper-plate", "steel-plate", "stone-brick"}
                return None  # a planned chest or belt: contents unknown
        u = w.tile.get(tile)
        e = w.ents.get(u) if u else None
        if not e:
            return set()
        if e["t"] in BELT_T:
            ln = w.line_of.get(u)
            if not ln:
                return None
            have = set(ln.items or {}) | added_to_line.get(ln.id, set())
            return have or None  # an empty line may still fill
        if e["t"] in ("container", "logistic-container", "infinity-container"):
            return set((e.get("inv") or {}).keys()) or None
        if e["t"] in ("assembling-machine", "furnace"):
            return {e["r"]} if e.get("r") else None
        return None
    for e in planned:
        if e["name"] not in ASSEMBLERS or not e["recipe"]:
            continue
        need = set(((recipes or {}).get(e["recipe"]) or {}).get("ingredients") or {})
        if not need:
            continue
        tl = set(e["tiles"])
        have: set[str] = set()
        unknown = False
        feeders = [x for x in planned if x["name"] in INSERTERS and x.get("dp") in tl]
        for x in feeders:
            got = source_items(x["pk"])
            if got is None:
                unknown = True
            else:
                have |= got
        for u, x in w.ents.items():
            if x["t"] == "inserter" and x.get("dp") and (math.floor(x["dp"][0]), math.floor(x["dp"][1])) in tl:
                got = source_items((math.floor(x["pk"][0]), math.floor(x["pk"][1])))
                if got is None:
                    unknown = True
                else:
                    have |= got
        missing = need - have
        if feeders and missing and not unknown:
            out.append(f"the {e['name']} at {fmt_xy((e['x'], e['y']))} makes {e['recipe']} but nothing brings it "
                       f"{', '.join(sorted(missing))} (its inserters pick up {', '.join(sorted(have)) or 'nothing'})")
    # power for planned electric things
    live = {g["id"] for g in w.grids.values() if grid_live(g)}
    poles = [(x["x"], x["y"], SUPPLY.get(x["n"], 2.5)) for x in w.ents.values()
             if x["t"] == "electric-pole" and x.get("net") in live]
    poles += [(x["x"], x["y"], SUPPLY.get(x["name"], 2.5)) for x in planned if x["name"] in SUPPLY]

    def covered(e) -> bool:
        for (px, py, r) in poles:
            for (tx, ty) in e["tiles"]:
                if abs(tx + 0.5 - px) <= r + 0.5 and abs(ty + 0.5 - py) <= r + 0.5:
                    return True
        for (tx, ty) in power_targets:
            if any(abs(a + 0.5 - tx) <= 4 and abs(b + 0.5 - ty) <= 4 for (a, b) in e["tiles"]):
                return True
        return False
    unpowered = [e for e in planned if e["name"] in ELECTRIC and not covered(e)]
    if unpowered:
        out.append(f"{len(unpowered)} planned electric machines have no pole in reach and no power step: "
                   + ", ".join(f"{e['name']} at {fmt_xy((e['x'], e['y']))}" for e in unpowered[:5]))
    # de-duplicate, keep order
    seen, res = set(), []
    for m in out:
        if m not in seen:
            seen.add(m)
            res.append(m)
    return res[:20]
