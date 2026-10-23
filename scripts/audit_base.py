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


# An empty research queue makes the labs stop, so the score would measure the queue, not the factory (p6 at 4 h:
# 30 packs a minute made, 0 used). Queue techs the packs the base has made can pay for, those using the most kinds
# of pack first; report that it was idle.
LUA_RESEARCH = """
local f, s = game.forces.player, game.surfaces.nauvis
local st = f.get_item_production_statistics(s)
local function payable(t)
  for _, ing in pairs(t.research_unit_ingredients) do if st.get_input_count(ing.name) == 0 then return false end end
  return true
end
-- research going on that the base's packs can pay for: leave it (one it can't pay for idles the labs just the same)
if f.current_research and payable(f.current_research) then return helpers.table_to_json { idle = false } end
local stuck = f.current_research and f.current_research.name
local cands = {}
for _, t in pairs(f.technologies) do
  if t.enabled and not t.researched and t.research_unit_count and t.research_unit_count > 0
     and not t.prototype.research_trigger then
    local ok = true
    for _, p in pairs(t.prerequisites) do if not p.researched then ok = false end end
    for _, ing in pairs(t.research_unit_ingredients) do if st.get_input_count(ing.name) == 0 then ok = false end end
    if ok then cands[#cands + 1] = { t.name, t.research_unit_count, #t.research_unit_ingredients } end
  end
end
-- techs using the most pack kinds first, so every science line the base has gets drawn on; then the cheapest
table.sort(cands, function(a, b) if a[3] ~= b[3] then return a[3] > b[3] end return a[2] < b[2] end)
local queued = {}
if stuck then
  -- put payable techs in front of the one the labs can't pay for
  local q = {}
  for i = 1, math.min(5, #cands) do q[#q + 1] = cands[i][1] end
  q[#q + 1] = stuck
  pcall(function() f.research_queue = q end)
  for _, t in pairs(f.research_queue or {}) do queued[#queued + 1] = t.name end
else
  for i = 1, math.min(5, #cands) do if f.add_research(cands[i][1]) then queued[#queued + 1] = cands[i][1] end end
end
return helpers.table_to_json { idle = true, unpayable = stuck, queued = queued }
"""


async def audit(save: str, minutes: float, k: int) -> dict:
    inst = Instance(k, save)
    await asyncio.to_thread(inst.start, 300)
    g = None
    try:
        g = await Game.connect(inst.host, inst.rcon_port, inst.password, "serf")
        research = json.loads((await g.call("eval", code=LUA_RESEARCH, timeout=60))["result"])
        r0 = json.loads((await g.call("eval", code=lua_made(SCIENCE), timeout=60))["result"])
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
    # sustained: per pack, the lower of made and used (a 5-minute window lets labs drain buffered packs, which counts
    # as used without being made: p7 'used' 81 a minute while making 42)
    sustained = round(sum(min(made.get(i, 0), used.get(i, 0)) for i in SCIENCE), 1)
    out = {
        "save": save, "game_minutes": round(game_min, 2), "spm_sustained": sustained,
        "research_was_idle": bool(research.get("idle")), "research_queued": research.get("queued") or [],
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
    (d / f"{Path(save).stem}.json").write_text(json.dumps(out, indent=1))
    return out


AUDIT_SLOTS = range(50, 60)  # campaigns audit their generations here, in the background


def claim_slot() -> tuple[int, Path]:
    """A free audit slot, held by a lock file until the audit ends (several campaigns may finish a generation at
    once)."""
    import os
    from instance import INSTANCES
    for _ in range(120):
        for k in AUDIT_SLOTS:
            d = INSTANCES / str(k)
            d.mkdir(parents=True, exist_ok=True)
            lock = d / "audit.lock"
            try:
                fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if time.time() - lock.stat().st_mtime > 3600:  # left by a crashed audit
                    lock.unlink(missing_ok=True)
                continue
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            if Instance(k).info().get("running"):
                lock.unlink(missing_ok=True)
                continue
            return k, lock
        time.sleep(30)
    raise RuntimeError("no free audit slot in 50-59")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("save", help="a save name in server/factorio/saves, or a path")
    ap.add_argument("--minutes", type=float, default=5)
    ap.add_argument("--instance", default="61", help="a slot, or auto (a free one in 50-59)")
    ap.add_argument("--append", default=None, help="also append the result as a JSON line to this file")
    ap.add_argument("--label", default=None)
    a = ap.parse_args()
    lock = None
    if a.instance == "auto":
        k, lock = claim_slot()
    else:
        k = int(a.instance)
    try:
        out = asyncio.run(audit(a.save, a.minutes, k))
    finally:
        if lock:
            lock.unlink(missing_ok=True)
    if a.label:
        out["label"] = a.label
    out["t"] = time.time()
    if a.append:
        with open(a.append, "a") as f:
            f.write(json.dumps(out) + "\n")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
