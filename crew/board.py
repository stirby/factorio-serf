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


@dataclass
class Zone:
    name: str
    owner: str
    area: list[float]  # x1, y1, x2, y2
    purpose: str = ""


class Board:
    """Tasks, zones (who builds where) and the roadmap (milestones), persisted as one JSON file."""

    def __init__(self, path: Path):
        self.path = path
        self.tasks: dict[int, Task] = {}
        self.zones: dict[str, Zone] = {}
        self.roadmap: list[dict] = []  # {"goal": str, "status": "todo|doing|done", "by": str}
        if path.exists():
            try:
                raw = json.loads(path.read_text())
                if isinstance(raw, list):  # old format: tasks only
                    raw = {"tasks": raw}
                for t in raw.get("tasks", []):
                    self.tasks[t["id"]] = Task(**t)
                for z in raw.get("zones", []):
                    self.zones[z["name"]] = Zone(**z)
                self.roadmap = raw.get("roadmap", [])
            except (json.JSONDecodeError, TypeError, KeyError):
                pass

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"tasks": [asdict(t) for t in self.tasks.values()],
                                         "zones": [asdict(z) for z in self.zones.values()],
                                         "roadmap": self.roadmap}, indent=1))

    def claim_zone(self, by: str, name: str, area: list[float], purpose: str) -> tuple[Zone, list[str]]:
        x1, y1, x2, y2 = min(area[0], area[2]), min(area[1], area[3]), max(area[0], area[2]), max(area[1], area[3])
        overlaps = [z.name + f" ({z.owner})" for z in self.zones.values()
                    if z.name != name and z.owner != by
                    and not (x2 <= z.area[0] or x1 >= z.area[2] or y2 <= z.area[1] or y1 >= z.area[3])]
        z = Zone(name=name, owner=by, area=[x1, y1, x2, y2], purpose=purpose)
        self.zones[name] = z
        self._save()
        return z, overlaps

    def release_zone(self, name: str) -> bool:
        if self.zones.pop(name, None):
            self._save()
            return True
        return False

    def zone_at(self, x: float, y: float) -> Zone | None:
        for z in self.zones.values():
            if z.area[0] <= x <= z.area[2] and z.area[1] <= y <= z.area[3]:
                return z
        return None

    def set_roadmap(self, by: str, goals: list[str]) -> None:
        old = {m["goal"]: m for m in self.roadmap}
        self.roadmap = [old.get(g, {"goal": g, "status": "todo", "by": by}) for g in goals]
        self._save()

    def mark_milestone(self, idx: int, status: str) -> dict:
        m = self.roadmap[idx]
        m["status"] = status
        self._save()
        return m

    def render_zones(self) -> str:
        if not self.zones:
            return "(no zones claimed)"
        return "\n".join(f"{z.name} @{z.owner} [{z.area[0]:.0f},{z.area[1]:.0f} .. {z.area[2]:.0f},{z.area[3]:.0f}]"
                         + (f" -- {z.purpose}" if z.purpose else "") for z in self.zones.values())

    def render_roadmap(self) -> str:
        if not self.roadmap:
            return "(no roadmap yet)"
        mark = {"todo": " ", "doing": ">", "done": "x"}
        return "\n".join(f"[{mark.get(m['status'], '?')}] {i}. {m['goal']}" for i, m in enumerate(self.roadmap))

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
