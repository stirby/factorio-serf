"""Quick builds without the planner: a row of machines making one product off belts that are already there, the most
common build order ("make gears off this belt into a chest", "4 furnaces making steel off that belt").

Jev reads the order (is it that kind of job, which product, how many, where the output goes); code finds the belt
lines that carry the ingredients and lays out the tested row step (jev/rowgen.py), checks the layout is free, and
the usual plan runner builds and verifies it. Anything else, or any doubt, goes to the planner as before."""
from __future__ import annotations

import math
import re

from .rowgen import DIRS
from .typesafe import Jev, choice, noul
from .world import Line, World

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


def straight_runs(w: World, ln) -> list:
    """The straight stretches of a belt line that turns (each its own Line with the line's items), or [ln] when it's
    straight already. A row of machines goes along one stretch."""
    if _straight(w, ln):
        return [ln]
    runs, cur = [], []
    for u in ln.belts:
        e = w.ents.get(u)
        if not e:
            continue
        if cur and e.get("d") != w.ents[cur[-1]].get("d"):
            runs.append(cur)
            cur = []
        cur.append(u)
    if cur:
        runs.append(cur)
    out = []
    for k, r in enumerate(runs):
        a, b = w.ents[r[0]], w.ents[r[-1]]
        seg = Line(f"{ln.id}.{k + 1}", r, a.get("d", ln.direction), ln.items, (a["x"], a["y"]), (b["x"], b["y"]),
                   ln.start_reason if k == 0 else "turns here", ln.end_reason if k == len(runs) - 1 else "turns",
                   ln.density, takers=ln.takers, putters=ln.putters)
        if _straight(w, seg):
            out.append(seg)
    return out


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
    def dist(ln):
        return min(abs(t[0] - p[0]) + abs(t[1] - p[1]) for t in _tiles(w, ln) for p in points)
    # nearest first: with parallel belts carrying the same items, the row goes on the one the order points at
    # (a line that turns counts as its straight stretches)
    near = sorted((seg for ln in w.lines if ln.items for seg in straight_runs(w, ln) if dist(seg) <= 12), key=dist)
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


INSERTER_RATE = 0.83  # items/s a basic inserter moves


def feeders_needed(recipes: dict, product: str, made: str, n: int, speed: float = 0.5) -> int:
    """Feeder assemblers to keep n main machines supplied: recipe rates at assembler 1 speed, capped by what one
    basic inserter moves in and out (a gear feeder takes 2 plates per gear, so it makes ~0.4 gears/s, not 1), with
    half again as margin. A main machine's one inserter brings all its ingredients, so a circuit assembler takes at
    most 3/4 of what that inserter moves as cable."""
    r, rb = recipes.get(product) or {}, recipes.get(made) or {}
    ing = r.get("ingredients") or {}
    use = min(ing.get(made, 1) * speed / max(float(r.get("time") or 1), 0.1),
              INSERTER_RATE * ing.get(made, 1) / (sum(ing.values()) or 1))
    per_craft_in = sum((rb.get("ingredients") or {}).values()) or 1
    makes = float(rb.get("makes") or 1)
    make = min(makes * speed / max(float(rb.get("time") or 1), 0.1),  # the recipe
               INSERTER_RATE / per_craft_in * makes,                  # what its input inserter brings
               INSERTER_RATE)                                         # what its output inserter moves
    return max(1, math.ceil(n * use * 1.5 / make - 1e-9))


def feeders_that_fit(line_len: int, k: int, count: int, size: int = 3) -> int:
    """At most k feeders (4 tiles each), so the feeders, a 2-tile gap and the main row (output chests: pitch size+2)
    all fit along a belt of line_len tiles; at least one."""
    row_len = (count - 1) * (size + 2) + size + 1
    return max(1, min(k, (line_len - 2 - row_len - 1) // 4))


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


OUTPUT_BELT = re.compile(r"\b(?:onto|on to|into|on)\s+(?:a|an|another|its own|their own)\s+(?:new\s+|output\s+|own\s+)?belt"
                         r"|\boutputs?\b.{0,30}\bbelt|\bbelt\b.{0,30}\boutputs?\b|\bbelt (?:it|them|the \w+)\b"
                         r"|\bon(?:to)? (?:the|that|this) (?:other|second|empty|next) belt", re.I)
PRODUCT_Q = "Which of these does `order` ask to have made?"
COUNTS = {"not_said": "the order doesn't say how many machines", **{str(n): f"{n} machine(s)" for n in range(1, 13)}}


def products_named(order: str, products) -> list[str]:
    """The products the order names by their words ('gears and pipes' -> both; 'pipes, 3 assemblers, into chests'
    -> pipes only: an iron chest needs 'iron' too). Plurals and the chat names in SAY count."""
    def stem(w):
        return w[:-1] if w.endswith("s") and len(w) > 3 else w
    words = {stem(w) for w in re.findall(r"[a-z]+", order.lower())}
    out = []
    for p in products:
        names = [p.replace("-", " ")] + ([SAY[p]] if p in SAY else [])
        if any(all(stem(w) in words for w in nm.split()) for nm in names):
            out.append(p)
    return out


OTHER_NAMES = {"copper-cable": "wire", "firearm-magazine": "magazine", "electronic-circuit": "circuit"}


def only_word(order: str, products: list[str], every: list[str] | None = None, carried=None) -> str | None:
    """The one option the order names by a word no other option has ("I need copper made" when the belt can only
    make copper plates), provided it doesn't fully name some product that isn't an option ("copper cable" off an
    ore belt). Jev hears "copper" alone as none of them."""
    infra = {"transport-belt", "inserter", "stone-furnace", "assembling-machine-1", "small-electric-pole", "iron-chest",
             "wooden-chest"}  # what orders talk about building with ("off this belt", "2 furnaces", "into chests")
    # (what the belt carries is the input: "the belt carries iron plates ... make steel")
    if products_named(order, [p for p in (every or SAY) if p not in products and p not in infra
                              and p not in (carried or [])]):
        return None
    # "3 furnaces", "a couple of assemblers": how many machines, not a product named
    plain = re.sub(r"\b\d+\s+(?:more\s+)?(?:stone\s+|steel\s+)?(?:furnaces?|assemblers?|assembling machines?|machines?)\b",
                   " ", plain_counts(order.lower()))
    # "into chests", "in a chest": where the product goes, not an iron chest to make
    plain = re.sub(r"\b(?:into|in|to)\s+(?:a\s+|the\s+|some\s+)?(?:chests?|boxes?)\b", " ", plain)
    words = {w[:-1] if w.endswith("s") and len(w) > 3 else w for w in re.findall(r"[a-z]+", plain)}
    def names(p):  # the product's own words and its chat names ("ammo" for firearm-magazine, "wire" for cable)
        out = set(p.split("-")) | set(SAY.get(p, "").split()) | set(OTHER_NAMES.get(p, "").split())
        return {w[:-1] if w.endswith("s") and len(w) > 3 else w for w in out}
    hits = []
    for p in products:
        mine = names(p) - {w for q in products if q != p for w in names(q)}
        if mine & words:
            hits.append(p)
    return hits[0] if len(hits) == 1 else None


def named_products(order: str, products: list[str]) -> int:
    return len(products_named(order, products))


def plain_counts(order: str) -> str:
    """'a couple of machines' -> '2 machines', 'a few' -> '3': Jev read 'a couple' as several products."""
    order = re.sub(r"\ba couple(?: of)?\b", "2", order, flags=re.I)
    order = re.sub(r"\ba few\b", "3", order, flags=re.I)
    return order


async def read_order(jev: Jev, order: str, products: list[str], carried: list[str] | None = None) -> dict:
    alias = {"iron-gear-wheel": "gears", "firearm-magazine": "ammo, yellow ammo", "copper-cable": "wire",
             "electronic-circuit": "green circuits", "automation-science-pack": "red science",
             "iron-plate": "iron, plates: furnaces smelting iron ore",
             "copper-plate": "copper, plates: furnaces smelting copper ore",
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
                      "belt', 'can you automate wire from the belt?, into a chest' (making the wire)",
                      "no: moving or belting items that already exist from one place to another, fixing or "
                      "refuelling, power, putting drills on ore, research, a question"),
        "several": noul("Does `order` ask for two or more DIFFERENT kinds of item to be made?",
                        "yes: 'make gears and pipes', 'iron chests and pipes off the belt'",
                        "no: one kind of item, whatever the plurals or how many machines and chests ('pipes, 3 "
                        "assemblers, into chests'); one item even if something has to be made for it first (red "
                        "science, green circuits)"),
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
    prod_p = float(a["product"].probs.get(prod) or 0)
    own = only_word(order, products, carried=carried)
    if prod == "none_of_these" and prod_p < 0.9 and own:
        prod, prod_p = own, 0.6
    elif own and prod != own and prod_p < 0.6:
        # Jev unsure, and the order names another option by its own word ("magazines ..., into chests": Jev wavered
        # towards iron chests)
        prod, prod_p = own, 0.6
    elif own and prod == own:
        # Jev's pick is the one option the order names by its own word ("plates please, off that belt" with only
        # iron plates to make there): its doubt is between that and nothing, not between products
        prod_p = max(prod_p, 0.6)
    cnt = a["count"].choice
    cnt_p = float(a["count"].probs.get(cnt) or 0)
    # "3 assemblers", "2 furnaces": an exact number next to a machine word is read by code
    m = re.search(r"\b(\d{1,2})\s+(?:more\s+)?(?:stone\s+|steel\s+)?(?:assemblers?|assembling machines?|machines?|furnaces?)\b",
                  plain_counts(order), re.I)
    if m and 1 <= int(m.group(1)) <= 12:
        cnt, cnt_p = m.group(1), 1.0
    # an output belt needs words for one ("onto a belt", "output on a belt", "belt them"): "make steel off the belt"
    # names only the belt it comes from, and Jev sometimes hears that as an output belt
    onto = a["onto_belt"].p if OUTPUT_BELT.search(order) else min(a["onto_belt"].p, 0.3)
    # "several products" needs the order to name two of them: Jev alone hears plurals ("plates ... into chests") as
    # several
    several = a["several"].p if named_products(order, products) >= 2 else min(a["several"].p, 0.3)
    return {"build": a["build"].p, "chain": max(several, a["onward"].p), "elsewhere": a["elsewhere"].p,
            "onto_belt": onto, "product": prod, "product_p": prod_p,
            "count": cnt, "count_p": cnt_p,
            "output": "belt" if onto >= 0.75 else "chest"}


def accept(r: dict, far_point: bool = True, one_point: bool = False, belt_to_place: bool = False) -> bool:
    """far_point: the order names a place more than ~40 tiles from the first one (code measures that; Jev doesn't do
    distances). Without one, "elsewhere" can only be nearby ("into a chest around [gps]"), so Jev's doubt counts less.
    "build" is logged but not gated on: the chat playbook already sent only build jobs here, and in the lab it caught
    nothing the other questions didn't while turning down plain orders ("iron sticks off this belt")."""
    # (chain = the larger of "several products?" and "feeds further machines?": both separate cleanly at 0.7)
    # one_point: the order names no other place at all, so "elsewhere" can only be a chest by the machines ("..., into
    # a chest") or the speaker ("bring them to me", which reads well above 0.85)
    # belt_to_place: words for an output belt and another place named ("plates on a belt into the chest at [gps]"):
    # it's sent on, which the compose path does, whatever Jev's "elsewhere" says
    limit = 0.4 if far_point or belt_to_place else (0.85 if one_point else 0.65)
    return (r["chain"] < 0.7 and r["elsewhere"] < limit
            and r["product"] not in (None, "none_of_these") and r["product_p"] >= 0.55)
