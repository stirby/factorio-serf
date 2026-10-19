"""`place` clears trees and rocks in the way (with mining time, wood/stone to the inventory) and treats "the same
entity is already there" as done. No model calls.

  .venv/bin/python tests/test_place.py [instance=9]
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from crew.game import GameLink  # noqa: E402

FAILS: list[str] = []


def check(cond: bool, what: str) -> None:
    print(("PASS " if cond else "FAIL ") + what, flush=True)
    if not cond:
        FAILS.append(what)


SETUP = """local s, f = game.surfaces.nauvis, game.forces.player
local X, Y = %d, %d
for _, e in pairs(s.find_entities_filtered{area={{X-6,Y-6},{X+12,Y+6}}}) do
  if e.type ~= 'character' then e.destroy() end end
s.set_tiles((function() local t = {} for x = X-6, X+12 do for y = Y-6, Y+6 do
  t[#t+1] = {name='grass-1', position={x,y}} end end return t end)())
local tree = s.create_entity{name='tree-01', position={X+2.3, Y+0.6}}
local rock = s.create_entity{name='big-rock', position={X+5.5, Y+0.5}}
s.create_entity{name='wooden-chest', position={X+8.5, Y+0.5}, force=f}
local c = storage.agents['t-place'].char
c.teleport({X, Y + 3})
c.insert{name='wooden-chest', count=10} c.insert{name='stone-furnace', count=5}
return {tree = tree and tree.valid, rock = rock and rock.valid, wood = c.get_item_count('wood'),
  stone = c.get_item_count('stone')}"""

POLES = """local s, f = game.surfaces.nauvis, game.forces.player
local X, Y = %d, %d
local t = {}
for x = X-2, X+44 do for y = Y-12, Y+12 do
  t[#t+1] = {name = (x >= X+18 and x <= X+21) and 'water' or 'grass-1', position={x,y}} end end
s.set_tiles(t)
for _, e in pairs(s.find_entities_filtered{area={{X-2,Y-12},{X+44,Y+12}}}) do
  if e.type ~= 'character' then e.destroy() end end
for y = Y-12, Y+12 do s.create_entity{name='wooden-chest', position={X+10.5, y+0.5}, force=f} end
s.create_entity{name='small-electric-pole', position={X+0.5, Y+0.5}, force=f}
s.create_entity{name='electric-energy-interface', position={X+0, Y+3}, force=f}
local c = storage.agents['t-place'].char
c.teleport({X+2, Y+2}) c.insert{name='small-electric-pole', count=20}"""

NET = """local s = game.surfaces.nauvis local X, Y = %d, %d
local function net(x) local p = s.find_entities_filtered{position={x, Y+0.5}, radius=1, type='electric-pole'}[1]
  return p and p.electric_network_id end
return {start = net(X+0.5), ['end'] = net(X+40.5),
  poles = s.count_entities_filtered{area={{X+1,Y-12},{X+44,Y+12}}, type='electric-pole'}}"""


async def main(k: int) -> None:
    from instance import Instance
    with Instance(k, "stage-s3-steel-oil-ready") as inst:
        link = GameLink(inst.host, inst.rcon_port, inst.password, client="t-place")
        await link.start()
        await link.call("spawn", name="t-place", client="t-place", starter_kit=False)
        x, y = 300, 300
        before = (await link.call("eval", code=SETUP % (x, y)))["result"]
        check(before["tree"] and before["rock"], f"tree and rock in place: {before}")

        async def act(*actions, timeout=60):
            ids = (await link.call("act", agent="t-place", actions=list(actions)))["job_ids"]
            return [await asyncio.wait_for(link.job_future(i), timeout) for i in ids]

        t0 = time.time()
        r1, = await act({"op": "place", "name": "wooden-chest", "x": x + 2.5, "y": y + 0.5})
        check(r1["ok"] and "cleared" in r1["msg"], f"chest placed over a tree: {r1['msg']}")
        r2, = await act({"op": "place", "name": "stone-furnace", "x": x + 6, "y": y + 1})
        took = time.time() - t0
        check(r2["ok"] and "cleared" in r2["msg"], f"furnace placed over a rock: {r2['msg']}")
        check(took > 1.0, f"clearing took mining time, not instant ({took:.1f}s for both)")
        r3, = await act({"op": "place", "name": "wooden-chest", "x": x + 8.5, "y": y + 0.5})
        check(r3["ok"] and "already" in r3["msg"], f"same entity already there counts as done: {r3['msg']}")
        r4, = await act({"op": "place", "name": "stone-furnace", "x": x + 8.5, "y": y + 0.5})
        check(not r4["ok"] and "blocked by wooden-chest" in r4["msg"], f"a real blocker still fails: {r4['msg']}")
        after = (await link.call("eval", code="local c = storage.agents['t-place'].char return {wood = "
                                               "c.get_item_count('wood'), stone = c.get_item_count('stone'), "
                                               "chests = c.get_item_count('wooden-chest')}"))["result"]
        check(after["wood"] > before["wood"] and after["stone"] > before["stone"],
              f"wood and stone went to the inventory: {before} -> {after}")
        check(after["chests"] == 9, f"only one chest was used (the 'already there' one cost nothing): {after}")

        # Pole lines hop by wire reach: across a 4-wide river and a row of chests, from an existing pole.
        py = y + 20
        await link.call("eval", code=POLES % (x, py))
        r5, = await act({"op": "connect", "item": "small-electric-pole", "from": [x + 0.5, py + 0.5],
                         "to": [x + 40.5, py + 0.5]}, timeout=120)
        net = (await link.call("eval", code=NET % (x, py)))["result"]
        check(r5["ok"], f"pole line placed: {r5['msg']}")
        check(net["start"] is not None and net["start"] == net["end"],
              f"the far end is on the start pole's network: {net}")
        check(net["poles"] <= 8, f"poles spaced by reach, not every few tiles ({net['poles']} for 40 tiles)")
    print("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 9))
