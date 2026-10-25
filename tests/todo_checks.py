#!/usr/bin/env python3
"""The Todo-List mod's remote interface (a patched Todo-List, for the serf's task bridge), on a test server.

Two runs on one test slot: the installed Todo-List (19.15.2) makes tasks and a player's subtask the old way and the
world is saved; then that save loads with the patched zip (the existing-save path) and every interface call is
exercised, junk inputs included. Calls go through the serf mod's eval (its Lua state can remote.call).

    .venv/bin/python tests/todo_checks.py --zip <scratchpad>/todo-patch/Todo-List_19.15.90.zip [--instance 62]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from instance import INSTALL, Instance  # noqa: E402
from jev.game import Game  # noqa: E402
from jev.rcon import Rcon  # noqa: E402

FAILS: list[str] = []


def check(name, cond, info=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  ({info})" if info and not cond else ""), flush=True)
    if not cond:
        FAILS.append(name)


async def ev(g: Game, code: str):
    return (await g.call("eval", code=code, timeout=60)).get("result")


async def rj(g: Game, call: str):
    """A remote call into Todo-List; its result through JSON (nil -> None)."""
    out = await ev(g, f"return helpers.table_to_json({{ v = {call} }})")
    return json.loads(out).get("v")


async def command(inst: Instance, cmd: str) -> str:
    r = Rcon(inst.host, inst.rcon_port, inst.password)
    await r.connect()
    try:
        return await r.command(cmd)
    finally:
        await r.close()


async def phase_old(k: int, saved: Path) -> None:
    """The installed 19.15.2: two tasks and a player's subtask, made with its own functions; then save."""
    old_zip = INSTALL / "mods" / "Todo-List_19.15.2.zip"
    inst = Instance(k, "crew-test", extra_mods=[old_zip])
    print(f"starting instance {k} with {old_zip.name}", flush=True)
    await asyncio.to_thread(inst.start, 300)
    try:
        g = await Game.connect(inst.host, inst.rcon_port, inst.password, "serf")
        has = await ev(g, "return remote.interfaces['Todo-List'] ~= nil")
        check("old: 19.15.2 has no remote interface", has is False, has)
        # the first console command in a game only warns that achievements will be disabled: one to get past it
        await command(inst, "/sc rcon.print('ready')")
        out = await command(inst, "/sc __Todo-List__ local ok, e = pcall(function() "
                            "local p = { name = 'otterplex' } "
                            "local a = todo.assemble_task({ title = 'Old task', task = 'from 19.15.2', assignee = 'otterplex' }, p) "
                            "todo.save_task_to_open_list(a, false) "
                            "local b = todo.assemble_task({ title = 'Old task two', task = 'second' }, p) "
                            "todo.save_task_to_open_list(b, false) "
                            "todo.save_subtask_to_task(a, 'player note') "
                            "return #storage.todo.open end) rcon.print(tostring(ok) .. ' ' .. tostring(e))")
        check("old: tasks made with 19.15.2's own functions", out.strip() == "true 2", repr(out))
        await command(inst, "/server-save todo-old")
        src = inst.dir / "saves" / "todo-old.zip"
        for _ in range(60):
            if src.exists() and src.stat().st_size > 0:
                break
            await asyncio.sleep(0.5)
        await asyncio.sleep(1)
        shutil.copy2(src, saved)
        await g.crew.close()
    finally:
        await asyncio.to_thread(inst.stop)


async def phase_new(k: int, saved: Path, patched: Path) -> None:
    inst = Instance(k, saved, extra_mods=[patched])
    print(f"starting instance {k} from the 19.15.2 save with {patched.name}", flush=True)
    await asyncio.to_thread(inst.start, 300)
    try:
        g = await Game.connect(inst.host, inst.rcon_port, inst.password, "serf")
        call = "remote.call('Todo-List', "
        check("version is 1", await rj(g, call + "'version')") == 1)

        tasks = await rj(g, call + "'get_tasks')")
        old = [t for t in tasks if t["title"].startswith("Old task")]
        check("existing save: the 19.15.2 tasks read back (no status, subtask without owner)",
              len(old) == 2 and old[0]["assignee"] == "otterplex" and not old[0].get("status")
              and [s["task"] for s in old[0]["subtasks"]] == ["player note"] and not old[0]["subtasks"][0].get("owner"),
              old)
        old_id = old[0]["id"]

        a1 = await rj(g, call + "'add_assignee', 'serf')")
        a2 = await rj(g, call + "'add_assignee', 'serf')")
        r1 = await rj(g, call + "'remove_assignee', 'serf')")
        r2 = await rj(g, call + "'remove_assignee', 'serf')")
        await rj(g, call + "'add_assignee', 'serf')")
        check("add_assignee is idempotent (one entry: removed once, then gone)", (a1, a2, r1, r2) == (True, True, True, False),
              (a1, a2, r1, r2))

        id1 = await rj(g, call + "'add_task', { title = 'Roboport grid', task = 'make a grid', assignee = 'serf', "
                                 "created_by = 'otterplex' })")
        id2 = await rj(g, call + "'add_task', { title = 'Stone to lava', assignee = 'serf' })")
        id3 = await rj(g, call + "'add_task', { task = 'Gleba labs\\nwith more lines', top = true })")
        tasks = await rj(g, call + "'get_tasks')")
        ids = [t["id"] for t in tasks]
        t1 = next((t for t in tasks if t["id"] == id1), {})
        t3 = next((t for t in tasks if t["id"] == id3), {})
        check("add_task: ids, top goes first, the rest in order, fields as given (title from the first line)",
              all(isinstance(x, int) for x in (id1, id2, id3)) and ids[0] == id3 and ids.index(id1) < ids.index(id2)
              and t1.get("assignee") == "serf" and t1.get("created_by") == "otterplex" and t1.get("task") == "make a grid"
              and t1.get("done") is False and t3.get("title") == "Gleba labs" and t3.get("created_by") == "script",
              (ids, t1, t3))

        u1 = await rj(g, call + f"'update_task', {id1}, {{ status = 'step 4 of 6', status_kind = 'progress' }})")
        t1 = next(t for t in await rj(g, call + "'get_tasks')") if t["id"] == id1)
        u2 = await rj(g, call + f"'update_task', {id1}, {{ status_kind = 'bogus', title = 'Roboport grid v2' }})")
        t1b = next(t for t in await rj(g, call + "'get_tasks')") if t["id"] == id1)
        u3 = await rj(g, call + f"'update_task', {id1}, {{ status = '', assignee = '' }})")
        t1c = next(t for t in await rj(g, call + "'get_tasks')") if t["id"] == id1)
        await rj(g, call + f"'update_task', {id1}, {{ assignee = 'serf' }})")
        check("update_task: status and kind; a bad kind clears it; '' clears status and unassigns",
              u1 is True and t1.get("status") == "step 4 of 6" and t1.get("status_kind") == "progress"
              and u2 is True and t1b.get("status_kind") is None and t1b.get("title") == "Roboport grid v2"
              and u3 is True and t1c.get("status") is None and t1c.get("assignee") is None, (t1, t1b, t1c))

        s1 = await rj(g, call + f"'set_subtasks', {old_id}, 'serf', {{ {{ task = 'find gaps', done = true }}, "
                                "{ task = 'ghost roboports', done = false } })")
        await rj(g, call + f"'set_subtasks', {old_id}, 'other', {{ {{ task = 'other mod step' }} }})")
        s2 = await rj(g, call + f"'set_subtasks', {old_id}, 'serf', {{ {{ task = 'find gaps', done = true }}, "
                                "{ task = 'ghost roboports', done = true }, { task = 'power them', done = false } })")
        s3 = await rj(g, call + f"'set_subtasks', {old_id}, 'serf', {{ {{ task = 'find gaps', done = true }}, "
                                "{ task = 'ghost roboports', done = true }, { task = 'power them', done = false } })")
        sub = next(t for t in await rj(g, call + "'get_tasks')") if t["id"] == old_id)["subtasks"]
        mine = [(s["task"], s["done"]) for s in sub if s.get("owner") == "serf"]
        check("set_subtasks: replaces only this owner's (the player's and another mod's stay); same list again is a no-op",
              s1 is True and s2 is True and s3 is True
              and sorted(mine) == sorted([("find gaps", True), ("ghost roboports", True), ("power them", False)])
              and any(s["task"] == "player note" and not s.get("owner") for s in sub)
              and any(s["task"] == "other mod step" and s.get("owner") == "other" for s in sub), sub)

        m1 = await rj(g, call + f"'mark_complete', {id1})")
        open_ids = [t["id"] for t in await rj(g, call + "'get_tasks')")]
        all_t = await rj(g, call + "'get_tasks', true)")
        m2 = await rj(g, call + f"'mark_complete', {id1})")
        o1 = await rj(g, call + f"'mark_open', {id1})")
        o2 = await rj(g, call + f"'mark_open', {id1})")
        open_after = [t["id"] for t in await rj(g, call + "'get_tasks')")]
        check("mark_complete moves it to done (get_tasks(true) has it, done=true); again is false; mark_open brings it back",
              m1 is True and id1 not in open_ids and any(t["id"] == id1 and t["done"] is True for t in all_t)
              and m2 is False and o1 is True and o2 is False and id1 in open_after, (m1, m2, o1, o2))

        one = await rj(g, call + f"'get_task', {id1})")
        none = await rj(g, call + "'get_task', 99999)")
        check("get_task: one task by id (open or done), nil for an unknown id",
              isinstance(one, dict) and one.get("id") == id1 and none is None, (one, none))
        ev_out = await ev(g, """storage.n_changed = 0
local id = remote.call('Todo-List', 'get_event_ids').on_tasks_changed
script.on_event(id, function() storage.n_changed = storage.n_changed + 1 end)
local t = remote.call('Todo-List', 'get_tasks', false)[1].id
remote.call('Todo-List', 'update_task', t, { status = 'event test 1' })
local a = storage.n_changed
remote.call('Todo-List', 'update_task', t, { status = 'event test 1' })
local b = storage.n_changed
script.on_event(id, function()
  storage.n_changed = storage.n_changed + 1
  remote.call('Todo-List', 'update_task', t, { status = 'from a handler ' .. storage.n_changed })
end)
remote.call('Todo-List', 'update_task', t, { status = 'event test 2' })
local c = storage.n_changed
script.on_event(id, nil)
return type(id) .. ' ' .. a .. ' ' .. b .. ' ' .. c""")
        check("on_tasks_changed: raised once per change, not for a no-op update, and not again while its handler "
              "updates a task", ev_out == "number 1 1 2", ev_out)

        junk = await ev(g, """local r = {}
local function try(name, f) local ok, v = pcall(f) r[#r + 1] = name .. '=' .. (ok and tostring(v) or ('ERROR ' .. tostring(v))) end
try('update_str', function() return remote.call('Todo-List', 'update_task', 'x', {}) end)
try('update_999', function() return remote.call('Todo-List', 'update_task', 999, { status = 'x' }) end)
try('update_nil_fields', function() return remote.call('Todo-List', 'update_task', 1, nil) end)
try('sub_no_owner', function() return remote.call('Todo-List', 'set_subtasks', 1, nil, {}) end)
try('sub_junk_list', function() return remote.call('Todo-List', 'set_subtasks', 1, 'serf', 'junk') end)
try('add_str', function() return remote.call('Todo-List', 'add_task', 'junk') end)
try('add_empty', function() return remote.call('Todo-List', 'add_task', {}) end)
try('complete_nil', function() return remote.call('Todo-List', 'mark_complete', nil) end)
try('open_str', function() return remote.call('Todo-List', 'mark_open', 'x') end)
try('assignee_num', function() return remote.call('Todo-List', 'add_assignee', 5) end)
try('get_yes', function() return #remote.call('Todo-List', 'get_tasks', 'yes') end)
return table.concat(r, ' ')""")
        check("junk inputs return false/nil, never an error", "ERROR" not in junk and junk.startswith(
            "update_str=false update_999=false update_nil_fields=false sub_no_owner=false sub_junk_list=false "
            "add_str=nil add_empty=nil complete_nil=false open_str=false assignee_num=false get_yes="), junk)
        await g.crew.close()
    finally:
        await asyncio.to_thread(inst.stop)


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zip", required=True, help="the patched Todo-List zip")
    ap.add_argument("--instance", type=int, default=62)
    a = ap.parse_args()
    if not 60 <= a.instance <= 69:
        ap.error("--instance must be 60..69")
    patched = Path(a.zip).resolve()
    tmp = Path(tempfile.mkdtemp(prefix="todo-", dir=str(ROOT / "bench" / "runs")))
    saved = tmp / "todo-old-save.zip"
    await phase_old(a.instance, saved)
    if saved.exists():
        await phase_new(a.instance, saved, patched)
    else:
        check("old: the 19.15.2 world was saved", False)
    print(f"\n{'ALL OK' if not FAILS else str(len(FAILS)) + ' FAILED: ' + ', '.join(FAILS)}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
