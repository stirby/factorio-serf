#!/bin/bash
# Player style with the main bus tools (bus, tap, bus_in) from the first minute: two fresh worlds, the same order
# ("beat the game"), 7 generations of 4 hours, each generation scored unattended (audits.jsonl). Compare with p6/p7,
# which got the bus tools only after 4-6 hours of building without them.
#   bench/bus_player.sh            -> p8 on campaign-w8 (slot 76), p9 on campaign-w9 (slot 86)
cd "$(dirname "$0")/.."
log=bench/runs
mkdir -p $log
start() {  # name world slot style
  echo "$(date +%H:%M:%S) start $1 ($4, $(git rev-parse --short HEAD))" >> $log/camp_$1.out
  setsid nohup .venv/bin/python bench/campaign.py --name "$1" --world "$2" --gen-hours 4 --gens 7 \
    --instance "$3" --mode project --style "$4" >> $log/camp_$1.out 2>&1 < /dev/null &
  disown
}
start p8 campaign-w8 76 player
start p9 campaign-w9 86 player
sleep 2
echo started
