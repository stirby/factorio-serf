"""Lessons: rules the serf was taught (or learned the hard way), kept per user across all worlds.

- lessons.md: one "- rule" line each, shown to the agent every turn. The user may edit it by hand.
- lessons.jsonl: every lesson with the chat that prompted it, for whoever improves the code: a lesson that works
  around a tool or mod bug is a bug report (see "Lessons loop" in CLAUDE.md).
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from .config import _home

MAX_LESSONS = 40


def lessons_dir() -> Path:
    """Next to the design library (SERF_LESSONS_DIR overrides, for tests)."""
    if os.environ.get("SERF_LESSONS_DIR"):
        return Path(os.environ["SERF_LESSONS_DIR"])
    return _home("~/.local/state", "factorio-serf")


def load() -> list[str]:
    path = lessons_dir() / "lessons.md"
    if not path.exists():
        return []
    return [line[2:].strip() for line in path.read_text().splitlines() if line.startswith("- ") and line[2:].strip()]


def render() -> str:
    return "\n".join(f"{i}. {text}" for i, text in enumerate(load(), 1))


def add(text: str, replaces: int | None = None, *, agent: str = "", world: str = "", context: list[str] = ()) -> str:
    """Record one lesson (or replace lesson number `replaces`). Returns a message for the agent."""
    text = re.sub(r"\s+", " ", text).strip().lstrip("-").strip()
    if not text:
        return "error: give the lesson as one short sentence"
    items = load()
    if replaces is not None:
        if not 1 <= replaces <= len(items):
            return f"error: there is no lesson {replaces} (you have {len(items)})"
        old = items[replaces - 1]
        items[replaces - 1] = text
    else:
        if text.lower() in (i.lower() for i in items):
            return "already a lesson"
        if len(items) >= MAX_LESSONS:
            return (f"error: you have {MAX_LESSONS} lessons; merge this into an existing one with replaces=<number> "
                    "(keep them general and short)")
        old = None
        items.append(text)
    d = lessons_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / "lessons.md").write_text("".join(f"- {i}\n" for i in items))
    entry = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "agent": agent, "world": world, "lesson": text,
             "replaced": old, "context": list(context)}
    with open(d / "lessons.jsonl", "a") as f:
        f.write(json.dumps(entry) + "\n")
    return f"lesson {'updated' if old else 'saved'}; it applies in every world from now on"
