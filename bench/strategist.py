"""The campaign's player: an Opus session with a long-term goal that gives the serf orders in chat, one at a time, the
way a person would. It can look at the world with the planner's read-only tools, keeps a journal (its memory from
one turn to the next), and ends each turn with give_order or wait. The serf takes the order like any other: its fast
paths, its planner, its keepers. The strategist decides how big each order is, which is what's being measured."""
from __future__ import annotations

import json
import time
from pathlib import Path

from jev.progress import MILESTONES
from jev.thinker import TOOLS

MODEL = "claude-opus-5-5"
LOOK_TOOLS = ("area", "find", "recipe", "free_space", "me", "production", "diagnose", "techs")

SYSTEM = """You are the player in a Factorio 2.0 (Space Age) world, single player, no enemies. Your helper is a \
character called "serf" that takes orders from chat. You don't act in the world yourself: you look around with \
your tools and give the serf orders, one at a time, like a player in multiplayer would. The long-term goal: \
{goal}

What the serf does well on its own (fast, no planning): machines making one product off a belt that's already \
there ("make gears off the belt at [gps]", "4 furnaces smelting the ore belt at [gps], plates into chests"), \
belting items from a belt end to a machine or chest, setting up a mine on an ore patch and belting the ore to a \
place, fixing broken things ("no gears coming out of [gps], fix it"), copying a build it just made to other \
places, swapping belts or assemblers for better ones, and research ("research automation 2"). Anything bigger \
goes to its own planner (Opus), which handles multi-part builds: "build a smelting column for the iron patch at \
[gps] and belt the plates to [gps]", "set up oil processing at [gps]". It walks, mines, crafts and builds by hand \
like a player, using what's in chests and what it can craft.

How to direct it:
- You're measured by how far the world gets toward the goal, and by giving the serf the largest orders it can \
complete on its own. Start with orders you think it can do, then grow them as it succeeds. If one fails, look at \
why (area, diagnose) and either break it down or change approach.
- Build things that keep running without help: belts from mines to furnaces, fuel by belt or inserter rather \
than by hand, power that scales. A base that needs constant refuelling and fixing gets nowhere.
- Name places with [gps=x,y] tags, and use free_space and area to pick them. Keep the base compact enough to walk.
- Keep research going whenever labs and packs allow ("research X").
- Each turn: look as much as you need (a few tool calls), write a short note with anything you want to remember \
(your plan, what failed and why, where things are), then end with give_order or wait. One order per turn; the \
serf works on it until it reports done or failed, and then you get the next turn.

Milestones, for reference: {milestones}
"""

OWN_TOOLS = [
    ("give_order", "Send the serf one order in chat (ends your turn). Phrase it as a player would, with [gps=x,y] "
                   "places. The serf works on it until done or failed.",
     {"type": "object", "properties": {"text": {"type": "string"}, "why": {"type": "string"}}, "required": ["text"]}),
    ("wait", "Let the factory run for some minutes without a new order (ends your turn): research to finish, "
             "packs to accumulate, a build to fill up.",
     {"type": "object", "properties": {"minutes": {"type": "number"}, "why": {"type": "string"}},
      "required": ["minutes"]}),
    ("note", "Write a line in your journal (your memory between turns): the plan, where things are, what failed.",
     {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}),
]


class Strategist:
    def __init__(self, goal: str, look: dict, workdir: Path, model: str = MODEL, effort: str | None = None):
        self.goal, self.look, self.workdir, self.model, self.effort = goal, look, workdir, model, effort
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.journal_path = workdir / "journal.jsonl"
        self.log_path = workdir / "strategist.jsonl"
        self.usd = 0.0
        self.turns = 0

    def journal(self, n: int = 40) -> list[str]:
        if not self.journal_path.exists():
            return []
        lines = [json.loads(x) for x in self.journal_path.read_text().splitlines() if x.strip()]
        return [f"[{x['when']}] {x['text']}" for x in lines[-n:]]

    def _log(self, rec: dict) -> None:
        with open(self.log_path, "a") as f:
            f.write(json.dumps({"t": time.time(), **rec}, default=str) + "\n")

    async def decide(self, report: str, when: str) -> dict:
        """One turn: returns {"order": text} or {"wait": minutes} (and logs the turn)."""
        from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock,
                                      create_sdk_mcp_server, query, tool)
        result: dict = {}
        schemas = {n: (d, s) for n, d, s in TOOLS if n in LOOK_TOOLS}

        def make(n):
            async def handler(args):
                t0 = time.time()
                try:
                    if n == "give_order":
                        result["order"], result["why"] = str(args.get("text", "")).strip(), args.get("why", "")
                        out = "sent; your turn ends here"
                    elif n == "wait":
                        result["wait"], result["why"] = float(args.get("minutes", 5)), args.get("why", "")
                        out = "ok; your turn ends here"
                    elif n == "note":
                        with open(self.journal_path, "a") as f:
                            f.write(json.dumps({"when": when, "text": str(args.get("text", ""))[:1000]}) + "\n")
                        out = "noted"
                    else:
                        out = await self.look[n](args)
                except Exception as e:  # noqa: BLE001
                    out = f"error: {e!r}"
                self._log({"kind": "tool", "tool": n, "args": args, "out": str(out)[:3000],
                           "secs": round(time.time() - t0, 2)})
                return {"content": [{"type": "text", "text": str(out)}]}
            return handler

        sdk_tools = [tool(n, d, s)(make(n)) for n, (d, s) in schemas.items()]
        sdk_tools += [tool(n, d, s)(make(n)) for n, d, s in OWN_TOOLS]
        server = create_sdk_mcp_server("world", tools=sdk_tools)
        system = SYSTEM.format(goal=self.goal, milestones="; ".join(f"{lv} {nm}" for lv, nm, _ in MILESTONES))
        kw = dict(system_prompt=system, mcp_servers={"world": server}, tools=[],
                  allowed_tools=[f"mcp__world__{t.name}" for t in sdk_tools], setting_sources=[], model=self.model,
                  cwd=str(self.workdir), max_turns=24)
        if self.effort:
            kw["effort"] = self.effort
        prompt = (f"Your journal so far:\n" + ("\n".join(self.journal()) or "(empty)") + "\n\n" + report +
                  "\n\nYour turn: look as needed, note what to remember, then give_order or wait.")
        t0 = time.time()
        text = ""
        async for m in query(prompt=prompt, options=ClaudeAgentOptions(**kw)):
            if isinstance(m, AssistantMessage):
                text += "".join(b.text for b in m.content if isinstance(b, TextBlock))
            elif isinstance(m, ResultMessage):
                self.usd += float(m.total_cost_usd or 0)
        self.turns += 1
        self._log({"kind": "turn", "secs": round(time.time() - t0, 1), "result": result, "text": text[-2000:],
                   "usd_total": round(self.usd, 3)})
        if not result:
            result = {"wait": 2.0, "why": "the turn ended without an order"}
        return result
