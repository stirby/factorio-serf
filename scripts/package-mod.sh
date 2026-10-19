#!/usr/bin/env bash
# Build the mod zip that a dedicated server (and every player's client) needs: dist/factorio-serf_<version>.zip.
# Factorio only auto-downloads mods from the mod portal, and this one isn't there, so copy the zip by hand into
# the server's mods/ folder and each player's mods/ folder. Server and clients must have the identical file.
#   scripts/package-mod.sh            build dist/factorio-serf_<version>.zip
#   scripts/package-mod.sh DIR        also copy it into DIR (e.g. a server's mods folder)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VER="$(python3 -c "import json;print(json.load(open('$ROOT/mod/factorio-serf/info.json'))['version'])")"
NAME="factorio-serf_$VER"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$ROOT/dist"
cp -r "$ROOT/mod/factorio-serf" "$TMP/$NAME"
(cd "$TMP" && zip -qrX "$ROOT/dist/$NAME.zip.new" "$NAME")
mv "$ROOT/dist/$NAME.zip.new" "$ROOT/dist/$NAME.zip"
echo "built dist/$NAME.zip ($(sha256sum "$ROOT/dist/$NAME.zip" | cut -c1-12))"
if [ -n "${1:-}" ]; then
  rm -f "$1"/factorio-serf_*.zip
  cp "$ROOT/dist/$NAME.zip" "$1/"
  echo "copied to $1/$NAME.zip"
fi
