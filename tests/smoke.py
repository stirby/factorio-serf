#!/usr/bin/env python3
"""No-LLM smoke test of every mod action against a running dev server.

    .venv/bin/python tests/smoke.py
"""
import asyncio
import json
import sys
import time
from pathlib import Path

SAVE_NOTE = "run against the crew-test save; it resets research"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from crew.rcon import Crew, GameError, Rcon  # noqa: E402

A = "smoke-bot"
passed, failed = [], []
events = []  # every poll drains events; keep them for checks


def check(name, cond, info=""):
    (passed if cond else failed).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f"  -- {info}" if info and not cond else ""))


async def run(crew, actions, timeout=90):
    ids = (await crew.call("act", agent=A, actions=actions))["job_ids"]
    got = {}
    t0 = time.time()
    while len(got) < len(ids) and time.time() - t0 < timeout:
        await asyncio.sleep(0.5)
        poll = await crew.call("poll")
        events.extend(poll.get("events") or [])
        for r in (poll.get("results") or {}).get(A, []):
            got[r["id"]] = r
    return [got.get(i, {"ok": False, "msg": "timeout"}) for i in ids]


async def give(crew, items):
    code = "local c=storage.agents['%s'].char " % A + " ".join(
        f"c.insert{{name='{k}',count={v}}}" for k, v in items.items()) + " return true"
    await crew.call("eval", code=code)


async def main():
    pw = (ROOT / "server/rcon-password").read_text().strip()
    r = Rcon("127.0.0.1", 27015, pw)
    await r.connect()
    crew = Crew(r)
    await crew.call("poll")
    try:
        await crew.call("despawn", agent=A)
    except GameError:
        pass
    await crew.call("eval", code="local f=game.forces.player f.research_queue={} for _,t in pairs{'automation',"
                                 "'electronics','automation-science-pack','steam-power'} do f.technologies[t].researched=false end return true")
    # clear leftovers from earlier runs
    await crew.call("eval", code="for _,e in pairs(game.surfaces.nauvis.find_entities_filtered{position={-40,40},"
                                 "radius=30,force='player'}) do if e.type~='character' then e.destroy() end end return true")
    sp = await crew.call("spawn", name=A, position=[-40, 40])
    check("spawn", sp["agent"] == A)

    # walk somewhere open, then build next to us
    me = await crew.call("self", agent=A)
    x, y = me["position"]
    bx, by = round(x) + 4, round(y)

    await give(crew, {"assembling-machine-1": 1, "iron-plate": 50, "transport-belt": 5, "wooden-chest": 1,
                      "coal": 10, "inserter": 1})
    res = await run(crew, [
        {"op": "place", "name": "assembling-machine-1", "x": bx + 0.5, "y": by + 0.5},
        {"op": "set_recipe", "x": bx + 0.5, "y": by + 0.5, "recipe": "iron-gear-wheel"},
        {"op": "insert", "x": bx + 0.5, "y": by + 0.5, "item": "iron-plate", "count": 10},
        {"op": "place", "name": "transport-belt", "x": bx + 3.5, "y": by + 0.5, "direction": "east"},
        {"op": "rotate", "x": bx + 3.5, "y": by + 0.5, "direction": "south"},
        {"op": "place", "name": "wooden-chest", "x": bx + 3.5, "y": by + 2.5},
        {"op": "insert", "x": bx + 3.5, "y": by + 2.5, "item": "iron-plate", "count": 5},
        {"op": "take", "x": bx + 3.5, "y": by + 2.5, "item": "iron-plate", "count": 3},
    ])
    for name, rr in zip(["place assembler", "set_recipe", "insert plates", "place belt", "rotate belt",
                         "place chest", "insert chest", "take 3 from chest"], res):
        check(name, rr["ok"], rr["msg"])
    insp = await crew.call("inspect", agent=A, x=bx + 3.5, y=by + 0.5, radius=0.5)
    check("rotate took effect", any(e["n"] == "transport-belt" for e in insp["entities"]))
    check("take counted", res[7].get("data", {}).get("taken", {}).get("iron-plate") == 3, res[7])

    # failure paths
    res = await run(crew, [{"op": "craft", "recipe": "electronic-circuit", "count": 2}])
    check("locked recipe explained", not res[0]["ok"] and "locked" in res[0]["msg"], res[0])
    res = await run(crew, [{"op": "research", "tech": "electronics"}])
    check("trigger tech explained", not res[0]["ok"] and "trigger" in res[0]["msg"], res[0])
    await crew.call("eval", code="for _,t in pairs{'electronics','automation-science-pack','steam-power'} do "
                                 "game.forces.player.technologies[t].researched=true end return true")
    res = await run(crew, [{"op": "craft", "recipe": "wooden-chest", "count": 2}])
    check("craft fails without wood", not res[0]["ok"] and "missing" in res[0]["msg"], res[0])
    res = await run(crew, [{"op": "place", "name": "wooden-chest", "x": bx + 3.5, "y": by + 2.5}])
    check("place fails with no item / blocked", not res[0]["ok"], res[0])
    await give(crew, {"wooden-chest": 1})
    res = await run(crew, [{"op": "place", "name": "wooden-chest", "x": bx + 3.5, "y": by + 2.5}])
    check("place blocked reports blocker", not res[0]["ok"] and "blocked by" in res[0]["msg"], res[0])
    res = await run(crew, [{"op": "craft", "recipe": "nope"}, {"op": "wait", "seconds": 1}])
    check("bad recipe fails and skips rest", not res[0]["ok"] and "skipped" in res[1]["msg"], res)

    # standing on the build spot -> sidestep
    me = await crew.call("self", agent=A)
    sx, sy = me["position"]
    res = await run(crew, [{"op": "place", "name": "wooden-chest", "x": int(sx) + 0.5 if sx >= 0 else int(sx) - 0.5,
                            "y": int(sy) + 0.5 if sy >= 0 else int(sy) - 0.5}])
    check("place under own feet sidesteps", res[0]["ok"], res[0])

    # handcraft chain: gears into inserter needs circuits -> give copper, craft circuits then inserter
    await give(crew, {"copper-plate": 10})
    res = await run(crew, [{"op": "craft", "recipe": "inserter", "count": 1}], timeout=60)
    check("intermediate auto-craft (inserter)", res[0]["ok"], res[0])

    # trigger tech: crafting a lab unlocks automation-science-pack (agents' crafts must count)
    await crew.call("eval", code="local f=game.forces.player f.technologies['automation-science-pack'].researched=false "
                                 "storage.trigger_counts=nil return true")
    await give(crew, {"iron-plate": 40, "copper-plate": 20})
    res = await run(crew, [{"op": "craft", "recipe": "lab", "count": 1}], timeout=60)
    w = await crew.call("eval", code="return game.forces.player.technologies['automation-science-pack'].researched")
    check("agent craft fires trigger tech", res[0]["ok"] and w["result"] is True, (res[0], w))
    events.extend((await crew.call("poll")).get("events") or [])
    check("research_finished event", any(e["type"] == "research_finished" for e in events), events)

    # research
    res = await run(crew, [{"op": "research", "tech": "automation"}])
    check("queue research", res[0]["ok"], res[0])
    w = await crew.call("world", agent=A)
    check("research visible", w["research"] != "none" or "automation" in json.dumps(w["research_queue"]), w)

    # trees/rocks (desert maps have few; just ensure it either works or says none found)
    res = await run(crew, [{"op": "mine", "name": "tree", "count": 1}], timeout=120)
    check("mine tree", res[0]["ok"] or "nothing minable" in res[0]["msg"], res[0])
    res = await run(crew, [{"op": "mine", "name": "rock", "count": 1}], timeout=120)
    check("mine rock", res[0]["ok"] or "nothing minable" in res[0]["msg"], res[0])

    # move to player-less target / cancel
    ids = (await crew.call("act", agent=A, actions=[{"op": "move", "x": 120, "y": 160}]))["job_ids"]
    await asyncio.sleep(2)
    await crew.call("cancel", agent=A)
    poll = await crew.call("poll")
    rs = (poll.get("results") or {}).get(A, [])
    check("cancel long move", any(x["id"] == ids[0] and "cancel" in x["msg"] for x in rs), rs)

    # map / nearby / find / recipes / techs / production
    m = await crew.call("map", agent=A, radius=8)
    check("map 17 rows", len(m["rows"]) == 17 and any("@" in row for row in m["rows"]))
    await run(crew, [{"op": "move", "x": bx - 2, "y": by}])
    nb = await crew.call("nearby", agent=A, radius=20)
    check("nearby sees assembler", any(e["n"] == "assembling-machine-1" for e in nb.get("entities", [])), nb)
    rec = await crew.call("recipes", agent=A, filter="gear")
    check("recipes", "iron-gear-wheel" in rec["recipes"])
    t = await crew.call("techs", agent=A)
    check("techs", len(t["available"]) > 0)
    p = await crew.call("production", agent=A)
    check("production", "per_minute_produced" in p)

    # death + respawn
    await crew.call("eval", code=f"storage.agents['{A}'].char.die() return true")
    await asyncio.sleep(1)
    lst = await crew.call("list")
    me = next(x for x in lst["agents"] if x["name"] == A)
    check("death recorded", not me["alive"])
    await asyncio.sleep(11)
    lst = await crew.call("list")
    me = next(x for x in lst["agents"] if x["name"] == A)
    check("respawned", me["alive"], me)
    poll = await crew.call("poll")
    check("death/respawn events", {"died", "respawned"} <= {e["type"] for e in poll.get("events", [])}, poll.get("events"))

    # cheat mode
    await crew.call("eval", code="settings.global['claude-crew-cheat'] = {value=true} return true")
    res = await run(crew, [{"op": "move", "x": 200, "y": 0}, {"op": "craft", "recipe": "iron-chest", "count": 2}])
    check("cheat teleport", res[0]["ok"], res[0])
    check("cheat craft", res[1]["ok"], res[1])
    await crew.call("eval", code="settings.global['claude-crew-cheat'] = {value=false} return true")

    await crew.call("say", agent=A, text="smoke test done [gps=0,0]")
    await crew.call("despawn", agent=A)
    await r.close()
    print(f"\n{len(passed)} passed, {len(failed)} failed: {failed}")
    sys.exit(1 if failed else 0)


asyncio.run(main())
