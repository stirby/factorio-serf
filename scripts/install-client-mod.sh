#!/usr/bin/env bash
# Put the factorio-serf mod in your Factorio client's mods folder, enabled, so `/serf add` works in your own games
# (and in servers that run the same version). Removes the mod's old name (claude-crew) if it's there.
#   --disabled: list it disabled instead (Factorio's "sync mods with server" turns it on for servers that run it)
#   scripts/install-client-mod.sh            symlink (dev: always matches this checkout)
#   scripts/install-client-mod.sh --zip      copy a versioned zip instead (for sharing / stable installs)
#   FACTORIO_USER_DIR=... to override ~/.factorio
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODS="${FACTORIO_USER_DIR:-$HOME/.factorio}/mods"
VER="$(python3 -c "import json;print(json.load(open('$ROOT/mod/factorio-serf/info.json'))['version'])")"
[ -d "$MODS" ] || { echo "no mods folder at $MODS (set FACTORIO_USER_DIR)"; exit 1; }
# Only the game client matters here, not a headless server (ours or anyone's).
if pgrep -ax factorio | grep -v -- "--start-server" | grep -q .; then
  echo "Factorio is running. Quit it first (it rewrites mod-list.json on exit)."; exit 1
fi
rm -rf "$MODS/claude-crew" "$MODS"/claude-crew_*.zip  # the old name
rm -rf "$MODS/factorio-serf" "$MODS"/factorio-serf_*.zip
if [[ " $* " == *" --zip "* ]]; then
  (cd "$ROOT/mod" && rm -f /tmp/factorio-serf_$VER.zip && cp -r factorio-serf "/tmp/factorio-serf_$VER" \
    && (cd /tmp && zip -qr "factorio-serf_$VER.zip" "factorio-serf_$VER") && rm -rf "/tmp/factorio-serf_$VER")
  mv "/tmp/factorio-serf_$VER.zip" "$MODS/"
  echo "installed $MODS/factorio-serf_$VER.zip"
else
  ln -s "$ROOT/mod/factorio-serf" "$MODS/factorio-serf"
  echo "linked $MODS/factorio-serf -> $ROOT/mod/factorio-serf"
fi
ENABLED=1
for a in "$@"; do [ "$a" = "--disabled" ] && ENABLED=0; done
python3 - "$MODS/mod-list.json" "$ENABLED" <<'PY'
import json, sys
p = sys.argv[1]
d = json.load(open(p))
on = sys.argv[2] == "1"
d["mods"] = [m for m in d["mods"] if m["name"] not in ("claude-crew", "factorio-serf")]  # incl. the old name
d["mods"].append({"name": "factorio-serf", "enabled": on})
json.dump(d, open(p, "w"), indent=2)
print("factorio-serf is listed as", "enabled" if on else "disabled", "in", p)
PY
