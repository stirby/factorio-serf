"""Route a TBM level offline: python tests/try_router.py K  (instance K already set up with a tbm-N scenario)"""
import asyncio, json, math, re, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
from dev import connect  # noqa: E402
from instance import Instance  # noqa: E402
from jev.router import Grid, solve  # noqa: E402
from jev.world import World  # noqa: E402

PAIR = re.compile(r"([\w-]+): \[gps=(-?[\d.]+),(-?[\d.]+)\] to \[gps=(-?[\d.]+),(-?[\d.]+)\]")


def grid_from_scan(sc, nets, margin=12):
    w = World(sc)
    blocked = {tuple(map(int, b)) for b in (sc.get("blocked") or [])}
    blocked |= set(w.tile)
    xs = [p[0] for _, s, e in nets for p in (s, e)]
    ys = [p[1] for _, s, e in nets for p in (s, e)]
    for _, s, e in nets:
        blocked.discard(s)
        blocked.discard(e)
    return Grid(blocked, (min(xs) - margin, min(ys) - margin, max(xs) + margin, max(ys) + margin))


async def main(k):
    setup = json.loads((Instance(k).dir / "setup.json").read_text())
    nets = [(m[0], (math.floor(float(m[1])), math.floor(float(m[2]))), (math.floor(float(m[3])), math.floor(float(m[4]))))
            for m in PAIR.findall(setup["pairs"])]
    g = await connect(k)
    await g.call("spawn", name="serf", client="rcon")
    sc = await g.scan(center=(0.5, 1.5), radius=20, tiles=True)
    grid = grid_from_scan(sc, nets)
    print(len(nets), "nets; blocked", len(grid.blocked), "bounds", grid.x0, grid.y0, grid.x1, grid.y1)
    t = time.time()
    kit = json.loads(sys.argv[2]) if len(sys.argv) > 2 else None
    ents, info = solve(grid, nets, kit=kit)
    print(f"{time.time()-t:.1f}s", info)
    if ents:
        from collections import Counter
        dup = [t for t, n in Counter((math.floor(e["x"]), math.floor(e["y"])) for e in ents).items() if n > 1]
        print("duplicate tiles:", dup[:10])
        onblk = [(math.floor(e["x"]), math.floor(e["y"])) for e in ents if (math.floor(e["x"]), math.floor(e["y"])) in grid.blocked]
        print("on blocked tiles:", onblk[:10])
        print(len(ents), "pieces:", sum(e["name"] == "transport-belt" for e in ents), "belts",
              sum(e["name"] == "underground-belt" for e in ents), "undergrounds")
        # draw
        occ = {(math.floor(e["x"]), math.floor(e["y"])): e for e in ents}
        arrows = {"north": "^", "south": "v", "east": ">", "west": "<"}
        for y in range(grid.y0 + 8, grid.y1 - 7):
            row = ""
            for x in range(grid.x0 + 6, grid.x1 - 5):
                e = occ.get((x, y))
                if e:
                    row += arrows[e["direction"]] if e["name"] == "transport-belt" else ("U" if e.get("type") == "input" else "D")
                elif (x, y) in grid.blocked:
                    row += "#"
                else:
                    row += "."
            print(row)
        Path("/tmp/claude-1000/-home-stephen-ops/dca040bd-512a-4ed8-b7ff-9ffd9741ccde/scratchpad/tbm_route.json").write_text(json.dumps(ents))

asyncio.run(main(int(sys.argv[1])))
