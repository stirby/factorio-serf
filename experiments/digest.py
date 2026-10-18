#!/usr/bin/env python3
"""Readable digest of one benchmark run: scores, what agents said, tool usage, failures, time split.

    .venv/bin/python experiments/digest.py <run_id or path> [--chat N]
"""
from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path

RUNS = Path(__file__).resolve().parent / "runs"
NEW_TOOLS = ("work", "consult", "mark", "marks", "zone", "roadmap", "plan_ghosts")
NEW_OPS = ("blueprint", "build_ghosts", "connect", "loot")


def load(run: str) -> tuple[Path, dict]:
    d = Path(run) if Path(run).exists() else RUNS / run
    res = json.loads((d / "result.json").read_text()) if (d / "result.json").exists() else {}
    return d, res


def time_split(rows: list[dict], span: float) -> str:
    """Where an agent's wall time went: inside wait, inside act (character working), other tools, model thinking
    between tool calls, and outside turns."""
    buckets = collections.Counter()
    pend, last_res = None, None
    for r in rows:
        if r["kind"] == "tool":
            if last_res is not None:
                buckets["model"] += r["t"] - last_res
            pend = (r["name"] if r["name"] in ("wait", "act", "consult") else "other tools", r["t"])
        elif r["kind"] == "result" and pend:
            buckets[pend[0]] += r["t"] - pend[1]
            last_res, pend = r["t"], None
        elif r["kind"] in ("turn", "prompt"):
            last_res = None
    buckets["between turns"] = max(span - sum(buckets.values()), 0)
    return ", ".join(f"{k} {v / 60:.1f}m ({100 * v / max(span, 1):.0f}%)" for k, v in buckets.most_common() if v >= 1)


def digest(run: str, chat_n: int = 14) -> str:
    d, res = load(run)
    out = [f"# {d.name}"]
    if res:
        out.append(f"score {res.get('score')} success {res.get('success')} elapsed {res.get('elapsed_s')}s "
                   f"cost ~${res.get('cost_usd')}")
        checks = res.get("checks") or {}
        out.append("checks: " + ", ".join(f"{k}={v[0] if isinstance(v, list) else v}"
                                          + (f"/{v[1]}" if isinstance(v, list) and v[1] is not None else "")
                                          for k, v in checks.items()))
    for t in sorted((d / "state" / "agents").glob("*/transcript.jsonl")):
        name = t.parent.name
        rows = [json.loads(l) for l in t.read_text().splitlines() if l.strip()]
        if not rows:
            continue
        tools = collections.Counter(r["name"] for r in rows if r["kind"] == "tool")
        ops = collections.Counter()
        said, fails, consults = [], collections.Counter(), []
        for r in rows:
            if r["kind"] == "tool" and r["name"] == "act":
                for a in r["args"].get("actions") or []:
                    if isinstance(a, dict):
                        ops[a.get("op")] += 1
            if r["kind"] == "tool" and r["name"] == "say":
                said.append(r["args"].get("text", ""))
            if r["kind"] == "tool" and r["name"] == "consult":
                consults.append(r["args"].get("question", "")[:120])
            if r["kind"] == "result":
                for line in r["out"].splitlines():
                    m = re.match(r"#\d+ (\w+): FAILED (.*)", line)
                    if m and "skipped" not in m.group(2):
                        fails[(m.group(1), re.sub(r"-?\d+(\.\d+)?", "N", m.group(2))[:80])] += 1
        turns = [r for r in rows if r["kind"] == "turn"]
        span = rows[-1]["t"] - rows[0]["t"]
        out.append(f"\n## {name}: {span / 60:.1f} min, {len(turns)} turns, {sum(tools.values())} tool calls")
        out.append("time: " + time_split(rows, span))
        out.append("tools: " + ", ".join(f"{k}{'*' if k in NEW_TOOLS else ''}={v}" for k, v in tools.most_common()))
        out.append("act ops: " + ", ".join(f"{k}{'*' if k in NEW_OPS else ''}={v}" for k, v in ops.most_common()))
        if consults:
            out.append("consulted: " + " | ".join(consults))
        if fails:
            out.append("failures: " + "; ".join(f"{k[0]}: {k[1]} x{v}" for k, v in fails.most_common(6)))
        for s in said[-chat_n:]:
            out.append(f"  > {s[:220]}")
    beh = res.get("behavior") if res else None
    if beh:
        out.append("\nbehavior: " + json.dumps(beh)[:900])
    return "\n".join(out)


if __name__ == "__main__":
    n = int(sys.argv[sys.argv.index("--chat") + 1]) if "--chat" in sys.argv else 14
    print(digest(sys.argv[1], n))
