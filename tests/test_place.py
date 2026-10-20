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

UNDER = """local s, f = game.surfaces.nauvis, game.forces.player
local X, Y = %d, %d
local t = {}
for x = X-2, X+24 do for y = Y-40, Y+40 do
  t[#t+1] = {name = (x >= X+9 and x <= X+11 and y >= Y+3) and 'water' or 'grass-1', position={x,y}} end end
s.set_tiles(t)
for _, e in pairs(s.find_entities_filtered{area={{X-2,Y-40},{X+24,Y+40}}}) do
  if e.type ~= 'character' then e.destroy() end end
for y = Y-40, Y+2 do s.create_entity{name='transport-belt', position={X+10.5, y+0.5}, direction=defines.direction.south, force=f} end
local c = storage.agents['t-place'].char
c.teleport({X+2, Y+2})
for _, it in pairs{'transport-belt', 'underground-belt', 'pipe', 'pipe-to-ground'} do c.insert{name=it, count=40} end"""

FLOW = """local s = game.surfaces.nauvis local X, Y = %d, %d
local first = s.find_entity('transport-belt', {X+0.5, Y+0.5})
first.get_transport_line(1).insert_at_back({name='iron-plate', count=1})
first.get_transport_line(2).insert_at_back({name='iron-plate', count=1})
local p0 = s.find_entity('pipe', {X+0.5, Y+6.5}) if p0 then p0.fluidbox[1] = {name='water', amount=100} end
return {}"""

ENDS = """local s = game.surfaces.nauvis local X, Y = %d, %d
local last = s.find_entity('transport-belt', {X+20.5, Y+0.5})
local pl = s.find_entity('pipe', {X+20.5, Y+6.5})
local w = pl and pl.fluidbox[1]
return {plates_at_end = last and last.get_item_count('iron-plate') or -1, water_at_end = w and w.amount or 0,
  crossing_intact = s.count_entities_filtered{area={{X+10,Y-40},{X+11,Y+3}}, name='transport-belt'} == 43,
  ug = (function() local t = {} for _, u in pairs(s.find_entities_filtered{area={{X,Y},{X+21,Y+1}}, name='underground-belt'}) do
    t[#t+1] = u.belt_to_ground_type .. '@' .. u.position.x .. '/' .. u.direction .. (u.neighbours and ' paired' or ' unpaired') end
    return table.concat(t, ' ') end)()}"""

COUNT = """local c = storage.agents['t-place'].char
return {belt = c.get_item_count('transport-belt'), fast = c.get_item_count('fast-transport-belt')}"""

LEGS = """local s, f = game.surfaces.nauvis, game.forces.player
local X, Y = %d, %d
local t = {}
for x = X-2, X+40 do for y = Y-4, Y+40 do t[#t+1] = {name='grass-1', position={x,y}} end end
s.set_tiles(t)
for _, e in pairs(s.find_entities_filtered{area={{X-2,Y-4},{X+40,Y+40}}}) do
  if e.type ~= 'character' then e.destroy() end end
-- a main line running north at x=X+20, and a lone belt facing west at (X+30, Y+30)
for y = Y-3, Y+20 do s.create_entity{name='transport-belt', position={X+20.5, y+0.5}, direction=defines.direction.north, force=f} end
s.create_entity{name='transport-belt', position={X+30.5, Y+30.5}, direction=defines.direction.west, force=f}
-- a wall of belts to cross, for the underground test
for x = X+2, X+12 do s.create_entity{name='transport-belt', position={x+0.5, Y+34.5}, direction=defines.direction.east, force=f} end
local c = storage.agents['t-place'].char
c.teleport({X+2, Y+2})
c.remove_item{name='underground-belt', count=1000}
c.insert{name='transport-belt', count=100} c.insert{name='iron-plate', count=40}"""

LEGS_CHECK = """local s = game.surfaces.nauvis local X, Y = %d, %d
local function dir(x, y) local e = s.find_entities_filtered{position={x, y}, radius=0.3, type='transport-belt'}[1]
  return e and e.direction end
local main = 0
for y = Y-3, Y+9 do local e = s.find_entity('transport-belt', {X+20.5, y+0.5})
  if e then main = main + e.get_item_count('iron-plate') end end
return {corner = dir(X+10.5, Y+0.5), main_items = main, before_target = dir(X+19.5, Y+10.5),
  on_main = s.find_entity('transport-belt', {X+20.5, Y+10.5}).direction,
  head_on = dir(X+29.5, Y+30.5) == defines.direction.east}"""

POND = """local s = game.surfaces.nauvis local X, Y = %d, %d
local t = {} for x = X+4, X+13 do for y = Y, Y+9 do t[#t+1] = {name='water', position={x,y}} end end
s.set_tiles(t) return {X+9, Y+5}"""


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
        spot = r4["msg"].split("nearest free spot: ")[-1].split(",") if "nearest free spot" in r4["msg"] else ["0.5"]
        check(float(spot[0]) % 1 == 0, f"and names the nearest free spot, on the 2x2 grid: {spot}")
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

        # Belts go under a crossing belt and pipes under a river instead of failing or detouring.
        uy = y + 60
        await link.call("eval", code=UNDER % (x, uy))
        r6, = await act({"op": "connect", "item": "transport-belt", "from": [x + 0.5, uy + 0.5],
                         "to": [x + 20.5, uy + 0.5], "end_direction": "east"}, timeout=120)
        check(r6["ok"] and "underground-belt" in r6["msg"], f"belt line passes under the crossing belt: {r6['msg']}")
        r7, = await act({"op": "connect", "item": "pipe", "from": [x + 0.5, uy + 6.5], "to": [x + 20.5, uy + 6.5]},
                        timeout=120)
        check(r7["ok"] and "pipe-to-ground" in r7["msg"], f"pipe passes under the river: {r7['msg']}")
        await link.call("eval", code=FLOW % (x, uy))
        await asyncio.sleep(16)  # 20 tiles at 1.875 tiles/s
        flow = (await link.call("eval", code=ENDS % (x, uy)))["result"]
        check(flow["plates_at_end"] > 0, f"plates put on the first belt reach the far end: {flow}")
        check(flow["water_at_end"] > 0, f"water put in the first pipe reaches the far end: {flow}")
        check(flow["crossing_intact"], f"the crossing belt was left alone: {flow}")

        # Placing over what's there works like a player's click: rotate the same thing, upgrade within its family.
        await link.call("eval", code="local c = storage.agents['t-place'].char c.insert{name='fast-transport-belt', count=5}")
        bx, by = x + 15.5, uy - 5.5
        await act({"op": "place", "name": "transport-belt", "x": bx, "y": by, "direction": "north"})
        r8, = await act({"op": "place", "name": "transport-belt", "x": bx, "y": by, "direction": "east"})
        check(r8["ok"] and "turned" in r8["msg"], f"same belt, other direction: rotated: {r8['msg']}")
        before = (await link.call("eval", code=COUNT))["result"]
        r9, = await act({"op": "place", "name": "fast-transport-belt", "x": bx, "y": by, "direction": "east"})
        after = (await link.call("eval", code=COUNT))["result"]
        check(r9["ok"] and "replaced" in r9["msg"], f"yellow -> red belt: fast-replaced: {r9['msg']}")
        check(after["belt"] == before["belt"] + 1, f"the old belt went back to the inventory: {before} -> {after}")

        # A line built in legs: the next leg starts on the last belt (turning it), the last leg feeds into a belt
        # that's there (from the side, not head-on), and missing undergrounds get crafted.
        ly = y + 130
        await link.call("eval", code=LEGS % (x, ly))
        r16, = await act({"op": "connect", "item": "transport-belt", "from": [x + 0.5, ly + 0.5],
                          "to": [x + 10.5, ly + 0.5]}, timeout=90)
        r17, = await act({"op": "connect", "item": "transport-belt", "from": [x + 10.5, ly + 0.5],
                          "to": [x + 10.5, ly + 10.5]}, timeout=90)
        check(r17["ok"], f"second leg starts on the first leg's last belt: {r17['msg']}")
        r18, = await act({"op": "connect", "item": "transport-belt", "from": [x + 10.5, ly + 10.5],
                          "to": [x + 20.5, ly + 10.5]}, timeout=90)
        check(r18["ok"] and "feeding" in r18["msg"], f"last leg ends into the main line: {r18['msg']}")
        r19, = await act({"op": "connect", "item": "transport-belt", "from": [x + 24.5, ly + 30.5],
                          "to": [x + 30.5, ly + 30.5]}, timeout=90)
        r20, = await act({"op": "connect", "item": "transport-belt", "from": [x + 7.5, ly + 31.5],
                          "to": [x + 7.5, ly + 37.5]}, timeout=90)
        check(r20["ok"] and "crafted" in r20["msg"], f"missing undergrounds get hand-crafted: {r20['msg']}")
        await link.call("eval", code=f"local e = game.surfaces.nauvis.find_entity('transport-belt', {{{x + 0.5}, {ly + 0.5}}}) "
                                     "e.get_transport_line(1).insert_at_back({name='iron-plate', count=1}) "
                                     "e.get_transport_line(2).insert_at_back({name='iron-plate', count=1})")
        await asyncio.sleep(20)  # ~31 tiles at 1.875 tiles/s
        legs = (await link.call("eval", code=LEGS_CHECK % (x, ly)))["result"]
        check(legs["corner"] == 8, f"the corner belt turned south: {legs}")
        check(legs["before_target"] == 4 and legs["on_main"] == 0, f"the last belt points into the main line, which is untouched: {legs}")
        check(legs["main_items"] > 0, f"plates from the first leg reach the main line: {legs}")
        check(r19["ok"] and not legs["head_on"], f"a belt facing the line isn't joined head-on: {r19['msg']} {legs}")

        # move to a spot nobody can stand on (the middle of a pond): walk to the nearest shore instead of "no path".
        pond = (await link.call("eval", code=POND % (x, uy + 20)))["result"]
        r10, = await act({"op": "move", "x": pond[0], "y": pond[1]}, timeout=90)
        check(r10["ok"], f"move into a pond ends at its shore: {r10['msg']}")

        r11, = await act({"op": "take", "x": x + 8.5, "y": y + 0.5, "item": "iron-plate"})
        check(not r11["ok"] and "it holds" in r11["msg"], f"take says what the chest holds: {r11['msg']}")

        await link.call("eval", code=f"local a = game.surfaces.nauvis.create_entity{{name='assembling-machine-1', "
                                     f"position={{{x + 3.5}, {y - 3.5}}}, force='player'}} a.set_recipe('iron-gear-wheel') "
                                     "storage.agents['t-place'].char.insert{name='copper-plate', count=5}")
        r12, = await act({"op": "insert", "x": x + 3.5, "y": y - 3.5, "item": "copper-plate"})
        check(not r12["ok"] and "uses iron-plate" in r12["msg"], f"insert says what the recipe uses: {r12['msg']}")

        r13, = await act({"op": "mine", "x": x + 3.5, "y": y - 6.5})
        check(not r13["ok"] and "assembling-machine-1 at" in r13["msg"], f"mine x,y names what's close by: {r13['msg']}")

        await link.call("eval", code="storage.agents['t-place'].char.insert{name='small-electric-pole', count=2}")
        r14, = await act({"op": "place", "name": "small-electric-pole", "x": x - 1, "y": y - 8})
        check(r14["ok"] and f"{x - 0.5},{y - 7.5}" in r14["msg"], f"off-grid x,y lands on the tile: {r14['msg']}")

        # A ghost planned over a tree (a stamp on rough ground): building it clears the tree first.
        gx, gy = x + 20.5, y - 8.5
        made = (await link.call("eval", code=f"local s = game.surfaces.nauvis "
            f"local t = s.create_entity{{name='tree-01', position={{{gx}, {gy}}}}} "
            f"local g = s.create_entity{{name='entity-ghost', inner_name='wooden-chest', position={{{gx}, {gy}}}, force='player'}} "
            "storage.agents['t-place'].char.insert{name='wooden-chest', count=2} "
            "return {tree = t and t.valid, ghost = g and g.valid}"))["result"]
        r15, = await act({"op": "build_ghosts", "x": gx, "y": gy, "radius": 3}, timeout=90)
        left = (await link.call("eval", code=f"local s = game.surfaces.nauvis return {{chest = s.find_entity('wooden-chest', "
                                             f"{{{gx}, {gy}}}) ~= nil, trees = s.count_entities_filtered{{position={{{gx}, {gy}}}, "
                                             "radius=1.5, type='tree'}}"))["result"]
        check(made["tree"] and made["ghost"] and r15["ok"] and left["chest"] and left["trees"] == 0,
              f"a ghost over a tree gets built: {made} {r15['msg']} {left}")

        # find forgives slips instead of throwing a game error.
        f1 = await link.call("find", agent="t-place", name="tree")
        check("found" in f1, f"find name=tree works as a type: {str(f1)[:80]}")
        try:
            await link.call("find", agent="t-place", name="iron-chets")
            check(False, "a typo names close matches")
        except Exception as e:
            check("did you mean" in str(e) and "iron-chest" in str(e), f"a typo names close matches: {e}")
    print("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 9))
