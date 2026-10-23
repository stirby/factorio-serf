#!/usr/bin/env python3
"""Dump the game's recipe book, crafting machines and mining drills to jev/data/recipes.json, for the throughput
calculator (jev/ratios.py), which then works offline. Run once per game version:

    .venv/bin/python scripts/dump_recipes.py [--instance 60]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from instance import Instance  # noqa: E402
from jev.game import Game  # noqa: E402

LUA = """
local out = { recipes = {}, machines = {}, drills = {}, resources = {}, version = script.active_mods['base'] }
for name, r in pairs(prototypes.recipe) do
  if not r.hidden then
    local ing, prod = {}, {}
    for _, i in pairs(r.ingredients) do ing[#ing + 1] = { type = i.type, name = i.name, amount = i.amount } end
    for _, p in pairs(r.products) do
      local amt = p.amount or ((p.amount_min or 0) + (p.amount_max or 0)) / 2
      prod[#prod + 1] = { type = p.type, name = p.name, amount = amt * (p.probability or 1) }
    end
    out.recipes[name] = { category = r.category, energy = r.energy, ingredients = ing, products = prod }
  end
end
for name, e in pairs(prototypes.entity) do
  if e.crafting_categories and (e.type == 'assembling-machine' or e.type == 'furnace' or e.type == 'rocket-silo') then
    local cats = {}
    for c in pairs(e.crafting_categories) do cats[#cats + 1] = c end
    local okS, speed = pcall(function() return e.get_crafting_speed() end)
    out.machines[name] = { type = e.type, speed = okS and speed or e.crafting_speed, categories = cats }
  elseif e.type == 'mining-drill' then
    local cats = {}
    for c in pairs(e.resource_categories or {}) do cats[#cats + 1] = c end
    out.drills[name] = { speed = e.mining_speed, categories = cats }
  elseif e.type == 'resource' then
    local mp = e.mineable_properties
    out.resources[name] = { mining_time = mp and mp.mining_time or 1, category = e.resource_category }
  end
end
return helpers.table_to_json(out)
"""


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance", type=int, default=60)
    ap.add_argument("--stage", default="crew-test")
    a = ap.parse_args()
    inst = Instance(a.instance, a.stage)
    await asyncio.to_thread(inst.start, 300)
    g = None
    try:
        g = await Game.connect(inst.host, inst.rcon_port, inst.password, "serf")
        r = await g.call("eval", code=LUA, timeout=120)
        data = json.loads(r["result"])
        out = ROOT / "jev" / "data" / "recipes.json"
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps(data, indent=0, sort_keys=True))
        print(f"{len(data['recipes'])} recipes, {len(data['machines'])} machines, {len(data['drills'])} drills -> {out}")
    finally:
        if g:
            await g.crew.close()
        await asyncio.to_thread(inst.stop)


if __name__ == "__main__":
    asyncio.run(main())
