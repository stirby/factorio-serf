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
from .world import fmt_xy, grid_live

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


REF = re.compile(r"^end:(\d+)$")


def resolve_refs(step: dict, ends: dict) -> tuple[dict, list[int]]:
    """A step with "end:N" in place of a tile ([x,y]) gets the end tile step N of the same plan reported (a tap's
    split-off belt, a row's output belt). Returns the resolved copy and the step numbers it needed but didn't have."""
    missing: list[int] = []

    def sub(v):
        if isinstance(v, str):
            m = REF.match(v.strip())
            if m:
                n = int(m.group(1))
                if n in ends:
                    return list(ends[n])
                missing.append(n)
            return v
        if isinstance(v, list):
            return [sub(x) for x in v]
        if isinstance(v, dict):
            return {k: sub(x) for k, x in v.items()}
        return v
    return {k: sub(v) for k, v in step.items()}, missing


def step_end(r: dict) -> list | None:
    """The end tile a step reports for later steps to build on (tap: its split-off belt; row: its output belt)."""
    e = r.get("end") or (r.get("info") or {}).get("output_belt_end")
    return list(e) if isinstance(e, (list, tuple)) and len(e) == 2 else None


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
    if d == "supply":
        return f"feed block {step.get('name')} at {step.get('x')},{step.get('y')} from the bus"
    if d in ("fetch", "craft", "mine"):
        return f"{d} {step.get('count', '')} {step.get('item') or step.get('recipe') or step.get('name')}"
    if d == "insert":
        return f"put {step.get('count', '')} {step.get('item')} into the thing{at}"
    if d == "say":
        return "say: " + str(step.get("text", ""))[:60]
    if d == "hop":
        return f"hop to {step.get('planet')}"
    if d == "request":
        return "have robots bring " + ", ".join(f"{n} {k}" for k, n in (step.get("items") or {}).items())
    if d == "sweep":
        return f"mark rocks and trees {step.get('x1')},{step.get('y1')} to {step.get('x2')},{step.get('y2')} for bots"
    if d == "tag":
        return f"tag {step.get('x')},{step.get('y')} \"{step.get('text')}\""
    if d == "bus":
        return f"lay bus {step.get('name') or 'main'}" + (f" ({', '.join(map(str, step['lanes']))})" if step.get(
            "lanes") else "")
    if d == "tap":
        return f"tap the {step.get('lane')} lane of bus {step.get('bus') or 'main'} at row {step.get('at')}"
    if d == "bus_in":
        return f"put {step.get('item') or step.get('lane')} onto bus {step.get('bus') or 'main'} at row {step.get('at')}"
    if d == "feed":
        return f"feed the {step.get('lane')} lane of bus {step.get('bus') or 'main'}"
    return f"{d}{at}"


# machines whose stopping matters to a clear (picked up while working = a line stops)
WORKERS = {"assembling-machine", "furnace", "mining-drill", "lab", "boiler", "generator", "offshore-pump", "pump",
           "rocket-silo", "reactor"}
FLUID_MACHINES = {"oil-refinery", "chemical-plant", "boiler", "steam-engine", "pumpjack", "offshore-pump", "pump"}


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
        self._minable: dict = {}  # (surface, item) -> (time, can it be mined near the serf)
        self.boxed_in = ""  # set when the character is shut in and couldn't get out: added to no-path failures

    async def can_mine(self, item: str) -> bool:
        """Whether a raw item can be mined near the serf. Wood needs trees that drop it: on Vulcanus the only trees
        are lichen, which drop carbon, and every plan there walked to one for wood that never came (live test,
        25 Oct). Ores, stone and coal are assumed. Asked of the mod at most every 5 minutes per planet."""
        if item != "wood":
            return True
        key = (self.g.surface, item)
        hit = self._minable.get(key)
        if hit and time.time() - hit[0] < 300:
            return hit[1]
        try:
            q = await self.g.call("query", what="mine_for", item=item, agent=self.g.name)
            ok = bool(q.get("nearest"))
        except Exception as e:  # noqa: BLE001
            # an older mod has no mine_for: assume trees, as before
            log.info("mine_for query failed (%r); assuming %s can be mined", e, item)
            ok = True
        self._minable[key] = (time.time(), ok)
        return ok

    async def pick_pole(self, n: int = 8) -> str:
        """The pole a plan should stock and lay when it doesn't name one: small ones when n are carried or stored or
        can be crafted (with wood that is stored or can be mined here), else medium ones when those can be had."""
        small, medium = "small-electric-pole", "medium-electric-pole"
        try:
            from . import craft
            have = dict((await self.g.call("query", what="materials", outputs=True)).get("materials") or {})
            for k, v in (await self.refresh_inventory()).items():
                have[k] = have.get(k, 0) + v
            if have.get(small, 0) >= n:
                return small
            if not self.recipes:
                return medium if have.get(medium, 0) >= n else small
            raw = dict(have)
            for item in ("stone", "coal") + (("wood",) if await self.can_mine("wood") else ()):
                raw[item] = raw.get(item, 0) + 10000
            if craft.most(small, raw, self.recipes, cap=n) >= n:
                return small
            if have.get(medium, 0) >= 3 or craft.most(medium, raw, self.recipes, cap=n) >= n:
                return medium
        except Exception as e:  # noqa: BLE001
            log.warning("pole choice failed: %r", e)
        return small

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
                self.boxed_in = ""
                if await self.escape():
                    return await self._act(action, timeout)
            if self.boxed_in:
                r = {**r, "msg": f"{r['msg']}; {self.boxed_in}"}
        elif r.get("ok"):
            self.no_path_streak = 0
            if action.get("op") == "move":
                self.boxed_in = ""
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

    async def tidy(self, low: int = 10, want: int = 20, everything: bool = False) -> dict | None:
        """Pockets nearly full (fewer than `low` free slots): drop raw resources and the surplus of plates and
        intermediates into a chest placed beside the character, until `want` slots are free. Fetching takes from
        chests, so nothing is lost. A full inventory quietly breaks mining, taking and hand-crafting: five of eight
        serfs were at 0 free slots after a night of campaigns (3,952 iron plates, 1,700 coal...)."""
        free = await self.free_slots()
        if free is None or (free >= low and not everything):
            return None
        inv = await self.refresh_inventory()
        if everything:  # every item, buildings too (hop: only empty-handed)
            dump = sorted(inv.items(), key=lambda t: -t[1])
        else:
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
        made, moved, used = 0, {}, []
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
                n = min(n, have)  # crafting a chest may have used some (iron plates)
                if n <= 0:
                    break
                r = await self._act({"op": "insert", "x": targets[0][0], "y": targets[0][1], "item": item,
                                     "count": n})
                put = have - (await self.refresh_inventory()).get(item, 0)
                if put > 0:
                    moved[item] = moved.get(item, 0) + put
                    n -= put
                    if targets[0] not in used:
                        used.append(list(targets[0]))
                if not r.get("ok") or put <= 0 or n > 0:
                    targets.pop(0)  # that chest is full
            free = await self.free_slots()
            if free is not None and free >= want and not everything:
                break
        chests = made
        self.log_fn({"t": time.time(), "kind": "tidy", "moved": moved, "chests": chests, "free_after": free,
                     "at": used})
        return {"ok": True, "msg": f"put {sum(moved.values())} items in {len(used)} chest(s) ({chests} new); {free} "
                                   "slots free", "at": used}

    ESCAPE_THROUGH = ("transport-belt", "underground-belt", "splitter", "pipe", "pipe-to-ground", "electric-pole",
                      "inserter", "container", "wall", "furnace", "mining-drill")
    # furnaces and drills go last (a burner loses its fuel to the pocket; it's given back after). The live test on
    # Vulcanus (25 Oct) boxed itself in among its own electric drills and stayed stuck: neither was on the list.
    LIFT_LAST = ("furnace", "mining-drill")

    async def escape(self) -> bool:
        """Several places in a row have no path: if the character can't walk anywhere, it has walled itself in
        (belts, pipes, drills, furnaces round it). Do what a player does: pick up the nearest piece beside it, step
        out through the gap, and put the piece back from outside. True when it got out."""
        self._escaping = True
        try:
            me = await self.g.me()
            x, y = me["position"]
            for dx, dy in ((14, 0), (-14, 0), (0, 14), (0, -14)):
                r = await self.g.run({"op": "move", "x": x + dx, "y": y + dy, "radius": 6}, timeout=60)
                if r.get("ok"):
                    self.log_fn({"t": time.time(), "kind": "escape", "trapped": False})
                    return False  # it can walk: the places it wanted are unreachable, not the character stuck
            sc = await self.g.scan(center=(x, y), radius=5)

            def beside(e):  # touching the character: big machines' centres sit farther off (an electric drill: 1.5+)
                lim = 3.4 if e.get("t") in self.LIFT_LAST else 2.6
                return abs(e["x"] - x) <= lim and abs(e["y"] - y) <= lim
            near = [e for e in (sc.get("ents") or []) if not e.get("ghost") and e.get("t") in self.ESCAPE_THROUGH
                    and beside(e)]
            near.sort(key=lambda e: (e.get("t") in self.LIFT_LAST, (e["x"] - x) ** 2 + (e["y"] - y) ** 2))
            for e in near[:5]:
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
                if put.get("ok") and e.get("t") in self.LIFT_LAST:
                    # a burner's fuel went into the pocket with it: give some back (an electric one just refuses)
                    inv = await self.refresh_inventory()
                    fuel = next((f for f in FUELS if inv.get(f, 0) > 0), None)
                    if fuel:
                        await self.g.run({"op": "insert", "x": e["x"], "y": e["y"], "item": fuel,
                                          "count": min(10, inv[fuel])}, timeout=30)
                self.log_fn({"t": time.time(), "kind": "escape", "trapped": True, "through": e["n"],
                             "at": [e["x"], e["y"]], "out": out.get("ok"), "put_back": put.get("ok")})
                if out.get("ok"):
                    return True
            self.log_fn({"t": time.time(), "kind": "escape", "trapped": True, "out": False})
            ring = sorted({e["n"] for e in (sc.get("ents") or []) if not e.get("ghost") and beside(e)})
            self.boxed_in = (f"the character itself is boxed in at {x:.0f},{y:.0f} (it can't walk 14 tiles any way)"
                             + (f" by {', '.join(ring[:5])}" if ring else "") + ": it has to be cleared out first")
            return False
        except Exception as ex:  # noqa: BLE001
            self.log_fn({"t": time.time(), "kind": "error", "where": "escape", "error": repr(ex)})
            return False
        finally:
            self._escaping = False

    async def stock(self, need: dict, fallback: bool = True) -> dict:
        """Get everything in `need` ({item: count}) in one trip: fetches queued back to back, so the character walks
        to storage once. Returns {item: error} for what it couldn't get."""
        inv = await self.refresh_inventory()
        short = {i: int(n) for i, n in need.items() if inv.get(i, 0) < int(n)}
        if not short:
            return {}
        t0 = time.time()
        # what can't be had at all is reported now, not after a long walk collecting ingredients for it: storage,
        # machine outputs and pockets, crafting (stone and coal count as minable, wood where it grows)
        known_short = {}
        if self.recipes:
            try:
                from . import craft
                have = dict((await self.g.call("query", what="materials", outputs=True)).get("materials") or {})
                for k, v in inv.items():
                    have[k] = have.get(k, 0) + v
                for raw in ("wood", "stone", "coal"):  # wood only where trees that drop it grow
                    if await self.can_mine(raw):
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
        for i in list(fails) if fallback else []:  # storage couldn't: try belts and crafting from belt items
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
                            # raw: mine it (wood from trees that drop it: 4 per tree)
                            short_ing = need - (await self.refresh_inventory()).get(ing, 0)
                            if short_ing <= 300 and await self.can_mine(ing):
                                await self._act({"op": "mine", "name": MINEABLE[ing], "item": ing,
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
        msg = f"laid it in {n} legs: " + " | ".join(msgs)
        span = max(abs(to[0] - fr[0]), abs(to[1] - fr[1]))
        if "pipe" in str(s["item"]) and span > 300:
            msg += (f". Note: it spans {span:.0f} tiles; a fluid segment longer than 320 tiles carries nothing in 2.0, "
                    f"so it needs a powered pump at least every 300 tiles")
        return {"ok": True, "msg": msg}

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
        item = "wood" if name == "raw-wood" else (name if name in MINEABLE else None)
        name = {"raw-wood": "tree"}.get(name, MINEABLE.get(name, name))
        n = int(s.get("count", 10))
        if item == "wood":
            if not await self.can_mine("wood"):
                return {"ok": False, "unobtainable": True,
                        "msg": "no trees that drop wood grow near here (on this planet trees give other things): wood "
                               "has to come from storage, or use parts that need none (medium poles, iron chests)"}
            return await self._act({"op": "mine", "name": name, "item": "wood", "count": n},
                                   timeout=max(400, 6 * n + 60))
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
                        r = await self._do_mine({"name": "wood", "count": max(4, want // 4)})
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
        item = s.get("item")
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
                item = item or await self.pick_pole(8)
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
            # several separate belt lines in the square: the one meant is rarely all of them (p6 cleared radius 12
            # of belts to remove one bad line and took its chemical science block's 183 belts with it)
            lines = {}
            for e in ents:
                ln = w.line_of.get(e["u"]) if e.get("t") in ("transport-belt", "underground-belt", "splitter") else None
                if ln is not None:
                    lines[ln.id] = ln
            # working machines and the pipes of a live fluid system: p6 cleared a square to rebuild a sulfur plant and
            # took the refineries' crude and water pipes with it (84 things; the oil block stood dry for an hour)
            if not s.get("force") and not only:
                busy = [e for e in ents if e.get("s") == "working" and e.get("t") in WORKERS]
                pipes = [e for e in ents if e.get("t") in ("pipe", "pipe-to-ground", "pump", "storage-tank")]
                wet = [e for e in busy if e.get("n") in FLUID_MACHINES]
                if len(busy) >= 3 or (len(pipes) >= 8 and wet):
                    names: dict[str, int] = {}
                    for e in busy:
                        names[e["n"]] = names.get(e["n"], 0) + 1
                    what = ", ".join(f"{k} {n}" for n, k in names.items())
                    return {"ok": False, "msg": f"that square holds {len(busy)} working machines ({what})"
                            + (f" and {len(pipes)} pipes of a working fluid line" if pipes and wet else "")
                            + ": clearing it stops them. Pick up only what you mean with only=[names] (or clear "
                              "line=[x,y] for one belt line), or add force=true to take everything there"}
            if len(lines) > 2 and not s.get("force"):
                desc = []
                for ln in list(lines.values())[:8]:
                    items = ", ".join(sorted(ln.items or {})) or "empty"
                    desc.append(f"line {ln.id} ({items}; {ln.length} tiles, {fmt_xy(ln.start)} to {fmt_xy(ln.end)})")
                return {"ok": False, "msg": f"that square holds {len(lines)} separate belt lines: " + "; ".join(desc) +
                        ". Clear the one you mean with clear line=[x,y] (a tile of it), or add force=true to take "
                        "them all"}
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

    async def _do_hop(self, s):
        """To another planet's spawn (the mod's hop: a teammate's stand-in for a rocket ride). Only empty-handed:
        everything it carries goes into chests here first (nearby ones with room, else new ones beside it); armor,
        guns and ammo go along."""
        planet = str(s.get("planet") or s.get("to") or "").lower()
        me = await self.g.me()
        if me.get("surface") == planet:
            return {"ok": True, "msg": f"already on {planet}"}
        stored, at = "", []
        if any(n > 0 for n in (me.get("inventory") or {}).values()):
            t = await self.tidy(everything=True)
            stored, at = (t or {}).get("msg", ""), (t or {}).get("at") or []
            left = {k: n for k, n in (await self.refresh_inventory()).items() if n > 0}
            if left:
                return {"ok": False, "msg": f"can't hop: still carrying {len(left)} kinds of items after storing "
                        f"({stored or 'no chest for them'}); empty the inventory into a chest first"}
        try:
            r = await self.g.call("hop", agent=self.g.name, planet=planet, timeout=30)
        except Exception as e:  # noqa: BLE001  (the mod's reason: not a planet with a surface, not empty-handed...)
            return {"ok": False, "msg": f"can't hop to {planet}: {e}"[:300]}
        self.inventory = {}
        if at:  # where its things are (live test: 1,810 items went into a chest and nobody was told where)
            src = me.get("surface") or "nauvis"
            await self.g.say("left my things in " + ("a chest" if len(at) == 1 else f"{len(at)} chests") + " on "
                             + src + ": " + " ".join(f"[gps={c[0]:g},{c[1]:g},{src}]" for c in at[:4]))
        pos = r.get("position") or (0, 0)
        return {"ok": True, "msg": f"on {planet} at its spawn {fmt_xy(pos)}" + (f"; {stored} before leaving" if stored
                                                                                   else "")}

    async def _network_here(self, items: list[str]) -> dict | None:
        """The logistic networks on the character's planet, with whether its spot is in a roboport's logistic area,
        the nearest spot that is, and how many of `items` each network holds (None from a mod before 0.3.5)."""
        me = await self.g.me()
        x, y = me["position"]
        try:
            r = await self.g.call("network", agent=self.g.name, x=float(x), y=float(y), items=items)
        except Exception:  # noqa: BLE001
            return None
        return r if isinstance(r, dict) and "at" in r else None

    async def _do_request(self, s):
        """Have logistic robots bring items to the character (its own requests): it walks into a roboport's logistic
        area first if it isn't in one, asks only for what the network holds, waits until the items arrive (wait
        seconds, default 90) or nothing has come for a while, then clears the requests so the bots don't keep
        bringing more. Live tests: "you should request stuff from logistics net too"; and it once waited 4 minutes
        outside every roboport's reach, 300 tiles from the build, for robots that couldn't come."""
        items = {str(k): int(v) for k, v in (s.get("items") or {}).items() if int(v) > 0}
        if not items:
            return {"ok": False, "msg": "request needs items={item: count}"}
        notes = []
        net = await self._network_here(list(items))
        if net is not None:  # an older mod doesn't say where coverage is: request where it stands
            if not net.get("at", {}).get("logistic"):
                near = net["at"].get("nearest_logistic")
                if not near:
                    return {"ok": False, "msg": "no roboport network on this planet: fetch or take the items from "
                                                "chests instead"}
                mv = await self._act({"op": "move", "x": near["x"], "y": near["y"], "radius": 2})
                if not mv.get("ok"):
                    return {"ok": False, "msg": f"couldn't walk into roboport coverage at {near['x']:.0f},"
                                                f"{near['y']:.0f}: {mv.get('msg')}"}
                notes.append(f"walked {near['d']} tiles into roboport coverage")
                net = await self._network_here(list(items)) or net
            nid = net.get("at", {}).get("logistic")
            held = next((n.get("item_counts") for n in net.get("networks") or [] if n.get("id") == nid), None)
            if held is not None:
                missing = [k for k in items if held.get(k, 0) <= 0]
                fewer = {k: held[k] for k in items if 0 < held.get(k, 0) < items[k]}
                if missing:
                    notes.append("the network has no " + ", ".join(missing))
                if fewer:
                    notes.append("it holds only " + ", ".join(f"{n} {k}" for k, n in fewer.items()))
                asked = {k: min(n, held.get(k, 0)) for k, n in items.items() if held.get(k, 0) > 0}
                if not asked:
                    return {"ok": False, "msg": "; ".join(notes) + ": fetch or craft them instead"}
            else:
                asked = dict(items)
        else:
            asked = dict(items)
        before = await self.refresh_inventory()
        want = {k: before.get(k, 0) + n for k, n in asked.items()}
        r = await self._act({"op": "configure", "self": True, "requests": want}, timeout=30)
        if not r.get("ok"):
            return r
        t0 = time.time()
        deadline = t0 + min(float(s.get("wait") or 90), 600)
        inv, last, last_gain = before, dict(before), t0
        while time.time() < deadline:
            await asyncio.sleep(3)
            inv = await self.refresh_inventory()
            if all(inv.get(k, 0) >= n for k, n in want.items()):
                break
            if any(inv.get(k, 0) > last.get(k, 0) for k in want):
                last, last_gain = dict(inv), time.time()
            elif time.time() - last_gain > (30 if last_gain > t0 else 60):
                notes.append(f"nothing arrived for {time.time() - last_gain:.0f} s, so it stopped waiting")
                break
        await self._act({"op": "configure", "self": True, "requests": {}}, timeout=30)
        got = {k: inv.get(k, 0) - before.get(k, 0) for k in items}
        short = {k: items[k] - got[k] for k in items if got[k] < items[k]}
        said = ("; ".join(notes) + "; ") if notes else ""
        if short:
            why = "" if net is not None else " (no roboport coverage here, or not in storage on this planet)"
            return {"ok": False, "msg": f"{said}robots brought {got}; still short {short}{why}"}
        return {"ok": True, "msg": f"{said}robots brought {got}"}

    async def _do_sweep(self, s):
        """Mark the trees and rocks in an area for deconstruction, for construction bots to clear (only those: never a
        building). Bots need roboport coverage there; the marks wait until then."""
        try:
            x1, y1, x2, y2 = (float(s[k]) for k in ("x1", "y1", "x2", "y2"))
        except (KeyError, TypeError, ValueError):
            return {"ok": False, "msg": "sweep needs x1 y1 x2 y2 (the area's corners)"}
        if abs(x2 - x1) * abs(y2 - y1) > 400 * 400:
            return {"ok": False, "msg": "sweep areas are at most 400x400 tiles: split it"}
        # a mod before 0.3.4 ignores nature_only and would mark the force's buildings there too
        try:
            ver = str((await self.g.call("ping")).get("version") or "0")
            if tuple(int(x) for x in ver.split(".")[:3]) < (0, 3, 4):
                return {"ok": False, "msg": f"sweep needs the serf mod 0.3.4 (this game runs {ver}): mine the rocks "
                                           "by hand for now"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "msg": f"sweep: couldn't check the mod version ({e})"[:300]}
        try:
            r = await self.g.call("order", kind="deconstruct", x1=x1, y1=y1, x2=x2, y2=y2, nature_only=True)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "msg": f"sweep failed: {e}"[:300]}
        return {"ok": True, "msg": f"marked {r.get('ordered', 0)} trees and rocks between {x1:g},{y1:g} and "
                                   f"{x2:g},{y2:g} for construction bots"}

    async def _do_tag(self, s):
        """A labelled map tag (and a floating label) players see: what a place or chest is for."""
        p = _xy(s)
        kind = s.get("kind") if s.get("kind") in ("provider", "requester", "storage", "note") else "note"
        try:
            r = await self.g.call("mark", agent=self.g.name, x=p[0], y=p[1], text=str(s.get("text") or "")[:80],
                                  kind=kind)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "msg": f"tag failed: {e}"[:300]}
        return {"ok": True, "msg": f"tagged {fmt_xy(p)} \"{s.get('text')}\" (mark {r.get('id')})"}

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
        pole = s.get("pole") or await self.pick_pole(2 * int(s.get("count", 1)) + 2)
        best = None
        for sd in cands:
            ents, info = row_entities((e["x"], e["y"]), d, sd, s.get("machine", "assembling-machine-1"),
                                      s.get("recipe"), int(s.get("count", 1)), bool(s.get("second_belt")),
                                      s.get("output", "chest"), s.get("inserter", "inserter"), int(s.get("offset", 0)),
                                      pole=pole)
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

    async def _do_supply(self, s):
        """Feed a placed block's belt inputs: for each input, tap the bus lane carrying each item it takes (at the
        free rows nearest the block, coming out on the block's side), merge two items onto their own lanes when the
        input takes two, and bring the belt to the tile the input is fed from. The block is named as in its block step
        (name, x, y, rotation, anchor); from={item: [x,y]} gives the last belt of a line for an item the bus doesn't
        carry; only=[items] limits it to inputs taking those. Fluid inputs are left to a pipe connect. (b7, p7, p8:
        wiring a block's inputs by hand took most of a blue science build, and mixed lines took dozens of purges.)"""
        from . import blueprints as bp
        from .busgen import DIRS as BD, OPP
        try:
            st = bp.stamp(s["name"], float(s["x"]), float(s["y"]), s.get("rotation", 0), s.get("anchor"))
        except KeyError as e:
            return {"ok": False, "msg": f"supply: {e}"}
        ports = [p for p in st.get("inputs") or [] if "at" in p and p.get("side") in BD
                 and p.get("kind") not in ("fluid", "chest", "power")]
        if not ports:
            return {"ok": False, "msg": f"supply: block {s['name']} has no belt inputs to feed"}
        given = {str(k): v for k, v in (s.get("from") or {}).items()} if isinstance(s.get("from"), dict) else {}
        only = s.get("only")
        only = [only] if isinstance(only, str) else (only or None)
        bx0, by0 = st["bbox"][0]
        bx1, by1 = st["bbox"][1]
        bcx, bcy = (bx0 + bx1) / 2, (by0 + by1) / 2
        # every line keeps off the block's footprint and the other inputs' feeding tiles (built yet or not)
        keep_off = [[x + 0.5, y + 0.5] for x in range(int(bx0), int(bx1)) for y in range(int(by0), int(by1))]
        for q in ports:
            qx, qy = BD[q["side"]]
            keep_off.append([q["at"][0] + 0.5 + qx, q["at"][1] + 0.5 + qy])
        done, failed = [], []

        async def source(item: str, near: tuple[float, float]):
            """The last belt of a line carrying item: given, or a new tap on the bus lane carrying it."""
            if item in given:
                return list(given[item]), f"{item} from the line ending at {fmt_xy(given[item])}"
            try:
                b = await self._bus(s.get("bus"))
                i = b.lane_index(item)
            except ValueError as e:
                # not on a bus: the nearest belt line carrying it that ends in the open (a base without a bus, or a
                # product of another block: q6's and q10's advanced-circuit orders fed from smelter and plastic belts)
                end = await self._open_line_end(item, (bcx, bcy))
                if end:
                    return end, f"{item} from the line ending at {fmt_xy(end)}"
                return None, (f"{item}: {e}; and no belt carrying it ends in the open within 80 tiles: give "
                              f"from={{\"{item}\": [x,y]}} (the last belt of a line carrying it)")
            nx, ny = BD[b.side]
            across = (bcx - b.x) * nx + (bcy - b.y) * ny
            a0 = max(0, min(b.length - 3, b.along_of(*near)))
            rows = sorted((a for a in range(max(b.start(i), 0), b.length - 2) if b.rows_free(a) is None),
                          key=lambda a: abs(a - a0))
            if not rows:
                return None, f"{item}: no free row left on bus {b.name} to tap lane {i} (taps and merges sit 4 apart)"
            for a in rows[:3]:
                r = await self._do_tap({"bus": b.name, "lane": i, "at": a,
                                        **({"side": "opposite"} if across < 0 else {})})
                if r.get("ok"):
                    return list(r["end"]), f"{item} tapped off lane {i} at row {a}"
                last = str(r.get("msg"))
            return None, f"{item}: tap failed: {last[:160]}"

        # Plan every input's tiles before laying anything: a merge's tile, the two tiles its feeds end on, and its run
        # into the block must not take another input's feeding tile or approach (b12: the LDS block's two inputs sit
        # on neighbouring rows, and the first merge's feed ended on the copper input's feeding tile, walling it in).
        LEFTV = {"east": (0, -1), "north": (-1, 0), "west": (0, 1), "south": (1, 0)}
        block = {(x, y) for x in range(int(bx0), int(bx1)) for y in range(int(by0), int(by1))}
        tile = lambda x, y: (int(x // 1), int(y // 1))  # noqa: E731
        # what already stands around the block: a merge can't use those tiles, and a feed's last tile needs a free
        # way in (b12: pipes laid before supply walled a feed tile into "a closed pocket of 1 free tiles")
        from .world import World
        try:
            wb = World(await self.g.scan(center=(bcx, bcy), radius=int(max(bx1 - bx0, by1 - by0) / 2 + 10)))
            taken = set(wb.tile)
        except Exception:  # noqa: BLE001
            taken = set()
        plans = []
        reserved: dict = {}  # tile -> index of the input that needs it
        for n, q in enumerate(ports):
            qx, qy = BD[q["side"]]
            e_t = (q["at"][0] + qx, q["at"][1] + qy)
            reserved[e_t] = n
            reserved.setdefault((e_t[0] + qx, e_t[1] + qy), n)  # a straight way in
        for n, p in enumerate(ports):
            lanes = p.get("lanes") or {}
            items = [lanes[k] for k in ("left", "right") if lanes.get(k)] or ([p["item"]] if p.get("item") else [])
            side = p["side"]
            sx, sy = BD[side]
            d = OPP[side]
            ex, ey = p["at"][0] + 0.5 + sx, p["at"][1] + 0.5 + sy
            k_use, need = None, set()
            if len(set(items)) >= 2:
                lx, ly = LEFTV[d]
                for k in range(0, 5):
                    mx, my = ex + sx * k, ey + sy * k
                    run = {tile(ex + sx * j, ey + sy * j) for j in range(0, k)}
                    need = {tile(mx, my), tile(mx + lx, my + ly), tile(mx - lx, my - ly)} | run
                    if need & block or need & taken or any(reserved.get(t, n) != n for t in need):
                        continue
                    blocked = block | taken | {t for t, o in reserved.items() if o != n} | need

                    def way_in(t):  # a feed tile needs a free neighbour to come in from (other than the merge)
                        return any((t[0] + a, t[1] + b) not in blocked for a, b in ((1, 0), (-1, 0), (0, 1), (0, -1)))
                    if not (way_in(tile(mx + lx, my + ly)) and way_in(tile(mx - lx, my - ly))):
                        continue
                    k_use = k
                    for t in need:
                        reserved[t] = n
                    break
            plans.append((p, items, side, d, ex, ey, k_use, need))
        for n, (p, items, side, d, ex, ey, k_use, need) in enumerate(plans):
            lanes = p.get("lanes") or {}
            if only and not any(it in only for it in items):
                continue
            sx, sy = BD[side]
            tx, ty = p["at"][0] + 0.5, p["at"][1] + 0.5
            what = " + ".join(items)
            # every route keeps off the block, the other inputs' tiles and this input's merge run
            others = [[t[0] + 0.5, t[1] + 0.5] for t, owner in reserved.items() if owner != n]
            if len(set(items)) >= 2:
                if k_use is None:
                    failed.append(f"{what} input at {fmt_xy((tx, ty))}: no room to merge its two items next to it "
                                  "(other inputs or buildings in the way)")
                    continue
                mx, my = ex + sx * k_use, ey + sy * k_use
                run = [[ex + sx * j, ey + sy * j] for j in range(0, k_use)]
                (lt, lw), (rt, rw) = [await source(it, (mx, my)) for it in (lanes["left"], lanes["right"])]
                if not (lt and rt):
                    failed.append(f"{what} input at {fmt_xy((tx, ty))}: " + "; ".join(w for t, w in ((lt, lw), (rt, rw))
                                                                                   if not t))
                    continue
                r = await self._do_merge_lanes({"left": lt, "right": rt, "at": [mx, my], "direction": d,
                                                **({"to": [ex, ey]} if k_use else {}),
                                                "avoid": [t for t in keep_off + others + run
                                                          if (t[0], t[1]) != (mx, my)]})
                if r.get("ok"):
                    await self._act({"op": "rotate", "x": ex, "y": ey, "direction": d})
                    done.append(f"{what} on their lanes into {fmt_xy((tx, ty))} ({lw}; {rw})")
                else:
                    failed.append(f"{what} input at {fmt_xy((tx, ty))}: merge failed: {str(r.get('msg'))[:200]}")
            elif items:
                t, w = await source(items[0], (ex, ey))
                if not t:
                    failed.append(f"{what} input at {fmt_xy((tx, ty))}: {w}")
                    continue
                r = await self._act({"op": "connect", "item": "transport-belt", "from": t, "to": [ex, ey],
                                     "end_direction": d,
                                     "avoid": [q for q in keep_off + others if (q[0], q[1]) != (ex, ey)]}, timeout=420)
                if r.get("ok"):
                    await self._act({"op": "rotate", "x": ex, "y": ey, "direction": d})
                    done.append(f"{what} into {fmt_xy((tx, ty))} ({w})")
                else:
                    failed.append(f"{what} input at {fmt_xy((tx, ty))}: belt failed: {str(r.get('msg'))[:200]}")
        msg = (f"supply {s['name']}: fed " + ("; ".join(done) if done else "nothing")
               + (f". Not fed: {'; '.join(failed)}" if failed else ""))
        return {"ok": not failed and bool(done), "msg": msg}

    async def _open_line_end(self, item: str, near: tuple[float, float], radius: int = 80):
        """The last tile of the nearest belt line carrying item whose end is open (nothing ahead), or None."""
        from .world import World
        try:
            w = World(await self.g.scan(center=near, radius=radius))
        except Exception:  # noqa: BLE001
            return None
        best = None
        for ln in w.lines:
            if item not in (ln.items or {}) or ln.end_reason != "ends (nothing ahead)":
                continue
            d = (ln.end[0] - near[0]) ** 2 + (ln.end[1] - near[1]) ** 2
            if best is None or d < best[0]:
                best = (d, [float(ln.end[0]), float(ln.end[1])])
        return best[1] if best else None

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
            other = right_tile if side == "left" else left_tile
            avoid = [[ax, ay], other] + [list(t) for t in (s.get("avoid") or []) if isinstance(t, (list, tuple))]
            r = await self._act({"op": "connect", "item": s.get("item", "transport-belt"), "from": list(src),
                                 "to": tile, "end_direction": face, "avoid": avoid}, timeout=420)
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
        from .busgen import DIRS, OPP, SPARE
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
        out_side = b.side
        if s.get("side") in ("opposite", OPP.get(b.side)):  # leave the bus on its far side (a mirrored view)
            mb = b.mirrored()
            ents, ex, mine = mb.tap(2 * b.pairs - 1 - i, a)
            out_side = mb.side
        else:
            ents, ex, mine = b.tap(i, a)
        nx, ny = DIRS[out_side]
        run = max(1, int(s.get("run", 3)))
        for k in range(run):
            ents.append({"name": "transport-belt", "x": ex["x"] + nx * k, "y": ex["y"] + ny * k,
                         "direction": out_side})
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
                f"{r.get('msg')}; the split-off belt ends at {end[0]:g},{end[1]:g} running {out_side}",
                "end": end}

    async def _do_feed(self, s):
        """Feed a lane of the bus from a supply line (from = its last belt): the line comes in beside the lane's first
        tile, in the free column on the lane's outer side, and turns into it, so the lanes of a pair are fed from
        opposite sides and never block each other (p9: two smelter lines aimed at neighbouring lane heads, one ended
        against the other's feed and both lanes ran empty)."""
        try:
            b = await self._bus(s.get("bus"))
            i = b.lane_index(s.get("lane"))
        except (ValueError, TypeError) as e:
            return {"ok": False, "msg": f"feed: {e}"}
        if not isinstance(s.get("from"), (list, tuple)):
            return {"ok": False, "msg": "feed needs from=[x,y], the last belt of the supply line"}
        (ex, ey), face = b.feed_entry(i)
        r = await self._act({"op": "connect", "item": s.get("belt", "transport-belt"), "from": list(s["from"]),
                             "to": [ex, ey], "end_direction": face}, timeout=600)
        if r.get("ok"):
            await self._act({"op": "rotate", "x": ex, "y": ey, "direction": face})
            if not any(j.get("kind") == "feed" and int(j.get("lane", -1)) == i for j in b.joins):
                b.joins.append({"kind": "feed", "lane": i, "at": b.start(i), "end": [ex, ey]})
                await self._save_bus(b)
        hx, hy = b.at(b.start(i), b.u(i))
        return {"ok": bool(r.get("ok")), "msg": f"feed bus {b.name} lane {i} ({b.lanes[i]}) at its first tile "
                f"{hx:g},{hy:g} from the side ({ex:g},{ey:g}, facing {face}): {str(r.get('msg'))[:200]}"}

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
        string = s.get("string")
        if not string and s.get("name"):  # a blueprint a player taught it (Teach serf)
            from . import blueprints as bp
            try:
                string = bp.get_design(str(s["name"])).get("string")
            except KeyError as e:
                return {"ok": False, "msg": str(e)[:300]}
        if not string:
            return {"ok": False, "msg": "stamp needs a blueprint string or the name of a taught blueprint"}
        a = {"op": "blueprint", "string": string, "x": float(s["x"]), "y": float(s["y"])}
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


def plan_needs(steps: list[dict], pole: str = "small-electric-pole") -> dict:
    """Items a plan will use, so they can be fetched in one trip before it starts. Lines (connect) are estimated
    from the distance: belts/pipes ~ the walking distance plus a margin, poles ~ one per 5 tiles. `pole` is the one
    rows, power steps and spares will lay when a step doesn't name one (Runner.pick_pole): stocking small poles a
    medium-pole base can't make sent the serf off for wood on every plan (live test, 25 Oct)."""
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
            add(s.get("pole") or pole, n * 2 + 4)
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
            add(s.get("item") or pole, 6)
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
        elif d == "feed" and isinstance(s.get("from"), (list, tuple)):
            add("transport-belt", 40)
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
        need[pole] = need.get(pole, 0) + 4
    if "transport-belt" in need:
        need["transport-belt"] += 6
    return need
