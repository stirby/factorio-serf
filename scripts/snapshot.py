#!/usr/bin/env python3
"""Save the running game under a named stage and record what the base looked like then.

    scripts/snapshot.py [label]        -> server/factorio/saves/stage-<time>-<label>.zip
Snapshots are listed in snapshots/manifest.jsonl (tracked in git; the saves themselves aren't).
Load one later with: scripts/server.sh start stage-...
"""
import asyncio, json, os, re, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from crew.rcon import Crew, Rcon  # noqa: E402

SUMMARY = """local s=game.surfaces.nauvis local f=game.forces.player local c={}
for _,n in pairs{'burner-mining-drill','electric-mining-drill','stone-furnace','assembling-machine-1',
 'assembling-machine-2','lab','steam-engine','boiler','offshore-pump','transport-belt','inserter','burner-inserter',
 'small-electric-pole','iron-chest','wooden-chest'} do local k=s.count_entities_filtered{name=n,force='player'} if k>0 then c[n]=k end end
local r={} for n,t in pairs(f.technologies) do if t.researched then r[#r+1]=n end end table.sort(r)
local a={} for n in pairs(storage.agents) do a[#a+1]=n end table.sort(a)
return {minutes=math.floor(game.tick/3600), entities=c, researched=r, agents=a, peaceful=s.peaceful_mode}"""


async def main():
    label = re.sub(r"[^a-z0-9-]+", "-", (sys.argv[1] if len(sys.argv) > 1 else "auto").lower()).strip("-")
    name = time.strftime("stage-%Y%m%d-%H%M") + f"-{label}"
    r = Rcon("127.0.0.1", int(os.environ.get("FACTORIO_RCON_PORT", 27015)),
             (ROOT / "server/rcon-password").read_text().strip())
    await r.connect()
    crew = Crew(r)
    summary = (await crew.call("eval", code=SUMMARY))["result"]
    out = await r.command(f"/server-save {name}")
    save = ROOT / "server/factorio/saves" / f"{name}.zip"
    for _ in range(60):
        if save.exists() and save.stat().st_size > 0:
            break
        await asyncio.sleep(0.5)
    entry = {"save": name, "time": time.strftime("%Y-%m-%d %H:%M"), "label": label, **summary,
             "bytes": save.stat().st_size if save.exists() else None, "server_said": out.strip()[:200]}
    (ROOT / "snapshots").mkdir(exist_ok=True)
    with open(ROOT / "snapshots/manifest.jsonl", "a") as f:
        f.write(json.dumps(entry) + "\n")
    print(json.dumps(entry))
    await r.close()

asyncio.run(main())
