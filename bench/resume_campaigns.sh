#!/bin/bash
# Put the ten build-like-a-player campaigns back on the current code, each from its latest save (after a reboot, a
# pause or a code change): scripts/resume_campaign.py closes the running generation at its newest save and starts the
# next one in a fresh, detached process. Then restarts the comparison watcher.
#   bench/resume_campaigns.sh [names...]     (default: all ten)
cd "$(dirname "$0")/.."
declare -A ARGS=(
  [p6]="--world campaign-w6 --gen-hours 4 --gens 14 --instance 75 --mode project --style player"
  [p7]="--world campaign-w7 --gen-hours 4 --gens 14 --instance 85 --mode project --style player"
  [p8]="--world campaign-w8 --gen-hours 4 --gens 14 --instance 76 --mode project --style player"
  [p9]="--world campaign-w9 --gen-hours 4 --gens 14 --instance 86 --mode project --style player"
  [p10]="--world campaign-w10 --gen-hours 4 --gens 14 --instance 78 --mode project --style player"
  [p11]="--world campaign-w11 --gen-hours 4 --gens 14 --instance 79 --mode project --style player"
  [q6]="--world campaign-w6 --gen-hours 4 --gens 14 --instance 77 --mode project --style classic"
  [q7]="--world campaign-w7 --gen-hours 4 --gens 14 --instance 87 --mode project --style classic"
  [q10]="--world campaign-w10 --gen-hours 4 --gens 14 --instance 88 --mode project --style classic"
  [q11]="--world campaign-w11 --gen-hours 4 --gens 14 --instance 89 --mode project --style classic"
  [p12]="--world campaign-w12 --gen-hours 4 --gens 14 --instance 80 --mode project --style player"
  [q12]="--world campaign-w12 --gen-hours 4 --gens 14 --instance 90 --mode project --style classic"
)
names=("$@")
[ ${#names[@]} -eq 0 ] && names=(p6 q6 p7 q7 p8 p10 q10 p11 q11 p12 q12)  # p9: goal met 2026-10-24
for n in "${names[@]}"; do
  echo "$(date +%H:%M:%S) resuming $n"
  .venv/bin/python scripts/resume_campaign.py "$n" ${ARGS[$n]}
  sleep 8
done
if ! pgrep -f "bench/[a]b_watch.py" > /dev/null; then
  setsid nohup .venv/bin/python bench/ab_watch.py p6:75 q6:77 p7:85 q7:87 p8:76 p9:86 p10:78 q10:88 p11:79 q11:89 p12:80 q12:90 \
    --every 30 >> bench/runs/ab_watch.log 2>&1 < /dev/null &
  disown
  echo "watcher started"
fi
echo "$(date +%H:%M:%S) done"
