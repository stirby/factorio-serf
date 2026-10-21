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
import re
import time

from .game import Game

log = logging.getLogger("jev.steps")

FUELS = ("coal", "wood", "solid-fuel")
PLACE_ITEM = {"straight-rail": "rail", "curved-rail-a": "rail", "curved-rail-b": "rail"}


def _xy(s: dict, key: str = "") -> tuple[float, float] | None:
    if key and isinstance(s.get(key), (list, tuple)) and len(s[key]) == 2:
        return float(s[key][0]), float(s[key][1])
    if "x" in s and "y" in s:
        return float(s["x"]), float(s["y"])
    return None


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
    return f"{d}{at}"


class Runner:
    def __init__(self, game: Game, log_fn=None):
        self.g = game
        self.log_fn = log_fn or (lambda rec: None)
        self.inventory: dict = {}

    async def refresh_inventory(self) -> dict:
        try:
            me = await self.g.me()
            self.inventory = me.get("inventory") or {}
        except Exception as e:  # noqa: BLE001
            log.warning("inventory read failed: %r", e)
        return self.inventory

    async def _act(self, action: dict, timeout: float = 240) -> dict:
        t0 = time.time()
        r = await self.g.run(action, timeout=timeout)
        self.log_fn({"t": t0, "kind": "act", "action": action, "ok": r.get("ok"), "msg": r.get("msg"),
                     "secs": round(time.time() - t0, 1)})
        return r

    async def stock(self, need: dict) -> dict:
        """Get everything in `need` ({item: count}) in one trip: fetches queued back to back, so the character walks
        to storage once. Returns {item: error} for what it couldn't get."""
        inv = await self.refresh_inventory()
        short = {i: int(n) for i, n in need.items() if inv.get(i, 0) < int(n)}
        if not short:
            return {}
        t0 = time.time()
        acts = [{"op": "fetch", "item": i, "count": n} for i, n in short.items()]
        try:
            ids = await self.g.act(acts)
        except Exception as e:  # noqa: BLE001
            return {i: repr(e) for i in short}
        fails = {}
        for i, jid in zip(short, ids):
            r = await self.g.wait_job(jid, 400)
            if not r.get("ok"):
                fails[i] = r.get("msg")
        self.log_fn({"t": t0, "kind": "stock", "need": short, "fails": fails, "secs": round(time.time() - t0, 1)})
        return fails

    async def ensure(self, item: str, count: int) -> dict:
        """Have at least count of item: storage first, then hand-crafting (the mod's fetch does both)."""
        inv = await self.refresh_inventory()
        if inv.get(item, 0) >= count:
            return {"ok": True, "msg": f"have {inv[item]} {item}"}
        r = await self._act({"op": "fetch", "item": item, "count": count}, timeout=300)
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
        if r.get("ok") and s.get("recipe"):
            r2 = await self._act({"op": "set_recipe", "x": p[0], "y": p[1], "recipe": s["recipe"]})
            if not r2.get("ok"):
                return {"ok": False, "msg": f"placed, but recipe failed: {r2.get('msg')}"}
            r["msg"] = (r.get("msg") or "") + f"; recipe {s['recipe']}"
        return r

    async def _do_connect(self, s):
        a = {"op": "connect", "item": s["item"], "from": list(s["from"]), "to": list(s["to"])}
        for k in ("end_direction", "join"):
            if s.get(k) is not None:
                a[k] = s[k]
        return await self._act(a, timeout=420)

    async def _do_fetch(self, s):
        return await self._act({"op": "fetch", "item": s["item"], "count": int(s.get("count", 1))}, timeout=300)

    async def _do_craft(self, s):
        return await self._act({"op": "craft", "recipe": s["recipe"], "count": int(s.get("count", 1))}, timeout=300)

    async def _do_mine(self, s):
        a = {"op": "mine", "name": s.get("name") or s.get("item"), "count": int(s.get("count", 10))}
        return await self._act(a, timeout=400)

    async def _do_mine_at(self, s):
        p = _xy(s)
        a = {"op": "mine", "x": p[0], "y": p[1]}
        if s.get("force_pickup"):
            a["force_pickup"] = True
        return await self._act(a)

    async def _do_insert(self, s):
        p = _xy(s)
        n = int(s.get("count", 0) or 0)
        r = await self.ensure(s["item"], max(1, n))
        if not r.get("ok"):
            return {"ok": False, "msg": f"couldn't get {s['item']}: {r.get('msg')}", "missing": {s["item"]: max(1, n)},
                    "unobtainable": True}
        a = {"op": "insert", "x": p[0], "y": p[1], "item": s["item"]}
        if n:
            a["count"] = n
        return await self._act(a)

    async def _do_take(self, s):
        p = _xy(s)
        a = {"op": "take", "x": p[0], "y": p[1]}
        if s.get("item"):
            a["item"] = s["item"]
        if s.get("count"):
            a["count"] = int(s["count"])
        return await self._act(a)

    async def _do_empty_chest(self, s):
        return await self._do_take({"x": s["x"], "y": s["y"]})

    async def _do_refuel(self, s):
        p = _xy(s)
        inv = await self.refresh_inventory()
        fuel = s.get("fuel") or next((f for f in FUELS if inv.get(f, 0) >= 5), None)
        n = int(s.get("count", 20))
        if not fuel:
            fuel = "coal"
            r = await self.ensure("coal", n)
            if not r.get("ok"):
                r = await self._act({"op": "mine", "name": "coal", "count": n}, timeout=400)
                if not r.get("ok"):
                    return {"ok": False, "msg": f"no fuel: {r.get('msg')}", "missing": {"coal": n}}
        return await self._act({"op": "insert", "x": p[0], "y": p[1], "item": fuel,
                                "count": min(n, max(1, (await self.refresh_inventory()).get(fuel, n)))})

    async def _do_power(self, s):
        """Poles from a grid pole (given, or the nearest powered one the mod knows) to the machine."""
        p = _xy(s)
        src = s.get("from")
        if not src:
            sc = await self.g.scan(center=p, radius=64)
            live = {g["id"] for g in (sc.get("grids") or []) if isinstance(g, dict) and (g.get("cap_w") or 0) > 0}
            poles = [e for e in (sc.get("ents") or []) if e.get("t") == "electric-pole" and e.get("net") in live
                     and not e.get("ghost")]
            poles.sort(key=lambda e: (e["x"] - p[0]) ** 2 + (e["y"] - p[1]) ** 2)
            src = [poles[0]["x"], poles[0]["y"]] if poles else None
        if not src:
            return {"ok": False, "msg": "no pole found to run power from; give from=[x,y]"}
        return await self._act({"op": "connect", "item": s.get("item", "small-electric-pole"),
                                "from": list(src), "to": [p[0], p[1]]}, timeout=420)

    async def _do_research(self, s):
        return await self._act({"op": "research", "tech": s["tech"], **({"first": True} if s.get("first") else {})})

    async def _do_wait(self, s):
        await asyncio.sleep(min(float(s.get("seconds", 5)), 120))
        return {"ok": True, "msg": f"waited {s.get('seconds', 5)}s"}

    async def _do_say(self, s):
        await self.g.say(str(s.get("text", "")))
        return {"ok": True, "msg": "said"}

    async def _do_move(self, s):
        p = _xy(s)
        return await self._act({"op": "move", "x": p[0], "y": p[1]}, timeout=300)

    async def _do_configure(self, s):
        a = {"op": "configure", **{k: v for k, v in s.items() if k != "do"}}
        return await self._act(a)

    async def _do_limit(self, s):
        return await self._act({"op": "limit", "x": s["x"], "y": s["y"], "slots": s.get("slots")})

    # ------------------------------------------------------------------ building plans
    async def _do_ghosts(self, s):
        ents = []
        for e in s.get("entities") or []:
            q = {"name": e["name"], "x": float(e["x"]), "y": float(e["y"])}
            if e.get("direction"):
                q["direction"] = e["direction"]
            if e.get("recipe"):
                q["recipe"] = e["recipe"]
            ents.append(q)
        if not ents:
            return {"ok": False, "msg": "ghosts needs entities"}
        r = await self._act({"op": "blueprint", "entities": ents})
        if not r.get("ok"):
            return r
        xs = [e["x"] for e in ents]
        ys = [e["y"] for e in ents]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        rad = max(max(xs) - min(xs), max(ys) - min(ys)) / 2 + 4
        placed = r.get("ghosts")
        await self.stock(r.get("needs") or {})
        b = await self._do_build_ghosts({"x": cx, "y": cy, "radius": rad})
        b["msg"] = f"planned {placed} of {len(ents)}; " + (b.get("msg") or "")
        if placed is not None and placed < len(ents):
            b["msg"] += f" ({len(ents) - placed} couldn't be planned: blocked or invalid spots)"
        return b

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
                return {"ok": True, "msg": f"built {built_total} ghosts; none left", "built": built_total}
            if last_left is not None and left >= last_left and not r.get("built"):
                return {"ok": False, "msg": f"built {built_total}; {left} ghosts left that I can't build "
                        f"(missing {missing})", "missing": missing, "built": built_total, "left": left}
            last_left = left
            fails = []
            for item, n in missing.items():
                fr = await self._act({"op": "fetch", "item": item, "count": int(n)}, timeout=400)
                if not fr.get("ok"):
                    fails.append(f"{item}: {fr.get('msg')}")
            if fails and len(fails) == len(missing):
                return {"ok": False, "msg": f"built {built_total}; {left} left; can't get items: " + "; ".join(fails),
                        "missing": missing, "built": built_total, "left": left}
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
            for e in s.get("entities") or []:
                add(e.get("name"), 1)
        elif d == "insert" and s.get("item") not in FUELS:
            add(s.get("item"), s.get("count") or 1)
        elif d == "connect" and isinstance(s.get("from"), (list, tuple)) and isinstance(s.get("to"), (list, tuple)):
            dist = abs(s["from"][0] - s["to"][0]) + abs(s["from"][1] - s["to"][1])
            item = s.get("item")
            if item and "pole" in item:
                add(item, dist / 5 + 2)
            elif item:
                add(item, dist * 1.2 + 4)
    return need
