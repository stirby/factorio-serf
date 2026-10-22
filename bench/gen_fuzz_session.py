#!/usr/bin/env python3
"""Play sessions from the variants: one quick build, one belt job, one fault and one mine (picked from the seeds'
suites), in a random order in one world, with chatter between and during them. Finds what goes wrong when orders
follow each other: watches and keepers from earlier orders, a busy character, reopened orders, chat that isn't an
order. Writes bench/scenarios/f-session-sN-NN.json and bench/suites/fuzz-session-sN.json (deterministic per seed).

    .venv/bin/python bench/gen_fuzz_session.py 4 [seed]"""
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SC = ROOT / "bench" / "scenarios"
SUITES = {"q": "fuzz-s6", "b": "fuzz-belt-s3", "x": "fuzz-fix-s4", "m": "fuzz-mine-s3"}
CHATTER = ["nice, how's it going?", "@{agent} what are you up to?", "thanks for the help earlier", "lol the biters are "
           "quiet today", "@{agent} you good?", "brb getting a drink", "this base is getting big"]


def wrap(prefix: str, lua: str) -> str:
    return f"local function setup_{prefix}()\n{lua}\nend\n"


def main(n: int, seed: int):
    rnd = random.Random(seed)
    names = []
    for i in range(1, n + 1):
        kinds = list(SUITES)
        rnd.shuffle(kinds)
        lua, objectives, picked = "", [], []
        for k in kinds:
            scn_name = rnd.choice(json.loads((ROOT / "bench" / "suites" / f"{SUITES[k]}.json").read_text()))
            s = json.loads((SC / f"{scn_name}.json").read_text())
            picked.append(scn_name)
            lua += wrap(k, s["setup_lua"])
            for o in s["objectives"]:
                o = json.loads(json.dumps(o))
                o["goal"] = re.sub(r"\{(?!agent\})(\w+)\}", lambda m: "{" + f"{k}_{m.group(1)}" + "}", o["goal"])
                o["name"] = f"{k}-{o['name']}"
                if rnd.random() < 0.6:
                    o["events"] = [{"after_s": rnd.choice([10, 20, 40]), "say": rnd.choice(CHATTER)}]
                objectives.append(o)
        lua += "local out = {}\n"
        for k in kinds:
            lua += f"for k, v in pairs(setup_{k}() or {{}}) do out['{k}_' .. k] = v end\n"
        lua += "return out\n"
        name = f"f-session-s{seed}-{i:02d}"
        scn = {"name": name, "stage": "stage-s3-steel-oil-ready",
               "minutes": sum(int(o.get("minutes", 10)) for o in objectives) + 4, "agents": 1, "kind": "directive",
               "group": "fuzz", "note": f"Session {i} (seed {seed}): {', '.join(picked)} in one world, with chatter",
               "setup_lua": lua, "objectives": objectives, "score": []}
        (SC / f"{name}.json").write_text(json.dumps(scn, indent=1) + "\n")
        names.append(name)
        print(f"{name}: {' -> '.join(picked)}  ({scn['minutes']} min)")
    (ROOT / "bench" / "suites" / f"fuzz-session-s{seed}.json").write_text(json.dumps(names, indent=1) + "\n")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 4, int(sys.argv[2]) if len(sys.argv) > 2 else 1)
