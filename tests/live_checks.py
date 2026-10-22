#!/usr/bin/env python3
"""In-game checks of tonight's core behaviours (2026-10-22) on one test server. Each check builds what it needs on
a clear spot of a copy of the crew-test stage and prints ok/FAIL like tests/test_units.py.

    .venv/bin/python tests/live_checks.py                    # instance 60
    .venv/bin/python tests/live_checks.py --instance 61 --only escape,launch

Checks: progress op numbers; a blueprint laid over an identical built copy plans no ghosts; an inserter-fed boiler
isn't "low on fuel"; an action waiting in the queue gives up on its own, without cancelling the job ahead of it, and
a job that runs too long is cancelled alone; a cancelled order (Runner.abort) stops at its next action; the escape
from a walled pen through a pipe gap (and the pipe is put back); the launch step (Space Age 2.0: no cargo
destination needed, rockets_launched counts the rocket once it has left). About 75 s plus server start.
"""
from __future__ import annotations

import argparse
import asyncio
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from instance import Instance  # noqa: E402
from jev import blueprints as bp  # noqa: E402
from jev.game import Game  # noqa: E402
from jev.steps import Runner  # noqa: E402

FAILS: list[str] = []


def check(name, cond, info=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  ({info})" if info and not cond else ""), flush=True)
    if not cond:
        FAILS.append(name)


class Live:
    def __init__(self, g: Game):
        self.g = g
        self.used: list[tuple[float, float, float, float]] = []  # sites handed out, so checks don't build on each other

    async def ev(self, code: str):
        return (await self.g.call("eval", code=code, timeout=60)).get("result")

    async def pos(self) -> tuple[float, float]:
        p = (await self.g.me()).get("position")
        return float(p[0]), float(p[1])

    async def site(self, w: int, h: int) -> tuple[float, float]:
        """Top-left tile of a clear w x h area (no entities but resources, no water) near spawn, away from sites
        handed out before."""
        skip = ",".join(f"{{{a},{b},{c},{d}}}" for a, b, c, d in self.used) or ""
        code = f"""
local s = game.surfaces.nauvis
local sp = game.forces.player.get_spawn_position(s)
local used = {{{skip}}}
local function free(x0, y0)
  for _, u in ipairs(used) do
    if x0 < u[3] + 4 and x0 + {w} > u[1] - 4 and y0 < u[4] + 4 and y0 + {h} > u[2] - 4 then return false end
  end
  local area = {{{{x0 - 1, y0 - 1}}, {{x0 + {w} + 1, y0 + {h} + 1}}}}
  return s.count_entities_filtered {{ area = area, type = "resource", invert = true }} == 0
     and s.count_tiles_filtered {{ area = area, collision_mask = "water_tile" }} == 0
end
for r = 12, 200, 4 do
  for _, d in ipairs {{ {{1, 0}}, {{0, 1}}, {{-1, 0}}, {{0, -1}}, {{1, 1}}, {{-1, 1}}, {{1, -1}}, {{-1, -1}} }} do
    local x0, y0 = math.floor(sp.x + d[1] * r), math.floor(sp.y + d[2] * r)
    if free(x0, y0) then return {{x0, y0}} end
  end
end
return nil"""
        p = await self.ev(code)
        if not p:
            raise RuntimeError(f"no clear {w}x{h} site")
        x0, y0 = p
        self.used.append((x0, y0, x0 + w, y0 + h))
        return float(x0), float(y0)


# ---------------------------------------------------------------------------- checks
async def chk_progress(L: Live, state: dict, after: bool = False):
    p = await L.g.call("progress", items=["iron-plate", "automation-science-pack"], fluids=["petroleum-gas"],
                       entities=["rocket-silo", "boiler", "steam-engine"])
    ntech = await L.ev("local n = 0 for _ in pairs(game.forces.player.technologies) do n = n + 1 end return n")
    tag = "after" if after else "before"
    sane = (isinstance(p.get("tick"), int) and p["tick"] > 0 and isinstance(p.get("techs"), int)
            and 0 <= p["techs"] <= ntech and isinstance(p.get("items", {}).get("iron-plate"), (int, float))
            and isinstance(p.get("fluids"), dict) and isinstance(p.get("by_recipe"), dict)
            and isinstance(p.get("labs_working"), int) and isinstance(p.get("rockets"), int))
    check(f"progress ({tag}): tick, techs, items, fluids, machines and rockets are sane numbers", sane, p)
    if not after:
        state["progress"] = p
        return
    p0 = state.get("progress") or {}
    e0, e1 = p0.get("ents") or {}, p.get("ents") or {}
    check("progress: counts the silo, boilers and engine the checks built",
          e1.get("rocket-silo", 0) == e0.get("rocket-silo", 0) + 1 and e1.get("boiler", 0) == e0.get("boiler", 0) + 2
          and e1.get("steam-engine", 0) == e0.get("steam-engine", 0) + 1, (e0, e1))
    if state.get("launched"):
        check("progress: rockets is force.rockets_launched (1 after the launch)", p.get("rockets") == 1, p.get("rockets"))


async def chk_ghost_dedup(L: Live, state: dict):
    x0, y0 = await L.site(15, 7)
    ents = bp.stamp_entities("red-science-5", x0, y0, 0)
    r1 = await L.g.run({"op": "blueprint", "entities": ents}, timeout=60)
    area = f"{{{{{x0 - 1},{y0 - 1}}},{{{x0 + 16},{y0 + 8}}}}}"
    revived = await L.ev(f"local n = 0 for _, gh in pairs(game.surfaces.nauvis.find_entities_filtered{{type='entity-ghost', "
                         f"area={area}}}) do if gh.revive() then n = n + 1 end end return n")
    r2 = await L.g.run({"op": "blueprint", "entities": ents}, timeout=60)
    left = await L.ev(f"return game.surfaces.nauvis.count_entities_filtered{{type='entity-ghost', area={area}}}")
    check("ghosts: the first stamp lays the layout", r1.get("ok") and revived == len(ents), (r1.get("msg"), revived))
    check("ghosts: the same layout over the built copy plans nothing (no ghosts on top)",
          r2.get("ok") and left == 0 and (r2.get("existing") or 0) == len(ents), (r2.get("msg"), r2.get("existing"), left))


async def chk_boilers(L: Live, state: dict):
    x0, y0 = await L.site(9, 9)
    sx, sy = x0 + 4.5, y0 + 4.5
    code = f"""
local s, f = game.surfaces.nauvis, game.forces.player
local function mk(t) local e = s.create_entity(t) if not e then error("could not create " .. t.name) end return e end
mk {{ name = "steam-engine", position = {{ {sx - 3}, {sy} }}, direction = defines.direction.north, force = f }}
mk {{ name = "small-electric-pole", position = {{ {sx - 1}, {sy - 2} }}, force = f }}
local a = mk {{ name = "boiler", position = {{ {sx + 2}, {sy - 2.5} }}, direction = defines.direction.north, force = f }}
local b = mk {{ name = "boiler", position = {{ {sx + 2}, {sy + 2.5} }}, direction = defines.direction.north, force = f }}
local ins = mk {{ name = "inserter", position = {{ {sx + 2}, {sy - 1} }}, direction = defines.direction.south, force = f }}
a.get_fuel_inventory().insert {{ name = "coal", count = 5 }}
b.get_fuel_inventory().insert {{ name = "coal", count = 5 }}
storage.live_boiler = {{ a = a, ins = ins }}
return {{ a = {{ a.position.x, a.position.y }}, b = {{ b.position.x, b.position.y }} }}"""
    built = await L.ev(code)
    sc = await L.g.call("scan", agent="serf", center=[sx, sy], radius=12)
    # an inserter picks its drop target on its first update, not when it's created
    built["feeds_a"] = await L.ev("local t = storage.live_boiler return t.ins.drop_target ~= nil and "
                                  "t.ins.drop_target.unit_number == t.a.unit_number")
    grid = next((gr for gr in sc.get("grids") or [] if isinstance(gr, dict) and gr.get("boilers")), None) or {}
    low_at = [tuple(p) for p in grid.get("boilers_low_at") or []]
    check("boilers: the test inserter feeds boiler A", built.get("feeds_a"), built)
    check("boilers: a boiler an inserter feeds with 5 coal isn't 'low'; a hand-fed one with 5 is",
          grid.get("boilers") == 2 and grid.get("boilers_low_fuel") == 1 and low_at == [tuple(built["b"])],
          {k: grid.get(k) for k in ("boilers", "boilers_low_fuel", "boilers_low_at")})


async def chk_queue(L: Live, state: dict):
    g = L.g
    long = asyncio.create_task(g.run({"op": "wait", "seconds": 40}, timeout=120))
    await asyncio.sleep(1.5)
    t = time.monotonic()
    r = await g.run({"op": "say", "text": "queued behind a wait"}, timeout=30, queue_timeout=5)
    waited = time.monotonic() - t
    me = await g.me()
    still = (me.get("job") or {}).get("op") == "wait"
    check("queue: an action stuck behind another job gives up by itself and says what it waited for",
          not r.get("ok") and "waiting in the queue" in str(r.get("msg")) and "wait" in str(r.get("msg"))
          and waited < 20, (round(waited, 1), r.get("msg")))
    check("queue: ... without cancelling the job ahead of it", still, me.get("job"))
    await g.cancel("live check: clean up")
    await long
    t = time.monotonic()
    slow = asyncio.create_task(g.run({"op": "wait", "seconds": 60}, timeout=5))
    await asyncio.sleep(0.5)
    after = asyncio.create_task(g.run({"op": "say", "text": "after the slow one"}, timeout=60))
    rs, ra = await slow, await after
    took = time.monotonic() - t
    check("queue: a job running past its timeout is cancelled alone, and the next one still runs",
          not rs.get("ok") and "timed out after 5s" in str(rs.get("msg")) and ra.get("ok") and took < 30,
          (round(took, 1), rs.get("msg"), ra.get("msg")))


async def chk_abort(L: Live, state: dict):
    g = L.g
    runner = Runner(g, lambda rec: None)
    stop = [False]
    runner.abort = lambda: stop[0]
    r1 = await runner._act({"op": "wait", "seconds": 1})
    stop[0] = True
    x, y = await L.pos()
    t = time.monotonic()
    r2 = await runner._act({"op": "move", "x": x + 30, "y": y, "radius": 2})
    quick = time.monotonic() - t
    r3 = await runner.run({"do": "move", "x": x + 30, "y": y})
    await asyncio.sleep(2)
    x2, y2 = await L.pos()
    check("abort: actions run while the order is live", r1.get("ok"), r1)
    check("abort: once cancelled, the next action stops without reaching the game",
          r2.get("cancelled") and quick < 1 and math.hypot(x2 - x, y2 - y) < 0.5, (r2, round(quick, 2), (x, y), (x2, y2)))
    check("abort: a whole step stops too", not r3.get("ok") and "cancelled" in str(r3.get("msg")), r3)


async def chk_escape(L: Live, state: dict):
    g = L.g
    x0, y0 = await L.site(9, 9)
    cx, cy = x0 + 4.5, y0 + 4.5
    await L.ev(f"local c = storage.agents['serf'].char c.teleport({{{cx}, {cy}}}) return true")
    code = f"""
local s, f = game.surfaces.nauvis, game.forces.player
local n = 0
for i = -2, 2 do for j = -2, 2 do
  if math.abs(i) == 2 or math.abs(j) == 2 then
    local name = (i == 2 and j == 0) and 'pipe' or 'stone-wall'
    if s.create_entity {{ name = name, position = {{ {cx} + i, {cy} + j }}, force = f }} then n = n + 1 end
  end
end end
return n"""
    pieces = await L.ev(code)
    pre = await g.run({"op": "move", "x": cx + 40, "y": cy, "radius": 2}, timeout=60)
    logs: list = []
    runner = Runner(g, logs.append)
    res = {}
    for _ in range(4):
        res = await runner._act({"op": "move", "x": cx + 40, "y": cy, "radius": 2}, timeout=60)
        if res.get("ok"):
            break
    pipe = await L.ev(f"return game.surfaces.nauvis.count_entities_filtered{{name='pipe', position={{{cx + 2},{cy}}}, "
                      f"radius=0.6}}")
    x, y = await L.pos()
    check("escape: the pen is closed (16 pieces) and a plain move finds no path",
          pieces == 16 and not pre.get("ok") and "no path" in str(pre.get("msg")), (pieces, pre.get("msg")))
    check("escape: after 3 no-path failures the runner gets out through the pipe and arrives",
          res.get("ok") and abs(x - (cx + 40)) < 4, (res.get("msg"), (round(x, 1), round(y, 1))))
    check("escape: the pipe is put back", pipe == 1, pipe)


async def chk_launch(L: Live, state: dict):
    g = L.g
    x0, y0 = await L.site(13, 9)
    sx, sy = x0 + 8.5, y0 + 4.5
    code = f"""
local s, f = game.surfaces.nauvis, game.forces.player
f.recipes["rocket-part"].enabled = true
pcall(function() f.technologies["rocket-silo"].researched = true end)
local silo = s.create_entity {{ name = "rocket-silo", position = {{ {sx}, {sy} }}, force = f }}
s.create_entity {{ name = "small-electric-pole", position = {{ {sx - 5}, {sy} }}, force = f }}
local eei = s.create_entity {{ name = "electric-energy-interface", position = {{ {sx - 6.5}, {sy + 2} }}, force = f }}
eei.power_production = 1e9 / 60; eei.power_usage = 0; eei.electric_buffer_size = 1e9 / 30
storage.live_silo = silo
return {{ silo.position.x, silo.position.y }}"""
    sp = await L.ev(code)
    runner = Runner(g, lambda rec: None)
    early = await runner.run({"do": "launch", "x": sp[0], "y": sp[1]})
    await L.ev("storage.live_silo.rocket_parts = 50 return true")
    ready = False
    for _ in range(40):
        st = await L.ev("local s = storage.live_silo return s.rocket_silo_status == defines.rocket_silo_status.rocket_ready")
        if st:
            ready = True
            break
        await asyncio.sleep(2)
    res = await runner.run({"do": "launch", "x": sp[0], "y": sp[1]})
    counted, t = 0, time.monotonic()
    while time.monotonic() - t < 60:
        counted = await L.ev("return game.forces.player.rockets_launched")
        if counted >= 1:
            break
        await asyncio.sleep(3)
    state["launched"] = counted >= 1
    check("launch: with no rocket ready it says so", not early.get("ok") and "isn't ready" in str(early.get("msg")),
          early.get("msg"))
    check("launch: a powered silo given 50 parts readies a rocket", ready)
    check("launch: the step walks there and launches (no cargo destination needed)",
          res.get("ok") and "1 launched" in str(res.get("msg")), res.get("msg"))
    check("launch: force.rockets_launched counts it once it has left", counted == 1, counted)


CHECKS = {"progress": chk_progress, "ghosts": chk_ghost_dedup, "boilers": chk_boilers, "queue": chk_queue,
          "abort": chk_abort, "escape": chk_escape, "launch": chk_launch}


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--instance", type=int, default=60, help="test server id, 60-69")
    ap.add_argument("--stage", default="crew-test")
    ap.add_argument("--only", help="comma list of checks: " + ",".join(CHECKS))
    a = ap.parse_args()
    if not 60 <= a.instance <= 69:
        ap.error("--instance must be 60..69 (the rest belong to campaigns and other runs)")
    only = a.only.split(",") if a.only else list(CHECKS)
    inst = Instance(a.instance, a.stage)
    print(f"starting instance {a.instance} on a copy of {a.stage}", flush=True)
    await asyncio.to_thread(inst.start, 300)
    g = None
    state: dict = {}
    try:
        g = await Game.connect(inst.host, inst.rcon_port, inst.password, "serf")
        await g.start(spawn=True)
        L = Live(g)
        for name in only:
            try:
                await asyncio.wait_for(CHECKS[name](L, state), 300)
            except Exception as e:  # noqa: BLE001
                check(f"{name}: ran without errors", False, repr(e)[:300])
        if "progress" in only:
            await chk_progress(L, state, after=True)
    finally:
        if g:
            await g.stop()
            await g.crew.close()
        await asyncio.to_thread(inst.stop)
    print(f"\n{'ALL OK' if not FAILS else str(len(FAILS)) + ' FAILED: ' + ', '.join(FAILS)}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
