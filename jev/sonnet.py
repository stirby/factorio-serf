"""Sonnet in Jev's place, to compare readers: the same ask(state, questions) -> {question id: Answer}, answered by
Claude Sonnet through the Claude Agent SDK (the subscription the planner uses). Every gate in code stays as it is.

    JEV_READER=sonnet .venv/bin/python bench/run.py ...      # or lab/eval_*.py
"""
from __future__ import annotations

import asyncio
import json
import os
import re
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
        err, out, usage, usd = None, None, {}, 0.0
        async with self._sem:
            for attempt in range(3):
                try:
                    text, usage, usd = await asyncio.wait_for(self._query(prompt), self.timeout)
                    m = re.search(r"\{.*\}", text, re.S)
                    out = json.loads(m.group(0)) if m else None
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
            raw = {"type": q.get("type")}
            if q.get("type") == "noul":
                raw["noul"] = min(1.0, max(0.0, float(a.get("noul", 0.5) or 0)))
            elif q.get("type") == "choice":
                names = list((q.get("criteria") or {}).keys())
                probs = {n: float(v) for n, v in (a.get("probabilities") or {}).items() if n in names}
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
                   "meta": meta})
        return answers

    def _log(self, rec: dict) -> None:
        if not self.log_path:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, "a") as f:
            f.write(json.dumps(rec, default=str) + "\n")
