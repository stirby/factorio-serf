#!/usr/bin/env python3
"""Export every night's runs for the results dashboard (the "Serf Nights" artifact), one row per run.

    .venv/bin/python experiments/dash_export.py [out_dir]     # default experiments/dash/

Writes runs.csv (one row per run, every night and track) and library.csv (one row per night and track: what the
serfs' own layer held at the end). A night directory named <YYYYMMDD>-<track> (e.g. 20261020-opus) is a second
track that night; a bare <YYYYMMDD> is the Sonnet track. Upload both files to the dashboard each morning.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NIGHTS = ROOT / "experiments" / "nights"

# time-lost buckets from waste.py, as short column names
LOST = {"thinking": "think_min", "waiting on jobs": "wait_jobs_min", "idle (nothing running)": "idle_min",
        "looking": "look_min", "hand building": "hand_build_min", "blueprint/line building": "line_build_min",
        "walking": "walk_min", "crafting/fetching": "craft_fetch_min", "failed calls": "failed_calls_min",
        "own scripts": "scripts_min", "other": "other_min"}
RUN_COLS = ["night", "track", "phase", "cycle", "scenario", "success", "met", "objectives", "cost", "minutes",
            "calls", "failed_calls", "waste", "skill_runs", "skill_saves", "failure_kinds", "commit", "run",
            *LOST.values()]
LIB_COLS = ["night", "track", "scripts", "playbooks", "lessons", "designs", "script_uses", "skill_saves", "friction"]


def night_track(d: Path) -> tuple[str, str]:
    stamp, _, track = d.name.partition("-")
    return f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}", track or "sonnet"


def runs(d: Path) -> list[dict]:
    night, track = night_track(d)
    out = []
    p = d / "runs.jsonl"
    for line in (p.read_text().splitlines() if p.exists() else []):
        if not line.strip():
            continue
        r = json.loads(line)
        tools = r.get("by_tool") or {}
        lost = r.get("lost_min") or {}
        phase = r.get("phase") or ""
        row = {"night": night, "track": track, "phase": "train" if phase.startswith("train") else phase,
               "cycle": r.get("cycle") or "", "scenario": r.get("scenario"), "success": int(bool(r.get("success"))),
               "met": r.get("met") or 0, "objectives": r.get("objectives") or 0,
               "cost": round(r.get("cost") or 0, 3), "minutes": r.get("minutes") or 0, "calls": r.get("calls") or 0,
               "failed_calls": r.get("failed_calls") or 0, "waste": r.get("waste") or 0,
               "skill_runs": tools.get("skill_run", 0), "skill_saves": tools.get("skill_save", 0),
               "failure_kinds": len(r.get("failure_kinds") or []), "commit": r.get("commit") or "",
               "run": r.get("run")}
        row.update({col: round(lost.get(k, 0), 2) for k, col in LOST.items()})
        out.append(row)
    return out


def library(d: Path) -> dict:
    night, track = night_track(d)
    lib = d / "library"
    kinds = [json.loads(p.read_text()).get("kind") for p in (lib / "skills").glob("*.json")]
    lessons = lib / "lessons" / "lessons.jsonl"
    usage = lib / "skills" / "usage.jsonl"

    def lines(p: Path) -> int:
        return sum(1 for l in p.read_text().splitlines() if l.strip()) if p.exists() else 0
    friction = 0
    for r in (json.loads(l) for l in (d / "runs.jsonl").read_text().splitlines() if l.strip()):
        friction += (r.get("by_tool") or {}).get("friction", 0)
    return {"night": night, "track": track, "scripts": kinds.count("script"), "playbooks": kinds.count("playbook"),
            "lessons": lines(lessons), "designs": len(list((lib / "designs").glob("*.json"))),
            "script_uses": lines(usage), "skill_saves": lines(lib / "skills" / "history.jsonl"), "friction": friction}


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "experiments" / "dash"
    out.mkdir(parents=True, exist_ok=True)
    all_runs, libs = [], []
    for d in sorted(p for p in NIGHTS.iterdir() if p.is_dir() and (p / "runs.jsonl").exists()):
        rows = runs(d)
        all_runs += rows
        libs.append(library(d))
    for name, cols, rows in (("runs.csv", RUN_COLS, all_runs), ("library.csv", LIB_COLS, libs)):
        with open(out / name, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
    print(f"{len(all_runs)} runs, {len(libs)} night-tracks -> {out}")


if __name__ == "__main__":
    main()
