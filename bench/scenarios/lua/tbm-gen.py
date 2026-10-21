"""Builds the Transport Belt Madness scenarios (experiments/scenarios/tbm-1..5.json) from the base game's campaign.

    .venv/bin/python experiments/scenarios/lua/tbm-gen.py --stages 60   # (re)make stage-tbm-01/02/03 on instance 60
    .venv/bin/python experiments/scenarios/lua/tbm-gen.py --solve 60    # find a known solution per level (selftests)
    .venv/bin/python experiments/scenarios/lua/tbm-gen.py               # write the scenario JSONs
    .venv/bin/python experiments/scenarios/lua/tbm-gen.py --check 60    # wrong layout resets, right one solves

TBM ships as a single-player campaign whose script needs a connected player 1 (it crashes headless), so only its
island maps (level-0N/blueprint.zip) and its level tables (level-0N/control.lua) are used: the maps become stage
saves, and each level's chests, start and checks are rebuilt by tbm-common.lua for a serf with real items (see
docs/tbm-investigation.md). Maps: 01 = levels 1-2, 02 = levels 3-4, 03 = level 5.
"""
import argparse
import asyncio
import heapq
import json
import random
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
TBM = ROOT / "server/factorio/data/base/campaigns/transport-belt-madness"
SOLUTIONS = HERE / "tbm-solutions.json"
COMMON = (HERE / "tbm-common.lua").read_text()

# level -> (map, index in that map's levels table, minutes, underground tiers TBM allows)
LEVELS = {1: ("01", 1, 10, ["underground-belt"]),
          2: ("01", 2, 12, ["underground-belt"]),
          3: ("02", 1, 15, ["underground-belt"]),
          4: ("02", 2, 20, ["underground-belt", "fast-underground-belt"]),
          5: ("03", 1, 25, ["underground-belt", "fast-underground-belt", "express-underground-belt"])}
REACH = {"underground-belt": 5, "fast-underground-belt": 7, "express-underground-belt": 9}
BELT_OF = {"underground-belt": "transport-belt", "fast-underground-belt": "fast-transport-belt",
           "express-underground-belt": "express-transport-belt"}
DIRS = {(0, -1): 0, (1, 0): 4, (0, 1): 8, (-1, 0): 12}  # defines.direction


def levels_src(m: str) -> str:
    ctl = (TBM / f"level-{m}" / "control.lua").read_text()
    return "local " + ctl[ctl.index("levels="):ctl.index("script.on_init")].strip()


def setup_lua(level: int, kit: dict) -> str:
    m, i, _, _ = LEVELS[level]
    kit_lua = "{" + ", ".join(f'["{k}"] = {v}' for k, v in sorted(kit.items())) + "}"
    return (f"-- tbm-{level}: Transport Belt Madness level {level} (TBM's level table, verbatim)\n"
            f"{levels_src(m)}\nlocal LEVEL = levels[{i}]\nlocal KIT = {kit_lua}\n" + COMMON)


# ---------------------------------------------------------------------- game access
def run_eval(k: int, code: str):
    from crew.rcon import Crew, Rcon
    pw = (ROOT / f"server/instances/{k}/rcon-password").read_text().strip()

    async def go():
        r = Rcon("127.0.0.1", 27100 + k, pw)
        await r.connect()
        try:
            return (await Crew(r).call("eval", code=code)).get("result")
        finally:
            await r.close()
    return asyncio.run(go())


def instance(k: int, stage: str):
    from instance import Instance
    return Instance(k, stage)


def make_stages(k: int) -> None:
    """TBM's island maps as ordinary saves (a scenario with the map and an empty script, then --scenario2map)."""
    from instance import BIN, Instance
    inst = Instance(k, "stage-s3-steel-oil-ready")
    inst.prepare()  # config, the bench mod set (the serf mod must be in the save)
    for m in ("01", "02", "03"):
        name = f"stage-tbm-{m}"
        d = inst.dir / "scenarios" / name
        d.mkdir(parents=True, exist_ok=True)
        shutil.copy2(TBM / f"level-{m}" / "blueprint.zip", d / "blueprint.zip")
        (d / "control.lua").write_text("-- empty: TBM's map only (tbm-gen.py)\n")
        subprocess.run([str(BIN), "-c", str(inst.dir / "config/config.ini"), "--scenario2map", name], check=True,
                       stdout=subprocess.DEVNULL)
        shutil.copy2(inst.dir / "saves" / f"{name}.zip", ROOT / "server/factorio/saves" / f"{name}.zip")
        print(f"stage {name}.zip")


GRID = """local T = storage.tbm local s = game.surfaces.nauvis local free = {}
local a = T.area
for x = a[1][1], a[2][1] - 1 do for y = a[1][2], a[2][2] - 1 do
  if s.can_place_entity{name='transport-belt', position={x+0.5, y+0.5}, force='player'} then free[#free+1] = {x, y} end
end end
local p = {}
for i, q in ipairs(T.pairs) do
  p[i] = {item=q.item, drop={math.floor(q.drop[1]), math.floor(q.drop[2])}, pick={math.floor(q.pick[1]), math.floor(q.pick[2])},
    oi={math.floor(q.oi.position.x), math.floor(q.oi.position.y)}, ii={math.floor(q.ii.position.x), math.floor(q.ii.position.y)}}
end
return {free=free, pairs=p}"""


# ---------------------------------------------------------------------- solver (for selftests only)
class Router:
    """Belts on a tile grid: each route's belts point only at its own next tile, so routes never feed each other;
    undergrounds hop over anything, but never share a line with another underground of the same tier."""

    def __init__(self, free, pairs, tiers):
        self.free = {tuple(t) for t in free}
        self.pairs = pairs
        self.tiers = tiers
        self.ug_cost = 4  # an underground pair vs one belt
        # each end tile and the tile in front of it (away from its inserter) belong to that pair alone, so no route
        # walls another pair's chest off
        self.owner = {}
        for i, p in enumerate(pairs):
            for end, ins in ((p["drop"], p["ii"]), (p["pick"], p["oi"])):
                front = (2 * end[0] - ins[0], 2 * end[1] - ins[1])
                self.owner[tuple(end)] = i
                self.owner.setdefault(front, i)

    def route(self, p, used, tunnels, noise=None):
        start, goal = tuple(p["drop"]), tuple(p["pick"])
        end_dir = (p["oi"][0] - goal[0], p["oi"][1] - goal[1])  # the last belt faces the output inserter
        me = self.pairs.index(p)
        ok = lambda t: t in self.free and t not in used and self.owner.get(t, me) == me
        # node: (tile, incoming dir or None, must go straight)
        h = lambda t: abs(t[0] - goal[0]) + abs(t[1] - goal[1])
        pq = [(h(start), 0, start, None, False)]
        prev = {(start, None, False): None}
        cost = {(start, None, False): 0}
        n = 0
        while pq:
            _, g, t, din, forced = heapq.heappop(pq)
            node = (t, din, forced)
            if g > cost.get(node, 1e9):
                continue
            if t == goal:
                steps, nd = [], node
                while prev[nd]:
                    nd, mv = prev[nd]
                    steps.append(mv)
                return steps[::-1], end_dir
            n += 1
            if n > 60000:
                return None
            for d in DIRS:
                if din and (d[0] == -din[0] and d[1] == -din[1]):
                    continue
                if forced and d != din:
                    continue
                nt = (t[0] + d[0], t[1] + d[1])
                # a plain belt step (from an underground's exit the exit itself carries on: no belt there)
                if ok(nt) and nt != start and not (nt == goal and d == (-end_dir[0], -end_dir[1])):
                    nn = (nt, d, False)
                    c = g + (noise.get(nt, 1) if noise else 1)
                    if c < cost.get(nn, 1e9):
                        cost[nn], prev[nn] = c, (node, ("skip" if forced else "belt", t, d))
                        heapq.heappush(pq, (c + h(nt), c, nt, d, False))
                # an underground from t (entered straight, or t is the start tile)
                if forced or (din is not None and d != din):
                    continue
                for ti, tier in enumerate(self.tiers):
                    for k in range(2, REACH[tier] + 1):
                        b = (t[0] + d[0] * k, t[1] + d[1] * k)
                        if not ok(b) or b in (start, goal) or self.clash(tunnels, tier, t, b, d):
                            continue
                        nn = (b, d, True)
                        c = g + (self.ug_cost + ti * 3) * (noise.get(b, 1) if noise else 1)
                        if c < cost.get(nn, 1e9):
                            cost[nn], prev[nn] = c, (node, ("under", t, d, tier, b))
                            heapq.heappush(pq, (c + h(b), c, b, d, True))
        return None

    @staticmethod
    def clash(tunnels, tier, a, b, d):
        axis = 0 if d[0] else 1
        lo, hi = sorted((a[axis], b[axis]))
        for (t2, ax2, line2, lo2, hi2) in tunnels:
            if t2 == tier and ax2 == axis and line2 == a[1 - axis] and not (hi < lo2 or hi2 < lo):
                return True
        return False

    def solve(self, tries=4000, seed=1):
        rnd = random.Random(seed)
        order = list(range(len(self.pairs)))
        best = None
        for attempt in range(tries):
            noise = None
            if attempt:
                rnd.shuffle(order)
            if attempt > 2 * len(order) ** 2:  # orders alone didn't do it: vary the paths and the tunnel price
                noise = {t: 1 + 3 * rnd.random() for t in self.free}
                self.ug_cost = rnd.choice((1, 2, 4, 6))
            used, tunnels, out = set(), [], []
            for i in order:
                r = self.route(self.pairs[i], used, tunnels, noise)
                if not r:
                    break
                steps, end_dir = r
                ents = []
                for mv in steps:
                    if mv[0] == "skip":
                        continue
                    if mv[0] == "belt":
                        ents.append({"name": "transport-belt", "p": mv[1], "d": DIRS[mv[2]]})
                        used.add(mv[1])
                    else:
                        _, a, d, tier, b = mv
                        ents.append({"name": tier, "p": a, "d": DIRS[d], "type": "input"})
                        ents.append({"name": tier, "p": b, "d": DIRS[d], "type": "output"})
                        used |= {a, b}
                        axis = 0 if d[0] else 1
                        lo, hi = sorted((a[axis], b[axis]))
                        tunnels.append((tier, axis, a[1 - axis], lo, hi))
                goal = tuple(self.pairs[i]["pick"])
                ents.append({"name": "transport-belt", "p": goal, "d": DIRS[end_dir]})
                used.add(goal)
                out.append({"item": self.pairs[i]["item"], "entities": ents})
            else:
                n = sum(len(r["entities"]) for r in out)
                if not best or n < best[0]:
                    best = (n, out)
                if attempt > 50:
                    break
        return best and best[1]


def solve(k: int) -> None:
    sols = json.loads(SOLUTIONS.read_text()) if SOLUTIONS.exists() else {}
    by_map: dict = {}
    for lv, (m, *_rest) in LEVELS.items():
        by_map.setdefault(m, []).append(lv)
    for m, lvs in by_map.items():
        for lv in lvs:
            inst = instance(k, f"stage-tbm-{m}")
            inst.start(240)
            try:
                run_eval(k, setup_lua(lv, {}))
                g = run_eval(k, GRID)
                sol = Router(g["free"], g["pairs"], LEVELS[lv][3]).solve()
                if not sol:
                    print(f"level {lv}: no solution found")
                    continue
                sols[str(lv)] = sol
                n = sum(len(r["entities"]) for r in sol)
                print(f"level {lv}: {n} entities for {len(sol)} pairs")
            finally:
                inst.stop()
    SOLUTIONS.write_text(json.dumps(sols, indent=0))


def place_lua(routes: list[dict]) -> str:
    """Lua that builds routes (as the serf would, raising script_raised_built)."""
    ents = [e for r in routes for e in r["entities"]]
    rows = ",".join("{'%s',%s,%s,%d,%s}" % (e["name"], e["p"][0] + 0.5, e["p"][1] + 0.5, e["d"],
                                             "'%s'" % e["type"] if e.get("type") else "nil") for e in ents)
    return ("local s=game.surfaces.nauvis local n=0 for _,e in ipairs{" + rows + "} do local x=s.create_entity{"
            "name=e[1],position={e[2],e[3]},direction=e[4],type=e[5],force='player',raise_built=true} "
            "if not x then error('selftest: no '..e[1]..' at '..e[2]..','..e[3]) end n=n+1 end return n")


def kit_for(level: int, routes: list[dict] | None) -> dict:
    """Twice the known solution's belts and undergrounds (rounded up), at least a floor per tier TBM allows."""
    tiers = LEVELS[level][3]
    if not routes:  # no known solution (level 3: 6 routes through 4 land rows need weaving the solver misses)
        return {"transport-belt": 300, **{t: 60 for t in tiers}}
    need: dict = {}
    for r in routes or []:
        for e in r["entities"]:
            need[e["name"]] = need.get(e["name"], 0) + 1
    kit = {"transport-belt": max(60, -(-need.get("transport-belt", 0) * 2 // 10) * 10)}
    for t in tiers:
        kit[t] = max(10, -(-need.get(t, 0) * 2 // 2) * 2)
    return kit


def write() -> None:
    sols = json.loads(SOLUTIONS.read_text()) if SOLUTIONS.exists() else {}
    for lv, (m, _i, minutes, tiers) in LEVELS.items():
        routes = sols.get(str(lv))
        kit = kit_for(lv, routes)
        tier_names = " and ".join(t.replace("-", " ") + "s" for t in tiers)
        ob = {
            "name": f"tbm-level-{lv}",
            "minutes": minutes,
            "hold_samples": 1,
            "goal": ("@{agent} Transport Belt Madness, level " + str(lv) + " of 5, on this island. {n} input chests "
                     "each need a belt to the output chest with the same item. Belt starts and ends: {pairs}. "
                     "Belts can't cross: go under with " + tier_names + ", and no item may ever reach the wrong "
                     "chest (that fails the level and resets it). You have {kit}; that's all there is. The "
                     "inserters start by themselves once every input's belt reaches an output chest. Done when "
                     "every output chest holds 21 of its item."),
            "answer": "Your call, any layout works as long as every item reaches its own chest.",
            "score": [
                {"name": "chests_full", "target": len(routes) if routes else None,
                 "lua": "local n=0 for _,p in pairs(storage.tbm.pairs) do local c=p.oc.get_item_count() "
                        "if c==21 and p.oc.get_item_count(p.item)==21 then n=n+1 end end return n"},
                {"name": "resets", "lua": "return storage.tbm.resets + storage.tbm.stalls"},
                {"name": "belts_placed",
                 "lua": "return #s.find_entities_filtered{area=storage.tbm.area, type={'transport-belt',"
                        "'underground-belt','splitter'}}"},
            ],
        }
        if routes:
            ob["selftest_lua"] = place_lua(routes)
            ob["selftest_wait"] = 75
        else:
            ob["score"][0]["target"] = {1: 4, 2: 8, 3: 6, 4: 8, 5: 14}[lv]
        scn = {
            "name": f"tbm-{lv}",
            "stage": f"stage-tbm-{m}",
            "minutes": minutes,
            "agents": 1,
            "kind": "directive",
            "group": "belts",
            "note": (f"Transport Belt Madness level {lv} (the base game's belt puzzle, map level-{m}): route each "
                     "input chest to its matching output chest on a cramped island; belts may only cross with "
                     "undergrounds. Finite kit (2x a known solution). The inserters start once every input's belt "
                     "reaches an output; a wrong item resets the level (counted in resets). Met = every output "
                     "chest at 21 of its own item, TBM's own check. Built by experiments/scenarios/lua/tbm-gen.py."),
            "setup_lua": setup_lua(lv, kit),
            "objectives": [ob],
            "score": [],
        }
        (OUT / f"tbm-{lv}.json").write_text(json.dumps(scn, indent=1) + "\n")
        print(f"tbm-{lv}: kit {kit}, selftest {'yes' if routes else 'NO'}")


def check(k: int, levels: list[int]) -> None:
    """End to end on a live instance: a layout with two routes swapped fails and resets, the solution solves."""
    import time
    sols = json.loads(SOLUTIONS.read_text())
    for lv in levels:
        m = LEVELS[lv][0]
        routes = sols[str(lv)]
        inst = instance(k, f"stage-tbm-{m}")
        inst.start(240)
        try:
            scn = json.loads((OUT / f"tbm-{lv}.json").read_text())
            run_eval(k, scn["setup_lua"])
            # wrong: two output chests swap items, so the solution delivers into a wrong chest and resets
            run_eval(k, "local p=storage.tbm.pairs p[1].item, p[2].item = p[2].item, p[1].item "
                        "for i=1,2 do p[i].oc.clear_items_inside() p[i].oc.insert{name=p[i].item,count=1} end return 1")
            run_eval(k, place_lua(routes))
            t0 = time.time()
            while time.time() - t0 < 60:
                r = run_eval(k, "return {resets=storage.tbm.resets, started=storage.tbm.started, "
                                "fails=storage.tbm.fails, err=storage.tbm.error}")
                if r["resets"]:
                    break
                time.sleep(3)
            print(f"level {lv} negative: {r}")
            # undo the swap and change the layout (rebuild one belt) so it may restart
            run_eval(k, "local p=storage.tbm.pairs p[1].item, p[2].item = p[2].item, p[1].item "
                        "for i=1,2 do p[i].oc.clear_items_inside() p[i].oc.insert{name=p[i].item,count=1} "
                        "p[i].ic.clear_items_inside() p[i].ic.insert{name=p[i].item,count=20} end "
                        "storage.tbm.failed_layout='changed' return 1")
            t0 = time.time()
            while time.time() - t0 < 150:
                r = run_eval(k, "local n=0 for _,p in pairs(storage.tbm.pairs) do if p.oc.get_item_count()==21 "
                                "and p.oc.get_item_count(p.item)==21 then n=n+1 end end return {full=n, "
                                "solved=storage.tbm.solved, resets=storage.tbm.resets, err=storage.tbm.error}")
                if r["solved"]:
                    break
                time.sleep(5)
            print(f"level {lv} positive: {r} in {round(time.time() - t0)}s")
        finally:
            inst.stop()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stages", type=int, metavar="K")
    ap.add_argument("--solve", type=int, metavar="K")
    ap.add_argument("--check", type=int, metavar="K")
    ap.add_argument("--levels", default="1,2,3,4,5")
    a = ap.parse_args()
    if a.stages:
        make_stages(a.stages)
    elif a.solve:
        solve(a.solve)
        write()
    elif a.check:
        check(a.check, [int(x) for x in a.levels.split(",")])
    else:
        write()
