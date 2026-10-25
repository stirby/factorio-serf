#!/usr/bin/env python3
"""The serf's Todo List bridge end to end on test servers: the serf mod's todo op answers "not available" without
Todo-List, and with the patched Todo-List a task assigned to the serf becomes its order, gets its status and plan
steps written back, and is ticked off when the order is done (jev/todo_bridge.py; the order's work is simulated).

    .venv/bin/python tests/todo_bridge_live.py --zip <scratchpad>/todo-patch/Todo-List_19.15.90.zip [--instance 62]
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from instance import Instance  # noqa: E402
from jev import decide  # noqa: E402
from jev.actor import Actor  # noqa: E402
from jev.game import Game  # noqa: E402
from jev.todo_bridge import TodoBridge, as_list  # noqa: E402

FAILS: list[str] = []


def check(name, cond, info=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  ({info})" if info and not cond else ""), flush=True)
    if not cond:
        FAILS.append(name)


async def tasks(g: Game, done: bool = False) -> list:
    r = await g.call("todo", fn="get_tasks", args=[done])
    return as_list(r.get("result"))


async def without(k: int) -> None:
    inst = Instance(k, "crew-test")
    await asyncio.to_thread(inst.start, 300)
    g = None
    try:
        g = await Game.connect(inst.host, inst.rcon_port, inst.password, "serf")
        r = await g.call("todo", fn="version")
        check("todo op: without Todo-List it says so (the bridge then does nothing)", r == {"available": False}, r)
    finally:
        if g:
            await g.crew.close()
        await asyncio.to_thread(inst.stop)


async def with_todo(k: int, zip_path: Path) -> None:
    inst = Instance(k, "crew-test", extra_mods=[zip_path])
    await asyncio.to_thread(inst.start, 300)
    g = None

    async def chat(jev, me, speaker, msg, doing, last):
        return decide.ChatCall(1.0, "new_job", 1.0, "plan", 1.0, 0.0)

    saved = decide.chat
    decide.chat = chat
    try:
        g = await Game.connect(inst.host, inst.rcon_port, inst.password, "serf")
        await g.start(spawn=True)
        r = await g.call("todo", fn="add_task", args=[{"title": "Roboport grid", "task": "as ghosts, for the bots",
                                                         "assignee": "serf", "created_by": "otterplex"}])
        tid = r.get("result")
        await g.call("todo", fn="add_task", args=[{"title": "Fulgora scrap", "assignee": "otterplex"}])
        a = Actor(g, None, Path(tempfile.mkdtemp()), "serf", think=False)
        b = TodoBridge(a)
        await b.tick()
        o = a.order_by_id(b.by_task.get(tid, -1))
        t = next((x for x in await tasks(g) if x.get("id") == tid), {})
        check("bridge: a task assigned to the serf becomes its order and says it's queued",
              o is not None and o.text == "Roboport grid: as ghosts, for the bots" and len(b.by_task) == 1
              and str(t.get("status", "")).startswith("serf · queued") and t.get("status_kind") == "queued", (t, o))
        o.status = "working"
        a.view = {"order": o.id, "goal": "g", "steps": ["fetch roboports", "ghost them", "power them"],
                  "states": ["ok", "run", "todo"]}
        await b.tick()
        t = next((x for x in await tasks(g) if x.get("id") == tid), {})
        subs = as_list(t.get("subtasks"))
        check("bridge: the task shows the step it's on, and the plan's steps as the serf's subtasks",
              "step 2 of 3: ghost them" in str(t.get("status")) and t.get("status_kind") == "working"
              and sorted(s.get("task") for s in subs) == ["fetch roboports", "ghost them", "power them"]
              and all(s.get("owner") == "serf" for s in subs)
              and [s.get("done") for s in subs if s.get("task") == "fetch roboports"] == [True], (t.get("status"), subs))
        o.status = "done"
        await b.tick()
        done = [x for x in await tasks(g, True) if x.get("id") == tid]
        open_ = [x for x in await tasks(g) if x.get("id") == tid]
        check("bridge: a done order ticks its task off", done and done[0].get("done") is True and not open_,
              (done, open_))
    finally:
        decide.chat = saved
        if g:
            await g.stop()
            await g.crew.close()
        await asyncio.to_thread(inst.stop)


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zip", required=True, type=Path)
    ap.add_argument("--instance", type=int, default=62)
    a = ap.parse_args()
    if not 60 <= a.instance <= 68:
        ap.error("--instance must be 60..68 (it uses this slot and the next)")
    await without(a.instance + 1)
    await with_todo(a.instance, a.zip.resolve())
    print(f"\n{'ALL OK' if not FAILS else str(len(FAILS)) + ' FAILED: ' + ', '.join(FAILS)}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
