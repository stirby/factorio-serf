"""How far into the game a world is: totals made, machines standing, research, rockets. Read by RCON eval, so it works
on any world; rates come from the difference between two probes. The milestone ladder turns a probe into one number
(0 = nothing yet, 10 = a rocket launched) for comparing generations and worlds."""
from __future__ import annotations

PACKS = ["automation-science-pack", "logistic-science-pack", "military-science-pack", "chemical-science-pack",
         "production-science-pack", "utility-science-pack", "space-science-pack"]
ITEMS = ["iron-plate", "copper-plate", "stone-brick", "steel-plate", "iron-gear-wheel", "electronic-circuit",
         "advanced-circuit", "processing-unit", "plastic-bar", "sulfur", "engine-unit", "electric-engine-unit",
         "low-density-structure", "rocket-fuel", "rocket-part", "solid-fuel", "battery", "flying-robot-frame"] + PACKS
FLUIDS = ["crude-oil", "petroleum-gas", "water", "steam"]
ENTITIES = ["burner-mining-drill", "electric-mining-drill", "stone-furnace", "steel-furnace", "electric-furnace",
            "assembling-machine-1", "assembling-machine-2", "assembling-machine-3", "lab", "steam-engine", "boiler",
            "solar-panel", "accumulator", "offshore-pump", "pumpjack", "oil-refinery", "chemical-plant", "rocket-silo",
            "transport-belt", "fast-transport-belt", "inserter", "roboport", "train-stop", "locomotive"]

PROBE_LUA = """
local f = game.forces.player
local s = game.surfaces.nauvis
local out = {tick = game.tick, techs = 0, research = nil, items = {}, fluids = {}, ents = {}, by_recipe = {},
  rockets = 0, labs_working = 0, power_mw = 0}
for _, t in pairs(f.technologies) do if t.researched then out.techs = out.techs + 1 end end
if f.current_research then out.research = f.current_research.name end
pcall(function() out.rockets = f.rockets_launched end)
local ist = f.get_item_production_statistics(s)
for _, n in pairs(ITEMS) do out.items[n] = ist.get_input_count(n) end
pcall(function()
  local fst = f.get_fluid_production_statistics(s)
  for _, n in pairs(FLUIDS) do out.fluids[n] = fst.get_input_count(n) end
end)
for _, n in pairs(ENTITIES) do out.ents[n] = s.count_entities_filtered{name = n, force = f} end
for _, m in pairs(s.find_entities_filtered{type = "assembling-machine", force = f}) do
  local r = m.get_recipe()
  if r then out.by_recipe[r.name] = (out.by_recipe[r.name] or 0) + 1 end
end
for _, l in pairs(s.find_entities_filtered{type = "lab", force = f}) do
  if l.status == defines.entity_status.working then out.labs_working = out.labs_working + 1 end
end
return out
"""


async def probe(g) -> dict:
    """One probe of the world, with its milestone level: the mod's progress op, or the same read by eval on a server
    whose mod predates it."""
    try:
        p = await g.call("progress", items=ITEMS, fluids=FLUIDS, entities=ENTITIES, timeout=60)
    except Exception as e:  # noqa: BLE001
        if "unknown op" not in str(e):
            raise
        p = (await g.call("eval", code=probe_lua(), timeout=60)).get("result")
    for k in ("items", "fluids", "ents", "by_recipe"):  # an empty Lua table comes back as [] in JSON
        if not isinstance(p.get(k), dict):
            p[k] = {}
    p["level"], p["milestones"] = level(p)
    return p


def probe_lua() -> str:
    def lua_list(xs):
        return "{" + ", ".join(f'"{x}"' for x in xs) + "}"
    return (f"local ITEMS = {lua_list(ITEMS)}\nlocal FLUIDS = {lua_list(FLUIDS)}\nlocal ENTITIES = {lua_list(ENTITIES)}\n"
            + PROBE_LUA)


MILESTONES = [  # (level, name, test on a probe)
    (1, "smelting by machine", lambda p: p["items"].get("iron-plate", 0) >= 200),
    (2, "electric power", lambda p: p["ents"].get("steam-engine", 0) + p["ents"].get("solar-panel", 0) >= 1
     and p["ents"].get("electric-mining-drill", 0) + p["ents"].get("assembling-machine-1", 0)
     + p["ents"].get("assembling-machine-2", 0) + p["ents"].get("lab", 0) >= 1),
    (3, "red science automated", lambda p: p["items"].get("automation-science-pack", 0) >= 50
     and p["by_recipe"].get("automation-science-pack", 0) >= 1),
    (4, "green science automated", lambda p: p["items"].get("logistic-science-pack", 0) >= 50
     and p["by_recipe"].get("logistic-science-pack", 0) >= 1),
    (5, "oil processing", lambda p: p["fluids"].get("petroleum-gas", 0) > 0),
    (6, "blue science automated", lambda p: p["items"].get("chemical-science-pack", 0) >= 50
     and p["by_recipe"].get("chemical-science-pack", 0) >= 1),
    (7, "purple science automated", lambda p: p["items"].get("production-science-pack", 0) >= 50
     and p["by_recipe"].get("production-science-pack", 0) >= 1),
    (8, "yellow science automated", lambda p: p["items"].get("utility-science-pack", 0) >= 50
     and p["by_recipe"].get("utility-science-pack", 0) >= 1),
    (9, "rocket silo built", lambda p: p["ents"].get("rocket-silo", 0) >= 1),
    (10, "rocket launched", lambda p: (p.get("rockets") or 0) >= 1),
]


def level(p: dict) -> tuple[int, list[str]]:
    """The highest milestone reached in order (each needs the ones before it), and the names of all reached."""
    got = [name for lv, name, test in MILESTONES if _safe(test, p)]
    lv = 0
    for n, name, test in MILESTONES:
        if _safe(test, p):
            lv = n
        else:
            break
    return lv, got


def _safe(test, p) -> bool:
    try:
        return bool(test(p))
    except Exception:  # noqa: BLE001
        return False


def rates(a: dict, b: dict) -> dict:
    """Per-minute rates of the tracked items between two probes (b later than a)."""
    mins = max((b["tick"] - a["tick"]) / 3600, 1e-6)
    return {k: round((b["items"].get(k, 0) - a["items"].get(k, 0)) / mins, 1) for k in ITEMS
            if b["items"].get(k, 0) != a["items"].get(k, 0)}


def summary(p: dict, r: dict | None = None) -> str:
    lv, got = level(p)
    made = ", ".join(f"{k} {v}" for k, v in p["items"].items() if v)[:600]
    ents = ", ".join(f"{k} {v}" for k, v in p["ents"].items() if v)
    rs = ", ".join(f"{k} {v}/min" for k, v in (r or {}).items())
    return (f"milestone {lv}/10 ({', '.join(got) or 'none'}); {p['techs']} techs researched, researching "
            f"{p.get('research') or 'nothing'}; labs working {p.get('labs_working', 0)}; rockets {p.get('rockets', 0)}\n"
            f"made so far: {made}\nstanding: {ents}\n" + (f"rates over the last interval: {rs}\n" if rs else ""))
