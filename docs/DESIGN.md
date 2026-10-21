# Jev + Opus: design

One character in Factorio, three parts:

| Part | Who | Job |
|---|---|---|
| Hands | the mod (forked from factorio-serf at `serf-v1-final`) | legit player actions: walk, reach, real inventory, crafting, routing belts/poles (`connect`), ghosts, `fetch` (storage then hand-craft). New: `scan`, one compact snapshot of an area (every building, belt neighbours, inserter targets, grids as numbers) in ~90 ms. |
| Code | `jev/world.py`, `jev/steps.py`, `jev/lint.py` | Everything exact: belt lines and why they end, which inserter feeds what, why a machine is stopped, faults with candidate fixes, what a plan needs, plan checking before anything is built. |
| Actor | Jev (`jev/decide.py`, `jev/actor.py`) | The judgment calls, each a narrow typed question over a small state code prepares: is this chat line for me and what is it; which fast playbook fits; which fault is the player talking about; a step failed, so retry, get the item, skip or replan; does the area now look like the goal. ~150 ms, ~$0.00003 each. |
| Thinker | Opus (`jev/thinker.py`) | Never in the action loop. Woken for orders the actor can't do alone and for plans that failed or missed. It reads the area through a few tools and submits one plan. |

## The layer between them: the plan

```json
{"goal": "one line", "say": "chat now", "done_text": "chat when verified",
 "steps": [{"do": "place", "name": "assembling-machine-1", "x": -34.5, "y": 96.5, "recipe": "iron-gear-wheel"},
           {"do": "connect", "item": "transport-belt", "from": [..], "to": [..]},
           {"do": "ghosts", "entities": [...]}, {"do": "power", "x": .., "y": ..}],
 "expect": [{"check": "working", "recipe": "iron-gear-wheel", "count": 1, "near": [x, y], "radius": 4},
            {"check": "has_item", "x": .., "y": .., "item": "iron-gear-wheel", "count": 1}]}
```

- Opus decides *what* and *where*. Code decides *how*: it fetches everything the plan needs in one trip, then
  runs the steps. Jev decides *what now* when something goes wrong.
- `expect` is checked by code. When a plan has none, Jev judges the goal words against the area.
- A failed step goes through Jev first (retry, get the item, skip). Only "replan" or low confidence wakes Opus,
  with a report: steps done, the failure, and the faults code sees there now.
- Before a plan runs, `lint.py` simulates its buildings on the scanned area. Problems go straight back to Opus
  in the same turn, so they cost seconds instead of a minute of building. Examples: overlaps, inserters picking
  from or dropping onto nothing, machines nothing feeds, no power, items that don't exist, a belt continued
  backwards from its end.

## Fast paths (no Opus)

- **fix**: "X stopped at [gps]". Code scans and finds faults: a reversed belt, no fuel, output full, a full
  chest, no power, low boiler fuel. Jev picks the fault that matches the complaint. Code runs its fix and waits
  for the stopped machines to start. If nothing fits, it escalates with what it saw.
- **deliver**: "N items in the chest at [gps]". Code parses the items, fetches them and inserts them.

## State encoding for Jev

Following TypeSafe's guidance and Jev 1.13's known rough edges:
- **No numbers to compare.** Code does the arithmetic and hands Jev words, like "out of fuel", "12 tiles
  north-east", "the belt behind it faces west, away from this line".
- **Small states.** Each question gets only what it needs. A fault choice sees the player's words and the
  faults code found, not the whole area.
- **Options are written in code**, with what each one is for and isn't for. Several independent questions go in
  one request: addressed, kind and playbook for chat.
- Every call is logged (`bench/runs/<id>/jev.jsonl`) with its state, questions and answers. That log is the
  encoding lab's dataset.

## Measuring

`bench/run.py` uses the serf's scenarios, scoring and scripted player, so the serf's nights 1–2 are the baseline.
Each run records:
- success, and minutes to each objective;
- Opus turns, cost and thinking seconds;
- Jev calls, cost and latency;
- character idle share;
- plans per order, step failures and recovery choices.

`bench/batch.py` runs many in parallel.
