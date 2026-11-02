#!/usr/bin/env python3
"""Send the mods you play with to the server, so the server runs exactly the same files as your game.

Run on your PC after updating mods in the game:

    python3 push-mods.py ubuntu@SERVER-IP              # uses ~/.ssh/slimebox; --key PATH for another key
    python3 push-mods.py ubuntu@SERVER-IP --dry-run    # only show what it would send

It takes each mod that's enabled in your game (the newest zip of it), your mod settings and a matching mod list, and
puts them in ~/incoming/mods-<time>/ on the server. Then, on the server: sudo factorio-ctl install-mods <that folder>
A mod you have as a folder (one in development, like factorio-serf) is zipped as it is now and sent as well.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

MODS = Path.home() / ".factorio" / "mods"
BUILT_IN = {"base", "space-age", "quality", "elevated-rails", "recycler"}
# needed once on your PC when switching from Dectorio to dectorio-fixes; the converted world doesn't need it
SKIP = {"dectorio-wall-rename"}


def version_key(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


def made_for(zp: Path) -> str | None:
    """The Factorio version a mod zip is for (its info.json factorio_version)."""
    try:
        with zipfile.ZipFile(zp) as z:
            info = next(n for n in z.namelist() if n.count("/") == 1 and n.endswith("/info.json"))
            return json.loads(z.read(info)).get("factorio_version")
    except (zipfile.BadZipFile, StopIteration, ValueError):
        return None


def folder_info(d: Path) -> dict | None:
    try:
        return json.loads((d / "info.json").read_text())
    except (OSError, ValueError):
        return None


def zip_folder(d: Path, info: dict, out_dir: Path) -> Path:
    """Zip a folder mod the way the mod portal does: <name>_<version>/... inside <name>_<version>.zip."""
    top = f"{info['name']}_{info['version']}"
    zp = out_dir / f"{top}.zip"
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(d.resolve().rglob("*")):
            rel = f.relative_to(d.resolve())
            if f.is_file() and not any(part.startswith(".") or part == "__pycache__" for part in rel.parts):
                z.write(f, f"{top}/{rel.as_posix()}")
    return zp


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", help="user@server-ip")
    ap.add_argument("--key", default=str(Path.home() / ".ssh" / "slimebox"))
    ap.add_argument("--factorio", default="2.1", help="the game version the server runs (default 2.1)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--anyway", action="store_true", help="send even if some enabled mods have no zip for the server")
    a = ap.parse_args()

    enabled = [m["name"] for m in json.loads((MODS / "mod-list.json").read_text())["mods"] if m.get("enabled")]
    zips: dict[str, list[tuple[str, Path]]] = {}
    for p in MODS.glob("*.zip"):
        m = re.fullmatch(r"(.+)_(\d+\.\d+\.\d+)\.zip", p.name)
        if m and made_for(p) == a.factorio:  # the game itself loads only zips made for its version
            zips.setdefault(m.group(1), []).append((m.group(2), p))

    tmpdir = tempfile.TemporaryDirectory()
    tmp = Path(tmpdir.name)
    send, left_out = [], []
    for name in enabled:
        if name in BUILT_IN:
            continue
        if name in SKIP:
            left_out.append(f"{name} (one-time helper, not needed on the server)")
        elif name in zips:
            send.append(max(zips[name], key=lambda vp: version_key(vp[0]))[1])
        elif (MODS / name).is_dir() and (fi := folder_info(MODS / name)) and fi.get("factorio_version") == a.factorio:
            send.append(zip_folder(MODS / name, fi, tmp))  # players need this exact zip too: it isn't on the portal
        else:
            left_out.append(f"{name} (no zip made for Factorio {a.factorio}: update it in the game first)")

    names = {re.fullmatch(r"(.+)_\d+\.\d+\.\d+\.zip", p.name).group(1) for p in send}
    mod_list = {"mods": [{"name": n, "enabled": True} for n in sorted(BUILT_IN)] +
                        [{"name": n, "enabled": True} for n in sorted(names)]}

    print("sending:")
    for p in sorted(send):
        print("  ", p.name)
    print("   mod-settings.dat, mod-list.json")
    for x in left_out:
        print("left out:", x)
    if a.dry_run:
        return
    if any("no zip made" in x for x in left_out) and not a.anyway:
        sys.exit("\nnot sent: the server would be missing mods your game has on (players couldn't join). Update them "
                 "in the game first, or pass --anyway.")

    dest = f"incoming/mods-{time.strftime('%Y%m%d-%H%M%S')}"
    ssh = ["-i", a.key, "-o", "IdentitiesOnly=yes"]
    ml = tmp / "mod-list.json"
    ml.write_text(json.dumps(mod_list, indent=2))
    subprocess.run(["ssh", *ssh, a.target, f"mkdir -p {dest}"], check=True)
    subprocess.run(["scp", *ssh, "-q", *map(str, send), str(MODS / "mod-settings.dat"), str(ml),
                    f"{a.target}:{dest}/"], check=True)
    tmpdir.cleanup()
    print(f"\nsent to ~/{dest} on the server. Next, on the server:\n  sudo factorio-ctl install-mods ~/{dest}")


if __name__ == "__main__":
    sys.exit(main())
