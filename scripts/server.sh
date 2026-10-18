#!/usr/bin/env bash
# Dev server: headless Factorio with the mod symlinked in and RCON on localhost.
#   scripts/server.sh start [save]   start in background (default save: crew-test)
#   scripts/server.sh stop | status | log | new <save>
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
F="$ROOT/server/factorio"
BIN="$F/bin/x64/factorio"
PIDF="$ROOT/server/server.pid"
LOG="$ROOT/server/server.log"
: "${FACTORIO_RCON_PORT:=27015}"
: "${FACTORIO_PORT:=34197}"
# Who can join: 127.0.0.1 = this machine only (default). FACTORIO_BIND_HOST=0.0.0.0 lets others on your network
# (or the internet, with the UDP port forwarded) join; set FACTORIO_GAME_PASSWORD too when you do that.
: "${FACTORIO_BIND_HOST:=127.0.0.1}"
PWF="$ROOT/server/rcon-password"
[ -f "$PWF" ] || head -c 18 /dev/urandom | base64 | tr -d '/+=' > "$PWF"
PW="$(cat "$PWF")"

link_mod() {
  mkdir -p "$F/mods"
  ln -sfn "$ROOT/mod/claude-crew" "$F/mods/claude-crew"
  python3 - "$F/mods/mod-list.json" <<'PY'
import json, sys, os
p = sys.argv[1]
d = json.load(open(p)) if os.path.exists(p) else {"mods": [{"name": "base", "enabled": True}]}
names = {m["name"] for m in d["mods"]}
if "claude-crew" not in names:
    d["mods"].append({"name": "claude-crew", "enabled": True})
for m in d["mods"]:
    if m["name"] == "claude-crew": m["enabled"] = True
json.dump(d, open(p, "w"), indent=2)
PY
}

settings() {
  cat > "$ROOT/server/server-settings.json" <<JSON
{
  "name": "Claude Crew dev",
  "description": "local dev server",
  "visibility": { "public": false, "lan": true },
  "require_user_verification": true,
  "max_players": 0,
  "auto_pause": false,
  "auto_pause_when_players_connect": false,
  "only_admins_can_pause_the_game": true,
  "autosave_interval": 5,
  "autosave_slots": 3,
  "autosave_only_on_server": true,
  "non_blocking_saving": false,
  "allow_commands": "admins-only",
  "game_password": "${FACTORIO_GAME_PASSWORD:-}"
}
JSON
  echo '["otterplex"]' > "$ROOT/server/server-adminlist.json"
}

running() { [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; }

case "${1:-status}" in
  new)
    link_mod
    "$BIN" --create "$F/saves/${2:?save name}.zip" ${MAPGEN:+--map-gen-settings "$MAPGEN"} ${MAPGEN_SEED:+--map-gen-seed "$MAPGEN_SEED"}
    ;;
  start)
    running && { echo "already running (pid $(cat "$PIDF"))"; exit 0; }
    link_mod; settings
    SAVE="$F/saves/${2:-crew-test}.zip"
    nohup "$BIN" --start-server "$SAVE" \
      --server-settings "$ROOT/server/server-settings.json" \
      --server-adminlist "$ROOT/server/server-adminlist.json" \
      --bind "$FACTORIO_BIND_HOST:$FACTORIO_PORT" \
      --rcon-bind "127.0.0.1:$FACTORIO_RCON_PORT" --rcon-password "$PW" \
      > "$LOG" 2>&1 &
    echo $! > "$PIDF"
    for _ in $(seq 60); do
      grep -q "changing state from(CreatingGame) to(InGame)" "$LOG" && { echo "up (pid $(cat "$PIDF")), rcon 127.0.0.1:$FACTORIO_RCON_PORT"; exit 0; }
      running || { echo "server exited:"; tail -20 "$LOG"; exit 1; }
      sleep 0.5
    done
    echo "timed out waiting for server"; tail -20 "$LOG"; exit 1
    ;;
  stop)
    running && kill -INT "$(cat "$PIDF")" && for _ in $(seq 30); do running || break; sleep 0.5; done
    rm -f "$PIDF"; echo stopped
    ;;
  restart) "$0" stop; "$0" start "${2:-crew-test}" ;;
  status) running && echo "running (pid $(cat "$PIDF"))" || echo "stopped" ;;
  host)
    # Host a COPY of a save (yours stays untouched): scripts/server.sh host ~/.factorio/saves/our-world.zip
    SRC="${2:?path to a save .zip}"
    NAME="hosted-$(basename "$SRC" .zip | tr ' ' '-')-$(date +%m%d-%H%M)"
    cp "$SRC" "$F/saves/$NAME.zip"
    echo "hosting a copy: $F/saves/$NAME.zip"
    "$0" start "$NAME"
    ;;
  log) tail -n "${2:-40}" "$LOG" ;;
  password) echo "$PW" ;;
  *) echo "usage: $0 start|stop|restart|status|log|new|password|host <save.zip>"; exit 2 ;;
esac
