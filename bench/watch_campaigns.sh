#!/bin/bash
# One line per thing worth knowing from the running campaigns' logs: a milestone that changed, a generation starting,
# ending or crashing, a relaunch, a limit hit. For a Monitor (each stdout line is an event).
#   bench/watch_campaigns.sh [names...]   (default: the ten build-like-a-player campaigns)
cd "$(dirname "$0")/.."
names=("$@")
[ ${#names[@]} -eq 0 ] && names=(p6 q6 p7 q7 p8 p9 p10 q10 p11 q11)
logs=()
for n in "${names[@]}"; do logs+=("bench/runs/camp_$n.out"); done
state=bench/runs/watch_state.txt  # the last milestone reported per campaign, so a new watch doesn't repeat them
touch "$state"
tail -F -n0 "${logs[@]}" 2>/dev/null | awk -v state="$state" '
  BEGIN { while ((getline line < state) > 0) { split(line, kv, " "); last[kv[1]] = kv[2] } close(state) }
  /^==> / { next }
  /milestone [0-9]+/ {
    if (match($0, /\] [a-z0-9]+ g[0-9]+: milestone [0-9]+/)) {
      split(substr($0, RSTART + 2, RLENGTH - 2), w, /[ :]+/)
      name = w[1]; ms = w[4]
      if (last[name] != ms) {
        last[name] = ms; print; fflush()
        out = ""; for (k in last) out = out k " " last[k] "\n"; printf "%s", out > state; close(state)
      }
    }
    next
  }
  /generation [0-9]+ crashed|stopping|Traceback|weekly limit|session limit|usage limit/ { print; fflush() }
'
