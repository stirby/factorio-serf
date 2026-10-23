#!/bin/bash
# The build-like-a-player comparison: two fresh worlds, each played by the player-style serf and the classic one,
# the same order ("beat the game"), 7 generations of 4 hours, each generation scored unattended (audits.jsonl).
#   bench/ab_player.sh            -> p6 q6 on campaign-w6, p7 q7 on campaign-w7 (slots 75 77 85 87)
cd "$(dirname "$0")/.."
log=bench/runs
mkdir -p $log
start() {  # name world slot style
  echo "$(date +%H:%M:%S) start $1 ($4, $(git rev-parse --short HEAD))" >> $log/camp_$1.out
  setsid nohup .venv/bin/python bench/campaign.py --name "$1" --world "$2" --gen-hours 4 --gens 7 \
    --instance "$3" --mode project --style "$4" >> $log/camp_$1.out 2>&1 < /dev/null &
  disown
}
start p6 campaign-w6 75 player
start q6 campaign-w6 77 classic
start p7 campaign-w7 85 player
start q7 campaign-w7 87 classic
sleep 2
echo started
