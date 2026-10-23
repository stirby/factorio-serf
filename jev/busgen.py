"""A main bus, generated exactly: straight lanes of plates and intermediates that production rows take from (taps) and
put back onto (merges), the backbone a player lays so a base can grow without tangling.

Layout, across the bus (u, in tiles from lane 0; `side` is where taps come out):

    u:  -2 -1 | 0  1 | 2  3 | 4  5 | 6  7 | ...
        gap   | W  E | gap  | W  E | gap  |
              pair 0         pair 1

Lanes go in pairs with two free columns before and after every pair, so every lane has free ground beside it:
- a tap puts a splitter on the lane and the free column next to it; the split-off belt turns toward `side` and goes
  under each later pair with an underground (entrance and exit 3 tiles apart), coming out past the bus at u = 4P;
  the whole belt is carried, both sides.
- a merge (bus_in) brings a belt in from `side` the same way and turns it onto the lane's first tile, so a product
  made beside the bus starts its own lane (or side-loads an existing lane of the same item).
Taps and merges use three rows of the gap columns: keep them 4 rows apart. Lanes named "spare" are kept free for
products added later; the bus never gets wider than it was laid.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

DIRS = {"north": (0, -1), "east": (1, 0), "south": (0, 1), "west": (-1, 0)}
OPP = {"north": "south", "south": "north", "east": "west", "west": "east"}
SPARE = "spare"
GAP = 4  # rows kept between taps/merges


@dataclass
class Bus:
    name: str
    x: float  # head tile of lane 0 (tile center)
    y: float
    direction: str  # the way items flow
    side: str  # where taps come out
    lanes: list[str]
    length: int
    starts: dict = field(default_factory=dict)  # lane index (as str) -> first row of a lane that starts mid-bus
    joins: list = field(default_factory=list)  # taps and merges: {"kind", "lane", "at", "end"}

    def __post_init__(self):
        if self.direction not in DIRS or self.side not in DIRS:
            raise ValueError("direction and side must be north/east/south/west")
        dx, dy = DIRS[self.direction]
        nx, ny = DIRS[self.side]
        if dx * nx + dy * ny != 0:
            raise ValueError(f"side {self.side} must be across the bus (it runs {self.direction})")
        self.x, self.y = int(float(self.x) // 1) + 0.5, int(float(self.y) // 1) + 0.5

    # ------------------------------------------------------------------ geometry
    @property
    def pairs(self) -> int:
        return (len(self.lanes) + 1) // 2

    def u(self, i: int) -> int:
        return 4 * (i // 2) + (i % 2)

    def at(self, along: float, across: float) -> tuple[float, float]:
        dx, dy = DIRS[self.direction]
        nx, ny = DIRS[self.side]
        return self.x + dx * along + nx * across, self.y + dy * along + ny * across

    def along_of(self, x: float, y: float) -> int:
        dx, dy = DIRS[self.direction]
        return round((x - self.x) * dx + (y - self.y) * dy)

    def start(self, i: int) -> int:
        return int(self.starts.get(str(i), 0))

    def lane_index(self, lane) -> int:
        """A lane by index or by item (the first lane carrying it; "spare" = the first spare lane)."""
        if isinstance(lane, int) or (isinstance(lane, str) and lane.isdigit()):
            i = int(lane)
            if not 0 <= i < len(self.lanes):
                raise ValueError(f"bus {self.name} has lanes 0..{len(self.lanes) - 1}")
            return i
        for i, it in enumerate(self.lanes):
            if it == lane:
                return i
        raise ValueError(f"bus {self.name} has no {lane} lane (lanes: {', '.join(self.lanes)})")

    def _e(self, name, along, across, direction, **kw) -> dict:
        x, y = self.at(along, across)
        return {"name": name, "x": x, "y": y, "direction": direction, **kw}

    # ------------------------------------------------------------------ pieces
    def lay(self, a0: int = 0, a1: int | None = None, belt: str = "transport-belt") -> list[dict]:
        """The lanes' belts from row a0 up to (not including) a1 (default: the bus's length); spare lanes stay
        empty, and a lane that starts mid-bus only from its start."""
        a1 = self.length if a1 is None else a1
        out = []
        for i, it in enumerate(self.lanes):
            if it == SPARE:
                continue
            for a in range(max(a0, self.start(i)), a1):
                out.append(self._e(belt, a, self.u(i), self.direction))
        return out

    def _cross_out(self, row: int, first_ug_u: int, belt: str, ug: str) -> list[dict]:
        """From the entrance at gap column first_ug_u (= 4q-1 for the pair q to cross) on `row`, under every later
        pair, ending with a belt in the last gap column; the tile past it (u = 4P) is the exit."""
        out = []
        n = self.side
        q = (first_ug_u + 1) // 4
        for q in range(q, self.pairs):
            out.append(self._e(ug, row, 4 * q - 1, n, type="input"))
            out.append(self._e(ug, row, 4 * q + 2, n, type="output"))
        out.append(self._e(belt, row, 4 * self.pairs - 1, n))
        return out

    def tap(self, i: int, a: int, belt: str = "transport-belt", splitter: str = "splitter",
            ug: str = "underground-belt") -> tuple[list[dict], dict, list[tuple[float, float]]]:
        """Entities of a tap on lane i at row a; the exit (the tile past the bus where the split-off belt arrives,
        and the way it points); the lane tile to pick up first (the splitter goes there)."""
        u, p, n, d = self.u(i), i // 2, self.side, self.direction
        out = []
        if i % 2:  # east lane of its pair: splitter over the lane and the gap column after it
            out.append(self._e(splitter, a, u + 0.5, d))
            row = a + 1
            out.append(self._e(belt, row, u + 1, n))  # turns from the splitter toward `side`
            if p + 1 < self.pairs:
                out += self._cross_out(row, 4 * (p + 1) - 1, belt, ug)
            else:
                out.append(self._e(belt, row, u + 2, n))
        else:  # west lane: splitter over the gap column before it and the lane; the split-off belt comes out on
            # the far side, loops back through the gap, and goes under this pair and the later ones
            out.append(self._e(splitter, a, u - 0.5, d))
            out.append(self._e(belt, a + 1, u - 1, OPP[n]))
            out.append(self._e(belt, a + 1, u - 2, d))
            out.append(self._e(belt, a + 2, u - 2, n))
            row = a + 2
            out += self._cross_out(row, u - 1, belt, ug)
        ex, ey = self.at(row, 4 * self.pairs)
        return out, {"x": ex, "y": ey, "direction": n}, [self.at(a, u)]

    def merge(self, i: int, a: int, belt: str = "transport-belt",
              ug: str = "underground-belt") -> tuple[list[dict], dict]:
        """Entities that bring a belt in from `side` on row a and turn it onto lane i at row a+1 (its first tile,
        or a side-load when the lane already runs there); the entry (the first piece, which the incoming line
        joins from behind)."""
        u, p, n, d = self.u(i), i // 2, self.side, self.direction
        back = OPP[n]
        out = [self._e(belt, a, 4 * self.pairs - 1, back)]
        for q in range(self.pairs - 1, p, -1):  # under the pairs between the edge and this lane's pair
            out.append(self._e(ug, a, 4 * q + 2, back, type="input"))
            out.append(self._e(ug, a, 4 * q - 1, back, type="output"))
        if i % 2:  # east lane: turn along the bus in the gap after the pair, then back onto the lane
            out.append(self._e(belt, a, u + 1, d))
            out.append(self._e(belt, a + 1, u + 1, back))
        else:  # west lane: under the whole pair to the gap before it, then round onto the lane from that side
            out.append(self._e(ug, a, u + 2, back, type="input"))
            out.append(self._e(ug, a, u - 1, back, type="output"))
            out.append(self._e(belt, a, u - 2, d))
            out.append(self._e(belt, a + 1, u - 2, n))
            out.append(self._e(belt, a + 1, u - 1, n))
        first = out[0]
        return out, {"x": first["x"], "y": first["y"], "direction": back}

    # ------------------------------------------------------------------ bookkeeping
    def rows_free(self, a: int) -> str | None:
        """Why row a can't take a tap or merge (another one too close, or off the bus), or None."""
        if not 0 <= a or a + 3 > self.length:
            return f"row {a} is off the bus (rows 0..{self.length - 3} can take a tap or merge)"
        for j in self.joins:
            if abs(int(j["at"]) - a) < GAP:
                return f"row {a} is too close to the {j['kind']} at row {j['at']} (keep {GAP} rows apart)"
        return None

    def describe(self) -> str:
        hx, hy = self.at(0, 0)
        ex, ey = self.at(self.length - 1, 0)
        lanes = []
        for i, it in enumerate(self.lanes):
            lx, ly = self.at(self.start(i), self.u(i))
            lanes.append(f"{i} {it} (head {lx:g},{ly:g})" if it != SPARE else f"{i} spare")
        joins = [f"{j['kind']} lane {j['lane']} at row {j['at']} -> {j['end'][0]:g},{j['end'][1]:g}"
                 for j in self.joins]
        free = [a for a in range(0, self.length - 2, GAP) if self.rows_free(a) is None]
        return (f"bus {self.name}: flows {self.direction} from {hx:g},{hy:g} to {ex:g},{ey:g} ({self.length} rows), "
                f"taps come out on the {self.side} side; lanes: " + "; ".join(lanes) +
                (". Joins: " + "; ".join(joins) if joins else "") +
                (f". Free rows for taps/merges include {', '.join(map(str, free[:8]))}" if free else ""))

    def sample_tiles(self, every: int = 4) -> list[tuple[int, int, tuple[float, float]]]:
        """(lane, row, tile) to read along each lane in use, every `every` rows and the last row."""
        out = []
        for i, it in enumerate(self.lanes):
            if it == SPARE:
                continue
            rows = sorted(set(list(range(self.start(i), self.length, every)) + [self.length - 1]))
            out += [(i, a, self.at(a, self.u(i))) for a in rows]
        return out

    def flow_words(self, samples: list[tuple[int, int, int]]) -> list[str]:
        """How full each lane is along its length, as a player reads a bus. samples: (lane, row, items on the tile;
        a full yellow belt tile holds 8)."""
        by: dict[int, list[tuple[int, int]]] = {}
        for i, a, n in samples:
            by.setdefault(i, []).append((a, n))
        out = []
        for i, pts in sorted(by.items()):
            pts.sort()
            name = f"lane {i} {self.lanes[i]}"
            head = sum(n for _, n in pts[:2]) / (8 * min(2, len(pts)))
            tail = pts[-max(1, len(pts) // 3):]
            end = sum(n for _, n in tail) / (8 * len(tail))
            last = max((a for a, n in pts if n > 0), default=None)
            if head < 0.1 and last is None:
                out.append(f"{name}: empty (nothing comes in at its head)")
            elif end >= 0.75:
                out.append(f"{name}: backed up to the end (more comes in than is taken: room to tap more)")
            elif end < 0.1 and last is not None and last < pts[-1][0]:
                out.append(f"{name}: used up by row {last} (taps take all of it: more supply needed before "
                           f"adding consumers)")
            else:
                out.append(f"{name}: flowing, {end * 8:.0f}/8 full near the end")
        return out

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Bus":
        d = dict(d)
        d["lanes"] = list(d.get("lanes") or [])
        d["starts"] = dict(d.get("starts") or {})
        d["joins"] = [j for j in (d.get("joins") or []) if isinstance(j, dict) and "at" in j]
        return cls(**d)
