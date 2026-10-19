"""The design library: blueprints an agent can build by name, wherever it goes.

Two kinds, one list (`names()`, `list_designs()`, `stamp()`):
- built-in: proven, in-game-validated designs shipped in crew/blueprints/ (entity lists with ports, below);
- learned: the agent's own library, kept per user across worlds (~/.local/state/factorio-serf/designs/): builds it
  copied after they worked, and blueprints players taught it (`/serf learn`). These keep Factorio's own blueprint
  string, so they rebuild exactly as copied (undergrounds, filters, recipes); they're placed with the mod's paste.

Each built-in design is one JSON file in crew/blueprints/ (see that folder). Entity positions are relative to the design's
top-left corner (0,0), written exactly as Factorio wants them: 1x1 and 3x3 entities at .5 centers, 2x2 at integer
corners, 3x2 / 3x5 / 1x2 entities at their real centers. Directions use Factorio 2.0 semantics, verified in game:
an inserter's direction is the side it TAKES from (it drops on the opposite side); belts point the way items
move; drills drop in front; a boiler points its steam output (water enters at its short ends); an offshore pump
faces the water and outputs behind itself; steam engines connect along their long axis.

    from crew import blueprint_lib as bp
    bp.list_designs()                                  # compact summaries for the agent
    bp.summary_text()                                  # the same as one short text block
    ents = bp.stamp_entities("red-science-5", 100, 40, rotation=90)
    # -> [{"name", "x", "y", "direction", "recipe"?}, ...] for the mod's act op `blueprint` (entities=...)
    full = bp.stamp("red-science-5", 100, 40, 90)      # + absolute inputs/outputs, bbox, needs
    bp.needs("red-science-5")                          # {item: count} to build it

Rotation is clockwise in 90-degree steps (0/90/180/270, or a direction name: "east" == 90 means "what faces north
in the design faces east"). (x, y) is where the ROTATED design's top-left corner goes; with anchor=<entity name>
(e.g. anchor="offshore-pump"), (x, y) is where that entity's position goes instead, which is how you stamp a
design onto a spot the game gave you (find water -> offshore_pump_spots [{p, direction}] -> rotation=direction).
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import time
from pathlib import Path

DESIGN_DIR = Path(__file__).resolve().parent / "blueprints"
DIRS = ["north", "east", "south", "west"]
VEC = {"north": (0, -1), "east": (1, 0), "south": (0, 1), "west": (-1, 0)}

# Footprint (w, h) when facing north; east/west swap them. Anything not listed is 1x1.
SIZES: dict[str, tuple[int, int]] = {
    "stone-furnace": (2, 2), "steel-furnace": (2, 2), "burner-mining-drill": (2, 2),
    "electric-energy-interface": (2, 2), "medium-electric-pole": (1, 1), "big-electric-pole": (2, 2),
    "substation": (2, 2), "assembling-machine-1": (3, 3), "assembling-machine-2": (3, 3),
    "assembling-machine-3": (3, 3), "electric-mining-drill": (3, 3), "lab": (3, 3), "electric-furnace": (3, 3),
    "chemical-plant": (3, 3), "boiler": (3, 2), "steam-engine": (3, 5), "oil-refinery": (5, 5),
}
# Placeable entity -> the item that builds it, where the names differ.
ITEM_FOR = {"straight-rail": "rail", "curved-rail-a": "rail", "curved-rail-b": "rail", "half-diagonal-rail": "rail"}

_cache: dict[str, tuple[float, dict]] = {}


# ---------------------------------------------------------------------------- loading
def learned_dir() -> Path:
    """The agent's own designs, shared by all worlds of this user (SERF_DESIGNS_DIR overrides, for tests)."""
    if os.environ.get("SERF_DESIGNS_DIR"):
        return Path(os.environ["SERF_DESIGNS_DIR"])
    from .config import _home
    return _home("~/.local/state", "factorio-serf") / "designs"


def _path(name: str) -> Path:
    for d in (DESIGN_DIR, learned_dir()):
        p = d / f"{name}.json"
        if p.exists():
            return p
    raise KeyError(f"no design named {name!r}; have: {', '.join(names())}")


def names() -> list[str]:
    learned = learned_dir()
    return sorted({p.stem for p in DESIGN_DIR.glob("*.json")}
                  | ({p.stem for p in learned.glob("*.json")} if learned.is_dir() else set()))


def is_learned(design: dict) -> bool:
    return bool(design.get("string")) and not design.get("entities")


def is_builtin(name: str) -> bool:
    return bool(name) and (DESIGN_DIR / f"{name}.json").exists()


def save_learned(name: str, string: str, info: dict, note: str, source: dict) -> dict:
    """Add (or replace) one of the agent's own designs. info: the mod's blueprint_info (size, needs, by_name)."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", name or ""):
        raise ValueError("design names are 1-40 letters, digits, - or _")
    if is_builtin(name):
        raise ValueError(f"{name} is a built-in design; pick another name")
    d = {"name": name, "description": note.strip()[:400], "size": list(info["size"]), "needs": info.get("needs") or {},
         "contents": info.get("by_name") or {}, "string": string,
         "learned": {**source, "at": time.strftime("%Y-%m-%d %H:%M")}, "uses": 0}
    folder = learned_dir()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.json").write_text(json.dumps(d, indent=1))
    _cache.pop(name, None)
    return d


def forget(name: str) -> None:
    """Drop one of the agent's own designs (moved to designs/.forgotten/, not deleted)."""
    p = learned_dir() / f"{name}.json"
    if not p.exists():
        raise KeyError(f"{name!r} isn't one of your learned designs" + (" (built-ins stay)" if
                                                                          (DESIGN_DIR / f"{name}.json").exists() else ""))
    trash = learned_dir() / ".forgotten"
    trash.mkdir(exist_ok=True)
    shutil.move(str(p), str(trash / f"{name}-{int(time.time())}.json"))
    _cache.pop(name, None)


def used(name: str) -> None:
    """Count a build from a learned design (shown in the list, so proven ones stand out)."""
    try:
        p = _path(name)
        if p.parent == DESIGN_DIR:
            return
        d = json.loads(p.read_text())
        d["uses"] = int(d.get("uses", 0)) + 1
        p.write_text(json.dumps(d, indent=1))
        _cache.pop(name, None)
    except (KeyError, OSError, ValueError):
        pass


def get_design(name: str) -> dict:
    """The design dict (cached; re-read when its file changes)."""
    p = _path(name)
    mt = p.stat().st_mtime
    hit = _cache.get(name)
    if hit and hit[0] == mt:
        return hit[1]
    d = json.loads(p.read_text())
    d.setdefault("name", name)
    _cache[name] = (mt, d)
    return d


def load_designs() -> dict[str, dict]:
    return {n: get_design(n) for n in names()}


# ---------------------------------------------------------------------------- geometry
def rotation_steps(rotation) -> int:
    """Degrees clockwise (0/90/180/270, -90 ...) or a direction name -> number of clockwise quarter turns."""
    if rotation is None:
        return 0
    if isinstance(rotation, str):
        r = rotation.strip().lower()
        if r in DIRS:
            return DIRS.index(r)
        rotation = float(r)
    r = float(rotation)
    if r % 90:
        raise ValueError(f"rotation must be a multiple of 90 degrees, got {rotation!r}")
    return int(r // 90) % 4


def rotate_dir(direction: str, steps: int) -> str:
    return DIRS[(DIRS.index(direction or "north") + steps) % 4]


def opposite(direction: str) -> str:
    return rotate_dir(direction, 2)


def rotate_point(x: float, y: float, w: float, h: float, steps: int) -> tuple[float, float]:
    """Rotate a point of a w x h design clockwise about its corner; the result is in the rotated design's frame,
    whose top-left is again (0,0). Works for points outside the box too (it is a rigid motion)."""
    steps %= 4
    if steps == 0:
        return x, y
    if steps == 1:
        return h - y, x
    if steps == 2:
        return w - x, h - y
    return y, w - x


def rotated_size(design: dict, steps: int) -> tuple[int, int]:
    w, h = design["size"]
    return (h, w) if steps % 2 else (w, h)


def entity_size(name: str, direction: str = "north") -> tuple[int, int]:
    w, h = SIZES.get(name, (1, 1))
    return (h, w) if direction in ("east", "west") else (w, h)


def _num(v: float):
    v = round(v * 2) / 2  # every valid position is on a half-tile
    return int(v) if v == int(v) else v


def _rot_entity(e: dict, w: int, h: int, steps: int, ox: float, oy: float) -> dict:
    x, y = rotate_point(e["x"], e["y"], w, h, steps)
    out = {"name": e["name"], "x": _num(x + ox), "y": _num(y + oy),
           "direction": rotate_dir(e.get("direction", "north"), steps)}
    if e.get("recipe"):
        out["recipe"] = e["recipe"]
    return out


def _rot_port(p: dict, w: int, h: int, steps: int, ox: float, oy: float) -> dict:
    q = dict(p)
    if "at" in p:
        # `at` is a tile; rotate its center, then back to the tile's corner
        cx, cy = rotate_point(p["at"][0] + 0.5, p["at"][1] + 0.5, w, h, steps)
        q["at"] = [int(math.floor(cx - 0.5 + ox)), int(math.floor(cy - 0.5 + oy))]
    if "side" in p:
        q["side"] = rotate_dir(p["side"], steps)
    return q


def _origin(design: dict, x: float, y: float, steps: int, anchor: str | None) -> tuple[int, int]:
    if not anchor:
        return int(math.floor(x + 1e-6)), int(math.floor(y + 1e-6))
    w, h = design["size"]
    for e in design["entities"]:
        if e["name"] == anchor:
            ax, ay = rotate_point(e["x"], e["y"], w, h, steps)
            return int(round(x - ax)), int(round(y - ay))
    raise KeyError(f"design {design['name']} has no {anchor!r} to anchor on")


def stamp(name: str, x: float, y: float, rotation=0, anchor: str | None = None) -> dict:
    """Absolute layout of a design: entities (for the `blueprint` act op), inputs/outputs with world tiles and
    sides, bounding box [[x0,y0],[x1,y1]) in tiles, size after rotation, and items needed."""
    d = get_design(name)
    steps = rotation_steps(rotation)
    w, h = d["size"]
    rw, rh = rotated_size(d, steps)
    if is_learned(d):  # placed whole by the mod's paste: centre + direction instead of an entity list
        ox, oy = int(math.floor(x + 1e-6)), int(math.floor(y + 1e-6))
        return {"name": d["name"], "rotation": steps * 90, "origin": [ox, oy], "size": [rw, rh],
                "bbox": [[ox, oy], [ox + rw, oy + rh]], "entities": None, "inputs": [], "outputs": [],
                "needs": needs(name), "string": d["string"], "center": [ox + rw / 2, oy + rh / 2],
                "direction": DIRS[steps]}
    ox, oy = _origin(d, x, y, steps, anchor)
    return {
        "name": d["name"], "rotation": steps * 90, "origin": [ox, oy], "size": [rw, rh],
        "bbox": [[ox, oy], [ox + rw, oy + rh]],
        "entities": [_rot_entity(e, w, h, steps, ox, oy) for e in d["entities"]],
        "inputs": [_rot_port(p, w, h, steps, ox, oy) for p in d.get("inputs", [])],
        "outputs": [_rot_port(p, w, h, steps, ox, oy) for p in d.get("outputs", [])],
        "needs": needs(name),
    }


def stamp_entities(name: str, x: float, y: float, rotation=0, anchor: str | None = None) -> list[dict]:
    """Absolute entity list [{name, x, y, direction, recipe?}] for the mod's `blueprint` act op."""
    return stamp(name, x, y, rotation, anchor)["entities"]


def needs(name: str) -> dict[str, int]:
    """Items needed to build the design (fuel and inputs not included)."""
    d = get_design(name)
    if d.get("needs"):
        return dict(d["needs"])
    return compute_needs(d)


def compute_needs(design: dict) -> dict[str, int]:
    out: dict[str, int] = {}
    for e in design["entities"]:
        item = ITEM_FOR.get(e["name"], e["name"])
        out[item] = out.get(item, 0) + 1
    return dict(sorted(out.items()))


# ---------------------------------------------------------------------------- agent-facing summaries
def _port_text(p: dict, kind: str) -> str:
    if "at" not in p:
        return p.get("what", "?")
    if p.get("kind") in ("chest", "power") or not p.get("side"):
        return f"{p.get('what', '?')} [tile ({p['at'][0]},{p['at'][1]})]"
    how = f"belt enters from the {p['side']}" if kind == "in" else f"belt leaves to the {p['side']}"
    return f"{p.get('what', '?')}: {how} at tile ({p['at'][0]},{p['at'][1]})"


def list_designs() -> list[dict]:
    """Compact summaries: name, size, what it does, inputs/outputs (design-relative tiles), build cost."""
    out = []
    for n in names():
        d = get_design(n)
        out.append({
            "name": n, "size": d["size"], "does": d.get("description", ""),
            **({"learned": d.get("learned") or {}, "uses": d.get("uses", 0)} if is_learned(d) else {}),
            "inputs": [_port_text(p, "in") for p in d.get("inputs", [])],
            "outputs": [_port_text(p, "out") for p in d.get("outputs", [])],
            "needs": needs(n),
            **({"placement": d["placement"]} if d.get("placement") else {}),
        })
    return out


def summary_text() -> str:
    lines = []
    for s in list_designs():
        need = ", ".join(f"{k} {v}" for k, v in s["needs"].items())
        tag = ""
        if "learned" in s:
            src = s["learned"]
            tag = (f" [yours: from {src.get('by', '?')}" + (f", built {s['uses']}x" if s.get("uses") else "") + "]")
        lines.append(f"- {s['name']} ({s['size'][0]}x{s['size'][1]}){tag}: {s['does']}")
        if s["inputs"]:
            lines.append("    in: " + "; ".join(s["inputs"]))
        if s["outputs"]:
            lines.append("    out: " + "; ".join(s["outputs"]))
        if s.get("placement"):
            lines.append("    placement: " + s["placement"])
        lines.append("    build: " + need)
    return "\n".join(lines)


# ---------------------------------------------------------------------------- static checks
def footprint_tiles(e: dict) -> list[tuple[int, int]]:
    w, h = entity_size(e["name"], e.get("direction", "north"))
    x0, y0 = e["x"] - w / 2, e["y"] - h / 2
    return [(int(math.floor(x0 + i + 1e-6)), int(math.floor(y0 + j + 1e-6))) for i in range(w) for j in range(h)]


def check_layout(entities: list[dict], size: tuple[int, int] | None = None, origin=(0, 0)) -> list[str]:
    """Problems with a layout: positions off the tile grid for their footprint, overlaps, outside the box."""
    probs, seen = [], {}
    for e in entities:
        w, h = entity_size(e["name"], e.get("direction", "north"))
        x0, y0 = e["x"] - w / 2, e["y"] - h / 2
        if abs(x0 - round(x0)) > 1e-6 or abs(y0 - round(y0)) > 1e-6:
            probs.append(f"{e['name']} at ({e['x']},{e['y']}) is off the grid for a {w}x{h} footprint")
            continue
        if e.get("direction", "north") not in DIRS:
            probs.append(f"{e['name']} at ({e['x']},{e['y']}) has bad direction {e.get('direction')!r}")
        for t in footprint_tiles(e):
            if size and not (origin[0] <= t[0] < origin[0] + size[0] and origin[1] <= t[1] < origin[1] + size[1]):
                probs.append(f"{e['name']} at ({e['x']},{e['y']}) sticks out of the {size[0]}x{size[1]} box")
                break
            if t in seen:
                probs.append(f"{e['name']} at ({e['x']},{e['y']}) overlaps {seen[t]}")
                break
            seen[t] = f"{e['name']} at ({e['x']},{e['y']})"
    return probs


POLES = {"small-electric-pole": (2.5, 7.5), "medium-electric-pole": (3.5, 9), "substation": (9, 18),
         "big-electric-pole": (2, 30)}  # supply half-width, wire reach
ELECTRIC = {"inserter", "fast-inserter", "long-handed-inserter", "bulk-inserter", "assembling-machine-1",
            "assembling-machine-2", "assembling-machine-3", "lab", "electric-mining-drill", "electric-furnace",
            "chemical-plant", "oil-refinery", "pump", "radar", "beacon"}


def check_power(entities: list[dict]) -> list[str]:
    """Every electric consumer touches some pole's supply area, and the poles form one wired network."""
    poles = [e for e in entities if e["name"] in POLES]
    probs = []
    for e in entities:
        if e["name"] not in ELECTRIC:
            continue
        w, h = entity_size(e["name"], e.get("direction", "north"))
        covered = False
        for p in poles:
            r = POLES[p["name"]][0]
            if (abs(e["x"] - p["x"]) < w / 2 + r) and (abs(e["y"] - p["y"]) < h / 2 + r):
                covered = True
                break
        if not covered:
            probs.append(f"{e['name']} at ({e['x']},{e['y']}) is not in any pole's supply area")
    if poles:
        seen, todo = {0}, [0]
        while todo:
            i = todo.pop()
            for j, q in enumerate(poles):
                if j not in seen:
                    reach = min(POLES[poles[i]["name"]][1], POLES[q["name"]][1])
                    if math.dist((poles[i]["x"], poles[i]["y"]), (q["x"], q["y"])) <= reach:
                        seen.add(j)
                        todo.append(j)
        if len(seen) < len(poles):
            probs.append(f"poles are not all wired together ({len(seen)}/{len(poles)} reachable)")
    return probs


def validate(name: str) -> list[str]:
    """Static checks of a design in every rotation (no game needed)."""
    d = get_design(name)
    probs = [f"[{name}] {p}" for p in check_layout(d["entities"], tuple(d["size"]))]
    probs += [f"[{name}] {p}" for p in check_power(d["entities"])]
    if d.get("needs") and d["needs"] != compute_needs(d):
        probs.append(f"[{name}] needs {d['needs']} != entities {compute_needs(d)}")
    for steps in (1, 2, 3):
        st = stamp(name, 0, 0, steps * 90)
        probs += [f"[{name} rot {steps * 90}] {p}" for p in check_layout(st["entities"], tuple(st["size"]))]
    for p in d.get("inputs", []) + d.get("outputs", []):
        if p.get("side") and p["side"] not in DIRS:
            probs.append(f"[{name}] port {p.get('what')} has bad side {p['side']!r}")
    return probs


def stamp_text(st: dict) -> str:
    """One short reply for an agent after stamping: where things are and what to bring."""
    lines = [f"{st['name']} rotated {st['rotation']} occupies x {st['bbox'][0][0]}..{st['bbox'][1][0] - 1}, "
             f"y {st['bbox'][0][1]}..{st['bbox'][1][1] - 1}"]
    for p in st["inputs"]:
        lines.append("in: " + _port_text(p, "in"))
    for p in st["outputs"]:
        lines.append("out: " + _port_text(p, "out"))
    lines.append("build: " + ", ".join(f"{k} {v}" for k, v in st["needs"].items()))
    return "\n".join(lines)
