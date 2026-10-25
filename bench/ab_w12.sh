#!/bin/bash
# A fifth world for the build-like-a-player comparison, both styles on the same code from the first minute (bus
# tools, research keeper, the oil block): p12 (player) and q12 (classic) on campaign-w12, 14 x 4 h generations.
#   bench/ab_w12.sh            -> p12 on slot 80, q12 on slot 90 (started 2026-10-24 on the code of that evening: supply, plan parts, fluid tracer, fix-first audit)
cd "$(dirname "$0")/.."
log=bench/runs
mkdir -p $log
start() {  # name world slot style
  echo "$(date +%H:%M:%S) start $1 ($4, $(git rev-parse --short HEAD))" >> $log/camp_$1.out
  setsid nohup .venv/bin/python bench/campaign.py --name "$1" --world "$2" --gen-hours 4 --gens 14 \
    --instance "$3" --mode project --style "$4" >> $log/camp_$1.out 2>&1 < /dev/null &
  disown
}
start p12 campaign-w12 80 player
start q12 campaign-w12 90 classic
sleep 2
echo started
