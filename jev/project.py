"""Projects: goals bigger than one plan ("automate green science", "get us to oil", "launch a rocket"). The serf runs
them itself. A manager (Opus, one short session per turn, with a journal as its memory) looks at the world, gives the
serf its next order, any size it thinks will work, which runs through the same paths a player's order takes, reads
how it went, and repeats until the goal is met, a player stops it, or it gives up. Players can still give orders
while a project runs; theirs go first. Started by the planner (start_project) or by an order that plainly is one
("beat the game", "launch a rocket", "project: ...")."""
from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path

from . import progress
from .thinker import TOOLS

MODEL = "claude-opus-5-5"
LOOK_TOOLS = ("area", "find", "recipe", "free_space", "me", "production", "diagnose", "techs", "rates", "audit")
ORDER_LIMIT = 45 * 60  # one order that runs longer is stopped and reported as unfinished

# an order that is a project on its face, no planner turn needed to see it
OBVIOUS = re.compile(r"\bproject:|\b(beat the game|launch (a|the) rocket|win the game|take charge of|run the (whole )?"
                     r"base|build (up )?the (whole )?(base|factory))\b", re.I)

SYSTEM = """You run projects for {name}, a character in a Factorio 2.0 (Space Age) world with no enemies. {name} \
takes orders from chat and carries them out itself: it walks, mines, crafts and builds like a player. A player gave \
it a goal too big for one order. You turn that goal into orders, one at a time, and give them to {name}; you don't \
act in the world yourself. You look with your tools, note what to remember, and end each turn with give_order, \
wait, or finish.

The goal: {goal}
(from {speaker})

What {name} does well on its own, fast and with no planning: machines making one product off a belt that's already \
there ("make gears off the belt at [gps]", "4 furnaces smelting the ore belt at [gps], plates into chests"), \
belting items from a belt end to a machine or chest, setting up a mine on an ore patch and belting the ore to a \
place, fixing broken things ("no gears coming out of [gps], fix it"), copying a build it just made to other places, \
swapping belts or assemblers for better ones, and research ("research automation 2"). Bigger orders go to its own \
planner (Opus too), which handles multi-part builds: "build a smelting column for the iron patch at [gps] and belt \
the plates to [gps]", "set up oil processing at [gps]". It uses what's in chests and what it can craft, and mines \
and smelts by hand when it has to (slow: a few hundred plates by hand take many minutes).

How to run it:
- Success is the goal met by a base that keeps running without help. Measure it with the progress line in each \
report (and production, diagnose, area), not with what {name} says.
- Give the largest orders {name} can finish on its own. Start with ones you're confident about; grow them as they \
succeed. When one fails, look at why (area, diagnose) and break it down or change approach. Don't repeat a failed \
order unchanged.
- Build for throughput that lasts: mines belted to furnaces, fuel by belt or inserter rather than by hand, power that \
scales with what's built, research running whenever labs and packs allow.
- {name} hand-crafts every building it places unless chests hold them, and a big craft keeps it busy for minutes. \
Once there's power and electronic circuits, have it build the two mall blocks (mall-logistics, mall-buildings) fed by \
belts; it takes from their chests from then on.
- Name places with [gps=x,y] tags; pick them with free_space and area. Keep the base compact enough to walk.
- Each turn: look as much as you need (a few tool calls), note anything worth remembering (the plan, where things \
are, what failed and why), then end with exactly one of give_order, wait or finish. {name} works on an order until \
it's done or failed; then you get the next turn.
- Players may also give {name} orders or say things; they're in the report. Players come first: fit your plan \
around what they ask.
- When a run of orders got a sub-goal done cleanly, save it with save_playbook so later projects can reuse it.
- finish when the goal is met (done=true), or when you've tried the ways you can think of and it can't be done from \
here (done=false, say what's in the way).

Milestones, for reference: {milestones}
"""

OWN_TOOLS = [
    ("give_order", "Give the serf its next order (ends your turn). Phrase it as a player would in chat, with "
                   "[gps=x,y] places. It works on it until done or failed.",
     {"type": "object", "properties": {"text": {"type": "string"}, "why": {"type": "string"}}, "required": ["text"]}),
    ("wait", "Let the factory run some minutes without a new order (ends your turn): research to finish, packs to "
             "pile up, a new build to fill.",
     {"type": "object", "properties": {"minutes": {"type": "number"}, "why": {"type": "string"}},
      "required": ["minutes"]}),
    ("note", "Write a line in the project journal (your memory between turns): the plan, where things are, what "
             "failed and why.",
     {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}),
    ("say", "Say a short line in game chat (progress for the players). Use it sparingly.",
     {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}),
    ("save_playbook", "Save a sequence of orders that worked for a sub-goal (e.g. 'bootstrap a fresh map', 'copper "
                      "smelting column'), written so it fits another world: places as descriptions, not coordinates. "
                      "Later projects see your playbooks. Only after the orders succeeded.",
     {"type": "object", "properties": {"name": {"type": "string"}, "when": {"type": "string", "description": "when "
                                       "to use it"}, "orders": {"type": "array", "items": {"type": "string"}},
                                       "result": {"type": "string", "description": "what it got you, how long"}},
      "required": ["name", "when", "orders"]}),
    ("finish", "End the project (ends your turn): done=true when the goal is met, false when it can't be done from "
               "here. summary: one or two lines for the player.",
     {"type": "object", "properties": {"done": {"type": "boolean"}, "summary": {"type": "string"}},
      "required": ["done", "summary"]}),
]


class Project:
    def __init__(self, actor, goal: str, speaker: str, workdir: Path, model: str = MODEL, effort: str | None = None,
                 deadline: float | None = None):
        self.actor, self.goal, self.speaker = actor, goal.strip(), speaker
        self.workdir, self.model, self.effort, self.deadline = workdir, model, effort, deadline
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.journal_path = workdir / "journal.jsonl"
        self.log_path = workdir / "project.jsonl"
        self.status = "running"  # running | done | given_up | stopped | out_of_time
        self.summary = ""
        self.usd = 0.0
        self.turns = 0
        self.orders: list = []
        self.probes: list[dict] = []
        self.t0 = time.time()
        self.heard: list[str] = []  # what players and the serf said, for the next report
        self.last: dict | None = None
        self._stop = asyncio.Event()
        self.task: asyncio.Task | None = None

    # ------------------------------------------------------------------ bookkeeping
    def _log(self, rec: dict) -> None:
        with open(self.log_path, "a") as f:
            f.write(json.dumps({"t": time.time(), **rec}, default=str) + "\n")

    def journal(self, n: int = 40) -> list[str]:
        if not self.journal_path.exists():
            return []
        lines = [json.loads(x) for x in self.journal_path.read_text().splitlines() if x.strip()]
        return [f"[{x['when']}] {x['text']}" for x in lines[-n:]]

    def hear(self, who: str, text: str) -> None:
        self.heard.append(time.strftime("%H:%M ") + f"{who}: {text[:240]}")
        del self.heard[:-30]

    def stop(self, why: str = "stopped") -> None:
        if self.status == "running":
            self.status, self.summary = "stopped", why
        self._stop.set()

    @property
    def active(self) -> bool:
        return self.status == "running"

    # ------------------------------------------------------------------ the loop
    async def run(self) -> str:
        a = self.actor
        self._log({"kind": "start", "goal": self.goal, "speaker": self.speaker})
        try:
            while self.active:
                if self.deadline and time.time() >= self.deadline:
                    self.status, self.summary = "out_of_time", "ran out of time"
                    break
                await self._players_first()
                if not self.active:
                    break
                p = await self._probe()
                when = f"+{int((time.time() - self.t0) / 60)}m"
                try:
                    d = await self._decide(self._report(p), when)
                except Exception as e:  # noqa: BLE001
                    self._log({"kind": "error", "error": repr(e)})
                    if "usage limit" in repr(e).lower() or "session limit" in repr(e).lower():
                        # it lifts after a while: wait and try again rather than ending the project
                        self._log({"kind": "usage_limit"})
                        await self._sleep(600)
                        continue
                    await self._sleep(60)
                    continue
                self._log({"kind": "decision", **d})
                if d.get("finish"):
                    self.status = "done" if d.get("done") else "given_up"
                    self.summary = str(d.get("summary") or "")
                    break
                if d.get("order"):
                    await self._run_order(d["order"])
                else:
                    mins = max(1.0, min(30.0, float(d.get("wait") or 5)))
                    await self._sleep(mins * 60)
                    self.last = {"text": f"(you waited {mins:.0f} min)", "outcome": "waited", "mins": mins}
        finally:
            p = await self._probe()
            self._log({"kind": "end", "status": self.status, "summary": self.summary, "turns": self.turns,
                       "usd": round(self.usd, 3), "orders": len(self.orders),
                       "level": p.get("level") if p else None})
        if self.status == "done":
            await a.say(f"project done: {self.summary}"[:300])
        elif self.status == "given_up":
            await a.say(f"I'm stopping the project: {self.summary}"[:300])
        return self.status

    async def _sleep(self, secs: float) -> None:
        try:
            await asyncio.wait_for(self._stop.wait(), max(0.0, secs))
        except asyncio.TimeoutError:
            pass

    async def _players_first(self) -> None:
        """Wait while the serf is busy with orders players gave it."""
        a = self.actor
        while self.active and any(o.status in ("new", "working", "thinking") for o in a.orders):
            await self._sleep(5)

    async def _probe(self) -> dict | None:
        try:
            p = await progress.probe(self.actor.g)
        except Exception as e:  # noqa: BLE001
            self._log({"kind": "probe_error", "error": repr(e)})
            return None
        self.probes.append(p)
        del self.probes[:-50]
        return p

    async def _run_order(self, text: str) -> None:
        a = self.actor
        text = text if text.lower().startswith(f"@{a.name}") else f"@{a.name} {text}"
        ts = time.time()
        o = await a.add_order(text, "project")
        o.project = self
        self.orders.append(o)
        self._log({"kind": "order", "order": o.id, "text": text, "playbook": o.playbook})
        while o.status in ("new", "working", "thinking") and time.time() - ts < ORDER_LIMIT and self.active:
            await self._sleep(5)
        if o.status in ("new", "working", "thinking"):
            o.status = "cancelled"
            await a.g.cancel("project moved on")
            outcome = (f"not finished after {(time.time() - ts) / 60:.0f} min (stopped)" if self.active
                       else "stopped by a player")
        else:
            outcome = o.status
            if getattr(o, "asked", None):
                outcome += f", but {a.name} asked: \"{o.asked[:400]}\" (answer it in your next order)"
        self.last = {"text": text, "outcome": outcome, "mins": (time.time() - ts) / 60,
                     "history": [h[:400] for h in o.history[-2:]]}
        self._log({"kind": "order_end", "order": o.id, **self.last})

    STUCK_H = 2.0

    def _stuck(self, p: dict) -> str:
        """How long the world has been at its current milestone, across sessions (kept in the project's folder).
        After STUCK_H hours, a nudge: c1 spent 5 h at purple and p2 hours at blue patching the same blockers, while
        block builds on clean ground succeeded 28 times in 38."""
        path = self.workdir / "level.json"
        try:
            st = json.loads(path.read_text())
        except (OSError, ValueError):
            st = {}
        lv = p.get("level")
        if st.get("level") != lv:
            st = {"level": lv, "since": time.time()}
            try:
                path.write_text(json.dumps(st))
            except OSError:
                pass
            return ""
        hours = (time.time() - float(st.get("since") or time.time())) / 3600
        if hours < self.STUCK_H:
            return ""
        return (f"The world has been at milestone {lv} for {hours:.1f} hours. If the same blockers keep coming back, "
                "stop patching them: build the missing chain fresh on clean ground from the library blocks, fed by "
                "its own belts (fresh blocks have worked far more often than repairs of tangled old lines).")

    def _by_hand(self) -> str:
        """What the serf keeps running by hand: chests it tops up and burners it refuels. Each is a line that isn't
        automated yet, which the probe can't tell from one that is (p2 hand-filled a brick chest 4 times in an hour)."""
        a = self.actor
        out = []
        for c in getattr(a, "stocked", [])[:10]:
            if c.get("topped"):
                out.append(f"- {c['item']} into the chest at [gps={c['x']:.0f},{c['y']:.0f}]: topped up {c['topped']} "
                           f"times so far ({c.get('moved', 0)} {c['item']})")
        nf = len(getattr(a, "fuelled", []))
        if nf >= 3:
            out.append(f"- {nf} burners (drills, furnaces, boilers) it refuels by hand when they run low")
        if not out:
            return ""
        return ("Kept going by hand (the serf does these itself between orders; each is something not automated "
                "yet, worth replacing with a belt or inserter feed when it matters):\n" + "\n".join(out))

    def _report(self, p: dict | None) -> str:
        mins = (time.time() - self.t0) / 60
        lines = [f"The project has run {mins:.0f} min; orders given: {len(self.orders)}."]
        if self.deadline:
            lines[0] += (f" This session ends in {(self.deadline - time.time()) / 60:.0f} min; the world is saved then "
                         "and you carry on in the next one with your journal, so don't finish the project because "
                         "time is short.")
        if p:
            r = progress.rates(self.probes[-2], p) if len(self.probes) >= 2 else None
            lines.append("State of the world:\n" + progress.summary(p, r))
            stuck = self._stuck(p)
            if stuck:
                lines.append(stuck)
        if self.last:
            s = f"Your last order: \"{self.last['text']}\" -> {self.last['outcome']} after {self.last['mins']:.0f} min."
            if self.last.get("history") and self.last["outcome"] != "done":
                s += "\nWhat went wrong along the way: " + " | ".join(self.last["history"])
            lines.append(s)
        hand = self._by_hand()
        if hand:
            lines.append(hand)
        if self.heard:
            lines.append("Said in chat lately:\n" + "\n".join(self.heard[-15:]))
            self.heard.clear()
        return "\n\n".join(lines)

    async def _decide(self, report: str, when: str) -> dict:
        from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock,
                                      create_sdk_mcp_server, query, tool)
        result: dict = {}
        look = self.actor._thinker_tools()
        schemas = {n: (d, s) for n, d, s in TOOLS if n in LOOK_TOOLS}

        def make(n):
            async def handler(args):
                t0 = time.time()
                try:
                    if result:
                        out = "your turn already ended; stop here"
                    elif n == "give_order":
                        result["order"], result["why"] = str(args.get("text", "")).strip(), args.get("why", "")
                        out = "sent; your turn ends here"
                    elif n == "wait":
                        result["wait"], result["why"] = float(args.get("minutes", 5)), args.get("why", "")
                        out = "ok; your turn ends here"
                    elif n == "finish":
                        result["finish"], result["done"] = True, bool(args.get("done"))
                        result["summary"] = str(args.get("summary", ""))
                        out = "ok; the project ends here"
                    elif n == "note":
                        with open(self.journal_path, "a") as f:
                            f.write(json.dumps({"when": when, "goal": self.goal[:80],
                                                "text": str(args.get("text", ""))[:1000]}) + "\n")
                        out = "noted"
                    elif n == "say":
                        await self.actor.say(str(args.get("text", ""))[:300])
                        out = "said"
                    elif n == "save_playbook":
                        from .library import save_playbook
                        out = save_playbook(args.get("name", ""), args.get("when", ""), args.get("orders") or [],
                                            args.get("result", ""))
                    else:
                        out = await look[n](args)
                except Exception as e:  # noqa: BLE001
                    out = f"error: {e!r}"
                self._log({"kind": "tool", "tool": n, "args": args, "out": str(out)[:3000],
                           "secs": round(time.time() - t0, 2)})
                return {"content": [{"type": "text", "text": str(out)}]}
            return handler

        sdk_tools = [tool(n, d, s)(make(n)) for n, (d, s) in schemas.items()]
        sdk_tools += [tool(n, d, s)(make(n)) for n, d, s in OWN_TOOLS]
        server = create_sdk_mcp_server("world", tools=sdk_tools)
        system = SYSTEM.format(name=self.actor.name, goal=self.goal, speaker=self.speaker,
                               milestones="; ".join(f"{lv} {nm}" for lv, nm, _ in progress.MILESTONES))
        try:
            from . import blueprints as bp
            names = sorted(bp.names()) if hasattr(bp, "names") else []
        except Exception:  # noqa: BLE001
            names = []
        if names:
            system += ("\nThe serf's planner has game-tested blocks it builds exactly (so an order that one of them covers, "
                       "fed by belts or pipes, is a safe size): " + ", ".join(names) + ".\n")
        from .library import playbooks
        books = playbooks()
        if books:
            system += "\nPlaybooks saved by earlier projects (orders that worked; adapt places to this world):\n" + \
                "\n".join(f"- {n} (when: {b.get('when')}; got: {b.get('result') or '?'}): " + " | ".join(b["orders"])
                          for n, b in list(books.items())[-12:])
        kw = dict(system_prompt=system, mcp_servers={"world": server}, tools=[],
                  allowed_tools=[f"mcp__world__{t.name}" for t in sdk_tools], setting_sources=[], model=self.model,
                  cwd=str(self.workdir), max_turns=24)
        if self.effort:
            kw["effort"] = self.effort
        prompt = ("Project journal so far:\n" + ("\n".join(self.journal()) or "(empty)") + "\n\n" + report +
                  "\n\nYour turn: look as needed, note what to remember, then give_order, wait or finish.")
        t0 = time.time()
        text = ""
        async for m in query(prompt=prompt, options=ClaudeAgentOptions(**kw)):
            if isinstance(m, AssistantMessage):
                text += "".join(b.text for b in m.content if isinstance(b, TextBlock))
            elif isinstance(m, ResultMessage):
                self.usd += float(m.total_cost_usd or 0)
        if "usage limit" in text.lower() or "hit your session limit" in text.lower():
            raise RuntimeError("usage limit: " + text[-200:])
        self.turns += 1
        self._log({"kind": "turn", "secs": round(time.time() - t0, 1), "result": result, "text": text[-2000:],
                   "usd_total": round(self.usd, 3)})
        return result or {"wait": 2.0, "why": "the turn ended without a decision"}
