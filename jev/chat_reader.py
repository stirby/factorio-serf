"""Opus reads the chat: one quick, low-effort decision per line, with the situation code gathers (what the serf is
doing, its queue, what it finished or gave up on lately, the conversation so far, where it is and what it carries).
The decision says whether the line is for the serf and what to do with it (a new job, more about a queued or the
running job, reopen a finished one, stop, answer, or let the planner look first), plus the reply to say now.

It replaces Jev's chat triage: in the live test of 25 Oct only 5 of 20 lines were handled well, mostly because the
right call needed context a narrow question never saw. The user: "smarter, not faster".

Its own session (the planner's can be busy planning for minutes), on the same Claude login, effort low. The session
is started fresh every so often so its context stays small; each line carries the situation it needs.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass

log = logging.getLogger("jev.chat_reader")

MODEL = "claude-opus-5-5"
ACTIONS = ("new_job", "add_to_queued", "change_running", "note_running", "reopen", "stop", "answer", "ask_planner",
           "none")
PLAYBOOKS = ("fix", "deliver", "plan")

SYSTEM = """You read the chat of a Factorio 2.0 (Space Age) multiplayer game for {name}, an AI character that plays \
alongside the players as their teammate and takes jobs from them. For each chat line you get the line and the \
situation as JSON, and you decide what {name} does with it. A planner (the same model, with tools to look at the map) \
works out and runs the jobs; you route the line and give the quick reply.

Fields of your answer:
- for_me: true when the line is meant for {name}: it names {name}, says @all or everyone, answers something {name} \
just said, or (with only one player online) asks for work or talks to whoever is listening. False when it's for \
another player.
- action, one of:
  new_job: asks for new work in the game (build, fix, bring items, follow, research, go somewhere, clear something). \
A line that points at a broken place ("no gears coming out of [gps], what's up?") is a fix job, not just a question. \
A line about a different place than a queued job's spot is a new job.
  add_to_queued: more about a job in `queued` (details, corrections, additions for that same job). Set order.
  change_running: changes how, where or what the running job does (another place, side, item, amount, method). The \
running plan stops and is redone with it. Set order to the running job's id.
  note_running: about the running job without changing it: a hint, encouragement, a go-ahead or "your call" \
answering what {name} asked. Set order to the running job's id.
  reopen: says a job in `recent_ended` isn't done, is still wrong, or should be finished after all (also after a \
stop). Set order.
  stop: stop, cancel, drop it, stop following. Everything running and queued stops.
  answer: a question or small talk you can answer from the situation (what it's doing, its queue, why a job failed, \
where it is, what it carries, how it's doing): the answer goes in reply.
  ask_planner: a question that needs a look at the base or the map first (where something is, how much is made, \
what's missing, what it would take): the planner looks and answers.
  none: nothing to do (not for {name}, or nothing to answer).
- order: the order id for add_to_queued, change_running, note_running and reopen; otherwise null.
- playbook (new_job only): fix = existing machines or belts stopped, starving, unpowered, out of fuel or broken and \
they want them working again; deliver = bring a stated number of specific items to a chest or to the player; plan = \
anything else (build, automate, belt A to B, mine, follow, research, move).
- multi (new_job only): true when the line asks for two or more separate jobs at once ("make gears here and research \
solar"); one build with several parts is one job.
- reply: what {name} says in chat right now, short and plain like a teammate (lower case is fine), owning its \
mistakes out loud. For a new job while it's busy, say it's next or its place in line. For ask_planner, a few words \
like "let me look" or nothing. Don't claim anything the situation doesn't show. Empty when nothing needs saying.
- why: a few words on your choice, for the log."""

SCHEMA = {
    "type": "object",
    "properties": {
        "for_me": {"type": "boolean"},
        "action": {"type": "string", "enum": list(ACTIONS)},
        "order": {"type": ["integer", "null"]},
        "playbook": {"type": "string", "enum": list(PLAYBOOKS)},
        "multi": {"type": "boolean"},
        "reply": {"type": "string"},
        "why": {"type": "string"},
    },
    "required": ["for_me", "action", "order", "playbook", "multi", "reply", "why"],
    "additionalProperties": False,
}


class ChatReaderError(Exception):
    pass


@dataclass
class ChatDecision:
    for_me: bool
    action: str
    order: int | None = None
    playbook: str = "plan"
    multi: bool = False
    reply: str = ""
    why: str = ""
    reader: str = "opus"  # "opus", or "rules" when Opus couldn't be asked

    @classmethod
    def parse(cls, d: dict) -> "ChatDecision":
        if not isinstance(d, dict):
            raise ChatReaderError(f"not an object: {d!r}"[:200])
        action = str(d.get("action") or "none")
        if action not in ACTIONS:
            raise ChatReaderError(f"unknown action {action!r}")
        order = d.get("order")
        try:
            order = int(order) if order is not None else None
        except (TypeError, ValueError):
            order = None
        pb = str(d.get("playbook") or "plan")
        return cls(bool(d.get("for_me")), action, order, pb if pb in PLAYBOOKS else "plan", bool(d.get("multi")),
                   str(d.get("reply") or "").strip()[:300], str(d.get("why") or "")[:200])


class ChatReader:
    FRESH_EVERY = 25  # lines per session before a fresh one

    def __init__(self, name: str, model: str = MODEL, effort: str = "low", timeout: float = 60):
        self.name, self.model, self.effort, self.timeout = name, model, effort, timeout
        self.client = None
        self.lines = 0
        self.calls, self.errors, self.cost_usd, self.secs = 0, 0, 0.0, 0.0
        self._session_cost = 0.0
        self._lock = asyncio.Lock()

    def _options(self):
        from claude_agent_sdk import ClaudeAgentOptions
        return ClaudeAgentOptions(system_prompt=SYSTEM.format(name=self.name), tools=[], allowed_tools=[],
                                  setting_sources=[], model=self.model, effort=self.effort, max_turns=3,
                                  output_format={"type": "json_schema", "schema": SCHEMA},
                                  stderr=lambda line: log.debug("[chat cli] %s", line))

    async def _connect(self) -> None:
        from claude_agent_sdk import ClaudeSDKClient
        await self.close()
        self.client = ClaudeSDKClient(self._options())
        await self.client.connect()
        self.lines, self._session_cost = 0, 0.0

    async def close(self) -> None:
        if self.client:
            try:
                await self.client.disconnect()
            except Exception:  # noqa: BLE001
                pass
            self.client = None

    async def decide(self, situation: dict) -> ChatDecision:
        """The decision for one line; raises ChatReaderError when Opus can't be asked or answers nonsense."""
        async with self._lock:
            t0 = time.time()
            try:
                if self.client is None or self.lines >= self.FRESH_EVERY:
                    await self._connect()
                self.lines += 1
                out = await asyncio.wait_for(self._ask(json.dumps(situation, default=str)), self.timeout)
                d = ChatDecision.parse(out)
            except ChatReaderError:
                self.errors += 1
                await self.close()
                raise
            except Exception as e:  # noqa: BLE001
                self.errors += 1
                await self.close()
                raise ChatReaderError(repr(e)[:300]) from e
            finally:
                self.calls += 1
                self.secs += time.time() - t0
            return d

    async def _ask(self, prompt: str) -> dict:
        from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock
        await self.client.query(prompt)
        text, out = "", None
        async for m in self.client.receive_response():
            if isinstance(m, AssistantMessage):
                text += "".join(b.text for b in m.content if isinstance(b, TextBlock))
            elif isinstance(m, ResultMessage):
                total = float(m.total_cost_usd or 0)
                self.cost_usd += max(0.0, total - self._session_cost)
                self._session_cost = total
                if m.is_error:
                    raise ChatReaderError(f"{m.subtype}: {(m.result or text)[:200]}")
                out = m.structured_output
        if out is None:  # no structured output: the first JSON object in the text
            i = text.find("{")
            try:
                out = json.JSONDecoder().raw_decode(text[i:])[0] if i >= 0 else None
            except ValueError:
                out = None
        if not isinstance(out, dict):
            raise ChatReaderError(f"no decision in the reply: {text[:200]!r}")
        return out
