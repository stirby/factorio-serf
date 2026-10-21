# factorio-jev

A Factorio 2.0 character that plays next to you and takes orders from chat. It splits the work:
- **Jev** (TypeSafe's decision model) makes the quick judgment calls.
- **Opus** plans asynchronously.
- **Code** does everything exact in between.

This is the successor to [factorio-serf](https://github.com/stirby/factorio-serf), which is frozen at `serf-v1-final` and serves as the baseline.

See [docs/DESIGN.md](docs/DESIGN.md) for how the parts fit together.

## Play

1. Start Factorio with `--enable-lua-udp 27200`.
2. Load a game with this repo's `mod/factorio-serf` installed. It's the serf mod plus new actions, so link this copy rather than the old one.
3. Run:

```
.venv/bin/python -m jev.cli play --udp 27200            # single player, or a client in multiplayer
.venv/bin/python -m jev.cli play --rcon 127.0.0.1:27015 --password-file <file>   # a server you run
```

Talk to it with `@serf`, for example:
- `@serf red science stopped at [gps=..]`
- `@serf I need 20 inserters in the chest at [gps=..]`
- `@serf automate gears off this belt`

Add `--no-think` to run with Jev and code only.

The Jev key is read from `~/dev/jev.env`. Opus runs through the local Claude Code login (the Agent SDK).

## Test

```
.venv/bin/python bench/run.py --scenario bench/scenarios/t-starved.json --instance 53     # one scored run
.venv/bin/python bench/batch.py --tag mytag -P 5 t-deliver t-starved tbm-3                # many, in parallel
.venv/bin/python bench/loop.py --suite bench/suites/core.json --tag loop1 -P 5 --budget 40 --until 16:00
.venv/bin/python bench/report.py --tags loop1                                               # vs the serf
.venv/bin/python tests/timeline.py bench/runs/<run_id>                                      # what happened
```

The scenarios, scoring and scripted player are the same as factorio-serf's. Biters are always off in test worlds.

## Encoding lab

Each lab replays Jev's decisions on hand-labelled cases, without starting the game:

```
.venv/bin/python lab/eval_chat.py         # chat sorting (CHAT_SET=chat_holdout.jsonl for the check set)
.venv/bin/python lab/eval_recovery.py     # what to do after a failed step
.venv/bin/python lab/eval_changes.py      # does a mid-job message change the plan
```

## Layout

| Path | What |
|---|---|
| `jev/actor.py` | the character's loops: chat, orders, plans, recovery, verifying, fast playbooks |
| `jev/decide.py` | every Jev question (state encodings and options) |
| `jev/thinker.py` | Opus: tools, prompt, plan submission |
| `jev/world.py` | scan → belt lines, feeders, machine states, faults with fixes, summaries |
| `jev/steps.py` | plan steps → mod actions (fetching, power, routing, building ghosts) |
| `jev/lint.py` | the plan checker |
| `jev/router.py` | multi-belt router (undergrounds, tiers, kits) |
| `jev/blueprints.py`, `jev/blueprints/` | built-in, game-tested blocks |
| `jev/library.py` | the agent layer: lessons and designs Opus writes |
| `mod/factorio-serf/` | the mod (forked), plus `scan`, `grab`, `query`, ingredient fetching and pole wiring |
| `bench/`, `lab/`, `tests/` | testing |
