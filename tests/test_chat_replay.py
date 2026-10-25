#!/usr/bin/env python3
"""Chat replay (no game, no model calls, $0, seconds): a live conversation, line by line with its timing, through the
actor's real chat handling and work loop, against a fake game and a fake planner. Jev's reading of each line is the
one the live log recorded, so a case replays what the serf saw. Seeded with the 2026-10-25 live session (player
renamed).

A case: Case(name, lines=[L(secs, text, J(kind, addressed, kind_conf, ...)), ...], expect=fn, runs={order id:
secs}). secs counts from the first line; J is Jev's reading (none needed for a line that's only the serf's name);
expect(r: Replay) returns what went wrong (empty = pass); orders run until stopped unless `runs` ends them sooner.
For a flagged live moment, `--from-log <actor.jsonl> [HH:MM:SS HH:MM:SS]` prints its lines as L(...) to paste.

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
from jev import decide  # noqa: E402
from jev.actor import Actor  # noqa: E402
from jev.thinker import Request, Thinker  # noqa: E402

FAILS = []


def check(name, cond, info=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  ({info})" if info and not cond else ""))
    if not cond:
        FAILS.append(name)


# ---------------------------------------------------------------------------- case shape
@dataclass
class J:
    """Jev's reading of a line (the live log's chat record), plus its answers to the follow-up questions."""
    kind: str
    addressed: float = 0.9
    kind_conf: float = 0.9
    playbook: str = "plan"
    playbook_conf: float = 1.0
    multi: float = 0.0
    qtype: tuple = ("other", 0.5)  # decide.question_type
    not_done: float = 0.0
    changes_plan: float = 0.0


@dataclass
class L:
    secs: float
    text: str
    jev: J | None = None
    speaker: str = "player"


@dataclass
class Case:
    name: str
    lines: list
    expect: Callable[["Replay"], list]
    runs: dict = field(default_factory=dict)  # order id -> seconds its job takes (default: until stopped)


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
        return [] if op == "list" else {}

    async def act(self, actions, replace=False):
        self.acts.extend(actions)
        return []


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
    table = {ln.text: ln.jev for ln in case.lines if ln.jev}

    def reading(msg):
        if msg not in table:
            raise AssertionError(f"no Jev reading for line {msg!r}")
        return table[msg]

    async def chat(jev, me, speaker, message, doing, last_said):
        j = reading(message)
        return decide.ChatCall(j.addressed, j.kind, j.kind_conf, j.playbook, j.playbook_conf, j.multi)

    async def question_type(jev, message):
        return reading(message).qtype

    async def not_done(jev, job, message):
        return reading(message).not_done

    async def changes_plan(jev, doing, message):
        return reading(message).changes_plan

    saved = {k: getattr(decide, k) for k in ("chat", "question_type", "not_done", "changes_plan")}
    real_time = actor_mod.time
    decide.chat, decide.question_type, decide.not_done, decide.changes_plan = chat, question_type, not_done, \
        changes_plan
    actor_mod.time = clock
    tmp = tempfile.TemporaryDirectory()
    try:
        g = FakeGame(clock)
        a = Actor(g, None, Path(tmp.name), "serf", think=False)
        th = FakeThinker(a)
        a.thinker = th

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
        r = Replay(a, g, th)
        r.problems = case.expect(r)
        return r
    finally:
        for k, v in saved.items():
            setattr(decide, k, v)
        actor_mod.time = real_time
        tmp.cleanup()


# ---------------------------------------------------------------------------- the 2026-10-25 session
TELEPORT = L(0, "can you teleport back to nauvis spawn", J("new_job", 0.78, 0.56, "plan", 0.97))
GHOSTS = L(70, "Okay serf here's what I'm thinking I need you to finish laying the ghosts for this logistics "
               "automation right here up to blue belts with space to add green", J("new_job", 0.92, 0.96, "plan", 1.0))
LOOK_AGAIN = L(135, "serf do you see the gear and iron plate input? i don't have the rest of the machiens for you but "
                    "look agian before working just figure it out make it clean", J("new_job", 0.94, 0.33, "plan", 0.83))
TF = L(145, "tf is number 1", J("question", 0.69, 0.82, "plan", 0.95, qtype=("other", 0.52)))
NUMBER_1 = L(156, "what is number 1 in your queue", J("question", 0.72, 0.95, "plan", 0.97, qtype=("other", 0.72)))
HERE = L(187, "no I want you to do the logistics automation here. Usually following me is a short task like 10 seconds",
         J("new_job", 0.77, 0.78, "plan", 1.0))
STOP = L(199, "JESUS CHRIST STOP QUEUEING SHIT SERF", J("stop", 0.94, 0.88, "plan", 0.79))
# not_done 0.69: Jev's reading of this line against the logistics job (asked 2026-10-25; "ok thanks that's enough" 0.16)
JUST_FINISH = L(212, "JUST FINISH THE LOGISTICS AUTOMATION I STATED HERE", J("more_info", 0.84, 0.76, "plan", 1.0,
                                                                            not_done=0.69))


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
    asks = r.thinker.asked
    if len(asks) != 2 or any(q.kind != "question" or q.order_id is not None for q in asks):
        out.append(f"planner asks {[(q.kind, q.order_id) for q in asks]}")
    elif not all("small talk" in q.text for q in asks):
        out.append("not asked as small talk")
    if len(r.said) != 2:
        out.append(f"said {r.said}")
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
CHESTS = L(0, "serf put a row of 4 iron chests down", J("new_job", 0.95, 0.95, "plan", 1.0))


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
    if r.said.count("got it, adding that to the job") != 2:
        out.append(f"said {r.said}")
    if any("#2" in t or "#3" in t for t in r.said):
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


CASES = [
    Case("name only gets an answer, no order", [L(0, "serf"), L(3, "@serf")], expect_name_only),
    Case("small talk gets a one-line reply, no order",
         [L(0, "serf how are you doing", J("chatter", 0.88, 0.62, "plan", 1.0)),
          L(60, "how are you doing bro", J("chatter", 0.57, 0.87, "plan", 1.0))], expect_small_talk),
    Case("a ! line is a flag for the developer, not an order", [
        L(0, "! that was wrong, I meant the red and blue machines", J("new_job", 0.9, 0.9, "plan", 1.0))], expect_flag),
    Case("a ping on its own is remembered, not an order or a reply", [PING], expect_ping_quiet),
    Case("a ping right after a player's order is that order's spot", [CHESTS, L(25, "[gps=10,-20,nauvis]")],
         expect_ping_joins_order),
    Case("the serf asks for a ping; the next ping reopens that order with the spot",
         [CHESTS, L(2, "where do you want them? ping where you want it", speaker="@serf"),
          L(200, "[gps=10,-20,nauvis]")], expect_ping_answers_ask, runs={1: 5}),
    Case("follow me is one order", [L(0, "okay follow me", J("new_job", 0.72, 1.0, "plan", 1.0))], expect_follow,
         runs={1: 0}),
    Case("follow-ups join the queued job", [TELEPORT, GHOSTS, LOOK_AGAIN, HERE], expect_followup_joins),
    Case("stop ends the job and clears the queue", [TELEPORT, GHOSTS, STOP], expect_stop),
    Case("after stop, 'just finish the X I stated' does X", [TELEPORT, GHOSTS, STOP, JUST_FINISH],
         expect_finish_after_stop),
    Case("a question about the queue keeps the orders", [TELEPORT, GHOSTS, TF, NUMBER_1], expect_question_keeps_order),
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
    """Print a live log's chat lines (between HH:MM:SS start and end, local time) as L(...) entries, Jev's readings
    included, to paste into a new Case."""
    rows = [json.loads(x) for x in Path(path).expanduser().read_text().splitlines() if x.strip()]
    t0 = None
    for i, r in enumerate(rows):
        if r.get("kind") != "chat" or r.get("speaker") in ("serf", "project", "planner"):
            continue
        hms = time.strftime("%H:%M:%S", time.localtime(r["t"]))
        if (start and hms < start) or (end and hms > end):
            continue
        t0 = r["t"] if t0 is None else t0
        extra = ""
        for nxt in rows[i + 1:i + 6]:
            if nxt.get("kind") == "chat":
                break
            if nxt.get("kind") == "question":
                extra += f", qtype=({nxt.get('type')!r}, {nxt.get('conf')})"
            elif nxt.get("kind") in ("not_done", "changes_plan"):
                extra += f", {nxt['kind']}={nxt.get('p')}"
        j = (f"J({r.get('kind_')!r}, {r.get('addressed')}, {r.get('kind_conf')}, {r.get('playbook')!r}, "
             f"{r.get('playbook_conf')}{extra})")
        print(f"    L({r['t'] - t0:.0f}, {r.get('msg')!r}, {j}, speaker={r.get('speaker')!r}),  # {hms}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--from-log":
        from_log(*sys.argv[2:5])
        sys.exit(0)
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print(f"\n{'ALL OK' if not FAILS else str(len(FAILS)) + ' FAILED: ' + ', '.join(FAILS)}")
    sys.exit(1 if FAILS else 0)
