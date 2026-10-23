"""Step runner: one plan step -> mod actions, with the obvious prerequisites done in code (fetch what the step
needs before placing it, keep building ghosts until none are left, refuel = get coal + insert).

A step is a dict {"do": <op>, ...}. Ops:
  rotate x y direction | place name x y [direction] [recipe] [pickup|drop] | set_recipe x y recipe
  connect item from to [end_direction] | ghosts entities=[{name,x,y,direction,recipe}] | stamp string x y [direction]
  build_ghosts [x y radius] | fetch item count | craft recipe count | mine name count | mine_at x y
  insert x y item [count] | take x y [item] [count] | empty_chest x y | refuel x y [fuel] | power x y [from]
  research tech | wait seconds | say text | move x y
Each returns {"ok": bool, "msg": str, ...}. The runner never decides what to do about a failure: the actor does.
"""
from __future__ import annotations

import asyncio
import logging
import math
import re
import time

from .game import Game
from .world import grid_live

log = logging.getLogger("jev.steps")

FUELS = ("coal", "wood", "solid-fuel")
MINEABLE = {"wood": "tree", "iron-ore": "iron-ore", "copper-ore": "copper-ore", "stone": "stone", "coal": "coal"}
PLACE_ITEM = {"straight-rail": "rail", "curved-rail-a": "rail", "curved-rail-b": "rail"}


# Upgrade families, lowest tier first. Upgrading into a belt tier upgrades the matching undergrounds and splitters too.
TIERS = [["transport-belt", "fast-transport-belt", "express-transport-belt", "turbo-transport-belt"],
         ["underground-belt", "fast-underground-belt", "express-underground-belt", "turbo-underground-belt"],
         ["splitter", "fast-splitter", "express-splitter", "turbo-splitter"],
         ["assembling-machine-1", "assembling-machine-2", "assembling-machine-3"],
         ["stone-furnace", "steel-furnace"],
         ["burner-inserter", "inserter", "fast-inserter"],
         ["small-electric-pole", "medium-electric-pole"],
         ["pipe-to-ground"], ["wooden-chest", "iron-chest", "steel-chest"]]


def upgrade_map(into: str) -> dict:
    """{old name: new name} for an upgrade into `into` (only lower tiers go up)."""
    fam = next((f for f in TIERS if into in f), None)
    if not fam:
        return {}
    t = fam.index(into)
    out = {old: into for old in fam[:t]}
    if fam is TIERS[0]:  # belts: their undergrounds and splitters move up a tier with them
        for sib in (TIERS[1], TIERS[2]):
            out.update({old: sib[t] for old in sib[:t]})
    return out


def unplaced(asked: list[dict], r: dict) -> list[dict]:
    """The requested ghosts the game refused for a real reason (not "an identical one already stands there"), each
    with that reason under "_why"."""
    failed = r.get("failed") or []
    if isinstance(failed, dict):
        failed = list(failed.values())
    out = []
    for f in failed:
        if not isinstance(f, dict) or f.get("why") in ("same", "turn"):
            continue
        fx, fy = float(f.get("x", 1e9)), float(f.get("y", 1e9))
        e = next((a for a in asked if abs(a["x"] - fx) < 0.01 and abs(a["y"] - fy) < 0.01), None)
        if e:
            out.append({**e, "_why": f.get("why")})
    return out


def turns(r: dict) -> list[dict]:
    """Pieces already standing where the layout wants them but facing another way: rotate steps."""
    failed = r.get("failed") or []
    if isinstance(failed, dict):
        failed = list(failed.values())
    return [{"do": "rotate", "x": f["x"], "y": f["y"], "direction": f["direction"]} for f in failed
            if isinstance(f, dict) and f.get("why") == "turn" and f.get("direction")]


def ghost_result(b: dict, s: dict) -> dict:
    """A ghosts step whose layout the game refused in places has not done its job, even if the rest got built."""
    bad = s.get("_unplaced") or []
    if not bad or not b.get("ok"):
        return b
    where = "; ".join(f"{e['name']} at {e['x']},{e['y']} ({e['_why']})" for e in bad[:4])
    more = f" and {len(bad) - 4} more" if len(bad) > 4 else ""
    return {"ok": False, "msg": f"{b.get('msg') or ''}. But {len(bad)} part(s) of the layout couldn't be placed: "
                                f"{where}{more}"}


def expand(entities: list) -> list[dict]:
    """Compact layout notation -> plain entities:
      {"repeat": N, "dx": 2, "dy": 0, "entities": [...]}   the group N times, shifted by (dx, dy) each time
      {"line": "transport-belt", "from": [x, y], "to": [x, y], "direction": "east"}   a straight run, one per tile
    Plain {name, x, y, ...} entries pass through. Nesting works."""
    out: list[dict] = []
    for e in entities or []:
        if not isinstance(e, dict):
            continue
        if "repeat" in e:
            n = int(e.get("repeat") or 0)
            dx, dy = float(e.get("dx", 0)), float(e.get("dy", 0))
            inner = expand(e.get("entities") or [])
            for k in range(min(n, 200)):
                for x in inner:
                    out.append({**x, "x": float(x["x"]) + dx * k, "y": float(x["y"]) + dy * k})
        elif "line" in e:
            f, t = e.get("from"), e.get("to")
            try:
                fx, fy, tx, ty = float(f[0]), float(f[1]), float(t[0]), float(t[1])
            except (TypeError, ValueError, IndexError):
                continue
            n = int(max(abs(tx - fx), abs(ty - fy)))
            sx = (tx > fx) - (tx < fx)
            sy = (ty > fy) - (ty < fy)
            d = e.get("direction") or ("east" if sx > 0 else "west" if sx < 0 else "south" if sy > 0 else "north")
            for k in range(min(n, 400) + 1):
                q = {"name": e["line"], "x": fx + sx * k, "y": fy + sy * k, "direction": d}
                out.append(q)
        elif "name" in e and "x" in e and "y" in e:
            out.append(e)
    return out


def _xy(s: dict, key: str = "") -> tuple[float, float] | None:
    if key and isinstance(s.get(key), (list, tuple)) and len(s[key]) == 2:
        return float(s[key][0]), float(s[key][1])
    if "x" in s and "y" in s:
        return float(s["x"]), float(s["y"])
    return None


def belt_end_targets(w, ends: set | None = None) -> set[tuple[int, int]]:
    """Free tiles an open belt end (belt, underground exit, splitter) points into: a new belt laid on one takes that
    end's items, side-loaded or head on. Belts standing on `ends` (a line's own source) don't count."""
    import math as _m
    from .world import DIRS
    out = set()
    for e in w.ents.values():
        t, d = e.get("t"), e.get("d")
        if d not in DIRS or not (t in ("transport-belt", "splitter") or (t == "underground-belt" and e.get("ug") == "output")):
            continue
        if ends and (_m.floor(e["x"]), _m.floor(e["y"])) in ends:
            continue
        dx, dy = DIRS[d]
        offs = (-0.5, 0.5) if t == "splitter" else (0.0,)
        for o in offs:
            tile = (_m.floor(e["x"] - dy * o + dx), _m.floor(e["y"] + dx * o + dy))
            if tile not in w.tile:
                out.add(tile)
    return out


def describe(step: dict) -> str:
    d = step.get("do", "?")
    if step.get("text"):
        return step["text"]
    p = _xy(step)
    at = f" at {p[0]:g},{p[1]:g}" if p else ""
    if d == "place":
        return f"place {step.get('name')}{at}" + (f" facing {step['direction']}" if step.get("direction") else "")
    if d == "connect":
        return f"run {step.get('item')} from {step.get('from')} to {step.get('to')}"
    if d == "ghosts":
        return f"lay out {len(step.get('entities') or [])} buildings as a plan and build them"
    if d in ("fetch", "craft", "mine"):
        return f"{d} {step.get('count', '')} {step.get('item') or step.get('recipe') or step.get('name')}"
    if d == "insert":
        return f"put {step.get('count', '')} {step.get('item')} into the thing{at}"
    if d == "say":
        return "say: " + str(step.get("text", ""))[:60]
    if d == "bus":
        return f"lay bus {step.get('name') or 'main'}" + (f" ({', '.join(map(str, step['lanes']))})" if step.get(
            "lanes") else "")
    if d == "tap":
        return f"tap the {step.get('lane')} lane of bus {step.get('bus') or 'main'} at row {step.get('at')}"
    if d == "bus_in":
        return f"put {step.get('item') or step.get('lane')} onto bus {step.get('bus') or 'main'} at row {step.get('at')}"
    return f"{d}{at}"


class Runner:
    def __init__(self, game: Game, log_fn=None):
        self.g = game
        self.log_fn = log_fn or (lambda rec: None)
        self.inventory: dict = {}
        self.recipes: dict = {}
        self.fuel_ahead = 0  # fuel the running plan's remaining refuel steps will use (set by the actor)
        self.no_path_streak = 0  # actions in a row that found no path: the character may have walled itself in
        self.abort = None  # set while an order runs: true once that order is cancelled, so its remaining actions stop
        self._escaping = False
        self.routed: list[dict] = []  # what each route step laid: {"ends": endpoint tiles, "tiles": belt tiles}

    async def refresh_inventory(self) -> dict:
        try:
            me = await self.g.me()
            self.inventory = me.get("inventory") or {}
        except Exception as e:  # noqa: BLE001
            log.warning("inventory read failed: %r", e)
        return self.inventory

    async def _act(self, action: dict, timeout: float = 240, retry: bool = True) -> dict:
        if self.abort and self.abort():
            # the order was cancelled (a player's stop, a project moving on): one step can be dozens of actions
            # (every ghost of a layout), so stop here rather than at the next step
            return {"ok": False, "msg": "cancelled", "cancelled": True}
        t0 = time.time()
        r = await self.g.run(action, timeout=timeout)
        self.log_fn({"t": t0, "kind": "act", "action": action, "ok": r.get("ok"), "msg": r.get("msg"),
                     "secs": round(time.time() - t0, 1)})
        if not r.get("ok") and "inventory" in str(r.get("msg")) and "full" in str(r.get("msg")) \
                and retry and not getattr(self, "_tidying", False):
            # a full pocket breaks mining, taking and crafting (883 "inventory full" mines in an afternoon): make
            # room once and try again
            self._tidying = True
            try:
                t = await self.tidy(low=12, want=16)
            finally:
                self._tidying = False
            if t and t.get("ok"):
                return await self._act(action, timeout, retry=False)
        if str(r.get("msg") or "").startswith("no path to") and not self._escaping:
            self.no_path_streak += 1
            if self.no_path_streak >= 3:
                self.no_path_streak = 0
                if await self.escape():
                    return await self._act(action, timeout)
        elif r.get("ok"):
            self.no_path_streak = 0
        return r

    # what may go into a dump chest when the pockets fill up, and how much of it to keep (buildings always stay)
    KEEP = {"coal": 100, "wood": 50, "solid-fuel": 50, "iron-plate": 200, "copper-plate": 200, "steel-plate": 100,
            "stone-brick": 100, "iron-ore": 0, "copper-ore": 0, "stone": 0, "uranium-ore": 0, "sulfur": 0,
            "iron-gear-wheel": 100, "copper-cable": 100, "electronic-circuit": 100, "advanced-circuit": 100,
            "processing-unit": 100, "engine-unit": 50, "electric-engine-unit": 50, "plastic-bar": 100,
            "battery": 100, "low-density-structure": 50, "rocket-fuel": 50, "flying-robot-frame": 50,
            "iron-stick": 100, "automation-science-pack": 0, "logistic-science-pack": 0, "chemical-science-pack": 0,
            "production-science-pack": 0, "utility-science-pack": 0, "military-science-pack": 0}

    async def free_slots(self) -> int | None:
        try:
            me = await self.g.me()
            if "free_slots" in me:
                return int(me["free_slots"])
            r = await self.g.call("eval", code=f"local a = storage.agents['{self.g.name}'] "
                                  "return a.char.get_main_inventory().count_empty_stacks()", timeout=15)
            return int(r.get("result"))
        except Exception:  # noqa: BLE001
            return None

    async def tidy(self, low: int = 10, want: int = 20) -> dict | None:
        """Pockets nearly full (fewer than `low` free slots): drop raw resources and the surplus of plates and
        intermediates into a chest placed beside the character, until `want` slots are free. Fetching takes from
        chests, so nothing is lost. A full inventory quietly breaks mining, taking and hand-crafting: five of eight
        serfs were at 0 free slots after a night of campaigns (3,952 iron plates, 1,700 coal...)."""
        free = await self.free_slots()
        if free is None or free >= low:
            return None
        inv = await self.refresh_inventory()
        dump = sorted(((k, n - self.KEEP[k]) for k, n in inv.items() if k in self.KEEP and n > self.KEEP[k]),
                      key=lambda t: -t[1])
        if not dump:
            return {"ok": False, "msg": f"{free} free slots and nothing to drop"}
        me = await self.g.me()
        x, y = me["position"]
        # chests nearby with room first (a full pocket can't even craft a new chest); then new chests beside it
        sc = await self.g.scan(center=(x, y), radius=32)
        targets = sorted(([e["x"], e["y"]] for e in (sc.get("ents") or []) if e.get("t") == "container"
                          and not e.get("ghost") and (e.get("free") or 0) >= 4),
                         key=lambda q: (q[0] - x) ** 2 + (q[1] - y) ** 2)[:6]
        made, moved = 0, {}
        carried = next((c for c in ("steel-chest", "iron-chest", "wooden-chest") if inv.get(c)), None)
        # crafting a chest needs a slot for it; with none, only chests in the pocket or already built will do
        can_make = free >= 1 or carried is not None
        for item, n in dump:
            while n > 0:
                if not targets:
                    if made >= 3 or not can_make:
                        break
                    fs = await self.g.call("find_space", agent=self.g.name, w=1, h=1, x=x, y=y, radius=24)
                    cands = fs.get("candidates") or []
                    name = carried or "iron-chest"
                    if not cands or not (await self.ensure(name, 1, grab=False)).get("ok"):
                        can_make = False
                        break
                    spot = cands[0]["center"]
                    if not (await self._act({"op": "place", "name": name, "x": spot[0], "y": spot[1]})).get("ok"):
                        can_make = False
                        break
                    made += 1
                    targets.append(spot)
                have = (await self.refresh_inventory()).get(item, 0)
                r = await self._act({"op": "insert", "x": targets[0][0], "y": targets[0][1], "item": item,
                                     "count": n})
                put = have - (await self.refresh_inventory()).get(item, 0)
                if put > 0:
                    moved[item] = moved.get(item, 0) + put
                    n -= put
                if not r.get("ok") or put <= 0 or n > 0:
                    targets.pop(0)  # that chest is full
            free = await self.free_slots()
            if free is not None and free >= want:
                break
        chests = made
        self.log_fn({"t": time.time(), "kind": "tidy", "moved": moved, "chests": chests, "free_after": free})
        return {"ok": True, "msg": f"put {sum(moved.values())} items in {chests} chest(s); {free} slots free"}

    ESCAPE_THROUGH = ("transport-belt", "underground-belt", "splitter", "pipe", "pipe-to-ground", "electric-pole",
                      "inserter", "container", "wall")

    async def escape(self) -> bool:
        """Several places in a row have no path: if the character can't walk anywhere, it has walled itself in
        (belts, pipes, machines round it). Do what a player does: pick up the nearest belt, pipe, pole or chest beside
        it, step out through the gap, and put the piece back from outside. True when it got out."""
        self._escaping = True
        try:
            me = await self.g.me()
            x, y = me["position"]
            for dx, dy in ((14, 0), (-14, 0), (0, 14), (0, -14)):
                r = await self.g.run({"op": "move", "x": x + dx, "y": y + dy, "radius": 6}, timeout=60)
                if r.get("ok"):
                    self.log_fn({"t": time.time(), "kind": "escape", "trapped": False})
                    return False  # it can walk: the places it wanted are unreachable, not the character stuck
            sc = await self.g.scan(center=(x, y), radius=4)
            near = [e for e in (sc.get("ents") or []) if not e.get("ghost") and e.get("t") in self.ESCAPE_THROUGH
                    and abs(e["x"] - x) <= 2.6 and abs(e["y"] - y) <= 2.6]
            near.sort(key=lambda e: (e["x"] - x) ** 2 + (e["y"] - y) ** 2)
            for e in near[:4]:
                took = await self.g.run({"op": "mine", "x": e["x"], "y": e["y"], "name": e["n"]}, timeout=30)
                if not took.get("ok"):
                    continue
                vx, vy = e["x"] - x, e["y"] - y
                n = max(abs(vx), abs(vy), 0.5)
                out = await self.g.run({"op": "move", "x": x + vx / n * 8, "y": y + vy / n * 8, "radius": 3},
                                       timeout=60)
                back = {"op": "place", "name": e["n"], "x": e["x"], "y": e["y"]}
                if e.get("d"):
                    back["direction"] = e["d"]
                if e.get("ug"):
                    back["type"] = e["ug"]
                put = await self.g.run(back, timeout=60)
                self.log_fn({"t": time.time(), "kind": "escape", "trapped": True, "through": e["n"],
                             "at": [e["x"], e["y"]], "out": out.get("ok"), "put_back": put.get("ok")})
                if out.get("ok"):
                    return True
            self.log_fn({"t": time.time(), "kind": "escape", "trapped": True, "out": False})
            return False
        except Exception as ex:  # noqa: BLE001
            self.log_fn({"t": time.time(), "kind": "error", "where": "escape", "error": repr(ex)})
            return False
        finally:
            self._escaping = False

    async def stock(self, need: dict) -> dict:
        """Get everything in `need` ({item: count}) in one trip: fetches queued back to back, so the character walks
        to storage once. Returns {item: error} for what it couldn't get."""
        inv = await self.refresh_inventory()
        short = {i: int(n) for i, n in need.items() if inv.get(i, 0) < int(n)}
        if not short:
            return {}
        t0 = time.time()
        # what can't be had at all is reported now, not after a long walk collecting ingredients for it: storage,
        # machine outputs and pockets, crafting (wood, stone and coal count as minable)
        known_short = {}
        if self.recipes:
            try:
                from . import craft
                have = dict((await self.g.call("query", what="materials", outputs=True)).get("materials") or {})
                for k, v in inv.items():
                    have[k] = have.get(k, 0) + v
                for raw in ("wood", "stone", "coal"):
                    have[raw] = have.get(raw, 0) + 10000
                for i, n in list(short.items()):
                    can = craft.most(i, have, self.recipes, cap=n)
                    if can < n and i in self.recipes:
                        known_short[i] = (f"only {can} {i} can be had (storage, machine outputs, pockets and "
                                          f"crafting; needs {n})")
                        if can > inv.get(i, 0):
                            short[i] = can
                        else:
                            short.pop(i)
            except Exception as e:  # noqa: BLE001
                log.warning("craftable check failed: %r", e)
        if not short:
            self.log_fn({"t": t0, "kind": "stock", "need": need, "fails": known_short, "secs": 0})
            return known_short
        acts = [{"op": "fetch", "item": i, "count": n} for i, n in short.items()]
        try:
            ids = await self.g.act(acts)
        except Exception as e:  # noqa: BLE001
            return {i: repr(e) for i in short}
        fails = {}
        for i, jid in zip(short, ids):
            r = await self.g.wait_job(jid, 400)
            if r.get("timeout"):
                # stop waiting = stop the job: left running it blocked the queue for 41 minutes (yellow-blk-r4)
                await self.g.cancel(f"stocking {i} took too long", job=jid)
            if not r.get("ok"):
                fails[i] = r.get("msg")
        for i in list(fails):  # storage couldn't: try belts and crafting from belt items
            r = await self.ensure(i, short[i])
            if r.get("ok"):
                fails.pop(i)
        fails.update(known_short)
        self.log_fn({"t": t0, "kind": "stock", "need": short, "fails": fails, "secs": round(time.time() - t0, 1)})
        return fails

    async def ensure(self, item: str, count: int, depth: int = 0, grab: bool = True) -> dict:
        """Have at least count of item: storage first, then hand-crafting (the mod's fetch does both, fetching
        ingredients from storage too). If that fails: grab it, or its ingredients, off belts, then craft. An
        ingredient that can't be had is made the same way, a few levels down to mining the raw resource (a boiler
        needs a stone furnace, which needs stone that's in no chest)."""
        inv = await self.refresh_inventory()
        if inv.get(item, 0) >= count:
            return {"ok": True, "msg": f"have {inv[item]} {item}"}
        r = await self._act({"op": "fetch", "item": item, "count": count}, timeout=300)
        if r.get("ok"):
            return r
        if not grab:
            return r
        inv = await self.refresh_inventory()
        short = count - inv.get(item, 0)
        g = await self._act({"op": "grab", "item": item, "count": short}, timeout=120)
        if g.get("ok") and (await self.refresh_inventory()).get(item, 0) >= count:
            return g
        rec = (self.recipes or {}).get(item)
        if rec and (rec.get("category") or "crafting") in ("crafting", "advanced-crafting", "electronics",
                                                             "pressing"):
            per = int(rec.get("makes") or (2 if item == "copper-cable" else 1))
            runs = -(-short // per)
            inv = await self.refresh_inventory()
            for ing, n in (rec.get("ingredients") or {}).items():
                need = int(n) * runs
                if inv.get(ing, 0) < need:
                    gi = await self._act({"op": "grab", "item": ing, "count": need - inv.get(ing, 0)}, timeout=120)
                    if not gi.get("ok"):
                        fi = await self._act({"op": "fetch", "item": ing, "count": need}, timeout=300)
                        if not fi.get("ok") and ing in MINEABLE:
                            # raw: mine it (wood from trees: 4 per tree)
                            short_ing = need - (await self.refresh_inventory()).get(ing, 0)
                            if short_ing <= 300:
                                await self._act({"op": "mine", "name": MINEABLE[ing],
                                                 "count": max(1, -(-short_ing // 4)) if ing == "wood" else short_ing},
                                                timeout=600)
                        elif not fi.get("ok") and depth < 3:
                            await self.ensure(ing, need, depth + 1)
            r2 = await self._act({"op": "fetch", "item": item, "count": count}, timeout=300)
            if r2.get("ok"):
                return r2
        return r

    async def run(self, step: dict) -> dict:
        d = step.get("do")
        fn = getattr(self, f"_do_{d}", None)
        if fn is None:
            return {"ok": False, "msg": f"unknown step op {d!r}"}
        try:
            return await fn(step)
        except Exception as e:  # noqa: BLE001
            log.exception("step %s crashed", d)
            return {"ok": False, "msg": f"step crashed: {e!r}"}

    # ------------------------------------------------------------------ simple ops
    async def _do_rotate(self, s):
        p = _xy(s)
        a = {"op": "rotate", "x": p[0], "y": p[1]}
        if s.get("direction"):
            a["direction"] = s["direction"]
        if s.get("reverse"):
            a["reverse"] = True
        return await self._act(a)

    async def _do_set_recipe(self, s):
        p = _xy(s)
        return await self._act({"op": "set_recipe", "x": p[0], "y": p[1], "recipe": s["recipe"]})

    async def _do_place(self, s):
        p = _xy(s)
        item = PLACE_ITEM.get(s["name"], s["name"])
        r = await self.ensure(item, 1)
        if not r.get("ok"):
            return {"ok": False, "msg": f"couldn't get a {item}: {r.get('msg')}", "missing": {item: 1},
                    "unobtainable": True}
        a = {"op": "place", "name": s["name"], "x": p[0], "y": p[1]}
        for k in ("direction", "pickup", "drop", "type"):
            if s.get(k) is not None:
                a[k] = s[k]
        r = await self._act(a)
        msg = str(r.get("msg") or "")
        if not r.get("ok") and f"entity-ghost@{p[0]:g},{p[1]:g}" in msg.replace(".0,", ",").replace(".0;", ";"):
            # a plan of ours (or a player's) already marks this spot: build that ghost instead
            r = await self._act({"op": "build_ghosts", "x": p[0], "y": p[1], "radius": 1.5})
        elif not r.get("ok") and "character@" in msg:
            await self._act({"op": "move", "x": p[0] + 4, "y": p[1] + 4, "radius": 1})
            r = await self._act(a)
        if r.get("ok") and s.get("recipe"):
            r2 = await self._act({"op": "set_recipe", "x": p[0], "y": p[1], "recipe": s["recipe"]})
            if not r2.get("ok"):
                return {"ok": False, "msg": f"placed, but recipe failed: {r2.get('msg')}"}
            r["msg"] = (r.get("msg") or "") + f"; recipe {s['recipe']}"
        return r

    async def _do_connect(self, s):
        a = {"op": "connect", "item": s["item"], "from": list(s["from"]), "to": list(s["to"])}
        for k in ("end_direction", "join", "from_fluid", "to_fluid", "fluid"):
            if s.get(k) is not None:
                a[k] = s[k]
        fr, to = [float(v) for v in s["from"]], [float(v) for v in s["to"]]
        dist = math.hypot(to[0] - fr[0], to[1] - fr[1])
        if "pole" not in str(s["item"]):
            # routes go round things: carry well over the straight-line count (a pipe run 5 tiles apart took 20)
            need = min(400, int(2 * (abs(to[0] - fr[0]) + abs(to[1] - fr[1]))) + 12)
            await self.ensure(s["item"], need)
        if dist <= 230:
            r = await self._act(a, timeout=420)
            if not r.get("ok") and "pole" in str(s["item"]) and "isn't wired" in str(r.get("msg")):
                r = await self._bridge_line(fr, to, s["item"], r)
            return r
        # one route goes ~250 tiles at most: lay it in legs, each continuing from the end of the last
        n = math.ceil(dist / 180)
        start, msgs = fr, []
        for k in range(1, n + 1):
            end = to if k == n else await self._free_tile(fr[0] + (to[0] - fr[0]) * k / n,
                                                          fr[1] + (to[1] - fr[1]) * k / n)
            leg = {**a, "from": list(start), "to": list(end)}
            if a.get("from_fluid") or a.get("to_fluid"):
                leg["fluid"] = a.get("from_fluid") or a.get("to_fluid")  # every leg keeps clear of other fluids
                if k > 1:
                    leg.pop("from_fluid", None)  # only the first leg starts at the machine's port
            if k < n:
                leg.pop("end_direction", None)
                leg.pop("join", None)
                leg.pop("to_fluid", None)
            r = await self._act(leg, timeout=420)
            if not r.get("ok") and "pole" in str(s["item"]) and "isn't wired" in str(r.get("msg")):
                r = await self._bridge_line(start, end, s["item"], r)
            if not r.get("ok"):
                return {"ok": False, "msg": f"long line, leg {k}/{n} from {start[0]:g},{start[1]:g} to {end[0]:g},"
                                            f"{end[1]:g} failed: {r.get('msg')}" + (f" (legs before it are laid; "
                                            f"it ends at {start[0]:g},{start[1]:g})" if k > 1 else "")}
            msgs.append(str(r.get("msg") or "")[:160])
            start = end
        return {"ok": True, "msg": f"laid it in {n} legs: " + " | ".join(msgs)}

    async def _free_tile(self, x: float, y: float) -> list[float]:
        """The free land tile nearest x,y (a waypoint for a long line)."""
        cx, cy = math.floor(x), math.floor(y)
        try:
            sc = await self.g.scan(center=(cx + 0.5, cy + 0.5), radius=6, tiles=True)
        except Exception:  # noqa: BLE001
            return [cx + 0.5, cy + 0.5]
        from .world import World
        w = World(sc)
        blocked = {tuple(map(int, b)) for b in (sc.get("blocked") or [])} | set(w.tile)
        for r in range(0, 6):
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    if max(abs(dx), abs(dy)) == r and (cx + dx, cy + dy) not in blocked:
                        return [cx + dx + 0.5, cy + dy + 0.5]
        return [cx + 0.5, cy + 0.5]

    async def _do_fetch(self, s):
        return await self._act({"op": "fetch", "item": s["item"], "count": int(s.get("count", 1))}, timeout=300)

    async def _do_craft(self, s):
        """Have `count` more of an item: the mod's fetch takes it from storage or hand-crafts it, fetching the
        ingredients from storage first when they aren't carried."""
        inv = await self.refresh_inventory()
        item, n = s["recipe"], int(s.get("count", 1))
        return await self._act({"op": "fetch", "item": item, "count": inv.get(item, 0) + n}, timeout=400)

    async def _do_mine(self, s):
        # by the item it gives ("wood" is mined from trees, "raw-wood" too) or by the entity's name
        name = s.get("name") or s.get("item")
        item = name if name in MINEABLE else None
        name = {"raw-wood": "tree"}.get(name, MINEABLE.get(name, name))
        n = int(s.get("count", 10))
        if item and item != "wood" and not s.get("by_hand"):
            # what a drill already dropped into a chest nearby is quicker to pick up than to mine (a bootstrap's coal
            # drill fills its chest while the character mines by hand)
            try:
                st = await self.g.call("stored", agent=self.g.name, item=item, radius=120)
                tot = int(st.get("in_storage_total") or 0)
                if tot >= 5:
                    have0 = (await self.refresh_inventory()).get(item, 0)
                    await self._act({"op": "fetch", "item": item, "count": have0 + min(n, tot)}, timeout=180)
                    got = (await self.refresh_inventory()).get(item, 0) - have0
                    if got >= n:
                        return {"ok": True, "msg": f"took {got} {item} from storage nearby (no mining needed)"}
                    if got > 0:
                        r = await self._act({"op": "mine", "name": name, "count": n - got},
                                            timeout=max(400, 6 * (n - got) + 60))
                        if r.get("ok"):
                            r["msg"] = f"took {got} {item} from storage nearby; " + str(r.get("msg"))
                        return r
            except Exception:  # noqa: BLE001
                pass
        return await self._act({"op": "mine", "name": name, "count": n}, timeout=max(400, 6 * n + 60))

    async def _do_launch(self, s):
        """Launch the rocket in the silo at x,y once it's ready (walks there first)."""
        p = _xy(s)
        mv = await self._act({"op": "move", "x": p[0], "y": p[1], "radius": 6})
        if not mv.get("ok"):
            return mv
        try:
            r = await self.g.call("launch", agent=self.g.name, x=p[0], y=p[1])
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "msg": str(e)}
        return {"ok": True, "msg": f"launched the rocket ({r.get('rockets')} launched so far)"}

    async def _do_mine_at(self, s):
        p = _xy(s)
        a = {"op": "mine", "x": p[0], "y": p[1]}
        if s.get("name"):
            a["name"] = s["name"]  # only that, not a neighbour when the coordinates are a tile off
        if s.get("force_pickup"):
            a["force_pickup"] = True
        return await self._act(a)

    async def _do_insert(self, s):
        p = _xy(s)
        n = int(s.get("count", 0) or 0)
        r = await self.ensure(s["item"], max(1, n), grab=not s.get("no_grab"))
        if not r.get("ok"):
            return {"ok": False, "msg": f"couldn't get {s['item']}: {r.get('msg')}", "missing": {s["item"]: max(1, n)},
                    "unobtainable": True}
        a = {"op": "insert", "x": p[0], "y": p[1], "item": s["item"]}
        if n:
            a["count"] = n
        r = await self._act(a)
        if not r.get("ok") and "fuel slot already holds" in str(r.get("msg")):
            return {"ok": True, "msg": "its fuel slot is already full (" + str(r.get("msg")).split("already holds ")[-1]}
        return r

    async def _do_take(self, s):
        p = _xy(s)
        a = {"op": "take", "x": p[0], "y": p[1]}
        if s.get("item"):
            a["item"] = s["item"]
        if s.get("count"):
            a["count"] = int(s["count"])
        return await self._act(a)

    async def _do_empty_chest(self, s):
        """Make room in a full chest: take part of it, enough that it doesn't fill again within minutes (100 of each
        item was gone in 3 minutes in x-sweep), without filling the pocket with junk like stone."""
        await self.tidy(low=8, want=12)  # 400 plates is 4 slots: a full pocket can't take any (489 failed fixes)
        return await self._do_take({"x": s["x"], "y": s["y"], "count": int(s.get("count", 400))})

    async def _do_refuel(self, s):
        p = _xy(s)
        inv = await self.refresh_inventory()
        n = int(s.get("count", 20))
        fuel = s.get("fuel") or next((f for f in FUELS if inv.get(f, 0) >= 5), None) or "coal"
        if inv.get(fuel, 0) < min(n, 5) or (s.get("stock") and inv.get(fuel, 0) < int(s["stock"]) // 2):
            # stock fuel for several machines at once (the plan's remaining refuels, within reason): storage, then
            # mining coal, then wood from trees
            want = max(n, int(s.get("stock") or min(max(40, self.fuel_ahead), 120)))
            r = await self.ensure(fuel, want) if fuel != "coal" else {"ok": False}
            if not r.get("ok"):
                r = await self.ensure("coal", want)
                fuel = "coal"
            if not r.get("ok"):
                r = await self._act({"op": "mine", "name": "coal", "count": want}, timeout=120 + 3 * want)
            if not r.get("ok"):
                inv = await self.refresh_inventory()
                fuel = "wood"
                if inv.get("wood", 0) < 10:
                    r = await self.ensure("wood", want)
                    if not r.get("ok"):
                        r = await self._act({"op": "mine", "name": "tree", "count": max(4, want // 4)}, timeout=400)
                inv = await self.refresh_inventory()
                if inv.get("wood", 0) <= 0:
                    return {"ok": False, "msg": f"no fuel: no coal anywhere and no wood ({r.get('msg')})",
                            "missing": {"coal": n}, "unobtainable": True}
        have = (await self.refresh_inventory()).get(fuel, 0)
        if fuel == "wood" and not s.get("count"):
            n = 50  # wood holds half what coal does: 20 keeps a stone furnace going only ~7 minutes
        r = await self._act({"op": "insert", "x": p[0], "y": p[1], "item": fuel, "count": max(1, min(n, have))})
        if not r.get("ok") and "fuel slot already holds" in str(r.get("msg")):
            # full of fuel already: that's what refuelling is for
            return {"ok": True, "msg": "its fuel slot is already full (" + str(r.get("msg")).split("already holds ")[-1]}
        return r

    async def _do_power(self, s):
        """Make sure every electric machine within `radius` (default 6) of x,y is on a grid that has generators:
        bridge from the nearest live pole to the closest unpowered pole (or machine), rescan, repeat."""
        p = _xy(s)
        rad = float(s.get("radius", 6))
        item = s.get("item", "small-electric-pole")
        msgs = []
        prev_off, stuck, stocked = None, 0, False
        for rnd in range(10):
            sc = await self.g.scan(center=p, radius=int(max(rad + 40, 48)))
            ents = [e for e in (sc.get("ents") or []) if not e.get("ghost")]
            live = {g["id"] for g in (sc.get("grids") or []) if isinstance(g, dict) and grid_live(g)}
            near = [e for e in ents if abs(e["x"] - p[0]) <= rad + 1.5 and abs(e["y"] - p[1]) <= rad + 1.5]
            off = [e for e in near if e.get("t") != "electric-pole" and "net" in e and e.get("net") not in live]
            off += [e for e in near if e.get("s") == "not_plugged_in_electric_network" and e not in off]
            off += [e for e in near if e.get("t") != "electric-pole" and str(e.get("pw", "")).startswith("no power")
                    and e not in off]
            if not off:
                return {"ok": True, "msg": ("everything there is powered" if not msgs else "; ".join(msgs[-3:]))}
            if prev_off is not None and len(off) >= prev_off:
                stuck += 1
                if stuck >= 2:
                    break
            else:
                stuck = 0
            prev_off = len(off)
            live_poles = [e for e in ents if e.get("t") == "electric-pole" and e.get("net") in live]
            if not live_poles:
                # the line ends at a pole of what needs power (the point itself may be a belt or a machine)
                mine = [e for e in near if e.get("t") == "electric-pole"]
                end = min(mine, key=lambda e: (e["x"] - p[0]) ** 2 + (e["y"] - p[1]) ** 2, default=None)
                return await self._long_power((end["x"], end["y"]) if end else p, s)
            dead_poles = [e for e in ents if e.get("t") == "electric-pole" and e.get("net") not in live
                          and any(abs(e["x"] - m["x"]) <= 4 and abs(e["y"] - m["y"]) <= 4 for m in off)]
            targets = dead_poles or off

            def d2(a, b):
                return (a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2
            best = min(((lp, t) for lp in live_poles for t in targets), key=lambda pr: d2(*pr))
            src = best[0]
            if s.get("from") and rnd == 0:
                f = s["from"]
                cand = [lp for lp in live_poles if abs(lp["x"] - f[0]) <= 1 and abs(lp["y"] - f[1]) <= 1]
                if cand:
                    src = cand[0]
            tgt = best[1]
            if not stocked:
                # poles in hand first, the full way (storage, crafting, wood from trees): the game's line routing
                # only fetches from storage; medium poles will do if small ones can't be had
                stocked = True
                got = await self.ensure(item, 8)
                if not got.get("ok") and not s.get("item"):
                    if (await self.refresh_inventory()).get("medium-electric-pole", 0) >= 3:
                        item = "medium-electric-pole"
            r = await self._act({"op": "connect", "item": item, "from": [src["x"], src["y"]],
                                 "to": [tgt["x"], tgt["y"]]}, timeout=420)
            msgs.append(str(r.get("msg"))[:160])
        return {"ok": False, "msg": f"{prev_off} things near {p[0]:g},{p[1]:g} still unpowered: " + " | ".join(msgs[-2:])}

    async def _long_power(self, p, s) -> dict:
        """No live pole nearby: find the nearest pole on a generating grid within 300 tiles and run a line from it in
        legs of at most ~180 tiles (medium poles when there are any, else small)."""
        src = (await self.g.call("query", what="live_pole", x=p[0], y=p[1], radius=300)).get("pole")
        if not src:
            return {"ok": False, "msg": "no powered pole within 300 tiles to run power from"}
        inv = await self.refresh_inventory()
        mats = {"m": ((await self.g.call("query", what="materials")).get("materials") or {}).get(
            "medium-electric-pole", 0)}
        item = s.get("item") or ("medium-electric-pole" if (inv.get("medium-electric-pole", 0) +
                                                            (mats.get("m") or 0)) >= 10 else "small-electric-pole")
        import math as _m
        dist = _m.hypot(p[0] - src[0], p[1] - src[1])
        legs = max(1, int(_m.ceil(dist / 180)))
        cur = [float(src[0]), float(src[1])]
        msgs = []
        for i in range(1, legs + 1):
            tgt = [src[0] + (p[0] - src[0]) * i / legs, src[1] + (p[1] - src[1]) * i / legs]
            r = await self._act({"op": "connect", "item": item, "from": cur, "to": tgt}, timeout=900)
            msgs.append(str(r.get("msg"))[:120])
            if not r.get("ok") and "isn't wired" in str(r.get("msg")):
                # the poles are down but a hop didn't wire (something stood where it would have gone): bridge the gap
                r = await self._bridge_line(cur, tgt, item, r)
            if not r.get("ok") and "no free spot" in str(r.get("msg")):
                # water, cliffs or a base in the way: go round by a waypoint off to one side of the straight line
                r = await self._pole_detour(cur, tgt, item, r)
            if not r.get("ok") and "already connected" not in str(r.get("msg")):
                return {"ok": False, "msg": f"long power line leg {i}/{legs} failed: {r.get('msg')}"}
            cur = tgt
        return {"ok": True, "msg": f"ran {item} {dist:.0f} tiles from the grid pole at {src[0]:g},{src[1]:g} in "
                                   f"{legs} leg(s)"}

    async def _pole_detour(self, a, b, item: str, first: dict) -> dict:
        """A pole line from a to b blocked on the way: try a waypoint 16 or 32 tiles to either side of the midpoint,
        a -> waypoint -> b (the poles of a failed try stay; the next try starts from a again)."""
        dx, dy = b[0] - a[0], b[1] - a[1]
        n = math.hypot(dx, dy) or 1
        px, py = -dy / n, dx / n
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        for off in (16, -16, 32, -32):
            wp = [round(mx + px * off) + 0.5, round(my + py * off) + 0.5]
            r1 = await self._act({"op": "connect", "item": item, "from": a, "to": wp}, timeout=600)
            if not r1.get("ok"):
                continue
            r2 = await self._act({"op": "connect", "item": item, "from": wp, "to": b}, timeout=600)
            if r2.get("ok") or "already connected" in str(r2.get("msg")):
                return {"ok": True, "msg": f"went round by {wp[0]:g},{wp[1]:g}: {str(r2.get('msg'))[:100]}"}
        return first

    async def _bridge_line(self, a, b, item: str, first: dict) -> dict:
        """A pole line from a (on a grid) toward b is laid but broken somewhere: join the pole nearest the break on
        the stranded side to the nearest pole on a's grid with another short pole run, until b's end is on it."""
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        rad = int(min(96, math.hypot(b[0] - a[0], b[1] - a[1]) / 2 + 12))
        for _ in range(3):
            sc = await self.g.scan(center=mid, radius=rad)
            poles = [e for e in sc.get("ents") or [] if e.get("t") == "electric-pole" and not e.get("ghost")]
            src = min(poles, key=lambda e: math.hypot(e["x"] - a[0], e["y"] - a[1]), default=None)
            if not src or src.get("net") is None:
                return first
            on = [e for e in poles if e.get("net") == src["net"]]
            off = [e for e in poles if e.get("net") != src["net"]
                   and abs(e["x"] - mid[0]) <= rad and abs(e["y"] - mid[1]) <= rad]
            end = min(poles, key=lambda e: math.hypot(e["x"] - b[0], e["y"] - b[1]))
            if end.get("net") == src["net"]:
                return {"ok": True, "msg": f"{first.get('msg')}; bridged the break"}
            if not off:
                return first
            x, y = min(((p, q) for p in on for q in off), key=lambda pq: math.hypot(pq[0]["x"] - pq[1]["x"],
                                                                                  pq[0]["y"] - pq[1]["y"]))
            r = await self._act({"op": "connect", "item": item, "from": [x["x"], x["y"]], "to": [y["x"], y["y"]]},
                                timeout=300)
            if not r.get("ok") and "already connected" not in str(r.get("msg")):
                return {"ok": False, "msg": f"{first.get('msg')}; couldn't bridge the break between "
                                            f"{x['x']:g},{x['y']:g} and {y['x']:g},{y['y']:g}: {r.get('msg')}"}
        return first

    async def _do_upgrade(self, s):
        """Swap buildings for a better tier in place, the way a player clicks the new one over the old (it keeps its
        direction, recipe and the items on a belt): everything upgradable within `radius` of x,y, or one belt line
        (line=[x,y], a tile of it). `into` names the new tier; `only` limits it to one old name."""
        mp = upgrade_map(str(s.get("into") or ""))
        only = s.get("only")
        if isinstance(only, str):
            only = [only]
        if isinstance(only, list) and only:  # (other values, like only=true for "just this one", mean no filter)
            mp = {k: v for k, v in mp.items() if k in only}
        if not mp:
            return {"ok": False, "msg": f"nothing upgrades into {s.get('into')!r} (try e.g. fast-transport-belt, "
                                        "assembling-machine-2, steel-furnace, fast-inserter)"}
        from .world import World
        if s.get("line"):
            lx, ly = float(s["line"][0]), float(s["line"][1])
            sc = await self.g.scan(center=(lx, ly), radius=64)
            w = World(sc)
            e0 = w.at(lx, ly)
            ln = w.line_of.get(e0["u"]) if e0 else None
            if not ln:
                return {"ok": False, "msg": f"no belt line at {lx:g},{ly:g}"}
            ents = [w.ents[u] for u in ln.belts if u in w.ents]
            # an underground's partner and splitters on the line belong to it too
            pairs = {e.get("pair") for e in ents if e.get("pair")}
            ents += [e for e in w.ents.values() if e["u"] in pairs and e not in ents]
            first, last = w.ents.get(ln.belts[0]), w.ents.get(ln.belts[-1])
            edge = bool(first and last) and (w.off_view(*w._behind(first)) or w.off_view(*w._ahead(last)))
        elif s.get("cluster"):
            # "the gear assemblers at [gps]": the upgradable thing nearest x,y and every one of the same kind next
            # to it, and next to those (within 6 tiles), whatever the radius
            p = _xy(s)
            w = World(await self.g.scan(center=p, radius=40))
            cand = [e for e in w.ents.values() if e.get("n") in mp and e["u"] > 0]
            seed = min(cand, key=lambda e: (e["x"] - p[0]) ** 2 + (e["y"] - p[1]) ** 2, default=None)
            ents = []
            if seed and abs(seed["x"] - p[0]) <= 8 and abs(seed["y"] - p[1]) <= 8:
                ents, todo = [seed], [seed]
                while todo:
                    a = todo.pop()
                    for e in cand:
                        if e not in ents and e["n"] == seed["n"] and abs(e["x"] - a["x"]) <= 6 and abs(e["y"] - a["y"]) <= 6:
                            ents.append(e)
                            todo.append(e)
            edge = False
        else:
            p = _xy(s)
            rad = min(float(s.get("radius", 8)), 48)
            sc = await self.g.scan(center=p, radius=int(rad + 3))
            w = World(sc)
            ents = [e for e in w.ents.values() if abs(e["x"] - p[0]) <= rad and abs(e["y"] - p[1]) <= rad]
            edge = False
        todo = [(e, mp[e["n"]]) for e in ents if e.get("n") in mp and e["u"] > 0]
        if not todo:
            return {"ok": True, "msg": "nothing there to upgrade (already at that tier or none found)"}
        need: dict = {}
        for _, new in todo:
            need[new] = need.get(new, 0) + 1
        fails = await self.stock(need)
        inv = await self.refresh_inventory()
        me = await self.g.me()
        pos = tuple(me.get("position") or (0, 0))
        order, left = [], list(todo)
        while left:  # nearest first, so the walk goes along the line
            k = min(range(len(left)), key=lambda i: (left[i][0]["x"] - pos[0]) ** 2 + (left[i][0]["y"] - pos[1]) ** 2)
            e, new = left.pop(k)
            order.append((e, new))
            pos = (e["x"], e["y"])
        done, failed, skipped = 0, [], 0
        for e, new in order:
            if inv.get(new, 0) <= 0:
                skipped += 1
                continue
            a = {"op": "place", "name": new, "x": e["x"], "y": e["y"]}
            if e.get("d"):
                a["direction"] = e["d"]
            if e.get("ug"):
                a["type"] = e["ug"]
            r = await self._act(a)
            if r.get("ok"):
                done += 1
                inv[new] = inv.get(new, 0) - 1
            else:
                failed.append(f"{e['n']} at {e['x']:g},{e['y']:g}: {str(r.get('msg'))[:100]}")
        msg = f"upgraded {done} of {len(todo)}"
        if skipped:
            msg += f"; {skipped} not done, no items: " + "; ".join(f"{k}: {v}" for k, v in fails.items())[:300]
        if failed:
            msg += f"; {len(failed)} failed: " + "; ".join(failed[:3])
        if edge:
            msg += "; the line runs on past what I looked at (upgrade from further along to do the rest)"
        return {"ok": done == len(todo), "msg": msg}

    async def _do_clear(self, s):
        """Pick up buildings in an area, nearest first, into the inventory (what's in them comes along): everything
        of ours within `radius` (default 6, max 24) of x,y, or only the names in `only`. trees=true clears the trees
        and rocks there instead (walking to each, like a player)."""
        from .world import World
        p = _xy(s)
        rad = min(float(s.get("radius", 6)), 24)
        only = s.get("only")
        if isinstance(only, str):
            only = [only]
        if s.get("trees"):
            q = await self.g.call("query", what="clutter", x=p[0], y=p[1], radius=rad)
            ents = [{"n": n, "x": x, "y": y} for n, x, y in (q.get("clutter") or [])]
        elif s.get("line"):
            # exactly one belt line (with its underground partners), nothing else around it
            lx, ly = float(s["line"][0]), float(s["line"][1])
            w = World(await self.g.scan(center=(lx, ly), radius=48))
            e0 = w.at(lx, ly)
            ln = w.line_of.get(e0["u"]) if e0 else None
            if not ln:
                return {"ok": False, "msg": f"no belt line at {lx:g},{ly:g}"}
            ents = [w.ents[u] for u in ln.belts if u in w.ents]
            pairs = {e.get("pair") for e in ents if e.get("pair")}
            ents += [e for e in w.ents.values() if e["u"] in pairs and e not in ents]
        else:
            sc = await self.g.scan(center=p, radius=int(rad + 3))
            w = World(sc)
            ents = [e for e in w.ents.values() if e["u"] > 0 and abs(e["x"] - p[0]) <= rad
                    and abs(e["y"] - p[1]) <= rad and (not only or e.get("n") in only)]
        if not ents:
            return {"ok": True, "msg": "nothing there to pick up"}
        me = await self.g.me()
        pos = tuple(me.get("position") or p)
        done, failed = 0, []
        while ents:
            k = min(range(len(ents)), key=lambda i: (ents[i]["x"] - pos[0]) ** 2 + (ents[i]["y"] - pos[1]) ** 2)
            e = ents.pop(k)
            # by name: with only a position, a tree already gone (the ghost builder clears trees in its way) left
            # whatever stood next to it to be picked up instead, belts included (p2: "picked up belts during tree
            # clear", orphaned undergrounds all over its base)
            r = await self._act({"op": "mine", "x": e["x"], "y": e["y"], "name": e["n"]}, timeout=60)
            if not r.get("ok") and "nothing minable" in str(r.get("msg")):
                r = {"ok": True}  # already gone
            if r.get("ok"):
                done += 1
            else:
                failed.append(f"{e['n']} at {e['x']:g},{e['y']:g}: {str(r.get('msg'))[:90]}")
            pos = (e["x"], e["y"])
        msg = (f"cleared {done} of {done + len(failed)} trees/rocks" if s.get("trees")
               else f"picked up {done} of {done + len(failed)}")
        if failed:
            msg += f"; {len(failed)} failed: " + "; ".join(failed[:3])
        return {"ok": not failed, "msg": msg}

    async def _do_purge(self, s):
        """Take every `item` off the belts around x,y (junk a wrong recipe put on a belt); the belts stay."""
        p = _xy(s)
        r = await self._act({"op": "grab", "item": s["item"], "count": int(s.get("count", 2000)), "x": p[0],
                             "y": p[1]}, timeout=300)
        if not r.get("ok") and "no belt" in str(r.get("msg")):
            return {"ok": True, "msg": f"no {s['item']} on the belts there"}
        return r

    async def _do_wait_research(self, s):
        """Wait until a tech is researched, so later steps can use what it unlocks (p3: "place electric drills once
        their research is done" had no way to say it, so the order ended half done). Queues the tech if it isn't
        researching or queued. It only waits: the labs need their packs. Up to `minutes` (default 15, at most 30)."""
        tech = s.get("tech")
        if not tech:
            return {"ok": False, "msg": "wait_research needs tech"}
        mins = min(float(s.get("minutes", 15)), 30)
        t0 = time.time()
        queued = False
        while True:
            q = await self.g.call("query", what="tech", name=tech)
            if q.get("error"):
                return {"ok": False, "msg": q["error"]}
            if q.get("researched"):
                if isinstance(self.recipes, dict):
                    self.recipes.update(q.get("unlocks") or {})  # usable now: crafting checks see them
                return {"ok": True, "msg": f"{tech} is researched (waited {time.time() - t0:.0f} s)"}
            if not q.get("current") and not q.get("queued") and not queued:
                queued = True
                r = await self._do_research({"tech": tech})
                if not r.get("ok"):
                    return {"ok": False, "msg": f"{tech} isn't researching and couldn't be queued: {r.get('msg')}"}
            if self.abort and self.abort():
                return {"ok": False, "msg": "cancelled", "cancelled": True}
            if time.time() - t0 > mins * 60:
                return {"ok": False, "msg": f"{tech} still at {100 * float(q.get('progress') or 0):.0f}% after "
                                           f"{mins:.0f} min: the labs need packs (or more labs)"}
            await asyncio.sleep(10)

    async def _do_research(self, s):
        """Queue a tech. tech="cheapest" (or a trigger/finished tech that fails) picks the cheapest lab tech whose
        packs are all in `packs` (default red and green)."""
        tech = s.get("tech") or "cheapest"
        if tech != "cheapest":
            r = await self._act({"op": "research", "tech": tech, **({"first": True} if s.get("first") else {}),
                                 **({"remove": True} if s.get("remove") else {})})
            if r.get("ok") or not s.get("fallback", True):
                return r
            first_msg = r.get("msg")
        else:
            first_msg = None
        t = await self.g.call("techs", agent=self.g.name)
        packs = set(s.get("packs") or ["automation-science-pack", "logistic-science-pack"])
        cands = [x for x in (t.get("available") or []) if x.get("units") and set(x.get("packs") or []) <= packs]
        cands.sort(key=lambda x: (x["units"] * len(x.get("packs") or []), x["name"]))
        for c in cands[:3]:
            r = await self._act({"op": "research", "tech": c["name"]})
            if r.get("ok"):
                r["msg"] = (f"{tech}: {first_msg}; queued {c['name']} instead" if first_msg else
                            f"queued {c['name']} ({c['units']} units)")
                return r
        return {"ok": False, "msg": first_msg or "no lab tech available with those packs"}

    async def _do_wait(self, s):
        await asyncio.sleep(min(float(s.get("seconds", 5)), 120))
        return {"ok": True, "msg": f"waited {s.get('seconds', 5)}s"}

    async def _do_say(self, s):
        await self.g.say(str(s.get("text", "")))
        return {"ok": True, "msg": "said"}

    async def _do_move(self, s):
        p = _xy(s)
        return await self._act({"op": "move", "x": p[0], "y": p[1]}, timeout=300)

    async def _do_follow(self, s):
        """Stay near a player (seconds, default 300); the step returns at once and the character keeps following."""
        a = {"op": "follow", "player": s.get("player"), "distance": s.get("distance", 3),
             "seconds": s.get("seconds", 300)}
        try:
            await self.g.act([a])
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "msg": repr(e)}
        return {"ok": True, "msg": f"following {s.get('player')}"}

    async def _do_configure(self, s):
        a = {"op": "configure", **{k: v for k, v in s.items() if k != "do"}}
        return await self._act(a)

    async def _do_limit(self, s):
        return await self._act({"op": "limit", "x": s["x"], "y": s["y"], "slots": s.get("slots")})

    # ------------------------------------------------------------------ building plans
    async def _do_ghosts(self, s):
        ents = []
        for e in expand(s.get("entities") or []):
            q = {"name": e["name"], "x": float(e["x"]), "y": float(e["y"])}
            if e.get("direction"):
                q["direction"] = e["direction"]
            if e.get("recipe"):
                q["recipe"] = e["recipe"]
            if e.get("type") in ("input", "output"):
                q["type"] = e["type"]
            ents.append(q)
        if not ents:
            return {"ok": False, "msg": "ghosts needs entities"}
        xs = [e["x"] for e in ents]
        ys = [e["y"] for e in ents]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        rad = ((max(xs) - min(xs)) ** 2 + (max(ys) - min(ys)) ** 2) ** 0.5 / 2 + 3
        if s.get("_laid"):  # a retry: the ghosts are already there; try the ones that couldn't go again, then build
            todo = s.get("_unplaced") or []
            if todo:
                r = await self._act({"op": "blueprint", "entities": todo})
                s["_unplaced"] = unplaced(todo, r)
            return ghost_result(await self._do_build_ghosts({"x": cx, "y": cy, "radius": rad}), s)
        r = await self._act({"op": "blueprint", "entities": ents})
        if not r.get("ok"):
            return r
        s["_laid"] = True
        s["_unplaced"] = unplaced(ents, r)
        placed = r.get("ghosts")
        await self.stock(r.get("needs") or {})
        b = await self._do_build_ghosts({"x": cx, "y": cy, "radius": rad})
        for t in turns(r):  # same piece, other direction: turn it, as placing over it would
            tr = await self._do_rotate(t)
            if not tr.get("ok"):
                s["_unplaced"].append({"name": "turn", "x": t["x"], "y": t["y"], "_why": tr.get("msg")})
        ex = int(r.get("existing") or 0)
        b["msg"] = f"planned {placed} of {len(ents)}" + (f" ({ex} already built there)" if ex else "") + "; " + \
            (b.get("msg") or "")
        return ghost_result(b, s)

    async def row_layout(self, s: dict):
        """The entities of a row step (needs the belt's direction from the game; picks a free side if none given)."""
        from .rowgen import DIRS, row_entities
        from .world import World
        b = s.get("belt")
        sc = await self.g.scan(center=(float(b[0]), float(b[1])), radius=int(10 + 6 * int(s.get("count", 1))))
        w = World(sc)
        e = w.at(float(b[0]), float(b[1]))
        if not e or e.get("t") not in ("transport-belt", "underground-belt", "splitter") or e.get("d") not in DIRS:
            raise ValueError(f"no belt at {b[0]},{b[1]} to build the row off")
        d = e["d"]
        sides = [x for x in DIRS if DIRS[x][0] * DIRS[d][0] + DIRS[x][1] * DIRS[d][1] == 0]
        side = s.get("side")
        cands = [side] if side else sides
        best = None
        for sd in cands:
            ents, info = row_entities((e["x"], e["y"]), d, sd, s.get("machine", "assembling-machine-1"),
                                      s.get("recipe"), int(s.get("count", 1)), bool(s.get("second_belt")),
                                      s.get("output", "chest"), s.get("inserter", "inserter"), int(s.get("offset", 0)))
            blocked = sum(1 for x in ents if w.at(x["x"], x["y"]) is not None)
            if best is None or blocked < best[0]:
                best = (blocked, ents, info, sd)
        # the input belt runs the row's whole length: a tap's split-off belt (or any line) that ends early is carried
        # on downstream over free ground, up to the first tile something else stands on
        from .rowgen import extend_input
        ext = extend_input((e["x"], e["y"]), d, int(best[2].get("length", 0)) + int(s.get("offset", 0)), w.at,
                           e.get("n") if "transport-belt" in str(e.get("n")) else "transport-belt")
        if ext:
            best[2]["belt_extended"] = len(ext)
        return best[1] + ext, best[2], best[3], best[0]

    async def _do_row(self, s):
        """Machines in a row along an existing belt (see jev/rowgen.py), then powered from the grid."""
        try:
            ents, info, side, blocked = await self.row_layout(s)
        except ValueError as e:
            return {"ok": False, "msg": str(e)}
        r = await self._do_ghosts({"entities": ents})
        if not r.get("ok"):
            return r
        xs, ys = [e["x"] for e in ents], [e["y"] for e in ents]
        pr = await self._do_power({"x": (min(xs) + max(xs)) / 2, "y": (min(ys) + max(ys)) / 2,
                                   "radius": max(max(xs) - min(xs), max(ys) - min(ys)) / 2 + 2})
        msg = (f"row of {info['machines']} {s.get('machine', 'assembling-machine-1')} on the {side} side: "
               f"{r.get('msg')}; power: {pr.get('msg')}")
        if info.get("belt_extended"):
            msg += f"; input belt carried on {info['belt_extended']} tiles to cover the row"
        if info.get("output_belt_end"):
            msg += f"; output belt ends at {info['output_belt_end'][0]:g},{info['output_belt_end'][1]:g}"
        return {"ok": bool(pr.get("ok")), "msg": msg, "info": info}

    async def _do_block(self, s):
        """A built-in, game-tested design (jev/blueprints) placed with its rotated top-left corner at x,y (or with
        anchor=<entity name> at x,y), laid as ghosts and built."""
        from . import blueprints as bp
        try:
            ents = bp.stamp_entities(s["name"], float(s["x"]), float(s["y"]), s.get("rotation", 0), s.get("anchor"))
        except KeyError as e:
            return {"ok": False, "msg": str(e)}
        r = await self._do_ghosts({"entities": ents})
        r["msg"] = f"block {s['name']}: " + str(r.get("msg"))
        return r

    async def _do_design(self, s):
        """A saved design (library) built at anchor x,y."""
        from .library import place_design
        ents = place_design(s.get("name", ""), s["x"], s["y"])
        if ents is None:
            return {"ok": False, "msg": f"no saved design {s.get('name')!r}"}
        return await self._do_ghosts({"entities": ents})

    async def _do_merge_lanes(self, s):
        """One belt carrying two items, one per lane: the `left` belt side-loads the merged belt's left lane and the
        `right` belt its right lane (left/right as seen facing `direction`). at=[x,y] is the first tile of the merged
        belt; to=[x,y] optionally continues it there. left/right = the last belt tile of each feeding line."""
        DV = {"north": (0, -1), "east": (1, 0), "south": (0, 1), "west": (-1, 0)}
        LEFT = {"east": "north", "north": "west", "west": "south", "south": "east"}
        d = s.get("direction")
        if d not in DV:
            return {"ok": False, "msg": "merge_lanes needs direction north/east/south/west"}
        ax, ay = float(s["at"][0]), float(s["at"][1])
        ax, ay = int(ax // 1) + 0.5, int(ay // 1) + 0.5
        lx, ly = DV[LEFT[d]]
        left_tile, right_tile = [ax + lx, ay + ly], [ax - lx, ay - ly]
        into_from_left = {(0, -1): "south", (0, 1): "north", (-1, 0): "east", (1, 0): "west"}[(lx, ly)]
        into_from_right = {"south": "north", "north": "south", "east": "west", "west": "east"}[into_from_left]
        msgs = []
        # feeds first, each ending beside the merge tile and pointing at it; the merge tile last, so nothing ever runs
        # into it from behind (that would put both items on both lanes)
        for side, src, tile, face in (("left", s.get("left"), left_tile, into_from_left),
                                      ("right", s.get("right"), right_tile, into_from_right)):
            if not src:
                continue
            r = await self._act({"op": "connect", "item": s.get("item", "transport-belt"), "from": list(src),
                                 "to": tile, "end_direction": face}, timeout=420)
            msgs.append(f"{side}: {str(r.get('msg'))[:140]}")
            if not r.get("ok"):
                return {"ok": False, "msg": "; ".join(msgs)}
            # the last piece must point into the merge tile from the side
            await self._act({"op": "rotate", "x": tile[0], "y": tile[1], "direction": face})
        r = await self._do_place({"name": s.get("item", "transport-belt"), "x": ax, "y": ay, "direction": d})
        if not r.get("ok"):
            return {"ok": False, "msg": f"merge tile: {r.get('msg')}; " + "; ".join(msgs)}
        if s.get("to"):
            r = await self._act({"op": "connect", "item": s.get("item", "transport-belt"),
                                 "from": [ax, ay], "to": list(s["to"])}, timeout=420)
            msgs.append(f"onward: {str(r.get('msg'))[:140]}")
            if not r.get("ok"):
                return {"ok": False, "msg": "; ".join(msgs)}
        return {"ok": True, "msg": "; ".join(msgs) or "merged"}

    # ------------------------------------------------------------------ main bus (jev/busgen.py)
    async def buses(self) -> dict:
        from .busgen import Bus
        lay = (await self.g.call("layout")).get("layout") or {}
        out = {}
        for k, v in (lay.items() if isinstance(lay, dict) else []):
            if str(k).startswith("bus:"):
                try:
                    out[k[4:]] = Bus.from_dict(v)
                except (TypeError, ValueError):
                    pass
        return out

    async def _bus(self, name):
        bs = await self.buses()
        if name and name in bs:
            return bs[name]
        if not name and len(bs) == 1:
            return next(iter(bs.values()))
        raise ValueError(f"no bus named {name!r} (buses: {', '.join(bs) or 'none yet: lay one with a bus step'})")

    async def bus_flow(self, b) -> list[str]:
        """How full each lane of bus b is along its length (mod belt_items op), in words."""
        pts = b.sample_tiles()
        r = await self.g.call("belt_items", tiles=[[x, y] for _, _, (x, y) in pts])
        got = r.get("tiles") or []
        return b.flow_words([(i, a, int((got[k] or {}).get("n", 0)) if k < len(got) else 0)
                             for k, (i, a, _) in enumerate(pts)])

    async def _save_bus(self, b) -> None:
        await self.g.call("layout", key=f"bus:{b.name}", value=b.to_dict())

    async def _blocked(self, ents: list[dict], skip: set | None = None, same_belts: bool = False) -> list[str]:
        """What already stands on the tiles these entities need (other than tiles in skip). same_belts: a belt
        already there running the way the planned one would is no obstacle (a bus laid over existing lanes)."""
        from .lint import size_of, tiles_of
        from .world import World
        xs, ys = [e["x"] for e in ents], [e["y"] for e in ents]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        w = World(await self.g.scan(center=(cx, cy), radius=int(max(max(xs) - min(xs), max(ys) - min(ys)) / 2 + 4)))
        out = []
        for e in ents:
            fw, fh = size_of(e["name"], e.get("direction"))
            for t in tiles_of(e["x"], e["y"], fw, fh):
                if skip and t in skip:
                    continue
                o = w.at(t[0] + 0.5, t[1] + 0.5)
                if same_belts and o and "belt" in str(e["name"]) and o.get("t") == "transport-belt" and \
                        o.get("d") == e.get("direction"):
                    continue
                if o and o.get("t") not in ("resource",):
                    out.append(f"{o.get('n')} at {o['x']:g},{o['y']:g}")
        return sorted(set(out))

    @staticmethod
    def _bus_row(b, at) -> int:
        if isinstance(at, (list, tuple)) and len(at) == 2:
            return b.along_of(float(at[0]), float(at[1]))
        return int(at)

    async def _do_bus(self, s):
        """Lay a main bus (or lengthen one): straight lanes in pairs with free columns between, registered by name
        so taps and merges can find its lanes later."""
        from .busgen import Bus
        name = s.get("name") or "main"
        old = (await self.buses()).get(name)
        if old and ("x" not in s or (abs(float(s["x"]) - old.x) < 1 and abs(float(s["y"]) - old.y) < 1)):
            n = int(s.get("length") or old.length)
            if n <= old.length:
                return {"ok": True, "msg": old.describe()}
            ents = old.lay(old.length, n)
            r = await self._do_ghosts({"entities": ents}) if ents else {"ok": True, "msg": "no lanes in use"}
            if r.get("ok"):
                old.length = n
                await self._save_bus(old)
            return {"ok": bool(r.get("ok")), "msg": f"lengthened bus {name} to {n} rows: {r.get('msg')}. " +
                    old.describe()}
        if old:
            return {"ok": False, "msg": f"a bus named {name} already exists elsewhere ({old.describe()}); pick "
                                        "another name"}
        try:
            b = Bus(name=name, x=float(s["x"]), y=float(s["y"]), direction=s["direction"], side=s["side"],
                    lanes=[str(x) for x in s["lanes"]], length=int(s["length"]))
        except (KeyError, ValueError, TypeError) as e:
            return {"ok": False, "msg": f"bus needs name x y direction side lanes=[items] length: {e}"}
        if not b.lanes:
            return {"ok": False, "msg": "bus needs at least one lane"}
        ents = b.lay()
        if not ents:
            return {"ok": False, "msg": "every lane is spare: name at least one lane's item"}
        bl = await self._blocked(ents, same_belts=True)
        if bl:
            return {"ok": False, "msg": f"the bus's lanes are blocked by {', '.join(bl[:6])}" +
                    (f" and {len(bl) - 6} more" if len(bl) > 6 else "") + ": clear them or lay it elsewhere"}
        await self._save_bus(b)  # registered first: a half-built bus is still the bus
        r = await self._do_ghosts({"entities": ents})
        return {"ok": bool(r.get("ok")), "msg": f"laid bus {name}: {r.get('msg')}. {b.describe()}. Feed each "
                "lane by connecting its supply line to the lane's head."}

    async def _do_tap(self, s):
        """Take one lane off the bus: a splitter on the lane, the split-off belt under the later lanes to the bus's
        side and `run` tiles beyond it (default 3), ready for a row or a connect."""
        from .busgen import DIRS, SPARE
        try:
            b = await self._bus(s.get("bus"))
            i = b.lane_index(s.get("lane"))
            a = self._bus_row(b, s.get("at"))
        except (ValueError, TypeError) as e:
            return {"ok": False, "msg": f"tap: {e}"}
        why = b.rows_free(a)
        if why:
            return {"ok": False, "msg": f"tap: {why}"}
        if b.lanes[i] == SPARE:
            return {"ok": False, "msg": f"tap: lane {i} of bus {b.name} is spare (nothing on it yet)"}
        if a < b.start(i):
            return {"ok": False, "msg": f"tap: lane {i} starts at row {b.start(i)}; tap it further down"}
        ents, ex, mine = b.tap(i, a)
        nx, ny = DIRS[b.side]
        run = max(1, int(s.get("run", 3)))
        for k in range(run):
            ents.append({"name": "transport-belt", "x": ex["x"] + nx * k, "y": ex["y"] + ny * k,
                         "direction": b.side})
        end = [ex["x"] + nx * (run - 1), ex["y"] + ny * (run - 1)]
        import math as _m
        lane_tile = (_m.floor(mine[0][0]), _m.floor(mine[0][1]))
        bl = await self._blocked(ents, skip={lane_tile})
        if bl:
            return {"ok": False, "msg": f"tap: blocked by {', '.join(bl[:6])} (keep the bus's gap columns clear; or "
                                        "tap at another row)"}
        m = await self._do_mine_at({"x": mine[0][0], "y": mine[0][1]})
        if not m.get("ok") and "nothing" not in str(m.get("msg")):
            return {"ok": False, "msg": f"tap: couldn't pick up the lane's belt for the splitter: {m.get('msg')}"}
        r = await self._do_ghosts({"entities": ents})
        if r.get("ok"):
            b.joins.append({"kind": "tap", "lane": i, "at": a, "end": end})
            await self._save_bus(b)
        return {"ok": bool(r.get("ok")), "msg": f"tap on bus {b.name} lane {i} ({b.lanes[i]}) at row {a}: "
                f"{r.get('msg')}; the split-off belt ends at {end[0]:g},{end[1]:g} running {b.side}",
                "end": end}

    async def _do_bus_in(self, s):
        """Put a product onto the bus: its belt (from = the last tile of the line carrying it) comes in from the
        bus's side under the lanes and starts a lane at row at+1: a spare lane, or one already carrying it (then
        it side-loads that lane)."""
        from .busgen import SPARE
        try:
            b = await self._bus(s.get("bus"))
            a = self._bus_row(b, s.get("at"))
        except (ValueError, TypeError) as e:
            return {"ok": False, "msg": f"bus_in: {e}"}
        if not isinstance(s.get("from"), (list, tuple)):
            return {"ok": False, "msg": "bus_in needs from=[x,y], the last belt of the line carrying the product"}
        item = s.get("item") or s.get("lane")
        try:
            i = b.lane_index(item)
        except ValueError:
            spares = [k for k, it in enumerate(b.lanes) if it == SPARE]
            if not spares:
                return {"ok": False, "msg": f"bus_in: bus {b.name} has no {item} lane and no spare lane (lanes: "
                                            f"{', '.join(b.lanes)}); lay a second bus"}
            i = spares[0]
        why = b.rows_free(a)
        if why:
            return {"ok": False, "msg": f"bus_in: {why}"}
        ents, entry = b.merge(i, a)
        new_lane = b.lanes[i] == SPARE or b.start(i) > a + 1
        lane_from = a + 1
        lane_to = b.length if b.lanes[i] == SPARE else b.start(i)
        if new_lane:
            for k in range(lane_from, lane_to):
                x, y = b.at(k, b.u(i))
                ents.append({"name": "transport-belt", "x": x, "y": y, "direction": b.direction})
        bl = await self._blocked(ents)
        if bl:
            return {"ok": False, "msg": f"bus_in: blocked by {', '.join(bl[:6])} (or merge at another row)"}
        r = await self._do_ghosts({"entities": ents})
        if not r.get("ok"):
            return {"ok": False, "msg": f"bus_in: {r.get('msg')}"}
        if new_lane:
            b.lanes[i] = item or b.lanes[i]
            b.starts[str(i)] = lane_from
        b.joins.append({"kind": "merge", "lane": i, "at": a, "end": [entry["x"], entry["y"]]})
        await self._save_bus(b)
        c = await self._act({"op": "connect", "item": s.get("belt", "transport-belt"), "from": list(s["from"]),
                             "to": [entry["x"], entry["y"]]}, timeout=600)
        side_load = "" if new_lane else " (side-loading the lane, which already runs there: one side of it)"
        return {"ok": bool(c.get("ok")) or "already connected" in str(c.get("msg")),
                "msg": f"bus_in to bus {b.name} lane {i} ({b.lanes[i]}) at row {a}{side_load}: laid {r.get('msg')}; "
                       f"line in: {str(c.get('msg'))[:160]}"}

    async def _do_route(self, s):
        """Several separate belt lines at once (pairs of from/to tiles), laid by the router so they never mix:
        crossings go under with undergrounds. Then built as ghosts."""
        import math as _m
        from .router import Grid, solve
        from .world import World
        pairs = s.get("pairs") or []
        nets = []
        for i, pr in enumerate(pairs):
            try:
                f, t = pr["from"], pr["to"]
                nets.append((pr.get("name") or f"line{i + 1}", (_m.floor(float(f[0])), _m.floor(float(f[1]))),
                             (_m.floor(float(t[0])), _m.floor(float(t[1])))))
            except (KeyError, TypeError, ValueError, IndexError):
                return {"ok": False, "msg": f"route pair {i + 1} needs from=[x,y] and to=[x,y]"}
        if not nets:
            return {"ok": False, "msg": "route needs pairs=[{from, to}]"}
        xs = [p[0] for _, a, b in nets for p in (a, b)]
        ys = [p[1] for _, a, b in nets for p in (a, b)]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        margin = int(s.get("margin", 10))
        rad = int(max(max(xs) - min(xs), max(ys) - min(ys)) / 2 + margin + 2)
        sc = await self.g.scan(center=(cx, cy), radius=min(rad, 96), tiles=True)
        w = World(sc)
        blocked = {tuple(map(int, b)) for b in (sc.get("blocked") or [])} | set(w.tile)
        blocked |= belt_end_targets(w, {p for _, a, b in nets for p in (a, b)})  # would take that belt's items (b4)
        # existing belts on the endpoints are fine to replace? no: endpoints must be free tiles
        for _, a, b in nets:
            blocked.discard(a)
            blocked.discard(b)
        g = Grid(blocked, (min(xs) - margin, min(ys) - margin, max(xs) + margin, max(ys) + margin))
        inv = await self.refresh_inventory()
        stock = (await self.g.call("query", what="materials")).get("materials") or {}
        names = ("transport-belt", "underground-belt", "fast-underground-belt", "express-underground-belt")
        kit = {n: inv.get(n, 0) + int((stock or {}).get(n, 0)) for n in names}
        kit = {n: v for n, v in kit.items() if v > 0} or None
        if isinstance(s.get("kit"), dict) and s["kit"]:
            kit = {n: int(v) for n, v in s["kit"].items()}
        t0 = time.time()
        ents, info = await asyncio.to_thread(solve, g, nets, kit, float(s.get("seconds", 25)))
        self.log_fn({"t": t0, "kind": "route", "nets": len(nets), "ok": bool(ents), "info": info, "kit": kit,
                     "secs": round(time.time() - t0, 2)})
        if not ents and not s.get("_cleared"):
            # an earlier attempt at these same lines in the way (it failed, or the order was reset): pick those belts
            # up and route on a clean area. Only belts an earlier route step laid between any of these endpoints:
            # "every belt the serf built" here was a working base by a campaign's fifth generation (p2 mined 335
            # pieces of its own plastic and circuit lines, and was stopped with 1,660 to go). Never what players built.
            ends = {p for _, a, b in nets for p in (a, b)}
            old = set().union(*[r["tiles"] for r in self.routed if r["ends"] & ends]) if self.routed else set()
            mine = [e for e in w.ents.values() if e.get("t") in ("transport-belt", "underground-belt", "splitter")
                    and e.get("by") == self.g.name and (_m.floor(e["x"]), _m.floor(e["y"])) in old]
            if mine:
                me = await self.g.me()
                pos = me.get("position") or (cx, cy)
                mine.sort(key=lambda e: (e["x"] - pos[0]) ** 2 + (e["y"] - pos[1]) ** 2)
                got = 0
                for e in mine:
                    r = await self._act({"op": "mine", "x": e["x"], "y": e["y"], "name": e["n"]}, timeout=60)
                    if not r.get("ok") and "inventory full" in str(r.get("msg")):
                        await self.tidy(low=4, want=12)
                        r = await self._act({"op": "mine", "x": e["x"], "y": e["y"], "name": e["n"]}, timeout=60)
                        if not r.get("ok"):
                            break  # pockets stay full: route around what's left
                    got += bool(r.get("ok"))
                self.log_fn({"t": time.time(), "kind": "route_cleared", "n": len(mine), "mined": got})
                return await self._do_route({**s, "_cleared": True})
        if not ents:
            return {"ok": False, "msg": f"router: {info}"}
        self.routed = (self.routed + [{"ends": {p for _, a, b in nets for p in (a, b)},
                                       "tiles": {(_m.floor(e["x"]), _m.floor(e["y"])) for e in ents}}])[-20:]
        r = await self._do_ghosts({"entities": ents})
        r["msg"] = f"routed {len(nets)} lines ({len(ents)} pieces); " + str(r.get("msg"))
        return r

    async def _do_stamp(self, s):
        a = {"op": "blueprint", "string": s["string"], "x": float(s["x"]), "y": float(s["y"])}
        if s.get("direction"):
            a["direction"] = s["direction"]
        r = await self._act(a)
        if not r.get("ok"):
            return r
        return await self._do_build_ghosts({"x": s["x"], "y": s["y"], "radius": s.get("radius", 24)})

    async def _do_build_ghosts(self, s):
        """Build every ghost around a point: fetch what's missing, build, repeat until none left or stuck."""
        p = _xy(s)
        built_total, last_left = 0, None
        for rnd in range(8):
            a = {"op": "build_ghosts"}
            if p:
                a.update(x=p[0], y=p[1], radius=float(s.get("radius", 32)))
            r = await self._act(a, timeout=600)
            if not r.get("ok"):
                return r
            built_total += int(r.get("built") or 0)
            left = int(r.get("left") or 0)
            missing = r.get("missing") or {}
            if left == 0:
                # the mod skips a ghost whose placement failed once (e.g. the character stood on it); look again
                remaining = 0
                if p:
                    sc = await self.g.scan(center=p, radius=int(float(s.get("radius", 32))) + 1)
                    remaining = sum(1 for e in (sc.get("ents") or []) if e.get("ghost"))
                if remaining and rnd < 2:
                    last_left = None
                    continue
                if remaining:
                    # still there: place each one directly (it walks its own way; dense underground layouts can
                    # wall a spot off from the ghost builder's approach)
                    misses = 0
                    for e in [e for e in (sc.get("ents") or []) if e.get("ghost")]:
                        a = {"op": "place", "name": e["n"], "x": e["x"], "y": e["y"]}
                        if e.get("d"):
                            a["direction"] = e["d"]
                        if e.get("ug"):
                            a["type"] = e["ug"]
                        pr = await self._act(a, timeout=90)
                        if pr.get("ok"):
                            built_total += 1
                            misses = 0
                        else:
                            misses += 1
                            if misses >= 6:  # walled off or blocked: the planner hears about it, not 500 more tries
                                break
                    sc = await self.g.scan(center=p, radius=int(float(s.get("radius", 32))) + 1)
                    remaining = sum(1 for e in (sc.get("ents") or []) if e.get("ghost"))
                return {"ok": True, "msg": f"built {built_total} ghosts; none left"
                        + (f" ({remaining} ghosts there I couldn't build)" if remaining else ""), "built": built_total}
            if last_left is not None and left >= last_left and not r.get("built"):
                return {"ok": False, "msg": f"built {built_total}; {left} ghosts left that I can't build "
                        f"(missing {missing})", "missing": missing, "built": built_total, "left": left}
            last_left = left
            fails = []
            for item, n in missing.items():
                fr = await self.ensure(item, int(n))
                if not fr.get("ok"):
                    fails.append(f"{item}: {fr.get('msg')}")
            if fails and len(fails) == len(missing):
                return {"ok": False, "msg": f"built {built_total}; {left} left; can't get items: " + "; ".join(fails),
                        "missing": missing, "built": built_total, "left": left, "unobtainable": True}
        return {"ok": False, "msg": f"built {built_total}; still ghosts left after 8 rounds", "built": built_total}


def parse_missing(msg: str) -> dict:
    """Items a failure message says are missing, e.g. 'no iron-gear-wheel in inventory'."""
    out = {}
    for m in re.finditer(r"no ([a-z0-9-]+) in inventory", msg or ""):
        out[m.group(1)] = 1
    return out


def plan_needs(steps: list[dict]) -> dict:
    """Items a plan will use, so they can be fetched in one trip before it starts. Lines (connect) are estimated
    from the distance: belts/pipes ~ the walking distance plus a margin, poles ~ one per 5 tiles."""
    need: dict = {}

    def add(item, n):
        if item:
            item = PLACE_ITEM.get(item, item)
            need[item] = need.get(item, 0) + int(n)
    for s in steps:
        d = s.get("do")
        if d == "place":
            add(s.get("name"), 1)
        elif d == "ghosts":
            for e in expand(s.get("entities") or []):
                add(e.get("name"), 1)
        elif d == "design":
            from .library import place_design
            for e in place_design(s.get("name", ""), s.get("x", 0), s.get("y", 0)) or []:
                add(e.get("name"), 1)
        elif d == "row":
            n = int(s.get("count", 1))
            add(s.get("machine", "assembling-machine-1"), n)
            per = 1 + (1 if s.get("second_belt") else 0) + (1 if s.get("output", "chest") in ("chest", "belt") else 0)
            add(s.get("inserter", "inserter"), n * per)
            if s.get("output", "chest") == "chest":
                add("iron-chest", n)
            else:
                add("transport-belt", n * 3 + 2)
            add("small-electric-pole", n * 2 + 4)
        elif d == "block":
            from . import blueprints as bp
            try:
                for item, n in bp.needs(s.get("name", "")).items():
                    add(item, n)
            except KeyError:
                pass
        elif d == "connect" and isinstance(s.get("from"), (list, tuple)) and isinstance(s.get("to"), (list, tuple)):
            dist = abs(s["from"][0] - s["to"][0]) + abs(s["from"][1] - s["to"][1])
            item = s.get("item")
            if item and "pole" in item:
                add(item, dist / 5 + 2)
            elif item:
                add(item, dist * 1.2 + 4)
        elif d == "power":
            add(s.get("item", "small-electric-pole"), 6)
        elif d == "merge_lanes":
            for k in ("left", "right"):
                src = s.get(k)
                if isinstance(src, (list, tuple)) and isinstance(s.get("at"), (list, tuple)):
                    add(s.get("item", "transport-belt"), abs(src[0] - s["at"][0]) + abs(src[1] - s["at"][1]) + 6)
            if isinstance(s.get("to"), (list, tuple)) and isinstance(s.get("at"), (list, tuple)):
                add(s.get("item", "transport-belt"), abs(s["to"][0] - s["at"][0]) + abs(s["to"][1] - s["at"][1]) + 4)
        elif d == "bus":
            n = sum(1 for x in (s.get("lanes") or []) if x != "spare")
            add("transport-belt", n * int(s.get("length") or 0))
        elif d == "tap":
            add("splitter", 1)
            add("underground-belt", 2 * 4)
            add("transport-belt", int(s.get("run", 3)) + 4)
        elif d == "bus_in":
            add("underground-belt", 2 * 4)
            add("transport-belt", 60)
        elif d == "route":
            for pr in s.get("pairs") or []:
                try:
                    dist = abs(pr["from"][0] - pr["to"][0]) + abs(pr["from"][1] - pr["to"][1])
                    add("transport-belt", dist * 0.8 + 4)
                except (KeyError, TypeError, IndexError):
                    pass
    # spares: a trip back to storage costs far more than a few extra items in the pocket
    electric = {"assembling-machine-1", "assembling-machine-2", "assembling-machine-3", "inserter", "fast-inserter",
                "electric-mining-drill", "lab", "electric-furnace", "long-handed-inserter"}
    if any(k in electric for k in need):
        need["small-electric-pole"] = need.get("small-electric-pole", 0) + 4
    if "transport-belt" in need:
        need["transport-belt"] += 6
    return need
