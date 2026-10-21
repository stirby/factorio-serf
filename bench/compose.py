#!/usr/bin/env python3
"""Compose a play-session scenario from existing ones: each part's setup runs in one world (as its own Lua function,
placeholders prefixed), and their objectives run one after another, as a player would give the orders.

    .venv/bin/python bench/compose.py t-session2   # writes bench/scenarios/t-session2.json from SESSIONS below

Parts must be scenarios whose setups find their own free area (the S3-stage t-* ones), not fixed-origin ones."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SC = ROOT / "bench" / "scenarios"

# name -> (note, stage, [(prefix, scenario, objective indexes, events per objective)], extra objectives)
SESSIONS = {
    "t-session2": (
        "A longer play session with today's kinds of order, one after another in one world, with chatter: gears off a "
        "belt, research, coal belted to a boiler, a belt line swapped to red, assembler 2s in place of 1s, and starved "
        "red science fixed. Most of it fits the actor's own paths; Opus gets what doesn't.",
        "stage-s3-steel-oil-ready",
        [("g", "t-gear-cell", [0], [[{"after_s": 30, "say": "nice, how's it going?"}]]),
         ("c", "t-coal-boilers", [0], [[]]),
         ("u", "t-upgrade", [0, 1], [[{"after_s": 20, "say": "@{agent} what are you up to?"}], []]),
         ("s", "t-starved", [0], [[{"after_s": 15, "say": "thanks for the help earlier"}]])],
        [{"after": "g", "name": "research-solar", "minutes": 3, "hold_samples": 1,
          "goal": "@{agent} research solar next please", "answer": "Solar energy, yes.",
          "score": [{"name": "solar_queued", "target": 1,
                     "lua": "local r=game.forces.player.current_research local q=game.forces.player.research_queue "
                            "or {} local ok=(r and r.name=='solar-energy') or "
                            "game.forces.player.technologies['solar-energy'].researched for _,t in pairs(q) do if "
                            "t.name=='solar-energy' then ok=true end end return ok and 1 or 0"}]}]),
}


def wrap(prefix: str, lua: str) -> str:
    return f"local function setup_{prefix}()\n{lua}\nend\n"


def main(name: str):
    note, stage, parts, extra = SESSIONS[name]
    lua, calls, objectives = "", [], []
    for prefix, scn, idxs, events in parts:
        s = json.loads((SC / f"{scn}.json").read_text())
        lua += wrap(prefix, s["setup_lua"])
        calls.append(prefix)
        for i, ev in zip(idxs, events):
            o = json.loads(json.dumps(s["objectives"][i]))
            o["goal"] = re.sub(r"\{(?!agent\})(\w+)\}", lambda m: "{" + f"{prefix}_{m.group(1)}" + "}", o["goal"])
            o["name"] = f"{prefix}-{o['name']}"
            if ev:
                o["events"] = ev
            objectives.append(o)
            for x in [x for x in extra if x.get("after") == prefix and i == idxs[-1]]:
                objectives.append({k: v for k, v in x.items() if k != "after"})
    lua += "local out = {}\n"
    for p in calls:
        lua += f"for k, v in pairs(setup_{p}() or {{}}) do out['{p}_' .. k] = v end\n"
    lua += "return out\n"
    scn = {"name": name, "stage": stage, "minutes": 60, "agents": 1, "kind": "directive", "group": "behaviour",
           "note": note, "setup_lua": lua, "objectives": objectives, "score": []}
    (SC / f"{name}.json").write_text(json.dumps(scn, indent=1) + "\n")
    print(f"{name}: {len(objectives)} objectives from {', '.join(p[1] for p in parts)}")


if __name__ == "__main__":
    main(sys.argv[1])
