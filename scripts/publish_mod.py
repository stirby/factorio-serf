#!/usr/bin/env python3
"""Put the serf mod on the Factorio mod portal (mods.factorio.com), so players' games download it when they join.

    .venv/bin/python scripts/publish_mod.py            # build dist/factorio-serf_<version>.zip and show what it'd do
    .venv/bin/python scripts/publish_mod.py --send     # publish it (the first time: the portal page too)

The zip is built from the committed mod (git archive of HEAD:mod/factorio-serf), so it refuses while the mod folder
has uncommitted changes, and a version that's already on the portal. The key is a factorio.com API key with
"ModPortal: Publish Mods" and "ModPortal: Upload Mods", from SERF_PORTAL_KEY or ~/.config/factorio-serf/portal-key.
It is never printed or put on a command line.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MOD = ROOT / "mod" / "factorio-serf"
API = "https://mods.factorio.com/api"
KEY_FILE = Path.home() / ".config" / "factorio-serf" / "portal-key"

DESCRIPTION = """An AI teammate for Factorio: the **serf** is a character that plays next to you and takes orders \
from chat. It plays by the same rules as a player: it walks, reaches, carries, mines and crafts like one, and builds \
what you ask for ("make gears off this belt", "belt the coal to the boilers", "red science stopped, fix it", \
"research solar", "two more just like it").

**This mod needs the serf app** running on your own computer, with your own Claude subscription (Claude Code logged \
in). The app is free and open source: https://github.com/stirby/factorio-serf

## Setup (each player who wants a serf)
1. Install [Claude Code](https://claude.com/claude-code) and log in with your Claude account.
2. Install the app: `pipx install git+https://github.com/stirby/factorio-serf` (Python 3.10 or newer).
3. Install this mod. In Steam, set Factorio's launch options to `--enable-lua-udp 27200`.
4. Start Factorio, load or join a game with Serf on, run `serf`, and type `/serf add` in chat.

Talk to it with `@serf ...`. Ctrl+Shift+J opens its tasks window.

## Multiplayer
Every player brings their own: each player's app drives only the serfs that player added, on that player's Claude \
login. The server needs only this mod.
"""


def run(*cmd: str, **kw) -> str:
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw).stdout


def portal_releases(name: str) -> list[str] | None:
    """The versions on the portal, or None when the mod isn't there yet."""
    try:
        with urllib.request.urlopen(f"{API}/mods/{name}", timeout=20) as r:
            return [x["version"] for x in json.load(r).get("releases", [])]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def key() -> str:
    k = os.environ.get("SERF_PORTAL_KEY") or (KEY_FILE.read_text().strip() if KEY_FILE.exists() else "")
    if not k:
        sys.exit(f"no portal key: make one at https://factorio.com/create-api-key (ModPortal: Publish Mods and "
                 f"Upload Mods) and put it in {KEY_FILE}")
    return k


def post(url: str, fields: dict[str, str], file: Path | None = None, auth: str | None = None) -> dict:
    """A multipart POST through curl. The key goes in on stdin as curl config, never on the command line."""
    cmd = ["curl", "-sS", "-K", "-", url]
    for k, v in fields.items():
        cmd += ["--form-string", f"{k}={v}"]
    if file:
        cmd += ["-F", f"file=@{file}"]
    cfg = f'header = "Authorization: Bearer {auth}"\n' if auth else ""
    out = subprocess.run(cmd, input=cfg, check=True, capture_output=True, text=True).stdout
    try:
        return json.loads(out)
    except ValueError:
        return {"error": "NotJSON", "message": out[:300]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--send", action="store_true", help="publish (otherwise only build the zip and say what it'd do)")
    a = ap.parse_args()

    info = json.loads((MOD / "info.json").read_text())
    name, version = info["name"], info["version"]
    if run("git", "-C", str(ROOT), "status", "--porcelain", "--", str(MOD)).strip():
        sys.exit(f"{MOD.relative_to(ROOT)} has uncommitted changes: commit them first (the zip is built from git)")
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    zp = dist / f"{name}_{version}.zip"
    run("git", "-C", str(ROOT), "archive", "--format=zip", f"--prefix={name}_{version}/", "-o", str(zp),
        f"HEAD:{MOD.relative_to(ROOT).as_posix()}")
    print(f"built {zp.relative_to(ROOT)} ({zp.stat().st_size // 1024} KB) from {run('git', '-C', str(ROOT), 'rev-parse', '--short', 'HEAD').strip()}")

    releases = portal_releases(name)
    if releases is not None and version in releases:
        sys.exit(f"{name} {version} is already on the portal: bump the version in info.json (and changelog.txt)")
    what = "a new mod page" if releases is None else f"version {version} (the portal has {', '.join(releases[-3:])})"
    if not a.send:
        print(f"would publish {what} at https://mods.factorio.com/mod/{name}; run again with --send")
        return

    k = key()
    if releases is None:
        r = post(f"{API}/v2/mods/init_publish", {"mod": name}, auth=k)
        extra = {"description": DESCRIPTION, "category": "content", "license": "default_mit",
                 "source_url": "https://github.com/stirby/factorio-serf"}
    else:
        r = post(f"{API}/v2/mods/releases/init_upload", {"mod": name}, auth=k)
        extra = {}
    if "upload_url" not in r:
        sys.exit(f"the portal said no: {r.get('error')}: {r.get('message')}")
    done = post(r["upload_url"], extra, file=zp)
    if not done.get("success"):
        sys.exit(f"the upload failed: {done.get('error')}: {done.get('message')}")
    print(f"published {name} {version}: https://mods.factorio.com/mod/{name}")


if __name__ == "__main__":
    main()
