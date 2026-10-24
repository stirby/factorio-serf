#!/usr/bin/env python3
"""Offline unit tests (no game, no network): router, row layouts, compact layout notation, plan checker rules, world
model belt lines and faults, failure facts.  Run: .venv/bin/python tests/test_units.py"""
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from jev.decide import failure_facts  # noqa: E402
from jev.lint import lint  # noqa: E402
from jev.router import Grid, solve  # noqa: E402
from jev.rowgen import row_entities  # noqa: E402
from jev.steps import expand, ghost_result, plan_needs, unplaced, upgrade_map  # noqa: E402
from jev.world import World  # noqa: E402
from jev import craft, quickbelt, quickbuild, quickcopy, quickmine  # noqa: E402

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


def test_world_summary():
    ents = [belt(1, 0.5, 0.5, "east", o=[2], items={"copper-plate": 4}), belt(2, 1.5, 0.5, "east", i=[1]),
            {"u": 7, "n": "inserter", "t": "inserter", "x": 1.5, "y": 1.5, "d": "north", "s": "working",
             "pk": [1.5, 0.5], "dp": [1.5, 2.7], "pku": 2, "dpu": 8},
            {"u": 8, "n": "assembling-machine-1", "t": "assembling-machine", "x": 1.5, "y": 3.5, "w": 3, "h": 3,
             "s": "item_ingredient_shortage", "r": "copper-cable"},
            {"u": 9, "n": "small-electric-pole", "t": "electric-pole", "x": 3.5, "y": 1.5, "net": 4}]
    w = World({"ents": ents, "center": [2, 2]}, {"copper-cable": {"ingredients": {"copper-plate": 1}}})
    s1 = w.summary(coords=True)
    check("summary: inserters listed with moves", isinstance(s1.get("inserters"), list) and "->" in s1["inserters"][0]["moves"], s1.get("inserters"))
    check("summary: poles listed", s1.get("poles") and "grid 4" in s1["poles"][0], s1.get("poles"))
    s2 = w.summary(coords=False)
    check("summary: relative words for Jev", "tiles" in s2["machines"][0]["at"] or s2["machines"][0]["at"] == "right here", s2["machines"][0])


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


def test_world_view_edge():
    # a line running east off the side of a radius-3 scan isn't "ending": it goes on out of sight
    ents = [belt(1, 1.5, 0.5, "east", o=[2], items={"iron-plate": 4}), belt(2, 2.5, 0.5, "east", i=[1])]
    w = World({"ents": ents, "center": [0, 0], "radius": 3})
    ln = w.lines[0]
    check("world: line past the view edge says so", "edge of this view" in ln.end_reason, ln.end_reason)
    w = World({"ents": ents, "center": [0, 0], "radius": 10})
    check("world: line inside the view ends", w.lines[0].end_reason == "ends (nothing ahead)", w.lines[0].end_reason)
    check("world: no gap fault from a line leaving the view",
          not [f for f in World({"ents": ents, "center": [0, 0], "radius": 3}).faults() if f["kind"] == "belt_gap"])


def test_ghost_refusals():
    asked = [{"name": "transport-belt", "x": 1.5, "y": 0.5, "direction": "east"},
             {"name": "transport-belt", "x": 2.5, "y": 0.5, "direction": "east"}]
    r = {"ok": True, "ghosts": 0, "failed": [{"name": "transport-belt", "x": 1.5, "y": 0.5, "why": "same"},
                                             {"name": "transport-belt", "x": 2.5, "y": 0.5,
                                              "why": "blocked by inserter@2.5,0.5"}]}
    bad = unplaced(asked, r)
    check("ghosts: identical entity already there isn't a refusal", len(bad) == 1 and bad[0]["x"] == 2.5, bad)
    res = ghost_result({"ok": True, "msg": "built 0 ghosts"}, {"_unplaced": bad})
    check("ghosts: a refused part fails the step and names the blocker", not res["ok"] and "inserter@2.5,0.5" in res["msg"],
          res)
    check("ghosts: nothing refused stays ok", ghost_result({"ok": True, "msg": "x"}, {"_unplaced": []})["ok"])


def _line(u0, y, n, items, d="east"):
    out = []
    for k in range(n):
        out.append(belt(u0 + k, 0.5 + k, y, d, o=[u0 + k + 1] if k < n - 1 else None, i=[u0 + k - 1] if k else None,
                        items=items))
    return out


RECIPES = {"iron-gear-wheel": {"ingredients": {"iron-plate": 2}, "category": "crafting"},
           "inserter": {"ingredients": {"iron-plate": 1, "iron-gear-wheel": 1, "electronic-circuit": 1},
                        "category": "crafting"},
           "electronic-circuit": {"ingredients": {"iron-plate": 1, "copper-cable": 3}, "category": "electronics"},
           "sulfuric-acid": {"ingredients": {"iron-plate": 1, "water": 100}, "category": "chemistry"}}


def test_quickbuild_options():
    w = World({"ents": _line(1, 4.5, 20, {"iron-plate": 3}), "center": [10, 4], "radius": 32}, RECIPES)
    o = quickbuild.options(w, RECIPES, [(0.5, 4.5)])
    check("quick: gears off an iron belt", "iron-gear-wheel" in o and len(o["iron-gear-wheel"]["lines"]) == 1, o)
    check("quick: no circuit without cables, no chemistry", "electronic-circuit" not in o and "sulfuric-acid" not in o)
    st = quickbuild.row_step(w, o["iron-gear-wheel"], "iron-gear-wheel", 2)
    check("quick: row starts 2 tiles in", st["belt"] == [2.5, 4.5] and st["recipe"] == "iron-gear-wheel", st)
    ents = _line(1, 4.5, 20, {"iron-plate": 3, "iron-gear-wheel": 2}) + _line(101, 10.5, 20, {"electronic-circuit": 4})
    w = World({"ents": ents, "center": [10, 7], "radius": 32}, RECIPES)
    o = quickbuild.options(w, RECIPES, [(0.5, 4.5), (0.5, 10.5)])
    check("quick: inserters off two belts 6 apart", "inserter" in o and len(o["inserter"]["lines"]) == 2, o.keys())
    if "inserter" in o:
        a, b = o["inserter"]["lines"]
        st = quickbuild.row_step(w, o["inserter"], "inserter", 1)
        want = "south" if w.ents[b.belts[0]]["y"] > w.ents[a.belts[0]]["y"] else "north"
        check("quick: machines go between the two belts", st.get("second_belt") and st["side"] == want, st)
    w = World({"ents": _line(1, 4.5, 20, {"iron-plate": 3, "coal": 3}), "center": [10, 4], "radius": 32}, RECIPES)
    o = quickbuild.options(w, RECIPES, [(0.5, 4.5)])
    check("quick: steel furnaces off an iron+coal belt", o.get("steel-plate", {}).get("machine") == "stone-furnace", o)
    r = {"build": 0.9, "chain": 0.1, "elsewhere": 0.1, "product": "x", "product_p": 0.8}
    check("quick: a product that feeds further machines is refused", not quickbuild.accept({**r, "chain": 0.85}))
    check("quick: accept gate", quickbuild.accept(r) and not quickbuild.accept({**r, "elsewhere": 0.7})
          and not quickbuild.accept({**r, "product": "none_of_these"}))


def test_upgrade_map():
    m = upgrade_map("fast-transport-belt")
    check("upgrade: red belts take the undergrounds and splitters along",
          m == {"transport-belt": "fast-transport-belt", "underground-belt": "fast-underground-belt",
                "splitter": "fast-splitter"}, m)
    check("upgrade: assemblers 1 and 2 into 3", upgrade_map("assembling-machine-3") == {
        "assembling-machine-1": "assembling-machine-3", "assembling-machine-2": "assembling-machine-3"})
    check("upgrade: nothing goes down a tier", upgrade_map("transport-belt") == {})


def test_boiler_fault_positions():
    w = World({"ents": [], "center": [0, 0], "radius": 20,
               "grids": [{"id": 3, "cap_w": 0, "used_w": 0, "boilers": 2, "boilers_low_fuel": 2,
                          "boilers_low_at": [[40.5, 2.0], [40.5, 6.0]]}]})
    f = next((x for x in w.faults() if x["kind"] == "boiler_fuel"), None)
    check("world: low boilers carry their positions", f and f["boilers"] == [(40.5, 2.0), (40.5, 6.0)]
          and f["at"] == (40.5, 2.0), f)


def test_quickbelt_ends():
    src = _line(1, 0.5, 6, {"coal": 5})  # x 0.5..5.5, ends with nothing ahead
    boiler = {"u": 50, "n": "boiler", "t": "boiler", "x": 30.5, "y": 1.0, "w": 3, "h": 2}
    wa = World({"ents": src, "center": [3, 0], "radius": 16})
    wb = World({"ents": [boiler], "center": [30, 1], "radius": 16})
    ep = quickbelt.endpoints(wa, (2, 0), wb, (30, 1))
    check("quickbelt: coal line to a boiler gets a burner inserter on the near side",
          ep and ep["kind"] == "new_inserter" and ep["inserter"]["name"] == "burner-inserter"
          and ep["inserter"]["x"] < 30 and ep["from"] == [5.5, 0.5] and ep["item"] == "coal", ep)
    ep2 = quickbelt.endpoints(wb, (30, 1), wa, (2, 0))
    check("quickbelt: works with the points the other way round", ep2 and ep2["from"] == [5.5, 0.5], ep2)
    dst = _line(101, 5.5, 8, None)
    dst = [dict(e, x=e["x"] + 30) for e in dst]
    ins = {"u": 200, "n": "inserter", "t": "inserter", "x": 32.5, "y": 6.5, "d": "north", "pk": [32.5, 5.5],
           "dp": [32.5, 7.5], "pku": 103}
    wb2 = World({"ents": dst + [ins], "center": [33, 6], "radius": 16})
    ep3 = quickbelt.endpoints(wa, (2, 0), wb2, (33, 6))
    check("quickbelt: joins an input belt at its start", ep3 and ep3["kind"] == "join" and ep3["to"] == [30.5, 5.5],
          ep3)
    chest = {"u": 300, "n": "iron-chest", "t": "container", "x": 40.5, "y": 0.5}
    gi = {"u": 301, "n": "inserter", "t": "inserter", "x": 39.5, "y": 0.5, "d": "west", "pk": [38.5, 0.5],
          "dp": [40.5, 0.5], "dpu": 300}
    wb3 = World({"ents": [chest, gi], "center": [40, 0], "radius": 16})
    ep4 = quickbelt.endpoints(wa, (2, 0), wb3, (40, 0))
    check("quickbelt: ends under an inserter that picks from the ground", ep4 and ep4["kind"] == "inserter"
          and ep4["to"] == [38.5, 0.5], ep4)
    chk = [c["check"] for c in quickbelt.delivered(ep, "coal")] + [c["check"] for c in quickbelt.delivered(ep4, "coal")]
    check("quickbelt: a delivery is checked at the belt's end and in what its inserter feeds",
          chk == ["belt_carries", "has_item", "belt_carries", "has_item"]
          and quickbelt.delivered(ep, "coal")[1]["x"] == 30.5 and quickbelt.delivered(ep4, "coal")[1]["x"] == 40.5, chk)


def test_craftable():
    rec = {"iron-gear-wheel": {"ingredients": {"iron-plate": 2}, "category": "crafting"},
           "copper-cable": {"ingredients": {"copper-plate": 1}, "category": "electronics", "makes": 2},
           "electronic-circuit": {"ingredients": {"iron-plate": 1, "copper-cable": 3}, "category": "electronics"},
           "assembling-machine-1": {"ingredients": {"electronic-circuit": 3, "iron-gear-wheel": 5, "iron-plate": 9},
                                    "category": "crafting"}}
    # one assembler: 3 circuits (3 iron, 9 cable = 5 copper with a spare cable) + 5 gears (10 iron) + 9 iron = 22 iron
    check("craft: 22 iron + 5 copper make one assembler", craft.most("assembling-machine-1",
          {"iron-plate": 22, "copper-plate": 5}, rec) == 1)
    check("craft: copper is the limit", craft.most("assembling-machine-1",
          {"iron-plate": 1000, "copper-plate": 9}, rec) == 2)
    check("craft: stocked intermediates count", craft.most("assembling-machine-1",
          {"assembling-machine-1": 2, "electronic-circuit": 3, "iron-gear-wheel": 5, "iron-plate": 9}, rec) == 3)


def test_full_chest_listed_once():
    ents = [{"u": 1, "n": "stone-furnace", "t": "furnace", "x": 1, "y": 1, "w": 2, "h": 2, "s": "full_output"},
            {"u": 2, "n": "inserter", "t": "inserter", "x": 1.5, "y": 2.5, "d": "north", "pk": [1.5, 1.5],
             "dp": [1.5, 3.5], "pku": 1, "dpu": 3},
            {"u": 3, "n": "wooden-chest", "t": "container", "x": 1.5, "y": 3.5, "free": 0, "inv": {"iron-plate": 1600}}]
    kinds = [f["kind"] for f in World({"ents": ents, "center": [1, 2]}).faults()]
    check("world: a full chest behind a full furnace is one fault, not two", kinds.count("chest_full") == 0
          and "output_full" in kinds, kinds)


def test_wrong_recipe():
    rec = {"pipe": {"ingredients": {"iron-plate": 1}}, "iron-gear-wheel": {"ingredients": {"iron-plate": 2}},
           "automation-science-pack": {"ingredients": {"copper-plate": 1, "iron-gear-wheel": 1}}}
    ents = [{"u": 1, "n": "assembling-machine-1", "t": "assembling-machine", "x": 1.5, "y": 1.5, "w": 3, "h": 3,
             "r": "pipe", "s": "working"},
            {"u": 2, "n": "inserter", "t": "inserter", "x": 1.5, "y": 3.5, "d": "north", "pk": [1.5, 2.5],
             "dp": [1.5, 4.5], "pku": 1, "dpu": 3},
            {"u": 3, "n": "assembling-machine-1", "t": "assembling-machine", "x": 1.5, "y": 5.5, "w": 3, "h": 3,
             "r": "automation-science-pack", "s": "item_ingredient_shortage"}]
    w = World({"ents": ents, "center": [1, 3]}, rec)
    f = next((x for x in w.faults() if x["kind"] == "wrong_recipe"), None)
    check("world: a pipe assembler feeding red science should make gears",
          f and f["fixes"][0]["recipe"] == "iron-gear-wheel", f)
    # "fix the gear setup": a pipe assembler filling a chest, nothing downstream to say gears are wanted but the order
    w = World({"ents": ents[:2], "center": [1, 3]}, rec)
    wanted = quickbuild.products_named("@serf fix the gear setup at [gps=1,1]", list(rec))
    f = w.wanted_faults(wanted)
    check("world: the order names gears and an assembler there makes pipes from the same plates",
          wanted == ["iron-gear-wheel"] and f and f[0]["fixes"][0]["recipe"] == "iron-gear-wheel", (wanted, f))
    belts = ents[:2] + [{"u": 9, "n": "pipe", "t": "pipe", "x": 5.5, "y": 5.5}]
    check("world: 'fix the pipes' with pipes standing there names them, not a product",
          not World({"ents": belts, "center": [1, 3]}, {**rec, "iron-gear-wheel": rec["iron-gear-wheel"]})
          .wanted_faults(["pipe"]) and not World({"ents": belts, "center": [1, 3]}, rec).wanted_faults(
              quickbuild.products_named("fix the pipes", list(rec))))
    check("world: no such fault when the order names nothing made here",
          not w.wanted_faults(quickbuild.products_named("the smelter at [gps=1,1] isn't making much", list(rec))))


def test_connected():
    # ore line A (x 0.5..3.5), a gap at 4.5, line B (x 5.5..8.5) feeding a furnace by an inserter; plates out by another
    # inserter into a chest. From the chest, the gap's last belt is linked; an unrelated belt nearby isn't.
    a = _line(1, 0.5, 4, {"iron-ore": 2})
    b = [dict(e, x=e["x"] + 5) for e in _line(11, 0.5, 4, {"iron-ore": 2})]
    fur = {"u": 30, "n": "stone-furnace", "t": "furnace", "x": 8.0, "y": 3.0, "w": 2, "h": 2}
    i1 = {"u": 31, "n": "inserter", "t": "inserter", "x": 7.5, "y": 1.5, "pku": 13, "dpu": 30}
    i2 = {"u": 32, "n": "inserter", "t": "inserter", "x": 7.5, "y": 4.5, "pku": 30, "dpu": 33}
    chest = {"u": 33, "n": "iron-chest", "t": "container", "x": 7.5, "y": 5.5}
    other = _line(41, 9.5, 3, {"stone": 1})
    w = World({"ents": a + b + [fur, i1, i2, chest] + other, "center": [5, 3], "radius": 20})
    linked = w.connected({33})
    gaps = [f for f in w.faults() if f["kind"] == "belt_gap"]
    check("world: from the chest, the line through the furnace back to the gap is linked; the stone belt isn't",
          4 in linked and 30 in linked and not (linked & {41, 42, 43}) and gaps and gaps[0]["u"] in linked,
          (sorted(linked), gaps))


def test_inserter_backwards():
    line = _line(1, 0.5, 6, {"iron-ore": 3, "coal": 2})
    fur = {"u": 30, "n": "stone-furnace", "t": "furnace", "x": 3.0, "y": 3.0, "w": 2, "h": 2, "r": "iron-plate",
           "s": "no_ingredients"}
    back = {"u": 31, "n": "inserter", "t": "inserter", "x": 2.5, "y": 1.5, "d": "south", "pku": 30, "dpu": 3}
    out = {"u": 32, "n": "inserter", "t": "inserter", "x": 2.5, "y": 4.5, "d": "north", "pku": 30, "dpu": 33}
    chest = {"u": 33, "n": "iron-chest", "t": "container", "x": 2.5, "y": 5.5}
    w = World({"ents": line + [fur, back, out, chest], "center": [3, 3]}, {"iron-plate": {"ingredients": {"iron-ore": 1}}})
    f = [x for x in w.faults() if x["kind"] == "inserter_backwards"]
    check("world: an inserter taking from an unfed furnace onto its ore belt is turned around (and only that one)",
          len(f) == 1 and f[0]["u"] == 31 and f[0]["fixes"][0]["direction"] == "north", f)
    fresh = dict(fur, r=None)
    w = World({"ents": line + [fresh, back, out, chest], "center": [3, 3]}, {"iron-plate": {"ingredients": {"iron-ore": 1}}})
    check("world: also when the furnace never smelted (no recipe yet)",
          [x["u"] for x in w.faults() if x["kind"] == "inserter_backwards"] == [31])


def test_options_nearest_line():
    a = _line(1, 0.5, 30, {"iron-plate": 5})
    b = _line(101, 12.5, 30, {"iron-plate": 5})
    w = World({"ents": a + b, "center": [10, 6], "radius": 32})
    rec = {"pipe": {"ingredients": {"iron-plate": 1}, "category": "crafting"}}
    o1 = quickbuild.options(w, rec, [(2, 12)]).get("pipe") or {}
    o2 = quickbuild.options(w, rec, [(2, 0)]).get("pipe") or {}
    check("quickbuild: of two parallel iron belts, the row goes on the one the order points at",
          o1.get("lines") and o1["lines"][0].start[1] == 12.5 and o2["lines"][0].start[1] == 0.5,
          (o1.get("lines") and o1["lines"][0].start, o2.get("lines") and o2["lines"][0].start))


def test_only_word():
    check("quickbuild: 'I need copper made' off an ore belt means copper plates; 'copper cable' doesn't",
          quickbuild.only_word("I need copper made from this belt, a couple of furnaces, into chests", ["copper-plate"])
          == "copper-plate" and quickbuild.only_word("make copper cable off this belt", ["copper-plate"]) is None
          and quickbuild.only_word("make iron stuff here", ["iron-chest", "iron-gear-wheel"]) is None)


def test_fluid_input():
    plant = {"u": 1, "n": "chemical-plant", "t": "assembling-machine", "x": 0.5, "y": 0.5, "w": 3, "h": 3, "r": "sulfur",
             "s": "fluid_ingredient_shortage",
             "fin": [{"want": "water", "amt": 0, "linked": 1, "at": [-0.5, -1.5], "next": "petroleum-gas",
                      "next_kind": "pipe"},
                     {"want": "petroleum-gas", "amt": 0, "linked": 0, "at": [1.5, -1.5]}]}
    f = [x for x in World({"ents": [plant], "center": [0, 0]}).faults() if x["kind"] == "fluid_input"]
    check("world: a chemical plant with petroleum on its water inlet says so, and that the other inlet has no pipe",
          f and "has petroleum-gas in the pipe joined to it" in f[0]["text"] and "petroleum-gas inlet at 1.5,-1.5 has "
          "no pipe" in f[0]["text"], f)


def test_unfed():
    line = _line(1, 0.5, 6, {"iron-ore": 3, "coal": 2})
    fur = {"u": 30, "n": "stone-furnace", "t": "furnace", "x": 3.0, "y": 3.0, "w": 2, "h": 2, "s": "no_ingredients"}
    f = [x for x in World({"ents": line + [fur], "center": [3, 3], "radius": 12}).faults() if x["kind"] == "unfed"]
    fx = f and f[0]["fixes"][0]
    check("world: a furnace two tiles from its ore belt with no inserter gets a burner inserter picking off the belt",
          fx and fx["name"] == "burner-inserter" and fx["y"] == 1.5 and fx["pickup"][1] == 0.5 and fx.get("then_refuel"),
          f)
    ins = {"u": 31, "n": "inserter", "t": "inserter", "x": 2.5, "y": 1.5, "d": "north", "pku": 3, "dpu": 30}
    check("world: not when an inserter feeds it", not [x for x in World({"ents": line + [fur, ins], "center": [3, 3],
          "radius": 12}).faults() if x["kind"] == "unfed"])
    # an empty chest feeding a gear assembler, a plate belt ending two tiles from it, no inserter between
    plates = _line(1, 0.5, 4, {"iron-plate": 6})  # x 0.5..3.5
    chest = {"u": 40, "n": "iron-chest", "t": "container", "x": 5.5, "y": 0.5}
    take = {"u": 41, "n": "inserter", "t": "inserter", "x": 6.5, "y": 0.5, "d": "west", "pku": 40, "dpu": 42}
    asm = {"u": 42, "n": "assembling-machine-1", "t": "assembling-machine", "x": 8.5, "y": 0.5, "w": 3, "h": 3,
           "r": "iron-gear-wheel", "s": "item_ingredient_shortage"}
    f = [x for x in World({"ents": plates + [chest, take, asm], "center": [4, 0], "radius": 12},
                          {"iron-gear-wheel": {"ingredients": {"iron-plate": 2}}}).faults() if x["kind"] == "unfed"]
    check("world: an empty chest feeding a gear assembler gets the inserter from the plate belt that ends by it",
          f and f[0]["u"] == 40 and f[0]["fixes"][0]["x"] == 4.5 and f[0]["fixes"][0]["pickup"] == [3.5, 0.5], f)


def test_options_bent_line():
    # iron plates east along y=0.5 for 12 tiles, then turning south along x=12.5 for 12 tiles: one line
    ents = []
    pos = [(0.5 + k, 0.5, "east") for k in range(12)] + [(12.5, 0.5 + k, "south") for k in range(12)]
    for k, (x, y, d) in enumerate(pos):
        ents.append(belt(k + 1, x, y, d, o=[k + 2] if k < len(pos) - 1 else None, i=[k] if k else None,
                         items={"iron-plate": 2}))
    w = World({"ents": ents, "center": [10, 8], "radius": 32})
    rec = {"pipe": {"ingredients": {"iron-plate": 1}, "category": "crafting"}}
    o1 = quickbuild.options(w, rec, [(13, 9)]).get("pipe") or {}
    o2 = quickbuild.options(w, rec, [(3, 0)]).get("pipe") or {}
    check("quickbuild: a belt that turns offers its straight stretches; the row goes on the one pointed at",
          len(w.lines) == 1 and o1.get("lines") and o1["lines"][0].direction == "south" and o2.get("lines")
          and o2["lines"][0].direction == "east",
          (len(w.lines), o1.get("lines") and o1["lines"][0].direction, o2.get("lines") and o2["lines"][0].direction))


def test_engine_slot():
    ents = [{"u": 1, "n": "boiler", "t": "boiler", "x": 0.5, "y": 5.0, "d": "north", "w": 3, "h": 2},
            {"u": 2, "n": "steam-engine", "t": "generator", "x": 0.5, "y": 1.5, "d": "north", "w": 3, "h": 5, "net": 7}]
    w = World({"ents": ents, "center": [0, 0], "radius": 20,
               "grids": [{"id": 7, "cap_w": 900000, "used_w": 899999}]})
    f = next((x for x in w.faults() if x["kind"] == "power_maxed"), None)
    fx = (f or {}).get("fixes") or [{}]
    check("world: a maxed grid with a one-engine boiler gets the second engine end to end",
          fx[0].get("name") == "steam-engine" and fx[0].get("x") == 0.5 and fx[0].get("y") == -3.5, f)
    ents.append({"u": 3, "n": "steam-engine", "t": "generator", "x": 0.5, "y": -3.5, "d": "north", "w": 3, "h": 5,
                 "net": 7})
    w = World({"ents": ents, "center": [0, 0], "radius": 20, "grids": [{"id": 7, "cap_w": 1800000, "used_w": 1799999}]})
    f = next((x for x in w.faults() if x["kind"] == "power_maxed"), None)
    check("world: a boiler with both engines has no code fix (more boilers are the planner's)", f and not f["fixes"], f)


def test_copy_offsets():
    orig = [(12, 8), (16, 30)]
    d = quickcopy.offsets(orig, [(28, 8), (44, 8), (32, 30), (48, 30)])
    check("copy: belt+chest pairs give two shifts", sorted(d) == [(16, 0), (32, 0)], d)
    d = quickcopy.offsets(orig, [(60, 8), (76, 8), (92, 8), (108, 8)], spacing=10)
    check("copy: one point per copy works when they're a build apart", sorted(d) == [(48, 0), (64, 0), (80, 0),
                                                                                     (96, 0)], d)
    check("copy: points too close for copies aren't copies", quickcopy.offsets(orig, [(60, 8), (63, 8)],
                                                                                 spacing=10) == [])
    check("copy: a different shape isn't a copy", quickcopy.offsets(orig, [(28, 8), (40, 40)]) == [])
    d = quickcopy.offsets([(12, 8), (16, 30), (0, 8), (-7, 14)], [(28, 8), (44, 8), (32, 30), (48, 30)])
    check("copy: shared points of the first order (supply chest, pole) don't stop a match",
          sorted(d) == [(16, 0), (32, 0)], d)
    d = quickcopy.offsets([(28, 8), (44, 8), (32, 30), (48, 30)], [(60, 8), (76, 8), (92, 8), (108, 8)])
    check("copy: a two-column unit copied twice for four, not three overlapping times", sorted(d) == [(32, 0), (64, 0)],
          d)


def test_feeder_option():
    rec = {"iron-gear-wheel": {"ingredients": {"iron-plate": 2}, "category": "crafting", "time": 0.5},
           "automation-science-pack": {"ingredients": {"copper-plate": 1, "iron-gear-wheel": 1},
                                       "category": "crafting", "time": 5},
           "copper-cable": {"ingredients": {"copper-plate": 1}, "category": "electronics", "time": 0.5, "makes": 2},
           "electronic-circuit": {"ingredients": {"iron-plate": 1, "copper-cable": 3}, "category": "electronics",
                                  "time": 0.5}}
    iron = [dict(b, lanes=[{}, {"iron-plate": 2}]) for b in _line(1, 4.5, 20, None)]
    copper = [dict(b, lanes=[{"copper-plate": 2}, {}]) for b in _line(101, 10.5, 20, None)]
    w = World({"ents": iron + copper, "center": [10, 7], "radius": 32}, rec)
    o = quickbuild.options(w, rec, [(0.5, 4.5), (0.5, 10.5)])
    red = o.get("automation-science-pack") or {}
    check("feeder: red science from the copper belt plus gears made off the iron belt",
          red.get("feeder", {}).get("recipe") == "iron-gear-wheel" and red.get("feeder", {}).get("left") is True, red)
    circ = o.get("electronic-circuit") or {}
    check("feeder: circuits from the iron belt plus cable made off the copper belt",
          circ.get("feeder", {}).get("recipe") == "copper-cable" and circ.get("feeder", {}).get("left") is False, circ)
    check("feeder: 2 gear assemblers for 3 science (inserter-limited to ~0.4 gears/s each); 3 cable for 2 circuit",
          quickbuild.feeders_needed(rec, "automation-science-pack", "iron-gear-wheel", 3) == 2 and
          quickbuild.feeders_needed(rec, "electronic-circuit", "copper-cable", 2) == 3,
          (quickbuild.feeders_needed(rec, "automation-science-pack", "iron-gear-wheel", 3),
           quickbuild.feeders_needed(rec, "electronic-circuit", "copper-cable", 2)))
    check("feeder: 3 circuit assemblers want 4 cable feeders; a 30-tile belt has room for 3 beside a 3-machine row",
          quickbuild.feeders_needed(rec, "electronic-circuit", "copper-cable", 3) == 4 and
          quickbuild.feeders_that_fit(30, 4, 3) == 3 and quickbuild.feeders_that_fit(60, 4, 3) == 4 and
          quickbuild.feeders_that_fit(10, 4, 3) == 1,
          (quickbuild.feeders_needed(rec, "electronic-circuit", "copper-cable", 3),
           quickbuild.feeders_that_fit(30, 4, 3)))
    check("output belt: named only by words for one, not by the belt it comes off",
          not quickbuild.OUTPUT_BELT.search("make steel off the belt at [gps=1,2]") and
          not quickbuild.OUTPUT_BELT.search("gears made from this belt [gps=1,2], 3 assemblers, into chests") and
          quickbuild.OUTPUT_BELT.search("put the cable on a belt") and
          quickbuild.OUTPUT_BELT.search("plates off that belt, output on a belt"))
    ents, c = quickbuild.feeder_layout(w, red, 1)
    am = [e for e in ents if e["name"] == "assembling-machine-1"][0]
    ins = sorted(e["y"] for e in ents if e["name"] == "inserter")
    check("feeder: gear assembler sits between the belts, inserters at both", am["y"] == 7.5 and ins == [5.5, 9.5]
          and am["recipe"] == "iron-gear-wheel", ents)
    copper_busy = [dict(b, lanes=[{"copper-plate": 2}, {"stone": 1}]) for b in _line(101, 10.5, 20, None)]
    w2 = World({"ents": iron + copper_busy, "center": [10, 7], "radius": 32}, rec)
    check("feeder: not offered when the lane it would use is taken",
          "feeder" not in (quickbuild.options(w2, rec, [(0.5, 4.5)]).get("automation-science-pack") or {}))


def test_mine_layout():
    tiles = {(x, y) for x in range(100, 115) for y in range(0, 9)}  # a 15x9 patch
    lay = quickmine.layout(tiles, 6, toward_x=0)
    check("mine: 6 drills, belt running west toward the destination", lay and lay["drills"] == 6
          and lay["direction"] == "west", lay and {k: v for k, v in lay.items() if k != "ents"})
    if lay:
        drills = [e for e in lay["ents"] if e["name"] == "electric-mining-drill"]
        belts = [e for e in lay["ents"] if e["name"] == "transport-belt"]
        belt_y = belts[0]["y"]
        drops = {(d["x"], d["y"] + (2 if d["direction"] == "south" else -2)) for d in drills}
        check("mine: every drill drops onto the belt", all(abs(dy - belt_y) < 0.01 for _, dy in drops), drops)
        tiles_used = [(math.floor(e["x"] - 1.5 + 0.01) + i, math.floor(e["y"] - 1.5 + 0.01) + j)
                      for e in drills for i in range(3) for j in range(3)]
        check("mine: drills don't overlap", len(tiles_used) == len(set(tiles_used)))
    tall = {(x, y) for x in range(10, 18) for y in range(0, 16)}  # 8 wide, 16 tall
    lay = quickmine.best_layout(tall, 6, (10, 200))
    across = quickmine.layout(tall, 6, 14)
    check("mine: a tall narrow patch gets a north-south belt and more drills than rows across it",
          lay and lay["direction"] == "south" and lay["drills"] == 6 and across and across["drills"] < 6,
          (lay and {k: v for k, v in lay.items() if k != "ents"}, across and across["drills"]))
    if lay:
        drills = [e for e in lay["ents"] if e["name"] == "electric-mining-drill"]
        bx = [e for e in lay["ents"] if e["name"] == "transport-belt"][0]["x"]
        check("mine: mirrored drills face the belt (east of it facing west, west of it facing east)",
              all((d["direction"] == "east" and d["x"] < bx) or (d["direction"] == "west" and d["x"] > bx)
                  for d in drills), drills)
        check("mine: mirrored drills sit on ore", all((math.floor(d["x"]), math.floor(d["y"])) in tall for d in drills))
    check("mine: '60 ore a minute' is 3 drills; '4 drills' is 4", quickmine.wanted_drills(
        "I want at least 60 ore a minute") == 3 and quickmine.wanted_drills("put 4 drills on it") == 4)


def test_named_products():
    opts = ["iron-gear-wheel", "pipe", "iron-chest", "iron-plate"]
    check("named: gears and pipes is two", quickbuild.named_products("make gears and pipes off this belt", opts) == 2)
    check("named: 'pipes, 3 assemblers, into chests' is one",
          quickbuild.named_products("I need pipes made from this belt, 3 assemblers, into chests", opts) == 1)
    check("named: 'plates ... into chests' is none", quickbuild.named_products("plates from this belt, into chests",
                                                                                  ["iron-plate"]) == 0)


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
    w2 = World({"ents": [], "center": [0, 0]})
    probs = lint([{"do": "place", "name": "burner-mining-drill", "x": 40, "y": -100, "direction": "south"},
                  {"do": "place", "name": "stone-furnace", "x": 40, "y": -98}], w2, None, {})
    check("lint: a burner drill dropping into a furnace feeds it", not any("nothing feeds" in p for p in probs), probs)
    probs = lint([{"do": "place", "name": "burner-mining-drill", "x": 40, "y": -100, "direction": "north"},
                  {"do": "place", "name": "stone-furnace", "x": 40, "y": -98}], w2, None, {})
    check("lint: a drill facing away doesn't", any("nothing feeds" in p for p in probs), probs)
    probs = lint([{"do": "place", "name": "burner-mining-drill", "x": -38, "y": -25, "direction": "south"},
                  {"do": "place", "name": "iron-chest", "x": -38.5, "y": -23.5}], w2, None, {})
    check("lint: a chest one tile off the drill's output is flagged", any("drops its ore" in p for p in probs), probs)
    probs = lint([{"do": "place", "name": "burner-mining-drill", "x": -38, "y": -25, "direction": "south"},
                  {"do": "place", "name": "iron-chest", "x": -37.5, "y": -23.5}], w2, None, {})
    check("lint: a chest on the drill's output is fine", not any("drops its ore" in p for p in probs), probs)


def test_lint_connect_mixing():
    # line A: coal belts running east ending at 5.5,0.5; line B: plastic belts running south through 10.5,y
    ents = [{"u": i + 1, "n": "transport-belt", "t": "transport-belt", "x": 0.5 + i, "y": 0.5, "d": "east",
             "lanes": [{"coal": 2}, {}]} for i in range(6)]
    ents += [{"u": 100 + j, "n": "transport-belt", "t": "transport-belt", "x": 10.5, "y": -5.5 + j, "d": "south",
              "lanes": [{"plastic-bar": 2}, {}]} for j in range(12)]
    w = World({"ents": ents, "center": [5, 0]})
    probs = lint([{"do": "connect", "item": "transport-belt", "from": [5.5, 0.5], "to": [10.5, 2.5]}], w, None, {})
    check("lint: a connect that runs coal onto a plastic belt is flagged", any("would put coal" in p for p in probs),
          probs)
    probs = lint([{"do": "connect", "item": "transport-belt", "from": [5.5, 0.5], "to": [9.5, 8.5]}], w, None, {})
    check("lint: a connect ending on empty ground isn't", not any("would put" in p for p in probs), probs)


def test_failure_facts():
    f = failure_facts("cannot place assembling-machine-1 at 1.5,2.5: blocked by character@1.2,2.4")
    check("facts: blocked only by the character", f["blocked_only_by_the_character"], f)
    f = failure_facts("cannot place inserter at 1,2: blocked by transport-belt@1,2, character@1,2")
    check("facts: a belt too is not only the character", not f["blocked_only_by_the_character"], f)
    f = failure_facts("needs 1 wooden-chest but you have 0; no chest or machine output within 400 tiles has any, "
                      "and you can't hand-craft the other 1 from what you carry")
    check("facts: item exists nowhere", f["item_exists_nowhere"], f)
    check("facts: already done", failure_facts("automation-2 is already researched")["already_done"])


# ---------------------------------------------------------------------------- tonight's core changes (2026-10-22)
def test_copy_words_heldout():
    import json
    held = json.loads((ROOT / "lab/data/hard_orders.json").read_text())["copy"]
    wrong = [c["order"] for c in held if bool(quickcopy.COPY_WORDS.search(c["order"])) != bool(c["copy"])]
    check(f"quick copy: copy words agree with the held-out copy set ({len(held)} orders)", not wrong, wrong)
    check("quick copy: 'two more like that' / 'x3' / 'same one' are copies",
          all(quickcopy.COPY_WORDS.search(t) for t in ("two more like that at [gps=1,2]", "copy paste that x3",
                                                        "make same one also at [gps=3,4]")))
    check("quick copy: a sulfur-plant complaint with a number isn't a copy (r3)",
          not quickcopy.COPY_WORDS.search("the sulfur plant gets no petroleum gas, only 0.75 a second"))


def test_research_queue_guards():
    import asyncio
    from types import SimpleNamespace
    from jev import fastpaths
    from jev.fastpaths import QUEUE_WORDS, FastPaths
    check("research: queue words caught", all(QUEUE_WORDS.search(t) for t in (
        "research automation then logistics", "queue steel processing after electronics",
        "remove military from the research queue", "research fluid handling and its prerequisites")))
    check("research: a single tech has no queue words", not any(QUEUE_WORDS.search(t) for t in (
        "research automation 2", "can you research steel axe please", "get logistics researched")))
    techs = [{"name": "automation-2"}, {"name": "logistics-2"}, {"name": "steel-axe"}]

    async def call(op, **kw):
        return {"available": techs}

    async def run(step):
        ran.append(step)
        return {"ok": True}

    async def say(text):
        said.append(text)

    async def research(jev, text, ts):
        return "steel-axe", 0.95

    def fake():
        return SimpleNamespace(g=SimpleNamespace(call=call), log=logs.append, name="serf", jev=None,
                               metrics={"fast_path": 0}, runner=SimpleNamespace(run=run), say=say)
    old = fastpaths.decide.research
    fastpaths.decide.research = research
    try:
        for text, want, why in (("research automation 2 and logistics 2", False, "names"),
                                ("research automation-2, then logistics-2", False, "queue"),
                                ("research steel axe", True, None)):
            ran, said, logs = [], [], []
            got = asyncio.run(FastPaths._quick_research(fake(), SimpleNamespace(id=1, text=text)))
            skip = next((r.get("why", "") for r in logs if r.get("kind") == "quick_research_skip"), "")
            check(f"research: {text!r} -> {'quick path' if want else 'the planner'}",
                  got is want and (want or why in skip) and (not want or ran[0].get("tech") == "steel-axe"),
                  (got, skip, ran))
    finally:
        fastpaths.decide.research = old


def test_quickbelt_item_guard():
    items = ["advanced-circuit", "electronic-circuit", "sulfur", "coal", "iron-plate", "copper-plate",
             "transport-belt", "inserter", "iron-chest"]
    infra = {"transport-belt", "inserter", "iron-chest"}

    def guard(order, belt_item):  # the check in FastPaths._quick_belt: skip when the order names other items
        named = [x for x in quickbuild.products_named(order, items) if x not in infra]
        return bool(named) and belt_item not in named
    order = "get the advanced circuits from [gps=10,0] over to [gps=60,0]"
    check("quick belt: 'advanced circuits' named", quickbuild.products_named(order, items) == ["advanced-circuit"],
          quickbuild.products_named(order, items))
    check("quick belt: a sulfur belt end isn't the job for advanced circuits (r5)", guard(order, "sulfur"))
    check("quick belt: an advanced-circuit belt is", not guard(order, "advanced-circuit"))
    check("quick belt: an order naming no item doesn't block it",
          not guard("belt that from [gps=0,0] to the chest at [gps=50,0]", "coal"))
    check("quick belt: 'with belts and inserters' names no cargo",
          not guard("move the coal to the boilers with belts and inserters", "coal"))


def test_quickmine_guard():
    import re
    rec = {"iron-gear-wheel": {"ingredients": {"iron-plate": 2}},
           "copper-cable": {"ingredients": {"copper-plate": 1}, "makes": 2},
           "electronic-circuit": {"ingredients": {"iron-plate": 1, "copper-cable": 3}},
           "electric-mining-drill": {"ingredients": {"electronic-circuit": 3, "iron-gear-wheel": 5, "iron-plate": 10}}}

    def skips(text, stock):  # the guard in FastPaths._quick_mine
        return bool(re.search(r"\bburner", text, re.I)) or craft.most("electric-mining-drill", stock, rec, 2) < 2
    check("quick mine: a fresh map with nothing to make drills from goes to the planner (c1)",
          skips("mine iron at [gps=10,10]", {}))
    check("quick mine: burner drills go to the planner", skips("put 2 burner drills on the coal", {"iron-plate": 999,
                                                                                                 "copper-plate": 999}))
    check("quick mine: plates for two drills are enough", not skips("mine iron at [gps=10,10]",
                                                                    {"iron-plate": 100, "copper-plate": 20}))


def test_says_what_is_wrong():
    from jev.actor import Actor
    s = Actor._says_what_is_wrong
    check("reopen: 'not done yet' alone says nothing new", not s("ops: @serf not done yet, keep going"))
    check("reopen: a number says what's wrong (x-outpost)",
          s("ops: @serf not done yet: drills on grid is 0, needs 2. Keep going on it."))
    check("reopen: a place says what's wrong", s("ops: the belt at [gps=10,-4] is still empty"))
    check("reopen: a sentence says what's wrong", s("ops: the drills are on their own grid and never get any power"))
    check("reopen: a short nudge doesn't", not s("ops: nope, not yet"))


def test_raw_buffer():
    from jev.actor import Actor
    ents = [{"u": 1, "n": "iron-chest", "t": "container", "x": 0.5, "y": 0.5, "inv": {"iron-ore": 3200}},
            {"u": 2, "n": "iron-chest", "t": "container", "x": 4.5, "y": 0.5, "inv": {"iron-plate": 3200}},
            {"u": 3, "n": "iron-chest", "t": "container", "x": 8.5, "y": 0.5, "inv": {"coal": 50, "stone": 3150}},
            {"u": 4, "n": "iron-chest", "t": "container", "x": 12.5, "y": 0.5, "inv": {"coal": 9, "iron-plate": 1}},
            {"u": 5, "n": "inserter", "t": "inserter", "x": 12.5, "y": 1.5, "pku": 4, "dpu": 6},
            {"u": 6, "n": "assembling-machine-1", "t": "assembling-machine", "x": 12.5, "y": 3.5},
            {"u": 7, "n": "stone-furnace", "t": "furnace", "x": 4, "y": 3, "s": "full_output"}]
    w = World({"ents": ents, "center": [0, 0]})
    rb = Actor._buffer
    check("watch: a full chest of ore at a mine is a buffer (oil-r2)", rb(w, {"kind": "chest_full", "u": 1}))
    check("watch: coal and stone together too", rb(w, {"kind": "chest_full", "u": 3}))
    check("watch: a full chest of plates nothing takes from is a store (yellow-blk-r5)",
          rb(w, {"kind": "chest_full", "u": 2}))
    check("watch: a furnace stopped on that store is too",
          rb(w, {"kind": "output_full", "u": 7, "fixes": [{"do": "empty_chest", "x": 4.5, "y": 0.5}]}))
    check("watch: a full chest an inserter takes from is a fault", not rb(w, {"kind": "chest_full", "u": 4}))
    check("watch: an unknown entity is a fault", not rb(w, {"kind": "chest_full", "u": 99}))
    check("watch: other faults aren't stores", not rb(w, {"kind": "no_fuel", "u": 7}))


def test_detailed_order():
    from jev.actor import Actor
    d = Actor._detailed
    check("fix order: a short one is the code fixer's", not d("@serf something's wrong with the iron line at "
                                                             "[gps=10,4], fix it please"))
    check("fix order: 'refuel everything' is too", not d("@serf all the furnaces are out of fuel, get them going"))
    check("fix order: a numbered list says what to do", d("@serf Two fixes. 1) The red science assembler at "
                                                          "[gps=-20.5,-33.5] has no copper. 2) Labs are idle."))
    check("fix order: so does a long description (yellow-blk-r5)", d(
        "@serf The furnaces are out of fuel: the stone furnaces in the column at [gps=74,6] to [gps=74,26] and the "
        "steel furnaces at [gps=84,14] to [gps=84,26]. Give them a permanent coal feed by belt and inserter so "
        "nobody has to fuel them by hand. There's a coal belt full of coal right next to them at [gps=69.5,15] "
        "(and another at [gps=67.5,15]). Use long-handed inserters."))
    check("fix order: gps numbers aren't a list", not d("@serf fix the belt at [gps=1,2] and [gps=3,4]"))


def test_route_clears_only_its_own_attempt():
    import asyncio
    import jev.router
    from jev.steps import Runner

    class G:
        name = "serf"
        def __init__(self):
            self.mined = []
        async def scan(self, center=None, radius=None, tiles=False):
            belt = lambda u, x, y: {"u": u, "n": "transport-belt", "t": "transport-belt", "x": x, "y": y, "by": "serf"}
            return {"ents": [belt(1, 5.5, 0.5), belt(2, 6.5, 0.5),  # an earlier try at these lines
                             belt(3, 5.5, 8.5), belt(4, 6.5, 8.5)],  # a working line the serf built long ago
                    "center": [5, 4]}
        async def call(self, op, **k):
            return {"materials": {}}
        async def me(self):
            return {"position": [0, 0], "inventory": {"transport-belt": 50}}
        async def run(self, a, timeout=None):
            if a["op"] == "mine":
                self.mined.append((a["x"], a["y"]))
            return {"ok": True, "msg": "ok"}

    real = jev.router.solve
    jev.router.solve = lambda *a, **k: (None, "no clean layout")
    try:
        g = G()
        r = Runner(g)
        step = {"do": "route", "pairs": [{"from": [0, 0], "to": [12, 0]}]}
        asyncio.run(r._do_route(step))
        check("route: with no earlier try, a failed layout mines nothing (p2 g5)", g.mined == [], g.mined)
        r.routed = [{"ends": {(0, 0), (12, 0)}, "tiles": {(5, 0), (6, 0)}}]
        asyncio.run(r._do_route(step))
        check("route: it picks up only its earlier try at the same lines", sorted(g.mined) == [(5.5, 0.5), (6.5, 0.5)],
              g.mined)
    finally:
        jev.router.solve = real


def test_fluid_backup():
    from jev.world import fluid_backup
    fb = [{"have": "heavy-oil", "amt": 1000, "cap": 1000, "linked": 1},
          {"have": "light-oil", "amt": 120, "cap": 1000, "linked": 1},
          {"have": "petroleum-gas", "amt": 1000, "cap": 1000, "linked": 0}]
    t = fluid_backup(fb)
    check("fluid backup: names the full outputs and how to drain them (yellow stage oil deadlock)",
          "heavy-oil is backed up" in t and "heavy-oil-cracking" in t and "petroleum-gas is backed up" in t
          and "no pipe takes it away" in t and "light-oil" not in t, t)
    check("fluid backup: nothing full, nothing said", fluid_backup([{"have": "water", "amt": 5, "cap": 100}]) == "")
    w = World({"ents": [{"u": 1, "n": "oil-refinery", "t": "assembling-machine", "x": 0.5, "y": 0.5, "w": 5, "h": 5,
                         "s": "full_output", "r": "advanced-oil-processing", "fout": fb}], "center": [0, 0]})
    f = [x for x in w.faults() if x["kind"] == "output_full"]
    check("fluid backup: the refinery's output-full fault says which", f and "heavy-oil is backed up" in f[0]["text"],
          [x["text"] for x in w.faults()])


def test_project_by_hand():
    from types import SimpleNamespace
    from jev.project import Project
    actor = SimpleNamespace(stocked=[{"x": 129.5, "y": 14.5, "item": "stone", "count": 450, "topped": 4, "moved": 1700},
                                     {"x": 1.5, "y": 2.5, "item": "coal", "count": 100}],
                            fuelled=[(0, 0), (1, 1), (2, 2)])
    t = Project._by_hand(SimpleNamespace(actor=actor))
    check("project: the report says what the serf keeps going by hand", "stone into the chest at [gps=130,14]" in t
          and "topped up 4 times" in t and "3 burners" in t and "coal" not in t, t)
    check("project: nothing by hand, nothing said",
          Project._by_hand(SimpleNamespace(actor=SimpleNamespace(stocked=[], fuelled=[]))) == "")


def test_numbered_order():
    from jev.actor import Actor
    n = Actor._numbered
    check("numbered: '1) ... 2) ...' (p2 copper)", n("@serf Copper is short. 1) Add 10 drills. 2) Swap the furnaces."))
    check("numbered: '(1) ... (2) ...'", n("@serf Two things. (1) Research queue: lubricant. (2) Purple feeds."))
    check("numbered: '1. ... 2. ...'", n("@serf do this: 1. lay the belt 2. place the chest"))
    check("numbered: one item isn't a list", not n("@serf 1) build a steel column at [gps=10,4]"))
    check("numbered: gps numbers aren't", not n("@serf belt from [gps=1,2] to [gps=2,1]"))
    check("numbered: a long one-job order isn't (t-red-block stays a quick build)", not n(
        "@serf Two belts start here: iron plates at [gps=1,2] and copper plates at [gps=1,4], both running east, and "
        "there's a power pole at [gps=3,3]. Make red science from them automatically into a chest, 1 a minute."))


def test_question_marks_order():
    import asyncio
    from types import SimpleNamespace
    from jev.actor import Actor, Order
    o = Order(1, "@serf build PU", "boss", "plan", [])
    o.status = "working"
    said = []
    a = SimpleNamespace(current=o, project=None, log=lambda r: None, last_said=None,
                        g=SimpleNamespace(say=lambda t: asyncio.sleep(0, said.append(t))))
    asyncio.run(Actor.say(a, "acid plant has sulfur now. Want me to divert adv circuits to the PU build?"))
    asyncio.run(Actor.say(a, "on it"))
    check("question: a question while on an order is kept on it (c1 PU order)", o.asked and "divert" in o.asked, o.asked)


def test_project_stuck():
    import tempfile
    from types import SimpleNamespace
    from jev.project import Project
    with tempfile.TemporaryDirectory() as d:
        pr = SimpleNamespace(workdir=Path(d), STUCK_H=2.0)
        check("stuck: a new level says nothing", Project._stuck(pr, {"level": 7}) == "")
        (Path(d) / "level.json").write_text(json.dumps({"level": 7, "since": time.time() - 3 * 3600}))
        t = Project._stuck(pr, {"level": 7})
        check("stuck: 3 hours at one milestone gets the nudge", "milestone 7 for 3.0 hours" in t, t)
        check("stuck: a level change resets it", Project._stuck(pr, {"level": 8}) == ""
              and json.loads((Path(d) / "level.json").read_text())["level"] == 8)


def test_fluid_reaches():
    import asyncio
    from types import SimpleNamespace
    from jev.actor import Actor

    def actor(fin):
        ents = [{"u": 1, "n": "chemical-plant", "t": "assembling-machine", "x": 10.5, "y": 10.5, "w": 3, "h": 3,
                 "fin": fin}]
        async def world(c, r):
            return World({"ents": ents, "center": [10, 10]})
        return SimpleNamespace(world=world)
    chk = {"check": "fluid_reaches", "x": 10.5, "y": 10.5, "fluid": "petroleum-gas"}
    ok, msg = asyncio.run(Actor._check(actor([{"want": "petroleum-gas", "have": "petroleum-gas", "amt": 40}]), chk))
    check("fluid_reaches: petroleum at the plastic plant's inlet passes", ok, msg)
    ok, msg = asyncio.run(Actor._check(actor([{"want": "petroleum-gas", "have": None, "amt": 0}]), chk))
    check("fluid_reaches: an empty inlet fails and says so (p1's false 'done')", not ok and "no petroleum-gas" in msg,
          msg)
    ok, msg = asyncio.run(Actor._check(actor([{"want": "petroleum-gas", "amt": 0, "pipes": ["water"]}]), chk))
    check("fluid_reaches: ... and names what its pipes carry instead", not ok and "carry water" in msg, msg)


def test_ratios():
    from jev.ratios import solve, solve_oil, table
    plan = solve({"automation-science-pack": 60})
    st = {x["recipe"]: x for x in plan["steps"]}
    check("ratios: 60 red/min = 6.67 assembler-2s (5 s, speed 0.75)",
          abs(st["automation-science-pack"]["count"] - 6.667) < 0.01, st["automation-science-pack"])
    check("ratios: ... 120 iron plates/min = 3.2 steel furnaces", abs(st["iron-plate"]["count"] - 3.2) < 0.01
          and abs(plan["raw"]["iron-ore"] - 120) < 0.01, (st["iron-plate"], plan["raw"]))
    p2 = solve({"production-science-pack": 45})
    s2 = {x["recipe"]: x for x in p2["steps"]}
    check("ratios: 45 purple/min = 450 rails/min and 375 steel/min (rails + electric furnaces)",
          abs(s2["rail"]["per_min"] - 450) < 0.1 and abs(s2["steel-plate"]["per_min"] - 375) < 0.1,
          (s2["rail"], s2["steel-plate"]))
    o = solve_oil({"petroleum-gas": 55 * 12, "light-oil": 0, "heavy-oil": 0})
    check("ratios: petroleum only = refinery + full cracking (97.5 petroleum per refinery run)",
          abs(o["refineries"] - 55 * 12 / 97.5 * 5 / 60) < 1e-6 and o["heavy_crackers"] > 0 and o["light_crackers"] > 0, o)
    o = solve_oil({"heavy-oil": 600})
    check("ratios: lots of heavy oil leaves petroleum over, and says it needs a consumer",
          o["surplus"].get("petroleum-gas", 0) > 0, o)
    check("ratios: the table names machines, raw and drills", "6.67 exact" in table(plan) and "drills" in table(plan))


def test_keeper_state():
    import tempfile
    from types import SimpleNamespace
    from jev.actor import Actor
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "keepers.json"
        a = SimpleNamespace(state_path=p, fuelled=[(1.5, 2.5)], stocked=[{"at": [3, 4], "item": "coal"}],
                            watches=[{"at": (5.0, 6.0), "what": "mine"}], log=lambda r: None)
        Actor.save_state(a)
        b = SimpleNamespace(state_path=p, fuelled=[], stocked=[], watches=[], log=lambda r: None)
        b.save_state = lambda: Actor.save_state(b)
        Actor.load_state(b)
        check("keepers: lists survive a new session", b.fuelled == [(1.5, 2.5)] and b.stocked == a.stocked
              and b.watches[0]["at"] == (5.0, 6.0), (b.fuelled, b.stocked, b.watches))
        p.write_text("{not json")
        c = SimpleNamespace(state_path=p, fuelled=[], stocked=[], watches=[], logs=[])
        c.log, c.save_state = c.logs.append, lambda: None
        Actor.load_state(c)
        check("keepers: a corrupt file is logged, not fatal", c.fuelled == [] and c.logs and c.logs[0]["where"] ==
              "load_state", c.logs)
    f = SimpleNamespace(fuelled=[])
    for xy in [(1.0, 1.0), (1.4, 1.2)] + [(float(i * 3), 0.0) for i in range(1, 50)]:
        Actor._remember_fuelled(f, *xy)
    check("keepers: a burner within a tile is remembered once, at most 40", len(f.fuelled) == 40
          and sum(1 for x in f.fuelled if x == (1.0, 1.0)) <= 1, len(f.fuelled))


def test_project_obvious():
    from jev.project import OBVIOUS
    check("project: big goals are projects", all(OBVIOUS.search(t) for t in (
        "@serf project: beat the game", "launch a rocket", "can you take charge of the base", "build the whole factory",
        "run the base for me")))
    check("project: everyday orders aren't", not any(OBVIOUS.search(t) for t in (
        "build a red science block at [gps=1,2]", "launch the drills on the iron patch", "build the smelter",
        "fix the base's power")))


def test_campaign_targets():
    from types import SimpleNamespace
    sys.path.insert(0, str(ROOT / "bench"))
    sys.path.insert(0, str(ROOT / "scripts"))
    import campaign
    from jev import progress
    names = {lv: name for lv, name, _ in progress.MILESTONES}
    met = campaign.Campaign.target_met
    check("campaign: target 5 met by oil alone (no green science needed)",
          met(SimpleNamespace(target="5"), {"milestones": [names[5]]}))
    check("campaign: target '7,8' needs both", not met(SimpleNamespace(target="7,8"), {"milestones": [names[7]]})
          and met(SimpleNamespace(target="7,8"), {"milestones": [names[7], names[8], names[1]]}))
    grow = campaign.Campaign.target_growth(SimpleNamespace(target="3,5"),
                                           {"items": {"automation-science-pack": 100}, "fluids": {"petroleum-gas": 50}},
                                           {"items": {"automation-science-pack": 117}, "fluids": {"petroleum-gas": 140}})
    check("campaign: growth per target product (fluids for petroleum)",
          grow == {"automation-science-pack": 17, "petroleum-gas": 90}, grow)

    def sustained(more):  # the rule in the campaign's sustain check
        return all(v >= campaign.CONFIRM_NEED.get(k, campaign.CONFIRM_MIN) for k, v in more.items())
    check("campaign: 90 petroleum in 15 min isn't sustained (oil-r3)", not sustained({"petroleum-gas": 90}))
    check("campaign: 17 red packs in 15 min is", sustained({"automation-science-pack": 17}))


def test_lint_drill_outputs():
    w = World({"ents": [{"u": 1, "n": "iron-chest", "t": "container", "x": 10.5, "y": 2.5}], "center": [0, 0]})
    probs = lint([{"do": "place", "name": "electric-mining-drill", "x": 0.5, "y": 0.5, "direction": "north"}], w, None, {})
    check("lint: an electric drill dropping on nothing is flagged", any("drops its ore" in p for p in probs), probs)
    probs = lint([{"do": "place", "name": "electric-mining-drill", "x": 0.5, "y": 0.5, "direction": "north"},
                  {"do": "place", "name": "transport-belt", "x": 0.5, "y": -1.5, "direction": "east"}], w, None, {})
    check("lint: an electric drill dropping on a planned belt is fine", not any("drops its ore" in p for p in probs), probs)
    probs = lint([{"do": "place", "name": "electric-mining-drill", "x": 10.5, "y": 0.5, "direction": "south"}], w, None,
                 {})
    check("lint: a drill dropping into a chest already built is fine", not any("drops its ore" in p for p in probs),
          probs)
    probs = lint([{"do": "place", "name": "electric-mining-drill", "x": 20.5, "y": 0.5, "direction": "north"},
                  {"do": "connect", "item": "transport-belt", "from": [15, -1], "to": [30, -1]}], w, None, {})
    check("lint: a drill over a belt the plan routes later isn't flagged", not any("drops its ore" in p for p in probs),
          probs)



def _flow(ents: list[dict], start: tuple[float, float]):
    """Where items put on the belt at `start` can go through these entities: the tiles reached, and side-loads onto a
    belt that also has an input from behind (half a belt lost) or onto an underground entrance."""
    from jev.busgen import DIRS
    tiles = {}
    for e in ents:
        if e["name"] == "splitter":
            dx, dy = DIRS[e["direction"]]
            ax, ay = -dy, dx  # across
            for k in (-0.5, 0.5):
                tiles[(math.floor(e["x"] + ax * k), math.floor(e["y"] + ay * k))] = e
        else:
            tiles[(math.floor(e["x"]), math.floor(e["y"]))] = e
    feeders = {}  # tile -> tiles that push into it

    def ahead(t, e):
        dx, dy = DIRS[e["direction"]]
        if e["name"] == "underground-belt" and e.get("type") == "input":
            for k in range(1, 6):
                o = tiles.get((t[0] + dx * k, t[1] + dy * k))
                if o and o["name"] == "underground-belt" and o.get("type") == "output" and o["direction"] == e["direction"]:
                    return [(t[0] + dx * k, t[1] + dy * k)]
            return []
        return [(t[0] + dx, t[1] + dy)]
    for t, e in tiles.items():
        for n in ahead(t, e):
            feeders.setdefault(n, []).append(t)
    seen, todo, bad = set(), [(math.floor(start[0]), math.floor(start[1]))], []
    while todo:
        t = todo.pop()
        if t in seen or t not in tiles:
            continue
        seen.add(t)
        e = tiles[t]
        if e["name"] == "splitter":  # whichever side items come in, they leave by both
            todo += [k for k, v in tiles.items() if v is e and k not in seen]
        for n in ahead(t, e):
            if n not in tiles:
                seen.add(n)  # off the end (an exit tile)
                continue
            ne = tiles[n]
            dx, dy = DIRS[ne["direction"]]
            behind = (n[0] - dx, n[1] - dy)
            ug_jump = e["name"] == "underground-belt" and e.get("type") == "input"
            if ne["name"] == "underground-belt" and ne.get("type") == "input" and t != behind:
                bad.append(f"side-load into underground at {n}")
            elif ne["name"] == "transport-belt" and t != behind and not ug_jump and behind in feeders.get(n, []):
                bad.append(f"side-load onto a fed belt at {n}")
            todo.append(n)
    return seen, bad


def test_bus():
    from jev.busgen import Bus
    for d, side in (("south", "east"), ("east", "north"), ("north", "west"), ("west", "south"), ("south", "west")):
        b = Bus(name="t", x=10.5, y=-4.5, direction=d, side=side, lanes=["a", "b", "c", "d", "spare"], length=40)
        lanes = b.lay()
        lane_tiles = {i: {(math.floor(x), math.floor(y)) for x, y in (b.at(k, b.u(i)) for k in range(b.length))}
                      for i in range(5)}
        ok_all, why = True, []
        for i in range(4):
            a = 6 + 5 * i
            tap, ex, mine = b.tap(i, a)
            mt = (math.floor(mine[0][0]), math.floor(mine[0][1]))
            rest = [e for e in lanes if (math.floor(e["x"]), math.floor(e["y"])) != mt]
            seen, bad = _flow(rest + tap, b.at(0, b.u(i)))
            exit_t = (math.floor(ex["x"]), math.floor(ex["y"]))
            end_t = tuple(math.floor(v) for v in b.at(b.length - 1, b.u(i)))
            others = set().union(*(lane_tiles[j] for j in range(5) if j != i))
            occupied = {}
            for e in rest + tap:
                k = (math.floor(e["x"]), math.floor(e["y"]))
                if e["name"] != "splitter":
                    occupied[k] = occupied.get(k, 0) + 1
            if exit_t not in seen or end_t not in seen or seen & others or bad or any(v > 1 for v in occupied.values()):
                ok_all = False
                why.append((d, side, i, exit_t in seen, end_t in seen, len(seen & others), bad[:2]))
            m_ents, entry = b.merge(4, a + 2) if i == 0 else b.merge(i, a + 2)
        check(f"bus {d}/{side}: a tap on every lane carries that lane (all of it, no side-loads) past the bus edge, "
              "and the lane runs on", ok_all, why)
        # merges: a spare lane started from the side, and an east and a west lane side-loaded
        okm, whym = True, []
        for i in (4, 1, 2):
            a = 20
            m_ents, entry = b.merge(i, a)
            lane = [] if i == 4 else [e for e in lanes if b.along_of(e["x"], e["y"]) > a and
                                      (math.floor(e["x"]), math.floor(e["y"])) in lane_tiles[i]]
            if i == 4:
                lane = [{"name": "transport-belt", "x": x, "y": y, "direction": d}
                        for x, y in (b.at(k, b.u(4)) for k in range(a + 1, b.length))]
            seen, bad = _flow(m_ents + lane, (entry["x"], entry["y"]))
            end_t = tuple(math.floor(v) for v in b.at(b.length - 1, b.u(i)))
            others = set().union(*(lane_tiles[j] for j in range(5) if j != i))
            if end_t not in seen or seen & others or (i == 4 and bad):
                okm = False
                whym.append((i, end_t in seen, len(seen & others), bad[:2]))
        check(f"bus {d}/{side}: merges reach their lane (a spare lane fully, no side-load) and no other", okm, whym)
    b = Bus(name="t", x=0.5, y=0.5, direction="south", side="east", lanes=["a", "b"], length=30)
    b.joins.append({"kind": "tap", "lane": 0, "at": 10, "end": [0, 0]})
    check("bus: rows within 4 of another join are refused, others free",
          b.rows_free(12) is not None and b.rows_free(14) is None and b.rows_free(28) is not None)
    fb = Bus(name="f", x=0.5, y=0.5, direction="south", side="east", lanes=["iron-plate", "copper-plate", "coal",
                                                                            "stone", "spare"], length=40)
    rows = [a for i, a, _ in fb.sample_tiles() if i == 0]
    samples = [(0, a, 8) for a in rows] + [(1, a, 8 if a < 20 else 0) for a in rows] + [(2, a, 0) for a in rows] + \
        [(3, a, 3) for a in rows]
    words = fb.flow_words(samples)
    check("bus flow: a lane nothing taps that stops at row 16 is still filling, not used up",
          "filling, items reach row 16" in words[1], words[1])
    fb.joins.append({"kind": "tap", "lane": 1, "at": 8, "end": [0, 0]})
    words = fb.flow_words(samples)
    check("bus flow: backed up / used up by row / empty / flowing, one line per lane in use",
          len(words) == 4 and "backed up to the end" in words[0] and "used up by row 16" in words[1] and
          "empty" in words[2] and "flowing, 3/8" in words[3], words)
    d = Bus.from_dict(json.loads(json.dumps(b.to_dict())))
    check("bus: round-trips through json (the game's layout store)", d.to_dict() == b.to_dict() and "lanes: 0 a" in
          d.describe())



def test_research_keeper():
    import asyncio
    from types import SimpleNamespace
    from jev.project import Project

    class G:
        name = "serf"

        def __init__(self, researching):
            self.researching, self.queued = researching, []

        async def call(self, op, **kw):
            if op == "progress":
                return {"research": self.researching, "ents": {"lab": 4}, "items": {}, "fluids": {},
                        "by_recipe": {"automation-science-pack": 2, "logistic-science-pack": 1}, "techs": 20}
            if op == "techs":
                return {"available": [
                    {"name": "toward-goal", "units": 900, "packs": ["automation-science-pack", "logistic-science-pack"],
                     "toward": True},
                    {"name": "chemical-thing", "units": 10, "packs": ["automation-science-pack", "chemical-science-pack"]},
                    {"name": "big-green", "units": 300, "packs": ["automation-science-pack", "logistic-science-pack"]},
                    {"name": "small-green", "units": 50, "packs": ["automation-science-pack", "logistic-science-pack"]},
                    {"name": "trigger-tech", "units": 0, "packs": []}]}
            if op == "research":
                self.queued.append(kw["tech"])
                return {"ok": True, "msg": "queued"}
            raise AssertionError(op)

    async def go(g):
        pr = SimpleNamespace(actor=SimpleNamespace(g=g), active=True, RESEARCH_EVERY=0, kept_research=[], logs=[],
                             toward="rocket-silo")
        pr._log = pr.logs.append

        async def sleep(secs):
            if pr.logs or len(g.queued) or getattr(pr, "_n", 0) > 2:
                pr.active = False
            pr._n = getattr(pr, "_n", 0) + 1
        pr._sleep = sleep
        await Project._keep_research(pr)
        return pr
    g = G(None)
    pr = asyncio.run(go(g))
    check("research keeper: idle labs get a tech toward the goal the base's packs pay for, before cheaper filler",
          g.queued == ["toward-goal"] and pr.kept_research == ["toward-goal"], (g.queued, pr.logs))
    g = G("automation")
    asyncio.run(go(g))
    check("research keeper: leaves a running research it can pay for alone", g.queued == [], g.queued)
    g = G("chemical-thing")
    asyncio.run(go(g))
    check("research keeper: puts a payable tech ahead of one needing packs the base doesn't make",
          g.queued == ["toward-goal"], g.queued)



def test_row_extends_short_belt():
    from jev.rowgen import extend_input
    w = World({"ents": [belt(1, 0.5, 0.5, "east", items={"iron-plate": 2}), belt(2, 1.5, 0.5, "east")],
               "center": [0, 0]})
    probs = lint([{"do": "row", "belt": [0.5, 0.5], "machine": "assembling-machine-1", "recipe": "iron-gear-wheel",
                   "count": 3, "side": "south"}], w, None, {})
    check("row: a 2-tile belt under a 3-machine row isn't flagged (the row carries its belt on)",
          not any("nothing" in p for p in probs), probs)
    ext = extend_input((0.5, 0.5), "east", 15, w.at)
    check("row: the extension starts past the existing belt and covers the row",
          ext and ext[0]["x"] == 2.5 and ext[-1]["x"] == 14.5 and all(e["direction"] == "east" for e in ext), ext[:2])
    w2 = World({"ents": [belt(1, 0.5, 0.5, "east"), {"u": 3, "n": "iron-chest", "t": "container", "x": 6.5, "y": 0.5}],
                "center": [0, 0]})
    ext = extend_input((0.5, 0.5), "east", 15, w2.at)
    check("row: the extension stops at the first thing in the way", [e["x"] for e in ext] == [1.5, 2.5, 3.5, 4.5, 5.5],
          [e["x"] for e in ext])
    w3 = World({"ents": [], "center": [0, 0]})
    plan = [{"do": "merge_lanes", "left": [61.5, -43.5], "right": [61.5, -39.5], "at": [64.5, -41.5],
             "direction": "south", "to": [64.5, -26.5]},
            {"do": "row", "belt": [64.5, -36.5], "machine": "stone-furnace", "recipe": "steel-plate", "count": 5,
             "side": "west", "output": "belt"}]
    probs = lint(plan, w3, None, {})
    check("lint: a row along the belt a merge_lanes step lays earlier in the plan isn't flagged (b3)", probs == [], probs)



def test_belt_end_targets():
    from jev.steps import belt_end_targets
    w = World({"ents": [belt(1, 0.5, 0.5, "east"), belt(2, 1.5, 0.5, "east"),
                        belt(3, 5.5, 5.5, "south"), belt(4, 5.5, 6.5, "south")], "center": [0, 0]})
    t = belt_end_targets(w)
    check("route: the free tile in front of each open belt end is kept clear, and only those",
          t == {(2, 0), (5, 7)}, t)
    t2 = belt_end_targets(w, {(1, 0)})
    check("route: ... except where the belt is a line's own source (an endpoint)", t2 == {(5, 7)}, t2)



def test_lessons_route_tool_complaints():
    import os
    import tempfile
    from jev import library
    with tempfile.TemporaryDirectory() as d:
        old = os.environ.get("JEV_LIBRARY")
        os.environ["JEV_LIBRARY"] = d
        try:
            r1 = library.save_lesson("If the tap and bus_in ops crash (TypeError), stop using them and hand-lay "
                                     "splitters instead.")
            r2 = library.save_lesson("Fuel for a furnace column: ore on one lane, coal on the other lane.")
            check("lessons: a rule to avoid a harness op goes to the maintainers, not the planners' rules",
                  r1.startswith("not saved") and (Path(d) / "tool_complaints.jsonl").exists()
                  and library.lessons() == ["Fuel for a furnace column: ore on one lane, coal on the other lane."],
                  (r1, library.lessons()))
            check("lessons: a game rule is saved", r2 == "saved")
        finally:
            if old is None:
                os.environ.pop("JEV_LIBRARY", None)
            else:
                os.environ["JEV_LIBRARY"] = old



def test_step_refs():
    from jev.steps import resolve_refs, step_end
    st, miss = resolve_refs({"do": "row", "belt": "end:2", "count": 3}, {2: [10.5, 4.5]})
    check("refs: end:N becomes the tile step N reported", st["belt"] == [10.5, 4.5] and not miss, st)
    st, miss = resolve_refs({"do": "connect", "from": "end:1", "to": [1, 2]}, {})
    check("refs: an end not reported yet is named as missing", miss == [1] and st["from"] == "end:1", (st, miss))
    check("refs: tap and row report their ends", step_end({"end": [1.5, 2.5]}) == [1.5, 2.5] and
          step_end({"info": {"output_belt_end": [3.5, 4.5]}}) == [3.5, 4.5] and step_end({"msg": "x"}) is None)
    w = World({"ents": [], "center": [0, 0]})
    probs = lint([{"do": "row", "belt": "end:1", "machine": "assembling-machine-2", "recipe": "iron-gear-wheel",
                   "count": 2}], w, None, {})
    check("refs: lint passes over a step that uses a run-time end", not any("malformed" in p for p in probs), probs)
    from jev.lint import plan_points
    plan = [{"do": "tap", "bus": "main", "lane": "iron-plate", "at": 4},
            {"do": "connect", "item": "transport-belt", "from": "end:1", "to": [30.5, 4.5]},
            {"do": "connect", "item": "pipe", "from": [1, 1], "to": "end:1", "to_fluid": "water"},
            {"do": "row", "belt": "end:1", "machine": "assembling-machine-2", "count": 2},
            {"do": "merge_lanes", "left": "end:1", "right": [2.5, 2.5], "at": "end:1", "direction": "east"}]
    try:
        plan_points(plan), plan_needs(plan), lint(plan, w, None, {})
        ok_ = True
    except Exception as e:  # noqa: BLE001
        ok_ = repr(e)
    check("refs: plan points, items needed and lint take a plan full of end:N references", ok_ is True, ok_)



def test_underground_pair_off_view():
    ug = {"u": 5, "n": "underground-belt", "t": "underground-belt", "x": 9.5, "y": 0.5, "d": "west", "ug": "input",
          "pair": 99}
    w = World({"ents": [belt(4, 10.5, 0.5, "west"), ug], "center": [12, 0], "radius": 3})
    reasons = [ln.end_reason for ln in w.lines]
    check("world: an underground entrance whose exit is outside the view isn't called broken",
          any("past the edge" in r for r in reasons) and not any("no exit" in r for r in reasons), reasons)
    ug2 = dict(ug)
    ug2.pop("pair")
    w2 = World({"ents": [belt(4, 10.5, 0.5, "west"), ug2], "center": [12, 0], "radius": 3})
    check("world: ... one with no partner at all still is", any("no exit" in ln.end_reason for ln in w2.lines),
          [ln.end_reason for ln in w2.lines])



def test_audit_ore_words():
    from jev import audit as A
    a = {"machines": 10, "status": {"working": 6, "no_minable_resources": 4}, "groups": {}, "labs": 0,
         "ore_left": [{"ore": "iron-ore", "at": [1, 2], "drills": 8, "amount": 30000, "rate": 480, "minutes": 62},
                      {"ore": "coal", "at": [5, 6], "drills": 4, "amount": 200000, "rate": 120, "minutes": 1666}]}
    w = A.words(a)
    check("audit words: ore that runs out within 2 h is called out, and drills on mined-out ground",
          "open new mines before a patch runs dry" in w and "iron-ore at [gps=1,2]: 30k under 8 drills, ~62 min" in w
          and "4 drills stand on mined-out ground" in w, w)



def test_fluid_break_words():
    from jev import audit as A
    crude = {"machine": {"n": "oil-refinery", "p": [10.5, 20.5], "status": "fluid_ingredient_shortage"},
             "why": "missing", "fluid": "crude-oil",
             "line": {"pipes": 12, "fill": 0, "sources": {}, "users": {}, "port": {"index": 2, "kind": "input"},
                      "ends": [{"at": [10.5, 8.5], "n": "pipe", "kind": "pipe end", "toward": "north",
                                "further": {"n": "pipe", "p": [10.5, 6.5], "gap": 1, "fluid": "water"}}],
                      "ends_total": 1}}
    jacks = {"machine": {"n": "pumpjack", "p": [300.5, 40.5], "status": "waiting_for_space_in_destination"},
             "why": "full", "fluid": "crude-oil",
             "line": {"pipes": 640, "fluid": "crude-oil", "fill": 97,
                      "sources": [{"n": "pumpjack", "p": [300.5, 40.5]}, {"n": "pumpjack", "p": [304.5, 40.5]}],
                      "users": {}, "port": {"index": 1, "kind": "output"}, "ends_total": 1,
                      "ends": [{"at": [12.5, 9.5], "n": "pipe-to-ground", "kind": "underground, no exit",
                                "toward": "west", "further": {"n": "pipe-to-ground", "p": [8.5, 9.5], "gap": 3,
                                                              "dir": "east"}}]}}
    w = A.words({"machines": 3, "groups": {}, "fluid_breaks": [crude, jacks]})
    check("audit words: a crude line stopping at a gap to a water pipe says joining them would mix fluids; full "
          "pumpjacks whose line goes underground with no exit say which way the next one faces",
          "oil-refinery at [gps=10.5,20.5] lacks crude-oil" in w and "joining them would mix fluids" in w
          and "no machine takes from it" in w and "facing east (an exit for this one faces west)" in w
          and "the line into it is 12 pipes dry" in w and "no pump, pumpjack or machine output" in w
          and w.count("no machine takes from it") == 1, w)


def test_lint_unfed_belt_start():
    from jev.lint import lint
    ents = [belt(k + 1, 0.5, k + 0.5, "south", i=[k] if k else None, o=[k + 2] if k < 9 else None,
                 items={"iron-plate": 4}) for k in range(10)]
    w = World({"ents": ents, "center": [0, 5], "radius": 20})
    flagged = lambda steps: any("nothing feeds that tile" in m for m in lint(steps, w))  # noqa: E731
    beside = flagged([{"do": "route", "pairs": [{"name": "transport-belt", "from": [1.5, 4.5], "to": [12.5, 4.5]}]}])
    end = flagged([{"do": "connect", "item": "transport-belt", "from": [0.5, 10.5], "to": [8.5, 14.5]}])
    ins = flagged([{"do": "connect", "item": "transport-belt", "from": [2.5, 6.5], "to": [9.5, 6.5]},
                   {"do": "place", "name": "inserter", "x": 1.5, "y": 6.5, "direction": "west"}])
    ref = flagged([{"do": "tap", "bus": "main", "lane": 0, "at": 3},
                   {"do": "connect", "item": "transport-belt", "from": "end:1", "to": [9.5, 2.5]}])
    chain = flagged([{"do": "route", "pairs": [{"name": "transport-belt", "from": [0.5, 10.5], "to": [6.5, 10.5]}]},
                     {"do": "route", "pairs": [{"name": "transport-belt", "from": [7.5, 10.5], "to": [12.5, 10.5]}]}])
    check("lint: a belt routed from beside a bus lane is flagged as unfed (p8's empty sub-bus); one from a lane's "
          "end, an inserter's drop, a tap's end or an earlier line's end isn't",
          beside and not end and not ins and not ref and not chain, (beside, end, ins, ref, chain))


def test_audit_fix_first():
    from jev import audit as A
    a = {"machines": 120, "status": {"no_minable_resources": 26}, "labs": 12,
         "groups": {"iron-plate": {"n": 66, "working": 10, "starved": 42, "blocked": 14},
                    "mining iron-ore": {"n": 24, "working": 5, "blocked": 19, "at": [211.5, 218.5]},
                    "copper-plate": {"n": 36, "working": 12, "starved": 0, "blocked": 24}}}
    w = A.words(a)
    b = A.words({**a, "groups": {**a["groups"], "mining iron-ore": {"n": 24, "working": 24, "blocked": 0}}})
    check("audit words: furnaces starving while their drills sit blocked come first as a broken ore line; with the "
          "drills fine, as a mine to open; copper (not starved) isn't named",
          "Fix first: 42 of 66 iron-plate furnaces have no iron-ore while 19 iron-ore drills are blocked" in w
          and "ore isn't reaching the furnaces" in w and "open a new iron-ore mine" in b and "26 drills" in b
          and "copper-plate furnaces" not in w, (w[:400], b[:300]))


def test_bus_feed_entries():
    from jev.busgen import DIRS, Bus
    ok_all, why = True, []
    for d, side in (("south", "east"), ("east", "north"), ("north", "west"), ("west", "south")):
        b = Bus(name="t", x=0.5, y=0.5, direction=d, side=side, lanes=["a", "b", "c", "d", "e"], length=20)
        lanes = b.lay()
        lane_tiles = {i: {(math.floor(x), math.floor(y)) for x, y in (b.at(k, b.u(i)) for k in range(b.length))}
                      for i in range(5)}
        entries = set()
        for i in range(5):
            (ex, ey), face = b.feed_entry(i)
            gu = b.u(i) + (-1 if i % 2 == 0 else 1)
            supply = [{"name": "transport-belt", "x": x, "y": y, "direction": d} for x, y in (b.at(-2, gu), b.at(-1, gu))]
            supply.append({"name": "transport-belt", "x": ex, "y": ey, "direction": face})
            seen, bad = _flow(lanes + supply, b.at(-2, gu))
            end_t = tuple(math.floor(v) for v in b.at(b.length - 1, b.u(i)))
            others = set().union(*(lane_tiles[j] for j in range(5) if j != i))
            entries.add((math.floor(ex), math.floor(ey)))
            if end_t not in seen or seen & others or bad:
                ok_all = False
                why.append((d, side, i, end_t in seen, len(seen & others), bad[:2]))
        if len(entries) != 5:
            ok_all = False
            why.append((d, side, "entries shared", sorted(entries)))
    check("bus feed: each lane's feed turns into its first tile from its own side column and runs the lane, alone",
          ok_all, why)



def test_summary_line_end_pieces():
    ug = {"u": 5, "n": "underground-belt", "t": "underground-belt", "x": 12.5, "y": 0.5, "d": "east", "ug": "output"}
    w = World({"ents": [ug, belt(6, 13.5, 0.5, "east"), belt(7, 14.5, 0.5, "east")], "center": [13, 0]})
    lines = w.summary()["belt_lines"]
    check("summary: a belt line starting at an underground exit says so", any(
        l.get("first_piece") == "underground-belt (exit)" for l in lines), lines)



def test_bus_opposite_taps():
    from jev.busgen import Bus
    ok_all, why = True, []
    for d, side in (("south", "east"), ("east", "north"), ("west", "south")):
        b = Bus(name="t", x=10.5, y=-4.5, direction=d, side=side, lanes=["a", "b", "c", "d", "e"], length=40)
        mb = b.mirrored()
        lanes = b.lay()
        lane_tiles = {i: {(math.floor(x), math.floor(y)) for x, y in (b.at(k, b.u(i)) for k in range(b.length))}
                      for i in range(5)}
        for i in range(5):
            a = 6 + 6 * i
            tap, ex, mine = mb.tap(2 * b.pairs - 1 - i, a)
            mt = (math.floor(mine[0][0]), math.floor(mine[0][1]))
            if mt not in lane_tiles[i]:
                ok_all = False
                why.append((d, side, i, "splitter not on lane", mt))
                continue
            rest = [e for e in lanes if (math.floor(e["x"]), math.floor(e["y"])) != mt]
            seen, bad = _flow(rest + tap, b.at(0, b.u(i)))
            exit_t = (math.floor(ex["x"]), math.floor(ex["y"]))
            end_t = tuple(math.floor(v) for v in b.at(b.length - 1, b.u(i)))
            others = set().union(*(lane_tiles[j] for j in range(5) if j != i))
            # the exit lies past the bus on the side opposite `side`
            nx, ny = {"north": (0, -1), "east": (1, 0), "south": (0, 1), "west": (-1, 0)}[side]
            beyond = (exit_t[0] - math.floor(b.x)) * nx + (exit_t[1] - math.floor(b.y)) * ny < -1
            if exit_t not in seen or end_t not in seen or seen & others or bad or not beyond:
                ok_all = False
                why.append((d, side, i, exit_t in seen, end_t in seen, len(seen & others), bad[:1], beyond))
    check("bus: a tap with side=opposite carries its lane out past the far side, every lane, no mixing", ok_all, why)



def test_lint_bus_steps_both_sides():
    import asyncio
    from types import SimpleNamespace
    from jev.actor import Actor
    from jev.busgen import Bus
    b = Bus(name="main", x=0.5, y=0.5, direction="south", side="east", lanes=["a", "b", "c", "d"], length=30)

    async def buses():
        return {"main": b}
    runner = SimpleNamespace(buses=buses, _bus_row=lambda bb, at: int(at))
    fake = SimpleNamespace(runner=runner)
    steps = [{"do": "tap", "bus": "main", "lane": "b", "at": 6},
             {"do": "tap", "bus": "main", "lane": "c", "at": 12, "side": "opposite"},
             {"do": "row", "belt": "end:2", "machine": "assembling-machine-2", "count": 1}]
    out = asyncio.run(Actor._bus_steps_as_ghosts(fake, steps))
    east = max(e["x"] for e in out[0]["entities"])
    west = min(e["x"] for e in out[1]["entities"])
    check("lint view: taps become their entities on the right side, and end:2 gets the opposite tap's end",
          out[0]["do"] == "ghosts" and out[1]["do"] == "ghosts" and east > 7 and west < -1
          and isinstance(out[2]["belt"], list) and out[2]["belt"][0] < -1, (east, west, out[2].get("belt")))


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print(f"\n{'ALL OK' if not FAILS else str(len(FAILS)) + ' FAILED: ' + ', '.join(FAILS)}")
    sys.exit(1 if FAILS else 0)
