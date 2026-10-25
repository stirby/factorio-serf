#!/usr/bin/env python3
"""A snapshot of the running tests for the monitoring dashboard: rows written as JSON files under media/monitor/.

- runs.json        bench runs going now and finished in the last 36 h (one row each)
- campaigns.json   the long campaigns: level, generation, research, science, orders, the manager's last note
- milestones.json  each campaign's milestone changes over the last 48 h (for the timeline)
- changes.json     commits to the harness in the last 36 h

    .venv/bin/python bench/monitor_snapshot.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "bench" / "runs"
OUT = ROOT / "media" / "monitor"
OUT.mkdir(parents=True, exist_ok=True)
NOW = time.time()
CAMPAIGNS = {"p6": ("w6", "player"), "q6": ("w6", "classic"), "p7": ("w7", "player"), "q7": ("w7", "classic"),
             "p8": ("w8", "player"), "p9": ("w9", "player"), "p10": ("w10", "player"), "q10": ("w10", "classic"),
             "p11": ("w11", "player"), "q11": ("w11", "classic"),
             "p12": ("w12", "player"), "q12": ("w12", "classic")}
RUNG = {"b1": "circuits off a bus", "b2": "red science from plates", "b3": "steel", "b4": "red+green 45/min",
        "b5": "double red+green", "b6": "plastic + sulfur from crude", "b7": "blue science from scratch",
        "b8": "purple science", "b9": "fix a broken crude line", "b10": "crude 450 tiles out",
        "b11": "research then build", "b12": "yellow science", "b13": "rocket from rocket parts",
        "b14": "rocket from plates", "b15": "rocket from the map's ore"}
MS_LINE = re.compile(r"^\[(\d\d:\d\d:\d\d)\] (\w+) g(\d+): milestone (\d+) \(([^)]*)\), (\d+) techs, research (\S+)")
MIN_LINE = re.compile(r"bench: ([\d.]+) min \[([^\]]+)\]: (\{.*\})")


def iso(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t))


def tail_lines(p: Path, nbytes: int = 400_000) -> list[str]:
    try:
        with open(p, "rb") as f:
            f.seek(0, 2)
            n = f.tell()
            f.seek(max(0, n - nbytes))
            return f.read().decode(errors="ignore").splitlines()
    except OSError:
        return []


def rung_of(scn: str) -> str:
    m = re.match(r"(b\d+)", scn)
    return RUNG.get(m.group(1), scn) if m else scn


def last_say(run_dir: Path | None) -> str:
    if not run_dir:
        return ""
    for line in reversed(tail_lines(run_dir / "actor.jsonl", 200_000)):
        if '"kind": "say"' in line:
            try:
                return str(json.loads(line).get("text", ""))[:160]
            except ValueError:
                continue
    return ""


def run_dir_for(scn: str, slot: str, after: float) -> Path | None:
    ds = [d for d in RUNS.glob(f"*-{scn}-*i{slot}") if d.is_dir() and d.stat().st_mtime >= after - 60]
    return max(ds, key=lambda d: d.stat().st_mtime) if ds else None


def runs() -> list[dict]:
    rows = []
    seen_out = set()
    # running: bench/run.py processes; their stdout file holds the per-minute progress
    for pid in subprocess.run(["pgrep", "-f", "bench/[r]un.py"], capture_output=True, text=True).stdout.split():
        try:
            cmd = Path(f"/proc/{pid}/cmdline").read_bytes().decode().split("\0")
            out = os.readlink(f"/proc/{pid}/fd/1")
            started = Path(f"/proc/{pid}").stat().st_mtime
        except OSError:
            continue
        scn = Path(cmd[cmd.index("--scenario") + 1]).stem if "--scenario" in cmd else "?"
        slot = cmd[cmd.index("--instance") + 1] if "--instance" in cmd else "?"
        seen_out.add(out)
        rows.append(run_row(Path(out), scn, slot, started, running=True))
    # finished in the last 36 h: the .out files whose last line is the result
    for out in RUNS.glob("b*-*.out"):
        if str(out) in seen_out or NOW - out.stat().st_mtime > 36 * 3600:
            continue
        lines = tail_lines(out, 20_000)
        if not lines or '"success"' not in lines[-1]:
            continue
        scn = re.sub(r"-(r\d+|g\d+|s\d+|base\d+)$", "", out.stem)
        rows.append(run_row(out, scn, "", out.stat().st_mtime, running=False))
    return sorted(rows, key=lambda r: (r["state"] != "running", r["started"]), reverse=False)


def run_row(out: Path, scn: str, slot: str, started: float, running: bool) -> dict:
    lines = tail_lines(out, 200_000)
    minutes, metric, value = 0.0, "", None
    for ln in reversed(lines):
        m = MIN_LINE.search(ln)
        if m:
            minutes = float(m.group(1))
            try:
                d = json.loads(m.group(3).replace("'", '"'))
                metric, value = next(iter(d.items())) if d else ("", None)
            except ValueError:
                pass
            break
    result = None
    if lines and '"success"' in lines[-1]:
        try:
            result = json.loads(lines[-1])
        except ValueError:
            result = None
    state = "running" if running else ("met" if result and result.get("success") else "missed")
    if result:
        minutes = round((result.get("elapsed_s") or 0) / 60, 1)
        started = result.get("t0") or started
    target = None
    try:
        sc = json.loads((ROOT / "bench" / "scenarios" / f"{scn}.json").read_text())
        target = sc["objectives"][0]["score"][0].get("target")
    except (OSError, ValueError, KeyError, IndexError):
        pass
    rd = run_dir_for(scn, slot or (result or {}).get("run_id", "").rsplit("-i", 1)[-1], started) if running else None
    cost = (result or {}).get("cost_usd")
    if cost is None and rd:
        cost = 0.0
        for line in tail_lines(rd / "actor.jsonl", 3_000_000):
            if '"kind": "thinker_turn"' in line:
                try:
                    cost += float(json.loads(line).get("cost") or 0)
                except ValueError:
                    pass
    return {"run": out.stem, "scenario": scn, "rung": rung_of(scn), "slot": slot, "state": state,
            "started": iso(started), "minutes": minutes, "metric": metric,
            "value": round(float(value), 1) if isinstance(value, (int, float)) else None, "target": target,
            "cost_usd": round(cost, 2) if cost is not None else None, "last_message": last_say(rd)}


def campaigns() -> tuple[list[dict], list[dict]]:
    rows, ms_rows = [], []
    for name, (world, style) in CAMPAIGNS.items():
        lines = tail_lines(RUNS / f"camp_{name}.out", 3_000_000)
        last, prev_level = None, None
        day0 = time.strftime("%Y-%m-%d", time.localtime(NOW))
        # timestamps in the log are clock times only: walk back from now, a day earlier each time the clock goes up
        stamps = []
        for ln in lines:
            m = MS_LINE.match(ln)
            if m:
                stamps.append(m)
        day = 0
        times = []
        later = None
        for m in reversed(stamps):
            hh, mm, ss = (int(x) for x in m.group(1).split(":"))
            t = time.mktime(time.strptime(day0, "%Y-%m-%d")) + hh * 3600 + mm * 60 + ss - day * 86400
            if later is not None and t > later:
                day += 1
                t -= 86400
            later = t
            times.append((t, m))
        times.reverse()
        for t, m in times:
            if NOW - t > 48 * 3600:
                continue
            level = int(m.group(4))
            if level != prev_level:
                ms_rows.append({"time": iso(t), "campaign": name, "level": level, "milestones": m.group(5)})
                prev_level = level
            last = (t, m)
        orders = failed = 0
        note = ""
        pj = ROOT / "bench" / "campaigns" / name / "project" / "project.jsonl"
        for line in tail_lines(pj, 3_000_000):
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if NOW - (e.get("t") or 0) > 6 * 3600:
                continue
            if e.get("kind") == "order_end":
                orders += 1
                failed += "failed" in str(e.get("outcome"))
        jl = tail_lines(ROOT / "bench" / "campaigns" / name / "project" / "journal.jsonl", 60_000)
        for line in reversed(jl):
            try:
                t = json.loads(line).get("text", "")
            except ValueError:
                continue
            if t and not t.startswith("(harness note"):
                note = t[:240]
                break
        spm_u = None
        for line in reversed(tail_lines(ROOT / "bench" / "campaigns" / name / "audits.jsonl", 40_000)):
            try:
                e = json.loads(line)
                spm_u = e.get("spm_sustained", e.get("spm"))
                break
            except ValueError:
                continue
        att = None
        for line in reversed(tail_lines(RUNS / "ab_watch.jsonl", 400_000)):
            if f'"run": "{name}"' in line:
                try:
                    att = json.loads(line)
                    break
                except ValueError:
                    continue
        rows.append({"campaign": name, "world": world, "style": style,
                     "generation": int(last[1].group(3)) if last else None,
                     "level": int(last[1].group(4)) if last else None,
                     "milestones": last[1].group(5) if last else "", "techs": int(last[1].group(6)) if last else None,
                     "research": (last[1].group(7) if last else "").replace("None", "nothing queued"),
                     "science_per_min": (att or {}).get("spm"), "working_share": (att or {}).get("working_share"),
                     "unattended_spm": spm_u, "orders_6h": orders, "failed_6h": failed, "last_note": note,
                     "updated": iso(last[0]) if last else None})
    return rows, ms_rows


def changes() -> list[dict]:
    out = subprocess.run(["git", "-C", str(ROOT), "log", "--since=36 hours ago", "--pretty=%ct\t%h\t%s"],
                         capture_output=True, text=True).stdout
    rows = []
    for ln in out.splitlines():
        ts, h, subj = ln.split("\t", 2)
        rows.append({"time": iso(int(ts)), "commit": h, "change": subj[:160]})
    return rows


def main() -> None:
    c_rows, m_rows = campaigns()
    data = {"runs": runs(), "campaigns": c_rows, "milestones": m_rows, "changes": changes()}
    for k, v in data.items():
        (OUT / f"{k}.json").write_text(json.dumps(v, indent=1))
        print(f"{k}: {len(v)} rows -> media/monitor/{k}.json")


if __name__ == "__main__":
    main()
