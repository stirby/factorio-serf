# The crew design (paused 2026-10-18)

From 2026-10-18 the project focuses on **one good player**: a single model-driven character in the world (see
`docs/architecture.md`). This page records the multi-agent crew we built before that, what it did well and badly,
and how to bring it back. The code is still in the repo and still works; it's just not where testing goes.

## What it was

| Part | File | Did |
|---|---|---|
| Foreman | `crew/foreman.py` | Opus, no character. Decided what the crew works on, posted board tasks with precise specs and `done_when` checks, answered workers' `ask_foreman` questions without making them wait (batched every ~12 s), took crew-wide chat (`@all fix our iron`), ran a review every 5 min with a health line per worker. |
| Workers | `crew/agent.py` | Sonnet characters. Owned board tasks; kept working while they owned one; `report` and `ask_foreman` to the foreman. |
| Board | `crew/board.py` | Shared JSON tasks: owner, notes, `done_when` + zone, status open/claimed/verifying/done. |
| Checks | `orchestrator._task_checks`, mod `scripts/orders.lua` | The game evaluated `done_when` every 20 s (`ghosts_cleared`, `working`, `exists`, `rate` produced/used, zone or `scope: base`); a task closed only when the check held 2 min; impossible checks failed fast. |
| Routing | `crew/orchestrator.py` | `@all`/`@crew` to the foreman, `@name` to one worker, idle workers and finished/failed tasks woke the foreman. |

Before that (removed, see the build log in `docs/architecture.md`): a player-foreman crew, an architect advisor,
and an order graph + scheduler + Haiku actors. The order system regressed to 0 techs and was deleted.

## Results

| Run | Setup | Outcome |
|---|---|---|
| Player crews, s3 research rush | 3-5 Sonnet/Opus characters, one acting as foreman | +6 techs in 35-59 min; 600 packs in 25-39 min |
| i31b | Opus foreman (no character) + Sonnet workers | tied best on time to 600 packs; $26 (after the cost fix) |
| Order system, round 17 | Opus coordinator + Haiku actors | 0 techs in ~45 min, ~$25: stopped |
| Live, feldspar copy (42 h world, biters on), 3 h 15 min | Opus foreman + 4 Sonnet workers | 3 new techs + 2 levels of infinite techs; labs 30 -> 41; 5 tasks passed held checks (iron 7,000/min, blue 120/min, green back to 125/min, packs to labs, a north iron corridor); 5 deaths to biters in the first 30 min; characters idle 55-65% of game time |

Verdict from the live run (the user's): "they're doing nothing productive" for the cost. Most of the wall clock was
models thinking; adding a brain on top added thinking without adding hands.

## What worked (reuse these)

- **`build` through the controller** (`crew/late_tools.py`, `crew/controller.py`): one call lays a stamp/paste as
  ghosts, fetches items from chests and machine outputs, crafts, mines raw resources, clears blockers and builds.
  11 of 13 builds needed no model calls; 50-87 entities in 16-37 s.
- **Game-evaluated checks that must hold 2 minutes**: caught 15 premature "done" claims in benchmarks and 3 in
  the first 30 live minutes. Measuring delivery (`rate` kind `used`), never a one-moment state.
- **Exact specs**: Sonnet with positions and inserter pickup/drop tiles built 13x faster than when it chose.
- **Late-game tools**: `diagnose` (bottleneck by machine status, with distribution hints), copy/paste of existing
  builds, upgrade/deconstruct planners, logistic `network`, `configure`, `equip`, research reorder.
- **Not stopping a batch on one failure** (`stop_on_fail` opt-in): 74% of failures had been cascades.
- The foreman's diagnoses were accurate and fast (median ~11 s); workers never waited on it.

## What didn't

- Coordination costs thinking time and money without adding hands: the brain never touches the world.
- Workers went idle mid-task when the prompt said "go idle when done" (68% of Sonnet time asleep before the fix).
- Symptom-fixing (repeated refuel orders), one-moment checks, and routing failures in the order system.
- Biters: agents walked into nests while scouting or hauling. All tests now run with biters off.
- Cost accounting was wrong for a while (SDK reports a running total per session); fixed in `crew/backends.py`.

Details: `docs/log-analysis/` (ranked fixes, per-run evidence).

## Bringing it back

Config only. In `crew.toml` add a `[foreman]` block and more `[[agent]]` blocks:

```toml
[foreman]
name = "foreman"
model = "claude-opus-5-5"
effort = "medium"

[[agent]]
name = "claude-1"
focus = "production"

[[agent]]
name = "claude-2"
focus = "resources"
```

Without `[foreman]` each agent plays on its own (its tools have no `ask_foreman`/`report`). Tests:
`tests/test_foreman.py`; benchmark variants `foreman-opus` and `opus-lead-sonnet` in `experiments/variants.json`.
