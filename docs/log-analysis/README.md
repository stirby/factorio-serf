# What was broken: log analysis, 2026-10-18

Five independent read-only analyses of every benchmark run (32), both live state dirs and live.log (about 27,500
tool calls, 101 transcripts). Details and evidence in:
[opus-crews.md](opus-crews.md) · [order-system.md](order-system.md) · [sonnet-workers.md](sonnet-workers.md) ·
[weak-models-and-deep-run.md](weak-models-and-deep-run.md) · [failure-census.md](failure-census.md)

Target setup going forward: a characterless Opus foreman (the brain) and Sonnet worker characters (the hands).

## The headline findings

1. **Our measurements were wrong in two ways.**
   - Cost: the Agent SDK reports a running total per session and we recorded it as each turn's cost
     (`crew/backends.py`, FIXED 2026-10-18). Inflation hit the characterless foreman hardest (many turns per
     session): foreman+Opus run $34.6 -> $26.1, order run $24.8 -> $4.6, deep run $35.6 -> $10.0. It also tripped the
     $25/h spend cap 11 times during the deep run, pausing workers for nothing.
   - Progress: "any 6 techs" rewards picking cheap techs. Run i26 (30 min, the "fastest") used 647 packs; the others
     used ~1,200. By time-to-600-packs the Opus runs span 25-39 min, and the foreman run (i31b) ties for best.
     The slowest run (i28, 59 min) hit the subscription session limit and played its last 21 min with no model;
     the harness logged that as "turn error (success)".
2. **The order system was a real regression, not an artifact.** By minute 30 it had used 55 and 28 science packs vs
   647-914 for player crews. Its coordinator repaired the fragile test base one symptom at a time; 45% of 100 orders
   were refuel/coal; one-moment checks passed while problems recurred (7 of 11 boiler fixes).
3. **"Sonnet fumbling" was mostly our instructions and tools.** Sonnet workers spent 68% of their time asleep
   between turns, half of it by setting themselves idle mid-task because the prompt, the auto-continue message and
   the status tool all say "go idle when done". With exact specs Sonnet built 13x faster and slightly faster per
   step than Opus. Its real weakness is orientation: inserter direction right 1 of 13 times when it chose, 22 of 22
   when told pickup and drop tiles; our `rotate reverse` turns 90 degrees and `inspect` hides direction.
4. **74% of all failures are cascades.** One failed action in a batch skips the rest (stop-on-fail), though 91% of
   the skipped ones didn't depend on it; agents then re-queue them (~10% of all act calls). An opt-out exists in the
   mod but was never documented.
5. **The critical path is the labs, and nothing shows it.** Every fast run fed the labs in minutes, added a lab row,
   and took the free trigger techs (pumpjack -> oil-processing, crafted steel -> steel-axe). Slow runs built new
   science blocks first, or chased fuel and belt faults.
6. **Agents can't see belts, lanes, inserters or fluids.** Mixed lanes, a head-on belt and crossed pipes each cost
   15-100 min in some run; `inspect` returns no direction, pickup/drop or contents; `diagnose`/`production` ignore
   fluids ("nothing makes water" beside a working pump).

## Ranked fixes for Opus foreman + Sonnet workers

Each item: what, why (evidence), where. A = measurement, B = worker loop and prompt, C = tools, D = foreman, E = test.

| # | Fix | Why | Where |
|---|---|---|---|
| A1 | Per-turn cost = delta of the running total | costs and spend cap were 1.0-7x too high | `crew/backends.py` (**done**) |
| A2 | Detect the subscription session limit; pause, flag and invalidate the run | i28's 21 min with no model counted as valid | `crew/backends.py`, `agent.py` backoff, bench |
| A3 | Score research by science packs consumed (and time to N packs), not "any N techs" | tech choice made 2x noise | `experiments/scenarios`, `digest.py`, `render_page.py` |
| A4 | Reset the who-built-what record for bench runs and drop departed agents' claims | 115 guard failures, 34 naming agents not in the run | mod `storage.built_by`, bench setup |
| B1 | Never go idle with an unfinished task: remove "set idle when done" wording; idle only when the board has nothing for you | 34% of Sonnet time | `crew/prompt.py`, `agent.py` auto-continue, `t_status` |
| B2 | Dependency-aware skipping instead of stop-on-fail (document `stop_on_fail`, default it off for independent ops) | 74% of failures are cascades; ~10% of act calls are re-queues | `mod/.../jobs.lua` finish(), `tools.py` ACTION_DOC |
| B3 | Drop the "crafting queue is idle" nag (25% of results, followed ~3 in 52) or make it rare | noise in every result | `crew/tools.py` _after |
| B4 | Health line counts `build`, and says thinking / backing off / paused / just started | the foreman declared busy workers dead | `crew/agent.py` health_line |
| C1 | Inserters by pickup and drop tiles (`place ... pickup=[x,y] drop=[x,y]`); `rotate reverse` = 180 degrees; `inspect` shows direction, pickup/drop, belt lane contents, fluid contents | Sonnet orientation 1/13; DeepSeek inspect loops | `jobs.lua` place/rotate, `control.lua` inspect, `observe.lua` |
| C2 | `connect` / `build line` report real completion (track the placement jobs), refuse to mix items on a lane, fix leg corners, route poles by reach not tile-by-tile, allow undergrounds | 39 false OKs; pole connect fails 50% | `jobs.lua` connect, `route.lua`, `controller.py` |
| C3 | `place` clears trees and rocks itself; treats "same entity already there" as success | 157 + 20 failures | `jobs.lua` place |
| C4 | `take` failure names where the item is now (the `sources` query exists) | 226 failures, 53% were a teammate emptying the chest | `jobs.lua` take, `orders.lua` sources |
| C5 | Labs in the [base] line: working/starved/idle and which pack is missing; fluids in `diagnose`/`production` and in `rate` checks | the lab bottleneck and fluid sites were invisible | `control.lua` vitals, `late.lua`, `orders.lua` |
| C6 | Smaller bugs: `mine x y name=tree` Lua error; bad op in a batch leaves earlier ops queued; positional mine reports the wrong position; splitter `create_entity` after a passing check | census items 6-9 | `jobs.lua`, `tools.py` |
| D1 | Foreman opening routine: hand-feed labs now, add a lab row, take the free trigger techs, then cheapest techs first | the pattern of every fast run | `crew/foreman.py` prompt |
| D2 | Foreman hands out tasks with precise specs (positions, pickup/drop, a `build` stamp or paste) and a done_when that measures delivery (`rate` kind `used`, labs working held 2 min), never one-moment states | order-system lesson; Sonnet executes exact specs well | `foreman.py`, `tools.py` post_task doc |
| D3 | Wake the foreman when a task completes, fails its check, or a worker goes idle; let it queue the next task per worker | Sonnet workers waited on the foreman | `orchestrator.py` _tell_lead (wake), `foreman.py` |
| D4 | Keep the fix-causes rule (twice -> automate) and one owner per junction | repeated refuel orders; 5 owners on one lab feed | `foreman.py` prompt |
| E1 | Treat the S3 save's boiler deadlock (electric inserter feeding the boilers) as part of the scenario, or fix the save | 3-4 blackouts per run | `experiments/scenarios`, stage save |

## Already fixed today (not yet benchmarked)
- Cost accounting (A1).
- Removed the order/scheduler/actor layer; kept the controller as the worker `build` tool and game-evaluated checks
  on board tasks that must hold 2 minutes.
- Impossible checks fail fast; checks can be base-wide (`scope: base`).
- Trigger techs explain what to do (pumpjack on crude oil).

## What clearly works (keep)
- Stamped/pasted builds through the controller: 11 of 13 built with no model calls, 50-87 entities in 16-37 s.
- Game-evaluated checks: caught 15 premature "done" claims.
- The characterless foreman's diagnoses were accurate; its answers were fast (median ~11 s) and workers never
  waited on them.
- Sonnet with exact specs: fast and honest about what it didn't do.
