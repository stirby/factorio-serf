"""Todo List (the Todo-List mod) as the serf's task list: tasks assigned to it become its orders, worked in the list's
order after anything said in chat; its live status shows under the task's title, its plan's steps are the task's
subtasks and tick off as they run, and a finished task is marked done. A failed one stays open with the reason (edit
it to have the serf try again); unassigning or deleting a task drops its order.

Needs Todo-List's remote interface (a patch to that mod: version 1 of get_tasks, add_assignee, update_task,
set_subtasks, mark_complete), reached through the serf mod's `todo` op. Without it the bridge does nothing. Live test:
"I would love to write out tasks there, assign the serf, then let it work on them".
"""
from __future__ import annotations

import asyncio
import json
import time



def as_list(x) -> list:
    """A Lua array arrives as a JSON list, or {} when empty."""
    if isinstance(x, list):
        return x
    if isinstance(x, dict):
        return [x[k] for k in sorted(x, key=lambda k: int(k) if str(k).isdigit() else 0)]
    return []


def signature(t: dict) -> str:
    return f"{t.get('title') or ''}\n{t.get('task') or ''}"


class TodoBridge:
    POLL = 3.0

    def __init__(self, actor):
        self.a = actor
        self.available: bool | None = None
        self.by_task: dict[int, int] = {}  # task id -> order id
        self.sig: dict[int, str] = {}  # task id -> its words when its order was made (an edit means try again)
        self.pushed: dict[int, str] = {}  # task id -> what was last written to it
        self.settled: dict[int, str] = {}  # task id -> its words when found already tried and given up on (no order)
        self.errors = 0

    def gave_up(self, t: dict) -> bool:
        """The task's status line, kept in the save, says this serf already tried it and couldn't finish or was
        stopped: after a restart of the app that's the only memory of it (live test 25 Oct: a task given up on after
        6 plans was taken again as a new order once the app restarted)."""
        st = str(t.get("status") or "")
        return t.get("status_kind") == "error" and (st.startswith(f"{self.a.name} · couldn't finish")
                                                    or st == f"{self.a.name} · stopped")

    async def call(self, fn: str, *args):
        r = await self.a.g.call("todo", fn=fn, args=list(args), timeout=15)
        if not (isinstance(r, dict) and r.get("available")):
            return None
        return r.get("result")

    async def loop(self) -> None:
        for o in self.a.orders:  # resumed after a restart: keep their tasks
            if getattr(o, "todo_id", None) is not None:
                self.by_task[o.todo_id] = o.id
        while True:
            await asyncio.sleep(self.POLL)
            if self.a.g.empty:
                continue
            try:
                await self.tick()
                self.errors = 0
            except Exception as e:  # noqa: BLE001
                self.errors += 1
                if self.errors <= 3:
                    self.a.log({"kind": "error", "where": "todo", "error": repr(e)[:300]})
                await asyncio.sleep(min(60, 5 * self.errors))

    async def tick(self) -> None:
        if not self.available:
            v = await self.call("version")
            if not v:
                self.available = False
                await asyncio.sleep(60)  # Todo-List (with the interface) isn't in this game
                return
            self.available = True
            await self.call("add_assignee", self.a.name)
            self.a.log({"kind": "todo", "available": True, "version": v})
        tasks = as_list(await self.call("get_tasks", False))
        mine = [t for t in tasks if isinstance(t, dict) and t.get("assignee") == self.a.name and not t.get("done")]
        ids = {int(t["id"]) for t in mine}
        # tasks gone, unassigned or ticked off by a player: their orders go too
        for tid, oid in list(self.by_task.items()):
            if tid in ids:
                continue
            o = self.a.order_by_id(oid)
            if o and o.status in ("new", "working", "thinking"):
                await self.a.drop_order(o, "its Todo task was removed, reassigned or ticked off")
            self.by_task.pop(tid, None)
            self.sig.pop(tid, None)
            self.pushed.pop(tid, None)
        for tid in [k for k in self.settled if k not in ids]:
            self.settled.pop(tid)
        for rank, t in enumerate(mine):
            tid = int(t["id"])
            o = self.a.order_by_id(self.by_task.get(tid, -1))
            if o is None and tid not in self.by_task and self.gave_up(t):
                self.settled.setdefault(tid, signature(t))
            if tid in self.settled:
                if signature(t) == self.settled[tid]:
                    continue  # left as it is; editing the task tries it again
                self.settled.pop(tid)
            if o is None or (o.status in ("failed", "cancelled") and signature(t) != self.sig.get(tid)):
                # a new task for the serf, or a failed one the player edited: an order
                text = (t.get("title") or "").strip()
                if (t.get("task") or "").strip() and (t.get("task") or "").strip() != text:
                    text += ": " + t["task"].strip()
                o = await self.a.add_order(text[:600], str(t.get("created_by") or "a player"))
                o.todo_id = tid
                self.by_task[tid], self.sig[tid] = o.id, signature(t)
                self.a.log({"kind": "todo_order", "task": tid, "order": o.id})
            o.todo_rank = rank
            await self.push(tid, o)

    def status_of(self, o) -> tuple[str, str, list]:
        """(status line, kind, subtasks) for the order's task. Kinds are Todo List's: info, progress, attention, error,
        success."""
        name = self.a.name
        subtasks = []
        v = getattr(self.a, "view", None)
        if v and v.get("order") == o.id:
            subtasks = [{"task": t, "done": st == "ok"} for t, st in zip(v["steps"], v["states"])]
        if o.status == "thinking":
            return f"{name} · planning it", "progress", subtasks
        if o.status == "working":
            if getattr(o, "asked", None):
                return f"{name} · needs you: {o.asked[:120]}", "attention", subtasks
            if v and v.get("order") == o.id and v["steps"]:
                i = next((k for k, st in enumerate(v["states"]) if st in ("run", "fail")), None)
                if i is not None:
                    return f"{name} · working · step {i + 1} of {len(v['steps'])}: {v['steps'][i][:80]}", "progress", subtasks
            return f"{name} · working", "progress", subtasks
        if o.status == "new":
            queued = [x for x in self.a.orders if x.status == "new"]
            k = self.a.queue_position(o, queued)
            return f"{name} · queued, #{k} in line", "info", subtasks
        if o.status == "done":
            return f"{name} · done", "success", subtasks
        if o.status == "failed":
            return f"{name} · couldn't finish: {getattr(o, 'fail_reason', '') or 'the checks never passed'}", "error", subtasks
        return f"{name} · stopped", "error", subtasks

    async def push(self, tid: int, o) -> None:
        status, kind, subtasks = self.status_of(o)
        key = json.dumps([status, kind, subtasks, o.status], sort_keys=True)
        if self.pushed.get(tid) == key:
            return
        await self.call("update_task", tid, {"status": status, "status_kind": kind})
        if subtasks:
            await self.call("set_subtasks", tid, self.a.name, subtasks)
        if o.status == "done":
            await self.call("mark_complete", tid)
            self.a.log({"kind": "todo_done", "task": tid, "order": o.id, "t": time.time()})
        self.pushed[tid] = key
