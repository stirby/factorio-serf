"""Progress over time: periodic metrics and stage snapshots (game saves + a manifest of what the base had)."""
from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "snapshots" / "manifest.jsonl"

SUMMARY = """local s=game.surfaces.nauvis local f=game.forces.player local c={}
for _,n in pairs{'burner-mining-drill','electric-mining-drill','stone-furnace','steel-furnace','assembling-machine-1',
 'assembling-machine-2','lab','steam-engine','boiler','offshore-pump','transport-belt','inserter','burner-inserter',
 'long-handed-inserter','fast-inserter','small-electric-pole','medium-electric-pole','iron-chest','wooden-chest',
 'pumpjack','oil-refinery','chemical-plant'} do local k=s.count_entities_filtered{name=n,force='player'} if k>0 then c[n]=k end end
local r={} for n,t in pairs(f.technologies) do if t.researched then r[#r+1]=n end end table.sort(r)
local a={} for n in pairs(storage.agents) do a[#a+1]=n end table.sort(a)
local st=f.get_item_production_statistics(s) local idx=defines.flow_precision_index.one_minute local pm={}
for _,n in pairs{'iron-plate','copper-plate','steel-plate','stone-brick','iron-gear-wheel','electronic-circuit',
 'automation-science-pack','logistic-science-pack','military-science-pack','chemical-science-pack','coal','iron-ore',
 'copper-ore','transport-belt','inserter'} do local v=st.get_flow_count{name=n,category='input',precision_index=idx,count=true}
 if v>0 then pm[n]=math.floor(v+0.5) end end
local cur=f.current_research
return {minutes=math.floor(game.tick/3600), entities=c, researched=r, research_count=#r, agents=a,
 per_minute=pm, researching=cur and cur.name or nil, peaceful=s.peaceful_mode}"""


async def summary(call) -> dict:
    return (await call("eval", code=SUMMARY))["result"]


async def snapshot(call, command, label: str) -> dict:
    """call = Crew.call, command = raw RCON command function."""
    label = re.sub(r"[^a-z0-9-]+", "-", label.lower()).strip("-")[:40] or "auto"
    name = time.strftime("stage-%Y%m%d-%H%M%S") + f"-{label}"
    info = await summary(call)
    said = await command(f"/server-save {name}")
    save = ROOT / "server/factorio/saves" / f"{name}.zip"
    for _ in range(60):
        if save.exists() and save.stat().st_size > 0:
            break
        await asyncio.sleep(0.5)
    entry = {"save": name, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "label": label, **info,
             "bytes": save.stat().st_size if save.exists() else None, "server_said": said.strip()[:200]}
    MANIFEST.parent.mkdir(exist_ok=True)
    with open(MANIFEST, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


async def metrics_loop(call, path: Path, every: float = 300) -> None:
    while True:
        try:
            info = await summary(call)
            info["t"] = time.time()
            with open(path, "a") as f:
                f.write(json.dumps(info) + "\n")
        except Exception:
            pass
        await asyncio.sleep(every)
