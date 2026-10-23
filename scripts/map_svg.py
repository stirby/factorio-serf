#!/usr/bin/env python3
"""Draw a base from above as an SVG: every building of the player force as its footprint, coloured by kind, with a
dot for machines that are starved (red), blocked (orange) or unpowered (purple); ore patches and water faintly
behind. For judging by eye whether a base is laid out like a player's (rows, a bus) or tangled. Read-only.

    .venv/bin/python scripts/map_svg.py --instance 85 out.svg          # a running server
    .venv/bin/python scripts/map_svg.py --save bench/campaigns/p7/saves/p7-g02-t090.zip out.svg   # loads a copy
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from jev.rcon import Crew, Rcon  # noqa: E402

LUA_BODY = """
local s = game.surfaces.nauvis
local ents, x0, y0, x1, y1 = {}, 1e9, 1e9, -1e9, -1e9
for _, e in pairs(s.find_entities_filtered { force = 'player', area = AREA }) do
  if e.type ~= 'character' and e.type ~= 'entity-ghost' then
    local b = e.bounding_box
    local ok, st = pcall(function() return e.status end)
    local code = ''
    if ok and st then
      local d = defines.entity_status
      if st == d.working or st == d.normal then code = 'w'
      elseif st == d.no_ingredients or st == d.no_input_fluid or st == d.no_minable_resources or st == d.no_fuel
        or st == d.missing_required_fluid or st == d.waiting_for_source_items then code = 's'
      elseif st == d.full_output or st == d.waiting_for_space_in_destination or st == d.full_burnt_result_output then code = 'b'
      elseif st == d.no_power or st == d.low_power then code = 'p' end
    end
    ents[#ents + 1] = { e.type, e.name, b.left_top.x, b.left_top.y, b.right_bottom.x, b.right_bottom.y, code }
    if e.type ~= 'electric-pole' and e.type ~= 'radar' then
      x0, y0 = math.min(x0, b.left_top.x), math.min(y0, b.left_top.y)
      x1, y1 = math.max(x1, b.right_bottom.x), math.max(y1, b.right_bottom.y)
    end
  end
end
local pad = 16
x0, y0, x1, y1 = math.floor(x0) - pad, math.floor(y0) - pad, math.ceil(x1) + pad, math.ceil(y1) + pad
local ore, water = {}, {}
local area = { { x0, y0 }, { x1, y1 } }
for _, r in pairs(s.find_entities_filtered { area = area, type = 'resource' }) do
  ore[math.floor(r.position.x / 2) .. ',' .. math.floor(r.position.y / 2)] = r.name
end
for _, t in pairs(s.find_tiles_filtered { area = area, collision_mask = 'water_tile' }) do
  water[math.floor(t.position.x / 2) .. ',' .. math.floor(t.position.y / 2)] = true
end
local o, w = {}, {}
for k, v in pairs(ore) do o[#o + 1] = k .. ',' .. v end
for k in pairs(water) do w[#w + 1] = k end
return helpers.table_to_json { box = { x0, y0, x1, y1 }, ents = ents, ore = o, water = w, tick = game.tick }
"""


def lua(area=None) -> str:
    """The dump, of everything of the player force or only what's in area ((x0, y0), (x1, y1))."""
    a = "nil" if area is None else f"{{{{{area[0][0]},{area[0][1]}}},{{{area[1][0]},{area[1][1]}}}}}"
    return "local AREA = " + a + "\n" + LUA_BODY


LUA = lua()


COLOURS = {
    "transport-belt": "#d6b31b", "underground-belt": "#a88a10", "splitter": "#e8c84a", "inserter": "#7bab3c",
    "assembling-machine": "#4a78b5", "furnace": "#c46a2b", "mining-drill": "#7a5aa8", "pipe": "#62aec4",
    "pipe-to-ground": "#3f8aa0", "pump": "#62aec4", "storage-tank": "#62aec4", "offshore-pump": "#2f8f9f",
    "electric-pole": "#8c8c8c", "container": "#8b6a3e", "logistic-container": "#a0763e", "boiler": "#b04040",
    "generator": "#c05050", "solar-panel": "#2a3d66", "accumulator": "#6a6a90", "lab": "#d8d8f0",
    "rocket-silo": "#f0f0f0", "radar": "#999999", "wall": "#555555", "gate": "#666666", "lamp": "#eeee99",
    "beacon": "#5aa0a0", "roboport": "#a0a0a0", "train-stop": "#cc6666", "straight-rail": "#777777",
}
TYPE_OVERRIDES = {"chemical-plant": "#3aa88a", "oil-refinery": "#2a8a6a", "centrifuge": "#5a9a5a",
                  "fast-transport-belt": "#d23a2a", "express-transport-belt": "#2a7ad2",
                  "fast-underground-belt": "#a02a1a", "express-underground-belt": "#1a5aa0"}
ORE = {"iron-ore": "#5a7a9a", "copper-ore": "#b0683a", "coal": "#2a2a2a", "stone": "#a89060",
       "crude-oil": "#202020", "uranium-ore": "#4ab04a"}
DOT = {"s": "#e03030", "b": "#ff9a00", "p": "#b040e0"}


def svg(d: dict, px: float = 6) -> str:
    x0, y0, x1, y1 = d["box"]
    W, H = (x1 - x0) * px, (y1 - y0) * px
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" '
           f'viewBox="0 0 {W:.0f} {H:.0f}">', f'<rect width="{W:.0f}" height="{H:.0f}" fill="#f4f1ea"/>']
    for w in d["water"]:
        cx, cy = (int(v) for v in w.split(","))
        out.append(f'<rect x="{(cx * 2 - x0) * px:.0f}" y="{(cy * 2 - y0) * px:.0f}" width="{2 * px:.0f}" '
                   f'height="{2 * px:.0f}" fill="#1d3a55"/>')
    for o in d["ore"]:
        cx, cy, name = o.split(",")
        out.append(f'<rect x="{(int(cx) * 2 - x0) * px:.0f}" y="{(int(cy) * 2 - y0) * px:.0f}" width="{2 * px:.0f}" '
                   f'height="{2 * px:.0f}" fill="{ORE.get(name, "#444")}" opacity="0.35"/>')
    big = []
    for t, name, ax, ay, bx, by, code in d["ents"]:
        col = TYPE_OVERRIDES.get(name) or COLOURS.get(t, "#b0b0b0")
        x, y, w, h = (ax - x0) * px, (ay - y0) * px, (bx - ax) * px, (by - ay) * px
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(w, 1):.1f}" height="{max(h, 1):.1f}" fill="{col}" '
                   f'stroke="#000" stroke-width="0.3"><title>{name}</title></rect>')
        if code in DOT and w >= 2 * px - 1:
            big.append(f'<circle cx="{x + w - px * 0.6:.1f}" cy="{y + px * 0.6:.1f}" r="{px * 0.45:.1f}" '
                       f'fill="{DOT[code]}"/>')
    out += big
    out.append("</svg>")
    return "\n".join(out)


async def grab(k: int) -> dict:
    pw = (ROOT / "server" / "instances" / str(k) / "rcon-password").read_text().strip()
    c = Crew(Rcon("127.0.0.1", 27100 + k, pw))
    await c.connect()
    try:
        return json.loads((await c.call("eval", code=lua(), timeout=120))["result"])
    finally:
        await c.close()


async def from_save(save: str, k: int) -> dict:
    from instance import Instance
    inst = Instance(k, save)
    await asyncio.to_thread(inst.start, 300)
    try:
        return await grab(k)
    finally:
        await asyncio.to_thread(inst.stop)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--instance", type=int, help="a running server's slot (read-only)")
    g.add_argument("--save", help="a save to load on a test slot")
    ap.add_argument("--slot", type=int, default=63, help="test slot for --save (60-69)")
    ap.add_argument("--px", type=float, default=6, help="pixels per tile")
    ap.add_argument("out")
    a = ap.parse_args()
    d = asyncio.run(grab(a.instance) if a.instance is not None else from_save(a.save, a.slot))
    Path(a.out).write_text(svg(d, a.px))
    x0, y0, x1, y1 = d["box"]
    print(f"{a.out}: {len(d['ents'])} entities, {x1 - x0}x{y1 - y0} tiles")


if __name__ == "__main__":
    main()
