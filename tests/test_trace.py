"""`trace` follows a belt line: straight runs, underground hops, a corner, why it ends (side-load, gap, head-on),
lane contents, and the inserters taking from and putting onto it. Both directions. No model calls.

  .venv/bin/python tests/test_trace.py [instance=41]
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
from crew.tools import t_trace  # noqa: E402

FAILS: list[str] = []


def check(cond: bool, what: str) -> None:
    print(("PASS " if cond else "FAIL ") + what, flush=True)
    if not cond:
        FAILS.append(what)


# Line A: east X..X+5, underground X+6 -> X+10 (a wall between), east X+11..X+13, a corner south at X+14 down to
# Y+4, side-loading onto line B (west along Y+5). An inserter takes off A into a chest, another puts onto it.
# Line C has a one-tile gap, line D runs head-on into a west belt, line E splits.
SETUP = """local s, f = game.surfaces.nauvis, game.forces.player
local X, Y = %d, %d
local t = {}
for x = X-4, X+24 do for y = Y-4, Y+22 do t[#t+1] = {name='grass-1', position={x,y}} end end
s.set_tiles(t)
for _, e in pairs(s.find_entities_filtered{area={{X-4,Y-4},{X+24,Y+22}}}) do
  if e.type ~= 'character' then e.destroy() end end
local D = defines.direction
local function belt(x, y, d) return s.create_entity{name='transport-belt', position={X+x+0.5, Y+y+0.5}, direction=d, force=f} end
for x = 0, 5 do belt(x, 0, D.east) end
s.create_entity{name='underground-belt', position={X+6.5, Y+0.5}, direction=D.east, type='input', force=f}
s.create_entity{name='stone-wall', position={X+8.5, Y+0.5}, force=f}
s.create_entity{name='underground-belt', position={X+10.5, Y+0.5}, direction=D.east, type='output', force=f}
for x = 11, 13 do belt(x, 0, D.east) end
for y = 0, 4 do belt(14, y, D.south) end
for x = 18, 10, -1 do belt(x, 5, D.west) end
for x = 0, 5 do s.find_entity('transport-belt', {X+x+0.5, Y+0.5}).get_transport_line(1).insert_at_back({name='iron-plate'}) end
s.find_entity('transport-belt', {X+3.5, Y+0.5}).get_transport_line(2).insert_at_back({name='coal'})
s.create_entity{name='wooden-chest', position={X+2.5, Y+2.5}, force=f}
local function inserter(x, y, py)
  for _, d in ipairs{D.north, D.south} do
    local i = s.create_entity{name='inserter', position={X+x, Y+y}, direction=d, force=f}
    if math.floor(i.pickup_position.y) == Y + py then return i end
    i.destroy()
  end
end
inserter(2.5, 1.5, 0)
s.create_entity{name='wooden-chest', position={X+4.5, Y-1.5}, force=f}
inserter(4.5, -0.5, -2)
for x = 0, 3 do belt(x, 10, D.east) end
belt(5, 10, D.east)
belt(0, 13, D.east) belt(1, 13, D.east) belt(2, 13, D.west)
belt(2, 16, D.east)
s.create_entity{name='splitter', position={X+3.5, Y+17}, direction=D.east, force=f}
for x = 4, 5 do belt(x, 16, D.east) belt(x, 17, D.east) end
return true"""


async def main(k: int) -> None:
    from instance import Instance
    with Instance(k, "stage-s3-steel-oil-ready") as inst:
        link = GameLink(inst.host, inst.rcon_port, inst.password, client="t-trace")
        await link.start()
        await link.call("spawn", name="t-trace", client="t-trace", starter_kit=False)
        X, Y = 400, 300
        await link.call("eval", code=SETUP % (X, Y))
        await link.call("eval", code=f"storage.agents['t-trace'].char.teleport({{{X - 2}, {Y + 8}}})")
        agent = SimpleNamespace(name="t-trace", link=link)

        def at(x, y):
            return f"{X + x + 0.5:g},{Y + y + 0.5:g}"

        d = await link.call("trace", agent="t-trace", x=X + 0.5, y=Y + 0.5)
        runs = d["runs"]
        check(d["belts"] == 16, f"16 belts down line A: {d['belts']}")
        check([r.get("dir") for r in runs] == ["east", "east", "east", "south"] and runs[1].get("under")
              and runs[1]["to"] == [X + 10.5, Y + 0.5], f"runs east, under, east, south: {runs}")
        check("side-loads onto the transport-belt at " + at(14, 5) in d["end"], f"ends side-loading B: {d['end']}")
        check(d["items"] != "empty" and d["items"]["left"].get("iron-plate") == 6
              and d["items"]["right"].get("coal") == 1, f"lane contents: {d['items']}")
        check(d["takes_total"] == 1 and "wooden-chest@" + at(2, 2) in d["takes"][0], f"inserter takes off: {d['takes']}")
        check(d["puts_total"] == 1 and "wooden-chest@" + at(4, -2) in d["puts"][0], f"inserter puts on: {d['puts']}")

        up = await link.call("trace", agent="t-trace", x=X + 14.5, y=Y + 4.5, direction="up")
        check(up["belts"] == 16 and up["runs"][-1]["to"] == [X + 0.5, Y + 0.5] and "starts here" in up["end"],
              f"upstream back to the start: {up['belts']} {up['end']} {up['runs'][-1]}")

        b = await link.call("trace", agent="t-trace", x=X + 18.5, y=Y + 5.5)
        check(b["belts"] == 9 and "nothing ahead" in b["end"] and any("side-load from" in p for p in b["puts"]),
              f"line B: fed from the side, ends: {b['belts']} {b['end']} {b['puts']}")

        c = await link.call("trace", agent="t-trace", x=X + 0.5, y=Y + 10.5)
        check("gap of 1 tile" in c["end"] and at(5, 10) in c["end"], f"gap found: {c['end']}")

        h = await link.call("trace", agent="t-trace", x=X + 0.5, y=Y + 13.5)
        check("head-on" in h["end"] and at(2, 13) in h["end"], f"head-on found: {h['end']}")

        sp = await link.call("trace", agent="t-trace", x=X + 2.5, y=Y + 16.5)
        check(sp["belts"] == 6 and len(sp.get("branches") or []) == 1 and any("branch" in r for r in sp["runs"]),
              f"a splitter's second output is followed as a branch: {sp['belts']} {sp.get('branches')}")

        try:
            await link.call("trace", agent="t-trace", x=X + 20.5, y=Y + 12.5)
            check(False, "no belt there is an error")
        except Exception as e:
            check("no belt at" in str(e), f"no belt there says so: {e}")

        text = await t_trace(agent, {"x": X + 0.5, "y": Y + 0.5})
        print(text)
        check(text.count("\n") <= 10 and "under to" in text and "side-loads onto" in text and "taken off by 1" in text,
              "the tool's text is short and says it all")
    print("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 41))
