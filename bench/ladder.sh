#!/bin/bash
# The task ladder, repeated: one order per rung on a stage save, met when its milestone shows up in the probe.
# Runs the rungs one after another in one server slot, round after round, so each rung gets several tries over
# a night (the code may change between them; each run records its commit).
#
#   bench/ladder.sh <slot> <first-round> <rounds> [rung ...]      e.g. bench/ladder.sh 83 2 4 green oil
# Output: bench/campaigns/<rung>-r<round>/, log lines in $LADDER_LOG (default bench/runs/ladder.log).
cd "$(dirname "$0")/.."
slot=$1; first=$2; rounds=$3; shift 3
rungs=${*:-green oil blue purple}
log=${LADDER_LOG:-bench/runs/ladder.log}

rung() {  # name -> world hours target order
  case $1 in
    green)  echo "stage-s2-electric-midgame|1.5|4|@serf project: automate green science (logistic science packs) with what's here, and keep research going" ;;
    oil)    echo "stage-s3-steel-oil-ready|3|5|@serf project: set up oil processing (pumpjacks, a refinery, petroleum gas) and automate plastic from what's here, and keep research going" ;;
    blue)   echo "stage-s5-oil-plastics|3|6|@serf project: automate blue science (chemical science packs) from what's here, and keep research going" ;;
    purple) echo "stage-s6-blue-science|4|7|@serf project: automate purple science (production science packs) from what's here, and keep research going" ;;
    yellow) echo "stage-s7-bots-online|6|7,8|@serf project: automate purple and yellow science (production and utility science packs) from what's here, and keep research going" ;;
  esac
}

for ((r = first; r < first + rounds; r++)); do
  for name in $rungs; do
    IFS='|' read -r world hours target order <<< "$(rung "$name")"
    camp="$name-r$r"
    [ -d "bench/campaigns/$camp" ] && continue
    echo "$(date +%H:%M:%S) start $camp ($(git rev-parse --short HEAD))" >> "$log"
    .venv/bin/python bench/campaign.py --name "$camp" --world "$world" --gen-hours "$hours" --gens 1 \
      --instance "$slot" --mode project --target "$target" --order "$order" >> "$log" 2>&1
    echo "$(date +%H:%M:%S) end $camp" >> "$log"
  done
done
