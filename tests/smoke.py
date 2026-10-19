#!/usr/bin/env python3
"""No-LLM smoke test of every mod action against a running dev server.

    .venv/bin/python tests/smoke.py
"""
import asyncio
import os
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
allres = []  # every job result seen, for diagnosing failures


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
            allres.append(r)
    return [got.get(i, {"ok": False, "msg": "timeout"}) for i in ids]


async def wait_idle(crew, timeout=90):
    t0 = time.time()
    while time.time() - t0 < timeout:
        poll = await crew.call("poll")
        events.extend(poll.get("events") or [])
        allres.extend((poll.get("results") or {}).get(A, []))
        me = next(x for x in (await crew.call("list"))["agents"] if x["name"] == A)
        if not me.get("job") and not me.get("queued"):
            return
        await asyncio.sleep(0.5)


async def give(crew, items):
    code = "local c=storage.agents['%s'].char " % A + " ".join(
        f"c.insert{{name='{k}',count={v}}}" for k, v in items.items()) + " return true"
    await crew.call("eval", code=code)


async def main():
    # SMOKE_INSTANCE=K runs against an isolated bench instance (scripts/instance.py start K crew-test)
    k = os.environ.get("SMOKE_INSTANCE")
    pwfile = ROOT / (f"server/instances/{k}/rcon-password" if k else "server/rcon-password")
    pw = pwfile.read_text().strip()
    r = Rcon("127.0.0.1", 27100 + int(k) if k else 27015, pw)
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
    check("trigger tech explained", not res[0]["ok"] and "unlocks when you" in res[0]["msg"]
          and "smelt" in res[0]["msg"], res[0])
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
    check("bad recipe fails, the rest still runs", not res[0]["ok"] and res[1]["ok"], res)
    res = await run(crew, [{"op": "craft", "recipe": "nope", "stop_on_fail": True}, {"op": "wait", "seconds": 1}])
    check("stop_on_fail skips the rest", not res[0]["ok"] and "skipped" in res[1]["msg"], res)

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

    # connect: route a belt around the assembler between two points
    me = await crew.call("self", agent=A)
    await give(crew, {"transport-belt": 40, "small-electric-pole": 10})
    res = await run(crew, [{"op": "connect", "item": "transport-belt", "from": [bx - 3.5, by + 0.5],
                            "to": [bx + 6.5, by + 0.5], "end_direction": "east"}], timeout=120)
    check("connect routes around obstacle", res[0]["ok"] and res[0]["data"]["placed"] > 10
          and res[0]["data"]["placed"] == res[0]["data"]["planned"], res[0])
    # the generated place jobs show up as results after the connect job
    n0 = len(allres)
    await wait_idle(crew)
    bad = [r for r in allres[n0:] if not r["ok"]][:3]
    belts = await crew.call("eval", code=f"return #game.surfaces.nauvis.find_entities_filtered{{name='transport-belt',"
                                         f"area={{{{{bx - 5},{by - 4}}},{{{bx + 8},{by + 5}}}}}}}")
    check("connect placed belts", belts["result"] >= 10, (belts, bad))
    nb = await crew.call("nearby", agent=A, radius=24)
    lines = nb.get("belt_lines") or []
    check("belt lines grouped", any(l["tiles"] >= 10 for l in lines), lines[:3])
    res = await run(crew, [{"op": "connect", "item": "small-electric-pole", "from": [bx - 3.5, by - 3.5],
                            "to": [bx + 12.5, by - 3.5]}], timeout=60)
    check("connect poles spaced", res[0]["ok"] and 2 <= res[0]["data"]["placed"] <= 4, res[0])

    # follow another agent, then cancel
    await crew.call("spawn", name="smoke-buddy", position=[bx - 10, by + 8], starter_kit=False)
    ids = (await crew.call("act", agent=A, actions=[{"op": "follow", "agent": "smoke-buddy", "distance": 2}]))["job_ids"]
    await asyncio.sleep(6)
    lst = {x["name"]: x for x in (await crew.call("list"))["agents"]}
    pa, pb = lst[A]["position"], lst["smoke-buddy"]["position"]
    check("follow closes distance", ((pa[0] - pb[0]) ** 2 + (pa[1] - pb[1]) ** 2) ** 0.5 < 4, (pa, pb))
    await crew.call("cancel", agent=A)
    await crew.call("despawn", agent="smoke-buddy")
    await crew.call("poll")

    # ghosts from an explicit layout, then build them
    me = await crew.call("self", agent=A)
    gx, gy = round(me["position"][0]) - 12, round(me["position"][1]) + 10
    await give(crew, {"stone-furnace": 3, "iron-chest": 2})
    layout = [{"name": "stone-furnace", "x": gx, "y": gy}, {"name": "stone-furnace", "x": gx + 3, "y": gy},
              {"name": "iron-chest", "x": gx + 6.5, "y": gy + 0.5}, {"name": "iron-chest", "x": gx + 8.5, "y": gy + 0.5},
              {"name": "stone-furnace", "x": gx + 11, "y": gy}, {"name": "stone-furnace", "x": gx + 14, "y": gy}]
    res = await run(crew, [{"op": "blueprint", "entities": layout}])
    check("layout ghosts placed", res[0]["ok"] and res[0]["data"]["ghosts"] == 6, res[0])
    g = await crew.call("ghosts", x=gx, y=gy, radius=30)
    check("ghosts op counts", g["count"] == 6 and g["needs"].get("stone-furnace") == 4, g)
    res = await run(crew, [{"op": "build_ghosts", "x": gx, "y": gy, "radius": 30}], timeout=120)
    check("build_ghosts builds what it has items for", res[0]["ok"] and res[0]["data"]["built"] >= 5, res[0])

    # blueprint string round trip: export a small blueprint in game, import it elsewhere as ghosts
    bp = await crew.call("eval", code="local inv=game.create_inventory(1) local st=inv[1] st.set_stack{name='blueprint'} "
                                      "st.set_blueprint_entities{{entity_number=1,name='wooden-chest',position={0.5,0.5}},"
                                      "{entity_number=2,name='wooden-chest',position={2.5,0.5}}} local s=st.export_stack() "
                                      "inv.destroy() return s")
    res = await run(crew, [{"op": "blueprint", "string": bp["result"], "x": gx, "y": gy + 6}])
    check("blueprint string ghosts", res[0]["ok"] and res[0]["data"]["ghosts"] == 2, res[0])

    # undergrounds in a layout pair up (exit listed first), then an abandoned plan is cleared in one action
    ux, uy = gx + 0.5, gy + 12.5
    ug = [{"name": "underground-belt", "x": ux, "y": uy - 4, "direction": "north"},
          {"name": "underground-belt", "x": ux, "y": uy, "direction": "north"}]
    res = await run(crew, [{"op": "blueprint", "entities": ug}])
    kinds = await crew.call("eval", code=f"local o={{}} for _,g in pairs(game.surfaces.nauvis.find_entities_filtered"
                                         f"{{type='entity-ghost',position={{{ux},{uy - 2}}},radius=3}}) do "
                                         "o[#o+1]=g.belt_to_ground_type end table.sort(o) return table.concat(o,',')")
    check("layout undergrounds paired", kinds["result"] == "input,output", kinds)
    res = await run(crew, [{"op": "clear_ghosts", "x": ux, "y": uy - 2, "radius": 4}])
    check("clear_ghosts removes a plan", res[0]["ok"] and res[0]["data"]["removed"] == 2, res[0])

    # logistics marks
    m = await crew.call("mark", agent=A, kind="requester", x=gx + 6.5, y=gy + 0.5, text="test depot",
                        requests={"iron-plate": 50})
    ml = (await crew.call("marks"))["marks"]
    mine = next(x for x in ml if x["id"] == m["id"])
    check("requester mark reports missing", mine.get("missing", {}).get("iron-plate") == 50, mine)
    await crew.call("unmark", id=m["id"])

    # background crafts count toward production stats once they finish
    before = await crew.call("eval", code="return game.forces.player.get_item_production_statistics(game.surfaces.nauvis)"
                                          ".get_input_count('iron-gear-wheel')")
    await give(crew, {"iron-plate": 20})
    await run(crew, [{"op": "craft", "recipe": "iron-gear-wheel", "count": 5, "wait": False}])
    await asyncio.sleep(5)
    after = await crew.call("eval", code="return game.forces.player.get_item_production_statistics(game.surfaces.nauvis)"
                                         ".get_input_count('iron-gear-wheel')")
    check("background crafts counted", after["result"] - before["result"] >= 5, (before, after))

    # idle/busy stats exposed
    lst = {x["name"]: x for x in (await crew.call("list"))["agents"]}
    st = lst[A].get("stats") or {}
    check("agent stats", st.get("busy_ticks", 0) > 0 and "idle_ticks" in st, st)

    # underground belt pair
    me = await crew.call("self", agent=A)
    ux, uy = round(me["position"][0]) + 0.5, round(me["position"][1]) - 8.5
    await give(crew, {"underground-belt": 2})
    res = await run(crew, [{"op": "place", "name": "underground-belt", "x": ux, "y": uy, "direction": "east", "type": "input"},
                           {"op": "place", "name": "underground-belt", "x": ux + 3, "y": uy, "direction": "east", "type": "output"}])
    check("underground pair", res[1]["ok"] and "paired" in res[1]["msg"] and "not paired" not in res[1]["msg"], res)

    # teammate guards: don't mine another agent's build; don't route a belt into a teammate's belt by accident
    me = await crew.call("self", agent=A)
    tx, ty = round(me["position"][0]) + 0.5, round(me["position"][1]) + 14.5
    await crew.call("spawn", name="smoke-mate", position=[tx - 2, ty], starter_kit=False)
    await crew.call("eval", code="storage.agents['smoke-mate'].char.insert{name='transport-belt',count=5} return 1")
    mate_ids = (await crew.call("act", agent="smoke-mate", actions=[
        {"op": "place", "name": "transport-belt", "x": tx, "y": ty, "direction": "east"}]))["job_ids"]
    await asyncio.sleep(2)
    await crew.call("poll")
    res = await run(crew, [{"op": "mine", "x": tx, "y": ty}])
    check("won't mine a teammate's build", not res[0]["ok"] and "built by smoke-mate" in res[0]["msg"], res[0])
    await give(crew, {"transport-belt": 20})
    res = await run(crew, [{"op": "connect", "item": "transport-belt", "from": [tx - 8, ty], "to": [tx - 1, ty],
                            "end_direction": "east"}])
    check("connect won't feed a teammate's belt", not res[0]["ok"] and "feed into smoke-mate" in res[0]["msg"], res[0])
    res = await run(crew, [{"op": "connect", "item": "transport-belt", "from": [tx - 8, ty], "to": [tx - 1, ty],
                            "end_direction": "east", "join": True}], timeout=60)
    check("connect join=true allowed", res[0]["ok"], res[0])
    await wait_idle(crew)
    await crew.call("despawn", agent="smoke-mate")

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

    # loot the corpse we left behind
    res = await run(crew, [{"op": "loot"}], timeout=120)
    check("loot corpse", res[0]["ok"] and "looted" in res[0]["msg"], res[0])

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
