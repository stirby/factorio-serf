#!/usr/bin/env python3
"""Render the overnight review page (hour-by-hour) from what the night already records:
experiments/DECISIONS.md, git commits, experiments/results.jsonl, experiments/log.jsonl, snapshots/manifest.jsonl,
and experiments/findings.md (hand-written headline findings).

    .venv/bin/python experiments/render_page.py OUT.html [--since "2026-10-18 01:10"]
"""
from __future__ import annotations

import html
import json
import re
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXP = ROOT / "experiments"


def jl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def parse_since(argv) -> float:
    if "--since" in argv:
        return time.mktime(time.strptime(argv[argv.index("--since") + 1], "%Y-%m-%d %H:%M"))
    return time.mktime(time.strptime("2026-10-18 01:10", "%Y-%m-%d %H:%M"))


def hour_key(t: float) -> str:
    return time.strftime("%H:00", time.localtime(t))


def collect(since: float) -> dict[str, dict[str, list]]:
    hours: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    day = time.strftime("%Y-%m-%d", time.localtime(since))
    # decisions: "| HH:MM | decision | why |"
    if (EXP / "DECISIONS.md").exists():
        for line in (EXP / "DECISIONS.md").read_text().splitlines():
            m = re.match(r"\| (\d\d):(\d\d) \| (.+?) \| (.+?) \|$", line)
            if m:
                t = time.mktime(time.strptime(f"{day} {m.group(1)}:{m.group(2)}", "%Y-%m-%d %H:%M"))
                if t < since - 3600:  # past midnight
                    t += 86400
                if t >= since:
                    hours[hour_key(t)]["decisions"].append((t, m.group(3), m.group(4)))
    # commits
    try:
        log = subprocess.run(["git", "-C", str(ROOT), "log", f"--since=@{int(since)}", "--format=%ct\t%s"],
                             capture_output=True, text=True, timeout=10).stdout
        for line in log.splitlines():
            ts, subj = line.split("\t", 1)
            hours[hour_key(int(ts))]["commits"].append((int(ts), subj))
    except Exception:
        pass
    # runs
    for r in jl(EXP / "results.jsonl"):
        t = r.get("end_t") or r.get("t") or 0
        if isinstance(t, str):
            try:
                t = time.mktime(time.strptime(t[:19], "%Y-%m-%d %H:%M:%S"))
            except ValueError:
                t = 0
        if t >= since:
            hours[hour_key(t)]["runs"].append((t, r))
    # snapshots
    for s in jl(ROOT / "snapshots" / "manifest.jsonl"):
        try:
            t = time.mktime(time.strptime(s["time"][:16], "%Y-%m-%d %H:%M"))
        except (KeyError, ValueError):
            continue
        if t >= since:
            hours[hour_key(t)]["snapshots"].append((t, s))
    for e in jl(EXP / "log.jsonl"):
        if e.get("kind") == "note" and e.get("t", 0) >= since:
            hours[hour_key(e["t"])]["notes"].append((e["t"], e.get("text", "")))
    return hours


def fmt_scores(r: dict) -> str:
    sc = r.get("scores") or {}
    parts = []
    if isinstance(sc, dict):
        for k, v in sc.items():
            if isinstance(v, dict):
                val, tgt = v.get("value"), v.get("target")
                parts.append(f"{k}: {val}" + (f" / {tgt}" if tgt is not None else ""))
            else:
                parts.append(f"{k}: {v}")
    elif isinstance(sc, list):
        for c in sc:
            parts.append(f"{c.get('name')}: {c.get('value')}" + (f" / {c.get('target')}" if c.get('target') is not None else ""))
    return "; ".join(parts)


def fmt_behavior(r: dict) -> str:
    b = r.get("behavior") or r.get("behavior_summary") or {}
    if not isinstance(b, dict):
        return ""
    keys = [("idle_pct", "char idle"), ("hand_logistics", "hand insert/take"), ("failures", "failures"),
            ("idle_turns", "idle turns"), ("cost", "~$")]
    out = []
    for k, label in keys:
        if k in b:
            v = b[k]
            out.append(f"{label} {v:.0f}%" if k == "idle_pct" and isinstance(v, (int, float)) else f"{label} {v}")
    return ", ".join(out)


def sparkline(tl: list[dict], minutes: float, key: str, ymax: float) -> str:
    """Science/min over the run as a line, with a tick each time a tech finishes."""
    W, H = 300, 56
    pts, ticks, last_techs = [], [], None
    for s in tl:
        v, e = s.get("values") or {}, s.get("elapsed")
        if e is None:
            continue
        x = min(e / 60 / minutes, 1) * W
        if isinstance(v.get(key), (int, float)):
            pts.append(f"{x:.1f},{H - 4 - min(v[key] / ymax, 1) * (H - 8):.1f}")
        t = v.get("techs_researched")
        if isinstance(t, (int, float)):
            if last_techs is not None and t > last_techs:
                ticks.append(x)
            last_techs = t
    tick_svg = "".join(f"<line x1='{x:.1f}' y1='0' x2='{x:.1f}' y2='7' class='tk'/>" for x in ticks)
    return (f"<svg viewBox='0 0 {W} {H}' class='spark' role='img' aria-label='{key} over the run'>"
            f"<line x1='0' y1='{H - 4}' x2='{W}' y2='{H - 4}' class='ax'/>{tick_svg}"
            f"<polyline points='{' '.join(pts)}' class='ln'/></svg>")


def invalid_runs() -> dict[str, str]:
    p = EXP / "invalid_runs.txt"
    out = {}
    for line in (p.read_text().splitlines() if p.exists() else []):
        if line.strip() and not line.startswith("#"):
            rid, _, why = line.partition("  ")
            out[rid.strip()] = why.strip()
    return out


def progress_panel(since: float) -> str:
    """One row per research run since `since`: score, cost, and science/min over time."""
    rows = []
    invalid = invalid_runs()
    for d in sorted((EXP / "runs").glob("*")):
        tlp, rp = d / "timeline.jsonl", d / "result.json"
        if not tlp.exists() or d.name.endswith("-dry"):
            continue
        tl = jl(tlp)
        t0 = tl[0].get("t", 0) if tl else 0
        if t0 < since:
            continue
        res = json.loads(rp.read_text()) if rp.exists() else {}
        vals = [s.get("values") or {} for s in tl]
        key = next((k for k in ("science_consumed_per_min", "blue_per_min_assemblers") if any(k in v for v in vals)), None)
        if not key:
            continue
        scn = json.loads((d / "scenario.json").read_text()) if (d / "scenario.json").exists() else {}
        minutes = float(res.get("minutes_planned") or scn.get("minutes") or 60)
        techs = [v["techs_researched"] for v in vals if isinstance(v.get("techs_researched"), (int, float))]
        used = [v["science_packs_used"] for v in vals if isinstance(v.get("science_packs_used"), (int, float))]
        peak = max((v.get(key) or 0 for v in vals), default=0)
        arch = d / "state" / "agents" / "architect" / "transcript.jsonl"
        arch_cost = sum(r.get("cost") or 0 for r in jl(arch) if r.get("kind") == "turn") if arch.exists() else 0
        cost = (res.get("cost_usd") or 0) + arch_cost
        status = (f"score {res.get('score')} · ${cost:.0f}" + (f" (architect ${arch_cost:.0f})" if arch_cost else "")
                  if res else (f"stopped at {tl[-1].get('elapsed', 0) / 60:.0f} min (no result)"
                               if time.time() - (tl[-1].get("t") or 0) > 900 else
                               f"running · {tl[-1].get('elapsed', 0) / 60:.0f} min in"))
        if d.name in invalid:
            status = "INVALID: " + invalid[d.name]
        hit6 = next((s.get("elapsed") for s, v in zip(tl, vals) if techs and isinstance(v.get("techs_researched"), (int, float))
                     and v["techs_researched"] - techs[0] >= 6), None)
        facts = [(f"+{techs[-1] - techs[0]:.0f} techs" + (f" (6th at {hit6 / 60:.0f} min)" if hit6 else "")) if len(techs) > 1 else "",
                 f"{used[-1] - used[0]:.0f} packs used" if len(used) > 1 else "",
                 f"peak {peak:.0f}/min"]
        name = d.name[16:]  # drop the timestamp
        rows.append(f"<div class='prow'><div><div><b>{html.escape(name)}</b></div><div class='n'>"
                    f"{html.escape(d.name[9:11] + ':' + d.name[11:13])} · {html.escape(status)} · "
                    f"{html.escape(' · '.join(f for f in facts if f))}</div></div>"
                    f"{sparkline(tl, minutes, key, 70)}</div>")
    if not rows:
        return ""
    return ("<section class='panel'><h3>Progress over time</h3><p class='sub'>Science consumed per minute across "
            "each run (scale 0-70/min); orange ticks mark finished techs.</p>" + "".join(reversed(rows)) + "</section>")


def render(out: Path, since: float) -> None:
    hours = collect(since)
    invalid = invalid_runs()
    findings = (EXP / "findings.md").read_text() if (EXP / "findings.md").exists() else ""
    esc = html.escape
    sections = []
    for h in sorted(hours):
        d = hours[h]
        items = []
        if d.get("notes"):
            items.append("<ul class='list'>" + "".join(f"<li>{esc(n)}</li>" for _, n in sorted(d["notes"])) + "</ul>")
        if d.get("runs"):
            rows = "".join(
                f"<tr><td class='n'>{time.strftime('%H:%M', time.localtime(t))}</td><td>{esc(str(r.get('scenario', '')))}</td>"
                f"<td>{esc(str(r.get('variant', '')))}</td><td>{esc(('INVALID: ' + invalid[r['run_id']]) if r.get('run_id') in invalid else fmt_scores(r))}</td><td>{esc(fmt_behavior(r))}</td></tr>"
                for t, r in sorted(d["runs"], key=lambda x: x[0]))
            items.append("<div class='tbl'><table><thead><tr><th>end</th><th>scenario</th><th>variant</th><th>scores</th>"
                         f"<th>behavior</th></tr></thead><tbody>{rows}</tbody></table></div>")
        if d.get("decisions"):
            items.append("<h3>Decisions</h3><ul class='list'>" + "".join(
                f"<li><b>{esc(dec)}</b> <span class='d'>{esc(why)}</span></li>" for _, dec, why in sorted(d["decisions"])) + "</ul>")
        if d.get("commits"):
            items.append("<h3>Changes</h3><ul class='list'>" + "".join(
                f"<li><span class='n'>{time.strftime('%H:%M', time.localtime(t))}</span> {esc(subj)}</li>"
                for t, subj in sorted(d["commits"])) + "</ul>")
        if d.get("snapshots"):
            items.append("<h3>Snapshots</h3><ul class='list'>" + "".join(
                f"<li><code>{esc(s['save'])}</code> {s.get('minutes', '?')} game-min, {s.get('research_count', len(s.get('researched', [])))} techs</li>"
                for _, s in sorted(d["snapshots"], key=lambda x: x[0])) + "</ul>")
        n_runs, n_commits = len(d.get("runs", [])), len(d.get("commits", []))
        summary = f"{n_runs} run{'s' * (n_runs != 1)} · {n_commits} change{'s' * (n_commits != 1)} · {len(d.get('decisions', []))} decisions"
        sections.append(f"<section class='panel'><div class='hh'><h2>{h}</h2><span class='chip'>{summary}</span></div>{''.join(items)}</section>")

    page = TEMPLATE.replace("{{UPDATED}}", time.strftime("%Y-%m-%d %H:%M")) \
        .replace("{{FINDINGS}}", md_to_html(findings) if findings else "<p class='sub'>First results land after the first benchmark runs.</p>") \
        .replace("{{PROGRESS}}", progress_panel(since)) \
        .replace("{{HOURS}}", "\n".join(reversed(sections)) or "<p class='sub'>Nothing logged yet.</p>")
    out.write_text(page)


def md_to_html(md: str) -> str:
    esc = html.escape
    out, in_list = [], False
    for line in md.splitlines():
        if line.startswith("- "):
            if not in_list:
                out.append("<ul class='list'>")
                in_list = True
            body = esc(line[2:])
            body = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", body)
            out.append(f"<li>{body}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if line.startswith("### "):
            out.append(f"<h3>{esc(line[4:])}</h3>")
        elif line.strip():
            out.append("<p>" + re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", esc(line)) + "</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


TEMPLATE = """<title>Claude Crew Build Log</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Titillium+Web:wght@400;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
/* Layout: one narrow column of game-UI panels, newest hour first; orange is the only accent. */
:root {
  --bg: #e9e6e1; --panel: #f7f5f2; --line: #cfc9bf; --fg: #26231f; --muted: #6b645a; --accent: #c76a00;
  --chipbg: #ebe7e1;
  --display: "Titillium Web", "Segoe UI", system-ui, sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, Menlo, monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #1d1b19; --panel: #2a2724; --line: #403b35; --fg: #ece7df; --muted: #a59d91; --accent: #ffa31a;
  --chipbg: #2f2b27; color-scheme: dark } }
:root[data-theme="dark"] {
  --bg: #1d1b19; --panel: #2a2724; --line: #403b35; --fg: #ece7df; --muted: #a59d91; --accent: #ffa31a;
  --chipbg: #2f2b27; color-scheme: dark }
body { background: var(--bg); color: var(--fg); font-family: var(--display); font-size: 16px; line-height: 1.55; }
.wrap { max-width: 900px; margin: 0 auto; padding-block: 28px 64px;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px));
  display: flex; flex-direction: column; gap: 18px; }
h1 { font-weight: 700; font-size: 2rem; line-height: 1.15; margin: 0; text-wrap: balance; }
h1 span { color: var(--accent); }
h2 { font-size: 1.1rem; margin: 0; font-variant-numeric: tabular-nums; }
h3 { font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); margin: 6px 0 0; }
p { margin: 0; max-width: 70ch; }
.sub { color: var(--muted); }
.panel { background: var(--panel); border: 1px solid var(--line); border-radius: 4px; padding: 16px 20px;
  display: flex; flex-direction: column; gap: 10px; min-width: 0; }
.hh { display: flex; flex-wrap: wrap; gap: 10px; align-items: baseline; justify-content: space-between; }
.chip { font-family: var(--mono); font-size: 0.74rem; padding: 2px 8px; border-radius: 3px; background: var(--chipbg);
  color: var(--muted); white-space: nowrap; }
ul.list { margin: 0; padding-left: 1.1rem; display: flex; flex-direction: column; gap: 4px; max-width: 75ch; }
.d { color: var(--muted); }
.n { font-family: var(--mono); font-size: 0.84rem; font-variant-numeric: tabular-nums; color: var(--muted); }
code { font-family: var(--mono); font-size: 0.84em; background: var(--chipbg); padding: 1px 5px; border-radius: 3px; }
.tbl { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 0.9rem; min-width: 600px; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
th { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); font-weight: 600; }
.lead { border-color: var(--accent); }
.prow { display: grid; grid-template-columns: minmax(0, 1fr) minmax(140px, 300px); gap: 12px; align-items: center;
  padding: 6px 0; border-bottom: 1px solid var(--line); }
.prow:last-child { border-bottom: 0; }
.spark { width: 100%; height: 56px; display: block; }
.spark .ln { fill: none; stroke: var(--fg); stroke-width: 1.5; vector-effect: non-scaling-stroke; }
.spark .ax { stroke: var(--line); stroke-width: 1; vector-effect: non-scaling-stroke; }
.spark .tk { stroke: var(--accent); stroke-width: 2; vector-effect: non-scaling-stroke; }
@media (max-width: 520px) { .prow { grid-template-columns: 1fr; } }
</style>
<div class="wrap">
  <header style="display:flex;flex-direction:column;gap:6px">
    <h1>Claude Crew <span>build log</span></h1>
    <p class="sub">Overnight tuning: making three Opus players progress like real players, faster, with less idle time. Newest hour first. Updated {{UPDATED}}.</p>
  </header>
  <section class="panel lead"><h3>Headline findings</h3>{{FINDINGS}}</section>
  {{PROGRESS}}
  {{HOURS}}
  <footer class="sub" style="font-size:0.85rem">Private page. Built from the decision log, commits, benchmark results and snapshots.</footer>
</div>
"""

if __name__ == "__main__":
    render(Path(sys.argv[1]), parse_since(sys.argv))
    print("rendered", sys.argv[1])
