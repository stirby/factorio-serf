"""Minimal async client for TypeSafe's System One API (Jev), with a decision log.

Every call is appended to a JSONL log (state, questions, answers, latency, tokens) so the encoding lab can replay
and score decisions later. The key comes from TYPESAFE_API_KEY or ~/dev/jev.env (just the key, or KEY=value).
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

API = "https://api.typesafe.ai/v1/systemone"
PRICE_PER_MTOK = 0.042  # input only; output is free
DEFAULT_MODEL = os.environ.get("JEV_MODEL", "jev-latest")


def load_key() -> str:
    k = os.environ.get("TYPESAFE_API_KEY")
    if k:
        return k.strip()
    raw = Path(os.path.expanduser("~/dev/jev.env")).read_text().strip()
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line and not line.startswith("ts"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
        return line
    raise RuntimeError("no TypeSafe key in ~/dev/jev.env")


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
    by_kind: dict = field(default_factory=dict)

    @property
    def cost(self) -> float:
        return self.input_tokens / 1e6 * PRICE_PER_MTOK

    def as_dict(self) -> dict:
        return {"calls": self.calls, "input_tokens": self.input_tokens, "errors": self.errors,
                "cost_usd": round(self.cost, 6), "ms_mean": round(self.ms_total / self.calls, 1) if self.calls else None,
                "by_kind": self.by_kind}


class Jev:
    def __init__(self, log_path: Path | None = None, model: str = DEFAULT_MODEL, timeout: float = 10.0):
        self.key = load_key()
        self.model = model
        self.log_path = log_path
        self.stats = Stats()
        self._client = httpx.AsyncClient(timeout=timeout, headers={"Authorization": f"Bearer {self.key}",
                                                                   "Content-Type": "application/json"})

    async def close(self) -> None:
        await self._client.aclose()

    async def ask(self, state, questions: dict, kind: str = "misc", meta: dict | None = None,
                  long_context: bool = False) -> dict[str, Answer]:
        """One request: every question about one state. Returns {question id: Answer}."""
        body = {"model": self.model, "state": state, "questions": questions}
        headers = {"TypeSafe-Danger-Zone-Long-Context": "true"} if long_context else None
        t0 = time.time()
        err, out = None, None
        for attempt in range(4):
            try:
                r = await self._client.post(API, json=body, headers=headers)
                if r.status_code in (429, 529, 500, 502, 503, 504):
                    await asyncio.sleep(float(r.headers.get("retry-after") or 0.5 * 2 ** attempt))
                    continue
                if r.status_code != 200:
                    err = f"HTTP {r.status_code}: {r.text[:400]}"
                    break
                out = r.json()
                break
            except (httpx.TransportError, json.JSONDecodeError) as e:
                err = repr(e)
                await asyncio.sleep(0.5 * 2 ** attempt)
        ms = (time.time() - t0) * 1000
        self.stats.calls += 1
        self.stats.ms_total += ms
        k = self.stats.by_kind.setdefault(kind, {"calls": 0, "tokens": 0})
        k["calls"] += 1
        if out is None:
            self.stats.errors += 1
            self._log({"t": t0, "kind": kind, "ms": round(ms), "error": err or "retries exhausted", "state": state,
                       "questions": questions, "meta": meta})
            raise JevError(err or "retries exhausted")
        tokens = int((out.get("usage") or {}).get("input_tokens") or 0)
        self.stats.input_tokens += tokens
        k["tokens"] += tokens
        answers = {qid: Answer(a.get("type", ""), a) for qid, a in (out.get("answers") or {}).items()}
        self._log({"t": t0, "kind": kind, "ms": round(ms), "model": out.get("model"), "tokens": tokens,
                   "state": state, "questions": questions, "answers": out.get("answers"), "meta": meta})
        return answers

    def _log(self, rec: dict) -> None:
        if not self.log_path:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, "a") as f:
            f.write(json.dumps(rec, default=str) + "\n")


class JevError(Exception):
    pass


def reader(log_path: Path | None = None):
    """Jev, or Sonnet answering the same questions when JEV_READER=sonnet (jev/sonnet.py), to compare readers."""
    if os.environ.get("JEV_READER") == "sonnet":
        from .sonnet import SonnetJev
        return SonnetJev(log_path=log_path)
    if os.environ.get("JEV_READER") == "hybrid":  # Jev, with Sonnet asked again where Jev is unsure on build readings
        from .sonnet import HybridReader
        return HybridReader(log_path=log_path)
    return Jev(log_path=log_path)
