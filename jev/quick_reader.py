"""The quick reader: the small yes/no and pick-one questions code asks about an order or a moment of play ("is this
a copy of the last build?", "which product does this row make?"), answered by Claude Sonnet through the Claude Agent
SDK on the player's own Claude login (the one the planner uses). ask(state, questions) -> {question id: Answer}; the
gates in code read the answers' probabilities.

It took the place of Jev (TypeSafe's model, which needed its own API key) on 2026-11-01, answering the same questions,
so the actor still calls it `self.jev`. The model can be changed with SERF_QUICK_MODEL.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

MODEL = os.environ.get("SERF_QUICK_MODEL", "claude-sonnet-5-5")
SYSTEM = """You answer structured questions about one moment of a Factorio 2.1 game, for a program that acts on your \
answers at once (a character building, belting, fixing). The input is JSON: "state" (what the program knows, often \
a player's chat message as "order" or "message") and "questions" (id -> question). Each question has "type", \
"instructions" and usually "criteria" (examples or option descriptions).

Answer every question, and reply with only one JSON object mapping each question id to its answer:
- type "noul" (yes/no): {"noul": P}, P = your probability (0 to 1) that the answer is yes, judged by the instructions \
and the yes/no criteria.
- type "choice": {"choice": NAME, "probabilities": {NAME: P, ...}}, NAME one of the option names under "criteria", \
probabilities over those names summing to 1.
- type "score": {"score": X}, X the expected level index (0 = first level).

Be calibrated: 0.5 means you can't tell; near 0 or 1 only when the text is clear. No prose, no code fences."""


# ---------------------------------------------------------------------- question builders
def choice(instructions, options: dict, **extra) -> dict:
    """options: {name: description (str/obj/None)}. At most 255."""
    if len(options) > 255:
        raise ValueError(f"choice has {len(options)} options (max 255)")
    return {"type": "choice", "instructions": instructions, "criteria": options, **extra}


def noul(instructions, true: str | None = None, false: str | None = None) -> dict:
    q = {"type": "noul", "instructions": instructions}
    if true or false:
        q["criteria"] = {"true": true or "yes", "false": false or "no"}
    return q


def score(instructions, levels: list) -> dict:
    """levels: ordered list, lowest first; the answer's score is the expected level index."""
    return {"type": "score", "instructions": instructions, "criteria": list(levels)}


@dataclass
class Answer:
    type: str
    raw: dict

    @property
    def choice(self) -> str | None:
        return self.raw.get("choice")

    @property
    def confidence(self) -> float:
        return float(self.raw.get("confidence") or 0.0)

    @property
    def probs(self) -> dict:
        return self.raw.get("probabilities") or {}

    @property
    def p(self) -> float:
        """Noul probability (yes)."""
        return float(self.raw.get("noul") or 0.0)

    @property
    def score(self) -> float | None:
        return self.raw.get("score")


@dataclass
class Stats:
    calls: int = 0
    input_tokens: int = 0
    errors: int = 0
    ms_total: float = 0.0
    usd: float = 0.0
    by_kind: dict = field(default_factory=dict)

    @property
    def cost(self) -> float:
        return self.usd

    def as_dict(self) -> dict:
        return {"calls": self.calls, "input_tokens": self.input_tokens, "errors": self.errors,
                "cost_usd": round(self.cost, 6), "ms_mean": round(self.ms_total / self.calls, 1) if self.calls else None,
                "by_kind": self.by_kind}


class ReaderError(Exception):
    pass


class QuickReader:
    def __init__(self, log_path: Path | None = None, model: str = MODEL, concurrency: int = 6, timeout: float = 90):
        self.model, self.log_path, self.timeout = model, log_path, timeout
        self.stats = Stats()
        self._sem = asyncio.Semaphore(concurrency)

    async def close(self) -> None:
        pass

    async def _query(self, prompt: str) -> tuple[str, dict, float]:
        from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, query
        opts = ClaudeAgentOptions(system_prompt=SYSTEM, tools=[], allowed_tools=[], setting_sources=[],
                                  model=self.model, max_turns=1)
        text, usage, usd = "", {}, 0.0
        async for m in query(prompt=prompt, options=opts):
            if isinstance(m, AssistantMessage):
                text += "".join(b.text for b in m.content if isinstance(b, TextBlock))
            elif isinstance(m, ResultMessage):
                usage, usd = m.usage or {}, float(m.total_cost_usd or 0)
        return text, usage, usd

    async def ask(self, state, questions: dict, kind: str = "misc", meta: dict | None = None,
                  long_context: bool = False) -> dict[str, Answer]:
        prompt = json.dumps({"state": state, "questions": questions}, default=str)
        t0 = time.time()
        err, out, usage, usd, text = None, None, {}, 0.0, ""
        async with self._sem:
            for attempt in range(3):
                try:
                    text, usage, usd = await asyncio.wait_for(self._query(prompt), self.timeout)
                    i = text.find("{")
                    out = json.JSONDecoder().raw_decode(text[i:])[0] if i >= 0 else None  # (first object only)
                    if isinstance(out, dict):
                        break
                    err = f"no JSON in reply: {text[:200]!r}"
                except Exception as e:  # noqa: BLE001
                    err = repr(e)
                await asyncio.sleep(1 + attempt)
        ms = (time.time() - t0) * 1000
        self.stats.calls += 1
        self.stats.ms_total += ms
        self.stats.usd += usd
        tokens = int((usage or {}).get("input_tokens") or 0) + int((usage or {}).get("cache_read_input_tokens") or 0)
        self.stats.input_tokens += tokens
        k = self.stats.by_kind.setdefault(kind, {"calls": 0, "tokens": 0})
        k["calls"] += 1
        k["tokens"] += tokens
        if not isinstance(out, dict):
            self.stats.errors += 1
            self._log({"t": t0, "kind": kind, "ms": round(ms), "error": err, "state": state, "questions": questions,
                       "meta": meta, "reader": self.model})
            raise ReaderError(err or "no answer")
        answers = {}
        for qid, q in questions.items():
            a = out.get(qid) if isinstance(out.get(qid), dict) else {}
            if not a and len(questions) == 1 and any(k in out for k in ("noul", "choice", "score")):
                a = out  # one question, answered without its id
            raw = {"type": q.get("type")}
            if q.get("type") == "noul":
                raw["noul"] = min(1.0, max(0.0, float(a.get("noul", 0.5) or 0)))
            elif q.get("type") == "choice":
                names = list((q.get("criteria") or {}).keys())
                canon = {n.lower(): n for n in names}  # option names matched regardless of case
                probs = {}
                for n, v in (a.get("probabilities") or {}).items():
                    if str(n).lower() in canon:
                        probs[canon[str(n).lower()]] = float(v)
                if isinstance(a.get("choice"), str) and a["choice"].lower() in canon:
                    a = {**a, "choice": canon[a["choice"].lower()]}
                tot = sum(probs.values())
                probs = {n: v / tot for n, v in probs.items()} if tot > 0 else {}
                pick = a.get("choice") if a.get("choice") in names else (max(probs, key=probs.get) if probs else None)
                if pick and pick not in probs:
                    probs[pick] = 1.0
                raw.update({"choice": pick, "probabilities": probs, "confidence": probs.get(pick, 0.0) if pick else 0.0})
            elif q.get("type") == "score":
                raw["score"] = a.get("score")
            answers[qid] = Answer(raw["type"] or "", raw)
        self._log({"t": t0, "kind": kind, "ms": round(ms), "model": self.model, "tokens": tokens, "usd": usd,
                   "state": state, "questions": questions, "answers": {q: a.raw for q, a in answers.items()},
                   "reply": text[:2000], "meta": meta})
        return answers

    def _log(self, rec: dict) -> None:
        if not self.log_path:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, "a") as f:
            f.write(json.dumps(rec, default=str) + "\n")


def reader(log_path: Path | None = None) -> QuickReader:
    return QuickReader(log_path=log_path)
