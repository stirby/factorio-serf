# factorio-serf

A Factorio 2.1 character, the serf, that plays next to you and takes orders from chat. It plays by the same rules as
a human player: it walks, reaches, carries and crafts like one. It splits the work:
- **Opus** reads every chat line (one quick, low-effort call with the situation: what it's doing, its queue, what
  just failed), plans the jobs asynchronously, and can run a whole goal as a project.
- **Sonnet** answers the small questions code asks: is this order one of the fast paths below, and with what (which
  product, ore, tier, tech), and which fault a player means (`jev/quick_reader.py`).
- **Code** does everything exact in between, including what to do when a step fails.

On 22 October 2026 it launched a rocket from a fresh map after about 19 hours of play, with an Opus player giving
the orders; another serf launched from a midgame base running "beat the game" as its own project.

This is version 2. The first serf (Claude agents acting step by step) is on the `serf-v1` branch and tag
`serf-v1-final`.

**Needs:** Factorio 2.1.24 with Space Age (the last 2.0 version of the mod is 0.3.6, commit 43c75d6) and a Claude
subscription logged in to Claude Code on the same computer. Every player who wants a serf runs the app with their own
login. Nothing else: no API keys. MIT licensed.

See [docs/DESIGN.md](docs/DESIGN.md) for how the parts fit together.

## Play

Every player who wants a serf does this on their own computer:
1. Install [Claude Code](https://claude.com/claude-code) and log in with your own Claude account.
2. Install the app (Python 3.10 or newer and [pipx](https://pipx.pypa.io)):
   `pipx install git+https://github.com/stirby/factorio-serf`
3. In Factorio, install the **Serf** mod from the mod portal (Mods, then Install). In Steam, set Factorio's launch
   options to `--enable-lua-udp 27200`.
4. Start Factorio and load or join a game with Serf on. Run `serf`, then type `/serf add` in the game chat.

The app talks only to your own game, on your own Claude login, and drives only the serfs you added: in multiplayer
each player brings their own. The server needs the mod and nothing else.

From a checkout of this repo (for working on it): link `mod/factorio-serf` into your Factorio mods folder, start
Factorio with `--enable-lua-udp 27200`, then run:

```
.venv/bin/python -m jev.cli play --udp 27200            # single player, or a client in multiplayer
.venv/bin/python -m jev.cli play --rcon 127.0.0.1:27015 --password-file <file>   # a server you run
```

Talk to it with `@serf`, for example:
- `@serf red science stopped at [gps=..]`
- `@serf I need 20 inserters in the chest at [gps=..]`
- `@serf make gears off this belt [gps=..]`
- `@serf belt the coal from [gps=..] to the boiler at [gps=..]`
- `@serf research solar`
- `@serf swap the belts on the line at [gps=..] for red ones`
- `@serf set up an iron mine on the patch at [gps=..] and belt the ore to [gps=..]`
- `@serf two more just like it at [gps=..] and [gps=..]`

None of these need the planner: Sonnet reads the order (a few seconds) and code does it. Anything it isn't sure of
goes to the planner, which also looks over what the actor built by itself when it has nothing else to do. A plan that
doesn't get there sends the next one at max thinking effort. Add `--no-think` to run with Sonnet and code only (also
what happens when Opus hits a usage limit): chat then follows plain rules (a line with `@serf` is an order, "stop"
stops).

It also answers game questions from this game's own recipes and the Factorio wiki: `@serf how do I make plastic?`,
`@serf what's on vulcanus?`. With mod 0.4.1 the answer opens in a window you can scroll and copy from (older mods: a
few chat lines only you see). Ctrl+Shift+J shows what it's doing and what's queued.

With a Todo List that has the serf's interface (the Todo-List mod plus the patch in `bench/live_mods/`, not yet in the
released mod), tasks assigned to the serf become its orders, and `@serf put the oil outpost on the todo list` adds one
(for the serf, for you, or for nobody, as you say).

**Your serf, your settings** (you pay for it, so you choose; nothing else changes):

| | at start | in chat |
|---|---|---|
| the planner's and chat reader's model (opus by default) | `serf --model sonnet` | `@serf use sonnet` |
| how hard the planner thinks | `serf --effort high` | `@serf set effort low`/`medium`/`high`/`max` |
| the quick reads' model (sonnet by default) | `serf --quick-model haiku` | `@serf set quick haiku` |
| show them | | `@serf settings` |

**Feedback:** start a chat line with `!` (`! it took my belts apart`) when something goes wrong. On a server with the
`serf-flags` service (see `hosting/`), that saves the world right then with your note and what every serf was doing,
for whoever works on the serf; your own app also notes it in your serf's log (`~/.local/state/jev/<time>/`).

Opus and Sonnet run through the local Claude Code login (the Agent SDK). Jev, TypeSafe's model, did Sonnet's part
until 2026-11-01; `lab/` holds the question tests from then.

### Playing on a server with friends

Every player who wants a serf brings their own: they install the app as above and run `serf` on their own computer,
with their own Claude login. In the game, `/serf add` brings yours in next to you (named `serf`, or `<you>-serf` if
someone else's already is). Your serf takes orders only from you, and to you it's always `@serf`. Others can see it
work but can't spend your Claude usage (`serf --share` lets anyone who names it give it orders). The mod keeps serfs
from taking over each other, and the server can cap how many each player has (mod setting).

To host a world: [hosting/](hosting/README.md) (setup, tools, backups, the `!` collector, notes for a Claude Code
session that runs the server).

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
