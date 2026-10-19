# Crew architecture: coordinator, scheduler, actors, controllers

Status: being built (2026-10-18). The previous design ("every worker is a full player driven by its own model") is
still the default; the order-based design below is switched on with `[experiment] orders = true`.

Diagrams and a worked example: https://claude.ai/artifact/9yoBYsF98TRKqPs3nZPFEz (private to the owner).

## Why

In the player design the model is in the loop for every micro-decision (walk here, place this inserter). A model
call takes 5-30 s, most game actions take a few seconds, so characters stood idle 55-95% of the time, and weaker
models (DeepSeek) spent most calls looking instead of building. Prior work agrees on the failure modes: the
Factorio Learning Environment (single agent writing programs) finds weak spatial reasoning, error loops and agents
breaking working builds; MINDcraft finds natural-language handoffs are the multi-agent bottleneck; Project Sid
(PIANO) keeps slow planning from blocking fast acting by running them concurrently.

Core rule: **models decide what change to make and whether it worked; deterministic controllers do the repeated
physical steps.** Adding hands adds execution capacity, not more agents redesigning the same factory.

## Layers

| Layer | Runs on | Decides | Never |
|---|---|---|---|
| Human | game chat | goals, ghosts of their own, cancel/redirect | |
| Coordinator (`crew/foreman.py`) | one strong model (Opus) | acks chat, diagnoses, splits a request into orders with dependencies and checks, owns roadmap + research | places buildings; talks to actors in prose |
| Planner (later) | any model, on demand | one design question -> ghosts + bill of materials | assigns work |
| Scheduler (`crew/orders.py`) | plain code | validates orders (zones, dependencies), dispatches to free actors, runs checks, bounces stuck orders | thinks |
| Actor (`crew/actor.py`) | small fast model, stateless calls | inside one order: sourcing, routes, local repairs, recovery; answers humans | lays out production blocks, changes research, builds outside its zone |
| Controller (`crew/controller.py`) | plain code over mod jobs | the physical loop: lay the plan's ghosts, fetch/craft materials, clear blockers, build, fuel | waits on a model; makes design choices |
| Game | Factorio + `mod/claude-crew` | ground truth; ghosts are the shared, visible plan | |

The controller is Python driving the mod's existing jobs (`move`, `take`, `craft`, `build_ghosts`, `mine`) plus a
few read-only mod queries (`zone`, `sources`, `check`). It runs between model calls and never waits on one.

## Orders

One order = one measurable check. Bigger goals are a request with several orders and dependencies.

```
order #12   request R7 "fix iron" · after #11
  title:      build iron column 3
  plan:       {kind: paste, name: "iron-column-v2", x: 84, y: 36, direction: north}
  zone:       [79, 30, 90, 44]
  notes:      ore from drills at [gps=90,54] (#11); plates onto the x=71 trunk at [gps=71,47]
  done_when:  [{ghosts_cleared}, {working: {name: stone-furnace, min: 12}}]
  owner:      claude-1 (optional hint)      status: active · progress 31/64
```

Plan kinds:
- `paste` a copied build (`copy` tool) or `stamp` a library design: the controller lays the ghosts itself.
- `ghosts`: ghosts are already in the zone (the coordinator pasted them, or a human placed them).
- `connect`: a belt/pipe/pole line from A to B (`item`, `from`, `to`).
- `task`: free text for the actor's model, for small jobs that need judgement ("refuel the furnaces in the zone and
  belt coal to them from [gps=..]"). The actor turns it into ghosts or a few actions, then the controller runs.

Checks (`done_when`, evaluated by the mod's `check` op, never by a model): `ghosts_cleared` (zone),
`working` (entities in zone with status working, optional name, min count), `exists` (name, min count in zone),
`rate` (item made/used per minute, min). An order with no explicit check gets `ghosts_cleared`.

## State

`orders.json` in the crew's state dir (one per world), owned by the orchestrator:
- the coordinator writes requests and orders (the only place dependencies are decided);
- the scheduler advances status (pending -> ready -> active -> done | blocked | failed | cancelled);
- actors write only their own order's progress.

After a restart the scheduler re-reads game state (remaining ghosts, checks), so nothing depends on what a
controller remembers doing.

## Actor model calls

At most three kinds per order, each with a fresh context (the order card + a zone-scoped snapshot, ~3k tokens):
1. start, only for `task` (and `connect` when it needs routing judgement);
2. exception: the controller exhausted its local retries (3) and reports a specific blocker; up to 2 model
   attempts, then the order is blocked and escalated to the coordinator with the blocker;
3. human chat addressed to that actor.

Successful completion needs no model call: the scheduler runs the check and the report is generated.

## Measures

Model calls per entity built, character busy %, first-attempt order success rate, time from dispatch to verified.
The long-run measure stays techs per hour (and per dollar).

## Build log

- 2026-10-18: architecture agreed; order graph + scheduler (`crew/orders.py`), controller (`crew/controller.py`),
  actor (`crew/actor.py`), coordinator order tools (`crew/foreman.py`), mod queries `zone`/`sources`/`check`
  (`mod/claude-crew/scripts/orders.lua`). Controller tested without a model on stage S7: pasted a 34-piece smelting
  column on open ground, fetched belts/inserters from chests, mined stone, crafted furnaces, built it all in 108 s,
  check passed. Actor + scheduler + coordinator not yet tested end to end.
- 2026-10-18: PAUSED for a prior-art review before building further. Several existing projects use the same
  "model picks the task, mod executes" split (AI Player v3, AI Companion / factorio-ai-companion, factorioctl,
  Factorio AI Coworker, FLE). Decide reuse vs build before continuing; see docs/prior-art.md.
- 2026-10-18: prior-art review done (docs/prior-art.md, notes in research_notes/). Verdict: keep the orchestrator
  and order design; port the game layer module by module from MIT projects (factorio-mcp in llm-play-factorio,
  factorio-codex); no fork or rebase.
- 2026-10-18 18:52: first live run (S7 robots save, Opus coordinator + 3 Haiku actors, "@all our iron is the
  bottleneck, go fix it"). Coordinator diagnosed "iron isn't short, it's stuck" in 60 s ($0.30) and wrote 3 orders;
  an actor closed a one-tile belt gap (iron 771 -> 1094/min); the coordinator then found copper was the real limit
  and re-targeted. 14 min: 12 orders, 4 wasted on impossible checks (zone vs base counts). Cost: coordinator $3.18,
  three actors ~$0.12 total. Fixes: checks take "scope": "base"; a check that can never pass (asks for more than
  exist) blocks immediately with the reason instead of retrying.
- 2026-10-18 19:50: order system benchmark (round 17, Opus coordinator + Haiku actors, s3-research-rush): 0 new
  techs in ~45 min, ~$25 per run; stopped. Failure modes: one-moment checks passed while problems recurred, the
  coordinator fixed symptoms (repeated refuel orders), malformed orders (connect with cargo as item), long belt
  routes failing. Judged a regression vs the player crews (+6 techs in 35-59 min).
- 2026-10-18 19:50: SIMPLIFIED. Removed actor.py, orders.py and the scheduler. Kept: the controller, as one worker
  tool `build` (stamp/paste/ghosts/line in one call: tested, a 51-piece red science block in 38 s); board tasks with
  optional game-evaluated done_when that must hold 2 min; foreman hands out outcomes with checks. Known issue: long
  `line` routes still fail near dense base areas even after automatic splitting. Not benchmarked yet.

