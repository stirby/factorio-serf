"""Items a job needs come from storage: `find` with an item name lists where it's stored, `fetch` walks there and
takes it (then hand-crafts the rest), and belt lines fetch or craft every piece their route needs. Belt lines say
whether each end joined a belt, and an off-by-one start next to a line end continues that line. No model calls.

  .venv/bin/python tests/test_items.py [instance=41]
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from crew.game import GameLink  # noqa: E402
from crew.tools import t_find  # noqa: E402

FAILS: list[str] = []


def check(cond: bool, what: str) -> None:
    print(("PASS " if cond else "FAIL ") + what, flush=True)
    if not cond:
        FAILS.append(what)


# Far from the stage's base, so the only storage within 400 tiles is what this sets up.
SETUP = """local s, f = game.surfaces.nauvis, game.forces.player
local X, Y = %d, %d
s.request_to_generate_chunks({X + 30, Y + 30}, 3) s.force_generate_chunk_requests()
local t = {}
for x = X-4, X+64 do for y = Y-4, Y+64 do t[#t+1] = {name='grass-1', position={x,y}} end end
s.set_tiles(t)
for _, e in pairs(s.find_entities_filtered{area={{X-4,Y-4},{X+64,Y+64}}}) do
  if e.type ~= 'character' then e.destroy() end end
local a = s.create_entity{name='wooden-chest', position={X+10.5, Y+0.5}, force=f} a.insert{name='copper-plate', count=30}
local b = s.create_entity{name='wooden-chest', position={X+25.5, Y+0.5}, force=f} b.insert{name='copper-plate', count=50}
b.insert{name='stone-furnace', count=3}
local fu = s.create_entity{name='stone-furnace', position={X+30, Y+4}, force=f}
fu.get_output_inventory().insert{name='iron-plate', count=12}
s.create_entity{name='stone-furnace', position={X+34, Y+4}, force=f}
-- the underground stock for the first line test, and a wall of belts that line has to pass under
local u = s.create_entity{name='wooden-chest', position={X+40.5, Y+0.5}, force=f} u.insert{name='underground-belt', count=2}
for x = X+2, X+12 do s.create_entity{name='transport-belt', position={x+0.5, Y+14.5}, direction=defines.direction.east, force=f} end
for x = X+22, X+32 do s.create_entity{name='transport-belt', position={x+0.5, Y+14.5}, direction=defines.direction.east, force=f} end
-- a dangling line end (east, ends at X+6), a target belt facing north with a chest beside it, a lone belt
for x = X+2, X+6 do s.create_entity{name='transport-belt', position={x+0.5, Y+30.5}, direction=defines.direction.east, force=f} end
s.create_entity{name='transport-belt', position={X+30.5, Y+40.5}, direction=defines.direction.north, force=f}
s.create_entity{name='wooden-chest', position={X+29.5, Y+40.5}, force=f}
s.create_entity{name='transport-belt', position={X+50.5, Y+50.5}, direction=defines.direction.north, force=f}
s.create_entity{name='transport-belt', position={X+2.5, Y+56.5}, direction=defines.direction.east, force=f}
local c = storage.agents['t-items'].char
c.teleport({X, Y + 2})
c.get_main_inventory().clear()
return true"""

COUNT = """local c = storage.agents['t-items'].char
return {copper = c.get_item_count('copper-plate'), iron = c.get_item_count('iron-plate'),
  gears = c.get_item_count('iron-gear-wheel'), ug = c.get_item_count('underground-belt')}"""


async def main(k: int) -> None:
    from instance import Instance
    with Instance(k, "stage-s3-steel-oil-ready") as inst:
        link = GameLink(inst.host, inst.rcon_port, inst.password, client="t-items")
        await link.start()
        await link.call("spawn", name="t-items", client="t-items", starter_kit=False)
        X, Y = 900, -900
        await link.call("eval", code=SETUP % (X, Y))
        agent = SimpleNamespace(link=link, name="t-items")

        async def act(*actions, timeout=90):
            ids = (await link.call("act", agent="t-items", actions=list(actions)))["job_ids"]
            return [await asyncio.wait_for(link.job_future(i), timeout) for i in ids]

        async def inv() -> dict:
            return (await link.call("eval", code=COUNT))["result"]

        # find: an item name lists storage, nearest first, with counts and a total
        f1 = await t_find(agent, {"name": "copper-plate"})
        print(f1)
        check("30 in wooden-chest" in f1 and f1.index("30 in") < f1.index("50 in") and "total within 400 tiles: 80" in f1,
              "find copper-plate lists both chests, nearest first, with the total")
        f2 = await t_find(agent, {"name": "iron-plate"})
        check("12 in stone-furnace" in f2, f"find iron-plate counts a furnace's finished plates: {f2}")
        f3 = await t_find(agent, {"name": "stone-furnace"})
        print(f3)
        check(f3.startswith("in the world:") and "3 in wooden-chest" in f3,
              "find stone-furnace gives both the placed furnaces and the stored ones")
        f4 = await t_find(agent, {"name": "steel-plate"})
        check("none in any chest" in f4, f"an item nobody stores says so: {f4}")
        f5 = await t_find(agent, {"name": "tree"})
        check("found" in f5, f"a non-item name still finds entities: {f5[:80]}")

        # fetch: walk to the stocks and take what's needed, across two chests
        r1, = await act({"op": "fetch", "item": "copper-plate", "count": 60})
        have = await inv()
        print(r1["msg"])
        check(r1["ok"] and have["copper"] == 60 and "30 copper-plate from wooden-chest" in r1["msg"],
              f"fetch 60 copper takes 30 + 30 from two chests: {have}")
        r2, = await act({"op": "fetch", "item": "iron-plate", "count": 10})
        check(r2["ok"] and (await inv())["iron"] == 10, f"fetch from a furnace's output: {r2['msg']}")
        r3, = await act({"op": "fetch", "item": "iron-gear-wheel", "count": 2})
        check(r3["ok"] and "crafted" in r3["msg"] and (await inv())["gears"] == 2,
              f"nothing stored: crafted from what's carried: {r3['msg']}")
        r4, = await act({"op": "fetch", "item": "steel-plate", "count": 5})
        check(not r4["ok"] and "can't hand-craft" in r4["msg"], f"can't fetch or craft: says so: {r4['msg']}")
        r5, = await act({"op": "fetch", "item": "copper-plate", "count": 5})
        check(r5["ok"] and "already have" in r5["msg"], f"already carried: nothing to do: {r5['msg']}")

        # A line that needs undergrounds that are only in a chest: fetched, not a failure.
        await link.call("eval", code="local c = storage.agents['t-items'].char c.get_main_inventory().clear() "
                                     "c.insert{name='transport-belt', count=60}")
        r6, = await act({"op": "connect", "item": "transport-belt", "from": [X + 7.5, Y + 10.5],
                         "to": [X + 7.5, Y + 18.5]}, timeout=120)
        print(r6["msg"])
        check(r6["ok"] and "underground-belt from wooden-chest" in r6["msg"],
              "a line needing undergrounds fetches them from the chest that has them")
        # ...and with none stored, crafts them (the chest's are used up above).
        await link.call("eval", code="storage.agents['t-items'].char.insert{name='iron-plate', count=40}")
        r7, = await act({"op": "connect", "item": "transport-belt", "from": [X + 27.5, Y + 10.5],
                         "to": [X + 27.5, Y + 18.5]}, timeout=120)
        check(r7["ok"] and "crafted" in r7["msg"] and "underground-belt" in r7["msg"],
              f"with none in storage, the undergrounds get crafted: {r7['msg']}")
        # ...and belts too: no belts carried, so it fetches belts? None stored: crafts them from plates.
        await link.call("eval", code="local c = storage.agents['t-items'].char c.get_main_inventory().clear() "
                                     "c.insert{name='iron-plate', count=20}")
        r8, = await act({"op": "connect", "item": "transport-belt", "from": [X + 40.5, Y + 20.5],
                         "to": [X + 46.5, Y + 20.5]}, timeout=120)
        check(r8["ok"] and "crafted" in r8["msg"], f"no belts carried: crafted from plates: {r8['msg']}")

        # Joined ends. Start on the tile beside a dangling line end (off by one): continues that line.
        await link.call("eval", code="storage.agents['t-items'].char.insert{name='transport-belt', count=100}")
        r9, = await act({"op": "connect", "item": "transport-belt", "from": [X + 6.5, Y + 31.5],
                         "to": [X + 6.5, Y + 36.5]}, timeout=90)
        print(r9["msg"])
        check(r9["ok"] and f"start: continues the belt at {X + 6.5},{Y + 30.5}" in r9["msg"],
              "a start one tile off a dangling line end continues it")
        # End given as a blocked tile (the chest) beside one belt: feeds that belt.
        r10, = await act({"op": "connect", "item": "transport-belt", "from": [X + 20.5, Y + 44.5],
                          "to": [X + 29.5, Y + 40.5]}, timeout=90)
        print(r10["msg"])
        check(r10["ok"] and f"end: feeds the transport-belt at {X + 30.5},{Y + 40.5}" in r10["msg"],
              "an end on a blocked tile next to one belt feeds that belt")
        # End on a free tile a tile away from a belt: not joined, and says where the belt is.
        r11, = await act({"op": "connect", "item": "transport-belt", "from": [X + 44.5, Y + 50.5],
                          "to": [X + 49.5, Y + 50.5], "end_direction": "north"}, timeout=90)
        print(r11["msg"])
        check(r11["ok"] and "end: not joined, nearest belt 1 tile(s) away" in r11["msg"],
              "an end beside a belt on a free tile reports it didn't join")
        # Integer corner coordinates name the tile: x,y on a line's last belt continues it.
        r12, = await act({"op": "connect", "item": "transport-belt", "from": [X + 2, Y + 56],
                          "to": [X + 8.5, Y + 60.5]}, timeout=90)
        check(r12["ok"] and f"start: continues the belt at {X + 2.5},{Y + 56.5}" in r12["msg"],
              f"a start at the tile's corner coordinates continues the belt there: {r12['msg']}")
    print("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 41))
