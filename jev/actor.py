"""The actor: one character, driven by code + Jev, with Opus (the thinker) asynchronous.

Loops:
  chat   every player line -> Jev triage (for me? new job / more info / question / stop / chatter; which playbook)
  work   one order at a time: fast playbook if one fits (fix, deliver), else ask the thinker for a plan; run the
         plan's steps (code), recover from failed steps (Jev picks: retry / get items / skip / replan), verify the
         goal (code checks, Jev when the goal is only words), report in chat. A plan that doesn't reach its goal goes
         back to the thinker with a report.
The thinker never blocks the chat loop, and the work loop only waits on it when it has nothing else to do.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import craft, decide, quickbelt, quickbuild, quickcopy
from .game import Game
from .lint import lint, plan_points
from .steps import Runner, describe, parse_missing, plan_needs
from .thinker import Request, Thinker
from .typesafe import Jev, JevError
from .world import World, fmt_xy, items_words

log = logging.getLogger("jev.actor")

GPS = re.compile(r"\[gps=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)(?:,[^\]]*)?\]")
PAIR = re.compile(r"([\w-]+): \[gps=(-?[\d.]+),(-?[\d.]+)\] to \[gps=(-?[\d.]+),(-?[\d.]+)\]")
RAW = {"iron-ore", "copper-ore", "coal", "stone", "wood", "uranium-ore"}


@dataclass
class Order:
    id: int
    text: str
    speaker: str
    playbook: str
    points: list[tuple[float, float]]
    t: float = field(default_factory=time.time)
    status: str = "new"  # new | working | thinking | done | failed | cancelled
    notes: list[str] = field(default_factory=list)
    plans: int = 0
    history: list[str] = field(default_factory=list)
    speaker_at: tuple | None = None
    interrupt: str | None = None  # a player correction that should stop the running plan
    watch_what: list | None = None  # trouble the planner wants watched for after it's done
    next_plan: dict | None = None  # a revised plan that arrived while the old one was running
    queued_plans: list = field(default_factory=list)  # next parts of a big order (plans submitted with more=true)
    running_more: bool = False  # the plan running now is a part with more to come
    quick: bool = False  # built by the actor's quick-build path (no planner)
    belt_len: float = 0  # the longest new belt any of its plans laid (items need time to travel it)
    built_pts: list = field(default_factory=list)  # where its plans built (for "two more just like it")

    @property
    def focus(self):
        return self.points[0] if self.points else None


BUILD_OPS = ("ghosts", "block", "design", "stamp", "place", "build_ghosts", "route", "row", "connect", "merge_lanes")


def fixed_words(fixed: list[str]) -> str:
    """'refuelled the furnace at 1,2; refuelled the furnace at 3,4; ...' -> 'refuelled the furnace at 1,2 (and 3
    more like it)': the same fix on several machines is one line in chat."""
    out: dict = {}
    for t in dict.fromkeys(fixed):
        key = re.sub(r"-?\d+(\.\d+)?,-?\d+(\.\d+)?", "#", t)
        out.setdefault(key, []).append(t)
    return "; ".join(v[0] + (f" (and {len(v) - 1} more like it)" if len(v) > 1 else "") for v in out.values())


class Actor:
    def __init__(self, game: Game, jev: Jev, workdir: Path, name: str = "serf", think: bool = True,
                 thinker_effort: str | None = None):
        self.g, self.jev, self.name = game, jev, name
        self.workdir = workdir
        self.log_path = workdir / "actor.jsonl"
        self.runner = Runner(game, self.log)
        self.orders: list[Order] = []
        self.current: Order | None = None
        self.wake = asyncio.Event()
        self.next_id = 1
        self.last_said: str | None = None
        self.recipes: dict = {}
        self.items: list[str] = []
        self._plan_waiters: dict[int, asyncio.Future] = {}
        self.think_enabled = think
        self.prefetch = True
        self.quick_build = True
        self.thinker = Thinker(name, self._thinker_tools(), self._on_plan, workdir / "thinker", self.log,
                               effort=thinker_effort, lint_fn=self._lint) if think else None
        self.metrics = {"orders": 0, "fast_path": 0, "plans": 0, "steps_ok": 0, "steps_failed": 0,
                        "recoveries": {}, "verified": 0, "unverified": 0, "chat_lines": 0}
        self._tasks: list[asyncio.Task] = []
        self.watches: list[dict] = []  # areas this character built: kept running while it's idle
        self.stocked: list[dict] = []  # chests a plan filled by hand: refilled when they run low
        self.watch_every = 45.0
        self.busy_since: float | None = None
        self.idle_secs = 0.0
        self._idle_mark = time.time()

    # ------------------------------------------------------------------ logging / chat
    def log(self, rec: dict) -> None:
        rec.setdefault("t", time.time())
        self.workdir.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, "a") as f:
            f.write(json.dumps(rec, default=str) + "\n")

    async def say(self, text: str) -> None:
        self.last_said = text
        self.log({"kind": "say", "text": text})
        await self.g.say(text)

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        rec = await self.g.call("recipes", agent=self.name, detail=True)
        self.recipes = rec.get("recipes") if isinstance(rec, dict) else {}
        self.runner.recipes = self.recipes
        self.items = (await self.g.call("query", what="items")).get("items") or []
        if self.thinker:
            await self.thinker.start()
        self._tasks = [asyncio.create_task(self._chat_loop()), asyncio.create_task(self._work_loop()),
                       asyncio.create_task(self._watch_loop())]
        self.log({"kind": "start", "recipes": len(self.recipes), "items": len(self.items)})

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except BaseException:
                pass
        if self.thinker:
            await self.thinker.stop()

    def _set_busy(self, busy: bool) -> None:
        now = time.time()
        if busy and self.busy_since is None:
            self.idle_secs += now - self._idle_mark
            self.busy_since = now
        elif not busy and self.busy_since is not None:
            self.busy_since = None
            self._idle_mark = now

    # ------------------------------------------------------------------ chat
    async def _chat_loop(self) -> None:
        while True:
            c = await self.g.chat.get()
            try:
                await self._on_chat(c)
            except Exception as e:  # noqa: BLE001
                log.exception("chat handling failed")
                self.log({"kind": "error", "where": "chat", "error": repr(e)})

    async def _on_chat(self, c: dict) -> None:
        speaker, msg = str(c.get("player") or "?"), str(c.get("message") or "")
        if speaker == self.name or not msg.strip():
            return
        self.metrics["chat_lines"] += 1
        explicit = f"@{self.name}".lower() in msg.lower() or "@all" in msg.lower()
        doing = self.current.text if self.current and self.current.status in ("working", "thinking") else None
        try:
            call = await decide.chat(self.jev, self.name, speaker, msg, doing, self.last_said)
        except JevError as e:
            self.log({"kind": "error", "where": "jev chat", "error": str(e)})
            # Jev is unreachable: an explicit @ is an order for the planner, and a plain "stop" still stops
            stop = re.match(r"^\W*(@\S+\s*)?(stop|cancel|halt|wait)\b", msg.strip(), re.I)
            call = decide.ChatCall(1.0 if explicit or stop else 0.0, "stop" if stop else "new_job", 0.0, "plan", 0.0)
        self.log({"kind": "chat", "speaker": speaker, "msg": msg, "addressed": round(call.addressed, 3),
                  "kind_": call.kind, "kind_conf": round(call.kind_conf, 3), "playbook": call.playbook,
                  "playbook_conf": round(call.playbook_conf, 3)})
        if not explicit and call.addressed < 0.5:
            return
        kind = call.kind
        last = self.orders[-1] if self.orders else None
        reopen = False
        if kind in ("more_info",) and not doing and last and last.status in ("done", "failed") \
                and time.time() - last.t < 1800:
            try:
                p_nd = await decide.not_done(self.jev, last.text, msg)
            except JevError:
                p_nd = 0.0
            self.log({"kind": "not_done", "order": last.id, "p": round(p_nd, 3)})
            reopen = p_nd >= 0.6
        if reopen:
            # "not done yet" / a correction after it finished: reopen that order with the note
            last.notes.append(f"{speaker}: {msg}")
            last.status = "new"
            self.log({"kind": "reopen", "order": last.id})
            self.wake.set()
            return
        if kind == "new_job" or (kind == "more_info" and not doing and call.kind_conf < 0.5
                                 and call.playbook_conf >= 0.8):
            pts = [(float(a), float(b)) for a, b in GPS.findall(msg)]
            o = Order(self.next_id, msg, speaker, call.playbook if call.playbook_conf >= 0.6 else "plan", pts)
            sp = c.get("position")
            if isinstance(sp, (list, tuple)) and len(sp) == 2:
                o.speaker_at = (float(sp[0]), float(sp[1]))
            self.next_id += 1
            self.orders.append(o)
            self.metrics["orders"] += 1
            if doing:
                waiting = sum(1 for x in self.orders if x.status == "new")
                await self.say(f"got it, I'll do that next" if waiting <= 1 else f"got it, that's #{waiting} in my queue")
            self.wake.set()
        elif kind in ("more_info", "approval") and self.current:
            self.current.notes.append(f"{speaker}: {msg}")
            if self.thinker and self.current.status == "thinking":
                self.thinker.ask(Request("report", f"The player added: \"{msg}\"", self.current.id))
            elif self.current.status == "working" and kind == "more_info":
                try:
                    p = await decide.changes_plan(self.jev, self.current.text, msg)
                except JevError:
                    p = 0.0
                self.log({"kind": "changes_plan", "order": self.current.id, "p": round(p, 3)})
                if p >= 0.6:
                    self.current.interrupt = f"{speaker}: {msg}"
                    await self.g.cancel("player changed the job")
        elif kind == "stop":
            if self.current and self.current.status in ("working", "thinking"):
                self.current.status = "cancelled"
            await self.g.cancel("player said stop")
            await self.say("ok, stopped")
        elif kind == "question" and await self._quick_answer(msg):
            pass
        elif kind == "question" and self.thinker:
            self.thinker.ask(Request("question", f"{speaker} asked in chat: \"{msg}\"\nAnswer briefly with the say "
                                     "tool (look first only if you need to). Don't submit a plan unless they asked "
                                     "for work.", self.current.id if self.current else None))

    async def _quick_answer(self, msg: str) -> bool:
        """Status/where/inventory questions answered by code; anything else goes to the thinker."""
        try:
            qt, conf = await decide.question_type(self.jev, msg)
        except JevError:
            return False
        self.log({"kind": "question", "type": qt, "conf": round(conf, 3)})
        if conf < 0.7 or qt == "other":
            return False
        me = await self.g.me()
        if qt == "where":
            await self.say(f"I'm at [gps={me['position'][0]:.0f},{me['position'][1]:.0f}]")
        elif qt == "carrying":
            await self.say("carrying " + items_words(me.get("inventory"), 8))
        else:
            o = self.current

            def brief(t: str) -> str:
                t = re.sub(r"@\S+", "", t).strip()
                t = re.split(r"[?.!]", t)[0].strip()
                return t[:90]
            if o and o.status in ("working", "thinking"):
                step = "planning it" if o.status == "thinking" else "building it"
                await self.say(f"working on: {brief(o.text)} ({step})")
            elif o:
                await self.say(f"free now. Last job ({brief(o.text)}) is {o.status}")
            else:
                await self.say("nothing right now, free for a job")
        return True

    # ------------------------------------------------------------------ work
    async def _work_loop(self) -> None:
        while True:
            o = next((x for x in self.orders if x.status == "new"), None)
            if not o:
                self._set_busy(False)
                self.wake.clear()
                await self.wake.wait()
                continue
            self.current = o
            o.status = "working"
            self._set_busy(True)
            t0 = time.time()
            try:
                ok = await self._do_order(o)
                if o.status != "cancelled":
                    o.status = "done" if ok else "failed"
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log.exception("order failed")
                self.log({"kind": "error", "where": "order", "error": repr(e)})
                o.status = "failed"
            self.log({"kind": "order_end", "order": o.id, "status": o.status, "secs": round(time.time() - t0, 1),
                      "plans": o.plans})
            if (o.status == "done" and o.focus and o.speaker != self.name
                    and (o.plans > 0 or o.quick or o.playbook == "fix")):
                self._add_watch(o)
            if self.thinker and (o.plans >= 2 or (o.status == "failed" and o.plans >= 1)):
                self.thinker.ask(Request("lesson", f"Order {o.id} (\"{o.text}\") took {o.plans} plans and ended "
                                         f"{o.status}. What went wrong: " + " | ".join(h[:300] for h in o.history[-3:]) +
                                         "\nWrite ONE general rule (no coordinates, max 2 sentences) that would have "
                                         "made your first plan work, with save_lesson. Then end your turn. Don't submit "
                                         "a plan.", None))
            await self.g.status(text="")

    async def _do_order(self, o: Order) -> bool:
        self.log({"kind": "order", "order": o.id, "text": o.text, "playbook": o.playbook, "points": o.points})
        if time.time() - getattr(self, "_recipes_t", 0) > 120:  # research unlocks recipes during a game
            try:
                rec = await self.g.call("recipes", agent=self.name, detail=True)
                if isinstance(rec, dict) and rec.get("recipes"):
                    self.recipes = rec["recipes"]
                    self.runner.recipes = self.recipes
                self._recipes_t = time.time()
            except Exception:  # noqa: BLE001
                pass
        await self.g.status(text=o.text[:100])
        if o.playbook == "fix" and o.focus:
            if o.speaker != self.name:
                await self.say("on it, taking a look")
            wide = await decide.scope(self.jev, o.text)
            self.log({"kind": "scope", "order": o.id, "wide": round(wide, 3)})
            r = await (self._fix_wide(o) if wide >= 0.6 else self._fix(o))
            if r is True:
                return True
            if o.speaker == self.name:  # a watch found it: don't spend a plan on it, stop watching that spot
                self.watches = [w for w in self.watches if w["at"] != o.focus]
                self.log({"kind": "watch_drop", "at": o.focus, "why": str(r)[:300]})
                return False
            report = r or "I found no fault I could fix on my own."
            return await self._planned(o, f"New order from {o.speaker}: \"{o.text}\"\n\nThe actor's quick look: {report}")
        if o.playbook == "deliver" and o.focus:
            r = await self._deliver(o)
            if r is True:
                return True
            return await self._planned(o, f"New order from {o.speaker}: \"{o.text}\"\n\nThe actor tried to deliver it "
                                          f"itself and couldn't: {r}")
        pairs = PAIR.findall(o.text)
        if len(pairs) >= 2:
            # an order that lists belt start/end pairs: the router lays them all, no planning needed
            await self.say(f"on it: routing {len(pairs)} belts")
            r = await self._route(o, pairs)
            if r is True:
                return True
            return await self._planned(o, f"New order from {o.speaker}: \"{o.text}\"\n\nThe actor tried the belt "
                                          f"router itself: {r}")
        if re.search(r"\b(upgrade|swap|replace|in place of|instead of)", o.text, re.I) and o.focus and self.quick_build:
            r = await self._quick_upgrade(o)
            if r is True or r is False:
                return r
            if isinstance(r, str):
                return await self._planned(o, f"New order from {o.speaker}: \"{o.text}\"\n\nThe actor tried the "
                                              f"swap itself and it didn't finish: {r}")
        if re.search(r"\b(research|tech|unlock)", o.text, re.I) and not o.points:
            r = await self._quick_research(o)
            if r:
                return True
        if o.points and self.quick_build:
            r = await self._quick_copy(o)
            if r is True or r is False:
                return r
            if isinstance(r, str):
                return await self._planned(o, f"New order from {o.speaker}: \"{o.text}\"\n\nThe actor tried to copy "
                                              f"the earlier build itself and it didn't work out: {r}\nWhat it built is "
                                              "still there.")
        if o.focus and self.quick_build:
            r = await self._quick(o)
            if r is True:
                return True
            if r is False:
                return False
            if isinstance(r, str):
                return await self._planned(o, f"New order from {o.speaker}: \"{o.text}\"\n\nThe actor tried a quick "
                                              f"build itself and it didn't work out: {r}\nWhat it built is still there.")
        if len(o.points) >= 2 and self.quick_build:
            r = await self._quick_belt(o)
            if r is True:
                return True
            if r is False:
                return False
            if isinstance(r, str):
                return await self._planned(o, f"New order from {o.speaker}: \"{o.text}\"\n\nThe actor tried to "
                                              f"belt it over itself and it didn't work out: {r}\nWhat it built is "
                                              "still there.")
        await self.say("on it")
        return await self._planned(o, f"New order from {o.speaker}: \"{o.text}\"")

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
            if (r["elsewhere"] >= 0.6 and away and r["chain"] < 0.4 and r["product_p"] >= 0.55 and r["build"] >= 0.5
                    and r["product"] not in (None, "none_of_these")):
                send_to = max(away, key=lambda q: math.hypot(q[0] - o.focus[0], q[1] - o.focus[1]))
                r["output"] = "belt"
            elif not quickbuild.accept(r, far):
                return None
            opt = opts[r["product"]]
            if r["output"] == "belt" and len(opt["lines"]) == 2:
                return None
            n = (int(r["count"]) if r["count"] not in (None, "not_said") and r["count_p"] >= 0.5
                 else quickbuild.DEFAULT_COUNT[opt["machine"]])
            layout = None
            for skip in (2, 4, 7, 11):
                step = quickbuild.row_step(w, opt, r["product"], n, skip)
                if r["output"] == "belt":
                    step["output"] = "belt"
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
        if dst:
            end = info["output_belt_end"]
            plan["steps"] += [{"do": "connect", "item": "transport-belt", "from": end, "to": dst["to"]}]
            plan["steps"] += self._delivery_steps(dst, r["product"])
            plan["expect"].append({"check": "belt_carries", "x": dst["to"][0], "y": dst["to"][1],
                                   "item": r["product"]})
            plan["goal"] += f", belted on to {dst['what']}"
            what += f", belted to {dst['what']}"
        return await self._run_quick(o, plan, what)

    def _delivery_steps(self, dst: dict, item: str) -> list[dict]:
        """What goes at a belt's far end (quickbelt.sink): an inserter into the machine or chest when there isn't one
        (burner for fuel without power nearby, else electric and powered)."""
        if dst["kind"] != "new_inserter":
            return []
        ins = dict(dst["inserter"])
        if not dst.get("electric") and item not in ("coal", "wood", "solid-fuel"):
            ins["name"] = "inserter"  # a burner inserter moving non-fuel would starve: power it instead
        steps = [{"do": "place", **ins}]
        if ins["name"] == "burner-inserter":
            steps.append({"do": "refuel", "x": ins["x"], "y": ins["y"], "count": 5})
        elif not dst.get("electric"):
            steps.append({"do": "power", "x": ins["x"], "y": ins["y"], "radius": 1})
        return steps

    async def _run_quick(self, o: Order, plan: dict, what: str) -> bool | str:
        """Run and check a plan the actor made itself; a string says what happened if it didn't work."""
        o.quick = True
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
                return True
            report = vreport
        o.history.append(report)
        return f"it tried: {plan['goal']}. {report}"

    async def _quick_copy(self, o: Order) -> bool | str | None:
        """'Two more just like it at [gps] and [gps]': the last build, copied where the new points sit the same way
        the earlier order's points did (jev/quickcopy.py)."""
        prev = next((x for x in reversed(self.orders) if x is not o and x.status == "done" and x.built_pts
                     and x.points), None)
        if not prev:
            return None
        xs = [q[0] for q in prev.built_pts + [prev.focus]]  # (not every point it named: a supply chest or grid
        ys = [q[1] for q in prev.built_pts + [prev.focus]]  # pole far off isn't part of the build)
        box = (min(xs) - 3, min(ys) - 3, max(xs) + 3, max(ys) + 3)
        ds = quickcopy.offsets(prev.points, o.points, spacing=min(box[2] - box[0], box[3] - box[1]) - 4)
        if not ds:
            return None
        try:
            p = await quickcopy.read_order(self.jev, o.text)
            self.log({"kind": "quickcopy", "order": o.id, "p": round(p, 3), "from_order": prev.id, "offsets": ds})
            if p < 0.7:
                return None
            c = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
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
        return await self._run_quick(o, plan, f"{n} more like the last one")

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
            t = await self.g.call("techs", agent=self.name)
            techs = [x for x in t.get("available") or [] if x.get("name")]
            if not techs:
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
            if p < 0.7:
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
                "steps": steps, "expect": [{"check": "belt_carries", "x": ep["to"][0], "y": ep["to"][1],
                                            "item": ep["item"]}]}
        return await self._run_quick(o, plan, f"belting {word} to {ep['what']}")

    async def _route(self, o: Order, pairs) -> bool | str:
        step = {"do": "route", "pairs": [{"name": n, "from": [float(a), float(b)], "to": [float(c), float(d)]}
                                         for n, a, b, c, d in pairs]}
        # "You have 240 transport-belt, 220 underground-belt; ..." -> the kit (it may not be in the pocket yet)
        m = re.search(r"[Yy]ou have ([^;.]*\d[^;.]*)", o.text)
        if m:
            kit = {it: int(n) for n, it in re.findall(r"(\d+) ([a-z][a-z-]+)", m.group(1)) if "belt" in it}
            if kit:
                step["kit"] = kit
        r = await self.runner.run(step)
        self.log({"kind": "step", "order": o.id, "i": 0, "step": {"do": "route", "pairs": len(pairs)},
                  "ok": r.get("ok"), "msg": r.get("msg")})
        if not r.get("ok"):
            return str(r.get("msg"))
        self.metrics["fast_path"] += 1
        await self.say("belts are down, items should start flowing")
        return True

    # ------------------------------------------------------------------ watching what it built
    WATCH_KINDS = {"no_fuel", "output_full", "chest_full", "no_power", "boiler_fuel", "belt_reversed", "belt_gap"}
    HEAL_KINDS = {"no_fuel", "boiler_fuel", "no_power"}  # fixed without asking when a plan's checks fail

    def _add_watch(self, o: Order) -> None:
        conds = [c for c in (getattr(o, "watch_what", None) or []) if isinstance(c, str)][:5]
        for p in (o.points[:3] or [o.focus]):
            if any(abs(w["at"][0] - p[0]) < 8 and abs(w["at"][1] - p[1]) < 8 for w in self.watches):
                continue
            self.watches.append({"at": p, "radius": 16, "what": conds, "order": o.id, "t": time.time()})
        self.watches = self.watches[-12:]

    async def _watch_loop(self) -> None:
        """While idle: look at the areas it built; fix what code can see (fuel, full chests, power, belts) and what
        the planner asked to watch for (Jev judges those)."""
        while True:
            await asyncio.sleep(self.watch_every)
            if any(x.status in ("new", "working", "thinking") for x in self.orders):
                continue
            # chests a plan stocked by hand (e.g. coal for a boiler or plastic plant): top them up before they run dry
            for c in list(self.stocked):
                try:
                    w = await self.world((c["x"], c["y"]), 2)
                    e = w.at(c["x"], c["y"])
                    if not e:
                        self.stocked.remove(c)
                        continue
                    have = (e.get("inv") or {}).get(c["item"], 0)
                    if have < c["count"] * 0.2:
                        self.log({"kind": "restock", "chest": [c["x"], c["y"]], "item": c["item"], "have": have})
                        await self.say(f"topping up {c['item']} in the chest at [gps={c['x']:.0f},{c['y']:.0f}]")
                        await self.runner.run({"do": "insert", "x": c["x"], "y": c["y"], "item": c["item"],
                                               "count": c["count"] - have})
                except Exception as ex:  # noqa: BLE001
                    self.log({"kind": "error", "where": "restock", "error": repr(ex)})
            if not self.watches:
                continue
            try:
                for wt in list(self.watches):
                    w = await self.world(wt["at"], wt["radius"])
                    # a machine whose output nothing takes is full by design (no output inserter): not a fault here
                    fl = [f for f in w.faults() if f["kind"] in self.WATCH_KINDS and f.get("fixes") and f.get("u")
                          and abs(f["at"][0] - wt["at"][0]) <= wt["radius"] and abs(f["at"][1] - wt["at"][1]) <= wt["radius"]
                          and not (f["kind"] == "output_full" and f["fixes"][0].get("do") == "take")]
                    # the grid powering what it built running out of boiler fuel: keep the lights on (wherever the
                    # boilers are)
                    dark = [f for f in w.faults() if f["kind"] == "boiler_fuel" and f.get("boilers")]
                    if dark and not fl:
                        self.log({"kind": "watch_power", "at": wt["at"], "what": dark[0]["text"]})
                        await self.say(f"noticed: {dark[0]['text']}. refuelling them")
                        await self._refuel_grid(w, dark[0]["grid"])
                        continue
                    found = fl[0]["text"] if fl else None
                    if not found and wt["what"] and time.time() - wt.get("warned", 0) > 600:
                        # a condition the planner asked to watch, judged by Jev: tell the players, don't act on it
                        # (nothing code can see to fix there)
                        ps = await decide.trouble(self.jev, wt["what"], w.summary(coords=False, focus=wt["at"]))
                        hit = [c for c, p in zip(wt["what"], ps) if p >= 0.8]
                        if hit:
                            wt["warned"] = time.time()
                            self.log({"kind": "watch_warn", "at": wt["at"], "what": hit[0]})
                            await self.say(f"heads up: near [gps={wt['at'][0]:.0f},{wt['at'][1]:.0f}] it looks like "
                                           f"{hit[0]}")
                            break
                    if found:
                        self.log({"kind": "watch_hit", "at": wt["at"], "what": found})
                        o = Order(self.next_id, f"(noticed) {found}", self.name, "fix", [wt["at"]])
                        self.next_id += 1
                        self.orders.append(o)
                        await self.say(f"noticed: {found}. fixing it")
                        self.wake.set()
                        break
            except Exception as e:  # noqa: BLE001
                self.log({"kind": "error", "where": "watch", "error": repr(e)})

    # ------------------------------------------------------------------ thinker
    def _thinker_tools(self) -> dict:
        async def area(a):
            x, y = float(a["x"]), float(a["y"])
            r = int(min(64, max(6, int(a.get("radius", 20)))))
            w = await self.world((x, y), r)
            out = w.summary(coords=True)
            fl = w.faults()
            if fl:
                out["faults"] = [{"problem": f["text"], "fixes": [x.get("text") for x in f.get("fixes", [])]}
                                 for f in fl[:20]]
            out["center"] = fmt_xy((x, y))
            out["radius"] = r
            return json.dumps(out, separators=(",", ":"))

        async def find(a):
            name = a["name"]
            out = {}
            if name == "water":
                out = await self.g.call("find", agent=self.name, name="water", limit=int(a.get("limit", 3)))
            else:
                if name in self.items:
                    try:
                        out["stored"] = await self.g.call("stored", agent=self.name, item=name)
                    except Exception as e:  # noqa: BLE001
                        out["stored"] = repr(e)
                try:
                    out["world"] = await self.g.call("find", agent=self.name, name=name, limit=int(a.get("limit", 5)))
                except Exception as e:  # noqa: BLE001
                    out["world"] = str(e)
            return json.dumps(out, separators=(",", ":"))

        async def recipe(a):
            r = self.recipes.get(a["name"])
            if not r:
                close = [n for n in self.recipes if a["name"] in n][:10]
                return f"no enabled recipe {a['name']!r}" + (f"; similar: {close}" if close else "")
            return json.dumps({a["name"]: r})

        async def free_space(a):
            return json.dumps(await self.g.call("find_space", agent=self.name, w=int(a["w"]), h=int(a["h"]),
                                                x=float(a["x"]), y=float(a["y"])), separators=(",", ":"))

        async def me(a):
            m = await self.g.me()
            return json.dumps({k: m.get(k) for k in ("position", "inventory", "job", "crafting", "reach")},
                              separators=(",", ":"))

        async def say(a):
            await self.say(str(a.get("text", "")))
            return "said"

        async def techs(a):
            t = await self.g.call("techs", agent=self.name)
            try:
                w = await self.g.call("world", agent=self.name)
                t = {"researching": w.get("research"), "queue": w.get("research_queue"), **t}
            except Exception:  # noqa: BLE001
                pass
            return json.dumps(t, separators=(",", ":"))[:8000]
        async def production(a):
            return json.dumps(await self.g.call("production", agent=self.name), separators=(",", ":"))[:6000]

        async def diagnose(a):
            return json.dumps(await self.g.call("diagnose", item=a.get("item", "iron-plate"), surface="nauvis"),
                              separators=(",", ":"))[:8000]
        return {"area": area, "find": find, "recipe": recipe, "free_space": free_space, "me": me, "say": say,
                "techs": techs, "production": production, "diagnose": diagnose}

    async def _lint(self, plan: dict) -> list[str]:
        pts = plan_points(plan.get("steps") or [])
        if not pts:
            return []
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        r = int(min(96, max(max(xs) - min(xs), max(ys) - min(ys)) / 2 + 8))
        w = await self.world((cx, cy), r)
        on_belts = {i for ln in w.lines for i in (ln.items or {})}
        return lint(plan.get("steps") or [], w, await self.available(on_belts), self.recipes)

    async def available(self, extra: set[str] | None = None) -> set[str]:
        """Items the character can get: in storage, inventory or on nearby belts, or hand-craftable from those."""
        stock = {k for k, n in await self.materials() if n > 0} | set(extra or ())
        me = await self.g.me()
        stock |= {k for k, n in (me.get("inventory") or {}).items() if n > 0}
        hand = {"crafting", "advanced-crafting", "electronics", "pressing", "crafting-with-fluid-or-metallurgy"}
        memo: dict[str, bool] = {}

        def ok(item: str, depth: int = 0) -> bool:
            if item in stock:
                return True
            if item in memo:
                return memo[item]
            memo[item] = False
            r = self.recipes.get(item)
            if not r or depth > 4 or (r.get("category") or "crafting") not in hand:
                return False
            memo[item] = all(ok(i, depth + 1) for i in (r.get("ingredients") or {}))
            return memo[item]
        return {i for i in set(self.items) if ok(i)}

    async def _on_plan(self, plan: dict, req: Request | None) -> None:
        oid = req.order_id if req else None
        self.log({"kind": "plan", "order": oid, "plan": plan})
        fut = self._plan_waiters.pop(oid, None) if oid is not None else None
        if fut and not fut.done():
            fut.set_result(plan)
        elif (oid is not None and self.current and self.current.id == oid and self.current.running_more
              and not plan.get("no_plan")):
            # the next part of a big order, designed while the previous part was being built
            self.current.queued_plans.append(plan)
            self.log({"kind": "plan_queued", "order": oid, "parts_waiting": len(self.current.queued_plans)})
        elif (oid is not None and self.current and self.current.id == oid and self.current.status == "working"
              and not plan.get("no_plan") and plan.get("steps")):
            # the planner revised the plan (e.g. after a correction) while the old one runs: switch at the next step
            self.current.next_plan = plan
            self.current.interrupt = "the planner revised the plan"
            self.log({"kind": "plan_swap", "order": oid})
            await self.g.cancel("plan revised")

    async def _prefetch(self, o: Order) -> None:
        """While the thinker plans a new order: Jev guesses the kind of build, code fetches that kit from storage
        (only what storage has; nothing is crafted on speculation). The plan's own stock-up then finds most of it."""
        try:
            k, conf = await decide.kit(self.jev, o.text)
            self.log({"kind": "prefetch", "order": o.id, "kit": k, "conf": round(conf, 3)})
            if k == "none" or conf < 0.5:
                return
            stock = dict(await self.materials())
            want = {i: n for i, n in decide.KITS[k]["items"].items() if stock.get(i, 0) >= n}
            if "assembling-machine-2" in want:
                want.pop("assembling-machine-1", None)
            if want:
                await self.runner.stock(want)
        except Exception as e:  # noqa: BLE001
            self.log({"kind": "error", "where": "prefetch", "error": repr(e)})
        # head for the site while the planner is still thinking (the plan's first steps start there anyway)
        try:
            if o.focus and o.status == "thinking":
                me = await self.g.me()
                pos = me.get("position") or (0, 0)
                if abs(pos[0] - o.focus[0]) + abs(pos[1] - o.focus[1]) > 20:
                    await self.g.act([{"op": "move", "x": o.focus[0], "y": o.focus[1], "radius": 6}])
                    self.log({"kind": "walk_ahead", "order": o.id, "to": o.focus})
        except Exception as e:  # noqa: BLE001
            self.log({"kind": "error", "where": "walk_ahead", "error": repr(e)})

    async def _wait_next_part(self, o: Order, timeout: float = 900) -> dict | None:
        """Wait for the next part of a big order without sending a new request (the thinker is still on it)."""
        fut = asyncio.get_running_loop().create_future()
        self._plan_waiters[o.id] = fut
        t0 = time.time()
        while True:
            try:
                return await asyncio.wait_for(asyncio.shield(fut), 20)
            except asyncio.TimeoutError:
                still = self.thinker and self.thinker.busy and self.thinker.current and \
                    self.thinker.current.order_id == o.id
                if not still or time.time() - t0 > timeout or o.status == "cancelled":
                    self._plan_waiters.pop(o.id, None)
                    return None

    async def _ask_plan(self, o: Order, text: str, timeout: float = 600) -> dict | None:
        if not self.thinker:
            return None
        if self.thinker.stats.usage_limited:
            if not getattr(self, "_told_limit", False):
                self._told_limit = True
                await self.say("my planner is out of capacity right now (usage limit); I can still fix, deliver and "
                               "route belts, but bigger builds will have to wait")
            return None
        fut = asyncio.get_running_loop().create_future()
        self._plan_waiters[o.id] = fut
        o.status = "thinking"
        self.thinker.ask(Request("order" if o.plans == 0 else "report", text, o.id))
        if o.plans == 0 and self.prefetch:
            asyncio.create_task(self._prefetch(o))
        t0 = time.time()
        plan = None
        told = False
        while True:
            try:
                plan = await asyncio.wait_for(asyncio.shield(fut), 45 if not told else 30)
                break
            except asyncio.TimeoutError:
                if not told and o.plans == 0:
                    told = True
                    await self.say("still working out the layout, one moment")
                # keep waiting while the thinker is still on this order (puzzles take long), up to 20 minutes
                still = self.thinker.busy and self.thinker.current and self.thinker.current.order_id == o.id
                queued = any(r.order_id == o.id for r in list(self.thinker.queue._queue))
                if time.time() - t0 > (1200 if (still or queued) else timeout) or o.status == "cancelled":
                    self._plan_waiters.pop(o.id, None)
                    break
        if o.status == "thinking":
            o.status = "working"
        return plan

    def _order_context(self, o: Order) -> str:
        parts = []
        if o.focus:
            parts.append(f"The order points at {fmt_xy(o.focus)}" + (f" (and {', '.join(fmt_xy(p) for p in o.points[1:])})"
                                                                     if len(o.points) > 1 else "") + ".")
        if o.speaker_at:
            parts.append(f"{o.speaker} is standing at {fmt_xy(o.speaker_at)}.")
        if o.notes:
            parts.append("The player also said: " + " | ".join(o.notes))
        return " ".join(parts)

    async def _planned(self, o: Order, intro: str) -> bool:
        """Thinker plans, actor runs, code/Jev verify; failures and misses go back to the thinker (up to 4 plans)."""
        text = intro + "\n" + self._order_context(o)
        if o.focus:
            # the area around each point the order names (far-apart ones get their own summary), so the thinker can
            # usually plan without a look of its own
            pts = []
            for p in o.points:
                if all(abs(p[0] - q[0]) > 24 or abs(p[1] - q[1]) > 24 for q in pts):
                    pts.append(p)
            pts = pts[:3]
            budget = 12000 if len(pts) == 1 else 7000
            for p in pts:
                try:
                    w = await self.world(p, 20 if len(pts) == 1 else 15)
                    sm = w.summary(coords=True)
                    fl = w.faults()
                    if fl:
                        sm["faults"] = [f["text"] for f in fl[:12]]
                    text += (f"\n\nArea around {fmt_xy(p)} (radius {20 if len(pts) == 1 else 15}):\n" +
                             json.dumps(sm, separators=(",", ":"))[:budget])
                except Exception as e:  # noqa: BLE001
                    text += f"\n(area read at {fmt_xy(p)} failed: {e!r})"
        me = await self.g.me()
        text += f"\n\nThe character is at {fmt_xy(me.get('position') or (0, 0))}, carrying {items_words(me.get('inventory'), 12)}."
        try:
            mats = await self.materials()
            if mats:
                text += "\nIn storage chests (fetchable): " + ", ".join(f"{n} {k}" for k, n in mats[:40])
            # what a plan can actually get: storage + machine outputs + pockets, crafting what's missing
            stock = dict((await self.g.call("query", what="materials", outputs=True)).get("materials") or {})
            for k, v in (me.get("inventory") or {}).items():
                stock[k] = stock.get(k, 0) + v
            cs = craft.summary(stock, self.recipes)
            if cs:
                text += ("\nBuildings the character can get right now (storage, machine outputs and pockets, "
                         "hand-crafting what's missing; more only by mining ore and smelting): " +
                         ", ".join(f"{'200+' if n >= 200 else n} {i}" for i, n in cs) +
                         ". Size the plan to these.")
        except Exception as e:  # noqa: BLE001
            self.log({"kind": "error", "where": "materials", "error": repr(e)})
        # up to 4 plans that get nowhere; a plan that got several steps done before failing (a big order built in
        # parts) doesn't use one up, within 10 plans in all
        wasted, total, ok_before = 0, 0, self.metrics["steps_ok"]
        while wasted < 4 and total < 10:
            total += 1
            if total > 1:
                if self.metrics["steps_ok"] - ok_before < 3:
                    wasted += 1
                    if wasted >= 4:
                        break
                ok_before = self.metrics["steps_ok"]
            if o.status == "cancelled":
                return False
            if o.next_plan:
                plan, o.next_plan = o.next_plan, None
            else:
                plan = await self._ask_plan(o, text)
            o.plans += 1
            parts_expect: list = []
            part_failed = False
            while plan and plan.get("more") and not plan.get("no_plan"):
                # a part of a big order: build it now; the thinker is designing the next part meanwhile
                o.running_more = True
                if plan.get("say"):
                    await self.say(plan["say"])
                ok_part, rep_part = await self._run_plan(o, plan)
                parts_expect += [e for e in (plan.get("expect") or []) if isinstance(e, dict)]
                if not ok_part or o.status == "cancelled":
                    o.running_more = False
                    part_failed, report = True, rep_part
                    break
                if o.queued_plans:
                    plan = o.queued_plans.pop(0)
                else:
                    plan = await self._wait_next_part(o)
                o.running_more = bool(plan and plan.get("more"))
                if plan is None:
                    # the thinker ended without a last part: verify what the parts promised
                    plan = {"goal": o.text, "steps": [], "expect": parts_expect, "_parts_only": True}
            o.running_more = False
            if part_failed:
                if o.status == "cancelled":
                    return False
                o.history.append(report)
                # later parts were designed assuming this one worked: drop them, the corrected plan says what's left
                dropped = [str(q.get("goal") or "")[:100] for q in o.queued_plans]
                o.queued_plans.clear()
                text = (f"Part of your plan for order {o.id} (\"{o.text}\") failed.\n{report}\nSubmit a corrected "
                        "plan for what's still needed (what was built is still there)." +
                        (f" The {len(dropped)} later part(s) you had queued were dropped, not run: "
                         + "; ".join(dropped) + ". Include whatever of them is still needed." if dropped else ""))
                continue
            if parts_expect:
                plan = {**plan, "expect": list(plan.get("expect") or []) + parts_expect}
            if plan and plan.get("_parts_only"):
                verified, vreport = await self._verify(o, plan)
                if verified:
                    await self.say("done")
                    return True
                o.history.append(vreport)
                text = (f"Your plan for order {o.id} (\"{o.text}\") didn't get there.\n{vreport}\n"
                        "Submit a corrected plan (only the steps still needed).")
                continue
            self.metrics["plans"] += 1
            if not plan:
                if not (self.thinker and self.thinker.stats.usage_limited):
                    await self.say("sorry, I'm stuck on this one (no plan)")
                return False
            if plan.get("no_plan") and plan.get("error"):
                await self.say("my planner hit an error; trying again")
                plan = None
                continue
            if plan.get("no_plan"):
                # answered in words only (e.g. a question) -- nothing to run
                return True
            if plan.get("say"):
                await self.say(plan["say"])
            if plan.get("watch"):
                o.watch_what = [str(x) for x in plan["watch"]][:5]
            if not plan.get("steps"):
                # nothing to do in the world (an answer, an acknowledgement): done
                if plan.get("done_text"):
                    await self.say(plan["done_text"])
                return True
            ok, report = await self._run_plan(o, plan)
            if o.status == "cancelled":
                return False
            if ok:
                verified, vreport = await self._verify(o, plan)
                if verified:
                    self.metrics["verified"] += 1
                    await self.say(plan.get("done_text") or "done")
                    return True
                self.metrics["unverified"] += 1
                report = vreport
            o.history.append(report)
            text = (f"Your plan for order {o.id} (\"{o.text}\") didn't get there.\n{report}\n"
                    "Look at the area again if you need to, then submit a corrected plan (only the steps still "
                    "needed; what was built is still there).")
        await self.say("I couldn't finish that one, sorry")
        return False

    # ------------------------------------------------------------------ running plans
    async def _run_plan(self, o: Order, plan: dict) -> tuple[bool, str]:
        steps = plan.get("steps") or []
        try:
            o.built_pts += plan_points([st for st in steps if st.get("do") in BUILD_OPS])
        except Exception:  # noqa: BLE001
            pass
        # waits at the end of a plan with checks are there to let things start up: the checker polls through that
        # time instead and stops as soon as everything is met (blind end waits were 22% of all run time)
        tail = len(steps)
        while tail > 0 and steps[tail - 1].get("do") == "wait":
            tail -= 1
        if tail < len(steps) and tail > 0 and any(isinstance(e, dict) for e in plan.get("expect") or []):
            plan["_end_wait"] = sum(float(st.get("seconds") or 0) for st in steps[tail:])
            steps = steps[:tail]
        done = []
        goal = plan.get("goal") or o.text
        need = plan_needs(steps)
        if need:
            await self.g.status(text="getting materials")
            fails = await self.runner.stock(need)
            if fails:
                self.log({"kind": "stock_short", "order": o.id, "fails": fails})
        for i, st in enumerate(steps):
            if o.status == "cancelled":
                return False, "cancelled"
            if o.interrupt:
                note, o.interrupt = o.interrupt, None
                await self.say("ok, changing it")
                return False, (f"The player changed the job while it was running ({len(done)} steps done): "
                               f"\"{note}\". Steps done so far:\n" + "\n".join(done[-15:]))
            tries = 0
            # fuel the rest of the plan's refuel steps will hand out, so one coal run covers them all
            self.runner.fuel_ahead = sum(int(x.get("count", 20)) for x in steps[i:] if x.get("do") == "refuel")
            while True:
                tries += 1
                await self.g.status(text=f"{describe(st)[:80]}")
                r = await self.runner.run(st)
                self.log({"kind": "step", "order": o.id, "i": i, "step": st, "ok": r.get("ok"), "msg": r.get("msg")})
                if r.get("ok"):
                    self.metrics["steps_ok"] += 1
                    done.append(f"{i + 1}. {describe(st)}: ok ({str(r.get('msg'))[:120]})")
                    if st.get("do") == "insert" and "chest" in str(r.get("msg")) and int(st.get("count") or 0) >= 20:
                        key = (float(st["x"]), float(st["y"]), st["item"])
                        self.stocked = [c for c in self.stocked if (c["x"], c["y"], c["item"]) != key]
                        self.stocked.append({"x": key[0], "y": key[1], "item": key[2], "count": int(st["count"])})
                        self.stocked = self.stocked[-10:]
                    break
                self.metrics["steps_failed"] += 1
                msg = str(r.get("msg") or "failed")
                missing = r.get("missing") or parse_missing(msg)
                if r.get("unobtainable"):
                    missing = {}
                choice_, conf = await self._recovery(goal, st, msg, tries, missing)
                self.metrics["recoveries"][choice_] = self.metrics["recoveries"].get(choice_, 0) + 1
                self.log({"kind": "recovery", "order": o.id, "i": i, "choice": choice_, "conf": round(conf, 3),
                          "msg": msg})
                if choice_ == "retry" and tries < 3:
                    await asyncio.sleep(1)
                    continue
                if choice_ == "get_items" and missing and tries < 3:
                    for item, n in missing.items():
                        # storage, then belts, then crafting (ingredients fetched or mined), then mining raw items
                        have = (await self.runner.refresh_inventory()).get(item, 0)
                        r2 = await self.runner.ensure(item, have + max(1, int(n)))
                        if not r2.get("ok") and item in RAW:
                            await self.runner.run({"do": "mine", "name": "tree" if item == "wood" else item,
                                                   "count": max(10, int(n))})
                    continue
                if choice_ == "skip":
                    done.append(f"{i + 1}. {describe(st)}: FAILED ({msg[:160]}) - skipped")
                    break
                rest = steps[i + 1:]
                report = ("Steps done:\n" + "\n".join(done[-15:]) +
                          f"\nFailed at step {i + 1}: {json.dumps(st)}\nError: {msg}" +
                          (f"\n{len(rest)} steps were not run yet." if rest else ""))
                return False, report
        return True, "all steps ran:\n" + "\n".join(done[-20:])

    async def _recovery(self, goal: str, st: dict, msg: str, tries: int, missing: dict) -> tuple[str, float]:
        if tries >= 3:
            return "replan", 1.0
        opts = dict(decide.RECOVERY)
        if not missing:
            opts.pop("get_items")
        try:
            c, conf = await decide.recovery(self.jev, goal, describe(st), msg, tries, opts)
        except JevError:
            return "replan", 0.0
        if conf < 0.5 and c != "replan":
            return "replan", conf
        return c, conf

    # ------------------------------------------------------------------ verifying
    async def _verify(self, o: Order, plan: dict) -> tuple[bool, str]:
        """Machine checks from the plan's expect list; Jev on the goal words if there are none. Waits up to ~60 s
        for things to start running."""
        exp = [e for e in (plan.get("expect") or []) if isinstance(e, dict)]
        goal = plan.get("goal") or o.text
        if not exp and all(st.get("do") in ("say", "wait", "research", "follow", "upgrade", "clear", "purge")
                           for st in plan.get("steps") or []):
            # an acknowledgement or a research queue, or a step that reports exactly what it did
            return True, "nothing more to check"
        builds = [st for st in plan.get("steps") or [] if st.get("do") in ("ghosts", "block", "design", "stamp",
                                                                            "place", "build_ghosts", "route")]
        if builds and not any(e.get("check") == "built" for e in exp):
            from .lint import plan_points
            pts = plan_points(builds)
            if pts:
                xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                exp.append({"check": "built", "x": (min(xs) + max(xs)) / 2, "y": (min(ys) + max(ys)) / 2,
                            "radius": max(max(xs) - min(xs), max(ys) - min(ys)) / 2 + 2})
        last = ""
        jev_checks = 0
        # a plan that already waited has given things time to start: don't wait as long again
        end_wait = float(plan.get("_end_wait") or 0)  # trailing waits the checker polls through instead
        waited = sum(float(st.get("seconds") or 0) for st in plan.get("steps") or [] if st.get("do") == "wait")
        waited -= end_wait
        rounds = 2 if waited >= 30 else 8
        if end_wait:
            rounds = max(rounds, min(40, int(end_wait / 6) + 2))
        # items need time to travel a long new belt (a yellow belt moves 1.875 tiles/s): wait that long too
        belt = sum(abs(float(st["to"][0]) - float(st["from"][0])) + abs(float(st["to"][1]) - float(st["from"][1]))
                   for st in plan.get("steps") or [] if st.get("do") == "connect" and "belt" in str(st.get("item"))
                   and st.get("from") and st.get("to"))
        o.belt_len = max(o.belt_len, belt)
        if any(e.get("check") in ("belt_carries", "has_item") for e in exp):
            belt = max(belt, o.belt_len)  # a fix plan for an order with a long belt still waits for the items
        if belt > 60:
            rounds = max(rounds, min(40, 4 + int((belt / 1.875 - waited) / 6)))
        for k in range(rounds):
            await asyncio.sleep(6 if k else 4)
            if exp:
                results = [(e, *await self._check(e)) for e in exp]
                bad = [msg for _, ok, msg in results if not ok]
                if not bad:
                    return True, "all expectations met"
                last = "Expectations not met: " + "; ".join(bad)
                if any(e.get("check") == "built" for e, ok, _ in results if not ok):
                    break  # missing buildings won't appear by waiting
            else:
                jev_checks += 1
                if jev_checks > 3:
                    break
                center = o.focus or tuple((await self.g.me()).get("position") or (0, 0))
                w = await self.world(center, 20)
                p = await decide.goal_met(self.jev, goal, w.summary(coords=False, focus=center))
                self.log({"kind": "goal_met", "order": o.id, "p": round(p, 3)})
                if p >= 0.8:
                    return True, "looks done"
                last = f"Goal not visibly met yet (judged {p:.2f})."
        center = o.focus or tuple((await self.g.me()).get("position") or (0, 0))
        try:
            w = await self.world(center, 20)
            fl = w.faults()
            heal = [f for f in fl if f["kind"] in self.HEAL_KINDS and f.get("fixes")]
            if heal and not plan.get("_healed"):
                # faults code can fix by itself (fuel, power) get fixed before the planner hears about it
                plan["_healed"] = True
                done = []
                # machines without power next to each other: one power step over all of them
                unpowered = [f for f in heal if f["kind"] == "no_power"]
                if len(unpowered) > 1:
                    xs, ys = [f["at"][0] for f in unpowered], [f["at"][1] for f in unpowered]
                    heal = [f for f in heal if f["kind"] != "no_power"] + [{
                        "kind": "no_power", "text": f"{len(unpowered)} machines without power",
                        "fixes": [{"do": "power", "x": (min(xs) + max(xs)) / 2, "y": (min(ys) + max(ys)) / 2,
                                   "radius": max(max(xs) - min(xs), max(ys) - min(ys)) / 2 + 3,
                                   "done": f"connected {len(unpowered)} machines to the grid"}]}]
                for f in heal[:6]:
                    fx = f["fixes"][0]
                    if fx.get("do") == "refuel_boilers":
                        r = {"ok": await self._refuel_grid(w, f.get("grid"))}
                    else:
                        r = await self.runner.run({k: v for k, v in fx.items() if k not in ("text", "done")})
                    self.log({"kind": "heal", "order": o.id, "fault": f["text"], "ok": r.get("ok")})
                    if r.get("ok"):
                        done.append(fx.get("done") or fx.get("text"))
                if done:
                    ok2, rep2 = await self._verify(o, plan)
                    note = "The actor fixed by itself before checking again: " + "; ".join(done) + "."
                    return ok2, (rep2 if ok2 else f"{note}\n{rep2}")
            if fl:
                last += "\nProblems the actor sees there now: " + "; ".join(f["text"] for f in fl[:10])
        except Exception as ex:  # noqa: BLE001
            self.log({"kind": "error", "where": "verify faults", "error": repr(ex)})
        return False, last

    async def _check(self, e: dict) -> tuple[bool, str]:
        c = e.get("check")
        try:
            if c == "working":
                near = e.get("near") or [e.get("x"), e.get("y")]
                r = float(e.get("radius", 12))
                w = await self.world(tuple(near), int(r) + 3)
                ms = [m for m in w.of_type("assembling-machine", "furnace", "lab", "mining-drill", "boiler", "generator")
                      if abs(m["x"] - near[0]) <= r and abs(m["y"] - near[1]) <= r
                      and (not e.get("recipe") or m.get("r") == e["recipe"] or m.get("n") == e["recipe"])]
                n_ok = sum(1 for m in ms if m.get("s") in ("working", "full_output"))
                need = int(e.get("count", 1))
                if n_ok >= need:
                    return True, ""
                states = ", ".join(sorted({f"{m['n']} {w.label.get(m['u'])}: {m.get('s')}" for m in ms})[:8])
                return False, f"{n_ok}/{need} {e.get('recipe') or 'machines'} working near {fmt_xy(near)} ({states or 'none found'})"
            if c == "built":
                p = (float(e["x"]), float(e["y"]))
                sc = await self.g.scan(center=p, radius=int(float(e.get("radius", 10))) + 1)
                left = [x for x in (sc.get("ents") or []) if x.get("ghost")]
                if not left:
                    return True, ""
                kinds = {}
                for x in left:
                    kinds[x["n"]] = kinds.get(x["n"], 0) + 1
                return False, f"{len(left)} planned buildings still unbuilt near {fmt_xy(p)}: {items_words(kinds, 5)}"
            if c == "has_item":
                w = await self.world((e["x"], e["y"]), 3)
                ent = w.at(e["x"], e["y"])
                if not ent:
                    return False, f"nothing at {e['x']},{e['y']}"
                have = (ent.get("inv") or {}).get(e["item"], 0) + (ent.get("out") or {}).get(e["item"], 0)
                if have >= int(e.get("count", 1)):
                    return True, ""
                return False, f"{ent['n']} at {e['x']},{e['y']} holds {have} {e['item']} (want {e.get('count', 1)})"
            if c == "powered":
                near = e.get("near") or [e.get("x"), e.get("y")]
                r = float(e.get("radius", 8))
                w = await self.world(tuple(near), int(r) + 3)
                bad = [m for m in w.near(near, r) if m.get("pw")]
                return (not bad), ("" if not bad else f"{len(bad)} machines without power near {fmt_xy(near)}")
            if c == "belt_carries":
                w = await self.world((e["x"], e["y"]), 4)
                ent = w.at(e["x"], e["y"])
                ln = w.line_of.get(ent["u"]) if ent else None
                if ln and e["item"] in ln.items:
                    return True, ""
                return False, f"belt at {e['x']},{e['y']} carries {items_words(ln.items if ln else None, 3)}"
        except Exception as ex:  # noqa: BLE001
            return False, f"check {c} failed: {ex!r}"
        return True, ""  # unknown checks don't block

    # ------------------------------------------------------------------ fast playbooks
    @staticmethod
    def _stopped(w: World) -> set[int]:
        return {m["u"] for m in w.of_type("assembling-machine", "furnace", "lab", "mining-drill", "boiler")
                if m.get("s") not in ("working", "full_output", "normal", None)}

    async def _settled(self, o: Order, watch: set[int], secs: float = 50) -> tuple[bool, World]:
        """Poll until none of the watched machines is stopped (they got going), or time runs out."""
        t0 = time.time()
        while True:
            w = await self.world(o.focus, 18)
            still = self._stopped(w) & watch
            if not still:
                return True, w
            if time.time() - t0 > secs:
                return False, w
            await asyncio.sleep(5)

    async def _fix(self, o: Order):
        """Find faults near the point; Jev picks the one the player means; run its fix; wait for the stopped
        machines to start; up to 6 rounds. Returns True, or a report for the thinker."""
        fixed = []
        w = await self.world(o.focus, 18)
        watch = self._stopped(w)
        for rnd in range(6):
            if rnd:
                w = await self.world(o.focus, 18)
            fl = [f for f in w.faults() if f.get("fixes")]
            allf = w.faults()
            if not allf and not (self._stopped(w) & watch):
                if fixed:
                    await self.say(fixed_words(fixed))
                    return True
                return "no faults found near the point and nothing there is stopped (the cause may be elsewhere)"
            if not fl:
                pre = f"I already did: {'; '.join(fixed)}. " if fixed else ""
                return pre + "Problems I see but can't fix by myself: " + "; ".join(f["text"] for f in allf[:8])
            # faults of the same kind are one option ("4 furnaces: output full"): they're usually one problem, and
            # picking one of four identical faults only splits Jev's confidence
            groups: dict = {}
            for f in fl:
                groups.setdefault(f["kind"], []).append(f)
            opts = []
            for kind, mem in groups.items():
                text = mem[0]["text"] if len(mem) == 1 else f"{len(mem)} of these: {mem[0]['text']}"
                opts.append({"text": text, "members": mem})
            idx, conf, p_any, p_all = await decide.fault(self.jev, o.text, opts)
            self.log({"kind": "fault_pick", "order": o.id, "faults": [x["text"] for x in opts], "pick": idx,
                      "conf": round(conf, 3), "p_any": round(p_any, 3), "p_all": round(p_all, 3)})
            if idx is None or idx >= len(opts) or (conf < 0.4 and p_any < 0.5):
                return "unsure which fault is meant: " + "; ".join(x["text"] for x in opts[:6])
            # "get it all running": every fault code can fix there in this round, the one Jev picked first
            extra = [g for i, g in enumerate(opts) if i != idx] if p_all >= 0.7 else []
            r, f, fx = {"ok": True}, None, None
            for f in opts[idx]["members"] + [m for g in extra for m in g["members"]]:
                main = f in opts[idx]["members"]
                fx = f["fixes"][0]
                step = {k: v for k, v in fx.items() if k != "text"}
                if fx.get("do") == "refuel_boilers":
                    ok = await self._refuel_grid(w, f.get("grid"))
                    r = {"ok": ok, "msg": "refuelled boilers" if ok else "couldn't refuel boilers"}
                else:
                    await self.g.status(text=fx.get("text", "")[:80])
                    r = await self.runner.run(step)
                    if r.get("ok") and fx.get("then_power"):  # a new generator has to touch the grid too
                        r = await self.runner.run({"do": "power", "x": fx["x"], "y": fx["y"], "radius": 3})
                    if r.get("ok") and fx.get("then_purge"):  # the old product left on its belt
                        r = await self.runner.run({"do": "purge", **fx["then_purge"]})
                self.log({"kind": "fix", "order": o.id, "fault": f["text"], "fix": fx, "ok": r.get("ok"),
                          "msg": r.get("msg")})
                if not r.get("ok") and main:
                    return f"tried to fix '{f['text']}' by '{fx.get('text')}' and it failed: {r.get('msg')}"
                if r.get("ok"):
                    fixed.append(fx.get("done") or fx.get("text"))
            self.metrics["fast_path"] += 1
            # let it run: success when the machines that were stopped got going
            ok, w2 = await self._settled(o, watch or self._stopped(w))
            if ok and not [f for f in w2.faults() if f.get("fixes")]:
                await self.say(fixed_words(fixed))
                return True
        w = await self.world(o.focus, 18)
        return (f"I did: {'; '.join(fixed)}, but problems remain: " + "; ".join(f["text"] for f in w.faults()[:8]))

    async def _wide_faults(self, center, reach: int = 160) -> list[tuple[dict, World]]:
        """Faults over a wide area: a grid of scans around center (each radius 64), de-duplicated."""
        out, seen = [], set()
        step = 120
        offs = [k * step for k in range(-(reach // step), reach // step + 1)]
        for dx in offs:
            for dy in offs:
                w = await self.world((center[0] + dx, center[1] + dy), 64)
                for f in w.faults():
                    key = (f["kind"], f.get("u"), tuple(f.get("at") or ()))
                    if key in seen or not f.get("fixes"):
                        continue
                    seen.add(key)
                    out.append((f, w))
        return out

    async def _fix_wide(self, o: Order):
        """Many sites: find every fixable fault in a wide area and fix them nearest-first, twice over."""
        fixed, failed = [], []
        for rnd in range(3):
            found = await self._wide_faults(o.focus)
            self.log({"kind": "wide_faults", "order": o.id, "round": rnd, "n": len(found),
                      "faults": [f["text"] for f, _ in found][:40]})
            if not found:
                break
            me = await self.g.me()
            pos = tuple(me.get("position") or o.focus)
            todo = list(found)
            while todo:
                todo.sort(key=lambda fw: (fw[0]["at"][0] - pos[0]) ** 2 + (fw[0]["at"][1] - pos[1]) ** 2)
                f, w = todo.pop(0)
                fx = f["fixes"][0]
                step = {k: v for k, v in fx.items() if k != "text"}
                if fx.get("do") == "refuel_boilers":
                    ok = await self._refuel_grid(w, f.get("grid"))
                    r = {"ok": ok, "msg": ""}
                else:
                    await self.g.status(text=fx.get("text", "")[:80])
                    r = await self.runner.run(step)
                    if r.get("ok") and fx.get("then_power"):  # a new generator has to touch the grid too
                        r = await self.runner.run({"do": "power", "x": fx["x"], "y": fx["y"], "radius": 3})
                    if r.get("ok") and fx.get("then_purge"):  # the old product left on its belt
                        r = await self.runner.run({"do": "purge", **fx["then_purge"]})
                self.log({"kind": "fix", "order": o.id, "fault": f["text"], "fix": fx, "ok": r.get("ok"),
                          "msg": r.get("msg")})
                (fixed if r.get("ok") else failed).append(fx.get("done") or fx.get("text"))
                pos = tuple(f.get("at") or pos)
                self.metrics["fast_path"] += 1
            await asyncio.sleep(10)
        left = await self._wide_faults(o.focus)
        if not left and fixed:
            await self.say(f"fixed {len(fixed)} things: " + "; ".join(fixed[:6]) + ("..." if len(fixed) > 6 else ""))
            return True
        return (f"I fixed {len(fixed)} things ({'; '.join(fixed[:8])}); failed: {'; '.join(failed[:5]) or 'none'}. "
                f"Still broken: " + "; ".join(f["text"] for f, _ in left[:10]))

    async def _refuel_grid(self, w: World, grid_id) -> bool:
        """Fill the grid's boilers that are low (the scan says where, even outside the area looked at). A boiler at
        full load burns ~0.45 coal/s, so they get a full stack (50), not the usual 20."""
        g = w.grids.get(grid_id) or {}
        at = [tuple(b) for b in g.get("boilers_low_at") or []]
        if not at:
            at = [(e["x"], e["y"]) for e in w.of_type("boiler") if sum((e.get("fuel") or {}).values()) < 5]
        ok = True
        for x, y in at:
            r = await self.runner.run({"do": "refuel", "x": x, "y": y, "count": 50, "stock": 50 * len(at)})
            ok = ok and bool(r.get("ok"))
        return ok

    def parse_items(self, text: str) -> list[tuple[str, int]]:
        """'20 inserters and 50 transport belts' -> [(inserter, 20), (transport-belt, 50)]."""
        out = []
        t = re.sub(r"\[gps=[^\]]*\]", " ", text.lower())
        for m in re.finditer(r"(\d+)\s*x?\s+([a-z][a-z \-]{1,40})", t):
            n = int(m.group(1))
            words = re.split(r"[\s\-]+", m.group(2).strip())
            best = None
            for k in range(min(4, len(words)), 0, -1):
                cand = "-".join(words[:k])
                for v in (cand, cand.rstrip("s"), re.sub(r"ies$", "y", cand), re.sub(r"es$", "", cand)):
                    if v in self.items:
                        best = v
                        break
                if best:
                    break
            if best:
                out.append((best, n))
        return out

    async def _deliver(self, o: Order):
        items = self.parse_items(o.text)
        if not items:
            return "couldn't tell which items"
        x, y = o.focus
        w = await self.world((x, y), 3)
        target = w.at(x, y) or next(iter(w.near((x, y), 1.5, types={"container", "logistic-container"})), None)
        if not target:
            return f"no chest at {x},{y}"
        await self.say("on it: " + ", ".join(f"{n} {i}" for i, n in items))
        for item, n in items:
            r = await self.runner.run({"do": "insert", "x": target["x"], "y": target["y"], "item": item, "count": n})
            self.log({"kind": "deliver", "order": o.id, "item": item, "n": n, "ok": r.get("ok"), "msg": r.get("msg")})
            if not r.get("ok"):
                return f"delivering {n} {item} failed: {r.get('msg')}"
            ins = int(r.get("inserted") or 0)
            if ins < n:
                more = await self.runner.run({"do": "insert", "x": target["x"], "y": target["y"], "item": item,
                                              "count": n - ins})
                if not more.get("ok"):
                    return f"only got {ins} of {n} {item} in: {more.get('msg')}"
        self.metrics["fast_path"] += 1
        await self.say("done, they're in the chest")
        return True

    # ------------------------------------------------------------------ reading the world
    async def materials(self) -> list[tuple[str, int]]:
        """Items in the force's storage chests (not endless ones), biggest first."""
        t = (await self.g.call("query", what="materials")).get("materials") or {}
        return sorted(((k, int(v)) for k, v in t.items()), key=lambda kv: -kv[1]) if isinstance(t, dict) else []

    async def world(self, center, radius: int = 20) -> World:
        sc = await self.g.scan(center=center, radius=radius)
        return World(sc, self.recipes)
