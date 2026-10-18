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
STOP_WORDS = re.compile(r"^\s*(stop|halt|freeze|cancel|abort)\b[\s!.]*$", re.I)


@dataclass
class Routed:
    targets: set[str]  # agents to wake
    message: str
    stop: bool  # "@x stop" style hard stop: cancel jobs immediately, before the model even sees it


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
    return Routed(targets=targets, message=text, stop=bool(targets) and bool(STOP_WORDS.match(body)))
