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

from . import decide
from .game import Game
from .steps import Runner, describe, parse_missing, plan_needs
from .thinker import Request, Thinker
from .typesafe import Jev, JevError
from .world import World, fmt_xy, items_words

log = logging.getLogger("jev.actor")

GPS = re.compile(r"\[gps=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)(?:,[^\]]*)?\]")
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

    @property
    def focus(self):
        return self.points[0] if self.points else None


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
        self.thinker = Thinker(name, self._thinker_tools(), self._on_plan, workdir / "thinker", self.log,
                               effort=thinker_effort) if think else None
        self.metrics = {"orders": 0, "fast_path": 0, "plans": 0, "steps_ok": 0, "steps_failed": 0,
                        "recoveries": {}, "verified": 0, "unverified": 0, "chat_lines": 0}
        self._tasks: list[asyncio.Task] = []
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
        self.items = await self.g.eval(
            "local t={} for n,p in pairs(prototypes.item) do if not p.hidden then t[#t+1]=n end end return t") or []
        if self.thinker:
            await self.thinker.start()
        self._tasks = [asyncio.create_task(self._chat_loop()), asyncio.create_task(self._work_loop())]
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
            call = decide.ChatCall(1.0 if explicit else 0.0, "new_job", 0.0, "plan", 0.0)
        self.log({"kind": "chat", "speaker": speaker, "msg": msg, "addressed": round(call.addressed, 3),
                  "kind_": call.kind, "kind_conf": round(call.kind_conf, 3), "playbook": call.playbook,
                  "playbook_conf": round(call.playbook_conf, 3)})
        if not explicit and call.addressed < 0.5:
            return
        kind = call.kind
        last = self.orders[-1] if self.orders else None
        if kind in ("more_info",) and not doing and last and last.status in ("done", "failed") \
                and time.time() - last.t < 1800:
            # "not done yet" / a correction after it finished: reopen that order with the note
            last.notes.append(f"{speaker}: {msg}")
            last.status = "new"
            self.log({"kind": "reopen", "order": last.id})
            self.wake.set()
            return
        if kind == "new_job" or (kind in ("more_info", "approval") and not doing and call.kind_conf < 0.7):
            pts = [(float(a), float(b)) for a, b in GPS.findall(msg)]
            o = Order(self.next_id, msg, speaker, call.playbook if call.playbook_conf >= 0.6 else "plan", pts)
            self.next_id += 1
            self.orders.append(o)
            self.metrics["orders"] += 1
            self.wake.set()
        elif kind in ("more_info", "approval") and self.current:
            self.current.notes.append(f"{speaker}: {msg}")
            if self.thinker and self.current.status == "thinking":
                self.thinker.ask(Request("report", f"The player added: \"{msg}\"", self.current.id))
        elif kind == "stop":
            if self.current:
                self.current.status = "cancelled"
            await self.g.cancel("player said stop")
            await self.say("ok, stopped")
        elif kind == "question" and self.thinker:
            self.thinker.ask(Request("question", f"{speaker} asked in chat: \"{msg}\"\nAnswer briefly with the say "
                                     "tool (look first only if you need to). Don't submit a plan unless they asked "
                                     "for work.", self.current.id if self.current else None))

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
            await self.g.status(text="")

    async def _do_order(self, o: Order) -> bool:
        self.log({"kind": "order", "order": o.id, "text": o.text, "playbook": o.playbook, "points": o.points})
        await self.g.status(text=o.text[:100])
        if o.playbook == "fix" and o.focus:
            await self.say("on it, taking a look")
            r = await self._fix(o)
            if r is True:
                return True
            report = r or "I found no fault I could fix on my own."
            return await self._planned(o, f"New order from {o.speaker}: \"{o.text}\"\n\nThe actor's quick look: {report}")
        if o.playbook == "deliver" and o.focus:
            r = await self._deliver(o)
            if r is True:
                return True
            return await self._planned(o, f"New order from {o.speaker}: \"{o.text}\"\n\nThe actor tried to deliver it "
                                          f"itself and couldn't: {r}")
        await self.say("on it")
        return await self._planned(o, f"New order from {o.speaker}: \"{o.text}\"")

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
        return {"area": area, "find": find, "recipe": recipe, "free_space": free_space, "me": me, "say": say}

    async def _on_plan(self, plan: dict, req: Request | None) -> None:
        oid = req.order_id if req else None
        self.log({"kind": "plan", "order": oid, "plan": plan})
        fut = self._plan_waiters.pop(oid, None) if oid is not None else None
        if fut and not fut.done():
            fut.set_result(plan)

    async def _ask_plan(self, o: Order, text: str, timeout: float = 600) -> dict | None:
        if not self.thinker:
            return None
        fut = asyncio.get_running_loop().create_future()
        self._plan_waiters[o.id] = fut
        o.status = "thinking"
        self.thinker.ask(Request("order" if o.plans == 0 else "report", text, o.id))
        try:
            plan = await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            self._plan_waiters.pop(o.id, None)
            plan = None
        if o.status == "thinking":
            o.status = "working"
        return plan

    def _order_context(self, o: Order) -> str:
        parts = []
        if o.focus:
            parts.append(f"The order points at {fmt_xy(o.focus)}" + (f" (and {', '.join(fmt_xy(p) for p in o.points[1:])})"
                                                                     if len(o.points) > 1 else "") + ".")
        if o.notes:
            parts.append("The player also said: " + " | ".join(o.notes))
        return " ".join(parts)

    async def _planned(self, o: Order, intro: str) -> bool:
        """Thinker plans, actor runs, code/Jev verify; failures and misses go back to the thinker (up to 4 plans)."""
        text = intro + "\n" + self._order_context(o)
        if o.focus:
            try:
                w = await self.world(o.focus, 20)
                s = w.summary(coords=True)
                fl = w.faults()
                if fl:
                    s["faults"] = [f["text"] for f in fl[:12]]
                text += "\n\nArea around the first point (radius 20), so you can usually plan right away:\n" + \
                    json.dumps(s, separators=(",", ":"))[:12000]
            except Exception as e:  # noqa: BLE001
                text += f"\n(area read failed: {e!r})"
        me = await self.g.me()
        text += f"\n\nThe character is at {fmt_xy(me.get('position') or (0, 0))}, carrying {items_words(me.get('inventory'), 12)}."
        try:
            mats = await self.materials()
            if mats:
                text += "\nIn storage chests (fetchable): " + ", ".join(f"{n} {k}" for k, n in mats[:40])
        except Exception as e:  # noqa: BLE001
            self.log({"kind": "error", "where": "materials", "error": repr(e)})
        for attempt in range(4):
            if o.status == "cancelled":
                return False
            plan = await self._ask_plan(o, text)
            o.plans += 1
            self.metrics["plans"] += 1
            if not plan:
                await self.say("sorry, I'm stuck on this one (no plan)")
                return False
            if plan.get("no_plan"):
                # answered in words only (e.g. a question) -- nothing to run
                return True
            if plan.get("say"):
                await self.say(plan["say"])
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
            tries = 0
            while True:
                tries += 1
                await self.g.status(text=f"{describe(st)[:80]}")
                r = await self.runner.run(st)
                self.log({"kind": "step", "order": o.id, "i": i, "step": st, "ok": r.get("ok"), "msg": r.get("msg")})
                if r.get("ok"):
                    self.metrics["steps_ok"] += 1
                    done.append(f"{i + 1}. {describe(st)}: ok ({str(r.get('msg'))[:120]})")
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
                        if item in RAW:
                            await self.runner.run({"do": "mine", "name": item, "count": max(10, int(n))})
                        else:
                            await self.runner.run({"do": "fetch", "item": item, "count": max(1, int(n))})
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
        last = ""
        for k in range(8):
            await asyncio.sleep(6 if k else 4)
            if exp:
                results = [await self._check(e) for e in exp]
                bad = [msg for ok, msg in results if not ok]
                if not bad:
                    return True, "all expectations met"
                last = "Expectations not met: " + "; ".join(bad)
            else:
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
            if fl:
                last += "\nProblems the actor sees there now: " + "; ".join(f["text"] for f in fl[:10])
        except Exception:  # noqa: BLE001
            pass
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
        machines to start; up to 4 rounds. Returns True, or a report for the thinker."""
        fixed = []
        w = await self.world(o.focus, 18)
        watch = self._stopped(w)
        for rnd in range(4):
            if rnd:
                w = await self.world(o.focus, 18)
            fl = [f for f in w.faults() if f.get("fixes")]
            allf = w.faults()
            if not allf and not (self._stopped(w) & watch):
                if fixed:
                    await self.say("fixed: " + "; ".join(fixed))
                    return True
                return "no faults found near the point and nothing there is stopped (the cause may be elsewhere)"
            if not fl:
                pre = f"I already did: {'; '.join(fixed)}. " if fixed else ""
                return pre + "Problems I see but can't fix by myself: " + "; ".join(f["text"] for f in allf[:8])
            idx, conf, p_any = await decide.fault(self.jev, o.text, fl)
            self.log({"kind": "fault_pick", "order": o.id, "faults": [f["text"] for f in fl], "pick": idx,
                      "conf": round(conf, 3), "p_any": round(p_any, 3)})
            if idx is None or idx >= len(fl) or (conf < 0.4 and p_any < 0.5):
                return "unsure which fault is meant: " + "; ".join(f["text"] for f in fl[:6])
            f = fl[idx]
            fx = f["fixes"][0]
            step = {k: v for k, v in fx.items() if k != "text"}
            if fx.get("do") == "refuel_boilers":
                ok = await self._refuel_grid(w, f.get("grid"))
                r = {"ok": ok, "msg": "refuelled boilers" if ok else "couldn't refuel boilers"}
            else:
                await self.g.status(text=fx.get("text", "")[:80])
                r = await self.runner.run(step)
            self.log({"kind": "fix", "order": o.id, "fault": f["text"], "fix": fx, "ok": r.get("ok"), "msg": r.get("msg")})
            if not r.get("ok"):
                return f"tried to fix '{f['text']}' by '{fx.get('text')}' and it failed: {r.get('msg')}"
            fixed.append(fx.get("text"))
            self.metrics["fast_path"] += 1
            # let it run: success when the machines that were stopped got going
            ok, w2 = await self._settled(o, watch or self._stopped(w))
            if ok and not [f for f in w2.faults() if f.get("fixes")]:
                await self.say("fixed: " + "; ".join(fixed))
                return True
        w = await self.world(o.focus, 18)
        return (f"I did: {'; '.join(fixed)}, but problems remain: " + "; ".join(f["text"] for f in w.faults()[:8]))

    async def _refuel_grid(self, w: World, grid_id) -> bool:
        boilers = [e for e in w.of_type("boiler") if sum((e.get("fuel") or {}).values()) < 5]
        ok = True
        for b in boilers:
            r = await self.runner.run({"do": "refuel", "x": b["x"], "y": b["y"]})
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
        lua = ("local s=game.surfaces.nauvis local t={} for _,c in pairs(s.find_entities_filtered{type={'container',"
               "'logistic-container'},force='player'}) do local inv=c.get_inventory(defines.inventory.chest) if inv then "
               "for _,it in pairs(inv.get_contents()) do t[it.name]=(t[it.name] or 0)+it.count end end end return t")
        t = await self.g.eval(lua) or {}
        return sorted(((k, int(v)) for k, v in t.items()), key=lambda kv: -kv[1]) if isinstance(t, dict) else []

    async def world(self, center, radius: int = 20) -> World:
        sc = await self.g.scan(center=center, radius=radius)
        return World(sc, self.recipes)
