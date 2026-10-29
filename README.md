# factorio-serf

A Factorio 2.0 character, the serf, that plays next to you and takes orders from chat. It plays by the same rules as
a human player: it walks, reaches, carries and crafts like one. It splits the work:
- **Opus** reads every chat line (one quick, low-effort call with the situation: what it's doing, its queue, what
  just failed), plans the jobs asynchronously, and can run a whole goal as a project.
- **Jev** (TypeSafe's decision model) reads orders for the fast paths below and picks which fault a player means. It
  also guesses how hard each order is; that guess is only logged for now (`bench/effort_shadow.py`).
- **Code** does everything exact in between, including what to do when a step fails.

On 22 October 2026 it launched a rocket from a fresh map after about 19 hours of play, with an Opus player giving
the orders; another serf launched from a midgame base running "beat the game" as its own project.

This is version 2. The first serf (Claude agents acting step by step) is on the `serf-v1` branch and tag
`serf-v1-final`.

**Needs:** Factorio 2.0.77 with Space Age, a TypeSafe API key for Jev (in `TYPESAFE_API_KEY` or `~/dev/jev.env`),
and Claude through the Claude Agent SDK (a Claude subscription logged in to Claude Code). MIT licensed.

See [docs/DESIGN.md](docs/DESIGN.md) for how the parts fit together.

## Play

1. Start Factorio with `--enable-lua-udp 27200`.
2. Load a game with this repo's `mod/factorio-serf` installed. Link this copy into your Factorio mods folder.
3. Run:

```
.venv/bin/python -m jev.cli play --udp 27200            # single player, or a client in multiplayer
.venv/bin/python -m jev.cli play --rcon 127.0.0.1:27015 --password-file <file>   # a server you run
.venv/bin/python -m jev.cli play --udp 27200 --reader sonnet   # Claude Sonnet reads orders instead of Jev
```

`--reader sonnet` puts Claude Sonnet in Jev's place: the same questions, through the Claude Agent SDK on the
subscription. It takes about 6 s and $0.01 a decision, against Jev's 0.2 s and $0.00004. The bench takes the same flag,
and `lab/eval_hard.py` compares the two readers on held-out player messages.

Talk to it with `@serf`, for example:
- `@serf red science stopped at [gps=..]`
- `@serf I need 20 inserters in the chest at [gps=..]`
- `@serf make gears off this belt [gps=..]`
- `@serf belt the coal from [gps=..] to the boiler at [gps=..]`
- `@serf research solar`
- `@serf swap the belts on the line at [gps=..] for red ones`
- `@serf set up an iron mine on the patch at [gps=..] and belt the ore to [gps=..]`
- `@serf two more just like it at [gps=..] and [gps=..]`

None of these need the planner: Jev reads the order and code does it. Anything Jev isn't sure of goes to the planner,
which also looks over what the actor built by itself when it has nothing else to do. A plan that doesn't get there
sends the next one at max thinking effort.
Add `--no-think` to run with Jev and code only (also what happens when Opus hits a usage limit): chat then follows
plain rules (a line with `@serf` is an order, "stop" stops).

The Jev key is read from `~/dev/jev.env`. Opus runs through the local Claude Code login (the Agent SDK).

### Projects

A goal bigger than one plan runs as a project: `@serf project: automate green science`, `@serf beat the game`, or
any big order the planner decides needs several builds in a row. An Opus manager inside the serf then gives it one
order at a time, checks progress between them (research, machines by recipe, what's been made), keeps a journal,
and says when it's done or stuck. Your own orders go first; `@serf stop` ends the project, and its notes are kept, so
`@serf carry on with the project: ...` picks it up. The manager can save order sequences that worked as playbooks
(`library/playbooks.json`) for later projects.

## Test

```
.venv/bin/python bench/run.py --scenario bench/scenarios/t-starved.json --instance 53     # one scored run
.venv/bin/python bench/batch.py --tag mytag -P 5 t-deliver t-starved tbm-3                # many, in parallel
.venv/bin/python bench/loop.py --suite bench/suites/core.json --tag loop1 -P 5 --budget 40 --until 16:00
.venv/bin/python bench/report.py --tags loop1                                               # vs the serf
.venv/bin/python tests/timeline.py bench/runs/<run_id>                                      # what happened
```

The scenarios, scoring and scripted player are the same as factorio-serf's. Biters are always off in test worlds.

How far it gets into the game:

```
.venv/bin/python scripts/new_world.py campaign-w3 3003                  # a fresh peaceful Space Age world
.venv/bin/python bench/campaign.py --name p1 --world campaign-w3 --mode project --gen-hours 4 --gens 12 --instance 85
.venv/bin/python bench/campaign.py --name c1 --world campaign-w3 --mode strategist ...   # an outside Opus player instead
bench/ladder.sh 83 1 3 green oil blue purple                             # one order per rung, 3 rounds
.venv/bin/python bench/campaign_report.py                                # everything so far, as JSON
```

A campaign plays a world in generations (4 h each by default), each from the last one's save, or a new world when it
got nowhere; progress is probed every few minutes against a 0-10 milestone ladder (`jev/progress.py`: smelting,
power, red, green, oil, blue, purple, yellow, silo, rocket). Files go to `bench/campaigns/<name>/`.

## Encoding lab

Each lab replays Jev's decisions on hand-labelled cases, without starting the game:

```
.venv/bin/python lab/eval_chat.py         # chat sorting (CHAT_SET=chat_holdout.jsonl for the check set)
.venv/bin/python lab/eval_recovery.py     # what to do after a failed step
.venv/bin/python lab/eval_changes.py      # does a mid-job message change the plan
.venv/bin/python lab/eval_quick.py        # quick builds: product, count, output, refusals (--holdout for the check set)
.venv/bin/python lab/eval_belt.py         # is it a belt job
.venv/bin/python lab/eval_research.py     # which research
```

`bench/digest.py <tag>` summarises a loop: time per order, where the time went, Jev's low-confidence calls to label,
and the lessons Opus wrote.

## Layout

| Path | What |
|---|---|
| `jev/actor.py` | the character's loops: chat, orders, plans, recovery, verifying, fast playbooks |
| `jev/decide.py` | the core Jev questions (state encodings and options) |
| `jev/fastpaths.py` | the actor's own paths for common orders (tried before Opus), and Opus's background reviews of them |
| `jev/quickbuild.py`, `quickbelt.py`, `quickmine.py`, `quickcopy.py` | what Jev is asked and how code lays it out for each path |
| `jev/craft.py` | how many of a building can be had from storage, machine outputs and crafting |
| `jev/thinker.py` | Opus: tools, prompt, plan submission |
| `jev/world.py` | scan → belt lines, feeders, machine states, faults with fixes, summaries |
| `jev/steps.py` | plan steps → mod actions (fetching, power, routing, building ghosts) |
| `jev/lint.py` | the plan checker |
| `jev/router.py` | multi-belt router (undergrounds, tiers, kits) |
| `jev/blueprints.py`, `jev/blueprints/` | built-in, game-tested blocks |
| `jev/library.py` | the agent layer: lessons and designs Opus writes, playbooks the project manager writes |
| `jev/project.py` | projects: the Opus manager that turns a big goal into orders |
| `jev/progress.py` | how far into the game a world is (probe, milestones, rates) |
| `mod/factorio-serf/` | the mod (forked), plus `scan`, `grab`, `query`, ingredient fetching and pole wiring |
| `bench/`, `lab/`, `tests/` | testing |
