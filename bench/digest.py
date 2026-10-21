#!/usr/bin/env python3
"""Daily-review digest for a set of runs (a loop tag, or any run-id substrings): what passed, where the time went,
what Jev decided and how sure it was, what the plan checker caught, what Opus wrote for its future self.

    .venv/bin/python bench/digest.py loop1 [more patterns] > digest.md
"""
from __future__ import annotations

import collections
import glob
import json
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def runs(pats):
    for f in sorted(glob.glob(str(ROOT / "bench/runs/*/result.json"))):
        d = Path(f).parent
        if any(p in d.name for p in pats):
            yield d, json.loads(Path(f).read_text())


def main():
    pats = sys.argv[1:] or ["loop1"]
    rs = list(runs(pats))
    out = [f"# Digest: {', '.join(pats)}", ""]
    ok = sum(1 for _, r in rs if r.get("success"))
    cost = sum(r.get("cost_usd") or 0 for _, r in rs)
    out.append(f"{ok}/{len(rs)} runs met, ${cost:.2f} notional (Opus) + Jev "
               f"${sum((r.get('jev') or {}).get('cost_usd', 0) for _, r in rs):.4f}.")
    misses = collections.Counter(r["scenario"] for _, r in rs if not r.get("success"))
    if misses:
        out.append("Missed: " + ", ".join(f"{k} x{n}" for k, n in misses.most_common()))
    # time split per order: waiting for the first plan, building, verifying
    split = collections.defaultdict(list)
    decisions = collections.defaultdict(list)
    low = []
    lint = collections.Counter()
    recov = collections.Counter()
    for d, r in rs:
        p = d / "actor.jsonl"
        if not p.exists():
            continue
        rows = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
        o = next((x for x in rows if x["kind"] == "order"), None)
        e = next((x for x in rows if x["kind"] == "order_end"), None)
        if o and e:
            fp = next((x["t"] for x in rows if x["kind"] == "plan"), None)
            split["order->done s"].append(e["t"] - o["t"])
            if fp:
                split["first plan s"].append(fp - o["t"])
            split["plans"].append(e.get("plans", 0))
        for x in rows:
            if x["kind"] == "lint":
                for pr in x["problems"]:
                    key = next((k for k in ("overlaps", "picks up from", "drops onto", "nothing feeds", "no pole",
                                            "not available", "nothing brings", "should sit", "middle of belt",
                                            "backwards", "no recipe") if k in pr), pr[:40])
                    lint[key] += 1
            if x["kind"] == "recovery":
                recov[x["choice"]] += 1
        jp = d / "jev.jsonl"
        if jp.exists():
            for l in jp.read_text().splitlines():
                j = json.loads(l)
                ans = j.get("answers") or {}
                for qid, a in ans.items():
                    if j["kind"] == "chat" and qid == "playbook" and (ans.get("kind") or {}).get("choice") != "new_job":
                        continue  # the playbook only matters for new jobs
                    c = a.get("confidence") if a.get("type") == "choice" else (
                        abs(a.get("noul", 0.5) - 0.5) * 2 if a.get("type") == "noul" else None)
                    if c is None:
                        continue
                    decisions[f"{j['kind']}.{qid}"].append(c)
                    if c < 0.5 and len(low) < 40:
                        st_ = json.dumps(j.get("state"))[:160]
                        low.append(f"- `{j['kind']}.{qid}` → **{a.get('choice', round(a.get('noul', 0), 2))}** "
                                   f"(conf {c:.2f}) state: {st_}")
    out += ["", "## Time per order", ""]
    for k, v in split.items():
        if v:
            out.append(f"- {k}: median {st.median(v):.0f}, p90 {sorted(v)[int(len(v) * 0.9)]:.0f}, n={len(v)}")
    out += ["", "## Jev decisions (confidence; for nouls, distance from 0.5 doubled)", "",
            "| decision | calls | median conf | share < 0.5 |", "|---|---|---|---|"]
    for k, v in sorted(decisions.items(), key=lambda kv: -len(kv[1])):
        out.append(f"| {k} | {len(v)} | {st.median(v):.2f} | {sum(1 for c in v if c < 0.5) / len(v):.0%} |")
    out += ["", "## Low-confidence decisions to label", ""] + (low or ["(none)"])
    out += ["", "## Recovery choices", "", ", ".join(f"{k} {n}" for k, n in recov.most_common()) or "(none)"]
    out += ["", "## Plan checker caught", "", ", ".join(f"{k} {n}" for k, n in lint.most_common()) or "(nothing)"]
    libs = set()
    for d, r in rs:
        libs.add(str(ROOT / "bench/libraries" / (r.get("tag") or "")))
    for lib in sorted(libs):
        lp = Path(lib) / "lessons.jsonl"
        if lp.exists():
            ls = [json.loads(l)["text"] for l in lp.read_text().splitlines() if l.strip()]
            out += ["", f"## Lessons in {Path(lib).name} ({len(ls)})", ""] + [f"- {t}" for t in ls[-15:]]
    print("\n".join(out))


if __name__ == "__main__":
    main()
