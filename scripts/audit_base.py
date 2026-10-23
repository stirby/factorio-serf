#!/usr/bin/env python3
"""How maintainable is a base? Load a save on a test server, let it run a few minutes, and measure what a good
player would look at: how many machines are actually working (and why the rest aren't), how much belt and pipe it
takes per machine, chests a person has to fill by hand, belts carrying a mix of items, how spread out it is, and
the science it really makes per minute.

    .venv/bin/python scripts/audit_base.py rocket-launched-c1-fresh-map [--minutes 5] [--instance 61]
Prints a JSON summary (also written to bench/audits/<save>.json).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from instance import Instance  # noqa: E402
from jev.game import Game  # noqa: E402

SCIENCE = ["automation-science-pack", "logistic-science-pack", "military-science-pack", "chemical-science-pack",
           "production-science-pack", "utility-science-pack"]

LUA_SNAPSHOT = """
local s, f = game.surfaces.nauvis, game.forces.player
local out = { types = {}, status = {}, chests = 0, chests_mixed = 0, chests_fed_by_hand = 0, belts = 0,
  undergrounds = 0, splitters = 0, pipes = 0, pipes_ug = 0, machines = 0, poles = 0, mixed_belt_tiles = 0,
  bbox = nil, statuses_by_type = {} }
local names = {}
for n, v in pairs(defines.entity_status) do names[v] = n end
local minx, miny, maxx, maxy
local crafting = { ['assembling-machine'] = true, furnace = true, lab = true, ['mining-drill'] = true,
  ['rocket-silo'] = true }
local feeders = {}  -- unit_number of an entity -> true if an inserter drops into it
local takers = {}
for _, i in pairs(s.find_entities_filtered { type = 'inserter', force = f }) do
  local d, p = i.drop_target, i.pickup_target
  if d and d.unit_number then feeders[d.unit_number] = true end
  if p and p.unit_number then takers[p.unit_number] = true end
end
for _, e in pairs(s.find_entities_filtered { force = f }) do
  local t = e.type
  if t ~= 'character' and t ~= 'entity-ghost' then
    out.types[t] = (out.types[t] or 0) + 1
    local p = e.position
    if t ~= 'electric-pole' then
      minx = math.min(minx or p.x, p.x); maxx = math.max(maxx or p.x, p.x)
      miny = math.min(miny or p.y, p.y); maxy = math.max(maxy or p.y, p.y)
    end
    if crafting[t] then
      out.machines = out.machines + 1
      local st = names[e.status] or 'unknown'
      out.status[st] = (out.status[st] or 0) + 1
      local bt = out.statuses_by_type[t] or {}
      bt[st] = (bt[st] or 0) + 1
      out.statuses_by_type[t] = bt
    elseif t == 'container' or t == 'logistic-container' then
      out.chests = out.chests + 1
      local inv = e.get_inventory(defines.inventory.chest)
      local kinds = inv and #inv.get_contents() or 0
      if kinds > 1 then out.chests_mixed = out.chests_mixed + 1 end
      -- a chest an inserter takes from but nothing fills: a person (or the serf) fills it by hand
      if e.unit_number and takers[e.unit_number] and not feeders[e.unit_number] and t == 'container' then
        out.chests_fed_by_hand = out.chests_fed_by_hand + 1
      end
    elseif t == 'transport-belt' then
      out.belts = out.belts + 1
      local kinds = {}
      for li = 1, 2 do
        local okL, line = pcall(e.get_transport_line, li)
        if okL and line then for _, it in pairs(line.get_contents()) do kinds[it.name] = true end end
      end
      local n = 0
      for _ in pairs(kinds) do n = n + 1 end
      if n > 2 then out.mixed_belt_tiles = out.mixed_belt_tiles + 1 end
    elseif t == 'underground-belt' then out.undergrounds = out.undergrounds + 1
    elseif t == 'splitter' then out.splitters = out.splitters + 1
    elseif t == 'pipe' then out.pipes = out.pipes + 1
    elseif t == 'pipe-to-ground' then out.pipes_ug = out.pipes_ug + 1
    elseif t == 'electric-pole' then out.poles = out.poles + 1
    end
  end
end
if minx then out.bbox = { minx, miny, maxx, maxy } end
out.tick = game.tick
return helpers.table_to_json(out)
"""


def lua_made(items: list[str]) -> str:
    names = ", ".join(f"'{i}'" for i in items)
    return f"""
local st = game.forces.player.get_item_production_statistics(game.surfaces.nauvis)
local out = {{ tick = game.tick, made = {{}}, used = {{}} }}
for _, n in ipairs {{ {names} }} do
  out.made[n] = st.get_input_count(n)
  out.used[n] = st.get_output_count(n)
end
return helpers.table_to_json(out)
"""


async def audit(save: str, minutes: float, k: int) -> dict:
    inst = Instance(k, save)
    await asyncio.to_thread(inst.start, 300)
    g = None
    try:
        g = await Game.connect(inst.host, inst.rcon_port, inst.password, "serf")
        r0 = json.loads((await g.call("eval", code=lua_made(SCIENCE), timeout=60))["result"])
        t0 = time.time()
        await asyncio.sleep(minutes * 60)
        r1 = json.loads((await g.call("eval", code=lua_made(SCIENCE), timeout=60))["result"])
        snap = json.loads((await g.call("eval", code=LUA_SNAPSHOT, timeout=120))["result"])
        game_min = (r1["tick"] - r0["tick"]) / 3600.0
    finally:
        if g:
            await g.crew.close()
        await asyncio.to_thread(inst.stop)
    used = {i: (r1["used"].get(i, 0) - r0["used"].get(i, 0)) / max(game_min, 1e-6) for i in SCIENCE}
    made = {i: (r1["made"].get(i, 0) - r0["made"].get(i, 0)) / max(game_min, 1e-6) for i in SCIENCE}
    m = max(snap["machines"], 1)
    st = snap["status"]
    working = st.get("working", 0) + st.get("normal", 0)
    starved = sum(v for k2, v in st.items() if "shortage" in k2 or "missing" in k2 or "no_input" in k2
                  or k2 in ("no_ingredients", "waiting_for_source_items", "no_minable_resources"))
    blocked = sum(v for k2, v in st.items() if "full_output" in k2 or "output_full" in k2 or "waiting_for_space" in k2)
    unpowered = sum(v for k2, v in st.items() if "power" in k2 or "no_fuel" in k2)
    bb = snap.get("bbox") or [0, 0, 0, 0]
    area = max(1.0, (bb[2] - bb[0]) * (bb[3] - bb[1]))
    out = {
        "save": save, "game_minutes": round(game_min, 2),
        "science_used_per_min": {k2: round(v, 1) for k2, v in used.items() if v > 0},
        "science_made_per_min": {k2: round(v, 1) for k2, v in made.items() if v > 0},
        "spm": round(sum(used.values()), 1),
        "machines": snap["machines"],
        "working_share": round(working / m, 3), "starved_share": round(starved / m, 3),
        "blocked_share": round(blocked / m, 3), "unpowered_or_unfuelled_share": round(unpowered / m, 3),
        "status": st,
        "belt_tiles_per_machine": round((snap["belts"] + snap["undergrounds"] + snap["splitters"]) / m, 2),
        "pipe_tiles_per_machine": round((snap["pipes"] + snap["pipes_ug"]) / m, 2),
        "chests": snap["chests"], "chests_fed_by_hand": snap["chests_fed_by_hand"], "chests_mixed": snap["chests_mixed"],
        "mixed_belt_tiles": snap["mixed_belt_tiles"],
        "footprint_tiles_per_machine": round(area / m, 1), "bbox": bb,
        "counts": {k2: snap["types"].get(k2, 0) for k2 in ("assembling-machine", "furnace", "mining-drill", "lab",
                                                           "transport-belt", "underground-belt", "splitter", "pipe",
                                                           "pipe-to-ground", "inserter", "container")},
    }
    d = ROOT / "bench" / "audits"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{save}.json").write_text(json.dumps(out, indent=1))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("save")
    ap.add_argument("--minutes", type=float, default=5)
    ap.add_argument("--instance", type=int, default=61)
    a = ap.parse_args()
    print(json.dumps(asyncio.run(audit(a.save, a.minutes, a.instance)), indent=1))


if __name__ == "__main__":
    main()
