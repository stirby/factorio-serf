#!/bin/bash
# A third world for the build-like-a-player comparison, both styles on the same code from the first minute (bus
# tools, research keeper, the oil block): p10 (player) and q10 (classic) on campaign-w10, 14 x 4 h generations.
#   bench/ab_w10.sh            -> p10 on slot 78, q10 on slot 88
cd "$(dirname "$0")/.."
log=bench/runs
mkdir -p $log
start() {  # name world slot style
  echo "$(date +%H:%M:%S) start $1 ($4, $(git rev-parse --short HEAD))" >> $log/camp_$1.out
  setsid nohup .venv/bin/python bench/campaign.py --name "$1" --world "$2" --gen-hours 4 --gens 14 \
    --instance "$3" --mode project --style "$4" >> $log/camp_$1.out 2>&1 < /dev/null &
  disown
}
start p10 campaign-w10 78 player
start q10 campaign-w10 88 classic
sleep 2
echo started
