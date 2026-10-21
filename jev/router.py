"""Multi-belt router: lay N separate belt lines between pairs of tiles on a grid without mixing items. Belts may only
cross with underground belts. Exact work, so code does it (Transport Belt Madness, belt buses, crossings).

Resources (each may be used by one line):
  ("s", tile)        the surface of a tile: a belt, underground entrance or exit
  ("a", tile, axis, tier)  a tile's slot on an axis (h/v) for one underground tier: an underground piece of that
                     tier on that axis, or one passing beneath it (so same-tier spans never nest or cross a same-axis
                     piece, whichever way they face: the game would pair or flip them; different tiers weave freely)
  a line's last belt points at a tile: it uses that tile's surface too (another line there would get side-loaded)
Start and end tiles are reserved for their line.

Search: negotiated congestion (PathFinder). Every round each line is ripped up and re-routed by A* where a resource
costs more the more other lines use it now (present factor, rising each round) and the more it was fought over before
(history). Ends when no resource is shared. Underground jumps cost more than belts so layouts stay within the kit;
if the kit is exceeded the underground price goes up and it keeps going.
"""
from __future__ import annotations

import heapq
import itertools
import time

DIRS = {"north": (0, -1), "east": (1, 0), "south": (0, 1), "west": (-1, 0)}
OPP = {"north": "south", "south": "north", "east": "west", "west": "east"}
AXIS = {"north": "v", "south": "v", "east": "h", "west": "h"}
UG = {"underground-belt": 5, "fast-underground-belt": 7, "express-underground-belt": 9, "turbo-underground-belt": 11}


class Grid:
    def __init__(self, blocked: set[tuple[int, int]], bounds: tuple[int, int, int, int]):
        self.blocked = set(blocked)
        self.x0, self.y0, self.x1, self.y1 = bounds  # inclusive tile bounds

    def ok(self, t) -> bool:
        return self.x0 <= t[0] <= self.x1 and self.y0 <= t[1] <= self.y1 and t not in self.blocked


def step(t, d, k=1):
    return (t[0] + DIRS[d][0] * k, t[1] + DIRS[d][1] * k)


def pieces_resources(pieces) -> list:
    """Resources a line's pieces use."""
    res = []
    for i, pc in enumerate(pieces):
        t, kind, d = pc[0], pc[1], pc[2]
        res.append(("s", t))
        if kind in ("ug_in", "ug_out"):
            res.append(("a", t, AXIS[d], pc[3]))
        if kind == "ug_in":
            ex = pieces[i + 1][0]
            k = abs(ex[0] - t[0]) + abs(ex[1] - t[1])
            for j in range(1, k):
                res.append(("a", step(t, d, j), AXIS[d], pc[3]))
    t, kind, d = pieces[-1][0], pieces[-1][1], pieces[-1][2]
    if kind == "belt":
        res.append(("s", step(t, d)))  # what the last belt points at
    return res


class Router:
    def __init__(self, g: Grid, nets: list[tuple], kit: dict | None = None, max_ug: int = 5):
        self.g, self.nets, self.kit, self.max_ug = g, nets, kit or {}, max_ug
        # underground tiers on hand (yellow always allowed when no kit is given)
        self.tiers = [(n, k) for n, k in UG.items() if (kit or {}).get(n, 0) > 0] or [("underground-belt", max_ug)]
        self.tier_cost = {n: 0.0 for n, _ in self.tiers}
        self.reserved = {}
        for i, (_, s, e) in enumerate(nets):
            self.reserved[s] = i
            self.reserved[e] = i
        self.use: dict = {}  # resource -> {line: count}
        self.hist: dict = {}
        self.pres = 0.5
        self.ug_cost = 3.0
        self.paths: dict[int, list] = {}

    def _add(self, line, pieces, sign):
        for r in pieces_resources(pieces):
            u = self.use.setdefault(r, {})
            u[line] = u.get(line, 0) + sign
            if u[line] <= 0:
                del u[line]

    def cost(self, line, r) -> float:
        u = self.use.get(r)
        others = sum(n for l, n in u.items() if l != line) if u else 0
        return (1.0 + self.hist.get(r, 0.0)) * (1.0 + self.pres * others)

    def route(self, line, budget_nodes: int = 40000):
        g, (_, start, end) = self.g, self.nets[line]
        res = self.reserved

        def can(t):
            return g.ok(t) and res.get(t, line) == line

        def h(t):
            return abs(t[0] - end[0]) + abs(t[1] - end[1])
        cnt = itertools.count()
        openq = [(h(start), 0.0, next(cnt), start, None)]
        best = {(start, None): 0.0}
        parent = {}
        nodes = 0
        goal = None
        while openq:
            f, gc, _, t, arr = heapq.heappop(openq)
            if t == "END":  # finished right on an underground exit at the end tile
                path, k2 = [], ("END", end)
                while k2 in parent:
                    k2, pc = parent[k2]
                    path = pc + path
                return path
            if best.get((t, arr), 1e18) < gc - 1e-9:
                continue
            nodes += 1
            if nodes > budget_nodes:
                break
            if t == end:
                # finish with a belt here, facing somewhere it can't feed another line
                fin = None
                for d in DIRS:
                    if arr and d == OPP[arr]:
                        continue
                    p = step(t, d)
                    if res.get(p, line) != line:
                        continue
                    c = self.cost(line, ("s", t)) + (self.cost(line, ("s", p)) if g.ok(p) else 0)
                    c += 0.0 if d == arr else 0.05
                    if fin is None or c < fin[0]:
                        fin = (c, d)
                if fin:
                    goal = ((t, arr), fin[1], gc + fin[0])
                    break
                continue
            ct = self.cost(line, ("s", t))
            for d in DIRS:
                if arr and d == OPP[arr]:
                    continue
                nt = step(t, d)
                if can(nt):
                    c = gc + ct + (0.1 if arr and d != arr else 0)
                    k = (nt, d)
                    if c < best.get(k, 1e18):
                        best[k] = c
                        parent[k] = ((t, arr), [(t, "belt", d)])
                        heapq.heappush(openq, (c + h(nt), c, next(cnt), nt, d))
                if arr is not None and d != arr:
                    continue
                for tier, kmax in self.tiers:
                  span = 0.0
                  for k_ in range(2, kmax + 1):
                    span += self.cost(line, ("a", step(t, d, k_ - 1), AXIS[d], tier)) - 1.0
                    ex = step(t, d, k_)
                    if not (self.g.x0 <= ex[0] <= self.g.x1 and self.g.y0 <= ex[1] <= self.g.y1):
                        break
                    if not can(ex):
                        continue
                    c = (gc + ct + self.cost(line, ("s", ex)) + self.cost(line, ("a", t, AXIS[d], tier)) +
                         self.cost(line, ("a", ex, AXIS[d], tier)) + span + self.ug_cost + self.tier_cost[tier] + 0.1 * k_)
                    if ex == end:
                        k = ("END", ex)
                        if c < best.get(k, 1e18):
                            best[k] = c
                            parent[k] = ((t, arr), [(t, "ug_in", d, tier), (ex, "ug_out", d, tier)])
                            heapq.heappush(openq, (c, c, next(cnt), "END", d))
                        continue
                    nt = step(ex, d)
                    if not can(nt):
                        continue
                    k = (nt, d)
                    if c < best.get(k, 1e18):
                        best[k] = c
                        parent[k] = ((t, arr), [(t, "ug_in", d, tier), (ex, "ug_out", d, tier)])
                        heapq.heappush(openq, (c + h(nt), c, next(cnt), nt, d))
        if goal is None:
            return None
        key, d_fin, _ = goal
        path = [(end, "belt", d_fin)]
        k2 = key
        while k2 in parent:
            k2, pc = parent[k2]
            path = pc + path
        return path

    def overused(self) -> list:
        return [r for r, u in self.use.items() if sum(u.values()) > 1]

    def counts(self) -> dict:
        c = {"transport-belt": 0}
        for p in self.paths.values():
            for x in p:
                n = "transport-belt" if x[1] == "belt" else x[3]
                c[n] = c.get(n, 0) + 1
        return c

    def solve(self, seconds: float = 40.0):
        t0 = time.time()
        n = len(self.nets)
        order = sorted(range(n), key=lambda i: -(abs(self.nets[i][1][0] - self.nets[i][2][0]) +
                                                 abs(self.nets[i][1][1] - self.nets[i][2][1])))
        it = 0
        best_bad = None
        while time.time() - t0 < seconds:
            it += 1
            for i in order:
                prev = self.paths.get(i)
                if prev is not None:
                    self._add(i, prev, -1)
                p = self.route(i, budget_nodes=150000)
                if p is None:
                    if prev is None:
                        return None, {"why": f"line {self.nets[i][0]} has no path at all", "iterations": it}
                    p = prev  # search ran out of nodes this round: keep the old path, keep negotiating
                self.paths[i] = p
                self._add(i, p, +1)
            bad = self.overused()
            if not bad:
                c = self.counts()
                over = {n: v for n, v in c.items() if self.kit and v > self.kit.get(n, 10 ** 9)}
                if not over:
                    return self.entities(), {"iterations": it, "secs": round(time.time() - t0, 2), "used": c}
                # legal but over the kit: what's short gets dearer, keep negotiating
                for n in over:
                    if n == "transport-belt":
                        self.ug_cost *= 0.8
                    else:
                        self.tier_cost[n] = self.tier_cost.get(n, 0.0) + 1.5
                        self.ug_cost *= 1.15
                best_bad = f"legal layout needs {c} (kit {self.kit})"
                continue
            for r in bad:
                self.hist[r] = self.hist.get(r, 0.0) + 0.6
            self.pres *= 1.4
            best_bad = f"{len(bad)} contested tiles left"
        return None, {"why": f"no clean layout in {seconds:.0f}s ({best_bad})", "iterations": it}

    def entities(self) -> list[dict]:
        ents = []
        for i, p in self.paths.items():
            for pc in p:
                t, kind, d = pc[0], pc[1], pc[2]
                e = {"name": "transport-belt" if kind == "belt" else pc[3], "x": t[0] + 0.5,
                     "y": t[1] + 0.5, "direction": d}
                if kind == "ug_in":
                    e["type"] = "input"
                elif kind == "ug_out":
                    e["type"] = "output"
                ents.append(e)
        return ents


def solve(g: Grid, nets: list[tuple], kit: dict | None = None, seconds: float = 40.0, seed: int = 1):
    """nets: [(name, start_tile, end_tile)]. Returns (entities, info) or (None, reason)."""
    r = Router(g, nets, kit)
    ents, info = r.solve(seconds)
    if ents is None:
        return None, info.get("why") if isinstance(info, dict) else info
    return ents, info
