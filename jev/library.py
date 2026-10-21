"""The agent layer: what the thinker writes for its future self. Lessons are short general rules saved after an
order that needed more than one plan; they go into the thinker's prompt in later games. The library lives in
JEV_LIBRARY (default <repo>/library); the overnight loop points every run of a night at one library so it grows."""
from __future__ import annotations

import json
import os
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


def save_lesson(text: str, source: dict | None = None) -> str:
    text = " ".join(str(text).split())[:400]
    if len(text) < 15:
        return "too short to be a rule"
    d = lib_dir()
    d.mkdir(parents=True, exist_ok=True)
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
