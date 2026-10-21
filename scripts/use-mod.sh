#!/bin/bash
# Point your Factorio client's factorio-serf mod at this repo's copy (the Jev prototype's mod: the serf mod plus scan,
# grab, query and the fetch/pole fixes), or back at the frozen serf's copy. Run it while Factorio is closed.
#
#   scripts/use-mod.sh jev      # this repo
#   scripts/use-mod.sh serf     # back to ~/dev/factorio-slave (frozen)
#   scripts/use-mod.sh          # show where it points
set -euo pipefail
MODS="${FACTORIO_USER_DIR:-$HOME/.factorio}/mods"
LINK="$MODS/factorio-serf"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
case "${1:-}" in
  jev) target="$HERE/mod/factorio-serf" ;;
  serf) target="$HOME/dev/factorio-slave/mod/factorio-serf" ;;
  "") readlink "$LINK" || echo "no link at $LINK"; exit 0 ;;
  *) echo "usage: $0 [jev|serf]"; exit 2 ;;
esac
if pgrep -f "steamapps/common/Factorio/bin/x64/[f]actorio" >/dev/null; then
  echo "Factorio is running: close it first (the client loads the mod at start)."; exit 1
fi
if [ -e "$LINK" ] && [ ! -L "$LINK" ]; then
  echo "$LINK is a real folder, not a link: leaving it alone."; exit 1
fi
ln -sfn "$target" "$LINK"
echo "factorio-serf -> $(readlink "$LINK")"
