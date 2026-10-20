"""Power you can see: `inspect` says powered / low power / no power (with the nearest grid pole), a pole shows its
whole grid, and placing or stamping machines warns when they have no power. Plus the message fixes: look at x,y,
craft count = items, inserter sides, underground entrance/exit, and the act-op vs tool error. No model calls.

  .venv/bin/python tests/test_power.py [instance=44]
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from crew.game import GameLink  # noqa: E402
from crew.tools import power_note, t_act, t_inspect, t_look, wrong_form  # noqa: E402

FAILS: list[str] = []


def check(cond: bool, what: str) -> None:
    print(("PASS " if cond else "FAIL ") + what, flush=True)
    if not cond:
        FAILS.append(what)


# Grid A: a 1 MW interface, a pole and a working gear assembler; an unconnected assembler 15 tiles east.
# Grid B: a 10 kW interface feeding an assembler (low power). Grid C: a pole and an assembler, no generator.
SETUP = """local s, f = game.surfaces.nauvis, game.forces.player
local X, Y = %d, %d
local t = {}
for x = X-4, X+44 do for y = Y-6, Y+40 do t[#t+1] = {name='grass-1', position={x,y}} end end
s.set_tiles(t)
for _, e in pairs(s.find_entities_filtered{area={{X-4,Y-6},{X+44,Y+40}}}) do
  if e.type ~= 'character' then e.destroy() end end
local function gen(x, y, w)
  local g = s.create_entity{name='electric-energy-interface', position={X+x, Y+y}, force=f}
  g.power_production = w / 60 g.power_usage = 0 g.electric_buffer_size = w
end
local function am(x, y)
  local a = s.create_entity{name='assembling-machine-1', position={X+x, Y+y}, force=f, recipe='iron-gear-wheel'}
  a.insert{name='iron-plate', count=200}
  return a
end
gen(1, 1, 1000000)
s.create_entity{name='small-electric-pole', position={X+3.5, Y+0.5}, force=f}
am(5.5, 2.5)
am(20.5, 2.5)
gen(1, 13, 10000)
s.create_entity{name='small-electric-pole', position={X+3.5, Y+12.5}, force=f}
am(5.5, 14.5)
s.create_entity{name='small-electric-pole', position={X+3.5, Y+24.5}, force=f}
am(5.5, 26.5)
s.create_entity{name='underground-belt', position={X+30.5, Y+10.5}, direction=defines.direction.east, type='input', force=f}
s.create_entity{name='underground-belt', position={X+33.5, Y+10.5}, direction=defines.direction.east, type='output', force=f}
s.create_entity{name='wooden-chest', position={X+30.5, Y+20.5}, force=f}
local i = s.create_entity{name='inserter', position={X+30.5, Y+21.5}, direction=defines.direction.north, force=f}
local c = storage.agents['t-power'].char
c.teleport({X+8, Y+6})
c.insert{name='inserter', count=10} c.insert{name='copper-plate', count=3}
return {pickup = {i.pickup_position.x, i.pickup_position.y}, drop = {i.drop_position.x, i.drop_position.y}}"""


async def main(k: int) -> None:
    from instance import Instance
    with Instance(k, "stage-s3-steel-oil-ready") as inst:
        link = GameLink(inst.host, inst.rcon_port, inst.password, client="t-power")
        await link.start()
        await link.call("spawn", name="t-power", client="t-power", starter_kit=False)
        X, Y = 500, 300
        ins = await link.call("eval", code=SETUP % (X, Y))
        await asyncio.sleep(3)  # let the grids run a few seconds for the 5 s statistics
        agent = SimpleNamespace(name="t-power", link=link, pending_jobs=set(), finished={},
                                interrupted=asyncio.Event(), note_activity=lambda s: None, last_position=None)

        async def one(x, y, name):
            d = json.loads(await t_inspect(agent, {"x": x, "y": y, "radius": 0.6}))
            return next((e for e in d["entities"] if e["n"] == name), {})

        a1 = await one(X + 5.5, Y + 2.5, "assembling-machine-1")
        check(a1.get("power") == "powered", f"working assembler: {a1.get('power')}")
        a2 = await one(X + 20.5, Y + 2.5, "assembling-machine-1")
        check(str(a2.get("power", "")).startswith("no power: not on the grid") and f"{X + 3.5:g},{Y + 0.5:g}" in a2["power"],
              f"unconnected assembler names the grid pole: {a2.get('power')}")
        a3 = await one(X + 5.5, Y + 14.5, "assembling-machine-1")
        check(str(a3.get("power", "")).startswith("low power"), f"10 kW grid: {a3.get('power')}")
        a4 = await one(X + 5.5, Y + 26.5, "assembling-machine-1")
        check(str(a4.get("power", "")).startswith("no power: its poles don't reach any generator"),
              f"grid with no generator: {a4.get('power')}")

        pole = await one(X + 3.5, Y + 0.5, "small-electric-pole")
        grid = pole.get("grid") or []
        print("\n".join(grid))
        check("energy" not in pole and grid and grid[0].startswith("grid #") and "of 1.0 MW capacity" in grid[0],
              f"pole shows load vs capacity: {grid[:1]}")
        check(any(g.startswith("generators: 1 electric-energy-interface") for g in grid), "pole lists generators")
        check(any(g.startswith("top users: assembling-machine-1") for g in grid), "pole lists top users")
        check(not any(g.startswith("fuel:") for g in grid), "no boilers on this grid: the base's boilers aren't listed")
        base = await link.call("eval", code="local b = game.surfaces.nauvis.find_entities_filtered{type='boiler', force='player'}[1] "
                                            "local p = b and b.surface.find_entities_filtered{type='electric-pole', position=b.position, radius=12}[1] "
                                            "return p and {p.position.x, p.position.y}")
        if base.get("result"):
            bx, by = base["result"]
            bp = json.loads(await t_inspect(agent, {"x": bx, "y": by, "radius": 0.4}))["entities"][0]
            print("\n".join(bp.get("grid") or []))
            check(any(g.startswith("fuel:") for g in bp.get("grid") or []), "the base grid lists its boilers' fuel")

        ug = await one(X + 30.5, Y + 10.5, "underground-belt")
        ug2 = await one(X + 33.5, Y + 10.5, "underground-belt")
        check(ug.get("ug") == "input (entrance)" and ug2.get("ug") == "output (exit)", f"underground ends: {ug.get('ug')} {ug2.get('ug')}")
        ins_d = await one(X + 30.5, Y + 21.5, "inserter")
        py = ins["result"]["pickup"][1]
        want = "picks from north, drops south" if py < Y + 21.5 else "picks from south, drops north"
        check(ins_d.get("sides") == want, f"inserter sides: {ins_d.get('sides')} (want {want})")

        # place: one inserter on grid A (powered), one far away (no power) -> the act result warns about one
        out = await t_act(agent, {"wait": True, "actions": [
            {"op": "place", "name": "inserter", "x": X + 2.5, "y": Y - 1.5, "direction": "north"},
            {"op": "place", "name": "inserter", "x": X + 38.5, "y": Y + 0.5, "direction": "north"}]})
        print(out)
        check("WARNING: 1 of 2 machines you placed have no power" in out and f"{X + 3.5:g},{Y + 0.5:g}" in out,
              "act place warns about the unpowered one and names the grid pole")
        out = await t_act(agent, {"wait": True, "actions": [
            {"op": "place", "name": "inserter", "x": X + 4.5, "y": Y - 1.5, "direction": "north"}]})
        check("no power" not in out, "a powered placement has no warning")

        note = await power_note(agent, x1=X + 15, y1=Y - 2, x2=X + 25, y2=Y + 6)
        check(note.startswith("WARNING: 1 of 1 machines have no power"), f"build zone note: {note}")
        await link.call("eval", code=f"game.surfaces.nauvis.create_entity{{name='entity-ghost', inner_name='assembling-machine-1', "
                                     f"position={{{X + 40.5}, {Y + 30.5}}}, force='player'}}")
        note = await power_note(agent, x1=X + 38, y1=Y + 28, x2=X + 43, y2=Y + 33, ghosts=True)
        check("no power pole in or next to this area" in note, f"stamp note for ghosts with no pole: {note}")

        # look around a remote point
        d = json.loads(await t_look(agent, {"x": X + 20.5, "y": Y + 2.5, "radius": 3}))
        ents = d["nearby"]["entities"]
        check(any(e["n"] == "assembling-machine-1" and str(e.get("power", "")).startswith("no power") for e in ents),
              f"look x,y sees the far assembler and its power: {ents[:2]}")

        # craft count = items: 3 plates make 6 cable; asking 10 says it was short
        r = await link.call("act", agent="t-power", actions=[{"op": "craft", "recipe": "copper-cable", "count": 10}])
        res = await asyncio.wait_for(link.job_future(r["job_ids"][0]), 30)
        check(res.get("ok") and res["msg"].startswith("crafted 6 copper-cable") and "not enough copper-plate" in res["msg"],
              f"craft count is items, short says why: {res.get('msg')}")
        await link.call("eval", code="storage.agents['t-power'].char.insert{name='copper-plate', count=2}")
        r = await link.call("act", agent="t-power", actions=[{"op": "craft", "recipe": "copper-cable", "count": 4}])
        res = await asyncio.wait_for(link.job_future(r["job_ids"][0]), 30)
        check(res.get("ok") and res["msg"] == "crafted 4 copper-cable", f"craft 4 cable = 2 crafts: {res.get('msg')}")

        # tool vs act op
        out = await t_act(agent, {"actions": [{"op": "inspect", "x": 1, "y": 2}]})
        check(out.startswith("inspect is a tool, not an act op"), f"tool as act op: {out}")
        check(wrong_form("place").startswith("place is an act op, not a tool"), "act op as tool")
    print("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 44))
