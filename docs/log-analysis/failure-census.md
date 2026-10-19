# Failure census: tool and game-action failures across all crew logs

Scope: 32 benchmark runs (every `experiments/runs/*` with transcripts, excluding `*-dry`, `dry-*`, `validate-*`) plus the two
live state dirs (`~/.local/state/claude-crew`, `~/.local/state/claude-crew-deep`). That is 101 transcripts with job
results, 27,532 tool calls, 7,194 `act` batches, 31,690 queued actions, 30,899 job outcomes and about 79 active
worker agent-hours. Code references are to HEAD `bb38fdc`.

## Summary

1,340 actions failed on their own (root failures), and 98 more tool calls failed. But 3,913 further actions failed only
because an earlier action in the same queue had failed ("skipped: earlier job N failed"). Those skips make up 74% of
all FAILED lines, and 91% of the skipped actions did not depend on the action that failed. Stop-on-fail is the largest
single source of waste: it cost about 704 extra `act` calls to re-queue work, and 1,378 intended actions were simply
dropped. Five signatures account for half of all root failures:

- `take`: nothing to take (226)
- `place`: blocked by a building (160)
- `place`: blocked by a tree (157)
- the teammate-ownership guard on `mine` (115)
- `connect` routing failures (101)

Most of these are tool-design problems or harness bugs rather than model mistakes, and none is fixed at HEAD. The new
`build` tool covers a few of them partly, but it isn't benchmarked yet. Two outputs actively mislead the agents:

- `connect` reports OK while its belt placements fail out of the agents' sight. In one case an agent marked a task
  done on a belt that was missing up to 22 tiles.
- `build_ghosts` says "none left here" while ghosts it skipped are still there (at least 5% of those results).

Opus fails least per action (38 per 1,000 jobs). The others are higher: Sonnet 51, DeepSeek-pro 56, Haiku 62,
DeepSeek-flash 69. Opus queues larger batches, though, so each of its failures skips more (3.3 actions per root failure,
against 1.5 to 2.5 for the other models).

## Method

The scripts (read-only) are in `/tmp/claude-1000/-home-stephen-ops/dca040bd-512a-4ed8-b7ff-9ffd9741ccde/scratchpad/`:

- `census.py` parses every transcript. It reads `#id op: OK|FAILED msg {data}` job lines from `act`/`wait` results
  (including `[earlier jobs]`) and tool-level failures (`game error`, `bad arguments`, `lost connection`, `unknown tool`,
  `FAILED`/`stamp failed` from non-act tools). It maps job ids back to the `act` arguments: ids in a batch are
  consecutive, so the base id comes from a vote over the reported ops. 6,932 of 7,194 batches mapped.
- `analyze.py` and `table.py` produce the signature families, recovery times, retries and cascade statistics.
- `deep.py` and `deep2.py`, plus inline probes, test specific hypotheses (ownership, stale observations, routing
  distance and so on).

How the model was attributed:

- Bench runs use `crew.toml`.
- For the live runs, the models come from the `(backend, model)` lines in `logs/live.log`. `claude-crew` was Opus, except
  for claude-2 to claude-5 on Sonnet from 00:45 to 01:04. Its transcripts before 00:27 are assumed to be Opus. In
  `claude-crew-deep`, claude-1 and claude-3 were DeepSeek-pro, claude-2 and claude-4 DeepSeek-flash, and the foreman Opus.

Definitions:

- **Recovery** is the time from a failure to the same agent's next successful job of the same op.
- **Est. time wasted** is given as a range:
  - The low end is the count times the median recovery.
  - The high end is the sum of the recovery times, each capped at 10 minutes. It overlaps with other work, so it is an
    upper bound.
- **Cascade** is the number of skipped actions attributed to that root failure.
- **Re-issued** means the identical action (same op and arguments) was queued again within 10 minutes.

There were no "timed out", "lost connection" or "unknown tool" results in any transcript. `unknown tool` is returned
before logging (`crew/tools.py:609-611`), so it could not appear anyway.

## Top failure signatures

Share is out of 1,438 root plus tool failures. Models are listed as o=opus, p=ds-pro, f=ds-flash, h=haiku, s=sonnet.

| # | Signature | Count | Share | Models (o/p/f/h/s) | Median recovery | Est. wasted (agent-min) | Cascade (skipped) | Cause class | Fixed at HEAD? |
|---|---|---|---|---|---|---|---|---|---|
| 1 | take: nothing to take | 226 | 15.7% | 169/22/27/2/6 | 21 s | 80–471 | 589 | tool design (+ model) | No (`build` sources chests itself) |
| 2 | place: blocked by building | 160 | 11.1% | 73/29/46/10/2 | 18 s | 49–267 | 527 | model mistake (+ non-idempotent place) | No |
| 3 | place: blocked by tree/stump | 157 | 10.9% | 139/5/4/8/1 | 9 s | 24–69 | 699 | tool design (missing auto-clear) | No for `place`; `build` clears only marked trees |
| 4 | mine: teammate guard (both message versions) | 115 | 8.0% | 88/11/11/5/0 | 11 s (v2), 83 s (v1) | 49–147 | 815 | harness bug (inherited ownership) + tool design | Message reworded in `ea1ee71`; guard and leak not fixed |
| 5 | connect: route needs N but you have M | 78 | 5.4% | 46/10/8/10/4 | 31 s | 41–222 | 24 | model + tool design (all-or-nothing) | Partly (`build kind=line` sources/crafts items) |
| 6 | move: no path | 78 | 5.4% | 40/22/13/1/2 | 21 s | 27–39 | 103 | tool design (no goal snapping) + model | No |
| 7 | connect: no route, A* node limit | 58 | 4.0% | 36/10/11/1/0 | 39 s | 38–173 | 44 | tool design (missing capability) | Partly (`build` splits legs over 30 tiles) |
| 8 | find: "Unknown entity name" game error | 55 | 3.8% | 22/17/5/9/2 | n/a | small | 0 | tool design | No |
| 9 | mine (x,y): nothing minable | 51 | 3.5% | 39/7/1/4/0 | 40 s | 34–97 | 165 | model + misleading message | No |
| 10 | move: stuck while walking | 45 | 3.1% | 35/6/4/0/0 | 23 s | 17–57 | 100 | harness (movement) | No |
| 11 | place: create_entity failed (after can_place passed) | 39 | 2.7% | 26/7/3/3/0 | 15 s | 10–29 | 118 | harness bug (fast-replace) | No |
| 12 | place: item not in inventory | 35 | 2.4% | 24/3/8/0/0 | 21 s | 12–41 | 76 | model | n/a |
| 13 | place: invalid spot, nothing listed | 35 | 2.4% | 11/11/7/6/0 | 28 s | 17–74 | 83 | tool design (no snapping, vague message) | No |
| 14 | connect: would feed a teammate's belt | 34 | 2.4% | 19/6/6/3/0 | 5 s | 3–40 | 25 | tool design (by design; inherits the ownership leak) | No |
| 15 | connect: no route (blocked) | 33 | 2.3% | 26/2/3/2/0 | 63 s | 34–103 | 10 | tool design (24 of 33 are poles) | No |
| 16 | craft: missing ingredients | 29 | 2.0% | 20/1/8/0/0 | 31 s | 15–68 | 62 | model (message is good) | n/a |
| 17 | insert: won't accept (11 of the 34 are fuel-slot cases) | 34 | 2.4% | 26/0/4/4/0 | 16–19 s | 10–48 | 138 | model + vague message | No |
| 18 | insert: item not in inventory | 15 | 1.0% | 10/2/1/2/0 | 106 s | 26–42 | 6 | model | n/a |
| 19 | act: game error "unknown action op" | 10 | 0.7% | 0/2/8/0/0 | n/a | small | 0 | model + harness bug (partial enqueue) | No |
| 20 | mine: Lua error "Unknown entity name: tree" | 9 | 0.6% | 4/0/2/2/1 | 11 s | 2 | 35 | harness bug | No |

Smaller items: `place` blocked by a ghost (7), a character (6), a rock (5) or crash-site wreckage (3); research
"already researched" or trigger techs queued in labs (about 25 across the action and the foreman tool); connect over
250 tiles (6); connect start or end tile blocked (10).

Per model:

| Model | Jobs | Root failures | Per 1,000 jobs | Skipped | Skipped per root | Mean batch size |
|---|---|---|---|---|---|---|
| opus | 23,780 | 903 | 38 | 2,987 | 3.3 | 4.8 |
| ds-pro | 2,985 | 166 | 56 | 357 | 2.2 | 3.5 |
| ds-flash | 2,648 | 183 | 69 | 417 | 2.3 | 3.4 |
| haiku | 1,076 | 67 | 62 | 100 | 1.5 | 3.3 |
| sonnet | 410 | 21 | 51 | 52 | 2.5 | 5.8 |

The models fail on different things:

- DeepSeek-flash hits "blocked by building" at 17.4 per 1,000 jobs, against Opus's 3.1.
- DeepSeek-pro hits "no path" at 7.4 per 1,000, against Opus's 1.7.
- Opus leads on trees (5.8 per 1,000). It builds more by hand on forested bench maps.

Across the top 30 families, the waste comes to between 8.8 and 35 agent-hours, against about 79 active worker
agent-hours.

## Task 2: causes, by signature

**1. take: "nothing to take from iron-chest (iron-plate)"** (226 failures, 589 skipped)

Example: `take x=-20 y=-23.5 item=iron-plate count=200` gives `nothing to take from iron-chest (iron-plate)`.

The handler (`mod/claude-crew/scripts/jobs.lua:470-503`) resolves the target with `entity_at` (`jobs.lua:41-68`) and fails
when nothing moved (`jobs.lua:499`). I checked each failure against the agent's last `look`/`inspect` of that container:

- In 116 of 219 (53%), the item **was there when the agent last looked**, mostly 2 or more minutes earlier. A teammate
  had emptied the shared depot since: stale information.
- In 69 (32%), the agent's own last observation already showed the item missing: a model mistake.
- In 34 (15%), the agent had never observed the container.

Off-grid coordinates are not the cause: they appear in 18% of failures and 23% of successful takes.

The message names neither the container's position nor what it does hold, and it doesn't say where the item is now. The
mod already has a `sources` query (used by `crew/controller.py:110`) that answers exactly that question.

Class: tool design, plus model. Fixed at HEAD: no for `act take`. The `build` tool sidesteps it by sourcing items itself.

**2. place: "blocked by \<entity\>"** (160 failures, 527 skipped)

Example: `cannot place electric-mining-drill at 49,102: blocked by transport-belt@47.5,100.5, …` (DeepSeek-flash).

The blocker list comes from `jobs.lua:355-371`. Of the 160:

- 20 had the **identical entity already at that exact spot**, usually a retry of the agent's own earlier placement. Place
  isn't idempotent, so these count as failures and trigger cascades.
- 42 had a different entity on the exact tile.
- 98 were footprint overlaps: a 2x2 or 3x3 anchor misjudged, or a drill placed over belts.

Class: mostly model mistakes, with tool design (no idempotence) for the first 20. Not fixed.

**3. place: "blocked by tree-0N@…"** (157 failures, 699 skipped, the largest cascade source)

`can_place_entity` with the manual build check (`jobs.lua:333-341`) refuses trees, and the handler never tries to clear
them. In 96 of 157 cases (61%), the agent mined the tree and then repeated the identical `place`, which succeeded. The
failure is pure overhead. On top of that, each one killed 4.5 queued actions on average, and 81% of those were
re-issued.

Class: tool design (missing capability; a player would just mine the tree). Not fixed. The HEAD `build` tool clears
blockers only when they are marked for deconstruction (`crew/controller.py:184-188`).

**4. mine: "transport-belt at x,y was built by claude-N …"** (115 failures, 815 skipped)

The guard is at `jobs.lua:177-182`. Ownership comes from `storage.built_by`, which is set at `jobs.lua:391,973` and
initialised once in `scripts/agents.lua:23`. **It is never reset, so bench runs inherit the live save's ownership
map.** The numbers:

- In bench runs, 34 of 89 guard hits named claude-4 or claude-5, agents that don't exist in a 3-agent bench crew. One
  example: `stone-furnace at 86,62 was built by claude-4` in the `effort-medium` run.
- Only 6 of 89 guarded entities had been placed by that teammate during the run.
- After a guard hit, the agent forced the pickup (`force_pickup=true`) 76 times and never retried 34 times. The guard
  added a round trip and a cascade: on average each hit killed 7 queued actions, usually the rest of a "pick up this belt
  line" batch.

The same map feeds the `connect` join guard (`jobs.lua:828`, signature #14). The message was reworded in `ea1ee71`
(04:37), which cut median recovery from 83 s to 11 s, but neither the guard nor the leak changed.

Class: harness bug (inherited ownership), plus tool design (failing instead of warning). Not fixed.

**5. connect: "route needs 73 transport-belt but you have 40"** (78 failures; `jobs.lua:843-847`)

Routing is all-or-nothing on inventory. A belt route's length can't be known in advance because of detours, so the
agent learns it only by failing. 24 identical retries later succeeded, after the agent fetched or crafted more.

Class: model, plus tool design. Partly fixed at HEAD: `build kind=line` fetches or crafts about 1.4 times the Manhattan
distance first (`crew/controller.py:254-262`).

**6 and 10. move: "no path to 80,-40 (blocked by water/cliffs/buildings?)"** (78) **and "stuck at x,y"** (45)

`movement.lua` makes three `request_path` attempts. The goal radius starts at 0.5 tiles, and only the third attempt
widens it by 2 (`movement.lua:81-91`). The goal is never snapped to a free spot, so a goal on a machine, in water or in a
dense block fails.

- 74% of failing goals were integer corner coordinates, about the same as successes (79%).
- Distance is not the driver: the median is 44 tiles for failures and 43 for successes.

"Stuck" means 45 ticks without moving, five times (`movement.lua:10-11,113-121`).

Class: harness and tool design. DeepSeek models are 3 to 4 times as likely as Opus to pick unreachable goals. Not fixed.

**7 and 15. connect: "can't route small-electric-pole: no route found within search limit" or "no route (blocked)"** (91 failures, plus 10 start or end tile blocked)

`route.find` (`mod/claude-crew/scripts/route.lua:38-93`) is a 4-neighbour A* over tiles where `can_place_entity` passes,
capped at **6,000 expanded nodes** (`route.lua:41,76`). It has two blind spots:

- **Poles are routed tile by tile like belts.** Placing every 6th tile along the path (`jobs.lua:801-808`) needs a
  contiguous free corridor, even though wires span 7.5 tiles over belts and machines. Pole `connect` fails 50% of the
  time (71 of 141), against 17% for belts and 30% for pipes. "Fully blocked" is 24 of 33 pole cases, with a median leg of
  only 21 tiles. After 56 pole routing failures, the agents placed poles by hand in 38 cases.
- **Belts and pipes can't cross existing belts or pipes**, because the router has no underground hops. When an endpoint
  sits in a pocket walled in by belts, pipes or machines (common next to machines in a dense base), A* floods all the
  open ground it can reach.
  - If that ground holds more than 6,000 tiles, the result is "search limit".
  - If not, it is "blocked".
  - That's why short legs fail too: the 25th-percentile length of node-limit failures is 23 tiles for belts and 11 for
    pipes. `free_tile` slides each endpoint up to 2 tiles (`jobs.lua:780-794`) and can slide it into such a pocket.

The message "within search limit" reads as "too far", which steers the model, and the HEAD controller's midpoint split
(`crew/controller.py:269-273`), towards shorter legs. Shorter legs don't fix a crossing. These failures also have the
longest recoveries (39 to 63 s median).

Class: tool design (missing capability, misleading message). Partly addressed at HEAD (leg splitting only).

**8. find: "game error: Unknown entity name: copper-plate"** (55; `mod/claude-crew/scripts/observe.lua:334-342`)

`find` passes `name` straight to `find_entities_filtered`. What the models passed:

- **Items**: copper-plate 12, iron-plate 6, steel 3, circuits 3, engine-unit 2, sulfur 2. "Where is X stored?" is a
  missing capability.
- **Types**: `assembling-machine`, `furnace`.
- **Generic words**: `tree` 7, `rock` 4. `mine` handles these, but `find` doesn't.
- **Agent names**: `claude-3`.

Every model does it, including Haiku 9 times and DeepSeek-pro 17 times.

Class: tool design. Not fixed.

**9. mine x,y: "nothing minable found near 31.8,-47.7"** (51 failures, 165 skipped)

All 51 were positional. The first search uses a 0.8-tile radius around (x,y) (`jobs.lua:107-117`). On a miss, the
handler takes the *named-search* branch and **reports the character's position, not the requested one**
(`jobs.lua:169-175`). For example, it asked for `x=27.5 y=-51.5` and was told "near 31.8,-47.7". The positional message
at `jobs.lua:166` is effectively unreachable.

In 38 of 51 cases, nothing had been observed within 1.5 tiles of the target in the previous 15 minutes (coordinates from
memory, or a teammate had already removed the thing). In 8 cases, an entity sat 0.8 to 1.6 tiles away, so the radius was
too tight.

Class: model, plus a misleading message. Not fixed.

**11. place: "create_entity failed for splitter|transport-belt"** (39 failures: 20 splitters, 18 belts, 1 fast belt; 118 skipped)

`can_place_entity{build_check_type=manual}` (`jobs.lua:341`) accepts fast-replace, such as a splitter over belts or a belt
over a belt. `create_entity` (`jobs.lua:383-389`) is called without `fast_replace=true` or a player, so it returns nil.
In 16 of 39 cases, the agent then mined the belts at that spot and the same `place` succeeded. This is an inference;
check it with a one-line smoke test that places a splitter on a straight belt.

Class: harness bug. Not fixed.

**13. place: "invalid spot (water, cliff or wrong tile)"** (35)

This is the fallback text when no blocker is found (`jobs.lua:372-378`):

- 37% of these failures used off-grid coordinates for a 1x1 entity (`small-electric-pole x=-10 y=-22`), against 6% of
  successful 1x1 places. `ACTION_DOC` says "the game snaps", but `can_place_entity` checks the exact position.
- Most of the rest are pipes. 9 identical retries failed again. These are probably the 2.0 rule against mixing fluids,
  which the message never mentions.

Class: tool design. Not fixed.

**14. connect: "this line would feed into claude-N's belt"** (34; `jobs.lua:822-842`)

Recovery is cheap (5 s median). In bench runs it shares the leaked ownership described in #4.

Class: design; acceptable once ownership is fixed.

**16, 17 and 18. craft and insert failures**

- `craft` missing ingredients: the message includes the `missing` map. Model mistake.
- `insert` "won't accept": the message doesn't say why (no recipe set, wrong ingredient, or full), except for the fuel
  case.
- `insert` with an item not in inventory: model mistake.

**19. act: "unknown action op 'look'"** (10, DeepSeek-flash 8)

The models put the `look` or `inspect` tools inside `act`. `jobs.enqueue` (`jobs.lua:1162-1172`) raises **after** it has
already queued the earlier actions in the batch. Those then run, while the model was told the whole call failed and holds
none of their ids.

Class: model, plus a harness bug (partial enqueue). Not fixed.

**20. mine x,y name=tree: "error: Unknown entity name: tree"** (9 failures, 35 skipped)

The positional branch passes `name = args.name` unmapped (`jobs.lua:109`). The named branch maps `tree` and `rock` to
types (`jobs.lua:121-122`).

Class: harness bug. Not fixed.

## Task 3: cascades and stop-on-fail

The job engine (`jobs.lua:1146-1159`) marks **every** queued job "skipped" when one job fails, unless that job's
`stop_on_fail == false`. The Python side returns as soon as any job fails (`crew/tools.py:135-136`), and `ACTION_DOC`
documents only the skip-all rule (`crew/tools.py:40`). The per-action `stop_on_fail` escape has existed since the first
commit (`jobs.lua:1153,1167`) but is undocumented. It was used **0 times in 31,690 actions**.

Measured:

- 69% of the 7,194 `act` batches have more than one action (4.4 on average). 1,294 batches had a root failure. In 806 of
  them (62%), the failure was not the last action, and **3,679 later actions were skipped**. Across all queues, 3,913
  jobs were skipped, against 1,340 root failures: 2.9 collateral skips per failure, and 74% of all FAILED lines.
- **Dependency**: by a heuristic, 91% of skipped actions (3,349 of 3,679) did not need the failed one. A skipped action
  counted as dependent if it consumed the item the failed `mine`, `craft` or `take` was meant to produce, targeted the
  same x,y, or followed a failed move with another move. Every action walks into range by itself, so a failed move
  doesn't invalidate later actions either.
- **Cost**: 63% of the skipped actions (2,301) were re-queued verbatim within 10 minutes, a median of 4.7 s after the
  failure. That took **704 extra `act` calls (about 10% of all `act` calls)** of model time and tokens. The other 37%
  (1,378) were never re-issued: intended work silently dropped.
- **Biggest cascade sources**:
  - trees: 699 skips from 157 failures
  - take: 589 from 226
  - ownership guard: 815 from 115
  - blocked by building: 527 from 160
- **Beyond the batch**:
  - The skip also wipes later pipelined batches and `connect` sub-placements. That is up to about 210 jobs: 9 confirmed
    plus 201 that could not be mapped to a batch.
  - Even the HEAD controller works around the rule: "one chest per action; a failed take shouldn't skip the others"
    (`crew/controller.py:123`).

Verdict: stop-on-fail is the wrong default. Make the default "continue". Skip only actions that depend on the failed
one: they consume the item it was meant to produce (the item named by mine, craft or take), or they target the same
entity. Also skip a connect's own remaining placements. Let the model opt in with `stop_on_fail=true` (or
`after=<index>`) for real chains, and document it. Report "N later actions ran anyway" in the result.

## Task 4: misleading tool outputs

1. **`connect` says OK while its placements fail where no agent can see.** `connect` queues its placements as new jobs
   with fresh ids (`jobs.lua:849-851`) that are never returned to Python. `Agent.on_result` drops any result whose id
   isn't in `pending_jobs` (`crew/agent.py:131-133`). So a failed sub-placement never reaches the model.
   - 39 root failures were never shown to any model; 28 of them came right after a `connect`. They skipped 65 of the
     agents' own later jobs with "skipped: earlier job N failed", where N is an id the model had never seen.
   - Example from `effort-medium-i29`: claude-3 ran `connect` #2241, "routed 87 tiles; placing 87 transport-belt from
     5.5,63.5 to 5.5,-22.5". One of its later placements, #2306, failed out of sight, so the tail of the line (up to about 22 belts) was never placed. Within 4
     minutes claude-3 ran `update_task #2 done` with the note "Plates belt x=5.5 north to 5.5,-22.5".
   - The HEAD controller has the same blind spot: `_do` waits only for the connect job's own id
     (`crew/controller.py:51-63`), so `build kind=line` will report "done" for a broken line too.
2. **`build_ghosts` says "built N ghosts; none left here" while ghosts remain.** Ghosts it couldn't reach or revive go
   into `job.skip` (`jobs.lua:945-949,965-969`) and are excluded from the "left" count (`jobs.lua:936-938`). In at least
   27 of 515 "none left" results (5%), the next status within 2 minutes showed an unbuilt ghost inside the same radius.
   That is a lower bound, since only one example ghost is shown. Separately, 113 results were "built 0 ghosts; none left
   here", usually from build_ghosts centred on the character, away from the plan.
3. **Positional `mine` failures report the character's position as the place searched** (`jobs.lua:175`). This affected
   51 cases.
4. **`take` failures hide the container's position and contents** (`jobs.lua:499`). In 53% of them, the agent's world
   view (its last look) still showed the item there.
5. **"invalid spot (water, cliff or wrong tile)"** (`jobs.lua:377`) is shown when the real cause is an off-grid
   coordinate (37%) or, probably, fluid mixing. Agents retried the identical action and failed again 9 times.
6. **"no route found within search limit"** implies the route is too long, but legs as short as 11 to 23 tiles hit the
   limit (see #7). Agents and the HEAD controller respond by splitting legs, which doesn't help a crossing.
7. **Partial successes reported as plain OK**:
   - `take count=N` returned fewer than N in 170 of 1,785 calls (9.5%).
   - `craft` "only had ingredients for n of m" (19).
   - Underground belts "not paired yet" (210). This is stated in the text, but it is still an OK that leaves a leaking
     belt.
8. **The "game error" on an unknown op hides a partial enqueue** (`jobs.lua:1164-1170`; see #19).
9. **`stamp` and `plan_ghosts` lay ghosts through the agent's own job queue** (`crew/tools.py:439-442,590-593`). An
   earlier failure in that queue skips them: 2 occurrences, "stamp failed: skipped: earlier job 1962 failed". A busy
   queue would also raise an uncaught `asyncio.TimeoutError` after 20 s, because `run_tool` doesn't catch it
   (`crew/tools.py:615-620`). That last one is latent; it was not seen.
10. **Operator-facing**: the "turn error (success)" lines in bench and live logs are usage-limit stops. `ResultMessage`
    reports `is_error` with subtype `success` (`crew/backends.py:118-119`, `crew/agent.py:306-312`). The backoff is
    right, but the label hides the cause. There were 15 in `noadvisor-i28`.

## Ranked fixes (frequency × time wasted)

1. **Make cascades dependency-aware** (`mod/claude-crew/scripts/jobs.lua:1146-1159`; `crew/tools.py:40,135-136`).
   - Impact: about 3,900 skipped jobs, about 700 extra `act` calls and about 1,400 dropped actions.
   - In `finish`, skip a queued job only when it depends on the failed one:
     - It consumes the failed job's product (`mine.name`, `craft.recipe`'s product or `take.item`, matched against a
       later `place.name`, `insert.item`, `craft` or `connect.item`).
     - It has the same x,y.
     - It is a sub-placement of the same `connect` (tag jobs with `parent`).
   - Keep the opt-in `stop_on_fail=true` and document it in ACTION_DOC. In `_wait_jobs`, stop breaking out on the first
     failure. Return the full batch outcome, with "#k failed; #k+1..n ran anyway".
2. **Have `place` (and `build_ghosts`) clear trees, rocks and stumps in the footprint** (`jobs.lua:341-379`).
   - Impact: 162 failures and about 710 skips, with a 61% verbatim-retry success rate after hand-mining.
   - When the only blockers are of type `tree` or `simple-entity` (or a decorative trunk), queue a `mine` sub-step for
     each, within resource reach, then retry `can_place_entity`. It costs about 0.5 s per tree, which is what a player
     pays anyway.
3. **Fix ownership** (`scripts/agents.lua:23`; `jobs.lua:177-182,828`).
   - Impact: 149 failures and about 840 skips.
   - Clear `storage.built_by` when a bench run starts. Ignore owners who aren't currently registered crew
     (`storage.agents`). For entities that don't belong to a human, downgrade the guard to a warning appended to an OK
     result ("picked up claude-2's belt; tell them"), or allow it automatically when the entity was placed more than N
     minutes ago.
4. **`take`: say what's there and where the item is** (`jobs.lua:470-503`).
   - Impact: 226 failures and 589 skips.
   - The failure should include the container's position and contents, plus the nearest 2 or 3 other containers holding
     the item. Reuse the `sources` query that `controller.source` uses.
   - Optionally add `from=nearest`, letting `take item=X count=N` without x,y pull from the nearest containers. With fix
     1 in place, a failed `take` stops costing the rest of the batch.
5. **Router capabilities** (`mod/claude-crew/scripts/route.lua`; `jobs.lua:772-855`).
   - Impact: 101 routing failures, 50% pole failure rate, and the slowest recoveries (39 to 63 s).
   - **Poles**: search over candidate pole sites, where a site is any free tile and an edge joins two free sites within
     wire reach. Never require a contiguous free path.
   - **Belts and pipes**: add underground-belt and pipe-to-ground hop edges (up to 4 or 10 tiles), costed by item.
   - **Diagnostics**: when the limit is hit, run a reverse flood from the goal with a small budget to tell "goal enclosed
     by transport-belt at x,y; needs an underground" apart from "too far". Raise `max_nodes` in proportion to distance.
6. **Report `connect`'s placements** (`jobs.lua:849-851`; `crew/agent.py:131-133`; `crew/controller.py:51-63`).
   - Impact: 39 hidden failures, false "done" reports, and the HEAD `build kind=line` has the same blind spot.
   - Make `connect` one long job that ticks its own placements and finishes with "placed 65/87; stopped at x,y: blocked
     by …". Alternatively, return the sub-job ids and add them to `pending_jobs`.
7. **Make `place` idempotent and fast-replace aware** (`jobs.lua:308-389`).
   - Impact: about 95 failures and about 200 skips.
   - Same entity, position and direction already there: return OK "already there".
   - When `can_place_entity` passes and the spot holds a fast-replaceable entity, call `create_entity{…, fast_replace=true,
     player=?, spill=false}` or ask the character to build.
   - Snap 1x1 and 3x3 positions to tile centres and 2x2 positions to corners before the check.
   - When no blocker is found, report the tile name, water, cliffs or fluid mixing.
8. **Make `build_ghosts` honest** (`jobs.lua:932-938`).
   - Impact: at least 27 false "none left" results, and the HEAD controller's `zone` checks rely on similar counts.
   - Count the skipped ghosts: "built N; M skipped (unreachable or blocked at x,y: …)". Return OK only when nothing is
     left.
9. **Teach `find` about items and generic names** (`mod/claude-crew/scripts/observe.lua:334-363`).
   - Impact: 55 failures.
   - Item names: search containers and machine outputs for the item, the same way as `sources`.
   - `tree`/`rock`: map them to types, as `mine` does.
   - Entity types given as names (`assembling-machine`, `furnace`): retry with `type=`.
   - Unknown names: a friendly error with close matches instead of a Lua error.
10. **Fix `mine` (x,y)** (`jobs.lua:105-110,166-175`).
    - Impact: 60 failures and 200 skips.
    - Map `tree`/`rock` in the positional branch.
    - Use a footprint search instead of a 0.8-tile radius (the same as `entity_at`).
    - On a miss, report "nothing minable at x,y; nearest is … at …".
11. **Snap `move` goals** (`mod/claude-crew/scripts/movement.lua:18-36,81-91`).
    - Impact: 123 failures and about 200 skips.
    - Before the first request, replace a goal that collides with `find_non_colliding_position("character", goal, 8,
      0.5)`.
    - When stuck, step aside with `find_non_colliding_position` before re-pathing.
    - Say which of water, cliff or an entity is at the goal.
12. **Let `connect` place what it can** (`jobs.lua:843-847`).
    - Impact: 78 failures.
    - Offer `partial=true` (lay as far as the inventory allows and return the stop point), or source from nearby chests
      as `build kind=line` does.
13. **Validate the whole batch before enqueueing** (`jobs.lua:1162-1172`).
    - Impact: 10 failures, but it removes the partial-enqueue hazard.
    - Check every op first. The error should list the valid ops and note that look and inspect are tools, not `act` ops.
14. **Small items**:
    - `research` on an already-researched tech should return OK, as it already does for "already queued".
    - `insert` "won't accept" should say why: no recipe, not an ingredient, or full.
    - Catch `asyncio.TimeoutError` in `run_tool`.
    - Run `stamp`/`plan_ghosts` ghost placement outside the agent's job queue: it's instant and needs no character.
