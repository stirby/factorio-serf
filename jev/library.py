"""The agent layer: what the thinker writes for its future self. Lessons are short general rules saved after an
order that needed more than one plan; they go into the thinker's prompt in later games. The library lives in
JEV_LIBRARY (default <repo>/library); the overnight loop points every run of a night at one library so it grows."""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def lib_dir() -> Path:
    return Path(os.environ.get("JEV_LIBRARY") or ROOT / "library")


def lessons(limit: int = 40) -> list[str]:
    p = lib_dir() / "lessons.jsonl"
    if not p.exists():
        return []
    rows = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    seen, out = set(), []
    for r in reversed(rows):
        t = r.get("text", "").strip()
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
        if len(out) >= limit:
            break
    return list(reversed(out))


# A rule that routes around a harness op ("if tap crashes, stop using it and hand-place splitters") outlives the fix
# and keeps every later planner off the tool (2026-10-23: four such lessons from one fixture bug turned the bus runs
# away from tap and bus_in for hours). Those go to tool_complaints.jsonl, for whoever maintains the harness.
OPS = ("tap", "bus_in", "bus", "connect", "route", "row", "merge_lanes", "ghosts", "block", "stamp", "design",
       "upgrade", "clear", "power", "place", "insert", "fetch", "craft", "mine", "mine_at", "purge", "research",
       "configure", "launch", "move")
_OPS_RE = "|".join(sorted(OPS, key=len, reverse=True))
TOOL_COMPLAINT = re.compile(
    rf"\b(?:stop using|don'?t use|do not use|never use|avoid(?: using)?)\s+(?:the\s+)?(?:`?(?:{_OPS_RE})`?"
    rf"(?:\s*(?:/|,|and|or)\s*`?(?:{_OPS_RE})`?)*)\s+(?:ops?|steps?|tools?)\b"
    rf"|\b(?:{_OPS_RE})\b[^.]{{0,40}}\b(?:crash(?:es|ed)?|is broken|doesn'?t work|TypeError)", re.I)


def save_lesson(text: str, source: dict | None = None) -> str:
    text = " ".join(str(text).split())[:400]
    if len(text) < 15:
        return "too short to be a rule"
    d = lib_dir()
    d.mkdir(parents=True, exist_ok=True)
    if TOOL_COMPLAINT.search(text):
        with open(d / "tool_complaints.jsonl", "a") as f:
            f.write(json.dumps({"t": time.time(), "text": text, "source": source or {}}) + "\n")
        return ("not saved as a rule: it works around a tool of the harness, which gets fixed instead (sent to the "
                "maintainers). Save what you learned about the game, not about avoiding a tool")
    with open(d / "lessons.jsonl", "a") as f:
        f.write(json.dumps({"t": time.time(), "text": text, "source": source or {}}) + "\n")
    return "saved"


def designs() -> dict[str, dict]:
    d = lib_dir() / "designs"
    out = {}
    for p in sorted(d.glob("*.json")) if d.exists() else []:
        try:
            x = json.loads(p.read_text())
            out[x["name"]] = x
        except Exception:  # noqa: BLE001
            pass
    return out


def save_design(name: str, entities: list[dict], note: str = "") -> str:
    """entities: [{name, x, y, direction?, recipe?}] relative to an anchor at 0,0 (integer tile corner)."""
    import re
    slug = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")[:40]
    if not slug or not entities:
        return "needs a name and entities"
    from .steps import expand
    clean = []
    for e in expand(entities):
        try:
            q = {"name": e["name"], "x": float(e["x"]), "y": float(e["y"])}
        except (KeyError, TypeError, ValueError):
            return f"bad entity {e!r}: needs name, x, y"
        for k in ("direction", "recipe"):
            if e.get(k):
                q[k] = e[k]
        clean.append(q)
    d = lib_dir() / "designs"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{slug}.json").write_text(json.dumps({"name": slug, "note": note[:300], "entities": clean}, indent=1))
    return f"saved design {slug} ({len(clean)} entities)"


def place_design(name: str, x: float, y: float) -> list[dict] | None:
    """The design's entities moved to anchor x,y (rounded to a tile corner so .5 centers stay .5)."""
    ds = designs()
    if name not in ds:
        return None
    ax, ay = round(float(x)), round(float(y))
    return [{**e, "x": e["x"] + ax, "y": e["y"] + ay} for e in ds[name]["entities"]]


def playbooks() -> dict[str, dict]:
    """Sequences of orders a project manager saved after they worked, for later projects."""
    p = lib_dir() / "playbooks.json"
    try:
        return json.loads(p.read_text()) if p.exists() else {}
    except json.JSONDecodeError:
        return {}


def save_playbook(name: str, when: str, orders: list[str], result: str = "") -> str:
    import re
    slug = re.sub(r"[^a-z0-9-]+", "-", str(name).lower()).strip("-")[:40]
    orders = [" ".join(str(o).split())[:500] for o in (orders or []) if str(o).strip()][:12]
    if not slug or not orders:
        return "needs a name and the orders"
    d = lib_dir()
    d.mkdir(parents=True, exist_ok=True)
    books = playbooks()
    books[slug] = {"when": " ".join(str(when).split())[:300], "orders": orders, "result": str(result)[:300],
                   "t": time.time()}
    (d / "playbooks.json").write_text(json.dumps(books, indent=1))
    return f"saved playbook {slug} ({len(orders)} orders)"
