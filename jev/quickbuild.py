"""Quick builds without the planner: a row of machines making one product off belts that are already there, the most
common build order ("make gears off this belt into a chest", "4 furnaces making steel off that belt").

Jev reads the order (is it that kind of job, which product, how many, where the output goes); code finds the belt
lines that carry the ingredients and lays out the tested row step (jev/rowgen.py), checks the layout is free, and
the usual plan runner builds and verifies it. Anything else, or any doubt, goes to the planner as before."""
from __future__ import annotations

from .rowgen import DIRS
from .typesafe import Jev, choice, noul
from .world import World

ASSEMBLER_CATS = {"crafting", "basic-crafting", "advanced-crafting", "electronics", "pressing"}
SMELT = {"iron-ore": "iron-plate", "copper-ore": "copper-plate", "stone": "stone-brick", "iron-plate": "steel-plate"}
FUELS = ("coal", "wood", "solid-fuel")
GAP = {"assembling-machine-1": 6, "stone-furnace": 5}  # where a second input belt has to run (machine size + 3)
DEFAULT_COUNT = {"assembling-machine-1": 2, "stone-furnace": 4}
# how products are said in chat
SAY = {"iron-gear-wheel": "gears", "steel-plate": "steel", "iron-plate": "iron plates", "copper-plate": "copper plates",
       "copper-cable": "copper cable", "electronic-circuit": "green circuits", "firearm-magazine": "ammo",
       "stone-brick": "bricks", "transport-belt": "belts", "inserter": "inserters", "pipe": "pipes",
       "iron-chest": "iron chests", "iron-stick": "iron sticks", "automation-science-pack": "red science",
       "logistic-science-pack": "green science"}


def _tiles(w: World, ln) -> list[tuple[float, float]]:
    return [(w.ents[u]["x"], w.ents[u]["y"]) for u in ln.belts if u in w.ents]


def _along(d: str, p) -> float:
    return DIRS[d][0] * p[0] + DIRS[d][1] * p[1]


def _across(d: str, p) -> float:
    return DIRS[d][1] * p[0] - DIRS[d][0] * p[1]


def _straight(w: World, ln) -> bool:
    ts = _tiles(w, ln)
    return ln.direction in DIRS and len(ts) >= 4 and len({round(_across(ln.direction, t), 1) for t in ts}) == 1


def _pair(w: World, a, b, gap: int) -> bool:
    """b runs parallel to a, `gap` tiles across, alongside it."""
    if not (_straight(w, a) and _straight(w, b)) or a.direction != b.direction:
        return False
    d = a.direction
    ta, tb = _tiles(w, a), _tiles(w, b)
    if abs(abs(_across(d, ta[0]) - _across(d, tb[0])) - gap) > 0.01:
        return False
    lo = max(min(_along(d, t) for t in ta), min(_along(d, t) for t in tb))
    hi = min(max(_along(d, t) for t in ta), max(_along(d, t) for t in tb))
    return hi - lo >= 6


def carried(w: World, points: list) -> list[str]:
    """Items on the belt lines near the order's points."""
    out: set = set()
    for ln in w.lines:
        if ln.items and any(min(abs(t[0] - p[0]) + abs(t[1] - p[1]) for t in _tiles(w, ln)) <= 12 for p in points):
            out |= set(ln.items)
    return sorted(out)


def options(w: World, recipes: dict, points: list) -> dict:
    """{product: {"machine", "lines", "ingredients"}} for each product a row off the straight belt lines near the
    order's points could make: lines that carry all its ingredients (one line, or two parallel at row spacing)."""
    near = [ln for ln in w.lines if ln.items and _straight(w, ln)
            and any(min(abs(t[0] - p[0]) + abs(t[1] - p[1]) for t in _tiles(w, ln)) <= 12 for p in points)]
    out: dict = {}
    for ln in near:
        items = set(ln.items)
        if any(f in items for f in FUELS):
            for ore, plate in SMELT.items():
                if ore in items and plate not in out:
                    out[plate] = {"machine": "stone-furnace", "lines": [ln], "ingredients": [ore]}
    for name, r in sorted(recipes.items()):
        ings = set(r.get("ingredients") or {})
        if (r.get("category") or "crafting") not in ASSEMBLER_CATS or not ings or name in out:
            continue
        for ln in near:
            if ings <= set(ln.items):
                out[name] = {"machine": "assembling-machine-1", "lines": [ln], "ingredients": sorted(ings)}
                break
            other = next((b for b in near if b is not ln and ings <= set(ln.items) | set(b.items)
                          and not ings <= set(b.items) and _pair(w, ln, b, GAP["assembling-machine-1"])), None)
            if other:
                out[name] = {"machine": "assembling-machine-1", "lines": [ln, other], "ingredients": sorted(ings)}
                break
    # two-stage: one ingredient on a belt, the other made by feeder assemblers from a parallel belt 6 tiles away,
    # dropped onto the first belt's free lane (red science: copper on its belt, gears made from the iron belt)
    on_belts = set().union(*[set(ln.items) for ln in near]) if near else set()
    for name, r in sorted(recipes.items()):
        ings = set(r.get("ingredients") or {})
        if (r.get("category") or "crafting") not in ASSEMBLER_CATS or len(ings) != 2 or name in out:
            continue
        for l1 in near:
            have = ings & set(l1.items)
            if len(have) != 1:
                continue
            made = (ings - have).pop()
            rb = recipes.get(made)
            if made in on_belts or not rb or (rb.get("category") or "crafting") not in ASSEMBLER_CATS:
                continue
            for l2 in near:
                if l2 is l1 or not _pair(w, l1, l2, GAP["assembling-machine-1"]):
                    continue
                if not set(rb.get("ingredients") or {}) <= set(l2.items):
                    continue
                d = l1.direction
                left = _across(d, _tiles(w, l2)[0]) - _across(d, _tiles(w, l1)[0]) > 0
                if lane_items(w, l1)[1 if left else 0]:
                    continue  # the lane the feeders would drop onto is taken
                out[name] = {"machine": "assembling-machine-1", "lines": [l1], "ingredients": sorted(ings),
                             "feeder": {"recipe": made, "line": l2, "left": left}}
                break
            if name in out:
                break
    return out


def lane_items(w: World, ln) -> list[set]:
    """Items on the line's left lane (index 0, relative to the way it runs) and right lane (1)."""
    lanes = [set(), set()]
    for u in ln.belts:
        for i, lane in enumerate((w.ents.get(u) or {}).get("lanes") or []):
            lanes[i] |= set(lane or {})
    return lanes


LEFT_OF = {"east": "north", "north": "west", "west": "south", "south": "east"}


def feeders_needed(recipes: dict, product: str, made: str, n: int) -> int:
    """Feeder assemblers to keep n main machines supplied (same machine speed, so recipe times compare)."""
    r, rb = recipes.get(product) or {}, recipes.get(made) or {}
    use = (r.get("ingredients") or {}).get(made, 1) / max(float(r.get("time") or 1), 0.1)
    make = float(rb.get("makes") or 1) / max(float(rb.get("time") or 1), 0.1)
    return max(1, -(-int(round(n * use * 1000)) // int(round(make * 1000))))


def feeder_layout(w: World, opt: dict, k: int, skip: int = 2) -> tuple[list[dict], tuple]:
    """k feeder assemblers between the main belt and the feeder belt, starting `skip` tiles into the main belt: input
    inserter from the feeder belt, output inserter onto the main belt's far lane, a pole between neighbours.
    Returns the entities and the centre of the feeders."""
    l1, fd = opt["lines"][0], opt["feeder"]
    d = l1.direction
    dx, dy = DIRS[d]
    side = LEFT_OF[d] if fd["left"] else {v: k_ for k_, v in LEFT_OF.items()}[d]
    nx, ny = DIRS[side]
    t = _tiles(w, l1)
    start = min(_along(d, q) for q in t)
    ents = []
    pts = []
    for i in range(k):
        a = start + skip + 4 * i
        tile = min(t, key=lambda q: abs(_along(d, q) - a))

        def at(along, across):
            return tile[0] + dx * along + nx * across, tile[1] + dy * along + ny * across
        mx, my = at(1, 3)
        ents.append({"name": "assembling-machine-1", "x": mx, "y": my, "recipe": fd["recipe"]})
        ix, iy = at(1, 5)
        ents.append({"name": "inserter", "x": ix, "y": iy, "direction": side})  # picks from the feeder belt side
        ox, oy = at(1, 1)
        ents.append({"name": "inserter", "x": ox, "y": oy, "direction": side})  # picks from the machine side
        px, py = at(3, 1)
        ents.append({"name": "small-electric-pole", "x": px, "y": py})
        pts.append((mx, my))
    c = (sum(q[0] for q in pts) / len(pts), sum(q[1] for q in pts) / len(pts))
    return ents, c


def row_step(w: World, opt: dict, product: str, count: int, skip: int = 2) -> dict:
    """The row step for that option: it starts `skip` tiles into the line (into both lines, for two), machines on
    the side of the second line if there is one (else whichever side is free)."""
    a = opt["lines"][0]
    d = a.direction
    ta = _tiles(w, a)
    start = min(_along(d, t) for t in ta)
    step = {"do": "row", "machine": opt["machine"], "count": count, "output": "chest"}
    if opt["machine"] != "stone-furnace":
        step["recipe"] = product
    if len(opt["lines"]) == 2:
        b = opt["lines"][1]
        tb = _tiles(w, b)
        start = max(start, min(_along(d, t) for t in tb))
        step["second_belt"] = True
        off = _across(d, tb[0]) - _across(d, ta[0])  # + is to the left of the direction of travel
        left = {"east": "north", "north": "west", "west": "south", "south": "east"}[d]
        right = {"east": "south", "north": "east", "west": "north", "south": "west"}[d]
        step["side"] = left if off > 0 else right
    tile = min(ta, key=lambda t: abs(_along(d, t) - (start + skip)))
    step["belt"] = [tile[0], tile[1]]
    return step


PRODUCT_Q = "Which of these does `order` ask to have made?"
COUNTS = {"not_said": "the order doesn't say how many machines", **{str(n): f"{n} machine(s)" for n in range(1, 13)}}


def plain_counts(order: str) -> str:
    """'a couple of machines' -> '2 machines', 'a few' -> '3': Jev read 'a couple' as several products."""
    import re
    order = re.sub(r"\ba couple(?: of)?\b", "2", order, flags=re.I)
    order = re.sub(r"\ba few\b", "3", order, flags=re.I)
    return order


async def read_order(jev: Jev, order: str, products: list[str], carried: list[str] | None = None) -> dict:
    alias = {"iron-gear-wheel": "gears", "steel-plate": "steel", "firearm-magazine": "yellow ammo",
             "electronic-circuit": "green circuits", "automation-science-pack": "red science",
             "iron-plate": "plates: furnaces smelting iron ore", "copper-plate": "plates: furnaces smelting copper ore",
             "stone-brick": "bricks: furnaces smelting stone", "steel-plate": "steel: furnaces on iron plates"}
    opts = {p: p.replace("-", " ") + (f" ({alias[p]})" if p in alias else "") for p in products[:200]}
    opts["none_of_these"] = "something not in this list, or two or more different products"
    state = {"order": plain_counts(order)}
    if carried:
        state["the_belts_there_carry"] = carried
    a = await jev.ask(state, {
        "build": noul("Does `order` ask for something to be made (produced automatically) from what a belt carries, "
                      "even if it doesn't say 'build' or name the machines?",
                      "yes: 'make gears off this belt', 'build 6 furnaces off the ore belt', 'set up an assembler "
                      "making inserters', 'pipes off the iron belt please', 'copper cable please, off the copper "
                      "belt'",
                      "no: moving or belting items that already exist from one place to another, fixing or "
                      "refuelling, power, putting drills on ore, research, a question"),
        "several": noul("Does `order` ask for two or more different products?",
                        "yes: 'make gears and pipes', 'iron chests and pipes off the belt'",
                        "no: one product, even if something has to be made for it first (red science, green "
                        "circuits)"),
        "onward": noul("Does `order` ask for the product to feed further new machines that make something else from "
                       "it?",
                       "yes: 'gear production feeding a row of red science assemblers', 'a science line with gears "
                       "from the iron belt into the science assemblers'",
                       "no: the product goes into chests or onto a belt; 'automate red science off these belts'"),
        "elsewhere": noul("Does `order` ask for the product to be transported somewhere after it's made: run, "
                          "belted, sent, carried or brought to some place?",
                          "yes: 'run them to the circuit build at [gps]', 'send the plates on a belt to the chest at "
                          "[gps]', 'belt them over to the science', 'and bring them to me'",
                          "no: 'into a chest', 'into a chest around [gps]', 'gears into a chest by the machines', "
                          "'onto a belt', 'put it on a belt', 'plates into chests'"),
        "onto_belt": noul("Does `order` ask for the finished product to be put onto an output belt rather than into "
                          "chests?",
                          "yes: 'put the cable on a belt', 'gears onto a belt', 'output onto a belt'",
                          "no: building the machines on, off or along a belt; 'into a chest'; nothing said"),
        "product": choice(PRODUCT_Q, opts),
        "count": choice("How many machines making the product itself does `order` ask for (not counting machines "
                        "that make its ingredients)? Pick the number written in it ('at least 3' -> 3, 'one assembler' "
                        "-> 1, '3 cable assemblers to 2 circuit assemblers' -> 2), or not_said.", COUNTS),
    }, kind="quickbuild")
    prod = a["product"].choice
    cnt = a["count"].choice
    return {"build": a["build"].p, "chain": max(a["several"].p, a["onward"].p), "elsewhere": a["elsewhere"].p,
            "onto_belt": a["onto_belt"].p, "product": prod, "product_p": float(a["product"].probs.get(prod) or 0),
            "count": cnt, "count_p": float(a["count"].probs.get(cnt) or 0),
            "output": "belt" if a["onto_belt"].p >= 0.75 else "chest"}


def accept(r: dict, far_point: bool = True) -> bool:
    """far_point: the order names a place more than ~40 tiles from the first one (code measures that; Jev doesn't do
    distances). Without one, "elsewhere" can only be nearby ("into a chest around [gps]"), so Jev's doubt counts less.
    "build" is logged but not gated on: the chat playbook already sent only build jobs here, and in the lab it caught
    nothing the other questions didn't while turning down plain orders ("iron sticks off this belt")."""
    # (chain = the larger of "several products?" and "feeds further machines?": both separate cleanly at 0.7)
    return (r["chain"] < 0.7 and r["elsewhere"] < (0.4 if far_point else 0.65)
            and r["product"] not in (None, "none_of_these") and r["product_p"] >= 0.55)
