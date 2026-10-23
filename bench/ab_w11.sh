#!/bin/bash
# A fourth world for the build-like-a-player comparison, both styles on the same code from the first minute (bus
# tools, research keeper, the oil block): p11 (player) and q11 (classic) on campaign-w11, 14 x 4 h generations.
#   bench/ab_w11.sh            -> p11 on slot 79, q11 on slot 89 (after the order-of-play change, 4e5beb9)
cd "$(dirname "$0")/.."
log=bench/runs
mkdir -p $log
start() {  # name world slot style
  echo "$(date +%H:%M:%S) start $1 ($4, $(git rev-parse --short HEAD))" >> $log/camp_$1.out
  setsid nohup .venv/bin/python bench/campaign.py --name "$1" --world "$2" --gen-hours 4 --gens 14 \
    --instance "$3" --mode project --style "$4" >> $log/camp_$1.out 2>&1 < /dev/null &
  disown
}
start p11 campaign-w11 79 player
start q11 campaign-w11 89 classic
sleep 2
echo started
