#!/usr/bin/env python3
"""A top-down timelapse of a campaign: every half-hourly save drawn in one fixed frame (the final base's bounds),
captioned with the hours of play, stitched into an MP4. Loads copies of the saves on a test slot; read-only.

    .venv/bin/python scripts/timelapse.py c1 --final rocket-launched-c1-fresh-map --slot 69 --out media/c1 --px 8
"""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import map_svg  # noqa: E402
from instance import Instance  # noqa: E402
from jev.rcon import Crew, Rcon  # noqa: E402


async def dump(save: str, k: int, area=None) -> dict:
    inst = Instance(k, save)
    await asyncio.to_thread(inst.start, 300)
    try:
        c = Crew(Rcon(inst.host, inst.rcon_port, inst.password))
        await c.connect()
        try:
            d = json.loads((await c.call("eval", code=map_svg.lua(area), timeout=120))["result"])
            tick = json.loads((await c.call("eval", code="return helpers.table_to_json{t = game.tick}",
                                            timeout=30))["result"])["t"]
            d["tick"] = tick
            return d
        finally:
            await c.close()
    finally:
        await asyncio.to_thread(inst.stop)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("campaign")
    ap.add_argument("--final", help="a save of the finished base, for the frame's bounds (default: the last save)")
    ap.add_argument("--slot", type=int, default=69)
    ap.add_argument("--out", required=True)
    ap.add_argument("--px", type=float, default=4)
    ap.add_argument("--fps", type=float, default=3)
    a = ap.parse_args()
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    saves = sorted((ROOT / "bench" / "campaigns" / a.campaign / "saves").glob("*.zip"), key=lambda p: p.stat().st_mtime)
    final = a.final or str(saves[-1])
    box = asyncio.run(dump(final, a.slot))["box"]
    area = ((box[0], box[1]), (box[2], box[3]))
    frames = []
    for i, sv in enumerate(saves + ([Path(final)] if a.final else [])):
        d = asyncio.run(dump(str(sv), a.slot, area))
        d["box"] = box  # one frame for all
        svg = out / f"{i:03d}.svg"
        svg.write_text(map_svg.svg(d, a.px))
        png = out / f"{i:03d}.png"
        hours = d["tick"] / 216000
        label = f"{a.campaign}  {hours:4.1f} h of play  ({len(d['ents'])} buildings)"
        k = a.px / 4  # caption scales with the frame
        subprocess.run(["convert", "-density", "72", str(svg), "-gravity", "NorthWest", "-pointsize", str(int(28 * k)),
                        "-fill", "#1d2326", "-annotate", f"+{int(16 * k)}+{int(12 * k)}", label, str(png)], check=True)
        frames.append(png)
        print(f"{i + 1}/{len(saves)} {sv.name}: {hours:.1f} h, {len(d['ents'])} buildings", flush=True)
    mp4 = out / f"{a.campaign}-timelapse.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(a.fps), "-i", str(out / "%03d.png"),
                    "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
                    str(mp4)], check=True)
    print(mp4)


if __name__ == "__main__":
    main()
