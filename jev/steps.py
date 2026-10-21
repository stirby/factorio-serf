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
MINEABLE = {"wood": "tree", "iron-ore": "iron-ore", "copper-ore": "copper-ore", "stone": "stone", "coal": "coal"}
PLACE_ITEM = {"straight-rail": "rail", "curved-rail-a": "rail", "curved-rail-b": "rail"}


def unplaced(asked: list[dict], r: dict) -> list[dict]:
    """The requested ghosts the game refused for a real reason (not "an identical one already stands there"), each
    with that reason under "_why"."""
    failed = r.get("failed") or []
    if isinstance(failed, dict):
        failed = list(failed.values())
    out = []
    for f in failed:
        if not isinstance(f, dict) or f.get("why") == "same":
            continue
        fx, fy = float(f.get("x", 1e9)), float(f.get("y", 1e9))
        e = next((a for a in asked if abs(a["x"] - fx) < 0.01 and abs(a["y"] - fy) < 0.01), None)
        if e:
            out.append({**e, "_why": f.get("why")})
    return out


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
        self.recipes: dict = {}
        self.fuel_ahead = 0  # fuel the running plan's remaining refuel steps will use (set by the actor)

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
        for i in list(fails):  # storage couldn't: try belts and crafting from belt items
            r = await self.ensure(i, short[i])
            if r.get("ok"):
                fails.pop(i)
        self.log_fn({"t": t0, "kind": "stock", "need": short, "fails": fails, "secs": round(time.time() - t0, 1)})
        return fails

    async def ensure(self, item: str, count: int) -> dict:
        """Have at least count of item: storage first, then hand-crafting (the mod's fetch does both, fetching
        ingredients from storage too). If that fails: grab it, or its ingredients, off belts, then craft."""
        inv = await self.refresh_inventory()
        if inv.get(item, 0) >= count:
            return {"ok": True, "msg": f"have {inv[item]} {item}"}
        r = await self._act({"op": "fetch", "item": item, "count": count}, timeout=300)
        if r.get("ok"):
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
                            await self._act({"op": "mine", "name": MINEABLE[ing],
                                             "count": max(1, -(-short_ing // 4)) if ing == "wood" else short_ing},
                                            timeout=600)
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
        for k in ("end_direction", "join"):
            if s.get(k) is not None:
                a[k] = s[k]
        return await self._act(a, timeout=420)

    async def _do_fetch(self, s):
        return await self._act({"op": "fetch", "item": s["item"], "count": int(s.get("count", 1))}, timeout=300)

    async def _do_craft(self, s):
        """Have `count` more of an item: the mod's fetch takes it from storage or hand-crafts it, fetching the
        ingredients from storage first when they aren't carried."""
        inv = await self.refresh_inventory()
        item, n = s["recipe"], int(s.get("count", 1))
        return await self._act({"op": "fetch", "item": item, "count": inv.get(item, 0) + n}, timeout=400)

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
        """Make room in a full chest: take part of it (enough to unblock what feeds it, without filling the pocket
        with junk like stone)."""
        return await self._do_take({"x": s["x"], "y": s["y"], "count": int(s.get("count", 100))})

    async def _do_refuel(self, s):
        p = _xy(s)
        inv = await self.refresh_inventory()
        n = int(s.get("count", 20))
        fuel = s.get("fuel") or next((f for f in FUELS if inv.get(f, 0) >= 5), None) or "coal"
        if inv.get(fuel, 0) < min(n, 5):
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
        return await self._act({"op": "insert", "x": p[0], "y": p[1], "item": fuel, "count": max(1, min(n, have))})

    async def _do_power(self, s):
        """Make sure every electric machine within `radius` (default 6) of x,y is on a grid that has generators:
        bridge from the nearest live pole to the closest unpowered pole (or machine), rescan, repeat."""
        p = _xy(s)
        rad = float(s.get("radius", 6))
        item = s.get("item", "small-electric-pole")
        msgs = []
        prev_off, stuck = None, 0
        for rnd in range(10):
            sc = await self.g.scan(center=p, radius=int(max(rad + 40, 48)))
            ents = [e for e in (sc.get("ents") or []) if not e.get("ghost")]
            live = {g["id"] for g in (sc.get("grids") or []) if isinstance(g, dict) and (g.get("cap_w") or 0) > 0}
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
                return await self._long_power(p, s)
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
            if not r.get("ok") and "already connected" not in str(r.get("msg")):
                return {"ok": False, "msg": f"long power line leg {i}/{legs} failed: {r.get('msg')}"}
            cur = tgt
        return {"ok": True, "msg": f"ran {item} {dist:.0f} tiles from the grid pole at {src[0]:g},{src[1]:g} in "
                                   f"{legs} leg(s)"}

    async def _do_research(self, s):
        """Queue a tech. tech="cheapest" (or a trigger/finished tech that fails) picks the cheapest lab tech whose
        packs are all in `packs` (default red and green)."""
        tech = s.get("tech") or "cheapest"
        if tech != "cheapest":
            r = await self._act({"op": "research", "tech": tech, **({"first": True} if s.get("first") else {})})
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
        b["msg"] = f"planned {placed} of {len(ents)}; " + (b.get("msg") or "")
        return ghost_result(b, s)

    async def row_layout(self, s: dict):
        """The entities of a row step (needs the belt's direction from the game; picks a free side if none given)."""
        from .rowgen import DIRS, SIZE, row_entities
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
            S = SIZE.get(s.get("machine", "assembling-machine-1"), 3)
            blocked = sum(1 for x in ents if w.at(x["x"], x["y"]) is not None)
            if best is None or blocked < best[0]:
                best = (blocked, ents, info, sd)
        return best[1], best[2], best[3], best[0]

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
            # our own earlier belts in the way (a failed or reset attempt): pick them up and route on a clean area.
            # Never touches what players built.
            mine = [e for e in w.ents.values() if e.get("t") in ("transport-belt", "underground-belt", "splitter")
                    and e.get("by") == self.g.name]
            if mine:
                me = await self.g.me()
                pos = me.get("position") or (cx, cy)
                mine.sort(key=lambda e: (e["x"] - pos[0]) ** 2 + (e["y"] - pos[1]) ** 2)
                for e in mine:
                    await self._act({"op": "mine", "x": e["x"], "y": e["y"]}, timeout=60)
                self.log_fn({"t": time.time(), "kind": "route_cleared", "n": len(mine)})
                return await self._do_route({**s, "_cleared": True})
        if not ents:
            return {"ok": False, "msg": f"router: {info}"}
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
                    for e in [e for e in (sc.get("ents") or []) if e.get("ghost")]:
                        a = {"op": "place", "name": e["n"], "x": e["x"], "y": e["y"]}
                        if e.get("d"):
                            a["direction"] = e["d"]
                        if e.get("ug"):
                            a["type"] = e["ug"]
                        pr = await self._act(a, timeout=90)
                        if pr.get("ok"):
                            built_total += 1
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
