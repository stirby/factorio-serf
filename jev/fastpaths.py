"""The actor's own paths for common orders, tried before the planner (see docs/DESIGN.md, "Fast paths"): a row of
machines off belts (one or two stages, optionally sent on), belting items from A to B, mining a patch, copies of the last
build, upgrades, research. In each, Jev reads the order (jev/quick*.py, jev/decide.py) and code lays it out; the usual
plan runner builds and checks it. A path returns True (done), False (cancelled), None (not that kind of order: the
planner gets it untouched) or a string (tried, and what happened: the planner takes it from there). After a success,
the planner may review the result in the background (asynchronous guidance)."""
from __future__ import annotations

import asyncio
import json
import math
import re
from typing import TYPE_CHECKING

from . import craft, decide, quickbelt, quickbuild, quickcopy, quickmine
from .thinker import Request
from .world import fmt_xy

if TYPE_CHECKING:
    from .actor import Order


QUEUE_WORDS = re.compile(r"\b(queue|then|remove|reorder|prerequisites?|in this order|followed by)\b", re.I)


class FastPaths:
    """Mixed into Actor: uses its world(), runner, jev, thinker, say(), log() and the plan runner/checker."""

    async def _quick(self, o: Order) -> bool | str | None:
        """A row of machines making one product off belts that are already there (jev/quickbuild.py): Jev reads the
        order, code lays out and checks the row, the plan runner builds and verifies it. None: not that kind of order,
        the planner gets it untouched. A string: tried and it didn't work (what happened)."""
        try:
            w = await self.world(o.focus, 32)
            opts = quickbuild.options(w, self.recipes, o.points)
            if not opts and any(not ln.items and ln.length >= 4 and any(
                    min(math.hypot(ln.start[0] - q[0], ln.start[1] - q[1]),
                        math.hypot(ln.end[0] - q[0], ln.end[1] - q[1])) <= 12 for q in o.points) for ln in w.lines):
                await asyncio.sleep(6)  # belts only just starting up may not carry anything yet
                w = await self.world(o.focus, 32)
                opts = quickbuild.options(w, self.recipes, o.points)
            if not opts:
                return None
            r = await quickbuild.read_order(self.jev, o.text, sorted(opts), quickbuild.carried(w, o.points))
            self.log({"kind": "quickbuild", "order": o.id, "options": sorted(opts)[:40],
                      **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items()}})
            far = any(math.hypot(q[0] - o.focus[0], q[1] - o.focus[1]) > 40 for q in o.points)
            # "...and send the plates on a belt to the chest at [gps]": the row puts its output on a belt, and the
            # belt fast path takes that belt on to the named place
            away = [q for q in o.points if math.hypot(q[0] - o.focus[0], q[1] - o.focus[1]) > 12]
            send_to = None
            belt_to_place = bool(away and quickbuild.OUTPUT_BELT.search(o.text))
            if ((r["elsewhere"] >= 0.6 or (belt_to_place and r["elsewhere"] >= 0.3)) and away and r["chain"] < 0.7
                    and r["product_p"] >= 0.55 and r["build"] >= 0.5 and r["product"] not in (None, "none_of_these")):
                send_to = away[0]  # the first other place named (later ones are often supplies or a grid pole)
                r["output"] = "belt"
            elif not quickbuild.accept(r, far, one_point=len(o.points) == 1, belt_to_place=belt_to_place):
                return None
            opt = opts[r["product"]]
            if r["output"] == "belt" and len(opt["lines"]) == 2:
                return None
            n = (int(r["count"]) if r["count"] not in (None, "not_said") and r["count_p"] >= 0.5
                 else quickbuild.DEFAULT_COUNT[opt["machine"]])
            layout = None
            feeders, fcenter, base = [], None, 0
            if opt.get("feeder"):
                if send_to or r["output"] == "belt":
                    return None
                k = quickbuild.feeders_needed(self.recipes, r["product"], opt["feeder"]["recipe"], n)
                fit = quickbuild.feeders_that_fit(opt["lines"][0].length, k, n)
                if fit < k:  # a short belt: fewer feeders (a slower row) rather than none
                    self.log({"kind": "quickbuild_feeders", "order": o.id, "needed": k, "fit": fit})
                    k = fit
                feeders, fcenter = quickbuild.feeder_layout(w, opt, k)
                if any((e := w.at(x["x"], x["y"])) is not None and e["u"] > 0 or w.off_view(x["x"], x["y"])
                       for x in feeders):
                    self.log({"kind": "quickbuild_skip", "order": o.id, "why": "no room for the feeders"})
                    return None
                base = 4 * k + 1  # the main row starts past the feeders
            for skip in (2, 4, 7, 11):
                step = quickbuild.row_step(w, opt, r["product"], n, base + skip)
                if r["output"] == "belt":
                    step["output"] = "belt"
                if opt.get("feeder"):  # the row goes on the side away from the feeder belt
                    d = opt["lines"][0].direction
                    toward = quickbuild.LEFT_OF[d] if opt["feeder"]["left"] else \
                        {v: k_ for k_, v in quickbuild.LEFT_OF.items()}[d]
                    step["side"] = {"north": "south", "south": "north", "east": "west", "west": "east"}[toward]
                ents, info, side, _ = await self.runner.row_layout(step)
                # our own buildings in the way (trees and rocks get cleared by the builder)
                bad = [x for x in ents if (e := w.at(x["x"], x["y"])) is not None and e["u"] > 0]
                if not bad and not any(w.off_view(x["x"], x["y"]) for x in ents):
                    step["side"] = side
                    layout = (step, ents, info)
                    break
            if not layout:
                self.log({"kind": "quickbuild_skip", "order": o.id, "why": "no free spot along the belt"})
                return None
            dst = None
            if send_to:
                end = layout[2].get("output_belt_end")
                dst = end and quickbelt.sink(await self.world(send_to, 16), send_to, end)
                self.log({"kind": "quickbuild_send", "order": o.id, "from": end, "to": dst})
                if not dst:
                    return None
        except Exception as e:  # noqa: BLE001
            self.log({"kind": "error", "where": "quickbuild", "error": repr(e)})
            return None
        step, ents, info = layout
        machines = [x for x in ents if x["name"] == opt["machine"]]
        xs, ys = [m["x"] for m in machines], [m["y"] for m in machines]
        center = [(min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2]
        word = quickbuild.SAY.get(r["product"], r["product"].replace("-", " "))
        mword = {"assembling-machine-1": "assembler", "stone-furnace": "furnace"}.get(opt["machine"], opt["machine"])
        what = f"{'an' if n == 1 and mword[0] in 'aeiou' else ('a' if n == 1 else n)} {mword}{'s' if n > 1 else ''} making {word}"
        expect = [{"check": "working", "count": max(1, (n + 1) // 2), "near": center,
                   "radius": max(max(xs) - min(xs), max(ys) - min(ys)) / 2 + 2}]
        if opt["machine"] != "stone-furnace":
            expect[0]["recipe"] = r["product"]
        chest = next((x for x in ents if x["name"] == "iron-chest"), None)
        if chest:
            expect.append({"check": "has_item", "x": chest["x"], "y": chest["y"], "item": r["product"]})
        plan = {"goal": f"{what} off the belt at {fmt_xy(step['belt'])}, "
                        f"{'into chests' if step['output'] == 'chest' else 'onto an output belt'}",
                "steps": [step], "expect": expect}
        if feeders:
            fw = quickbuild.SAY.get(opt["feeder"]["recipe"], opt["feeder"]["recipe"].replace("-", " "))
            plan["steps"] = [{"do": "ghosts", "entities": feeders},
                             {"do": "power", "x": fcenter[0], "y": fcenter[1], "radius": 2 * len(feeders) // 4 + 4},
                             step]
            plan["goal"] += f", with {len(feeders) // 4} assembler(s) making {fw} onto that belt"
            what += f" (and {len(feeders) // 4} making {fw} for them)"
        if dst:
            end = info["output_belt_end"]
            plan["steps"] += [{"do": "connect", "item": "transport-belt", "from": end, "to": dst["to"]}]
            plan["steps"] += self._delivery_steps(dst, r["product"])
            plan["expect"] += quickbelt.delivered(dst, r["product"])
            plan["goal"] += f", belted on to {dst['what']}"
            what += f", belted to {dst['what']}"
        return await self._run_quick(o, plan, what)

    def _delivery_steps(self, dst: dict, item: str, fast: bool = False) -> list[dict]:
        """What goes at a belt's far end (quickbelt.sink): an inserter into the machine or chest when there isn't one
        (burner for fuel without power nearby, else electric and powered). fast: the flow is more than a basic
        inserter moves (~50 a minute), so a fast inserter."""
        if dst["kind"] != "new_inserter":
            return []
        ins = dict(dst["inserter"])
        if not dst.get("electric") and item not in ("coal", "wood", "solid-fuel"):
            ins["name"] = "inserter"  # a burner inserter moving non-fuel would starve: power it instead
        if fast and ins["name"] != "burner-inserter":
            ins["name"] = "fast-inserter"
        steps = [{"do": "place", **ins}]
        if ins["name"] == "burner-inserter":
            steps.append({"do": "refuel", "x": ins["x"], "y": ins["y"], "count": 5})
        else:  # a pole in wire reach doesn't mean one whose supply area covers it (a no-op when it's powered)
            steps.append({"do": "power", "x": ins["x"], "y": ins["y"], "radius": 1})
        return steps

    async def _run_quick(self, o: Order, plan: dict, what: str) -> bool | str:
        """Run and check a plan the actor made itself; a string says what happened if it didn't work."""
        o.quick = True
        o.quick_plan = plan
        self.log({"kind": "quick_plan", "order": o.id, "plan": plan})
        await self.say(f"on it: {what}")
        ok, report = await self._run_plan(o, plan)
        if o.status == "cancelled":
            return False
        if ok:
            verified, vreport = await self._verify(o, plan)
            if verified:
                self.metrics["fast_path"] += 1
                await self.say(f"done: {what}")
                await self._ask_review(o, plan)
                return True
            report = vreport
        o.history.append(report)
        return f"it tried: {plan['goal']}. {report}"

    async def _ask_review(self, o: Order, plan: dict) -> None:
        """Asynchronous guidance: the planner looks at what the actor built on its own, when it has nothing else to
        do. A plan it sends back becomes a follow-up order; usually it just ends its turn."""
        th = self.thinker
        if not (self.review_quick and th and not th.stats.usage_limited and th.queue.empty() and th.current is None
                and o.focus):
            return
        try:
            # the whole build, not a fixed radius round the order's point (that cut a furnace's output inserter off
            # and Opus "fixed" it by placing one that was already there)
            pts = o.built_pts or [o.focus]
            xs, ys = [q[0] for q in pts], [q[1] for q in pts]
            c = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
            r = int(max(max(xs) - min(xs), max(ys) - min(ys)) / 2 + 6)
            sm = (await self.world(c, min(r, 40))).summary(coords=True)
        except Exception:  # noqa: BLE001
            return
        th.ask(Request("review", (
            f"For order {o.id} from {o.speaker} (\"{o.text}\") the actor built this by itself, without you, and its "
            f"checks passed: {plan.get('goal')}.\nArea now: {json.dumps(sm, separators=(',', ':'))[:14000]}\n"
            "Look only for a real problem with how it answers the order (wrong product, wrong place, something that "
            "will stop working soon). Before deciding something is missing, look with the area tool centred on that "
            "spot (summaries of big areas can leave things out). If there is a real problem, submit a plan that fixes "
            "just that. If it's fine, end your turn without a plan and without chatting."), o.id))
        self.log({"kind": "review_asked", "order": o.id})

    async def _mine_near(self, o: Order, full: bool = False):
        """Unit numbers (or, with full, {unit: layout entry}) of what the character built within 48 tiles of the
        order's point; None when the order has no point."""
        if not o.focus:
            return None
        try:
            w = await self.world(o.focus, 48)
        except Exception:  # noqa: BLE001
            return None
        mine = {u: e for u, e in w.ents.items() if u > 0 and e.get("by") == self.name}
        return quickcopy.layout_entries(mine) if full else set(mine)

    async def _quick_copy(self, o: Order) -> bool | str | None:
        """'Two more just like it at [gps] and [gps]': the last build, copied where the new points sit the same way
        the earlier order's points did (jev/quickcopy.py)."""
        prev = next((x for x in reversed(self.orders) if x is not o and x.status == "done" and x.built_pts
                     and x.points), None)
        if prev and prev.copy_of:  # "now four more" after "two more": copies of the same unit, not of the pair
            prev = prev.copy_of
        if not prev:
            return None
        if not quickcopy.COPY_WORDS.search(o.text):
            return None
        unit = prev.built  # exactly what that order built
        pts = [(e["x"], e["y"]) for e in unit] or prev.built_pts + [prev.focus]
        xs, ys = [q[0] for q in pts], [q[1] for q in pts]
        box = (min(xs) - 1, min(ys) - 1, max(xs) + 1, max(ys) + 1)
        # (at least 2: a one-row build's box is about 4 across, and 0 switched the one-point copy off)
        ds = quickcopy.offsets(prev.points, o.points, spacing=max(2, min(box[2] - box[0], box[3] - box[1]) - 4))
        if not ds:
            self.log({"kind": "quickcopy_skip", "order": o.id, "from_order": prev.id, "why": "points don't match"})
            return None
        try:
            p = await quickcopy.read_order(self.jev, o.text)
            self.log({"kind": "quickcopy", "order": o.id, "p": round(p, 3), "from_order": prev.id, "offsets": ds})
            if p < 0.7:
                return None
            c = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
            if unit:
                ents = unit
            else:
                w = await self.world(c, int(max(box[2] - box[0], box[3] - box[1]) / 2 + 4))
                ents = quickcopy.built_by(w, box, self.name)
            if not ents:
                return None
        except Exception as e:  # noqa: BLE001
            self.log({"kind": "error", "where": "quickcopy", "error": repr(e)})
            return None
        steps = []
        for d in ds:
            steps.append({"do": "ghosts", "entities": quickcopy.shifted(ents, d)})
            steps.append({"do": "power", "x": c[0] + d[0], "y": c[1] + d[1],
                          "radius": max(box[2] - box[0], box[3] - box[1]) / 2})
        n = len(ds)
        plan = {"goal": f"{n} cop{'y' if n == 1 else 'ies'} of order {prev.id}'s build ({len(ents)} pieces each)",
                "steps": steps}
        machines = [e for e in ents if e["name"] in ("assembling-machine-1", "assembling-machine-2",
                                                      "stone-furnace", "steel-furnace", "electric-furnace")]
        if machines:
            mx = [e["x"] for e in machines]
            my = [e["y"] for e in machines]
            mc = ((min(mx) + max(mx)) / 2, (min(my) + max(my)) / 2)
            r = max(max(mx) - min(mx), max(my) - min(my)) / 2 + 2
            plan["expect"] = [{"check": "working", "count": max(1, len(machines) // 2), "near": [mc[0] + d[0], mc[1] + d[1]],
                               "radius": r} for d in ds]
        o.copy_of = prev
        return await self._run_quick(o, plan, f"{n} more like the last one")

    async def _quick_mine(self, o: Order) -> bool | str | None:
        """'Set up an iron mine on the patch at [gps] and belt the ore to [gps]' (jev/quickmine.py)."""
        try:
            # the patch is whichever named point has ore ("we need copper at [chest]: drills on [patch]" names the
            # chest first)
            at, ores = o.focus, []
            for pt in o.points[:3] or [o.focus]:
                w = await self.world(pt, 24)
                ores = sorted(k for k in (w.res or {}) if k in ("iron-ore", "copper-ore", "coal", "stone",
                                                                "uranium-ore"))
                if ores:
                    at = pt
                    break
            if not ores:
                return None
            p, ore, op = await quickmine.read_order(self.jev, o.text, ores)
            self.log({"kind": "quickmine", "order": o.id, "p": round(p, 3), "ore": ore, "ore_p": round(op, 3)})
            if p < 0.7 or not ore or op < 0.6:
                return None
            q = await self.g.call("query", what="ore", name=ore, x=at[0], y=at[1], radius=24)
            tiles = {tuple(t) for t in q.get("tiles") or []}
            away = [x for x in o.points if math.hypot(x[0] - at[0], x[1] - at[1]) > 12]
            # the first other place it names: "...belt it to the chest at [A]. Drills are in the chest at [B]" (the
            # farthest one was the supply chest in a mining variant)
            dest = away[0] if away else None
            # small poles if they can be had (wood and copper), else medium ones from storage
            stock = dict((await self.g.call("query", what="materials", outputs=True)).get("materials") or {})
            for k, v in (await self.runner.refresh_inventory()).items():
                stock[k] = stock.get(k, 0) + v
            pole = ("small-electric-pole" if craft.most("small-electric-pole", stock, self.recipes, 12) >= 8
                    else "medium-electric-pole")
            lay = quickmine.best_layout(tiles, quickmine.wanted_drills(o.text), dest or (at[0] + 100, at[1]), pole)
            if not lay:
                return None
            if any((e := w.at(x["x"], x["y"])) is not None and e["u"] > 0 for x in lay["ents"]):
                self.log({"kind": "quickmine_skip", "order": o.id, "why": "our buildings on the patch"})
                return None
            dst = quickbelt.sink(await self.world(dest, 16), dest, lay["belt_end"]) if dest else None
            if dest and not dst:
                return None
        except Exception as e:  # noqa: BLE001
            self.log({"kind": "error", "where": "quickmine", "error": repr(e)})
            return None
        dx = [e["x"] for e in lay["ents"]]
        dy = [e["y"] for e in lay["ents"]]
        c = lay["center"]
        steps = [{"do": "ghosts", "entities": lay["ents"]},
                 {"do": "power", "x": c[0], "y": c[1], "radius": max(max(dx) - min(dx), max(dy) - min(dy)) / 2 + 1}]
        expect = [{"check": "working", "count": max(1, lay["drills"] // 2), "near": c,
                   "radius": max(max(dx) - min(dx), max(dy) - min(dy)) / 2 + 2}]
        word = ore.replace("-", " ")
        what = f"{lay['drills']} drills on the {word}"
        if dst:
            steps.append({"do": "connect", "item": "transport-belt", "from": lay["belt_end"], "to": dst["to"]})
            # six drills make ~180 ore a minute; a basic inserter into a chest moves ~50 and the drills back up
            fast = lay["drills"] * 30 > 45 and craft.most("fast-inserter", stock, self.recipes, 1) >= 1
            steps += self._delivery_steps(dst, ore, fast=fast)
            expect += quickbelt.delivered(dst, ore)
            what += f", belted to {dst['what']}"
        else:
            expect.append({"check": "belt_carries", "x": lay["belt_end"][0], "y": lay["belt_end"][1], "item": ore})
        plan = {"goal": what, "steps": steps, "expect": expect}
        return await self._run_quick(o, plan, what)

    async def _quick_upgrade(self, o: Order) -> bool | str | None:
        """'Swap the belts on that line for red ones': Jev names the tier (and line or spot), code upgrades."""
        try:
            into, p, p_line = await decide.upgrade(self.jev, o.text)
            self.log({"kind": "quick_upgrade", "order": o.id, "into": into, "p": round(p, 3),
                      "line": round(p_line, 3)})
            if not into or p < 0.7:
                return None
            step = {"do": "upgrade", "into": into}
            if p_line >= 0.6 and "belt" in into:
                step["line"] = list(o.focus)
            else:
                step.update({"x": o.focus[0], "y": o.focus[1], "cluster": True})
        except Exception as e:  # noqa: BLE001
            self.log({"kind": "error", "where": "quick_upgrade", "error": repr(e)})
            return None
        what = decide.UPGRADES[into].split(" (")[0].split(",")[0]
        return await self._run_quick(o, {"goal": f"swapped for {what} at {fmt_xy(o.focus)}", "steps": [step]},
                                     f"swapping to {what}")

    async def _quick_research(self, o: Order) -> bool:
        """"Research X": code lists what can be researched now, Jev picks the one the order names, code queues it."""
        try:
            if QUEUE_WORDS.search(o.text):
                # a queue to arrange ("after X research Y, then Z; remove W"): more than one tech, the planner's
                self.log({"kind": "quick_research_skip", "order": o.id, "why": "several techs or a queue"})
                return False
            t = await self.g.call("techs", agent=self.name)
            techs = [x for x in t.get("available") or [] if x.get("name")]
            if not techs:
                return False
            named = {x["name"] for x in techs if re.search(re.escape(x["name"]).replace("\\-", "[- ]"), o.text, re.I)}
            if len(named) >= 2:
                self.log({"kind": "quick_research_skip", "order": o.id, "why": f"names {sorted(named)}"})
                return False
            tech, p = await decide.research(self.jev, o.text, techs)
            self.log({"kind": "quick_research", "order": o.id, "tech": tech, "p": round(p, 3)})
            if not tech or p < 0.7:
                return False
            r = await self.runner.run({"do": "research", "tech": tech, "fallback": False})
            if not r.get("ok"):
                return False
            self.metrics["fast_path"] += 1
            await self.say(f"queued research: {tech.replace('-', ' ')}")
            return True
        except Exception as e:  # noqa: BLE001
            self.log({"kind": "error", "where": "quick_research", "error": repr(e)})
            return False

    async def _quick_belt(self, o: Order) -> bool | str | None:
        """Belt items from one named place to another (jev/quickbelt.py): Jev says it's that kind of order, code
        finds the two ends. None: not that kind, or the ends aren't clear; the planner gets it untouched."""
        try:
            a, b = o.points[0], o.points[1]
            if math.hypot(a[0] - b[0], a[1] - b[1]) < 8:
                return None
            p = await quickbelt.read_order(self.jev, o.text)
            self.log({"kind": "quickbelt", "order": o.id, "p": round(p, 3)})
            # Jev's doubt counts less when what's there says it: a belt ending with items on it at one point and
            # something that takes them at the other (Jev reads 'get that coal over to the boiler from the belt' at
            # 0.6-0.75 from run to run)
            if p < 0.5:
                return None
            ep = None
            for k in range(2):
                wa, wb = await self.world(a, 16), await self.world(b, 16)
                ep = quickbelt.endpoints(wa, a, wb, b)
                self.log({"kind": "quickbelt_ends", "order": o.id, "ends": ep})
                if ep or k or not (quickbelt.empty_source(wa, a) or quickbelt.empty_source(wb, b)):
                    break
                await asyncio.sleep(6)  # a source belt only just starting up may not carry anything yet
            if not ep:
                return None
        except Exception as e:  # noqa: BLE001
            self.log({"kind": "error", "where": "quickbelt", "error": repr(e)})
            return None
        steps = [{"do": "connect", "item": "transport-belt", "from": ep["from"], "to": ep["to"]}]
        steps += self._delivery_steps(ep, ep["item"])
        word = quickbuild.SAY.get(ep["item"], ep["item"].replace("-", " "))
        plan = {"goal": f"a belt carrying {word} from {ep['from'][0]:g},{ep['from'][1]:g} to {ep['what']}",
                "steps": steps, "expect": quickbelt.delivered(ep, ep["item"])}
        return await self._run_quick(o, plan, f"belting {word} to {ep['what']}")
