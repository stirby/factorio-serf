#!/bin/bash
# Run bench scenarios detached (they survive this shell and any agent task): bench/run_detached.sh SCENARIO SLOT TAG [...]
# e.g. bench/run_detached.sh b12-bus-yellow 60 r1 b12-bus-yellow 61 r2
cd "$(dirname "$0")/.."
while [ $# -ge 3 ]; do
  setsid nohup .venv/bin/python bench/run.py --scenario "bench/scenarios/$1.json" --instance "$2" \
    > "bench/runs/$1-$3.out" 2>&1 < /dev/null & disown
  echo "started $1 on slot $2 -> bench/runs/$1-$3.out"
  shift 3
  sleep 3
done
