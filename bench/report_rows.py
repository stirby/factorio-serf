#!/usr/bin/env python3
"""HTML table rows for the progress report: serf baseline vs Jev runs whose run_id matches any of the given patterns.
    .venv/bin/python bench/report_rows.py loop1-c2 loop1-c3 tbmroute3 sweepfix2 > rows.html"""
import glob, json, re, statistics as st, sys
from collections import defaultdict
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
SERF = Path.home() / "dev/factorio-slave/experiments/nights"
SERFBASE = ROOT / "bench" / "serfbase"  # the frozen serf's results, copied here to compare


def serf():
    out = defaultdict(lambda: {"n": 0, "ok": 0, "min": [], "cost": []})
    for f in glob.glob(str(SERF / "*/runs.jsonl")):
        for l in open(f):
            if not l.strip():
                continue
            r = json.loads(l)
            b = out[r["scenario"]]
            b["n"] += 1
            b["ok"] += bool(r.get("success"))
            if r.get("success"):
                b["min"].append(r.get("minutes"))
            b["cost"].append(r.get("cost") or 0)
    # crew-era runs of the long single-goal scenarios (before the nights), from the serf's results log
    for l in open(Path.home() / "dev/factorio-slave/experiments/results.jsonl"):
        try:
            r = json.loads(l)
        except json.JSONDecodeError:
            continue
        sc = r.get("scenario") or ""
        if r.get("dry") or not sc.startswith(("s1", "s2", "s3", "s4", "s5")):
            continue
        b = out[sc]
        b["n"] += 1
        b["ok"] += bool(r.get("success"))
        if r.get("success"):
            b["min"].append(round((r.get("elapsed_s") or 0) / 60, 1))
        b["cost"].append(r.get("cost_usd") or 0)
    for f in list(SERFBASE.glob("*.log")) + list(SERFBASE.with_name("serfbase2").glob("*.log")):
        m = [l for l in f.read_text().splitlines() if l.startswith('{"run_id"')]
        if not m:
            continue
        r = json.loads(m[-1])
        b = out[f.stem]
        b["n"] += 1
        b["ok"] += bool(r.get("success"))
        if r.get("success"):
            b["min"].append(round(r["elapsed_s"] / 60, 1))
        b["cost"].append(r.get("cost_usd") or 0)
    return out


def jev(pats):
    out = defaultdict(list)
    for f in glob.glob(str(ROOT / "bench/runs/*/result.json")):
        rid = Path(f).parent.name
        if not any(p in rid for p in pats):
            continue
        r = json.loads(Path(f).read_text())
        secs = None
        ap = Path(f).parent / "actor.jsonl"
        if ap.exists():
            ends = [json.loads(l) for l in ap.read_text().splitlines() if '"order_end"' in l]
            done = [e for e in ends if e.get("status") == "done"]
            secs = done[0]["secs"] if done else None
        out[r["scenario"]].append({"ok": r.get("success"), "min": r.get("elapsed_s", 0) / 60, "cost": r.get("cost_usd") or 0,
                                   "secs": secs, "think": (r.get("thinker") or {}).get("turns", 0)})
    return out


def rng(xs, fmt="{:.1f}"):
    xs = [x for x in xs if x is not None]
    if not xs:
        return "–"
    lo, hi = min(xs), max(xs)
    return fmt.format(lo) if abs(hi - lo) < 1e-9 else f"{fmt.format(lo)}–{fmt.format(hi)}"


def secs_txt(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return "–"
    m = st.median(xs)
    return f"{m:.0f} s" if m < 120 else f"{m / 60:.1f} min"


GROUPS = [("Behaviour and new tests", ("t-change", "t-maintain", "t-session", "t-quick-mix", "t-upgrade")),
          ("Simple tests (t-*)", "t-"), ("Lab tests (x-*)", "x-"), ("Transport Belt Madness", "tbm-"),
          ("Long scenarios", ("s1", "s2", "s3", "s4", "s5", "d2", "f1"))]


def main():
    # --alone=tag1,tag2: no-Opus runs (--no-think); a test any of them met gets a "no Opus needed" chip
    alone_tags = [a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--alone=")]
    alone_tags = [t for a in alone_tags for t in a.split(",") if t]
    alone = jev(alone_tags) if alone_tags else {}
    sb, jr = serf(), jev([a for a in sys.argv[1:] if not a.startswith("--")])
    rows = []
    shown = set()
    for title, pre in GROUPS:
        names = sorted(n for n in jr if n.startswith(pre) and n not in shown)
        shown |= set(names)
        if not names:
            continue
        rows.append(f'<tr class="group"><td colspan="9">{title}</td></tr>')
        for n in names:
            s, j = sb.get(n), jr[n]
            ok = sum(1 for x in j if x["ok"])
            serf_cells = (f'<td class="n">{s["ok"]}/{s["n"]}</td><td class="n">{rng(s["min"])}</td>'
                          f'<td class="n">{st.mean(s["cost"]):.2f}</td>') if s and s["n"] else \
                '<td class="n">–</td><td class="n">–</td><td class="n">–</td>'
            notes = []
            if all(x["think"] == 0 for x in j) or any(x["ok"] for x in alone.get(n, [])):
                notes.append('<span class="chip win">no Opus needed</span>')
            if s and s["n"] and s["ok"] < s["n"] and ok == len(j):
                notes.append('<span class="chip win">serf missed</span>')
            if ok < len(j):
                notes.append('<span class="chip lose">missed</span>')
            cls = "ok" if ok == len(j) else "no"
            rows.append(f'<tr><td class="name">{n}</td>{serf_cells}<td class="n {cls}">{ok}/{len(j)}</td>'
                        f'<td class="n">{rng([x["min"] for x in j if x["ok"]])}</td><td class="n">{secs_txt([x["secs"] for x in j if x["ok"]])}</td>'
                        f'<td class="n">{st.mean([x["cost"] for x in j]):.2f}</td><td>{" ".join(notes)}</td></tr>')
    print("\n".join(rows))
    tot = sum(len(v) for v in jr.values())
    met = sum(1 for v in jr.values() for x in v if x["ok"])
    print(f"<!-- {met}/{tot} runs, {len(jr)} tests, mean ${st.mean([x['cost'] for v in jr.values() for x in v]):.3f} -->")


if __name__ == "__main__":
    main()
