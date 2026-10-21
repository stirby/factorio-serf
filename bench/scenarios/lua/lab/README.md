# Lab scenarios (x-*)

A clean flat stage for production-chain and scale tests, so nothing from a base distracts the serf.

    .venv/bin/python experiments/scenarios/lua/lab/make_stage_lab.py   # server/factorio/saves/stage-lab.zip
    python3 experiments/scenarios/lua/lab/lab-gen.py                   # experiments/scenarios/x-*.json
    .venv/bin/python tests/bench.py --scenario experiments/scenarios/x-red-circuits.json --dry --selftest --instance 51

- `make_stage_lab.lua`: landfill square of 448x448 around spawn, no trees/rocks/ore/water/cliffs/enemies,
  research through advanced circuits (assembler 2, fast inserters, undergrounds, splitters, steel, medium poles).
- `lab-common.lua`: fixture helpers. `feed` makes full input belts (infinity chest + loader; two items side-load one
  per lane, since a loader only outputs its chest's first item). `supply` is a steel chest of building materials
  (no plates or intermediates) that each goal names. `grid` is an always-on power corner with a medium pole.
- Checks only count what machines fed by inserters from belts or machines made; a chest or the serf's hands
  feeding a machine disqualifies it. Selftests build a passing chain on their own feeds beside the fixture.
