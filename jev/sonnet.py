"""Sonnet in Jev's place, to compare readers: the same ask(state, questions) -> {question id: Answer}, answered by
Claude Sonnet through the Claude Agent SDK (the subscription the planner uses). Every gate in code stays as it is.

    JEV_READER=sonnet .venv/bin/python bench/run.py ...      # or lab/eval_*.py
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

from .typesafe import Answer, JevError, Stats

MODEL = os.environ.get("JEV_SONNET_MODEL", "claude-sonnet-5-5")
SYSTEM = """You answer structured questions about one moment of a Factorio 2.0 game, for a program that acts on your \
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


class SonnetStats(Stats):
    usd: float = 0.0

    @property
    def cost(self) -> float:
        return self.usd


class SonnetJev:
    def __init__(self, log_path: Path | None = None, model: str = MODEL, concurrency: int = 6, timeout: float = 90):
        self.model, self.log_path, self.timeout = model, log_path, timeout
        self.stats = SonnetStats()
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
            raise JevError(err or "no answer")
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


class HybridReader:
    """Jev first; Sonnet answers again only where Jev is unsure on the readings Sonnet does better (what to build, belt
    jobs, mines). Chat triage and everything else stays Jev's: on the held-out set Jev read the conversation better
    (corrections, questions, stop) and Sonnet read terse build orders better."""
    ESCALATE = {"quickbuild", "quickbelt", "quickmine", "quickcopy"}

    def __init__(self, log_path: Path | None = None):
        from .typesafe import Jev
        self.jev = Jev(log_path=log_path)
        self.sonnet = SonnetJev(log_path=log_path)
        self.escalated = 0

    @property
    def stats(self):
        j, s = self.jev.stats, self.sonnet.stats
        out = Stats(calls=j.calls + s.calls, input_tokens=j.input_tokens + s.input_tokens, errors=j.errors + s.errors,
                    ms_total=j.ms_total + s.ms_total, by_kind={**j.by_kind, **{f"sonnet:{k}": v for k, v in
                                                                               s.by_kind.items()}})
        cost = j.cost + s.cost
        out.as_dict = lambda: {**Stats.as_dict(out), "cost_usd": round(cost, 6), "escalated": self.escalated}
        return out

    async def close(self) -> None:
        await self.jev.close()

    @staticmethod
    def unsure(answers: dict) -> bool:
        for a in answers.values():
            if a.type == "noul" and 0.3 < a.p < 0.7:
                return True
            if a.type == "choice" and (a.confidence < 0.6 or a.choice == "none_of_these"):
                return True
        return False

    async def ask(self, state, questions: dict, kind: str = "misc", meta: dict | None = None,
                  long_context: bool = False) -> dict[str, Answer]:
        a = await self.jev.ask(state, questions, kind=kind, meta=meta, long_context=long_context)
        if kind in self.ESCALATE and self.unsure(a):
            self.escalated += 1
            try:
                return await self.sonnet.ask(state, questions, kind=kind, meta={**(meta or {}), "escalated": True})
            except JevError:
                return a
        return a
