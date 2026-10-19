"""The hands: a deterministic controller that carries out one order with a character, no model in the loop.

Given an order (docs/architecture.md) it lays the plan's ghosts, then repeats until the zone is done:
clear blockers marked for removal, refuel burners, fetch missing items from chests, craft what's still missing,
build ghosts. It's idempotent (it always re-reads the zone from the game), so it can stop and resume anywhere.
When it can't make progress after a few local retries it returns an exception describing exactly what's wrong;
the actor's model handles that, or the order goes back to the coordinator.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from .rcon import GameError

log = logging.getLogger("crew.controller")

LOCAL_RETRIES = 3       # cycles without progress before giving up with an exception
MAX_CYCLES = 60         # hard stop for one fulfill call
BATCH_TIMEOUT = 240     # seconds to wait for one batch of jobs (long walks)
FUEL_PER_BURNER = 10
FUELS = ("coal", "wood", "solid-fuel")
RAW = {"stone", "coal", "iron-ore", "copper-ore", "wood"}  # gather these by hand when no chest has them
MINE_CAP = 100


@dataclass
class Outcome:
    ok: bool
    kind: str                      # done | exception
    detail: str = ""
    built: int = 0
    blocker: dict = field(default_factory=dict)


class Controller:
    def __init__(self, link, agent_name: str, progress=None, stop=None, deadline: float | None = None):
        self.link = link
        self.name = agent_name
        self.progress = progress or (lambda **kw: None)
        self.stop = stop or (lambda: False)  # e.g. a human talked to the agent
        self.deadline = deadline
        self.log: list[str] = []

    def _out_of_time(self) -> bool:
        return self.stop() or (self.deadline is not None and time.time() > self.deadline)

    # ------------------------------------------------------------------ helpers
    async def _do(self, actions: list[dict], timeout: float = BATCH_TIMEOUT) -> list[dict]:
        """Queue actions on our character and wait for all their results."""
        if not actions:
            return []
        d = await self.link.call("act", agent=self.name, actions=actions)
        ids = d.get("job_ids") or []
        futs = [self.link.job_future(i) for i in ids]
        try:
            done = await asyncio.wait_for(asyncio.gather(*futs, return_exceptions=True), timeout)
        except asyncio.TimeoutError:
            await self.link.call("cancel", agent=self.name, reason="controller timeout")
            return [{"ok": False, "msg": "timed out"}]
        out = [r if isinstance(r, dict) else {"ok": False, "msg": repr(r)} for r in done]
        for r in out:
            if not r.get("ok"):
                self.log.append(f"{r.get('op', '?')}: {r.get('msg', '')}"[:200])
        return out

    async def _inventory(self) -> dict:
        me = await self.link.call("self", agent=self.name)
        self.pos = me.get("position") or [0, 0]
        return me.get("inventory") or {}

    async def zone(self, zone) -> dict:
        return await self.link.call("zone", zone=zone)

    # ------------------------------------------------------------------ plan
    async def lay_plan(self, order) -> str:
        """Put the plan's ghosts in the zone (once). Returns a short note."""
        plan = order.plan or {}
        kind = plan.get("kind", "ghosts")
        if order.laid or kind in ("ghosts", "task", "connect"):
            return ""
        if kind == "paste":
            from .late_tools import load_copies
            lib = load_copies(order.state_dir)
            c = lib.get(plan.get("name", ""))
            string = c["string"] if c else plan.get("string")
            if not string:
                raise ValueError(f"no copy named {plan.get('name')!r}")
            d = await self.link.call("paste", string=string, x=plan["x"], y=plan["y"],
                                     direction=plan.get("direction", "north"))
            order.laid = True
            return f"pasted {d['placed']}/{d['of']} ghosts"
        if kind == "stamp":
            from . import blueprint_lib
            ents = blueprint_lib.stamp_entities(plan["name"], plan["x"], plan["y"], plan.get("rotation", 0),
                                                plan.get("anchor"))
            r = await self._do([{"op": "blueprint", "entities": ents}], 30)
            order.laid = True
            return r[0].get("msg", "") if r else ""
        raise ValueError(f"unknown plan kind {kind!r}")

    # ------------------------------------------------------------------ sourcing
    async def source(self, missing: dict, zone) -> dict:
        """Take missing items from the nearest chests outside the zone. Returns what's still missing."""
        if not missing:
            return {}
        await self._inventory()
        d = await self.link.call("sources", items=list(missing), x=self.pos[0], y=self.pos[1], exclude=zone)
        src = d.get("sources") or {}
        actions = []
        left = dict(missing)
        for item, need in missing.items():
            for c in (src.get(item) or []):
                if need <= 0:
                    break
                n = min(need, c["n"])
                actions.append({"op": "take", "x": c["p"][0], "y": c["p"][1], "item": item, "count": n})
                need -= n
            left[item] = need
        if actions:
            # one chest per action; a failed take shouldn't skip the others
            for a in actions:
                await self._do([a])
        inv = await self._inventory()
        return {k: v - inv.get(k, 0) for k, v in missing.items() if v - inv.get(k, 0) > 0}

    async def craft(self, missing: dict) -> dict:
        """Hand-craft what's missing (the mod crafts intermediates too). Returns what's still missing."""
        for item, n in missing.items():
            await self._do([{"op": "craft", "recipe": item, "count": n}], timeout=180)
        inv = await self._inventory()
        return {k: v - inv.get(k, 0) for k, v in missing.items() if v - inv.get(k, 0) > 0}

    async def gather(self, missing: dict) -> dict:
        """Mine raw resources nobody has stored (stone for furnaces, coal for fuel), like a player would."""
        acts = [{"op": "mine", "name": "tree" if k == "wood" else k, "count": min(v, MINE_CAP)}
                for k, v in missing.items() if k in RAW and v > 0]
        if acts:
            await self._do(acts, timeout=300)
        inv = await self._inventory()
        return {k: v - inv.get(k, 0) for k, v in missing.items() if v - inv.get(k, 0) > 0}

    async def raw_for(self, missing: dict) -> dict:
        """Ingredients of the missing items (one level), to fetch when crafting fails."""
        need: dict[str, int] = {}
        for item, n in missing.items():
            try:
                r = await self.link.call("recipes", agent=self.name, filter=item, detail=True)
            except GameError:
                continue
            rec = (r.get("recipes") or {}).get(item) if isinstance(r.get("recipes"), dict) else None
            if not rec:
                continue
            for ing, k in (rec.get("ingredients") or {}).items():
                need[ing] = need.get(ing, 0) + k * n
        return need

    # ------------------------------------------------------------------ the loop
    async def fulfill(self, order) -> Outcome:
        zone = order.zone
        built_total, stall, cycles = 0, 0, 0
        t0 = time.time()
        note = await self.lay_plan(order)
        if note:
            self.log.append(note)
        last_missing: dict = {}
        while cycles < MAX_CYCLES:
            cycles += 1
            if self._out_of_time():
                z = await self.zone(zone)
                return Outcome(False, "paused", f"paused with {z.get('ghosts')} ghosts left (built {built_total}); "
                               "call build again to continue", built_total)
            z = await self.zone(zone)
            ghosts = z.get("ghosts", 0)
            self.progress(ghosts_left=ghosts, built=built_total)
            progressed = False

            blockers = z.get("blockers") or []
            if blockers:
                acts = [{"op": "mine", "x": b["p"][0], "y": b["p"][1]} for b in blockers[:20]]
                res = await self._do(acts)
                progressed |= any(r.get("ok") for r in res)

            low = z.get("low_fuel") or []
            if low:
                inv = await self._inventory()
                fuel = next((f for f in FUELS if inv.get(f, 0) >= FUEL_PER_BURNER), None)
                if not fuel:
                    left = await self.source({"coal": FUEL_PER_BURNER * len(low)}, zone)
                    if left:
                        await self.gather(left)
                    inv = await self._inventory()
                    fuel = next((f for f in FUELS if inv.get(f, 0) >= FUEL_PER_BURNER), None)
                if fuel:
                    acts = [{"op": "insert", "x": e["p"][0], "y": e["p"][1], "item": fuel, "count": FUEL_PER_BURNER}
                            for e in low[: max(1, inv.get(fuel, 0) // FUEL_PER_BURNER)]]
                    res = await self._do(acts)
                    progressed |= any(r.get("ok") for r in res)

            if ghosts == 0:
                if not low or progressed or stall >= LOCAL_RETRIES:
                    return Outcome(True, "done", f"zone complete; built {built_total} in {int(time.time() - t0)}s",
                                   built_total)
                stall += 1
                continue

            inv = await self._inventory()
            need = z.get("needs") or {}
            missing = {k: v - inv.get(k, 0) for k, v in need.items() if v - inv.get(k, 0) > 0}
            if missing:
                missing = await self.source(missing, zone)
            if missing:
                missing = await self.craft(missing)
            if missing:
                raw = await self.raw_for(missing)
                if raw:
                    inv = await self._inventory()
                    raw_missing = {k: v - inv.get(k, 0) for k, v in raw.items() if v - inv.get(k, 0) > 0}
                    raw_missing = await self.source(raw_missing, zone)
                    if raw_missing:
                        await self.gather(raw_missing)
                    missing = await self.craft(missing)
            last_missing = missing

            res = await self._do([{"op": "build_ghosts", "zone": zone}])
            data = (res[0].get("data") or {}) if res else {}
            n = int(data.get("built") or 0)
            built_total += n
            progressed |= n > 0
            stall = 0 if progressed else stall + 1
            if stall >= LOCAL_RETRIES:
                z = await self.zone(zone)
                if z.get("ghosts", 0) == 0:
                    continue
                blocker = {"ghosts_left": z.get("ghosts"), "left_by_name": z.get("by_name"),
                           "missing_items": last_missing, "example_ghosts": z.get("ghost_at"),
                           "recent_failures": self.log[-5:]}
                why = (f"missing {last_missing} (no chest has them and I can't craft them)" if last_missing else
                       "ghosts I can't build (unreachable, or blocked by something not marked for removal)")
                return Outcome(False, "exception", f"stuck with {z.get('ghosts')} ghosts left: {why}", built_total,
                               blocker)
        return Outcome(False, "exception", "ran out of cycles", built_total, {"recent_failures": self.log[-5:]})

    LINE_ITEMS = ("transport-belt", "fast-transport-belt", "express-transport-belt", "turbo-transport-belt", "pipe",
                  "small-electric-pole", "medium-electric-pole", "big-electric-pole", "substation")

    async def connect(self, order) -> Outcome:
        """A line from A to B. `item` is what's placed; a cargo name (coal, copper-plate) means a belt carrying it.
        Routes the router can't find in one go are split into legs (up to 4)."""
        p = order.plan
        item = p.get("item", "transport-belt")
        note = ""
        if item not in self.LINE_ITEMS:
            note = f" (a belt for {item})"
            item = "pipe" if item in ("water", "crude-oil", "petroleum-gas", "light-oil", "heavy-oil", "lubricant",
                                      "sulfuric-acid", "steam") else "transport-belt"
        legs = [(list(p["from"]), list(p["to"]))]
        done_legs, tiles = [], 0
        while legs:
            a, b = legs.pop(0)
            dist = abs(a[0] - b[0]) + abs(a[1] - b[1])
            per = 1 if ("belt" in item or item == "pipe") else max(1, dist // 6)
            want = int(dist * 1.4) + 4 if per == 1 else per + 2
            inv = await self._inventory()
            if inv.get(item, 0) < want:
                left = await self.source({item: want - inv.get(item, 0)}, order.zone)
                if left:
                    left = await self.craft(left)
            args = {"op": "connect", "item": item, "from": a, "to": b}
            if not legs:  # only the final leg carries the caller's end options
                for k in ("end_direction", "join"):
                    if k in p:
                        args[k] = p[k]
            res = await self._do([args])
            r = res[0] if res else {"ok": False, "msg": "no result"}
            if r.get("ok"):
                done_legs.append(r.get("msg", ""))
                continue
            msg = str(r.get("msg", ""))
            if "no route" in msg and len(done_legs) + len(legs) < 4 and dist > 30:
                mid = [round((a[0] + b[0]) / 2) + 0.5, round((a[1] + b[1]) / 2) + 0.5]
                legs[:0] = [(a, mid), (mid, b)]
                self.log.append(f"split {a}->{b} at {mid}")
                continue
            return Outcome(False, "exception", f"line{note} failed after {len(done_legs)} leg(s): {msg}", 0,
                           {"recent_failures": self.log[-5:]})
        return Outcome(True, "done", f"line{note} in {len(done_legs)} leg(s): " + " | ".join(done_legs)[:300], 1)
