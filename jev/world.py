"""World model: one scan of an area turned into things a player thinks about.

Code does everything exact here (geometry, counting, belt continuity, which inserter feeds what, power numbers).
Jev never sees raw numbers it has to compare; Opus gets the same model with coordinates.

    w = World(scan, recipes)
    w.lines            belt lines (ordered belts, direction, items, where they start and end and why)
    w.machines         crafting machines, drills, boilers, labs with their feeders and a plain-words state
    w.faults()         things that look broken, each with a cause in words and candidate fixes (actions)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

DIRS = {"north": (0, -1), "east": (1, 0), "south": (0, 1), "west": (-1, 0)}
OPP = {"north": "south", "south": "north", "east": "west", "west": "east"}
BELT_T = {"transport-belt", "underground-belt", "splitter"}
CRAFTERS = {"assembling-machine", "furnace", "lab", "mining-drill", "boiler", "rocket-silo", "reactor",
            "generator", "burner-generator"}
CHESTS = {"container", "logistic-container", "infinity-container"}
FUELS = ["coal", "wood", "solid-fuel", "rocket-fuel", "nuclear-fuel"]

STATUS_WORDS = {
    "working": "working",
    "normal": "idle",
    "no_power": "stopped: no power",
    "low_power": "slowed: low power",
    "no_fuel": "stopped: out of fuel",
    "item_ingredient_shortage": "stopped: missing ingredients",
    "fluid_ingredient_shortage": "stopped: missing fluid",
    "full_output": "stopped: output full",
    "no_recipe": "stopped: no recipe set",
    "waiting_for_source_items": "waiting for items to pick up",
    "waiting_for_space_in_destination": "blocked: destination full",
    "no_minable_resources": "stopped: ore ran out",
    "missing_required_fluid": "stopped: missing fluid",
    "no_input_fluid": "stopped: no water/fluid",
    "disabled_by_control_behavior": "disabled by circuit",
    "disabled_by_script": "disabled",
    "marked_for_deconstruction": "marked for removal",
    "networks_disconnected": "not connected",
    "out_of_logistic_network": "outside logistic network",
    "not_plugged_in_electric_network": "stopped: not on the power grid",
    "frozen": "frozen",
}
STOPPED = {"no_power", "no_fuel", "item_ingredient_shortage", "fluid_ingredient_shortage", "full_output",
           "no_recipe", "no_minable_resources", "missing_required_fluid", "no_input_fluid", "low_power",
           "not_plugged_in_electric_network", "waiting_for_space_in_destination"}


def compass(dx: float, dy: float) -> str:
    if abs(dx) < 0.75 and abs(dy) < 0.75:
        return "here"
    ang = math.degrees(math.atan2(dx, -dy)) % 360  # 0 = north, clockwise
    names = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"]
    return names[int((ang + 22.5) // 45) % 8]


def rel(frm, to) -> str:
    """'12 tiles north-east' (rounded words for Jev)."""
    dx, dy = to[0] - frm[0], to[1] - frm[1]
    d = math.hypot(dx, dy)
    if d < 1.5:
        return "right here"
    n = int(round(d))
    return f"{n} tiles {compass(dx, dy)}"


def fmt_xy(p) -> str:
    return f"{p[0]:g},{p[1]:g}"


def items_words(d: dict | None, limit: int = 6) -> str:
    if not d:
        return "nothing"
    parts = [f"{n} {k}" for k, n in sorted(d.items(), key=lambda kv: -kv[1])[:limit]]
    more = len(d) - limit
    return ", ".join(parts) + (f" (+{more} more kinds)" if more > 0 else "")


def amount_word(n: float, full: float) -> str:
    if n <= 0:
        return "empty"
    f = n / full if full else 1
    return "nearly empty" if f < 0.15 else "low" if f < 0.4 else "half" if f < 0.7 else "full" if f >= 0.9 else "mostly full"


@dataclass
class Line:
    id: str
    belts: list[int]
    direction: str  # the direction of most belts
    items: dict
    start: tuple
    end: tuple
    start_reason: str
    end_reason: str
    density: float  # items per belt tile (0..8)
    takers: list[int] = field(default_factory=list)  # inserters/units taking from it
    putters: list[int] = field(default_factory=list)

    @property
    def length(self) -> int:
        return len(self.belts)


def grid_live(g: dict) -> bool:
    """The grid can power something now (the mod says; older scans: it has generator capacity)."""
    return bool(g.get("live")) if "live" in g else (g.get("cap_w") or 0) > 0


class World:
    def __init__(self, scan: dict, recipes: dict | None = None, me: dict | None = None):
        self.raw = scan
        self.recipes = recipes or {}
        self.me = me or {}
        ents = scan.get("ents") or []
        if isinstance(ents, dict):
            ents = list(ents.values())
        self.ents: dict[int, dict] = {}
        self.ghosts: list[dict] = []
        for i, e in enumerate(ents):
            if e.get("ghost"):
                self.ghosts.append(e)
            else:
                if e.get("u") is None:  # neutral props and other things without a unit number: obstacles only
                    e["u"] = -(i + 1)
                self.ents[e["u"]] = e
        self.center = tuple(scan.get("center") or (0, 0))
        self.radius = scan.get("radius")
        self.tile: dict[tuple[int, int], int] = {}
        for u, e in self.ents.items():
            w, h = e.get("w", 1), e.get("h", 1)
            x0, y0 = math.floor(e["x"] - w / 2 + 0.01), math.floor(e["y"] - h / 2 + 0.01)
            for i in range(w):
                for j in range(h):
                    self.tile[(x0 + i, y0 + j)] = u
        self.res = scan.get("res") if isinstance(scan.get("res"), dict) else {}
        self.grids = {g["id"]: g for g in (scan.get("grids") or []) if isinstance(g, dict)}
        self.chars = scan.get("chars") if isinstance(scan.get("chars"), list) else []
        self.water = scan.get("water") if isinstance(scan.get("water"), dict) else None
        self.feeders: dict[int, list[int]] = {}  # machine/chest u -> inserters dropping into it
        self.takers: dict[int, list[int]] = {}  # u -> inserters picking from it
        for u, e in self.ents.items():
            if e["t"] == "inserter":
                if e.get("dpu"):
                    self.feeders.setdefault(e["dpu"], []).append(u)
                if e.get("pku"):
                    self.takers.setdefault(e["pku"], []).append(u)
            if e["t"] == "mining-drill" and e.get("dpu"):
                self.feeders.setdefault(e["dpu"], []).append(u)
        self.lines: list[Line] = []
        self.line_of: dict[int, Line] = {}
        self._build_lines()
        self._labels()

    # ------------------------------------------------------------------ lookups
    def at(self, x: float, y: float) -> dict | None:
        u = self.tile.get((math.floor(x), math.floor(y)))
        return self.ents.get(u) if u else None

    def of_type(self, *types) -> list[dict]:
        return [e for e in self.ents.values() if e["t"] in types]

    def near(self, p, r: float, types=None) -> list[dict]:
        out = [e for e in self.ents.values() if abs(e["x"] - p[0]) <= r and abs(e["y"] - p[1]) <= r
               and (not types or e["t"] in types)]
        return sorted(out, key=lambda e: (e["x"] - p[0]) ** 2 + (e["y"] - p[1]) ** 2)

    # ------------------------------------------------------------------ belts
    def _build_lines(self) -> None:
        belts = {u: e for u, e in self.ents.items() if e["t"] in BELT_T}
        nxt: dict[int, int] = {}
        prev_count: dict[int, int] = {}
        for u, e in belts.items():
            outs = [o for o in (e.get("o") or []) if o in belts]
            if e["t"] == "underground-belt" and e.get("ug") == "input" and e.get("pair") in belts:
                outs = [e["pair"]]
            if len(outs) == 1:
                nxt[u] = outs[0]
                prev_count[outs[0]] = prev_count.get(outs[0], 0) + 1
        # a line starts where no single belt leads in (or a merge), and runs while each step has one successor
        seen: set[int] = set()
        starts = [u for u in belts if prev_count.get(u, 0) != 1]
        n = 0
        for s in sorted(starts, key=lambda u: (belts[u]["y"], belts[u]["x"])) + sorted(belts, key=lambda u: (belts[u]["y"], belts[u]["x"])):
            if s in seen:
                continue
            chain = [s]
            seen.add(s)
            cur = s
            while cur in nxt and nxt[cur] not in seen and prev_count.get(nxt[cur], 0) == 1:
                cur = nxt[cur]
                chain.append(cur)
                seen.add(cur)
            n += 1
            self._add_line(f"L{n}", chain, belts, nxt)

    def _add_line(self, lid: str, chain: list[int], belts: dict, nxt: dict) -> None:
        items: dict = {}
        load = 0
        dirs: dict = {}
        for u in chain:
            e = belts[u]
            dirs[e.get("d", "?")] = dirs.get(e.get("d", "?"), 0) + 1
            for lane in e.get("lanes") or []:
                for k, v in (lane or {}).items():
                    items[k] = items.get(k, 0) + v
                    load += v
        first, last = belts[chain[0]], belts[chain[-1]]
        direction = max(dirs, key=dirs.get)
        line = Line(lid, chain, direction, items, (first["x"], first["y"]), (last["x"], last["y"]),
                    self._start_reason(first), self._end_reason(last, nxt), round(load / max(1, len(chain)), 1))
        for u in chain:
            line.takers += self.takers.get(u, [])
            line.putters += self.feeders.get(u, [])
            self.line_of[u] = line
        self.lines.append(line)

    def _ahead(self, e: dict):
        d = DIRS.get(e.get("d", ""), (0, 0))
        return e["x"] + d[0], e["y"] + d[1]

    def _behind(self, e: dict):
        d = DIRS.get(e.get("d", ""), (0, 0))
        return e["x"] - d[0], e["y"] - d[1]

    def _continues(self, ln) -> list:
        """Lines that carry on in the same direction just past this one's end (across a gap or a turned tile)."""
        d = DIRS.get(ln.direction)
        if not d:
            return []
        out = []
        for other in self.lines:
            if other is ln or other.direction != ln.direction:
                continue
            for k in (1, 2, 3):
                if abs(other.start[0] - (ln.end[0] + d[0] * k)) < 0.1 and abs(other.start[1] - (ln.end[1] + d[1] * k)) < 0.1:
                    out.append(other)
                    break
        return out

    def connected(self, seeds) -> set[int]:
        """Everything linked to the seed units by inserters and belts, upstream and down: an inserter's pickup and drop,
        whatever feeds or takes from a unit, a belt's whole line with what puts onto it and takes from it, and the lines
        it continues into or that continue into it (across a gap)."""
        into: dict = {}
        for ln in self.lines:
            for nx in self._continues(ln):
                into.setdefault(nx.id, []).append(ln)
        seen, todo = set(), [u for u in seeds if u in self.ents]
        while todo:
            u = todo.pop()
            if u in seen:
                continue
            seen.add(u)
            e = self.ents.get(u) or {}
            nb = [e.get("pku"), e.get("dpu")] + self.takers.get(u, []) + self.feeders.get(u, [])
            ln = self.line_of.get(u)
            if ln:
                for other in [ln] + self._continues(ln) + into.get(ln.id, []):
                    nb += other.belts + other.takers + other.putters
            todo += [x for x in nb if x and x in self.ents and x not in seen]
        return seen

    def _engine_slots(self, grid_id) -> list[dict]:
        """Fixes for a maxed grid that code can do: a boiler on it driving fewer than its 2 steam engines gets the
        next one, end to end along its steam output (a free 3x5 spot needed). More boilers are the planner's job."""
        fixes = []
        engines = {(e["x"], e["y"]) for e in self.ents.values() if e.get("n") == "steam-engine"}
        on_grid = [e for e in self.ents.values() if e.get("n") == "steam-engine" and e.get("net") == grid_id]
        for b in self.ents.values():
            if b.get("t") != "boiler" or b.get("d") not in DIRS:
                continue
            dx, dy = DIRS[b["d"]]
            first = (b["x"] + dx * 3.5, b["y"] + dy * 3.5)
            second = (first[0] + dx * 5, first[1] + dy * 5)
            if first in engines and not any(abs(e["x"] - first[0]) < 0.1 and abs(e["y"] - first[1]) < 0.1
                                            for e in on_grid):
                continue  # this boiler's engines are on another grid
            spot = second if first in engines else first
            if spot in engines:
                continue  # both engines there
            long_x = dx != 0
            w, h = (5, 3) if long_x else (3, 5)
            x0, y0 = math.floor(spot[0] - w / 2 + 0.01), math.floor(spot[1] - h / 2 + 0.01)
            if any((x0 + i, y0 + j) in self.tile or self.off_view(x0 + i + 0.5, y0 + j + 0.5)
                   for i in range(w) for j in range(h)):
                continue
            fixes.append({"do": "place", "name": "steam-engine", "x": spot[0], "y": spot[1], "direction": b["d"],
                          "text": f"add a steam engine to the boiler at {fmt_xy((b['x'], b['y']))}",
                          "done": f"added a steam engine to the boiler at {fmt_xy((b['x'], b['y']))}",
                          "then_power": True})
            break
        return fixes

    def off_view(self, x: float, y: float) -> bool:
        """Is this point outside the square the scan covered (so "nothing there" only means "not looked at")?"""
        if not self.radius:
            return False
        return abs(x - self.center[0]) > self.radius or abs(y - self.center[1]) > self.radius

    def _end_reason(self, e: dict, nxt: dict) -> str:
        if e["u"] in nxt:
            return f"merges into another line at {fmt_xy(self._ahead(e))}"
        if e["t"] == "underground-belt" and e.get("ug") == "input":
            return "underground entrance with no exit"
        ax, ay = self._ahead(e)
        o = self.at(ax, ay)
        if o is None and self.off_view(ax, ay):
            return "runs on past the edge of this view (look further that way)"
        if o is None:
            return "ends (nothing ahead)"
        if o["t"] in BELT_T:
            if o.get("d") == OPP.get(e.get("d")):
                return f"runs head-on into a belt facing {o.get('d')} at {fmt_xy((o['x'], o['y']))}"
            return f"stops against a {o['n']} at {fmt_xy((o['x'], o['y']))}"
        return f"ends at a {o['n']} (belts can't feed machines; an inserter must)"

    def _start_reason(self, e: dict) -> str:
        if e.get("i"):
            return "fed from another line"
        bx, by = self._behind(e)
        o = self.at(bx, by)
        if o is None and self.off_view(bx, by):
            return "comes in from past the edge of this view"
        if o is not None and o["t"] in BELT_T and o.get("d") == OPP.get(e.get("d")):
            return f"the belt behind it at {fmt_xy((o['x'], o['y']))} faces {o.get('d')}, away from this line"
        if o is not None and o["t"] in BELT_T:
            return f"a {o['n']} behind it at {fmt_xy((o['x'], o['y']))} doesn't feed it"
        return "starts here"

    # ------------------------------------------------------------------ labels
    def _labels(self) -> None:
        """Short stable handles for this scan: A1 assembler, F2 furnace, D3 drill, C4 chest, I5 inserter, P6 pole..."""
        pref = {"assembling-machine": "A", "furnace": "F", "mining-drill": "D", "container": "C",
                "logistic-container": "C", "infinity-container": "S", "inserter": "I", "electric-pole": "P",
                "lab": "R", "boiler": "B", "generator": "G", "offshore-pump": "W", "pipe": "Q", "pipe-to-ground": "Q",
                "transport-belt": "T", "underground-belt": "U", "splitter": "X", "electric-energy-interface": "E"}
        self.label: dict[int, str] = {}
        self.by_label: dict[str, int] = {}
        count: dict[str, int] = {}
        for u, e in sorted(self.ents.items(), key=lambda kv: (kv[1]["y"], kv[1]["x"])):
            p = pref.get(e["t"], "M")
            count[p] = count.get(p, 0) + 1
            lab = f"{p}{count[p]}"
            self.label[u] = lab
            self.by_label[lab] = u
        for ln in self.lines:
            self.by_label[ln.id] = ln.belts[0]

    def name(self, u: int) -> str:
        e = self.ents.get(u)
        if not e:
            return f"#{u}"
        return f"{e['n']} {self.label.get(u, '')}".strip()

    # ------------------------------------------------------------------ machines
    def ingredients(self, recipe: str | None) -> dict:
        r = self.recipes.get(recipe or "") or {}
        return r.get("ingredients") or {}

    def source_of(self, ins: dict) -> str:
        """What an inserter picks up from, in words."""
        pu = ins.get("pku")
        if pu and pu in self.ents:
            src = self.ents[pu]
            if src["t"] in BELT_T:
                ln = self.line_of.get(pu)
                carried = items_words(ln.items, 3) if ln and ln.items else "nothing"
                return f"belt line {ln.id if ln else '?'} (carrying {carried})"
            return self.name(pu)
        return "the ground (nothing there)"

    def machine_state(self, e: dict) -> dict:
        """Plain-words state of a machine: what it does, whether it runs, and the most likely reason if not."""
        st = e.get("s") or "?"
        words = STATUS_WORDS.get(st, st.replace("_", " "))
        out = {"id": self.label.get(e["u"]), "what": e["n"], "at": fmt_xy((e["x"], e["y"])), "state": words}
        if e.get("r"):
            out["recipe"] = e["r"]
        if e.get("pw") and st not in ("working",):
            out["power"] = e["pw"]
        if "fuel" in e:
            nf = sum((e.get("fuel") or {}).values())
            out["fuel"] = "none" if nf == 0 else ("low" if nf < 5 else "ok")
        feeds = self.feeders.get(e["u"], [])
        takes = self.takers.get(e["u"], [])
        if feeds:
            out["fed_by"] = [f"{self.name(i)} from {self.source_of(self.ents[i])}" for i in feeds if i in self.ents]
        if takes:
            dst = []
            for i in takes:
                ins = self.ents.get(i)
                if not ins:
                    continue
                du = ins.get("dpu")
                dst.append(f"{self.name(i)} into {self.name(du) if du else 'the ground'}"
                           + (f" (belt line {self.line_of[du].id})" if du in self.line_of else ""))
            out["emptied_by"] = dst
        if e.get("inp"):
            out["holds_inputs"] = items_words(e["inp"])
        if e.get("out"):
            out["holds_output"] = items_words(e["out"])
        if st == "item_ingredient_shortage":
            need = self.ingredients(e.get("r"))
            have = e.get("inp") or {}
            missing = [k for k in need if have.get(k, 0) < need[k]]
            if missing:
                out["missing"] = missing
                out["why"] = self._why_missing(e, missing)
        return out

    def _why_missing(self, e: dict, missing: list[str]) -> list[str]:
        reasons = []
        feeds = [self.ents[i] for i in self.feeders.get(e["u"], []) if i in self.ents]
        for item in missing:
            srcs = []
            for ins in feeds:
                pu = ins.get("pku")
                src = self.ents.get(pu) if pu else None
                if src and src["t"] in BELT_T:
                    ln = self.line_of.get(pu)
                    if ln and item in (ln.items or {}):
                        srcs.append(("has", ln))
                    elif ln:
                        srcs.append(("line", ln))
                elif src and src["t"] in CHESTS | {"assembling-machine", "furnace"}:
                    has = (src.get("inv") or src.get("out") or {}).get(item, 0)
                    srcs.append(("chest", src, has))
            if not srcs:
                reasons.append(f"no inserter brings it {item}")
                continue
            lines = [s[1] for s in srcs if s[0] == "line"]
            if any(s[0] == "has" for s in srcs):
                reasons.append(f"{item} is on its belt but not arriving fast enough (or the inserter is slow)")
            elif lines:
                for ln in lines:
                    if ln.items:
                        reasons.append(f"its belt line {ln.id} carries {items_words(ln.items, 3)}, not {item}")
                    else:
                        why = ln.start_reason if ln.start_reason != "starts here" else "nothing puts items on it"
                        reasons.append(f"its belt line {ln.id} is empty: {why}")
            else:
                reasons.append(f"the chest/machine feeding it has no {item}")
        return reasons

    # ------------------------------------------------------------------ faults
    def wanted_faults(self, wanted: list[str]) -> list[dict]:
        """The order names a product ("fix the gear setup") that no machine here makes, and an assembler here makes
        something else from the same ingredients: it was probably set to the wrong recipe."""
        asm = [m for m in self.ents.values() if m.get("t") == "assembling-machine" and m.get("r") in self.recipes]
        out = []
        for want in wanted:
            if want not in self.recipes or any(m.get("r") == want for m in asm):
                continue
            # "fix the belts here", "the pipes are broken": the word names things standing there, not a product
            if any(e.get("n") == want for e in self.ents.values()):
                continue
            need = set(self.recipes[want].get("ingredients") or {})
            for m in asm:
                r = m["r"]
                if not need or not need <= set(self.recipes[r].get("ingredients") or {}):
                    continue
                out_at = next((e["dp"] for e in self.ents.values() if e.get("t") == "inserter"
                               and e.get("pku") == m["u"] and self.line_of.get(e.get("dpu")) and e.get("dp")), None)
                pos = (m["x"], m["y"])
                out.append({"kind": "wanted_recipe", "u": m["u"], "at": pos,
                            "text": f"{self.name(m['u'])} at {fmt_xy(pos)} makes {r}; nothing here makes {want}, "
                                    f"which it could make from the same ingredients",
                            "fixes": [{"do": "set_recipe", "x": m["x"], "y": m["y"], "recipe": want,
                                       "text": f"set {self.name(m['u'])} to make {want}",
                                       "done": f"set the {m['n']} at {fmt_xy(pos)} to make {want}"
                                               + (f" and cleared the {r} off its belt" if out_at else ""),
                                       "then_purge": {"item": r, "x": out_at[0], "y": out_at[1]} if out_at else None}]})
                break
        return out

    def faults(self) -> list[dict]:
        """Things that look broken, with code-generated candidate fixes (actions for the step runner)."""
        out: list[dict] = []
        covered: set = set()  # full chests already given as the cause of a full machine
        belts = [e for e in self.ents.values() if e["t"] == "transport-belt"]
        # 1. a belt facing against the line it sits in: neighbours on its axis both disagree with it
        for e in belts:
            d = e.get("d")
            if d not in DIRS:
                continue
            ahead, behind = self.at(*self._ahead(e)), self.at(*self._behind(e))
            dx, dy = DIRS[d]
            votes_opp = 0
            for o in (ahead, behind):
                if o is not None and o["t"] in BELT_T and o.get("d") == OPP[d]:
                    votes_opp += 1
            if votes_opp == 2 or (votes_opp == 1 and not e.get("i") and not e.get("o")):
                out.append({"kind": "belt_reversed", "u": e["u"], "at": (e["x"], e["y"]),
                            "text": f"a belt at {fmt_xy((e['x'], e['y']))} faces {d}, against the belts around it "
                                    f"(they run {OPP[d]}), so items can't pass",
                            "fixes": [{"do": "rotate", "x": e["x"], "y": e["y"], "direction": OPP[d],
                                       "text": f"turn the belt at {fmt_xy((e['x'], e['y']))} to face {OPP[d]}",
                                       "done": f"a belt at {fmt_xy((e['x'], e['y']))} was facing the wrong way, turned it back"}]})
        # 1b. a gap: a line ends with nothing ahead, and a few tiles further on, in line with it, another line starts
        # going the same way (a belt was cut or never finished)
        starts = {}
        for ln in self.lines:
            b0 = self.ents[ln.belts[0]]
            if ln.start_reason == "starts here" and b0.get("d") in DIRS:
                starts[(b0["x"], b0["y"])] = ln
        for ln in self.lines:
            last = self.ents[ln.belts[-1]]
            d = last.get("d")
            if ln.end_reason != "ends (nothing ahead)" or d not in DIRS or not ln.items:
                continue
            dx, dy = DIRS[d]
            for k in range(2, 6):
                p = (last["x"] + dx * k, last["y"] + dy * k)
                other = starts.get(p)
                if other is not None and self.ents[other.belts[0]].get("d") == d:
                    gap = [(last["x"] + dx * j, last["y"] + dy * j) for j in range(1, k)]
                    if all(self.at(*g) is None for g in gap):
                        out.append({"kind": "belt_gap", "u": last["u"], "at": (last["x"], last["y"]),
                                    "text": f"belt line {ln.id} ({items_words(ln.items, 2)}) stops at "
                                            f"{fmt_xy((last['x'], last['y']))}, {k - 1} tile(s) short of line "
                                            f"{other.id} that continues {d}",
                                    "fixes": [{"do": "connect", "item": "transport-belt",
                                               "from": [last["x"], last["y"]], "to": [p[0], p[1]],
                                               "text": f"fill the {k - 1}-tile gap in the belt at "
                                                       f"{fmt_xy(gap[0])}",
                                               "done": f"filled a gap in the belt at {fmt_xy(gap[0])}"}]})
                    break
        # 2. machines stopped
        for e in self.ents.values():
            if e["t"] not in CRAFTERS:
                continue
            st = e.get("s")
            pos = (e["x"], e["y"])
            if st == "no_fuel" or ("fuel" in e and not e.get("fuel") and st not in ("working",) and e["t"] in ("boiler", "furnace", "mining-drill")):
                out.append({"kind": "no_fuel", "u": e["u"], "at": pos,
                            "text": f"{self.name(e['u'])} at {fmt_xy(pos)} is out of fuel",
                            "fixes": [{"do": "refuel", "x": e["x"], "y": e["y"],
                                       "text": f"put coal into {self.name(e['u'])}",
                                       "done": f"refuelled the {e['n']} at {fmt_xy(pos)}"}]})
            elif st == "full_output":
                fx = []
                for i in self.takers.get(e["u"], []):
                    ins = self.ents.get(i)
                    du = ins.get("dpu") if ins else None
                    if du and du in self.ents and self.ents[du]["t"] in CHESTS and not self.ents[du].get("free"):
                        c = self.ents[du]
                        covered.add(du)  # the full chest is this fault's cause: not listed again on its own
                        fx.append({"do": "empty_chest", "x": c["x"], "y": c["y"],
                                   "text": f"empty the full chest {self.name(du)} at {fmt_xy((c['x'], c['y']))}",
                                   "done": f"made room in the full chest at {fmt_xy((c['x'], c['y']))}"})
                # no full chest behind it: a machine whose output nothing takes away is usually full on purpose
                # (a mall, a buffer). Don't offer to take a player's products; the planner can decide.
                out.append({"kind": "output_full", "u": e["u"], "at": pos,
                            "text": f"{self.name(e['u'])} at {fmt_xy(pos)} stopped: its output is full", "fixes": fx})
            elif st in ("no_power", "not_plugged_in_electric_network") or (e.get("pw") or "").startswith("no power"):
                out.append({"kind": "no_power", "u": e["u"], "at": pos,
                            "text": f"{self.name(e['u'])} at {fmt_xy(pos)} has no power ({e.get('pw') or st})",
                            "fixes": [{"do": "power", "x": e["x"], "y": e["y"],
                                       "text": f"run poles from the grid to {self.name(e['u'])}",
                                       "done": f"connected the {e['n']} at {fmt_xy(pos)} to the grid"}]})
            elif st == "no_recipe" and e["t"] == "assembling-machine":
                out.append({"kind": "no_recipe", "u": e["u"], "at": pos,
                            "text": f"{self.name(e['u'])} at {fmt_xy(pos)} has no recipe", "fixes": []})
            elif st == "item_ingredient_shortage":
                ms = self.machine_state(e)
                if ms.get("why"):
                    out.append({"kind": "starved", "u": e["u"], "at": pos,
                                "text": f"{self.name(e['u'])} at {fmt_xy(pos)} is missing {', '.join(ms.get('missing', []))}: "
                                        + "; ".join(ms["why"]), "fixes": []})
        # 2a. a machine making something nothing downstream uses, when what they're short of could be made from the
        # same ingredients (an assembler someone set to pipes in a gear slot)
        for m in self.ents.values():
            r = m.get("r")
            if m.get("t") != "assembling-machine" or not r or r not in self.recipes:
                continue
            mine = set((self.recipes[r].get("ingredients") or {}))
            needed: set = set()
            out_at = None
            for e in self.ents.values():
                if e.get("t") != "inserter" or e.get("pku") != m["u"] or not e.get("dpu"):
                    continue
                if self.line_of.get(e["dpu"]) and e.get("dp"):
                    out_at = e["dp"]
                dst = self.ents.get(e["dpu"])
                ln = self.line_of.get(e["dpu"])
                lines = [ln] + self._continues(ln) if ln else []
                consumers = ([self.ents.get(self.ents[i].get("dpu")) for x in lines for i in x.takers if i in self.ents]
                             if ln else [dst])
                for c in consumers:
                    if c and c.get("r") in self.recipes:
                        needed |= set(self.recipes[c["r"]].get("ingredients") or {})
            if not needed or r in needed:
                continue
            cand = [x for x in sorted(needed) if x in self.recipes
                    and set(self.recipes[x].get("ingredients") or {}) <= mine and x not in mine]
            if cand:
                pos = (m["x"], m["y"])
                out.append({"kind": "wrong_recipe", "u": m["u"], "at": pos,
                            "text": f"{self.name(m['u'])} at {fmt_xy(pos)} makes {r}, but what it feeds needs "
                                    f"{', '.join(sorted(needed))}",
                            "fixes": [{"do": "set_recipe", "x": m["x"], "y": m["y"], "recipe": cand[0],
                                       "text": f"set {self.name(m['u'])} to make {cand[0]}",
                                       "done": f"set the {m['n']} at {fmt_xy(pos)} to make {cand[0]}"
                                               + (f" and cleared the {r} off its belt" if out_at else ""),
                                       # what it already put on the belt would block the lane: take it off
                                       "then_purge": {"item": r, "x": out_at[0], "y": out_at[1]} if out_at else None}]})
        # 2b. labs with nothing to research
        labs = [e for e in self.ents.values() if e["t"] == "lab" and e.get("s") == "no_research_in_progress"]
        if labs:
            out.append({"kind": "no_research", "u": labs[0]["u"], "at": (labs[0]["x"], labs[0]["y"]),
                        "text": f"{len(labs)} lab(s) idle: no research in progress",
                        "fixes": [{"do": "research", "tech": "cheapest", "text": "queue the cheapest research the "
                                                                              "labs can do"}]})
        # 3. power grids that can't keep up
        for g in self.grids.values():
            cap, used = g.get("cap_w") or 0, g.get("used_w") or 0
            if g.get("boilers_low_fuel"):
                at = g.get("boilers_low_at") or []
                out.append({"kind": "boiler_fuel", "grid": g["id"], "at": tuple(at[0]) if at else self.center,
                            "boilers": [tuple(b) for b in at],
                            "text": f"grid {g['id']}: {g['boilers_low_fuel']} of {g['boilers']} boilers low on fuel",
                            "fixes": [{"do": "refuel_boilers", "grid": g["id"], "text": "refuel the boilers",
                                       "done": "refuelled the boilers"}]})
            if cap and used >= 0.97 * cap:
                out.append({"kind": "power_maxed", "grid": g["id"], "at": self.center,
                            "text": f"grid {g['id']} is maxed out: using {used / 1e6:.1f} MW of {cap / 1e6:.1f} MW",
                            "fixes": self._engine_slots(g["id"])})
        # 4. chests that are full and block an inserter
        for e in self.ents.values():
            if (e["t"] in ("container", "logistic-container") and e.get("free") == 0 and self.feeders.get(e["u"])
                    and e["u"] not in covered):
                out.append({"kind": "chest_full", "u": e["u"], "at": (e["x"], e["y"]),
                            "text": f"{self.name(e['u'])} at {fmt_xy((e['x'], e['y']))} is full ({items_words(e.get('inv'), 3)})",
                            "fixes": [{"do": "empty_chest", "x": e["x"], "y": e["y"],
                                       "text": f"empty {self.name(e['u'])}",
                                       "done": f"made room in the full chest at {fmt_xy((e['x'], e['y']))}"}]})
        # 4a. a machine short of a fluid: say which inlet and why (nothing joined, the wrong fluid in its pipe, or
        # empty pipes); fixing it is the planner's (pipes to lay or swap)
        for e in self.ents.values():
            if e.get("s") not in ("fluid_ingredient_shortage", "missing_required_fluid", "no_input_fluid"):
                continue
            why = []
            for b in e.get("fin") or []:
                want = b.get("want")
                if not want or b.get("amt"):
                    continue
                at = f" at {fmt_xy(tuple(b['at']))}" if b.get("at") else ""
                if b.get("next") and b["next"] != want:
                    why.append(f"its {want} inlet{at} has {b['next']} in the pipe joined to it (inlets swapped?)")
                elif not b.get("linked") and not b.get("next_kind"):
                    why.append(f"its {want} inlet{at} has no pipe")
                elif not b.get("linked"):
                    why.append(f"its {want} inlet{at} has a {b['next_kind']} next to it that isn't joined to it")
                elif b.get("pipes") and want not in b["pipes"]:
                    why.append(f"its {want} inlet{at} is joined to pipes carrying {', '.join(b['pipes'])}")
                else:
                    why.append(f"its {want} inlet{at} is joined to pipes with no {want} in them")
            if why:
                out.append({"kind": "fluid_input", "u": e["u"], "at": (e["x"], e["y"]),
                            "text": f"{self.name(e['u'])} at {fmt_xy((e['x'], e['y']))} is short of fluid: "
                                    + "; ".join(why), "fixes": []})
        # 4c. a machine nothing feeds, with a belt carrying what it needs two tiles out: its inserter is missing
        for e in self.ents.values():
            if e["t"] not in ("furnace", "assembling-machine") or self.feeders.get(e["u"]) or \
                    e.get("s") in ("working", "full_output", "no_recipe"):
                continue
            need = set((self.recipes.get(e.get("r")) or {}).get("ingredients") or {})
            if e["t"] == "furnace" and not need:
                need = {"iron-ore", "copper-ore", "stone", "iron-plate"}
            if not need:
                continue
            wd, ht = e.get("w", 1), e.get("h", 1)
            x0, y0 = e["x"] - wd / 2, e["y"] - ht / 2
            sides = [((x0 + i + 0.5, y0 - 0.5), (x0 + i + 0.5, y0 - 1.5)) for i in range(wd)] + \
                [((x0 + i + 0.5, y0 + ht + 0.5), (x0 + i + 0.5, y0 + ht + 1.5)) for i in range(wd)] + \
                [((x0 - 0.5, y0 + j + 0.5), (x0 - 1.5, y0 + j + 0.5)) for j in range(ht)] + \
                [((x0 + wd + 0.5, y0 + j + 0.5), (x0 + wd + 1.5, y0 + j + 0.5)) for j in range(ht)]
            for ins, belt in sides:
                b = self.at(*belt)
                ln = self.line_of.get(b["u"]) if b else None
                if not ln or not (need & set(ln.items)) or self.at(*ins) is not None or self.off_view(*ins):
                    continue
                powered = any(p.get("t") == "electric-pole" and abs(p["x"] - ins[0]) <= 2.5 and abs(p["y"] - ins[1]) <= 2.5
                              and grid_live(self.grids.get(p.get("net")) or {}) for p in self.ents.values())
                name = "inserter" if powered and e["t"] != "furnace" else "burner-inserter"
                fix = {"do": "place", "name": name, "x": ins[0], "y": ins[1], "pickup": [belt[0], belt[1]],
                       "text": f"put a {name.replace('-', ' ')} between {self.name(e['u'])} and the belt",
                       "done": f"added the missing inserter feeding the {e['n']} at {fmt_xy((e['x'], e['y']))}"}
                fix["then_power" if name == "inserter" else "then_refuel"] = True
                out.append({"kind": "unfed", "u": e["u"], "at": (e["x"], e["y"]),
                            "text": f"{self.name(e['u'])} at {fmt_xy((e['x'], e['y']))} has nothing feeding it, though "
                                    f"belt line {ln.id} ({items_words(ln.items, 2)}) runs right by it",
                            "fixes": [fix]})
                break
        # 4b. an inserter facing backwards: it takes from a machine that nothing feeds and drops onto a belt carrying
        # that machine's ingredients (its input belt)
        for e in self.ents.values():
            # (a furnace that never smelted has no recipe yet)
            if e["t"] not in ("furnace", "assembling-machine") or self.feeders.get(e["u"]) or \
                    (not e.get("r") and e["t"] != "furnace"):
                continue
            need = set((self.recipes.get(e.get("r")) or {}).get("ingredients") or {})
            if e["t"] == "furnace" and not need:
                need = {"iron-ore", "copper-ore", "stone", "iron-plate"}
            for i in self.takers.get(e["u"], []):
                ins = self.ents.get(i) or {}
                ln = self.line_of.get(ins.get("dpu"))
                if ln and need & set(ln.items) and ins.get("d"):
                    back = {"north": "south", "south": "north", "east": "west", "west": "east"}.get(ins["d"])
                    out.append({"kind": "inserter_backwards", "u": i, "at": (ins["x"], ins["y"]),
                                "text": f"{self.name(i)} at {fmt_xy((ins['x'], ins['y']))} takes from {self.name(e['u'])} "
                                        f"and drops onto its input belt: it faces backwards, so nothing feeds the "
                                        f"{e['n']}",
                                "fixes": [{"do": "rotate", "x": ins["x"], "y": ins["y"], "direction": back,
                                           "text": f"turn {self.name(i)} around",
                                           "done": f"turned the inserter at {fmt_xy((ins['x'], ins['y']))} around"}]})
                    break
        # 5. inserters dropping on the ground or picking from nothing
        for e in self.ents.values():
            if e["t"] == "inserter" and e.get("s") == "waiting_for_source_items" and not e.get("pku"):
                out.append({"kind": "inserter_no_source", "u": e["u"], "at": (e["x"], e["y"]),
                            "text": f"{self.name(e['u'])} at {fmt_xy((e['x'], e['y']))} has nothing to pick up from "
                                    f"at {fmt_xy(e['pk'])}", "fixes": []})
        return out

    # ------------------------------------------------------------------ summaries
    def summary(self, focus=None, coords: bool = True, max_items: int = 40) -> dict:
        """The area as a player would describe it. coords=False gives relative words only (for Jev)."""
        focus = focus or self.center

        def where(x, y):
            return fmt_xy((x, y)) if coords else rel(focus, (x, y))
        machines = []
        crafters = sorted(self.of_type(*CRAFTERS), key=lambda e: (e["y"], e["x"]))
        if len(crafters) > 30:
            # a big area: groups of the same machine, recipe and state, with where they are; look closer for detail
            groups: dict = {}
            for e in crafters:
                st = STATUS_WORDS.get(e.get("s") or "?", e.get("s") or "?")
                key = (e["n"], e.get("r"), st)
                g = groups.setdefault(key, {"what": e["n"], "recipe": e.get("r"), "state": st, "count": 0,
                                            "xs": [], "ys": []})
                g["count"] += 1
                g["xs"].append(e["x"])
                g["ys"].append(e["y"])
            for g in sorted(groups.values(), key=lambda g: -g["count"]):
                xs, ys = g.pop("xs"), g.pop("ys")
                g["area"] = (f"{min(xs):g}..{max(xs):g}, {min(ys):g}..{max(ys):g}" if coords else
                             rel(focus, ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)))
                if not g["recipe"]:
                    g.pop("recipe")
                machines.append(g)
        else:
            for e in crafters[:max_items]:
                m = self.machine_state(e)
                m["at"] = where(e["x"], e["y"])
                machines.append(m)
        lines = []
        for ln in sorted(self.lines, key=lambda l: -l.length)[:max_items]:
            d = {"id": ln.id, "belts": ln.length, "runs": ln.direction, "from": where(*ln.start), "to": where(*ln.end),
                 "carrying": items_words(ln.items, 4), "end": ln.end_reason}
            if ln.start_reason not in ("starts here", "fed from another line"):
                d["start"] = ln.start_reason
            if ln.density >= 7:
                d["backed_up"] = True
            if ln.takers:
                d["taken_by"] = len(ln.takers)
            lines.append(d)
        chests = []
        for e in self.of_type(*CHESTS):
            c = {"id": self.label.get(e["u"]), "what": e["n"], "at": where(e["x"], e["y"]),
                 "holds": items_words(e.get("inv"), 5)}
            if e.get("free") == 0:
                c["full"] = True
            if e.get("infinite"):
                c["endless"] = True
            chests.append(c)
        grids = []
        for g in self.grids.values():
            cap, used = g.get("cap_w") or 0, g.get("used_w") or 0
            gd = {"grid": g["id"], "load": f"{used / 1e6:.1f} of {cap / 1e6:.1f} MW" if coords else
                  ("overloaded" if cap and used >= 0.97 * cap else "busy" if cap and used > 0.7 * cap else "fine"),
                  "generators": ", ".join(f"{n} {k}" for k, n in (g.get("gens") or {}).items()) or "none"}
            if g.get("boilers"):
                gd["boilers"] = f"{g['boilers']} ({g.get('boilers_low_fuel', 0)} low on fuel)"
            if not grid_live(g):
                gd["load"] = "dead: nothing on it is making power"
            grids.append(gd)
        out = {"machines": machines, "belt_lines": lines, "chests": chests, "power": grids}
        poles = self.of_type("electric-pole")
        others = {}
        for e in self.ents.values():
            if e["t"] not in CRAFTERS | CHESTS | BELT_T | {"inserter"} and not (coords and e["t"] == "electric-pole"
                                                                                  and len(poles) <= 30):
                others[e["n"]] = others.get(e["n"], 0) + 1
        if others:
            out["other"] = others
        ins = self.of_type("inserter")
        if ins and coords and len(ins) <= 40:
            # where each inserter is and what it moves between: the planner needs exact tiles to reuse or fix them
            lst = []
            for e in sorted(ins, key=lambda e: (e["y"], e["x"])):
                d = {"id": self.label.get(e["u"]), "what": e["n"], "at": where(e["x"], e["y"])}
                src = self.name(e["pku"]) if e.get("pku") in self.ents else ("ground " + fmt_xy(e["pk"]) if e.get("pk") else "?")
                dst = self.name(e["dpu"]) if e.get("dpu") in self.ents else ("ground " + fmt_xy(e["dp"]) if e.get("dp") else "?")
                d["moves"] = f"{src} -> {dst}"
                st_ = e.get("s")
                if st_ and st_ not in ("working", "waiting_for_source_items"):
                    d["state"] = STATUS_WORDS.get(st_, st_)
                if e.get("pw"):
                    d["power"] = e["pw"]
                lst.append(d)
            out["inserters"] = lst
        elif ins:
            out["inserters"] = len(ins)
        if poles and coords and len(poles) <= 30:
            out["poles"] = [f"{e['n']} {fmt_xy((e['x'], e['y']))} grid {e.get('net')}" for e in
                            sorted(poles, key=lambda e: (e["y"], e["x"]))]
        if self.ghosts:
            gh: dict = {}
            for g in self.ghosts:
                gh[g["n"]] = gh.get(g["n"], 0) + 1
            out["planned_ghosts"] = gh
        if self.res:
            out["ore"] = {k: {"tiles": v["n"], "amount": v["amount"],
                              "area": f"{v['x0']:g},{v['y0']:g} to {v['x1']:g},{v['y1']:g}" if coords else
                              rel(focus, ((v['x0'] + v['x1']) / 2, (v['y0'] + v['y1']) / 2))}
                          for k, v in self.res.items()}
        if self.water:
            out["water"] = where(self.water["x"], self.water["y"])
        return out
