"""Shared task board so agents can split work without talking over each other in chat."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Task:
    id: int
    title: str
    detail: str = ""
    status: str = "open"  # open | claimed | done | blocked | cancelled
    owner: str | None = None
    created_by: str = ""
    notes: list[str] = field(default_factory=list)
    updated: float = field(default_factory=time.time)


class Board:
    def __init__(self, path: Path):
        self.path = path
        self.tasks: dict[int, Task] = {}
        if path.exists():
            try:
                for t in json.loads(path.read_text()):
                    self.tasks[t["id"]] = Task(**t)
            except (json.JSONDecodeError, TypeError):
                pass

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps([asdict(t) for t in self.tasks.values()], indent=1))

    def post(self, by: str, title: str, detail: str = "", owner: str | None = None) -> Task:
        tid = max(self.tasks, default=0) + 1
        t = Task(id=tid, title=title, detail=detail, created_by=by, owner=owner,
                 status="claimed" if owner else "open")
        self.tasks[tid] = t
        self._save()
        return t

    def update(self, by: str, tid: int, status: str | None = None, note: str | None = None,
               owner: str | None = None) -> Task:
        t = self.tasks.get(tid)
        if not t:
            raise KeyError(f"no task {tid}")
        if status:
            t.status = status
            if status == "claimed" and not owner and not t.owner:
                t.owner = by
        if owner is not None:
            t.owner = owner or None
        if note:
            t.notes.append(f"{by}: {note}")
            t.notes = t.notes[-6:]
        t.updated = time.time()
        self._save()
        return t

    def active(self) -> list[Task]:
        return [t for t in self.tasks.values() if t.status in ("open", "claimed", "blocked")]

    def render(self, for_agent: str | None = None, limit: int = 12) -> str:
        tasks = sorted(self.active(), key=lambda t: (t.owner != for_agent, t.id))[:limit]
        if not tasks:
            return "(board is empty)"
        lines = []
        for t in tasks:
            who = f" @{t.owner}" if t.owner else ""
            lines.append(f"#{t.id} [{t.status}{who}] {t.title}" + (f" -- {t.detail}" if t.detail else ""))
            if t.notes:
                lines.append("    last note: " + t.notes[-1])
        return "\n".join(lines)
