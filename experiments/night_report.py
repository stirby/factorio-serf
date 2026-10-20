#!/usr/bin/env python3
"""The morning page for one night of the overnight loop: computed tables first, then the agent layer, friction,
debriefs, and the written review (nights/<night>/review.md: major challenges + indexed core proposals).

    .venv/bin/python experiments/night_report.py NIGHT OUT.html
"""
from __future__ import annotations

import html
import json
import statistics
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
E = html.escape


def load(night: Path) -> tuple[list[dict], list[dict]]:
    runs = [json.loads(l) for l in (night / "runs.jsonl").read_text().splitlines() if l.strip()] \
        if (night / "runs.jsonl").exists() else []
    ev = [json.loads(l) for l in (night / "events.jsonl").read_text().splitlines() if l.strip()] \
        if (night / "events.jsonl").exists() else []
    return runs, ev


def summarize(rs: list[dict]) -> dict:
    n = len(rs)
    met = sum(m.get("met") or 0 for m in rs)
    obj = sum(m.get("objectives") or 0 for m in rs)
    cost = sum(m.get("cost") or 0 for m in rs)
    return {"runs": n, "pass": sum(1 for m in rs if m.get("success")) / n if n else 0,
            "met": met, "objectives": obj, "cost": cost, "cost_per_met": cost / met if met else None,
            "waste": statistics.mean([m["waste"] for m in rs if "waste" in m]) if rs else 0,
            "minutes": statistics.mean([m.get("minutes") or 0 for m in rs]) if rs else 0}


def jaccard_spread(sets: list[set]) -> float:
    """Mean pairwise Jaccard distance: 0 = every repeat played the same way, 1 = nothing in common."""
    pairs = list(combinations(sets, 2))
    if not pairs:
        return 0.0
    return statistics.mean(1 - len(a & b) / len(a | b) if a | b else 0 for a, b in pairs)


def table(head: list[str], rows: list[list]) -> str:
    h = "".join(f"<th>{E(str(x))}</th>" for x in head)
    b = "".join("<tr>" + "".join(f"<td>{x if isinstance(x, str) and x.startswith('<') else E(str(x))}</td>"
                                 for x in r) + "</tr>" for r in rows)
    return f"<div class=scroll><table><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table></div>"


def pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def money(x) -> str:
    return "-" if x is None else f"${x:.2f}"


def md(text: str) -> str:
    """Just enough Markdown for review.md: headings, numbered/bulleted lists, bold, code, paragraphs."""
    import re
    out, lst, rows = [], None, []
    for line in text.splitlines() + [""]:
        s = line.rstrip()
        if s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if not all(re.fullmatch(r":?-+:?", c) for c in cells):
                rows.append(cells)
            continue
        if rows:
            out.append(f"<div class=scroll><table><tr>{''.join(f'<th>{inline(c)}</th>' for c in rows[0])}</tr>"
                       + "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in rows[1:])
                       + "</table></div>")
            rows = []
        m = re.match(r"^(#{1,3}) (.*)", s)
        item = re.match(r"^\s*(\d+\.|[-*]) (.*)", s)
        if lst and not item:
            out.append(f"</{lst}>")
            lst = None
        if m:
            out.append(f"<h{len(m.group(1)) + 1}>{inline(m.group(2))}</h{len(m.group(1)) + 1}>")
        elif item:
            kind = "ol" if item.group(1)[0].isdigit() else "ul"
            if lst != kind:
                if lst:
                    out.append(f"</{lst}>")
                out.append(f"<{kind}>")
                lst = kind
            out.append(f"<li>{inline(item.group(2))}</li>")
        elif s:
            out.append(f"<p>{inline(s)}</p>")
    if lst:
        out.append(f"</{lst}>")
    return "\n".join(out)


def inline(s: str) -> str:
    import re
    s = E(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    return re.sub(r"`(.+?)`", r"<code>\1</code>", s)


def build(night: Path) -> str:
    runs, ev = load(night)
    phases = defaultdict(list)
    for m in runs:
        phases[m.get("phase") or "?"].append(m)
    parts = []

    review = night / "review.md"
    if review.exists():
        parts.append(f"<section>{md(review.read_text())}</section>")
    # The serfs' own requests (debriefs and friction, clustered and sorted each morning).
    requests = night / "requests.md"
    if requests.exists():
        parts.append(f"<section>{md(requests.read_text())}</section>")

    # Headline: holdout before vs after (only the agent layer changes overnight), then every phase.
    rows = []
    for ph, rs in phases.items():
        s = summarize(rs)
        rows.append([ph, s["runs"], pct(s["pass"]), f"{s['met']}/{s['objectives']}", money(s["cost"]),
                     money(s["cost_per_met"]), f"{s['waste']:.2f}", f"{s['minutes']:.1f}"])
    parts.append("<section><h2>Results by phase</h2><p class=note>Holdout before = fresh empty library; holdout "
                 "after = the night's library, read-only. The core doesn't change overnight, so their difference is "
                 "what the serfs' own layer bought. Waste = (failed + self-undone + repeated-look calls) / calls."
                 "</p>" + table(["phase", "runs", "pass", "objectives met", "cost", "cost / objective", "waste",
                                 "avg min"], rows) + "</section>")

    # Where the time went, over every run.
    lost = Counter()
    for m in runs:
        for k, v in (m.get("lost_min") or {}).items():
            lost[k] += v
    total = sum(lost.values()) or 1
    parts.append("<section><h2>Where the time went</h2>" + table(
        ["bucket", "minutes", "share"], [[k, f"{v:.1f}", pct(v / total)] for k, v in lost.most_common()])
        + "</section>")

    # Per test: outcomes, time, and how much distinct data it produced.
    by_s = defaultdict(list)
    for m in runs:
        by_s[m.get("scenario") or "?"].append(m)
    all_fail = Counter()
    for m in runs:
        for k in m.get("failure_kinds") or []:
            all_fail[k] += 1
    rows = []
    for sc, rs in sorted(by_s.items()):
        s = summarize(rs)
        fk = set().union(*[set(m.get("failure_kinds") or []) for m in rs])
        only = [k for k in fk if all_fail[k] == sum(1 for m in rs if k in (m.get("failure_kinds") or []))]
        ops = [set(m.get("ops_used") or []) for m in rs]
        mins = [m.get("minutes") or 0 for m in rs]
        rows.append([sc, s["runs"], pct(s["pass"]), money(s["cost_per_met"]), f"{s['waste']:.2f}",
                     f"{statistics.mean(mins):.1f} ± {statistics.pstdev(mins):.1f}", len(fk), len(only),
                     len(set().union(*ops)), f"{jaccard_spread(ops):.2f}"])
    rows.sort(key=lambda r: -(r[6] + r[7] + r[8] / 5 + 5 * float(r[9])))
    parts.append("<section><h2>Tests: outcomes and data diversity</h2><p class=note>Distinct failures = different "
                 "failure kinds seen; only here = kinds no other test produced; spread = how differently repeats "
                 "played (mean pairwise Jaccard distance of tools/ops used). Sorted by diversity.</p>" + table(
        ["test", "runs", "pass", "cost / obj", "waste", "minutes", "distinct failures", "only here", "tools/ops",
         "spread"], rows) + "</section>")

    # Trend per train cycle.
    cyc = defaultdict(list)
    for m in runs:
        if m.get("cycle"):
            cyc[m["cycle"]].append(m)
    if cyc:
        rows = []
        for c in sorted(cyc):
            s = summarize(cyc[c])
            rows.append([c, s["runs"], pct(s["pass"]), money(s["cost_per_met"]), f"{s['waste']:.2f}"])
        parts.append("<section><h2>Train cycles</h2>" + table(["cycle", "runs", "pass", "cost / obj", "waste"], rows)
                     + "</section>")

    parts.append("<section><h2>Top failures (all runs)</h2>" + table(
        ["runs hit", "failure"], [[n, k] for k, n in all_fail.most_common(25)]) + "</section>")

    # The agent layer: what the serfs built for themselves.
    lib = night / "library"
    sk_rows = []
    usage = defaultdict(lambda: [0, 0])
    up = lib / "skills" / "usage.jsonl"
    if up.exists():
        for l in up.read_text().splitlines():
            u = json.loads(l)
            usage[u["name"]][0] += 1
            usage[u["name"]][1] += bool(u.get("ok"))
    for p in sorted((lib / "skills").glob("*.json")) if (lib / "skills").exists() else []:
        sk = json.loads(p.read_text())
        u = usage[sk["name"]]
        body = sk.get("code") or sk.get("text") or ""
        sk_rows.append([sk["name"], sk["kind"], sk["doc"], sk.get("version", 1), u[0], f"{u[1]}/{u[0]}",
                        f"<details><summary>{len(body)} chars</summary><pre>{E(body)}</pre></details>"])
    lessons = (lib / "lessons" / "lessons.md").read_text() if (lib / "lessons" / "lessons.md").exists() else ""
    designs = sorted(p.stem for p in (lib / "designs").glob("*")) if (lib / "designs").exists() else []
    parts.append("<section><h2>What the serfs built</h2>"
                 + (table(["name", "kind", "doc", "version", "uses", "ok", "body"], sk_rows) if sk_rows
                    else "<p>No scripts or playbooks.</p>")
                 + f"<h3>Lessons</h3><pre>{E(lessons) or '(none)'}</pre>"
                 + f"<h3>Designs</h3><p>{E(', '.join(designs)) or '(none)'}</p></section>")

    fr = lib / "friction.jsonl"
    if fr.exists():
        notes = [json.loads(l) for l in fr.read_text().splitlines() if l.strip()]
        parts.append(f"<section><h2>Friction notes ({len(notes)})</h2><ul>" + "".join(
            f"<li>{E(n['note'])} <span class=note>({E(n.get('run', '')[-40:])})</span></li>" for n in notes)
            + "</ul></section>")

    deb = [(m.get("run", ""), m.get("debrief")) for m in runs if m.get("debrief")]
    if deb:
        parts.append(f"<section><h2>Debriefs ({len(deb)})</h2>" + "".join(
            f"<details><summary>{E(r)}</summary><blockquote>{'<br>'.join(E(x) for x in d)}</blockquote></details>"
            for r, d in deb) + "</section>")

    pauses = [e for e in ev if e["event"] in ("usage_limit_pause", "budget_stop")]
    spent = sum(m.get("cost") or 0 for m in runs)
    head = (f"<p class=note>{len(runs)} runs, API-equivalent {money(spent)} (subscription), "
            f"{len(pauses)} usage-limit pauses/stops.</p>")
    return PAGE.replace("{TITLE}", f"Night {E(night.name)}").replace("{BODY}", head + "\n".join(parts))


PAGE = """<!doctype html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>{TITLE}</title><style>
:root{--bg:#fbfaf7;--fg:#1d1d1b;--mute:#6b6a65;--line:#e4e1d8;--card:#fff;--accent:#b4572e}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#171716;--fg:#ecebe6;--mute:#a09e96;--line:#34332f;--card:#1f1f1d;--accent:#e08a5f}}
:root[data-theme="dark"]{--bg:#171716;--fg:#ecebe6;--mute:#a09e96;--line:#34332f;--card:#1f1f1d;--accent:#e08a5f}
body{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;margin:0;padding:24px 16px}
main{max-width:1100px;margin:0 auto}h1{font-size:26px;margin:0 0 4px}h2{font-size:19px;margin:28px 0 8px;color:var(--accent)}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:14px 0}
.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13.5px}
th,td{border-bottom:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}th{color:var(--mute);font-weight:600}
.note{color:var(--mute);font-size:13px}pre{white-space:pre-wrap;font-size:12.5px;background:var(--bg);padding:8px;border-radius:6px}
code{font-size:13px}blockquote{margin:6px 0;padding-left:10px;border-left:3px solid var(--line)}
</style></head><body><main><h1>{TITLE}</h1>{BODY}</main></body></html>"""


if __name__ == "__main__":
    night = Path(sys.argv[1])
    if not night.is_absolute() and not night.exists():
        night = ROOT / "experiments" / "nights" / sys.argv[1]
    Path(sys.argv[2]).write_text(build(night))
    print(f"wrote {sys.argv[2]}")
