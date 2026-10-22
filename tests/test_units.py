#!/usr/bin/env python3
"""Offline unit tests (no game, no network): router, row layouts, compact layout notation, plan checker rules, world
model belt lines and faults, failure facts.  Run: .venv/bin/python tests/test_units.py"""
import math
import sys
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
