#!/usr/bin/env bash
# Put the claude-crew mod in your Factorio client's mods folder so you can join a crew server.
# It's added DISABLED, so your singleplayer saves don't pick it up. When you join a server that runs it,
# Factorio's "sync mods with server" turns it on.
#   scripts/install-client-mod.sh            symlink (dev: always matches this checkout)
#   scripts/install-client-mod.sh --zip      copy a versioned zip instead (for sharing / stable installs)
#   FACTORIO_USER_DIR=... to override ~/.factorio
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODS="${FACTORIO_USER_DIR:-$HOME/.factorio}/mods"
VER="$(python3 -c "import json;print(json.load(open('$ROOT/mod/claude-crew/info.json'))['version'])")"
[ -d "$MODS" ] || { echo "no mods folder at $MODS (set FACTORIO_USER_DIR)"; exit 1; }
# Only the game client matters here, not a headless server (ours or anyone's).
if pgrep -ax factorio | grep -v -- "--start-server" | grep -q .; then
  echo "Factorio is running. Quit it first (it rewrites mod-list.json on exit)."; exit 1
fi
rm -rf "$MODS/claude-crew" "$MODS"/claude-crew_*.zip
if [ "${1:-}" = "--zip" ]; then
  (cd "$ROOT/mod" && rm -f /tmp/claude-crew_$VER.zip && cp -r claude-crew "/tmp/claude-crew_$VER" \
    && (cd /tmp && zip -qr "claude-crew_$VER.zip" "claude-crew_$VER") && rm -rf "/tmp/claude-crew_$VER")
  mv "/tmp/claude-crew_$VER.zip" "$MODS/"
  echo "installed $MODS/claude-crew_$VER.zip"
else
  ln -s "$ROOT/mod/claude-crew" "$MODS/claude-crew"
  echo "linked $MODS/claude-crew -> $ROOT/mod/claude-crew"
fi
python3 - "$MODS/mod-list.json" <<'PY'
import json, sys
p = sys.argv[1]
d = json.load(open(p))
for m in d["mods"]:
    if m["name"] == "claude-crew":
        m["enabled"] = False
        break
else:
    d["mods"].append({"name": "claude-crew", "enabled": False})
json.dump(d, open(p, "w"), indent=2)
print("claude-crew is listed as disabled in", p)
PY
