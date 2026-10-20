"""Chat routing: who gets woken by which message.

- "@claude-2 ..." or "claude-2, ..." wakes claude-2. Several names can be addressed at once.
- "@all", "@crew", "@everyone" wake every agent.
- "@claude" / "claude ..." with no number wakes the foreman if there is one, else everyone.
- Anything else is ambient: agents see it on their next turn, but it doesn't wake them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

ALL_WORDS = {"all", "crew", "everyone", "team", "yall", "y'all"}
COME = re.compile(r"\b(come here|come to me|over here|get over here|come back)\b", re.I)
FOLLOW = re.compile(r"\b(follow me|follow along|stick with me|tag along)\b", re.I)
STOP_WORDS = re.compile(r"^\s*(stop|halt|freeze|cancel|abort)\b[\s!.]*$", re.I)
MODEL_CMD = re.compile(r"^\s*model(?:\s+([\w.\-/:]+))?[\s!.?]*$", re.I)
FAST_CMD = re.compile(r"^\s*fast(?:\s+mode)?(?:\s+(on|off))?[\s!.?]*$", re.I)

MODEL_ALIASES = {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5", "haiku": "claude-haiku-5-5",
                 "fable": "claude-fable-5-1"}
FAST_MODELS = ("claude-opus-5-5", "claude-opus-5", "claude-opus-4-8")  # the models with a fast mode


@dataclass
class Routed:
    targets: set[str]  # agents to wake
    message: str
    stop: bool  # "@x stop" style hard stop: cancel jobs immediately, before the model even sees it
    direct: str | None = None  # "come" | "follow": start moving right away, no model call needed
    # ("model", name or "") | ("fast", "on" | "off" | ""): a settings change the app makes itself, no model call
    command: tuple[str, str] | None = None


def parse_command(body: str) -> tuple[str, str] | None:
    """"model opus" / "model" / "fast on" / "fast off" / "fast" -> (command, argument)."""
    if m := MODEL_CMD.match(body):
        return "model", (m.group(1) or "").lower()
    if m := FAST_CMD.match(body):
        return "fast", (m.group(1) or "").lower()
    return None


def resolve_model(name: str) -> str | None:
    """"opus" -> claude-opus-5-5; full ids (claude-..., provider/model) pass through; anything else is unknown."""
    name = name.lower()
    if name in MODEL_ALIASES:
        return MODEL_ALIASES[name]
    return name if name.startswith("claude-") or "/" in name else None


def route(text: str, agent_names: list[str], foreman: str | None) -> Routed:
    names = {n.lower(): n for n in agent_names}
    targets: set[str] = set()
    lowered = text.lower()

    for m in re.finditer(r"@([\w\-']+)", lowered):
        word = m.group(1)[:-2] if m.group(1).endswith("'s") else m.group(1)
        if word in names:
            targets.add(names[word])
        elif word in ALL_WORDS:
            targets.update(agent_names)
        elif word in ("claude", "claudes", "bot", "bots"):
            targets.update([foreman] if foreman and word in ("claude", "bot") else agent_names)

    # Bare name mentions: "claude-1 come here", "ok claude-2, thanks"
    for low, real in names.items():
        if re.search(rf"(?<![\w@-]){re.escape(low)}(?![\w-])", lowered):
            targets.add(real)

    if not targets and re.match(r"^\s*(hey |ok |yo )?claude\b", lowered):
        targets.update([foreman] if foreman else agent_names)

    body = re.sub(r"@[\w\-']+[,:]?\s*", "", text).strip()
    direct = command = None
    if targets:
        direct = "follow" if FOLLOW.search(body) else "come" if COME.search(body) else None
        command = parse_command(body)
    return Routed(targets=targets, message=text, stop=bool(targets) and bool(STOP_WORDS.match(body)), direct=direct,
                  command=command)
