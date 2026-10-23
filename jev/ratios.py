"""Throughput: what a target rate of an item takes, all the way down to ore, crude and water.

Players size a build from the rate they want ("45 purple a minute") and work the chain back: machines per step,
belts of plates, drills, refineries. The serf built the minimum that met a check and starved itself every time it
added a consumer. This is that arithmetic, in code: recipes are fixed, so it is exact, and nobody should guess it.

    from jev.ratios import solve, table
    plan = solve({"production-science-pack": 45})
    print(table(plan))

Recipe data: jev/data/recipes.json (scripts/dump_recipes.py dumps it from the game). Rates are per minute. Oil
products come from one oil setup sized to all three demands at once (advanced processing + cracking), the way the
library's advanced-oil-processing-block works.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

DATA = json.loads((Path(__file__).parent / "data" / "recipes.json").read_text())
RECIPES: dict = DATA["recipes"]
MACHINES: dict = DATA["machines"]

RAW = {"iron-ore", "copper-ore", "stone", "coal", "crude-oil", "water", "uranium-ore", "wood"}
OIL = {"petroleum-gas", "light-oil", "heavy-oil"}  # from the oil setup, solved together
# where several recipes make an item, the one a Nauvis base uses
PREFER = {"solid-fuel": "solid-fuel-from-light-oil", "rocket-fuel": "rocket-fuel", "lubricant": "lubricant",
          "plastic-bar": "plastic-bar", "sulfur": "sulfur", "sulfuric-acid": "sulfuric-acid", "battery": "battery",
          "advanced-circuit": "advanced-circuit", "low-density-structure": "low-density-structure",
          "iron-plate": "iron-plate", "copper-plate": "copper-plate", "steel-plate": "steel-plate",
          "iron-gear-wheel": "iron-gear-wheel", "copper-cable": "copper-cable", "iron-stick": "iron-stick",
          "concrete": "concrete", "pipe": "pipe", "pipe-to-ground": "pipe-to-ground"}
SKIP = ("recycling", "casting-", "barrel", "asteroid", "bio", "molten", "kovarex", "-from-lava", "spoilage",
        "bacteria", "jelly", "ammonia", "coal-liquefaction")
BELT = {"transport-belt": 900, "fast-transport-belt": 1800, "express-transport-belt": 2700}  # items a minute
DRILL_PER_MIN = 30.0  # an electric mining drill on ordinary ore (0.5/s)
PUMPJACK_PER_MIN = 600.0  # a pumpjack on a fresh field, roughly (10/s at 100% yield)

DEFAULT_MACHINES = {"smelting": "steel-furnace", "chemistry": "chemical-plant", "oil-processing": "oil-refinery",
                    "rocket-building": "rocket-silo"}
DEFAULT_ASSEMBLER = "assembling-machine-2"


def recipe_for(item: str) -> str | None:
    if item in PREFER and PREFER[item] in RECIPES:
        return PREFER[item]
    if item in RECIPES and any(p["name"] == item for p in RECIPES[item]["products"]):
        return item
    for name, r in sorted(RECIPES.items()):
        if any(s in name for s in SKIP):
            continue
        if any(p["name"] == item for p in r["products"]):
            return name
    return None


def machine_for(recipe: str, assembler: str = DEFAULT_ASSEMBLER, furnace: str = "steel-furnace") -> str:
    cat = RECIPES[recipe]["category"]
    if cat == "smelting":
        return furnace
    for c, m in DEFAULT_MACHINES.items():
        if cat == c or cat.startswith(c) or c in cat.split("-or-"):
            if m in MACHINES and cat in MACHINES[m]["categories"]:
                return m
    if assembler in MACHINES and cat in MACHINES[assembler]["categories"]:
        return assembler
    for m, spec in MACHINES.items():  # whatever can make it
        if cat in spec["categories"]:
            return m
    return assembler


def _product_amount(recipe: str, item: str) -> float:
    return sum(p["amount"] for p in RECIPES[recipe]["products"] if p["name"] == item)


def solve(targets: dict[str, float], assembler: str = DEFAULT_ASSEMBLER, furnace: str = "steel-furnace",
          belt: str = "transport-belt") -> dict:
    """Everything needed to make `targets` (item -> per minute). Returns {targets, steps: [{recipe, item, machine,
    count, per_min}], raw: {item: per_min}, oil: {...}, belts: {item: belts}, drills: {ore: drills}}."""
    demand: dict[str, float] = {}
    runs: dict[str, float] = {}  # recipe -> runs a minute
    order: list[str] = []

    def add(item: str, rate: float, depth: int = 0) -> None:
        demand[item] = demand.get(item, 0.0) + rate
        if item in RAW or item in OIL or depth > 30:
            return
        r = recipe_for(item)
        if not r:
            return
        n = rate / max(_product_amount(r, item), 1e-9)
        runs[r] = runs.get(r, 0.0) + n
        if r not in order:
            order.append(r)
        for ing in RECIPES[r]["ingredients"]:
            add(ing["name"], n * ing["amount"], depth + 1)

    for item, rate in targets.items():
        add(item, float(rate))

    steps = []
    for r in order:
        m = machine_for(r, assembler, furnace)
        speed = MACHINES.get(m, {}).get("speed", 1) or 1
        count = runs[r] * RECIPES[r]["energy"] / 60.0 / speed
        main = next((p["name"] for p in RECIPES[r]["products"]), r)
        steps.append({"recipe": r, "item": main, "machine": m, "count": count,
                      "per_min": runs[r] * _product_amount(r, main)})
    oil = solve_oil({k: demand.get(k, 0.0) for k in OIL})
    raw = {k: v for k, v in demand.items() if k in RAW}
    for k in ("crude-oil", "water"):
        if oil.get(k):
            raw[k] = raw.get(k, 0.0) + oil[k]
    per_belt = BELT.get(belt, 900)
    solids = {k: v for k, v in demand.items() if k not in OIL and k not in ("water", "crude-oil")}
    return {"targets": dict(targets), "steps": steps, "raw": raw, "oil": oil,
            "belts": {k: v / per_belt for k, v in solids.items() if v / per_belt >= 0.05},
            "drills": {k: raw[k] / DRILL_PER_MIN for k in ("iron-ore", "copper-ore", "stone", "coal") if raw.get(k)},
            "pumpjacks": raw.get("crude-oil", 0.0) / PUMPJACK_PER_MIN, "belt": belt}


def solve_oil(need: dict[str, float]) -> dict:
    """Refineries (advanced processing) and crackers for petroleum, light and heavy oil demands (per minute), the
    fewest refineries that cover all three. Each refinery run (5 s): 100 crude + 50 water -> 25 heavy + 45 light +
    55 petroleum; heavy cracking (2 s): 40 heavy + 30 water -> 30 light; light cracking (2 s): 30 light + 30 water ->
    20 petroleum. Anything left over has to go somewhere, or the refinery stops: `surplus` says what."""
    P, L, H = (need.get("petroleum-gas", 0.0), need.get("light-oil", 0.0), need.get("heavy-oil", 0.0))
    if P + L + H <= 0:
        return {}
    r = max((P + 0.5 * H + 2 * L / 3) / 97.5, H / 25.0, (0.75 * H + L) / 63.75)  # refinery runs a minute
    hc = (25 * r - H) / 40.0  # heavy cracking runs a minute
    lc = max(0.0, (45 * r + 30 * hc - L) / 30.0)
    petroleum = 55 * r + 20 * lc
    surplus = {"petroleum-gas": max(0.0, petroleum - P)}
    return {"refineries": r * 5 / 60.0, "heavy_crackers": hc * 2 / 60.0, "light_crackers": lc * 2 / 60.0,
            "crude-oil": 100 * r, "water": 50 * r + 30 * hc + 30 * lc,
            "surplus": {k: v for k, v in surplus.items() if v > 0.5}}


def table(plan: dict, margin: float = 1.0) -> str:
    """The plan in words a planner can build from. margin > 1 rounds machine counts for headroom (1.25 = 25% more)."""
    t = ", ".join(f"{v:g}/min {k}" for k, v in plan["targets"].items())
    lines = [f"To make {t}:"]
    for s in plan["steps"]:
        n = max(1, math.ceil(s["count"] * margin - 1e-6))
        lines.append(f"- {s['recipe']}: {n} x {s['machine']} ({s['count']:.2f} exact), {s['per_min']:.1f} {s['item']}/min")
    o = plan["oil"]
    if o:
        lines.append(f"- oil: {math.ceil(o['refineries'] * margin - 1e-6)} oil-refinery (advanced processing, "
                     f"{o['refineries']:.2f} exact), {math.ceil(o['heavy_crackers'] * margin - 1e-6)} heavy-oil-cracking "
                     f"and {math.ceil(o['light_crackers'] * margin - 1e-6)} light-oil-cracking chemical plants"
                     + (f"; surplus {', '.join(f'{v:.0f}/min {k}' for k, v in o['surplus'].items())} needs a consumer"
                        if o.get("surplus") else ""))
    raw = ", ".join(f"{v:.0f}/min {k}" for k, v in sorted(plan["raw"].items(), key=lambda kv: -kv[1]))
    lines.append(f"Raw: {raw}.")
    if plan["drills"]:
        lines.append("Mining: " + ", ".join(f"{math.ceil(v * margin - 1e-6)} electric drills on {k}"
                                            for k, v in plan["drills"].items())
                     + (f", {math.ceil(plan['pumpjacks'] * margin - 1e-6)} pumpjacks" if plan["pumpjacks"] else "") + ".")
    big = [f"{k} {v:.1f}" for k, v in sorted(plan["belts"].items(), key=lambda kv: -kv[1]) if v >= 0.25]
    if big:
        lines.append(f"Belts ({plan['belt']}, full belts): " + ", ".join(big) + ".")
    return "\n".join(lines)
