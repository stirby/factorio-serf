"""How many of an item could be had from what's in storage, machine outputs and the character's pockets: the item
itself plus hand-crafting it from ingredients (recursively). The planner gets these numbers so it sizes a build to
what exists instead of finding out during a long fetch-and-craft run."""
from __future__ import annotations

HAND = ("crafting", "advanced-crafting", "electronics", "pressing")
KEY = ["assembling-machine-1", "assembling-machine-2", "inserter", "fast-inserter", "long-handed-inserter",
       "transport-belt", "underground-belt", "splitter", "small-electric-pole", "medium-electric-pole",
       "stone-furnace", "steel-furnace", "electric-mining-drill", "burner-mining-drill", "pipe", "boiler",
       "steam-engine", "lab", "iron-chest"]


def _take(item: str, n: int, stock: dict, recipes: dict, depth: int = 0) -> bool:
    """Use n of item from stock, crafting the shortfall from ingredients (stock is consumed as it goes)."""
    have = stock.get(item, 0)
    use = min(have, n)
    stock[item] = have - use
    n -= use
    if n <= 0:
        return True
    r = recipes.get(item)
    if not r or depth > 6 or (r.get("category") or "crafting") not in HAND:
        return False
    per = int(r.get("makes") or 1)
    runs = -(-n // per)
    for ing, amt in (r.get("ingredients") or {}).items():
        if not _take(ing, int(amt) * runs, stock, recipes, depth + 1):
            return False
    stock[item] = stock.get(item, 0) + runs * per - n  # leftovers of a multi-output craft
    return True


def most(item: str, stock: dict, recipes: dict, cap: int = 200) -> int:
    """The most of item that stock covers, up to cap."""
    lo, hi = 0, cap
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _take(item, mid, dict(stock), recipes):
            lo = mid
        else:
            hi = mid - 1
    return lo


def summary(stock: dict, recipes: dict, items=KEY, cap: int = 200) -> list[tuple[str, int]]:
    """(item, how many could be had) for the key building items that have a recipe."""
    return [(i, most(i, stock, recipes, cap)) for i in items if i in recipes or stock.get(i)]
