#!/usr/bin/env python3
"""What the campaigns have done so far, as one JSON for the report: per campaign, its generations; per generation,
the probes over time (milestone level, techs, a few totals), the orders given with how they ended, and the cost.

    .venv/bin/python bench/campaign_report.py [names...] > campaigns.json"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
CAMPS = ROOT / "bench" / "campaigns"
TOTALS = ["iron-plate", "copper-plate", "electronic-circuit", "automation-science-pack", "logistic-science-pack",
          "chemical-science-pack", "production-science-pack", "utility-science-pack", "plastic-bar", "rocket-part"]


def jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    out = []
    for ln in p.read_text().splitlines():
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            pass
    return out


def generation(d: Path, mode: str) -> dict:
    probes = [p for p in jsonl(d / "progress.jsonl") if "level" in p]
    t0 = probes[0]["t"] if probes else None
    from jev.progress import MILESTONES
    pts = [{"min": round((p["t"] - t0) / 60, 1), "level": p["level"], "techs": p.get("techs"),
            "got": [lv for lv, nm, _ in MILESTONES if nm in (p.get("milestones") or [])],
            **{k: p.get("items", {}).get(k, 0) for k in TOTALS if p.get("items", {}).get(k)}} for p in probes]
    orders = []
    actor = jsonl(d / "actor.jsonl")
    ends = {r["order"]: r for r in actor if r.get("kind") == "order_end"}
    for r in actor:
        if r.get("kind") == "order":
            e = ends.get(r["order"], {})
            orders.append({"id": r["order"], "text": r.get("text", "")[:240], "playbook": r.get("playbook"),
                           "status": e.get("status", "running"), "mins": round(e.get("secs", 0) / 60, 1),
                           "plans": e.get("plans"), "min": round((r["t"] - t0) / 60, 1) if t0 else None})
    summ = json.loads((d / "summary.json").read_text()) if (d / "summary.json").exists() else None
    usd = {"thinker": round(sum(r.get("cost", 0) for r in actor if r.get("kind") == "thinker_turn"), 2)}
    return {"gen": d.name, "probes": pts, "orders": orders, "summary": summ, "usd": usd,
            "level": probes[-1]["level"] if probes else None, "level_start": probes[0]["level"] if probes else None,
            "milestones": probes[-1].get("milestones") if probes else None,
            "techs": probes[-1].get("techs") if probes else None}


def campaign(c: Path) -> dict:
    state = json.loads((c / "campaign.json").read_text()) if (c / "campaign.json").exists() else {}
    gens = [generation(d, "") for d in sorted(c.glob("gen-*"))]
    manager = []
    for f in (c / "project" / "project.jsonl", c / "strategist" / "strategist.jsonl"):
        manager += [r for r in jsonl(f) if r.get("kind") == "turn"]
    usd_manager = max([r.get("usd_total", 0) for r in manager] or [0])
    journal = [r.get("text", "")[:400] for r in jsonl(c / "project" / "journal.jsonl")] + \
              [r.get("text", "")[:400] for r in jsonl(c / "strategist" / "journal.jsonl")]
    return {"name": c.name, "worlds": state.get("worlds"), "stage": state.get("stage"),
            "mode": "project" if (c / "project").exists() else "strategist", "gens": gens,
            "manager_turns": len(manager), "manager_usd": round(usd_manager, 2), "journal_tail": journal[-6:]}


def main() -> None:
    names = sys.argv[1:] or sorted(d.name for d in CAMPS.iterdir() if d.is_dir())
    print(json.dumps([campaign(CAMPS / n) for n in names if (CAMPS / n).is_dir()], indent=1, default=str))


if __name__ == "__main__":
    main()
