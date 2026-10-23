"""Row of machines along an existing belt: the most common build, generated exactly so the planner doesn't have to
work out every inserter, pole and chest by hand.

    row_entities(belt=(x, y), belt_dir="east", side="south", machine="assembling-machine-1", recipe="iron-gear-wheel",
                 count=3, second_belt=False, output="chest", inserter="inserter", offset=0)

Geometry, with `d` the belt's direction and `n` the side the machines go (perpendicular to d), in tiles from the belt:
  1        input inserters, picking from the belt (and poles between them)
  2..S+1   the machines (S = 3 for assemblers, 2 for stone/steel furnaces)
  S+2      a second input row picking from a second belt at S+3 (second_belt=True), or output inserters dropping onto
           an output belt at S+3 (output="belt"); poles share this row
  output="chest": an output inserter beside each machine (downstream side) puts into a chest; pitch S+2
The row starts at the belt tile and grows downstream (the way the belt runs), offset tiles further on.
"""
from __future__ import annotations

DIRS = {"north": (0, -1), "east": (1, 0), "south": (0, 1), "west": (-1, 0)}
OPP = {"north": "south", "south": "north", "east": "west", "west": "east"}
SIZE = {"assembling-machine-1": 3, "assembling-machine-2": 3, "assembling-machine-3": 3, "stone-furnace": 2,
        "steel-furnace": 2, "electric-furnace": 3, "chemical-plant": 3, "lab": 3}


def row_entities(belt, belt_dir: str, side: str, machine: str, recipe: str | None, count: int,
                 second_belt: bool = False, output: str = "chest", inserter: str = "inserter",
                 offset: int = 0, pole: str = "small-electric-pole") -> tuple[list[dict], dict]:
    if belt_dir not in DIRS or side not in DIRS:
        raise ValueError("belt_dir and side must be north/east/south/west")
    dx, dy = DIRS[belt_dir]
    nx, ny = DIRS[side]
    if dx * nx + dy * ny != 0:
        raise ValueError(f"side {side} must be across the belt (it runs {belt_dir})")
    S = SIZE.get(machine, 3)
    bx, by = float(belt[0]), float(belt[1])
    bx, by = int(bx // 1) + 0.5, int(by // 1) + 0.5  # belt tile center

    def at(along: float, across: float) -> tuple[float, float]:
        return bx + dx * along + nx * across, by + dy * along + ny * across

    ents: list[dict] = []
    burner = machine in ("stone-furnace", "steel-furnace")
    pitch = S + 2 if output == "chest" else S
    if output == "belt" and second_belt:
        raise ValueError("output='belt' needs the far side free: use output='chest' with a second belt")
    poles_far = second_belt or output == "belt"
    for k in range(int(count)):
        a = offset + k * pitch  # first tile (along) of this machine
        mid = a + (S - 1) / 2  # machine center along
        col = a + (S // 2)  # the column the input inserters use (middle for 3, first+1 for 2)
        if S == 2:
            col = a
        cx, cy = at(mid, 1 + (S + 1) / 2)
        m = {"name": machine, "x": cx, "y": cy}
        if recipe and not burner:
            m["recipe"] = recipe
        ents.append(m)
        ix, iy = at(col, 1)
        ents.append({"name": inserter, "x": ix, "y": iy, "direction": OPP[side]})  # takes from the belt side
        if second_belt:
            jx, jy = at(col, S + 2)
            ents.append({"name": inserter, "x": jx, "y": jy, "direction": side})  # takes from the far belt
        if output == "chest":
            ox, oy = at(a + S, 1 + (S + 1) // 2 if S == 3 else 2)
            # the output inserter takes from the machine (upstream side along d) and drops into the chest beyond it
            ents.append({"name": inserter, "x": ox, "y": oy, "direction": OPP[belt_dir]})
            chx, chy = at(a + S + 1, 1 + (S + 1) // 2 if S == 3 else 2)
            ents.append({"name": "iron-chest", "x": chx, "y": chy})
        elif output == "belt":
            ox, oy = at(col, S + 2)
            ents.append({"name": inserter, "x": ox, "y": oy, "direction": OPP[side]})  # takes from the machine
        # poles: one in the input row (and the far row) every machine with chest output, every other otherwise
        if not burner or inserter != "burner-inserter":
            if output == "chest" or k % 2 == 0:
                px, py = at(a + S if output == "chest" else col + 1, 1)
                ents.append({"name": pole, "x": px, "y": py})
                if poles_far:
                    qx, qy = at(a + S if output == "chest" else col + 1, S + 2)
                    ents.append({"name": pole, "x": qx, "y": qy})
    if output == "belt":
        n_len = (int(count) - 1) * pitch + S + 1
        for t in range(offset, offset + n_len):
            x, y = at(t, S + 3)
            ents.append({"name": "transport-belt", "x": x, "y": y, "direction": belt_dir})
    end_along = offset + (int(count) - 1) * pitch + S + 1
    info = {"machines": int(count), "pitch": pitch, "length": end_along - offset,
            "covers": [at(offset, 0), at(end_along, S + 3)]}
    if output == "belt":
        ox, oy = at(end_along - 1, S + 3)
        info["output_belt_end"] = [ox, oy]
    return ents, info


def extend_input(belt, belt_dir: str, length: int, at, name: str = "transport-belt") -> list[dict]:
    """Belts that carry the row's input belt on downstream over the row's whole length (a tap's short split-off belt,
    any line that ends early): from the tile after `belt`, over free tiles, up to the first tile something else
    stands on. at(x, y) -> the entity there as {"t", "d"} or None. Tiles already holding a belt running the same way
    at the start are passed over."""
    dx, dy = DIRS[belt_dir]
    bx, by = int(float(belt[0]) // 1) + 0.5, int(float(belt[1]) // 1) + 0.5
    out = []
    for k in range(1, int(length)):
        x, y = bx + dx * k, by + dy * k
        o = at(x, y)
        if o is None:
            out.append({"name": name, "x": x, "y": y, "direction": belt_dir})
        elif o.get("t") == "transport-belt" and o.get("d") == belt_dir and not out:
            continue
        else:
            break
    return out
