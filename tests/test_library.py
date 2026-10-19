"""The design library: copy a working build into it, stamp it elsewhere (rotated), and /serf learn. No model calls.

  .venv/bin/python tests/test_library.py [instance=9]
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
os.environ["SERF_DESIGNS_DIR"] = tempfile.mkdtemp(prefix="serf-designs-")

from crew import blueprint_lib  # noqa: E402
from crew import config as config_mod  # noqa: E402
from crew.controller import Controller  # noqa: E402
from crew.orchestrator import Orchestrator  # noqa: E402

FAILS: list[str] = []


def check(cond: bool, what: str) -> None:
    print(("PASS " if cond else "FAIL ") + what, flush=True)
    if not cond:
        FAILS.append(what)


# A small build: belt -> inserter -> assembler (gears) -> inserter -> chest, plus a pole. 5 wide, 7 tall.
BUILD = """local s, f = game.surfaces.nauvis, game.forces.player
local X, Y = %d, %d
for _, e in pairs(s.find_entities_filtered{area={{X-2,Y-2},{X+8,Y+10}}, type={'tree','simple-entity'}}) do e.destroy() end
local made = {}
local function put(n, x, y, d) local e = s.create_entity{name=n, position={X+x, Y+y}, direction=d, force=f}
  made[#made+1] = e and n or ('FAILED ' .. n) return e end
for i = 0, 4 do put('transport-belt', i + 0.5, 0.5, defines.direction.east) end
put('inserter', 2.5, 1.5, defines.direction.north)
put('assembling-machine-1', 2.5, 3.5).set_recipe('iron-gear-wheel')
put('inserter', 2.5, 5.5, defines.direction.north)
put('wooden-chest', 2.5, 6.5)
put('small-electric-pole', 0.5, 3.5)
return made"""

GHOSTS = """local s = game.surfaces.nauvis local out = {}
for _, g in pairs(s.find_entities_filtered{area={{%d,%d},{%d,%d}}, name='entity-ghost'}) do
  local r = g.ghost_type == 'assembling-machine' and g.get_recipe() or nil
  out[#out+1] = {name = g.ghost_name, x = g.position.x, y = g.position.y, d = g.direction, recipe = r and r.name}
end return out"""

BOOK = """local inv = game.create_inventory(1)
storage.test_book = inv
inv[1].set_stack{name = 'blueprint-book'}
inv[1].label = 'My book'
local b = inv[1].get_inventory(defines.inventory.item_main)
b.insert{name = 'blueprint'} b.insert{name = 'blueprint'} b.insert{name = 'blueprint'}
b[1].import_stack([[%s]]) b[1].label = 'Gear cell v2'
b[2].import_stack([[%s]])
b[3].import_stack(b[1].export_stack()) b[3].label = 'Red Science 5'
return remote.call('factorio-serf', 'stack_designs', inv[1], 'x')"""


async def main(k: int) -> None:
    from instance import Instance
    with Instance(k, "stage-s3-steel-oil-ready") as inst:
        cfg = config_mod.load(None, {"join": True})
        cfg.server.host, cfg.server.rcon_port, cfg.server.rcon_password = inst.host, inst.rcon_port, inst.password
        cfg.state_dir = Path(tempfile.mkdtemp(prefix="serf-state-"))
        orch = Orchestrator(cfg)
        await orch.start()
        call = orch.link.call

        bx, by = 120, -140
        made = (await call("eval", code=BUILD % (bx, by)))["result"]
        check(not any(str(m).startswith("FAILED") for m in made), f"test build placed: {made}")

        # copy -> blueprint_info -> library
        d = await call("copy", x1=bx - 1, y1=by - 1, x2=bx + 6, y2=by + 8)
        info = await call("blueprint_info", string=d["string"])
        check(info["entities"] == 10, f"blueprint_info sees the 10 entities: {info['by_name']}")
        check(info["size"] == [5, 7], f"footprint is the entities' extent, not the copy area: {info['size']}")
        blueprint_lib.save_learned("gear-cell", d["string"], info, "gears from a belt of iron", {"by": "test"})
        check("gear-cell" in blueprint_lib.names() and "[yours" in blueprint_lib.summary_text(),
              "it's listed in the library, marked as yours")

        # stamp it rotated (east) through the controller, like build kind=stamp does
        sx, sy = 140, -140
        ctl = Controller(orch.link, "nobody", stop=lambda: False, deadline=__import__("time").time() + 60)
        order = SimpleNamespace(plan={"kind": "stamp", "name": "gear-cell", "x": sx, "y": sy, "rotation": 90},
                                zone=None, laid=False, state_dir=cfg.state_dir)
        note = await ctl.lay_plan(order)
        st = blueprint_lib.stamp("gear-cell", sx, sy, 90)
        (x1, y1), (x2, y2) = st["bbox"]
        check(st["size"] == [7, 5], f"rotated footprint 7x5: {st['size']}")
        g = (await call("eval", code=GHOSTS % (x1 - 1, y1 - 1, x2 + 1, y2 + 1)))["result"] or []
        check(len(g) == 10, f"stamp laid all 10 ghosts inside its footprint ({note}; found {len(g)})")
        asm = [e for e in g if e["name"] == "assembling-machine-1"]
        check(bool(asm) and asm[0]["recipe"] == "iron-gear-wheel", f"the recipe came along: {asm}")
        belts = {e["d"] for e in g if e["name"] == "transport-belt"}
        check(belts == {8}, f"belts turned east -> south (direction 8): {belts}")
        check(blueprint_lib.get_design("gear-cell").get("uses") == 1, "the build is counted")

        # /serf learn: the event a player's command makes, handled by the orchestrator
        await call("eval", code="storage.feed_seq = storage.feed_seq + 1 table.insert(storage.feed, {seq = "
                                "storage.feed_seq, kind = 'event', data = {type = 'learn', name = 'their-cell', "
                                f"player = 'otterplex', string = [[{d['string']}]]}}, to = 'rcon'}})")
        for _ in range(20):
            if "their-cell" in blueprint_lib.names():
                break
            await asyncio.sleep(0.5)
        check("their-cell" in blueprint_lib.names(), "/serf learn puts the player's blueprint in the library")
        if "their-cell" in blueprint_lib.names():
            dsg = blueprint_lib.get_design("their-cell")
            check(dsg["learned"]["by"] == "otterplex" and "taught by otterplex" in dsg["description"],
                  f"credited to the player: {dsg['description'][:80]}")
        # A blueprint book (the Teach serf shortcut / /serf learn with a book in hand): every blueprint goes in,
        # named from its label; one that clashes with a built-in gets "-yours".
        book = (await call("eval", code=BOOK % (d["string"], d["string"])))["result"]
        names = [x["name"] for x in book or []]
        check(names == ["gear-cell-v2", "my-book-2", "red-science-5"], f"book read: designs named from labels {names}")
        await call("eval", code="storage.feed_seq = storage.feed_seq + 1 table.insert(storage.feed, {seq = "
                                "storage.feed_seq, kind = 'event', data = {type = 'learn', book = 'My book', "
                                "player = 'otterplex', designs = remote.call('factorio-serf', 'stack_designs', "
                                "storage.test_book[1], 'x')}, to = 'rcon'})")
        want = {"gear-cell-v2", "my-book-2", "red-science-5-yours"}
        for _ in range(30):
            if want <= set(blueprint_lib.names()):
                break
            await asyncio.sleep(0.5)
        check(want <= set(blueprint_lib.names()), f"the whole book is in the library: {sorted(blueprint_lib.names())}")
        for n in want & set(blueprint_lib.names()):
            blueprint_lib.forget(n)
        bad = blueprint_lib.names()
        try:
            blueprint_lib.save_learned("red-science-5", d["string"], info, "x", {})
            check(False, "can't overwrite a built-in")
        except ValueError:
            check(True, "can't overwrite a built-in")
        blueprint_lib.forget("gear-cell")
        check("gear-cell" not in blueprint_lib.names() and len(bad) == len(blueprint_lib.names()) + 1,
              "forget drops it (moved aside)")
        await orch.stop()
    print("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 9))
