#!/usr/bin/env python3
"""Offline unit tests (no game, no network): router, row layouts, compact layout notation, plan checker rules, world
model belt lines and faults, failure facts.  Run: .venv/bin/python tests/test_units.py"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from jev.decide import failure_facts  # noqa: E402
from jev.lint import lint  # noqa: E402
from jev.router import Grid, solve  # noqa: E402
from jev.rowgen import row_entities  # noqa: E402
from jev.steps import expand, plan_needs  # noqa: E402
from jev.world import World  # noqa: E402

FAILS = []


def check(name, cond, info=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  ({info})" if info and not cond else ""))
    if not cond:
        FAILS.append(name)


def belt(u, x, y, d, o=None, i=None, items=None):
    e = {"u": u, "n": "transport-belt", "t": "transport-belt", "x": x, "y": y, "d": d}
    if o:
        e["o"] = o
    if i:
        e["i"] = i
    if items:
        e["lanes"] = [items, {}]
    return e


def test_world_reversed_belt():
    # an east line with one belt turned west in the middle
    ents = [belt(1, 0.5, 0.5, "east", o=[2], items={"copper-plate": 4}), belt(2, 1.5, 0.5, "east", i=[1]),
            belt(3, 2.5, 0.5, "west"), belt(4, 3.5, 0.5, "east", o=[5]), belt(5, 4.5, 0.5, "east", i=[4])]
    w = World({"ents": ents, "center": [2, 0]})
    kinds = [f["kind"] for f in w.faults()]
    check("world: reversed belt found", "belt_reversed" in kinds, kinds)
    fx = next(f for f in w.faults() if f["kind"] == "belt_reversed")["fixes"][0]
    check("world: fix rotates it east", fx["do"] == "rotate" and fx["direction"] == "east" and fx["x"] == 2.5, fx)


def test_world_gap():
    ents = [belt(1, 0.5, 0.5, "east", o=[2], items={"iron-ore": 5}), belt(2, 1.5, 0.5, "east", i=[1]),
            belt(3, 4.5, 0.5, "east", o=[4]), belt(4, 5.5, 0.5, "east", i=[3])]
    w = World({"ents": ents, "center": [2, 0]})
    gaps = [f for f in w.faults() if f["kind"] == "belt_gap"]
    check("world: belt gap found", len(gaps) == 1, [f["kind"] for f in w.faults()])
    if gaps:
        fx = gaps[0]["fixes"][0]
        check("world: gap fix connects the two ends", fx["do"] == "connect" and fx["from"] == [1.5, 0.5]
              and fx["to"] == [4.5, 0.5], fx)


def test_router_cross():
    # two lines that must cross: west->east and north->south on an open grid
    g = Grid(set(), (0, 0, 10, 10))
    nets = [("a", (0, 5), (10, 5)), ("b", (5, 0), (5, 10))]
    ents, info = solve(g, nets, None, 10)
    check("router: crossing solved", ents is not None, info)
    if ents:
        tiles = [(int(e["x"] // 1), int(e["y"] // 1)) for e in ents]
        check("router: no tile used twice", len(tiles) == len(set(tiles)))
        check("router: uses an underground", any(e["name"] == "underground-belt" for e in ents))


def test_router_kit():
    g = Grid(set(), (0, 0, 10, 10))
    nets = [("a", (0, 5), (10, 5)), ("b", (5, 0), (5, 10))]
    ents, info = solve(g, nets, {"transport-belt": 5, "underground-belt": 0}, 3)
    check("router: impossible kit is refused", ents is None, info)


def test_rowgen():
    ents, info = row_entities((-54.5, 84.5), "east", "south", "assembling-machine-1", "iron-gear-wheel", 2,
                              second_belt=True)
    ams = [e for e in ents if e["name"] == "assembling-machine-1"]
    check("row: two machines", len(ams) == 2)
    check("row: machine 3 tiles south of the belt", ams[0]["y"] == 87.5, ams[0])
    ins = [e for e in ents if e["name"] == "inserter" and e["x"] == ams[0]["x"]]
    dirs = sorted(e["direction"] for e in ins)
    check("row: input inserters face the two belts", dirs == ["north", "south"], dirs)
    tiles = [(e["x"], e["y"]) for e in ents]
    check("row: nothing overlaps at a center", len(tiles) == len(set(tiles)))
    f, _ = row_entities((0.5, 0.5), "east", "south", "stone-furnace", None, 3, output="belt")
    fur = [e for e in f if e["name"] == "stone-furnace"]
    check("row: furnaces at integer corners", all(e["x"] == int(e["x"]) and e["y"] == int(e["y"]) for e in fur), fur)
    check("row: output belt laid", any(e["name"] == "transport-belt" for e in f))


def test_expand():
    e = expand([{"repeat": 3, "dx": 2, "dy": 0, "entities": [{"name": "stone-furnace", "x": 10, "y": 5}]},
                {"line": "transport-belt", "from": [0.5, 0.5], "to": [3.5, 0.5]}])
    check("expand: repeat x3 + line of 4", len(e) == 7, len(e))
    check("expand: line direction inferred", e[-1]["direction"] == "east")
    check("expand: plan_needs counts it", plan_needs([{"do": "ghosts", "entities": [
        {"repeat": 4, "dx": 2, "entities": [{"name": "stone-furnace", "x": 0, "y": 0}]}]}]) == {"stone-furnace": 4})


def test_lint_rules():
    w = World({"ents": [{"u": 1, "n": "wooden-chest", "t": "container", "x": 0.5, "y": 0.5}], "center": [0, 0]})
    probs = lint([{"do": "place", "name": "iron-chest", "x": 0.5, "y": 0.5}], w, None, {})
    check("lint: chest upgrade in place is allowed", not any("overlaps" in p for p in probs), probs)
    probs = lint([{"do": "place", "name": "assembling-machine-1", "x": 1.5, "y": 1.5, "recipe": "iron-gear-wheel"}],
                 w, None, {"iron-gear-wheel": {"ingredients": {"iron-plate": 2}}})
    check("lint: assembler over a chest is an overlap", any("overlaps" in p for p in probs), probs)
    probs = lint([{"do": "place", "name": "assembling-machine-1", "x": 10, "y": 10, "recipe": "iron-gear-wheel"}],
                 w, None, {"iron-gear-wheel": {"ingredients": {"iron-plate": 2}}})
    check("lint: 3x3 at integer corner flagged", any("should sit" in p for p in probs), probs)


def test_failure_facts():
    f = failure_facts("cannot place assembling-machine-1 at 1.5,2.5: blocked by character@1.2,2.4")
    check("facts: blocked only by the character", f["blocked_only_by_the_character"], f)
    f = failure_facts("cannot place inserter at 1,2: blocked by transport-belt@1,2, character@1,2")
    check("facts: a belt too is not only the character", not f["blocked_only_by_the_character"], f)
    f = failure_facts("needs 1 wooden-chest but you have 0; no chest or machine output within 400 tiles has any, "
                      "and you can't hand-craft the other 1 from what you carry")
    check("facts: item exists nowhere", f["item_exists_nowhere"], f)
    check("facts: already done", failure_facts("automation-2 is already researched")["already_done"])


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print(f"\n{'ALL OK' if not FAILS else str(len(FAILS)) + ' FAILED: ' + ', '.join(FAILS)}")
    sys.exit(1 if FAILS else 0)
