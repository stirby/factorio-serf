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


async def chk_full_pocket(L: Live, state: dict):
    g = L.g
    x0, y0 = await L.site(6, 4)
    cx, cy = x0 + 1.5, y0 + 1.5
    await L.ev(f"""
local a = storage.agents['serf']
a.char.teleport({{{cx + 2}, {cy}}})
local s, f = game.surfaces.nauvis, game.forces.player
local ch = s.create_entity {{ name = 'iron-chest', position = {{{cx}, {cy}}}, force = f }}
ch.insert {{ name = 'iron-plate', count = 3200 }}
local inv = a.char.get_main_inventory()
inv.clear()
inv.insert {{ name = 'iron-chest', count = 5 }}
inv.insert {{ name = 'stone', count = inv.get_insertable_count('stone') }}
return inv.count_empty_stacks()""")
    r = await g.run({"op": "take", "x": cx, "y": cy, "count": 400}, timeout=30)
    check("full pocket: take says the inventory is full, not 'nothing to take'",
          not r.get("ok") and "inventory is full" in str(r.get("msg")), r.get("msg"))
    logs: list = []
    runner = Runner(g, logs.append)
    r = await runner.run({"do": "empty_chest", "x": cx, "y": cy})
    left = await L.ev(f"return game.surfaces.nauvis.find_entity('iron-chest', {{{cx}, {cy}}}).get_item_count('iron-plate')")
    check("full pocket: empty_chest makes room first, then takes", r.get("ok") and left < 3200, (r.get("msg"), left))
    await L.ev("storage.agents['serf'].char.get_main_inventory().clear() return true")


async def chk_orphan(L: Live, state: dict):
    g = L.g
    task = asyncio.create_task(g.run({"op": "wait", "seconds": 90}, timeout=120))
    await asyncio.sleep(3)
    before = (await g.call("self", agent="serf")).get("job") or {}
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    await asyncio.sleep(1)
    after = (await g.call("self", agent="serf")).get("job")
    check("orphan: a job whose caller is cancelled is withdrawn in the mod",
          before.get("op") == "wait" and not after, (before, after))
    # stock() giving up on a fetch cancels it too: a fetch that can't finish soon (hand-crafting 400 assemblers)
    r = Runner(g)
    jid = (await g.act([{"op": "wait", "seconds": 90}]))[0]
    w = await g.wait_job(jid, 2)
    if w.get("timeout"):
        await g.cancel("test", job=jid)
    after = (await g.call("self", agent="serf")).get("job")
    check("orphan: cancel by job id after a wait times out leaves nothing running", not after, after)


async def chk_craft_stall(L: Live, state: dict):
    g = L.g
    await L.ev("""
local a = storage.agents['serf']
local inv = a.char.get_main_inventory()
inv.clear()
inv.insert { name = 'iron-plate', count = 222 }
inv.insert { name = 'electronic-circuit', count = 103 }
inv.insert { name = 'iron-chest', count = 5 }
inv.insert { name = 'stone', count = inv.get_insertable_count('stone') }
return inv.count_empty_stacks()""")
    t0 = time.monotonic()
    r = await g.run({"op": "craft", "recipe": "inserter", "count": 1}, timeout=90)
    secs = time.monotonic() - t0
    check("craft stall: crafting with full pockets fails fast and says why",
          not r.get("ok") and secs < 60 and "inventory is full" in str(r.get("msg")), (round(secs), r.get("msg")))
    # the runner makes room (it carries 5 chests) and the crafting that was stuck finishes
    logs: list = []
    r = await Runner(g, logs.append)._act({"op": "craft", "recipe": "inserter", "count": 1}, timeout=90)
    have = await L.ev("return storage.agents['serf'].char.get_item_count('inserter')")
    check("craft stall: the runner tidies on a full pocket and the craft goes through",
          r.get("ok") and have >= 1 and any(x.get("kind") == "tidy" for x in logs),
          (r.get("msg"), have, [x for x in logs if x.get("kind") != "act" or not x.get("ok")][:6]))
    await L.ev("local c = storage.agents['serf'].char c.get_main_inventory().clear() "
               "while c.crafting_queue_size > 0 do c.cancel_crafting{index = 1, count = c.crafting_queue[1].count} end "
               "c.get_main_inventory().clear() return true")


async def chk_positional(L: Live, state: dict):
    g = L.g
    p = await L.ev("""
local s, c = game.surfaces.nauvis, storage.agents['serf'].char
local r = s.find_entities_filtered { position = c.position, radius = 120, type = 'resource', name = 'iron-ore', limit = 1 }[1]
if not r then return nil end
c.teleport({ r.position.x + 1, r.position.y })
return { r.position.x, r.position.y }""")
    if not p:
        check("positional mine: an ore tile near spawn", False, "no iron ore within 120 tiles")
        return
    t0 = time.monotonic()
    r = await g.run({"op": "mine", "x": p[0], "y": p[1]}, timeout=60)
    check("positional mine: with no building there it doesn't hand-mine the ore", not r.get("ok") and
          time.monotonic() - t0 < 10, (r.get("msg"), round(time.monotonic() - t0)))
    r = await g.run({"op": "mine", "x": p[0], "y": p[1], "name": "iron-ore", "count": 2}, timeout=60)
    check("positional mine: ... unless the ore is named", r.get("ok"), r.get("msg"))
    r = await g.run({"op": "mine", "name": "iron-ore", "count": 10}, timeout=90)
    check("mine: 10 ore by name, one unit after another (96f9bf0 stopped after 3)",
          r.get("ok") and "10" in str(r.get("msg")), r.get("msg"))
    x0, y0 = await L.site(8, 3)
    await L.ev(f"""
local s, f, c = game.surfaces.nauvis, game.forces.player, storage.agents['serf'].char
for i = 0, 5 do
  local b = s.create_entity {{ name = 'transport-belt', position = {{ {x0} + i + 0.5, {y0} + 0.5 }}, direction = defines.direction.east, force = f }}
  b.get_transport_line(1).insert_at_back('iron-plate')
end
c.teleport({{ {x0} + 2.5, {y0} + 1.5 }})
local inv = c.get_main_inventory()
inv.clear()
inv.insert {{ name = 'stone', count = inv.get_insertable_count('stone') }}
return true""")
    t0 = time.monotonic()
    r = await g.run({"op": "grab", "item": "iron-plate", "count": 4, "x": x0 + 2, "y": y0}, timeout=60)
    check("grab: a full pocket fails at once and says so", not r.get("ok") and "inventory is full" in str(r.get("msg"))
          and time.monotonic() - t0 < 10, (r.get("msg"), round(time.monotonic() - t0)))
    await L.ev("storage.agents['serf'].char.get_main_inventory().clear() return true")


async def chk_mine_contents(L: Live, state: dict):
    g = L.g
    x0, y0 = await L.site(6, 4)
    await L.ev(f"""
local s, f, c = game.surfaces.nauvis, game.forces.player, storage.agents['serf'].char
local fu = s.create_entity {{ name = 'stone-furnace', position = {{ {x0} + 1, {y0} + 1 }}, force = f }}
fu.insert {{ name = 'coal', count = 40 }}
fu.get_inventory(defines.inventory.furnace_source).insert {{ name = 'iron-ore', count = 40 }}
c.teleport({{ {x0} + 3.5, {y0} + 1.5 }})
local inv = c.get_main_inventory()
inv.clear()
inv.insert {{ name = 'stone-furnace', count = 1 }}
inv.insert {{ name = 'stone', count = inv.get_insertable_count('stone') }}
return true""")
    t0 = time.monotonic()
    r = await g.run({"op": "mine", "x": x0 + 1, "y": y0 + 1}, timeout=60)
    check("mine: a furnace whose contents don't fit fails at once and says so",
          not r.get("ok") and "inventory full" in str(r.get("msg")) and time.monotonic() - t0 < 10,
          (r.get("msg"), round(time.monotonic() - t0)))
    await L.ev("storage.agents['serf'].char.get_main_inventory().clear() return true")
    r = await g.run({"op": "mine", "x": x0 + 1, "y": y0 + 1}, timeout=60)
    have = await L.ev("return storage.agents['serf'].char.get_item_count('iron-ore')")
    check("mine: with room it picks the furnace up, contents and all", r.get("ok") and have == 40, (r.get("msg"), have))


async def chk_route_why(L: Live, state: dict):
    g = L.g
    x0, y0 = await L.site(12, 7)
    gx, gy = x0 + 9, y0 + 3
    ring = f"""
local s, f = game.surfaces.nauvis, game.forces.player
for _, d in ipairs {{ {{1, 0}}, {{-1, 0}}, {{0, 1}}, {{0, -1}} }} do
  s.create_entity {{ name = 'wooden-chest', position = {{ {gx} + d[1] + 0.5, {gy} + d[2] + 0.5 }}, force = f }}
end"""
    await L.ev(ring + f"""
local c = storage.agents['serf'].char
c.teleport({{ {x0} + 1.5, {y0} + 5.5 }})
c.get_main_inventory().clear()
c.insert {{ name = 'pipe', count = 50 }}
return true""")
    r = await g.run({"op": "connect", "item": "pipe", "from": [x0 + 1.5, y0 + 3.5], "to": [gx + 0.5, gy + 0.5]},
                    timeout=60)
    check("route: a boxed-in end is still reached by going under", r.get("ok"), r.get("msg"))
    x1, y1 = await L.site(12, 7)
    gx, gy = x1 + 9, y1 + 3
    ring = ring.replace("{gx}", str(gx))
    await L.ev(f"""
local s, f = game.surfaces.nauvis, game.forces.player
for _, d in ipairs {{ {{1, 0}}, {{-1, 0}}, {{0, 1}}, {{0, -1}} }} do
  s.create_entity {{ name = 'wooden-chest', position = {{ {gx} + d[1] + 0.5, {gy} + d[2] + 0.5 }}, force = f }}
end
storage.agents['serf'].char.teleport({{ {x1} + 1.5, {y1} + 5.5 }})
return true""")
    r = await g.run({"op": "connect", "item": "pipe", "from": [x1 + 1.5, y1 + 3.5], "to": [gx + 0.5, gy + 0.5],
                     "underground": False}, timeout=60)
    why = r.get("msg")
    check("route: with no way in (no undergrounds), it says what's around the end",
          "no free tile beside it" in str(why) and "wooden-chest" in str(why), why)
    await L.ev("storage.agents['serf'].char.get_main_inventory().clear() return true")


async def chk_route_detour(L: Live, state: dict):
    """A 16-tile pipe whose way is barred by a block of walls thicker than an underground reaches: the route has to go
    round, which the default node budget can't find; the retry with a bigger budget does."""
    g = L.g
    X0, Y0 = 3000, 3400
    await L.ev(f"""local s, f = game.surfaces.nauvis, game.forces.player
s.request_to_generate_chunks({{ {X0}, {Y0} }}, 4)
s.force_generate_chunk_requests()
local tiles = {{}}
for x = {X0} - 100, {X0} + 100 do for y = {Y0} - 40, {Y0} + 60 do tiles[#tiles + 1] = {{ name = 'refined-concrete', position = {{ x, y }} }} end end
s.set_tiles(tiles)
for _, e in pairs(s.find_entities_filtered {{ area = {{ {{ {X0} - 100, {Y0} - 40 }}, {{ {X0} + 100, {Y0} + 60 }} }} }}) do
  if e.type ~= 'character' then e.destroy() end
end
-- a cup open to the south, walls 12 thick (more than an underground reaches): the start is inside at the top,
-- the goal just north of the cup, so the line has to go out the bottom and round
local function wall(x0, y0, x1, y1)
  for x = x0, x1 do for y = y0, y1 do s.create_entity {{ name = 'stone-wall', position = {{ x + 0.5, y + 0.5 }}, force = f }} end end
end
wall({X0} - 42, {Y0} - 12, {X0} + 42, {Y0} - 1)
wall({X0} - 42, {Y0}, {X0} - 31, {Y0} + 40)
wall({X0} + 31, {Y0}, {X0} + 42, {Y0} + 40)
local c = storage.agents['serf'].char
c.teleport({{ {X0} + 0.5, {Y0} + 2.5 }})
c.get_main_inventory().clear()
c.insert {{ name = 'pipe', count = 400 }}
c.insert {{ name = 'pipe-to-ground', count = 20 }}
return true""")
    t0 = time.time()
    r = await g.run({"op": "connect", "item": "pipe", "from": [X0 + 0.5, Y0 + 0.5], "to": [X0 + 0.5, Y0 - 16.5]},
                    timeout=400)
    check("route: a 17-tile pipe from inside a walled cup goes out and round (bigger search on retry)",
          r.get("ok"), (str(r.get("msg"))[:200], f"{time.time() - t0:.0f}s"))
    await L.ev("storage.agents['serf'].char.get_main_inventory().clear() return true")


async def chk_route_pocket(L: Live, state: dict):
    """A water line to a tile ringed by crude pipes (no undergrounds): the failure says the end is in a closed pocket
    walled in by crude-oil pipes, not "search limit"."""
    g = L.g
    x0, y0 = await L.site(24, 12)
    gx, gy = x0 + 18, y0 + 6
    await L.ev(f"""local s, f = game.surfaces.nauvis, game.forces.player
local src = s.create_entity {{ name = 'infinity-pipe', position = {{ {gx} + 4.5, {gy} + 0.5 }}, force = f }}
src.set_infinity_pipe_filter {{ name = 'crude-oil', percentage = 1, mode = 'at-least' }}
for dx = -3, 3 do for dy = -3, 3 do
  if math.max(math.abs(dx), math.abs(dy)) == 3 then
    s.create_entity {{ name = 'pipe', position = {{ {gx} + dx + 0.5, {gy} + dy + 0.5 }}, force = f }}
  end
end end
local c = storage.agents['serf'].char
c.teleport({{ {x0} + 1.5, {y0} + 9.5 }})
c.insert {{ name = 'pipe', count = 50 }}
return true""")
    await asyncio.sleep(2)
    r = await g.run({"op": "connect", "item": "pipe", "from": [x0 + 1.5, y0 + 6.5], "to": [gx + 0.5, gy + 0.5],
                     "fluid": "water", "underground": False}, timeout=60)
    why = str(r.get("msg"))
    check("route: an end ringed by crude pipes is reported as a closed pocket walled in by crude-oil pipes",
          not r.get("ok") and "closed pocket of 9 free tiles" in why and "crude-oil pipes" in why, why[:300])
    await L.ev("storage.agents['serf'].char.get_main_inventory().clear() return true")


async def chk_fetch_far(L: Live, state: dict):
    """Pipes in a chest 600 tiles away and none nearer: fetch walks there (past the 400-tile search) instead of
    failing on the iron ore it would take to craft them; an ingredient failure says what it was for."""
    g = L.g
    X0, Y0 = 3000, 4200
    await L.ev(f"""local s, f = game.surfaces.nauvis, game.forces.player
s.request_to_generate_chunks({{ {X0} + 300, {Y0} }}, 11)
s.force_generate_chunk_requests()
local tiles = {{}}
for x = {X0} - 6, {X0} + 610 do for y = {Y0} - 4, {Y0} + 4 do tiles[#tiles + 1] = {{ name = 'refined-concrete', position = {{ x, y }} }} end end
s.set_tiles(tiles)
for _, e in pairs(s.find_entities_filtered {{ area = {{ {{ {X0} - 6, {Y0} - 4 }}, {{ {X0} + 610, {Y0} + 4 }} }} }}) do
  if e.type ~= 'character' then e.destroy() end
end
local ch = s.create_entity {{ name = 'steel-chest', position = {{ {X0} + 600.5, {Y0} + 0.5 }}, force = f }}
ch.insert {{ name = 'pipe', count = 100 }}
local c = storage.agents['serf'].char
c.teleport({{ {X0} + 0.5, {Y0} + 0.5 }})
c.get_main_inventory().clear()
return true""")
    r = await g.run({"op": "fetch", "item": "pipe", "count": 60}, timeout=300)
    have = await L.ev("return storage.agents['serf'].char.get_item_count('pipe')")
    check("fetch: pipes in a chest 600 tiles away are fetched (no closer storage)", r.get("ok") and have >= 60,
          (str(r.get("msg"))[:200], have))
    r2 = await g.run({"op": "fetch", "item": "iron-chest", "count": 2}, timeout=120)
    check("fetch: a failure on an ingredient says what it was for",
          not r2.get("ok") and "(to craft" in str(r2.get("msg")), str(r2.get("msg"))[:240])
    await L.ev("storage.agents['serf'].char.get_main_inventory().clear() return true")


async def chk_ug_pair(L: Live, state: dict):
    g = L.g
    x0, y0 = await L.site(10, 3)
    await L.ev(f"""
local c = storage.agents['serf'].char
c.teleport({{ {x0} + 3.5, {y0} + 2.5 }})
c.get_main_inventory().clear()
c.insert {{ name = 'underground-belt', count = 4 }}
return true""")
    a = await g.run({"op": "place", "name": "underground-belt", "x": x0 + 0.5, "y": y0 + 0.5, "direction": "east"},
                    timeout=30)
    b = await g.run({"op": "place", "name": "underground-belt", "x": x0 + 4.5, "y": y0 + 0.5, "direction": "east"},
                    timeout=30)
    check("underground: the first is an entrance, the next one downstream its exit (rocket-r3)",
          "input" in str(a.get("msg")) and "output" in str(b.get("msg")) and "paired with" in str(b.get("msg")),
          (a.get("msg"), b.get("msg")))
    c = await g.run({"op": "place", "name": "underground-belt", "x": x0 + 0.5, "y": y0 + 2.5, "direction": "west"},
                    timeout=30)
    check("underground: with nothing upstream it's an entrance", "input" in str(c.get("msg")), c.get("msg"))
    await L.ev("storage.agents['serf'].char.get_main_inventory().clear() return true")


async def chk_fluid_mix(L: Live, state: dict):
    g = L.g
    x0, y0 = await L.site(8, 4)
    info = await L.ev(f"""
local s, f = game.surfaces.nauvis, game.forces.player
local a = s.create_entity {{ name = 'pipe', position = {{ {x0} + 0.5, {y0} + 1.5 }}, force = f }}
a.insert_fluid {{ name = 'water', amount = 50 }}
local b = s.create_entity {{ name = 'pipe', position = {{ {x0} + 2.5, {y0} + 1.5 }}, force = f }}
b.insert_fluid {{ name = 'crude-oil', amount = 50 }}
local c = storage.agents['serf'].char
c.teleport({{ {x0} + 1.5, {y0} + 3.5 }})
c.get_main_inventory().clear()
c.insert {{ name = 'pipe', count = 5 }}
local okM = s.can_place_entity {{ name = 'pipe', position = {{ {x0} + 1.5, {y0} + 1.5 }}, force = f,
  build_check_type = defines.build_check_type.manual }}
return {{ manual = okM }}""")
    r = await g.run({"op": "place", "name": "pipe", "x": x0 + 1.5, "y": y0 + 1.5}, timeout=30)
    print("   fluid mix: can_place(manual) =", info, "| place ->", r.get("msg"))
    check("fluid mix: a pipe joining water and crude is refused and the message says the fluids would mix",
          not r.get("ok") and "mix" in str(r.get("msg")), r.get("msg"))
    await L.ev("storage.agents['serf'].char.get_main_inventory().clear() return true")


async def chk_tree_clear(L: Live, state: dict):
    g = L.g
    x0, y0 = await L.site(6, 4)
    await L.ev(f"""
local s, f = game.surfaces.nauvis, game.forces.player
s.create_entity {{ name = 'transport-belt', position = {{ {x0} + 2.5, {y0} + 1.5 }}, direction = defines.direction.east, force = f }}
s.create_entity {{ name = 'tree-01', position = {{ {x0} + 3.2, {y0} + 1.6 }} }}
local c = storage.agents['serf'].char
c.teleport({{ {x0} + 3.5, {y0} + 3.5 }})
c.get_main_inventory().clear()
return true""")
    r = await Runner(g)._act({"op": "mine", "x": x0 + 3.2, "y": y0 + 1.6, "name": "tree-01"}, timeout=30)
    r2 = await Runner(g)._act({"op": "mine", "x": x0 + 3.2, "y": y0 + 1.6, "name": "tree-01"}, timeout=30)
    belt = await L.ev(f"return game.surfaces.nauvis.count_entities_filtered{{name='transport-belt', position={{{x0} + 2.5, {y0} + 1.5}}, radius=0.5}}")
    check("tree clear: the tree goes, and mining it again when it's gone leaves the belt beside it (p2)",
          r.get("ok") and not r2.get("ok") and belt == 1, (r.get("msg"), r2.get("msg"), belt))
    r3 = await Runner(g)._do_clear({"x": x0 + 3, "y": y0 + 2, "radius": 3, "trees": True})
    check("tree clear: clearing an area with no trees left is fine", r3.get("ok"), r3.get("msg"))


async def chk_wait_research(L: Live, state: dict):
    g = L.g
    pick = await L.ev("""
local f = game.forces.player
local out = {}
for name, t in pairs(f.technologies) do
  if not t.researched and t.enabled and t.research_unit_count and #t.research_unit_ingredients > 0 then
    local ready = true
    for _, pre in pairs(t.prerequisites) do if not pre.researched then ready = false break end end
    local unlocks = false
    for _, eff in pairs(t.prototype.effects or {}) do if eff.type == 'unlock-recipe' then unlocks = true end end
    if ready and unlocks then out[#out + 1] = name end
    if #out >= 2 then break end
  end
end
return out""")
    if not pick or len(pick) < 2:
        check("wait_research: two researchable techs on the stage", False, pick)
        return
    a, b = pick[0], pick[1]
    r = Runner(g)
    await r._do_research({"tech": a, "first": True})
    async def finish_soon():  # the labs finish it while the step waits (this stage has no working labs)
        await asyncio.sleep(12)
        await L.ev(f"game.forces.player.technologies['{a}'].researched = true return true")
    done = asyncio.create_task(finish_soon())
    res = await r._do_wait_research({"tech": a, "minutes": 2})
    await done
    check(f"wait_research: waits until {a} is researched", res.get("ok") and "researched" in str(res.get("msg")),
          res.get("msg"))
    res = await r._do_wait_research({"tech": b, "minutes": 0.2})
    check(f"wait_research: a tech far from done times out and says how far it got",
          not res.get("ok") and "still at" in str(res.get("msg")), res.get("msg"))


async def chk_fluid_ports(L: Live, state: dict):
    g = L.g
    x0, y0 = await L.site(20, 12)
    setup = await L.ev(f"""
local s, f = game.surfaces.nauvis, game.forces.player
f.recipes['battery'].enabled = true
f.recipes['sulfuric-acid'].enabled = true
local a = s.create_entity {{ name = 'chemical-plant', position = {{ {x0} + 2.5, {y0} + 5.5 }}, force = f,
  direction = defines.direction.east }}
a.set_recipe('sulfuric-acid')
local b = s.create_entity {{ name = 'chemical-plant', position = {{ {x0} + 16.5, {y0} + 5.5 }}, force = f,
  direction = defines.direction.south }}
b.set_recipe('battery')
local w = s.create_entity {{ name = 'pipe', position = {{ {x0} + 9.5, {y0} + 5.5 }}, force = f }}
w.insert_fluid {{ name = 'water', amount = 50 }}
local c = storage.agents['serf'].char
c.teleport({{ {x0} + 9.5, {y0} + 9.5 }})
c.get_main_inventory().clear()
c.insert {{ name = 'pipe', count = 60 }}
c.insert {{ name = 'pipe-to-ground', count = 10 }}
return {{ a = a.unit_number, b = b.unit_number }}""")
    r = await Runner(g)._do_connect({"item": "pipe", "from": [x0 + 2.5, y0 + 5.5], "to": [x0 + 16.5, y0 + 5.5],
                                     "from_fluid": "sulfuric-acid", "to_fluid": "sulfuric-acid"})
    await L.ev(f"""
local a = game.surfaces.nauvis.find_entity('chemical-plant', {{ {x0} + 2.5, {y0} + 5.5 }})
local fb = a.fluidbox
for i = 1, #fb do if fb.get_locked_fluid(i) == 'sulfuric-acid' then fb[i] = {{ name = 'sulfuric-acid', amount = 100 }} end end
return true""")
    await asyncio.sleep(4)
    joined = await L.ev(f"""
local s = game.surfaces.nauvis
local b = s.find_entity('chemical-plant', {{ {x0} + 16.5, {y0} + 5.5 }})
local got = 0
for i = 1, #b.fluidbox do local fl = b.fluidbox[i] if fl and fl.name == 'sulfuric-acid' then got = got + fl.amount end end
local w = s.find_entity('pipe', {{ {x0} + 9.5, {y0} + 5.5 }})
local wf = w and w.fluidbox[1]
return {{ acid_at_b = got, water_pipe = wf and wf.name or 'empty' }}""")
    joined = joined if isinstance(joined, dict) else {}
    joined["same"] = (joined.get("acid_at_b") or 0) > 0
    joined["clean"] = joined.get("water_pipe") == "water"
    check("fluid ports: acid output piped to the battery plant's acid input, clear of the water pipe in the way",
          r.get("ok") and isinstance(joined, dict) and joined.get("same") and joined.get("clean"),
          (r.get("msg"), joined))
    # a plain pipe line from a water pipe keeps clear of the acid line just laid (its fluid comes from its start)
    x1, y1 = await L.site(14, 6)
    await L.ev(f"""
local s, f = game.surfaces.nauvis, game.forces.player
local w = s.create_entity {{ name = 'pipe', position = {{ {x1} + 0.5, {y1} + 2.5 }}, force = f }}
w.insert_fluid {{ name = 'water', amount = 50 }}
local o = s.create_entity {{ name = 'pipe', position = {{ {x1} + 6.5, {y1} + 2.5 }}, force = f }}
o.insert_fluid {{ name = 'crude-oil', amount = 50 }}
storage.agents['serf'].char.teleport({{ {x1} + 6.5, {y1} + 5.5 }})
return true""")
    r3 = await Runner(g)._do_connect({"item": "pipe", "from": [x1 + 1.5, y1 + 2.5], "to": [x1 + 12.5, y1 + 2.5]})
    mixed = await L.ev(f"""
local o = game.surfaces.nauvis.find_entity('pipe', {{ {x1} + 6.5, {y1} + 2.5 }})
local fl = o and o.fluidbox[1]
return fl and fl.name or 'empty'""")
    check("fluid ports: a plain pipe line takes its fluid from its start and goes round another fluid",
          r3.get("ok") and mixed == "crude-oil", (r3.get("msg"), mixed))
    r2 = await Runner(g)._do_connect({"item": "pipe", "from": [x0 + 2.5, y0 + 5.5], "to": [x0 + 16.5, y0 + 5.5],
                                      "from_fluid": "crude-oil"})
    check("fluid ports: a fluid the machine doesn't have says what its boxes are",
          not r2.get("ok") and "has no output for crude-oil" in str(r2.get("msg")), r2.get("msg"))
    await L.ev("storage.agents['serf'].char.get_main_inventory().clear() return true")


async def chk_fluid_ports2(L: Live, state: dict):
    g = L.g
    x0, y0 = await L.site(24, 14)
    ports = await L.ev(f"""
local s, f = game.surfaces.nauvis, game.forces.player
for _, r in ipairs {{ 'battery', 'sulfuric-acid', 'sulfur' }} do f.recipes[r].enabled = true end
local a = s.create_entity {{ name = 'chemical-plant', position = {{ {x0} + 2.5, {y0} + 3.5 }}, force = f,
  direction = defines.direction.east }}
a.set_recipe('sulfuric-acid')
local b = s.create_entity {{ name = 'chemical-plant', position = {{ {x0} + 14.5, {y0} + 3.5 }}, force = f }}
b.set_recipe('battery')
local d = s.create_entity {{ name = 'chemical-plant', position = {{ {x0} + 14.5, {y0} + 10.5 }}, force = f }}
d.set_recipe('sulfur')
local w = s.create_entity {{ name = 'pipe', position = {{ {x0} + 1.5, {y0} + 10.5 }}, force = f }}
w.insert_fluid {{ name = 'water', amount = 50 }}
-- pipes already on both of the acid plant's acid ports
local fb, out = a.fluidbox, {{}}
for i = 1, #fb do
  if fb.get_locked_fluid(i) == 'sulfuric-acid' then
    for _, pc in pairs(fb.get_pipe_connections(i)) do
      s.create_entity {{ name = 'pipe', position = pc.target_position, force = f }}
      out[#out + 1] = {{ pc.target_position.x, pc.target_position.y }}
    end
  end
end
local c = storage.agents['serf'].char
c.teleport({{ {x0} + 8.5, {y0} + 7.5 }})
c.get_main_inventory().clear()
c.insert {{ name = 'pipe', count = 80 }}
c.insert {{ name = 'pipe-to-ground', count = 10 }}
return out""")
    r = await Runner(g)._do_connect({"item": "pipe", "from": [x0 + 2.5, y0 + 3.5], "to": [x0 + 14.5, y0 + 3.5],
                                     "from_fluid": "sulfuric-acid", "to_fluid": "sulfuric-acid"})
    check("fluid ports: with pipes already on the acid ports, the line carries on from one",
          r.get("ok"), (r.get("msg"), ports))
    r2 = await Runner(g)._do_connect({"item": "pipe", "from": [x0 + 1.5, y0 + 10.5], "to": [x0 + 14.5, y0 + 10.5]})
    await asyncio.sleep(3)
    got = await L.ev(f"""
local d = game.surfaces.nauvis.find_entity('chemical-plant', {{ {x0} + 14.5, {y0} + 10.5 }})
local out = {{}}
for i = 1, #d.fluidbox do local fl = d.fluidbox[i] out[#out + 1] = (d.fluidbox.get_locked_fluid(i) or '?') .. '=' .. (fl and fl.name or 'empty') end
return table.concat(out, ' ')""")
    check("fluid ports: a plain water line to the middle of a sulfur plant lands on its water inlet",
          r2.get("ok") and "water=water" in str(got) and "petroleum-gas=water" not in str(got), (r2.get("msg"), got))
    # an empty pipe of some other line in the straight path: the water line goes round it, it doesn't join it (p2)
    x1, y1 = await L.site(14, 7)
    await L.ev(f"""
local s, f = game.surfaces.nauvis, game.forces.player
local w = s.create_entity {{ name = 'pipe', position = {{ {x1} + 0.5, {y1} + 3.5 }}, force = f }}
w.insert_fluid {{ name = 'water', amount = 50 }}
for dy = 2, 4 do s.create_entity {{ name = 'pipe', position = {{ {x1} + 6.5, {y1} + dy + 0.5 }}, force = f }} end
storage.agents['serf'].char.teleport({{ {x1} + 6.5, {y1} + 6.5 }})
return true""")
    r3 = await Runner(g)._do_connect({"item": "pipe", "from": [x1 + 1.5, y1 + 3.5], "to": [x1 + 12.5, y1 + 3.5]})
    await asyncio.sleep(2)
    dry = await L.ev(f"""
local n = 0
for dy = 2, 4 do
  local e = game.surfaces.nauvis.find_entity('pipe', {{ {x1} + 6.5, {y1} + dy + 0.5 }})
  if e and e.fluidbox[1] then n = n + 1 end
end
return n""")
    check("fluid ports: a water line goes round an empty pipe of another line instead of joining it",
          r3.get("ok") and dry == 0, (r3.get("msg"), dry))
    await L.ev("storage.agents['serf'].char.get_main_inventory().clear() return true")


async def chk_long_craft(L: Live, state: dict):
    g = L.g
    await L.ev("""
local c = storage.agents['serf'].char
c.get_main_inventory().clear()
c.insert { name = 'iron-plate', count = 100 }
return true""")
    t0 = time.monotonic()
    r = await g.run({"op": "craft", "recipe": "iron-gear-wheel", "count": 40}, timeout=5)
    secs = time.monotonic() - t0
    have = await L.ev("return storage.agents['serf'].char.get_item_count('iron-gear-wheel')")
    check("long craft: a craft longer than its timeout runs on while it's getting on (c1: 110 adv circuits)",
          r.get("ok") and have >= 40 and secs > 10, (r.get("msg"), have, round(secs)))
    await L.ev("storage.agents['serf'].char.get_main_inventory().clear() return true")


async def chk_rate(L: Live, state: dict):
    from types import SimpleNamespace
    from jev.actor import Actor
    from jev.world import World
    g = L.g
    x0, y0 = await L.site(8, 4)
    await L.ev(f"""
local s, f = game.surfaces.nauvis, game.forces.player
for i = 0, 1 do
  local fu = s.create_entity {{ name = 'stone-furnace', position = {{ {x0} + 1 + 3 * i, {y0} + 1 }}, force = f }}
  fu.insert {{ name = 'coal', count = 50 }}
  fu.get_inventory(defines.inventory.furnace_source).insert {{ name = 'iron-ore', count = 50 }}
end
return true""")

    async def world(center, radius):
        return World(await g.scan(center=center, radius=radius))
    a = SimpleNamespace(world=world)
    near = [x0 + 2.5, y0 + 1]
    ok30 = ok100 = None
    msg100 = ""
    t0 = time.monotonic()
    while time.monotonic() - t0 < 120 and (ok30 is None or ok100 is None):
        r30 = await Actor._check(a, {"check": "rate", "item": "iron-plate", "per_min": 30, "near": near, "radius": 4})
        r100 = await Actor._check(a, {"check": "rate", "item": "iron-plate", "per_min": 100, "near": near, "radius": 4})
        if "measuring" not in r30[1]:
            ok30 = r30[0]
        if "measuring" not in r100[1]:
            ok100, msg100 = r100
        await asyncio.sleep(6)
    check("rate: two stone furnaces make about 37 plates/min, so a 30/min target passes", ok30 is True, ok30)
    check("rate: ... and a 100/min target fails and says the measured rate", ok100 is False and "/min, want 100"
          in msg100, msg100)


async def chk_chunks(L: Live, state: dict):
    g = L.g
    edge_lua = """
local s, sp = game.surfaces.nauvis, game.forces.player.get_spawn_position(game.surfaces.nauvis)
local cy = math.floor(sp.y / 32)
local cx = math.floor(sp.x / 32)
while s.is_chunk_generated { cx, cy } do cx = cx + 1 end
return { cx * 32, sp.y }"""
    ex, ey = await L.ev(edge_lua)
    await L.ev(f"storage.agents['serf'].char.teleport({{{ex - 60}, {ey}}}) return true")
    pre = await L.ev(f"return game.surfaces.nauvis.is_chunk_generated {{ {(ex + 64) // 32}, {int(ey // 32)} }}")
    walk = await g.run({"op": "move", "x": ex - 10, "y": ey, "radius": 3}, timeout=60)
    await asyncio.sleep(4)
    post = await L.ev(f"local s = game.surfaces.nauvis local c = {{ {(ex + 64) // 32}, {int(ey // 32)} }} "
                      "return { s.is_chunk_generated(c), game.forces.player.is_chunk_charted(s, c) }")
    far = await g.run({"op": "move", "x": ex + 60, "y": ey, "radius": 3}, timeout=60)
    t0 = time.monotonic()
    longer = await g.run({"op": "move", "x": ex + 350, "y": ey, "radius": 3}, timeout=240)
    secs = time.monotonic() - t0
    check("chunks: one move to a point 350 tiles past the generated edge walks there in legs",
          longer.get("ok"), (longer.get("msg"), round(secs)))
    await L.ev("local s = game.surfaces.nauvis storage.agents['serf'].char.teleport("
               "game.forces.player.get_spawn_position(s)) return true")  # later checks look near the serf
    # (charting only runs while a player is connected, so a headless test can only see the generation)
    check("chunks: walking toward the edge of the map generates the ground 2-3 chunks ahead",
          walk.get("ok") and pre is False and post[0] is True, (walk.get("msg"), pre, post))
    check("chunks: ... so a move past the old edge finds a path", far.get("ok"), far.get("msg"))


async def chk_bus(L: Live, state: dict):
    from jev.busgen import Bus
    g = L.g
    x0, y0 = await L.site(24, 44)
    await L.ev("""local f = game.forces.player
for _, t in pairs { 'logistics', 'logistics-2' } do if f.technologies[t] then f.technologies[t].researched = true end end
local c = storage.agents['serf'].char
for n, k in pairs { ['transport-belt'] = 400, ['splitter'] = 10, ['underground-belt'] = 40 } do c.insert { name = n, count = k } end
return true""")
    await L.ev(f"storage.agents['serf'].char.teleport({{{x0 + 8}, {y0 + 10}}}) return true")
    runner = Runner(g, lambda r: None)
    lanes = ["iron-plate", "copper-plate", "stone", "coal", "spare"]
    hx, hy = x0 + 2.5, y0 + 0.5
    r = await runner.run({"do": "bus", "name": "lc", "x": hx, "y": hy, "direction": "south", "side": "east",
                          "lanes": lanes, "length": 40})
    check("bus: laid 4 lanes of 40 (one spare)", r.get("ok"), r.get("msg"))
    b = Bus(name="lc", x=hx, y=hy, direction="south", side="east", lanes=lanes, length=40)
    taps = {}
    for i, a in ((0, 6), (3, 12), (1, 18), (2, 24)):
        t = await runner.run({"do": "tap", "bus": "lc", "lane": lanes[i], "at": a, "run": 3})
        taps[i] = t.get("end")
        check(f"bus: tap lane {i} ({lanes[i]}) at row {a}", t.get("ok") and t.get("end"), t.get("msg"))
    # a gear belt coming from the side, to start the spare lane
    sx, sy = b.at(30, 4 * b.pairs + 6)
    await L.ev(f"""local s, f = game.surfaces.nauvis, game.forces.player
for k = 0, 3 do s.create_entity {{ name = 'transport-belt', position = {{ {sx} + k, {sy} }}, direction = defines.direction.west, force = f }} end
return true""")
    m = await runner.run({"do": "bus_in", "bus": "lc", "item": "iron-gear-wheel", "at": 29, "from": [sx, sy]})
    check("bus: bus_in starts the spare lane with gears from the side", m.get("ok"), m.get("msg"))
    heads = [b.at(0, b.u(i)) for i in range(4)] + [(sx + 3, sy)]
    items = lanes[:4] + ["iron-gear-wheel"]
    feed = "local s = game.surfaces.nauvis local ok = 0\n" + "\n".join(
        f"do local e = s.find_entity('transport-belt', {{{x}, {y}}}) if e then for l = 1, 2 do "
        f"if e.get_transport_line(l).insert_at_back({{ name = '{it}' }}) then ok = ok + 1 end end end end"
        for (x, y), it in zip(heads, items)) + "\nreturn ok"
    t0 = time.monotonic()
    while time.monotonic() - t0 < 45:
        await L.ev(feed)
        await asyncio.sleep(0.25)
    await asyncio.sleep(8)

    async def on(x, y):
        return await L.ev(f"""local s = game.surfaces.nauvis local out = {{}}
for _, e in pairs(s.find_entities_filtered {{ position = {{ {x}, {y} }}, type = {{ 'transport-belt', 'underground-belt', 'splitter' }} }}) do
  for l = 1, 2 do for _, c in pairs(e.get_transport_line(l).get_contents()) do out[c.name] = (out[c.name] or 0) + c.count end end
end
return out""") or {{}}
    for i, end in taps.items():
        if not end:
            continue
        got = await on(*end)
        check(f"bus: tap {i}'s belt end has {lanes[i]} and nothing else", set(got) == {lanes[i]}, got)
    for i, it in enumerate(items):
        x, y = b.at(39, b.u(i))
        got = await on(x, y)
        check(f"bus: lane {i}'s far end carries {it} only", set(got) == {it}, got)
    bb = (await runner.buses())["lc"]
    words = await runner.bus_flow(bb)
    check("bus: the lane readout covers every lane in use (5) and reads the fed ones as carrying items",
          len(words) == 5 and not any("empty" in w for w in words), words)


async def chk_row_extend(L: Live, state: dict):
    g = L.g
    x0, y0 = await L.site(18, 8)
    await L.ev(f"""local s, f = game.surfaces.nauvis, game.forces.player
for k = 0, 1 do s.create_entity {{ name = 'transport-belt', position = {{ {x0} + k + 0.5, {y0} + 0.5 }}, direction = defines.direction.east, force = f }} end
local eei = s.create_entity {{ name = 'electric-energy-interface', position = {{ {x0} - 3, {y0} + 3 }}, force = f }}
eei.power_production = 1e7 eei.electric_buffer_size = 1e8
s.create_entity {{ name = 'small-electric-pole', position = {{ {x0} - 1.5, {y0} + 1.5 }}, force = f }}
local c = storage.agents['serf'].char
for n, k in pairs {{ ['assembling-machine-1'] = 5, inserter = 12, ['transport-belt'] = 40, ['iron-chest'] = 5, ['small-electric-pole'] = 12 }} do c.insert {{ name = n, count = k }} end
c.teleport {{ {x0} + 6, {y0} - 2 }}
return true""")
    runner = Runner(g, lambda r: None)
    r = await runner.run({"do": "row", "belt": [x0 + 0.5, y0 + 0.5], "machine": "assembling-machine-1",
                          "recipe": "iron-gear-wheel", "count": 3, "side": "south"})
    check("row: built along a 2-tile belt, carrying the belt on", r.get("ok") and "carried on" in str(r.get("msg")),
          r.get("msg"))
    feed = (f"local e = game.surfaces.nauvis.find_entity('transport-belt', {{ {x0} + 0.5, {y0} + 0.5 }}) "
            "if e then for l = 1, 2 do e.get_transport_line(l).insert_at_back({ name = 'iron-plate' }) end end return true")
    t0 = time.monotonic()
    while time.monotonic() - t0 < 40:
        await L.ev(feed)
        await asyncio.sleep(0.3)
    got = await L.ev(f"""local n = 0
for _, a in pairs(game.surfaces.nauvis.find_entities_filtered {{ area = {{ {{ {x0}, {y0} }}, {{ {x0} + 18, {y0} + 8 }} }}, name = 'assembling-machine-1' }}) do
  if a.products_finished > 0 or a.get_inventory(defines.inventory.assembling_machine_input).get_item_count('iron-plate') > 0 then n = n + 1 end
end
return n""")
    check("row: every machine in the row gets plates (3 of 3)", got == 3, got)


async def chk_bus_adopt(L: Live, state: dict):
    g = L.g
    x0, y0 = await L.site(14, 24)
    await L.ev(f"""local s, f = game.surfaces.nauvis, game.forces.player
for k = 0, 19 do for _, u in pairs {{ 2, 3 }} do
  s.create_entity {{ name = 'transport-belt', position = {{ {x0} + u + 0.5, {y0} + k + 0.5 }}, direction = defines.direction.south, force = f }}
end end
local c = storage.agents['serf'].char
c.insert {{ name = 'transport-belt', count = 100 }}
c.teleport {{ {x0} + 8, {y0} + 4 }}
return true""")
    runner = Runner(g, lambda r: None)
    r = await runner.run({"do": "bus", "name": "adopt", "x": x0 + 2.5, "y": y0 + 0.5, "direction": "south",
                          "side": "east", "lanes": ["iron-plate", "copper-plate", "spare", "spare"], "length": 24})
    n = await L.ev(f"return game.surfaces.nauvis.count_entities_filtered {{ area = {{ {{ {x0}, {y0} }}, {{ {x0} + 14, {y0} + 24 }} }}, name = 'transport-belt' }}")
    check("bus: laid over two existing straight lanes, it adopts them and adds only the missing rows",
          r.get("ok") and n == 48, (r.get("msg"), n))


async def chk_fluid_port_taken(L: Live, state: dict):
    g = L.g
    res = {}
    for case in ("ptg", "inserter"):
        x0, y0 = await L.site(16, 12)
        pet = await L.ev(f"""
local s, f = game.surfaces.nauvis, game.forces.player
f.recipes['sulfur'].enabled = true
local d = s.create_entity {{ name = 'chemical-plant', position = {{ {x0} + 8.5, {y0} + 5.5 }}, force = f }}
d.set_recipe('sulfur')
local fb, port = d.fluidbox, nil
for i = 1, #fb do
  if fb.get_locked_fluid(i) == 'petroleum-gas' then port = fb.get_pipe_connections(i)[1].target_position end
end
local src = s.create_entity {{ name = 'pipe', position = {{ {x0} + 0.5, {y0} + 10.5 }}, force = f }}
src.insert_fluid {{ name = 'petroleum-gas', amount = 50 }}
s.create_entity {{ name = '{"pipe-to-ground" if case == "ptg" else "inserter"}', position = port, force = f,
  direction = defines.direction.south }}
local c = storage.agents['serf'].char
c.teleport({{ {x0} + 4.5, {y0} + 10.5 }})
c.insert {{ name = 'pipe', count = 60 }} c.insert {{ name = 'pipe-to-ground', count = 10 }}
return {{ port.x, port.y }}""")
        res[case] = await Runner(g)._do_connect({"item": "pipe", "from": [x0 + 0.5, y0 + 10.5],
                                                 "to": [x0 + 8.5, y0 + 5.5], "to_fluid": "petroleum-gas"})
    check("fluid ports: an empty pipe-to-ground on the inlet is joined, not reported as taken",
          "taken" not in str(res["ptg"].get("msg")), res["ptg"].get("msg"))
    check("fluid ports: with a building on the petroleum inlet, the failure names what's there",
          not res["inserter"].get("ok") and "taken by inserter at" in str(res["inserter"].get("msg")),
          res["inserter"].get("msg"))

async def chk_belt_end(L: Live, state: dict):
    g = L.g
    x0, y0 = await L.site(12, 14)
    await L.ev(f"""local s, f = game.surfaces.nauvis, game.forces.player
for k = 0, 2 do s.create_entity {{ name = 'transport-belt', position = {{ {x0} + k + 0.5, {y0} + 6.5 }}, direction = defines.direction.east, force = f }} end
s.create_entity {{ name = 'transport-belt', position = {{ {x0} + 3.5, {y0} + 0.5 }}, direction = defines.direction.south, force = f }}
local c = storage.agents['serf'].char
c.insert {{ name = 'transport-belt', count = 60 }} c.insert {{ name = 'underground-belt', count = 10 }}
c.teleport {{ {x0} + 8, {y0} + 6 }}
return true""")
    # the copper belt ends at x0+2 pointing east, into tile x0+3; the iron line runs down column x0+3 from its start
    r = await Runner(g)._do_connect({"item": "transport-belt", "from": [x0 + 3.5, y0 + 0.5], "to": [x0 + 3.5, y0 + 12.5]})
    on = await L.ev(f"""local e = game.surfaces.nauvis.find_entities_filtered {{ position = {{ {x0} + 3.5, {y0} + 6.5 }}, radius = 0.4, type = {{ 'transport-belt', 'splitter' }} }}
return #e""")
    feed = (f"local s = game.surfaces.nauvis "
            f"local a = s.find_entity('transport-belt', {{ {x0} + 0.5, {y0} + 6.5 }}) "
            f"local b = s.find_entity('transport-belt', {{ {x0} + 3.5, {y0} + 0.5 }}) "
            "for l = 1, 2 do if a then a.get_transport_line(l).insert_at_back({ name = 'copper-plate' }) end "
            "if b then b.get_transport_line(l).insert_at_back({ name = 'iron-plate' }) end end return true")
    t0 = time.monotonic()
    while time.monotonic() - t0 < 15:
        await L.ev(feed)
        await asyncio.sleep(0.4)
    await asyncio.sleep(8)
    cu = await L.ev(f"""local n = 0
for _, e in pairs(game.surfaces.nauvis.find_entities_filtered {{ area = {{ {{ {x0} + 2, {y0} + 9 }}, {{ {x0} + 6, {y0} + 14 }} }}, type = 'transport-belt' }}) do
  for l = 1, 2 do n = n + e.get_transport_line(l).get_item_count('copper-plate') end
end
return n""")
    check("belt routes: a new line keeps off the tile another belt's open end points into (no belt there)",
          r.get("ok") and on == 0, (r.get("msg"), on))
    check("belt routes: ... so none of that belt's copper reaches the new line's end", cu == 0, cu)


async def chk_block_pipe(L: Live, state: dict):
    g = L.g
    x0, y0 = await L.site(22, 26)
    await L.ev(f"""local f = game.forces.player
for _, t in pairs {{ 'fluid-handling', 'oil-gathering', 'oil-processing', 'plastics', 'sulfur-processing' }} do if f.technologies[t] then f.technologies[t].researched = true end end
local c = storage.agents['serf'].char
for n, k in pairs {{ ['oil-refinery'] = 3, ['chemical-plant'] = 2, ['fast-inserter'] = 3, pipe = 60, ['pipe-to-ground'] = 6, ['small-electric-pole'] = 6, ['transport-belt'] = 6 }} do c.insert {{ name = n, count = k }} end
c.teleport {{ {x0} + 8, {y0} + 18 }}
local src = game.surfaces.nauvis.create_entity {{ name = 'infinity-pipe', position = {{ {x0} + 8.5, {y0} + 22.5 }}, force = f }}
src.set_infinity_pipe_filter {{ name = 'crude-oil', percentage = 1, mode = 'at-least' }}
return true""")
    runner = Runner(g)
    b = await runner.run({"do": "block", "name": "plastic-sulfur-basic", "x": x0, "y": y0})
    r = await runner._do_connect({"item": "pipe", "from": [x0 + 8.5, y0 + 22.5], "to": [x0 + 8.5, y0 + 14.5]})
    await asyncio.sleep(6)
    crude = await L.ev(f"""local n = 0
for _, e in pairs(game.surfaces.nauvis.find_entities_filtered {{ area = {{ {{ {x0}, {y0} }}, {{ {x0} + 15, {y0} + 15 }} }}, name = 'oil-refinery' }}) do
  for i = 1, #e.fluidbox do local fl = e.fluidbox[i] if fl and fl.name == 'crude-oil' then n = n + 1 end end
end
return n""")
    check("pipes: a crude line joins a new block's empty input pipe (b6: 'end tile is blocked')",
          b.get("ok") and r.get("ok"), (b.get("msg"), r.get("msg")))
    check("pipes: ... and the block's refineries get crude", (crude or 0) >= 1, crude)
    # b7: a water line ending one tile outside the block's water port (east side, at 14,4)
    await L.ev(f"""local w = game.surfaces.nauvis.create_entity {{ name = 'infinity-pipe', position = {{ {x0} + 17.5, {y0} + 11.5 }}, force = game.forces.player }}
w.set_infinity_pipe_filter {{ name = 'water', percentage = 1, mode = 'at-least' }}
return true""")
    r2 = await runner._do_connect({"item": "pipe", "from": [x0 + 17.5, y0 + 11.5], "to": [x0 + 15.5, y0 + 4.5]})
    await asyncio.sleep(5)
    water = await L.ev(f"""local n = 0
for _, e in pairs(game.surfaces.nauvis.find_entities_filtered {{ area = {{ {{ {x0}, {y0} }}, {{ {x0} + 15, {y0} + 15 }} }}, name = 'chemical-plant' }}) do
  for i = 1, #e.fluidbox do local fl = e.fluidbox[i] if fl and fl.name == 'water' then n = n + 1 end end
end
return n""")
    check("pipes: a water line ending one tile outside the block's water port joins it (b7: 'end tile is blocked')",
          r2.get("ok") and (water or 0) >= 1, (r2.get("msg"), water))


async def chk_clear_guard(L: Live, state: dict):
    g = L.g
    x0, y0 = await L.site(12, 10)
    await L.ev(f"""local s, f = game.surfaces.nauvis, game.forces.player
for row = 0, 2 do for k = 0, 7 do
  s.create_entity {{ name = 'transport-belt', position = {{ {x0} + k + 0.5, {y0} + 2 * row + 1.5 }}, direction = defines.direction.east, force = f }}
end end
storage.agents['serf'].char.teleport {{ {x0} + 4, {y0} + 8 }}
return true""")
    runner = Runner(g)
    r = await runner.run({"do": "clear", "x": x0 + 4, "y": y0 + 3, "radius": 5, "only": ["transport-belt"]})
    left = await L.ev(f"return game.surfaces.nauvis.count_entities_filtered {{ area = {{ {{ {x0}, {y0} }}, {{ {x0} + 12, {y0} + 10 }} }}, name = 'transport-belt' }}")
    check("clear: a square holding 3 separate belt lines is refused and the lines are listed",
          not r.get("ok") and "3 separate belt lines" in str(r.get("msg")) and left == 24, (r.get("msg"), left))
    r2 = await runner.run({"do": "clear", "x": x0 + 4, "y": y0 + 3, "radius": 5, "only": ["transport-belt"],
                           "force": True})
    left2 = await L.ev(f"return game.surfaces.nauvis.count_entities_filtered {{ area = {{ {{ {x0}, {y0} }}, {{ {x0} + 12, {y0} + 10 }} }}, name = 'transport-belt' }}")
    check("clear: ... with force=true it takes them all", r2.get("ok") and left2 == 0, (r2.get("msg"), left2))


async def chk_clear_working(L: Live, state: dict):
    """A square clear over 3 working assemblers is refused (they'd stop); force=true takes them."""
    g = L.g
    x0, y0 = await L.site(14, 8)
    await L.ev(f"""local s, f = game.surfaces.nauvis, game.forces.player
local eei = s.create_entity {{ name = 'electric-energy-interface', position = {{ {x0} + 12, {y0} + 6 }}, force = f }}
eei.power_production = 1e7 eei.electric_buffer_size = 1e8
for k = 0, 2 do
  local m = s.create_entity {{ name = 'assembling-machine-2', position = {{ {x0} + 1.5 + 3 * k, {y0} + 1.5 }}, force = f, recipe = 'iron-gear-wheel' }}
  m.insert {{ name = 'iron-plate', count = 200 }}
end
s.create_entity {{ name = 'medium-electric-pole', position = {{ {x0} + 4.5, {y0} + 3.5 }}, force = f }}
s.create_entity {{ name = 'medium-electric-pole', position = {{ {x0} + 10.5, {y0} + 5.5 }}, force = f }}
storage.agents['serf'].char.teleport {{ {x0} + 4, {y0} + 6 }}
return true""")
    await asyncio.sleep(2)
    runner = Runner(g)
    count = (f"return game.surfaces.nauvis.count_entities_filtered {{ area = {{ {{ {x0}, {y0} }}, {{ {x0} + 10, {y0} + 4 }} }}, "
             f"name = 'assembling-machine-2' }}")
    r = await runner.run({"do": "clear", "x": x0 + 4.5, "y": y0 + 2, "radius": 5})
    left = await L.ev(count)
    check("clear: a square over 3 working machines is refused, and says what's working there",
          not r.get("ok") and "3 working machines" in str(r.get("msg")) and left == 3, (r.get("msg"), left))
    r2 = await runner.run({"do": "clear", "x": x0 + 4.5, "y": y0 + 2, "radius": 5, "force": True})
    left2 = await L.ev(count)
    check("clear: ... with force=true it takes them", r2.get("ok") and left2 == 0, (str(r2.get("msg"))[:120], left2))


async def chk_audit_lacks(L: Live, state: dict):
    """Starved assemblers: the audit says which ingredient they lack (p6's manager guessed sulfur; it was circuits)."""
    from jev import audit as base_audit
    g = L.g
    x0, y0 = await L.site(12, 6)
    await L.ev(f"""local s, f = game.surfaces.nauvis, game.forces.player
f.technologies['electronics'].researched = true
local eei = s.create_entity {{ name = 'electric-energy-interface', position = {{ {x0} + 10, {y0} + 4 }}, force = f }}
eei.power_production = 1e7 eei.electric_buffer_size = 1e8
for k = 0, 1 do
  local m = s.create_entity {{ name = 'assembling-machine-2', position = {{ {x0} + 1.5 + 3 * k, {y0} + 1.5 }}, force = f, recipe = 'electronic-circuit' }}
  m.insert {{ name = 'copper-cable', count = 60 }}
end
s.create_entity {{ name = 'medium-electric-pole', position = {{ {x0} + 3.5, {y0} + 3.5 }}, force = f }}
s.create_entity {{ name = 'medium-electric-pole', position = {{ {x0} + 8.5, {y0} + 3.5 }}, force = f }}
return true""")
    await asyncio.sleep(3)
    a = await g.call("audit", timeout=90)
    grp = (a.get("groups") or {}).get("electronic-circuit") or {}
    w = base_audit.words(a)
    line = next((x for x in w.splitlines() if x.startswith("- electronic-circuit")), "")
    print("   ", line)
    import tempfile
    from jev.actor import Actor
    from jev.typesafe import reader
    d = Path(tempfile.mkdtemp())
    act = Actor(g, reader(log_path=d / "jev.jsonl"), d, "serf", think=False)
    rec = await g.call("recipes", agent="serf", detail=True)
    act.recipes = rec.get("recipes") or {}
    ok, why = await act._check({"check": "working", "recipe": "electronic-circuit", "near": [x0 + 3, y0 + 1.5],
                                "radius": 6, "count": 2})
    print("   ", why)
    check("working check: names the ingredient the starved machines lack", not ok and "short of iron-plate in 2" in why,
          why)
    check("audit: starved circuit assemblers say they lack iron plates (they hold cables)",
          (grp.get("lacks") or {}).get("iron-plate", 0) >= 2 and "copper-cable" not in (grp.get("lacks") or {})
          and "lacking iron-plate" in line, grp)


async def chk_pipe_gap(L: Live, state: dict):
    g = L.g
    x0, y0 = await L.site(16, 6)
    await L.ev(f"""local s, f = game.surfaces.nauvis, game.forces.player
local src = s.create_entity {{ name = 'infinity-pipe', position = {{ {x0} + 0.5, {y0} + 2.5 }}, force = f }}
src.set_infinity_pipe_filter {{ name = 'crude-oil', percentage = 1, mode = 'at-least' }}
for k = 1, 5 do s.create_entity {{ name = 'pipe', position = {{ {x0} + k + 0.5, {y0} + 2.5 }}, force = f }} end
for k = 7, 10 do s.create_entity {{ name = 'pipe', position = {{ {x0} + k + 0.5, {y0} + 2.5 }}, force = f }} end
-- a line that just ends, nothing past it
local src2 = s.create_entity {{ name = 'infinity-pipe', position = {{ {x0} + 0.5, {y0} + 4.5 }}, force = f }}
src2.set_infinity_pipe_filter {{ name = 'water', percentage = 1, mode = 'at-least' }}
for k = 1, 4 do s.create_entity {{ name = 'pipe', position = {{ {x0} + k + 0.5, {y0} + 4.5 }}, force = f }} end
return true""")
    await asyncio.sleep(3)
    a = await g.call("audit", timeout=90)
    gaps = [q for q in (a.get("pipe_gaps") or []) if x0 <= q["at"][0] <= x0 + 16 and y0 <= q["at"][1] <= y0 + 6]
    check("audit: a crude line stopping 1 tile short of an empty pipe is reported as a gap, a plain end isn't",
          len(gaps) == 1 and gaps[0]["fluid"] == "crude-oil" and gaps[0]["gap"] == 1, gaps)


async def chk_fluid_trace(L: Live, state: dict):
    """Two machines missing water: one behind a 1-tile gap in its line, one behind an underground with no exit (the
    next pipe-to-ground faces the wrong way). The audit traces both; the pipes op follows a line from its source."""
    from jev import audit as base_audit
    g = L.g
    x0, y0 = await L.site(24, 10)
    await L.ev(f"""local s, f = game.surfaces.nauvis, game.forces.player
f.technologies['concrete'].researched = true
local eei = s.create_entity {{ name = 'electric-energy-interface', position = {{ {x0} + 10, {y0} + 9 }}, force = f }}
eei.power_production = 1e7 eei.electric_buffer_size = 1e8
for _, x in pairs {{ 6.5, 12.5, 18.5 }} do s.create_entity {{ name = 'medium-electric-pole', position = {{ {x0} + x, {y0} + 8.5 }}, force = f }} end
local function am(x)
  local m = s.create_entity {{ name = 'assembling-machine-2', position = {{ {x0} + x, {y0} + 6.5 }}, force = f, recipe = 'concrete' }}
  m.insert {{ name = 'stone-brick', count = 50 }} m.insert {{ name = 'iron-ore', count = 20 }}
end
am(3.5) am(16.5)
local src = s.create_entity {{ name = 'infinity-pipe', position = {{ {x0} + 10.5, {y0} + 1.5 }}, force = f }}
src.set_infinity_pipe_filter {{ name = 'water', percentage = 1, mode = 'at-least' }}
for x = 6, 9 do s.create_entity {{ name = 'pipe', position = {{ {x0} + x + 0.5, {y0} + 1.5 }}, force = f }} end
for _, q in pairs {{ {{4.5, 1.5}}, {{3.5, 1.5}}, {{3.5, 2.5}}, {{3.5, 3.5}}, {{3.5, 4.5}} }} do
  s.create_entity {{ name = 'pipe', position = {{ {x0} + q[1], {y0} + q[2] }}, force = f }}
end
s.create_entity {{ name = 'pipe-to-ground', position = {{ {x0} + 16.5, {y0} + 4.5 }}, direction = defines.direction.south, force = f }}
s.create_entity {{ name = 'pipe-to-ground', position = {{ {x0} + 16.5, {y0} + 1.5 }}, direction = defines.direction.south, force = f }}
return true""")
    await asyncio.sleep(3)
    a = await g.call("audit", timeout=90)
    br = [b for b in (a.get("fluid_breaks") or []) if isinstance(b, dict)
          and x0 <= b["machine"]["p"][0] <= x0 + 24 and y0 <= b["machine"]["p"][1] <= y0 + 10]
    words = [base_audit.break_words(b) for b in br]
    for w in words:
        print("   ", w)
    gap = [b for b in br if any((e.get("further") or {}).get("gap") == 1 and (e.get("further") or {}).get("fluid") == "water"
                                for e in b["line"].get("ends") or [])]
    ug = [b for b in br if any(e.get("kind") == "underground, no exit" and (e.get("further") or {}).get("dir") == "south"
                               for e in b["line"].get("ends") or [])]
    check("pipes: the audit traces both dry machines' lines (a 1-tile gap to a water pipe; an underground whose "
          "next pipe-to-ground faces the wrong way)",
          len(br) == 2 and all(b["why"] == "missing" and b["fluid"] == "water" for b in br) and gap and ug,
          [(b["machine"]["p"], b["why"], b["fluid"]) for b in br])
    r = await g.call("pipes", x=x0 + 10.5, y=y0 + 1.5)
    net = (r.get("lines") or [{}])[0]
    ends = net.get("ends") or []
    print("   ", base_audit.line_words(net))
    check("pipes: from the source, the water line is 5 pieces holding water and ends 1 tile short of the dry pipe",
          net.get("fluid") == "water" and net.get("pipes") == 5
          and any((e.get("further") or {}).get("gap") == 1 and e.get("toward") == "west" for e in ends), net)
    import tempfile
    from jev.actor import Actor
    from jev.typesafe import reader
    d = Path(tempfile.mkdtemp())
    act = Actor(g, reader(log_path=d / "jev.jsonl"), d, "serf", think=False)
    txt = await act._thinker_tools()["pipes"]({"x": x0 + 3.5, "y": y0 + 6.5})
    print("   ", txt.replace("\n", "\n    "))
    check("pipes tool: from the dry machine it follows the line past the gap to the water beyond",
          "past the break at" in txt and "holding water" in txt.split("past the break at", 1)[1], txt[:300])


async def chk_long_pipe(L: Live, state: dict):
    """A 330-tile crude line is one segment too long to flow (2.0: over 320 tiles nothing comes out); the audit names
    it and the pipes op flags it. A 290-tile line isn't flagged."""
    from jev import audit as base_audit
    g = L.g
    await L.ev("""local s, f = game.surfaces.nauvis, game.forces.player
local X0, Y0 = 3000, 3000
s.request_to_generate_chunks({ X0 + 170, Y0 }, 8)
s.force_generate_chunk_requests()
local tiles = {}
for x = X0 - 2, X0 + 340 do for y = Y0 - 2, Y0 + 6 do tiles[#tiles + 1] = { name = 'refined-concrete', position = { x, y } } end end
s.set_tiles(tiles)
for _, e in pairs(s.find_entities_filtered { area = { { X0 - 2, Y0 - 2 }, { X0 + 340, Y0 + 6 } } }) do
  if e.type ~= 'character' then e.destroy() end
end
for i, n in ipairs { 330, 290 } do
  local y = Y0 + 0.5 + (i - 1) * 3
  local src = s.create_entity { name = 'infinity-pipe', position = { X0 + 0.5, y }, force = f }
  src.set_infinity_pipe_filter { name = 'crude-oil', percentage = 1, mode = 'at-least' }
  for k = 1, n do s.create_entity { name = 'pipe', position = { X0 + k + 0.5, y }, force = f } end
end
return true""")
    await asyncio.sleep(2)
    a = await g.call("audit", timeout=90)
    lp = [x for x in (a.get("long_pipes") or []) if isinstance(x, dict) and x["from"][1] >= 3000]
    for x in lp:
        print("   ", base_audit.long_words(x))
    check("pipes: the audit names a 330-tile crude segment as too long to flow, not a 290-tile one",
          len(lp) == 1 and lp[0]["span"] >= 330 and lp[0]["fluid"] == "crude-oil", lp)
    r = await g.call("pipes", x=3100.5, y=3000.5)
    net = (r.get("lines") or [{}])[0]
    check("pipes: tracing the long line flags its segment too", bool(net.get("long"))
          and "nothing comes out" in base_audit.line_words(net), net.get("long"))


async def chk_end_ref(L: Live, state: dict):
    """A plan that taps a bus and builds a row on the tap's end via "end:1", run by the actor's plan loop."""
    import tempfile
    from jev.actor import Actor, Order
    from jev.typesafe import reader
    g = L.g
    x0, y0 = await L.site(28, 30)
    await L.ev(f"""local s, f = game.surfaces.nauvis, game.forces.player
for _, t in pairs {{ 'logistics', 'automation', 'automation-2' }} do if f.technologies[t] then f.technologies[t].researched = true end end
local c = storage.agents['serf'].char
for n, k in pairs {{ ['transport-belt'] = 200, ['splitter'] = 4, ['underground-belt'] = 20, ['assembling-machine-2'] = 4,
  inserter = 20, ['iron-chest'] = 6, ['small-electric-pole'] = 20 }} do c.insert {{ name = n, count = k }} end
local eei = s.create_entity {{ name = 'electric-energy-interface', position = {{ {x0} + 26, {y0} + 2 }}, force = f }}
eei.power_production = 1e7 eei.electric_buffer_size = 1e8
s.create_entity {{ name = 'small-electric-pole', position = {{ {x0} + 24.5, {y0} + 2.5 }}, force = f }}
c.teleport {{ {x0} + 12, {y0} + 4 }}
return true""")
    runner = Runner(g, lambda r: None)
    r = await runner.run({"do": "bus", "name": "ref", "x": x0 + 2.5, "y": y0 + 0.5, "direction": "south", "side": "east",
                          "lanes": ["iron-plate", "copper-plate"], "length": 26})
    d = Path(tempfile.mkdtemp())
    a = Actor(g, reader(log_path=d / "jev.jsonl"), d, "serf", think=False)
    o = Order(id=1, text="test", speaker="ops", playbook="plan", points=[(x0 + 10, y0 + 10)])
    o.built_pts = []
    ok, msg = await a._run_plan(o, {"goal": "gears off the iron tap", "steps": [
        {"do": "tap", "bus": "ref", "lane": "iron-plate", "at": 6},
        {"do": "row", "belt": "end:1", "machine": "assembling-machine-2", "recipe": "iron-gear-wheel", "count": 2}]})
    n = await L.ev(f"return game.surfaces.nauvis.count_entities_filtered {{ area = {{ {{ {x0}, {y0} }}, {{ {x0} + 28, {y0} + 30 }} }}, name = 'assembling-machine-2' }}")
    check("refs: a row built on the end of a tap in the same plan (\"end:1\")", r.get("ok") and ok and n == 2,
          (r.get("msg", "")[:80], ok, str(msg)[:200], n))


async def chk_split_start(L: Live, state: dict):
    g = L.g
    x0, y0 = await L.site(16, 18)
    await L.ev(f"""local s, f = game.surfaces.nauvis, game.forces.player
for _, t in pairs {{ 'logistics' }} do if f.technologies[t] then f.technologies[t].researched = true end end
for k = 0, 12 do
  if k ~= 3 then s.create_entity {{ name = 'transport-belt', position = {{ {x0} + 2.5, {y0} + k + 0.5 }}, direction = defines.direction.south, force = f }} end
  s.create_entity {{ name = 'transport-belt', position = {{ {x0} + 4.5, {y0} + k + 0.5 }}, direction = defines.direction.south, force = f }}
end
s.create_entity {{ name = 'splitter', position = {{ {x0} + 3, {y0} + 3.5 }}, direction = defines.direction.south, force = f }}
local c = storage.agents['serf'].char
c.insert {{ name = 'transport-belt', count = 80 }} c.insert {{ name = 'underground-belt', count = 10 }}
c.teleport {{ {x0} + 8, {y0} + 8 }}
return true""")
    r = await Runner(g)._do_connect({"item": "transport-belt", "from": [x0 + 3.5, y0 + 4.5], "to": [x0 + 12.5, y0 + 4.5]})
    ent = await L.ev(f"""local e = game.surfaces.nauvis.find_entities_filtered {{ position = {{ {x0} + 3.5, {y0} + 4.5 }}, radius = 0.4 }}[1]
return e and (e.name .. ' ' .. e.direction) or 'none'""")
    feed = (f"local s = game.surfaces.nauvis local a = s.find_entity('transport-belt', {{ {x0} + 2.5, {y0} + 0.5 }}) "
            f"local b = s.find_entity('transport-belt', {{ {x0} + 4.5, {y0} + 0.5 }}) "
            "for l = 1, 2 do if a then a.get_transport_line(l).insert_at_back({ name = 'iron-plate' }) end "
            "if b then b.get_transport_line(l).insert_at_back({ name = 'copper-plate' }) end end return true")
    t0 = time.monotonic()
    while time.monotonic() - t0 < 25:
        await L.ev(feed)
        await asyncio.sleep(0.4)
    await asyncio.sleep(10)
    got = await L.ev(f"""local out = {{}}
for _, e in pairs(game.surfaces.nauvis.find_entities_filtered {{ area = {{ {{ {x0} + 10, {y0} }}, {{ {x0} + 14, {y0} + 18 }} }}, type = 'transport-belt' }}) do
  for l = 1, 2 do for _, c in pairs(e.get_transport_line(l).get_contents()) do out[c.name] = (out[c.name] or 0) + c.count end end
end
return out""")
    check("splitter start: the line from a splitter's side output doesn't start with a sideways underground entrance",
          r.get("ok") and not str(ent).startswith("underground-belt"), (r.get("msg"), ent))
    check("splitter start: ... and the split-off iron (only) reaches its end", (got or {}).get("iron-plate", 0) > 0
          and "copper-plate" not in (got or {}), got)


async def chk_power_big(L: Live, state: dict):
    g = L.g
    x0, y0 = await L.site(26, 14)
    y0 += 2
    await L.ev(f"""local s, f = game.surfaces.nauvis, game.forces.player
for _, t in pairs {{ 'oil-processing', 'fluid-handling' }} do if f.technologies[t] then f.technologies[t].researched = true end end
local eei = s.create_entity {{ name = 'electric-energy-interface', position = {{ {x0} + 2, {y0} + 6 }}, force = f }}
eei.power_production = 1e7 eei.electric_buffer_size = 1e8
-- p7's case: the live pole 6 tiles from the refinery's centre (in wire reach of it, its supply short of the edge)
s.create_entity {{ name = 'small-electric-pole', position = {{ {x0} + 3.5, {y0} + 4.5 }}, force = f }}
for k = 1, 2 do s.create_entity {{ name = 'small-electric-pole', position = {{ {x0} + 3.5 + 7 * k, {y0} + 4.5 - k }}, force = f }} end
s.create_entity {{ name = 'small-electric-pole', position = {{ {x0} + 19.5, {y0} + 0.5 }}, force = f }}
local r = s.create_entity {{ name = 'oil-refinery', position = {{ {x0} + 19.5, {y0} + 6.5 }}, force = f }}
r.set_recipe('basic-oil-processing')
local c = storage.agents['serf'].char
c.insert {{ name = 'small-electric-pole', count = 20 }}
c.teleport {{ {x0} + 10, {y0} + 10 }}
return true""")
    r = await Runner(g).run({"do": "power", "x": x0 + 19.5, "y": y0 + 6.5})
    st = await L.ev(f"""local e = game.surfaces.nauvis.find_entity('oil-refinery', {{ {x0} + 19.5, {y0} + 6.5 }})
return e.is_connected_to_electric_network()""")
    check("power: a pole line aimed at the middle of a 5x5 refinery ends beside it and powers it",
          r.get("ok") and st is True, (r.get("msg"), st))


async def chk_ore_left(L: Live, state: dict):
    g = L.g
    spot = await L.ev("""local s, c = game.surfaces.nauvis, storage.agents['serf'].char
local r = s.find_entities_filtered { position = c.position, radius = 200, name = 'iron-ore', limit = 1 }[1]
if not r then return nil end
for k = 0, 1 do s.create_entity { name = 'electric-mining-drill', position = { r.position.x + 3 * k, r.position.y }, force = game.forces.player } end
return { r.position.x, r.position.y }""")
    if not spot:
        check("audit ore: an iron patch near spawn", False, "none within 200 tiles")
        return
    a = await g.call("audit", timeout=90)
    near = [o for o in (a.get("ore_left") or []) if o["ore"] == "iron-ore" and abs(o["at"][0] - spot[0]) < 70
            and abs(o["at"][1] - spot[1]) < 70]
    check("audit ore: drills on an iron patch report the ore under them and hours left",
          near and near[0]["drills"] >= 2 and near[0]["amount"] > 0 and near[0].get("minutes") is not None, near)


async def chk_bus_feed(L: Live, state: dict):
    from jev.busgen import Bus
    g = L.g
    x0, y0 = await L.site(40, 20)
    await L.ev(f"""local s, f = game.surfaces.nauvis, game.forces.player
if f.technologies['logistics'] then f.technologies['logistics'].researched = true end
-- two supply lines from the south-west, ending 2 tiles apart, both heading east
for k = 0, 3 do
  s.create_entity {{ name = 'transport-belt', position = {{ {x0} + k + 0.5, {y0} + 14.5 }}, direction = defines.direction.east, force = f }}
  s.create_entity {{ name = 'transport-belt', position = {{ {x0} + k + 0.5, {y0} + 16.5 }}, direction = defines.direction.east, force = f }}
end
local c = storage.agents['serf'].char
c.insert {{ name = 'transport-belt', count = 200 }} c.insert {{ name = 'underground-belt', count = 20 }}
c.teleport {{ {x0} + 12, {y0} + 12 }}
return true""")
    runner = Runner(g, lambda r: None)
    r = await runner.run({"do": "bus", "name": "fd", "x": x0 + 16.5, "y": y0 + 6.5, "direction": "east", "side": "south",
                          "lanes": ["iron-plate", "copper-plate"], "length": 20})
    f0 = await runner.run({"do": "feed", "bus": "fd", "lane": 0, "from": [x0 + 3.5, y0 + 14.5]})
    f1 = await runner.run({"do": "feed", "bus": "fd", "lane": 1, "from": [x0 + 3.5, y0 + 16.5]})
    feed = (f"local s = game.surfaces.nauvis "
            f"local a = s.find_entity('transport-belt', {{ {x0} + 0.5, {y0} + 14.5 }}) "
            f"local b = s.find_entity('transport-belt', {{ {x0} + 0.5, {y0} + 16.5 }}) "
            "for l = 1, 2 do if a then a.get_transport_line(l).insert_at_back({ name = 'iron-plate' }) end "
            "if b then b.get_transport_line(l).insert_at_back({ name = 'copper-plate' }) end end return true")
    t0 = time.monotonic()
    while time.monotonic() - t0 < 35:
        await L.ev(feed)
        await asyncio.sleep(0.4)
    await asyncio.sleep(12)
    b = Bus(name="fd", x=x0 + 16.5, y=y0 + 6.5, direction="east", side="south", lanes=["iron-plate", "copper-plate"],
            length=20)
    ends = []
    for i in (0, 1):
        x, y = b.at(19, b.u(i))
        ends.append(await L.ev(f"""local e = game.surfaces.nauvis.find_entity('transport-belt', {{ {x}, {y} }}) local out = {{}}
if e then for l = 1, 2 do for _, c in pairs(e.get_transport_line(l).get_contents()) do out[c.name] = (out[c.name] or 0) + c.count end end end
return out""") or {})
    check("feed: two supply lines from the same side feed the two lanes of a pair (bus laid, both feeds ok)",
          r.get("ok") and f0.get("ok") and f1.get("ok"), (f0.get("msg", "")[:200], f1.get("msg", "")[:200]))
    check("feed: ... lane 0 carries only iron and lane 1 only copper to the far end",
          set(ends[0]) == {"iron-plate"} and set(ends[1]) == {"copper-plate"}, ends)


async def chk_tap_opposite(L: Live, state: dict):
    from jev.busgen import Bus
    g = L.g
    x0, y0 = await L.site(30, 30)
    await L.ev(f"""local f = game.forces.player
if f.technologies['logistics'] then f.technologies['logistics'].researched = true end
local c = storage.agents['serf'].char
for n, k in pairs {{ ['transport-belt'] = 200, ['splitter'] = 6, ['underground-belt'] = 30 }} do c.insert {{ name = n, count = k }} end
c.teleport {{ {x0} + 22, {y0} + 10 }}
return true""")
    runner = Runner(g, lambda r: None)
    lanes = ["iron-plate", "copper-plate", "stone", "spare"]
    hx, hy = x0 + 12.5, y0 + 0.5
    await runner.run({"do": "bus", "name": "op", "x": hx, "y": hy, "direction": "south", "side": "east",
                      "lanes": lanes, "length": 28})
    t = await runner.run({"do": "tap", "bus": "op", "lane": "copper-plate", "at": 8, "side": "opposite", "run": 3})
    b = Bus(name="op", x=hx, y=hy, direction="south", side="east", lanes=lanes, length=28)
    heads = [b.at(0, b.u(i)) for i in range(3)]
    feed = "local s = game.surfaces.nauvis\n" + "\n".join(
        f"do local e = s.find_entity('transport-belt', {{{x}, {y}}}) if e then for l = 1, 2 do "
        f"e.get_transport_line(l).insert_at_back({{ name = '{it}' }}) end end end"
        for (x, y), it in zip(heads, lanes[:3])) + "\nreturn true"
    t0 = time.monotonic()
    while time.monotonic() - t0 < 30:
        await L.ev(feed)
        await asyncio.sleep(0.3)
    await asyncio.sleep(8)
    end = t.get("end") or [0, 0]
    got = await L.ev(f"""local e = game.surfaces.nauvis.find_entity('transport-belt', {{ {end[0]}, {end[1]} }}) local out = {{}}
if e then for l = 1, 2 do for _, c in pairs(e.get_transport_line(l).get_contents()) do out[c.name] = (out[c.name] or 0) + c.count end end end
return out""") or {}
    check("tap side=opposite: copper comes off on the west side (the bus's taps are east) and only copper",
          t.get("ok") and end[0] < hx and set(got) == {"copper-plate"}, (t.get("msg", "")[:160], end, got))


async def chk_supply(L: Live, state: dict):
    """supply: a block's two-lane input (iron left, copper right) fed off a bus by two taps and a lane merge; the
    belt into the input carries iron on its left lane and copper on its right (the block itself isn't built)."""
    from jev import blueprints as bp
    from jev.busgen import Bus
    g = L.g
    x0, y0 = await L.site(40, 40)
    await L.ev(f"""local f = game.forces.player
if f.technologies['logistics'] then f.technologies['logistics'].researched = true end
local c = storage.agents['serf'].char
for n, k in pairs {{ ['transport-belt'] = 300, ['splitter'] = 6, ['underground-belt'] = 30 }} do c.insert {{ name = n, count = k }} end
c.teleport {{ {x0} + 12, {y0} + 10 }}
return true""")
    runner = Runner(g, lambda r: None)
    lanes = ["iron-plate", "copper-plate"]
    hx, hy = x0 + 3.5, y0 + 0.5
    await runner.run({"do": "bus", "name": "sup", "x": hx, "y": hy, "direction": "south", "side": "east",
                      "lanes": lanes, "length": 36})
    bx, by = x0 + 16, y0 + 14
    r = await runner.run({"do": "supply", "name": "electronic-circuit-3-2", "x": bx, "y": by, "bus": "sup"})
    print("   ", str(r.get("msg"))[:300])
    b = Bus(name="sup", x=hx, y=hy, direction="south", side="east", lanes=lanes, length=36)
    heads = [b.at(0, b.u(i)) for i in range(2)]
    feed = "local s = game.surfaces.nauvis\n" + "\n".join(
        f"do local e = s.find_entity('transport-belt', {{{x}, {y}}}) if e then for l = 1, 2 do "
        f"e.get_transport_line(l).insert_at_back({{ name = '{it}' }}) end end end"
        for (x, y), it in zip(heads, lanes)) + "\nreturn true"
    t0 = time.monotonic()
    while time.monotonic() - t0 < 45:
        await L.ev(feed)
        await asyncio.sleep(0.3)
    await asyncio.sleep(15)
    p = bp.stamp("electronic-circuit-3-2", bx, by, 0)["inputs"][0]
    ex, ey = p["at"][0] - 1 + 0.5, p["at"][1] + 0.5  # fed from the west
    got = await L.ev(f"""local e = game.surfaces.nauvis.find_entity('transport-belt', {{ {ex}, {ey} }}) local out = {{}}
if e then for l = 1, 2 do local t = {{}} for _, c in pairs(e.get_transport_line(l).get_contents()) do t[c.name] = c.count end out[l] = t end
out.d = e.direction end
return out""") or {}
    left, right = set((got.get("1") or got.get(1) or {})), set((got.get("2") or got.get(2) or {}))
    if not (left and right):
        from jev.world import World
        w = World(await g.scan(center=(x0 + 16, y0 + 16), radius=22))
        for ln in w.lines:
            print(f"    line {ln.id}: {ln.length} tiles {ln.start} -> {ln.end} items={ln.items} end: {ln.end_reason}")
    check("supply: the block's input is fed iron on the left lane and copper on the right, from two taps",
          r.get("ok") and left == {"iron-plate"} and right == {"copper-plate"}, (str(r.get("msg"))[:200], got))


async def chk_supply_far(L: Live, state: dict):
    """supply on the bus's far side: the advanced-circuit block turned 180 (inputs face east, toward the bus) west of a
    bus whose taps normally come out east. Its plastic + circuit input gets plastic left, circuits right; its copper
    input gets copper."""
    from jev import blueprints as bp
    from jev.busgen import Bus
    g = L.g
    x0, y0 = await L.site(48, 40)
    await L.ev(f"""local f = game.forces.player
if f.technologies['logistics'] then f.technologies['logistics'].researched = true end
local c = storage.agents['serf'].char
for n, k in pairs {{ ['transport-belt'] = 300, ['splitter'] = 6, ['underground-belt'] = 30 }} do c.insert {{ name = n, count = k }} end
c.teleport {{ {x0} + 30, {y0} + 10 }}
return true""")
    runner = Runner(g, lambda r: None)
    lanes = ["copper-plate", "plastic-bar", "electronic-circuit", "spare"]
    hx, hy = x0 + 32.5, y0 + 0.5
    await runner.run({"do": "bus", "name": "far", "x": hx, "y": hy, "direction": "south", "side": "east",
                      "lanes": lanes, "length": 38})
    bx, by = x0 + 2, y0 + 16
    r = await runner.run({"do": "supply", "name": "advanced-circuit-block", "x": bx, "y": by, "rotation": 180,
                          "bus": "far"})
    print("   ", str(r.get("msg"))[:400])
    b = Bus(name="far", x=hx, y=hy, direction="south", side="east", lanes=lanes, length=38)
    heads = [b.at(0, b.u(i)) for i in range(3)]
    feed = "local s = game.surfaces.nauvis\n" + "\n".join(
        f"do local e = s.find_entity('transport-belt', {{{x}, {y}}}) if e then for l = 1, 2 do "
        f"e.get_transport_line(l).insert_at_back({{ name = '{it}' }}) end end end"
        for (x, y), it in zip(heads, lanes[:3])) + "\nreturn true"
    t0 = time.monotonic()
    while time.monotonic() - t0 < 50:
        await L.ev(feed)
        await asyncio.sleep(0.3)
    await asyncio.sleep(15)
    got = []
    for p in bp.stamp("advanced-circuit-block", bx, by, 180)["inputs"]:
        ex, ey = p["at"][0] + 1 + 0.5, p["at"][1] + 0.5  # fed from the east
        got.append(await L.ev(f"""local e = game.surfaces.nauvis.find_entity('transport-belt', {{ {ex}, {ey} }}) local out = {{}}
if e then for l = 1, 2 do local t = {{}} for _, c in pairs(e.get_transport_line(l).get_contents()) do t[c.name] = c.count end out[l] = t end end
return out""") or {})
    def lanes2(o, k):  # a Lua {1 = .., 2 = ..} comes back as a list or a dict
        if isinstance(o, list):
            v = o[k - 1] if len(o) >= k else {}
        else:
            v = o.get(str(k)) or o.get(k) or {}
        return set(v) if isinstance(v, dict) else set()
    ok2 = lanes2(got[0], 1) == {"plastic-bar"} and lanes2(got[0], 2) == {"electronic-circuit"}
    ok1 = (lanes2(got[1], 1) | lanes2(got[1], 2)) == {"copper-plate"}
    if not (ok1 and ok2):
        from jev.world import World
        w = World(await g.scan(center=(x0 + 24, y0 + 20), radius=26))
        for ln in w.lines:
            print(f"    line {ln.id}: {ln.length} tiles {ln.start} -> {ln.end} items={ln.items} end: {ln.end_reason}")
    check("supply far side: plastic left and circuits right on one input, copper on the other, tapped out west",
          r.get("ok") and ok1 and ok2, (str(r.get("msg"))[:200], got))


async def chk_supply_silo(L: Live, state: dict):
    """supply on the rocket silo block (two-lane input entering from the north, a one-item input from the west): the
    north input carries processing units on its left lane and low density structures on its right, nothing mixed
    (b13: LDS reached the PU lane)."""
    from jev import blueprints as bp
    from jev.busgen import Bus
    from jev.busgen import DIRS as BD
    g = L.g
    x0, y0 = await L.site(44, 44)
    await L.ev(f"""local f = game.forces.player
if f.technologies['logistics'] then f.technologies['logistics'].researched = true end
local c = storage.agents['serf'].char
for n, k in pairs {{ ['transport-belt'] = 300, ['splitter'] = 6, ['underground-belt'] = 30 }} do c.insert {{ name = n, count = k }} end
c.teleport {{ {x0} + 14, {y0} + 10 }}
return true""")
    runner = Runner(g, lambda r: None)
    lanes = ["processing-unit", "low-density-structure", "rocket-fuel", "spare"]
    hx, hy = x0 + 3.5, y0 + 0.5
    await runner.run({"do": "bus", "name": "sil", "x": hx, "y": hy, "direction": "south", "side": "east",
                      "lanes": lanes, "length": 40})
    bx, by = x0 + 22, y0 + 18
    r = await runner.run({"do": "supply", "name": "rocket-silo-feed", "x": bx, "y": by, "bus": "sil"})
    print("   ", str(r.get("msg"))[:300])
    b = Bus(name="sil", x=hx, y=hy, direction="south", side="east", lanes=lanes, length=40)
    heads = [b.at(0, b.u(i)) for i in range(3)]
    feed = "local s = game.surfaces.nauvis\n" + "\n".join(
        f"do local e = s.find_entity('transport-belt', {{{x}, {y}}}) if e then for l = 1, 2 do "
        f"e.get_transport_line(l).insert_at_back({{ name = '{it}' }}) end end end"
        for (x, y), it in zip(heads, lanes[:3])) + "\nreturn true"
    t0 = time.monotonic()
    while time.monotonic() - t0 < 50:
        await L.ev(feed)
        await asyncio.sleep(0.3)
    await asyncio.sleep(15)
    p = bp.stamp("rocket-silo-feed", bx, by, 0)["inputs"][0]
    sx, sy = BD[p["side"]]
    ex, ey = p["at"][0] + sx + 0.5, p["at"][1] + sy + 0.5
    got = await L.ev(f"""local e = game.surfaces.nauvis.find_entity('transport-belt', {{ {ex}, {ey} }}) local out = {{}}
if e then for l = 1, 2 do local t = {{}} for _, c in pairs(e.get_transport_line(l).get_contents()) do t[c.name] = c.count end out[l] = t end out.d = e.direction end
return out""") or {}

    def lanes2(o, k):
        if isinstance(o, list):
            v = o[k - 1] if len(o) >= k else {}
        else:
            v = o.get(str(k)) or o.get(k) or {}
        return set(v) if isinstance(v, dict) else set()
    left, right = lanes2(got, 1), lanes2(got, 2)
    if not (left == {"processing-unit"} and right == {"low-density-structure"}):
        from jev.world import World
        w = World(await g.scan(center=(x0 + 20, y0 + 20), radius=24))
        for ln in w.lines:
            print(f"    line {ln.id}: {ln.length} tiles {ln.start} -> {ln.end} items={ln.items} end: {ln.end_reason}")
    check("supply silo: the north input gets processing units on the left lane and LDS on the right, unmixed",
          r.get("ok") and left == {"processing-unit"} and right == {"low-density-structure"},
          (str(r.get("msg"))[:160], (ex, ey), got))


CHECKS = {"progress": chk_progress, "ghosts": chk_ghost_dedup, "boilers": chk_boilers, "queue": chk_queue,
          "abort": chk_abort, "escape": chk_escape, "launch": chk_launch, "pocket": chk_full_pocket, "orphan": chk_orphan, "stall": chk_craft_stall, "positional": chk_positional, "contents": chk_mine_contents, "routewhy": chk_route_why, "detour": chk_route_detour, "routepocket": chk_route_pocket, "fetchfar": chk_fetch_far, "ugpair": chk_ug_pair, "fluidmix": chk_fluid_mix, "treeclear": chk_tree_clear, "waitresearch": chk_wait_research, "fluidports": chk_fluid_ports, "fluidports2": chk_fluid_ports2, "longcraft": chk_long_craft, "rate": chk_rate, "chunks": chk_chunks, "bus": chk_bus, "rowext": chk_row_extend, "busadopt": chk_bus_adopt, "porttaken": chk_fluid_port_taken, "beltend": chk_belt_end, "blockpipe": chk_block_pipe, "clearguard": chk_clear_guard, "clearworking": chk_clear_working, "pipegap": chk_pipe_gap, "auditlacks": chk_audit_lacks, "endref": chk_end_ref, "splitstart": chk_split_start, "powerbig": chk_power_big, "oreleft": chk_ore_left, "busfeed": chk_bus_feed, "tapopp": chk_tap_opposite, "pipes": chk_fluid_trace, "longpipe": chk_long_pipe, "supply": chk_supply, "supplyfar": chk_supply_far, "supplysilo": chk_supply_silo}


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
