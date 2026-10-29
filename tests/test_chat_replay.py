#!/usr/bin/env python3
"""Chat replay (no game, no model calls, $0, seconds): a live conversation, line by line with its timing, through the
actor's real chat handling and work loop, against a fake game and a fake planner. The chat reader's decision on each
line (Opus's, in play) is given by the case, so a case checks what the serf does with a decision. Seeded with the
2026-10-25 live session (player renamed).

A case: Case(name, lines=[L(secs, text, D(action, order, ...)), ...], expect=fn, runs={order id: secs}). secs counts
from the first line; D is the decision (none needed for a line that's only the serf's name); expect(r: Replay)
returns what went wrong (empty = pass); orders run until stopped unless `runs` ends them sooner. For a flagged live
moment, `--from-log <actor.jsonl> [HH:MM:SS HH:MM:SS]` prints its lines as L(...) to paste.

    Run: .venv/bin/python tests/test_chat_replay.py
"""
import asyncio
import json
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import jev.actor as actor_mod  # noqa: E402
from jev.chat_reader import ChatDecision, ChatReaderError  # noqa: E402
from jev.actor import Actor  # noqa: E402
from jev.thinker import Request, Thinker  # noqa: E402

FAILS = []


def check(name, cond, info=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  ({info})" if info and not cond else ""))
    if not cond:
        FAILS.append(name)


# ---------------------------------------------------------------------------- case shape
def D(action, order=None, playbook="plan", reply="", for_me=True, multi=False):
    """The chat reader's decision on a line (the live log's chat record has the same fields)."""
    return ChatDecision(for_me, action, order, playbook, multi, reply, "replay")


ERROR = "error"  # a line the reader fails on (Opus unreachable): the plain rules decide


@dataclass
class L:
    secs: float
    text: str
    d: ChatDecision | str | None = None
    speaker: str = "player"


@dataclass
class Case:
    name: str
    lines: list
    expect: Callable[["Replay"], list]
    runs: dict = field(default_factory=dict)  # order id -> seconds its job takes (default: until stopped)
    game: dict = field(default_factory=dict)  # FakeGame attributes to set first (e.g. job: the running job)


# ---------------------------------------------------------------------------- fakes
class Clock:
    """Replay time: jev.actor's time.time() reads it, so the 90 s and 180 s windows see the live gaps."""

    def __init__(self):
        self.t0 = self.now = time.time()

    def time(self):
        return self.now

    def __getattr__(self, k):
        return getattr(time, k)


class FakeGame:
    def __init__(self, clock, name="serf"):
        self.clock, self.name, self.away = clock, name, False
        self.chat, self.events = asyncio.Queue(), asyncio.Queue()
        self.said, self.cancels, self.acts, self.calls = [], [], [], []
        self.job = None  # the character's running job, as the mod's list op describes it

    async def say(self, text):
        self.said.append((round(self.clock.now - self.clock.t0, 1), text))

    async def cancel(self, reason="replanned", job=None):
        self.cancels.append(reason)

    async def status(self, **kw):
        pass

    async def me(self):
        return {"position": [0.0, 0.0], "inventory": {}, "surface": "nauvis", "free_slots": 40}

    async def call(self, op, timeout=30, **kw):
        self.calls.append((op, kw))
        if op == "list":  # the mod's reply shape (a bare list here hid a bug: live test 2026-10-25)
            return {"agents": [{"name": self.name, "job": self.job}]}
        return {}

    async def act(self, actions, replace=False):
        self.acts.extend(actions)
        return []


class FakeReader:
    """The chat reader: each line's decision from the case; what it was shown is kept."""

    def __init__(self, table):
        self.table, self.seen = table, []

    async def decide(self, situation):
        self.seen.append(situation)
        d = self.table.get(situation["message"])
        if d is None:
            raise AssertionError(f"no decision for line {situation['message']!r}")
        if d == ERROR:
            raise ChatReaderError("unreachable (replay)")
        return d

    async def close(self):
        pass


class FakeThinker:
    """Takes requests as the real one does; a question or small talk is answered at once (a line through the actor's
    say, as the say tool does, then a no-plan answer). Plan requests aren't made: the orders' work is stubbed."""

    def __init__(self, actor):
        self.actor, self.asked = actor, []

    def ask(self, req):
        self.asked.append(req)
        if req.kind == "question":
            asyncio.get_running_loop().create_task(self._answer(req))

    async def _answer(self, req):
        await self.actor.say("(planner's answer)")
        await self.actor._on_plan({"goal": None, "steps": [], "no_plan": True, "text": "answered"}, req)


@dataclass
class Replay:
    actor: Actor
    game: FakeGame
    thinker: FakeThinker
    reader: FakeReader

    @property
    def orders(self):
        return self.actor.orders

    @property
    def said(self):
        return [t for _, t in self.game.said]

    def records(self, kind):
        p = self.actor.log_path
        rows = [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []
        return [r for r in rows if r.get("kind") == kind]

    def order(self, oid):
        return next((o for o in self.orders if o.id == oid), None)


async def _settle(n=15):
    for _ in range(n):
        await asyncio.sleep(0.002)


async def replay(case: Case) -> Replay:
    clock = Clock()
    real_time = actor_mod.time
    actor_mod.time = clock
    tmp = tempfile.TemporaryDirectory()
    try:
        g = FakeGame(clock)
        for k, v in case.game.items():
            setattr(g, k, v)
        a = Actor(g, None, Path(tmp.name), "serf", think=False)
        th = FakeThinker(a)
        a.thinker = th
        rd = FakeReader({ln.text: ln.d for ln in case.lines if ln.d})
        a.chat_reader = rd

        async def no_tidy(*args, **kw):
            return None

        async def mine_near(o, full=False):
            return None

        async def job(o):  # the order's work: runs until stopped, or for case.runs[o.id] replay seconds
            secs, start = case.runs.get(o.id), clock.now
            while o.status != "cancelled":
                if secs is not None and clock.now - start >= secs:
                    return True
                await asyncio.sleep(0.002)
            return False

        a.runner.tidy, a._mine_near, a._do_order = no_tidy, mine_near, job
        work = asyncio.create_task(a._work_loop())
        seen = set()
        for ln in case.lines:
            clock.now = clock.t0 + ln.secs
            await _settle()
            if ln.speaker == "@serf":  # the serf's own line (as its planner's say tool would)
                await a.say(ln.text)
            else:
                await a._on_chat({"player": ln.speaker, "message": ln.text, "position": [0.0, 0.0]})
            for o in a.orders:  # Order.t is stamped with the real clock: put new ones on replay time
                if o.id not in seen:
                    seen.add(o.id)
                    o.t = clock.now
            await _settle()
        clock.now += 1
        await _settle(30)
        work.cancel()
        try:
            await work
        except BaseException:  # noqa: BLE001
            pass
        r = Replay(a, g, th, rd)
        r.problems = case.expect(r)
        return r
    finally:
        actor_mod.time = real_time
        tmp.cleanup()


# ---------------------------------------------------------------------------- the 2026-10-25 session
TELEPORT = L(0, "can you teleport back to nauvis spawn", D("new_job"))
GHOSTS = L(70, "Okay serf here's what I'm thinking I need you to finish laying the ghosts for this logistics "
               "automation right here up to blue belts with space to add green", D("new_job"))
LOOK_AGAIN = L(135, "serf do you see the gear and iron plate input? i don't have the rest of the machiens for you but "
                    "look agian before working just figure it out make it clean", D("add_to_queued", 2))
TF = L(145, "tf is number 1", D("ask_planner"))
NUMBER_1 = L(156, "what is number 1 in your queue", D("ask_planner"))
HERE = L(187, "no I want you to do the logistics automation here. Usually following me is a short task like 10 seconds",
         D("add_to_queued", 2))
STOP = L(199, "JESUS CHRIST STOP QUEUEING SHIT SERF", D("stop"))
JUST_FINISH = L(212, "JUST FINISH THE LOGISTICS AUTOMATION I STATED HERE", D("reopen", 2))


def expect_name_only(r):
    out = []
    if r.said != ["yes? what do you need?"] * 2:
        out.append(f"said {r.said}")
    if r.orders:
        out.append(f"{len(r.orders)} order(s) made")
    if r.thinker.asked:
        out.append("asked the planner")
    return out


def expect_small_talk(r):
    out = []
    if r.orders:
        out.append(f"{len(r.orders)} order(s) made")
    if r.thinker.asked:
        out.append(f"asked the planner {[q.kind for q in r.thinker.asked]}")
    if r.said != ["doing good, free for a job", "all good, nothing queued"]:
        out.append(f"said {r.said}")
    seen = r.reader.seen
    if len(seen) != 2 or "doing good, free for a job" not in " ".join(seen[1]["recent_chat"]):
        out.append("the second line's situation doesn't show the conversation so far")
    return out


def expect_flag(r):
    out = []
    if r.orders:
        out.append(f"{len(r.orders)} orders: {[o.text for o in r.orders]}")
    if r.thinker.asked:
        out.append(f"asked the planner {[q.text[:40] for q in r.thinker.asked]}")
    if r.said:
        out.append(f"said in chat {r.said}")
    f = r.records("flag")
    if len(f) != 1 or f[0].get("note") != "that was wrong, I meant the red and blue machines":
        out.append(f"flag records {f}")
    if not any(op == "tell" and kw.get("player") == "player" for op, kw in r.game.calls):
        out.append("no confirmation to the player who flagged")
    return out


def expect_ping_quiet(r):
    out = []
    if r.orders or r.said or r.thinker.asked:
        out.append(f"orders {[o.text for o in r.orders]}, said {r.said}, asked {len(r.thinker.asked)}")
    if r.actor.pings.get("player", (None, None))[:2] != (10.0, -20.0):
        out.append(f"pings {r.actor.pings}")
    return out


def expect_ping_joins_order(r):
    out = []
    o = r.order(1)
    if len(r.orders) != 1 or not o:
        return [f"{len(r.orders)} orders"]
    if (10.0, -20.0) not in o.points or not any("pinged" in n for n in o.notes):
        out.append(f"order 1 points {o.points}, notes {o.notes}")
    if "got it, [gps=10,-20]" not in r.said:
        out.append(f"said {r.said}")
    return out


def expect_ping_answers_ask(r):
    out = []
    o = r.order(1)
    if len(r.orders) != 1 or not o:
        return [f"{len(r.orders)} orders"]
    if o.reopened != 1 or (10.0, -20.0) not in o.points:
        out.append(f"order 1 reopened {o.reopened}, points {o.points}, status {o.status}")
    if not r.records("reopen"):
        out.append("no reopen record")
    return out


PING = L(0, "[gps=10,-20,nauvis]")
CHESTS = L(0, "serf put a row of 4 iron chests down", D("new_job"))


def expect_order_ends_follow(r):
    out = []
    if "a new order comes before following" not in r.game.cancels:
        out.append(f"cancels {r.game.cancels}")
    if r.records("error"):
        out.append(f"errors {r.records('error')}")
    return out


def expect_line_goes_to_running_job(r):
    out = []
    o3, o4 = r.order(1), r.order(2)
    if len(r.orders) != 2:
        return [f"{len(r.orders)} orders: {[(o.id, o.text[:30]) for o in r.orders]}"]
    if any("construction bots" in n for n in o4.notes):
        out.append(f"joined the queued roboport order: {o4.notes}")
    if not any("construction bots" in n for n in o3.notes):
        out.append(f"the running rock job didn't get it: {o3.notes}")
    return out


# 2026-10-25 14:01-14:05, Vulcanus: rocks running, roboports queued, then a line about the rocks
ROCKS = L(0, "Serf there are way more boulders to break", D("new_job"))
ROBOPORTS = L(90, "serf after you're done make a clean grid of robot ports as ghosts and make as many as you can so we "
                  "have better base coverage", D("new_job"))
BOTS = L(147, "btw serf you should break all the rocks/boulders vents. Can you mark areas for deletion and use "
              "construction bots?", D("change_running", 1))


def expect_follow(r):
    out = []
    if len(r.orders) != 1:
        out.append(f"{len(r.orders)} orders: {[o.text for o in r.orders]}")
    elif r.orders[0].status != "done":
        out.append(f"order ended {r.orders[0].status}")
    if any("queue" in t for t in r.said):
        out.append(f"said {r.said}")
    return out


def expect_followup_joins(r):
    out = []
    if len(r.orders) != 2:
        out.append(f"{len(r.orders)} orders: {[(o.id, o.text[:40]) for o in r.orders]}")
    o2 = r.order(2)
    if o2 and (o2.status != "new" or len(o2.notes) != 2):
        out.append(f"order 2 is {o2.status} with {len(o2.notes)} notes")
    if sum(t.startswith("got it, adding that to #2") for t in r.said) != 2:
        out.append(f"said {r.said}")
    if any(("#2" in t or "#3" in t) and "adding that to" not in t for t in r.said):
        out.append("queued a second copy")
    return out


def expect_stop(r):
    out = []
    left = [(o.id, o.status) for o in r.orders if o.status in ("new", "working", "thinking")]
    if left:
        out.append(f"still on {left}")
    if not r.game.cancels:
        out.append("never cancelled the character's jobs")
    if "ok, stopped" not in r.said:
        out.append(f"said {r.said}")
    dropped = [x for rec in r.records("dropped") for x in rec.get("orders", [])]
    if 2 not in dropped:
        out.append(f"dropped {dropped}")
    return out


def expect_finish_after_stop(r):
    active = [o for o in r.orders if o.status in ("new", "working", "thinking")]
    if not any("logistics automation" in (o.text + " ".join(o.notes)).lower() for o in active):
        return [f"no live order for it: {[(o.id, o.status, o.text[:30]) for o in r.orders]}"]
    return []


def expect_question_keeps_order(r):
    out = []
    st = {o.id: o.status for o in r.orders}
    if st != {1: "working", 2: "new"}:
        out.append(f"orders {st}")
    asks = [q for q in r.thinker.asked if q.kind == "question"]
    if len(asks) != 2 or any(q.order_id is not None for q in asks):
        out.append(f"planner asks {[(q.kind, q.order_id) for q in r.thinker.asked]}")
    elif not ("working on #1" in asks[-1].text and "queued: #2" in asks[-1].text):
        out.append("the question's prompt doesn't list the orders")
    return out


def expect_change_running(r):
    o = r.order(1)
    out = []
    if not o or not o.interrupt or "other side" not in o.interrupt:
        out.append(f"order 1 interrupt {o and o.interrupt}")
    if "player changed the job" not in r.game.cancels:
        out.append(f"cancels {r.game.cancels}")
    if "ok, switching sides" not in r.said or len(r.orders) != 1:
        out.append(f"said {r.said}, {len(r.orders)} orders")
    return out


def expect_situation(r):
    sit = r.reader.seen[-1]
    out = []
    if (sit.get("running") or {}).get("id") != 1 or [q["id"] for q in sit.get("queued") or []] != [2]:
        out.append(f"running {sit.get('running')}, queued {sit.get('queued')}")
    if "#2, the logistics ghosts" not in r.said:
        out.append(f"said {r.said}")
    return out


def expect_rules_fallback(r):
    out = []
    if len(r.orders) != 1 or r.orders[0].status != "cancelled":
        out.append(f"orders {[(o.text[:20], o.status) for o in r.orders]}")
    if "ok, stopped" not in r.said:
        out.append(f"said {r.said}")
    if any("weather" in o.text for o in r.orders):
        out.append("a line not for it became an order")
    return out


CASES = [
    Case("name only gets an answer, no order", [L(0, "serf"), L(3, "@serf")], expect_name_only),
    Case("small talk gets a one-line reply, no order",
         [L(0, "serf how are you doing", D("answer", reply="doing good, free for a job")),
          L(60, "how are you doing bro", D("answer", reply="all good, nothing queued"))], expect_small_talk),
    Case("a ! line is a flag for the developer, not an order", [
        L(0, "! that was wrong, I meant the red and blue machines", D("new_job"))], expect_flag),
    Case("a ping on its own is remembered, not an order or a reply", [PING], expect_ping_quiet),
    Case("a ping right after a player's order is that order's spot", [CHESTS, L(25, "[gps=10,-20,nauvis]")],
         expect_ping_joins_order),
    Case("the serf asks for a ping; the next ping reopens that order with the spot",
         [CHESTS, L(2, "where do you want them? ping where you want it", speaker="@serf"),
          L(200, "[gps=10,-20,nauvis]")], expect_ping_answers_ask, runs={1: 5}),
    Case("a new order ends the follow job first", [CHESTS], expect_order_ends_follow,
         game={"job": {"id": 7, "op": "follow", "what": "following player"}}),
    Case("a line about the running job goes to it, not to the queued one", [ROCKS, ROBOPORTS, BOTS],
         expect_line_goes_to_running_job),
    Case("follow me is one order", [L(0, "okay follow me", D("new_job"))], expect_follow,
         runs={1: 0}),
    Case("follow-ups join the queued job", [TELEPORT, GHOSTS, LOOK_AGAIN, HERE], expect_followup_joins),
    Case("stop ends the job and clears the queue", [TELEPORT, GHOSTS, STOP], expect_stop),
    Case("after stop, 'just finish the X I stated' does X", [TELEPORT, GHOSTS, STOP, JUST_FINISH],
         expect_finish_after_stop),
    Case("a question about the queue keeps the orders", [TELEPORT, GHOSTS, TF, NUMBER_1], expect_question_keeps_order),
    Case("a change to the running job stops its plan to redo it", [
        CHESTS, L(30, "serf put them on the other side of the belt", D("change_running", 1, reply="ok, switching sides"))],
         expect_change_running),
    Case("the reader sees the queue and the running job", [TELEPORT, GHOSTS, L(100, "serf what's next", D(
        "answer", reply="#2, the logistics ghosts"))], expect_situation),
    Case("with Opus unreachable, an @ is still an order and stop still stops", [
        L(0, "@serf build a wall around the base", ERROR), L(20, "stop", ERROR), L(30, "nice weather", ERROR)],
         expect_rules_fallback),
]


def test_cases():
    for c in CASES:
        try:
            r = asyncio.run(replay(c))
            check(c.name, not r.problems, "; ".join(r.problems))
        except Exception as e:  # noqa: BLE001
            check(c.name, False, f"crashed: {e!r}")


# ---------------------------------------------------------------------------- the planner folding requests
class FakeClient:
    """The planner's model: submits a plan when the prompt it gets contains `plan_for`, else only talks."""

    def __init__(self, thinker, plan_for=None):
        self.th, self.plan_for, self.prompts = thinker, plan_for, []

    async def query(self, prompt):
        self.prompts.append(prompt)

    async def receive_response(self):
        if self.plan_for and self.plan_for in self.prompts[-1]:
            await self.th._submit({"goal": "the thing", "steps": [{"do": "wait", "seconds": 1}], "more": False})
        return
        yield  # an async generator with nothing to say

    async def interrupt(self):
        pass

    async def disconnect(self):
        pass


async def fold(first: Request, second: Request, plan_for: str | None) -> list:
    """Both requests queued before the planner looks: it folds them into one turn. The answers it gives, as
    (order id, plan)."""
    got = []

    async def on_plan(plan, req):
        got.append((req.order_id if req else None, plan))

    with tempfile.TemporaryDirectory() as d:
        th = Thinker("serf", {}, on_plan, Path(d))
        th.client = FakeClient(th, plan_for)

        async def no_restart():
            pass
        th._restart = no_restart
        th.ask(first)
        th.ask(second)
        task = asyncio.create_task(th._loop())
        for _ in range(100):
            await asyncio.sleep(0.005)
            if th.queue.empty() and not th.busy:
                break
        task.cancel()
        try:
            await task
        except BaseException:  # noqa: BLE001
            pass
    return got


def test_thinker_folding():
    q = Request("question", "player asked in chat: \"tf is number 1\"", None)
    o = Request("order", "ORDER-5: finish laying the ghosts for the logistics automation", 5)
    got = asyncio.run(fold(q, o, plan_for="ORDER-5"))
    plans = [p for oid, p in got if oid == 5 and p.get("steps")]
    check("folded behind a question, an order still gets its plan", bool(plans), f"answers {[(i, p.get('goal')) for i, p in got]}")
    got = asyncio.run(fold(Request("question", "player asked in chat: \"tf is number 1\"", None),
                           Request("order", "ORDER-5: finish laying the ghosts", 5), plan_for=None))
    check("folded behind a question, an order with no plan still gets an answer (nothing waits forever)",
          any(oid == 5 for oid, _ in got), f"answers {[(i, p.get('no_plan')) for i, p in got]}")
    got = asyncio.run(fold(Request("order", "ORDER-5: finish laying the ghosts", 5),
                           Request("question", "player asked in chat: \"tf is number 1\"", None), plan_for="ORDER-5"))
    check("an order first, a question folded behind it: the order gets the plan",
          any(oid == 5 and p.get("steps") for oid, p in got), f"answers {[(i, p.get('goal')) for i, p in got]}")


# ---------------------------------------------------------------------------- new cases from a live log
def from_log(path: str, start: str | None = None, end: str | None = None) -> None:
    """Print a live log's chat lines (between HH:MM:SS start and end, local time) as L(...) entries, with the chat
    reader's decisions, to paste into a new Case."""
    rows = [json.loads(x) for x in Path(path).expanduser().read_text().splitlines() if x.strip()]
    t0 = None
    for r in rows:
        if r.get("kind") != "chat" or r.get("speaker") in ("serf", "project", "planner") or r.get("assigned"):
            continue
        hms = time.strftime("%H:%M:%S", time.localtime(r["t"]))
        if (start and hms < start) or (end and hms > end):
            continue
        t0 = r["t"] if t0 is None else t0
        d = (f"D({r.get('action')!r}, {r.get('order')!r}, {r.get('playbook')!r}, reply={r.get('reply') or ''!r}"
             + (", for_me=False" if not r.get("for_me") else "") + (", multi=True" if r.get("multi") else "") + ")")
        print(f"    L({r['t'] - t0:.0f}, {r.get('msg')!r}, {d}, speaker={r.get('speaker')!r}),  # {hms}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--from-log":
        from_log(*sys.argv[2:5])
        sys.exit(0)
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print(f"\n{'ALL OK' if not FAILS else str(len(FAILS)) + ' FAILED: ' + ', '.join(FAILS)}")
    sys.exit(1 if FAILS else 0)
