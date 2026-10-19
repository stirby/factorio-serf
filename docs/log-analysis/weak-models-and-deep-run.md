# Weak models and the deep run: what the DeepSeek logs say about the harness

Slice: the DeepSeek benchmark runs of 2026-10-18 (s3-research-rush, +6 techs target, 60 min: ds-pro-foreman-flash-workers i41/i42, ds-pro-all i40/i41/i42, ds-pro-workers i43/i44) and the deep run (Opus characterless foreman with 2 v4-pro and 2 v4.1-flash workers on the crew-deep clone, 16:22-18:15). Read-only analysis of transcripts, bench.log, result.json, live.log, metrics.jsonl and board.json, plus the code as it was at the time (`25fea08`/`cd39a74` for the benchmarks, `a2bcfe3` for the deep run).

## Summary

DeepSeek workers act in only 15-29% of their tool calls (Opus workers on the same scenario: 37%). Most of the rest is looking at the world through tools that leave out what the model needs. `inspect` returns no direction, no inserter pickup/drop, no belt contents and no fluids. `map` draws belts and inserters with the same arrow even though the arrow means opposite item flow for the two. Every long inspect loop in the logs is a model trying to infer one of these hidden facts by trial and error. Two harness bugs then cost each worker another 2-18 minutes per hour: (1) the OpenAI backend ends a turn silently at the 60-call cap, so the worker goes idle and waits about 100 s for an idle check (67 of 72 non-error worker turns ended this way); (2) a v4-pro reply cut off at max_tokens is treated as an API error with exponential backoff (25 of 67 pro turns). The deep run's 8 techs were held back by two faults no tool could show: junk on the lab belt (91 min to find) and a broken water/petgas pipe at the oil site (about 100 min to find). The most important finding for the next setup is about money: the claude-code backend records the session's *cumulative* `total_cost_usd` as each turn's cost. That inflated the Opus foreman from about $4.45 to $29.85, so the deep run cost about $10, not $35.61. The same phantom spend tripped the $25/h cap and paused all workers from 18:01 to 18:10. The bug is still at HEAD and will hit Opus foreman + Sonnet workers directly.

## 1. Why DeepSeek workers acted in only 10-30% of their calls

### The numbers

| Workers | Tool calls | Act share (tool calls) | Act share (model calls) | Calls per model call |
|---|---|---|---|---|
| Bench flash (6 workers, i41/i42 flash) | 2063 | 28.5% | 41% | 1.43 |
| Bench pro (12 workers, ds-pro-all + ds-pro-workers) | 3856 | 19.7% | 30% | 1.58 |
| Deep flash (claude-2, claude-4) | 944 | 24% | 34% | 1.40 |
| Deep pro (claude-1, claude-3) | 990 | 15% | 24% | 1.62 |
| Opus baseline (round 13, i30/i31 workers) | 1633 | 36.8% | - | - |

"Act" = `act`/`stamp`/`plan_ghosts`. Part of the low share is an artifact of how it's counted: DeepSeek fires 1.4-1.6 read-only calls in parallel per model call. Even per model call, though, pro acts in only 24-30% of steps. The mod's character counters agree: characters were idle 70-89% of the hour for flash workers and 74-98% for pro workers (result.json `mod_stats.idle_pct`).

### Every non-action call, by purpose (all 22 DeepSeek worker transcripts, 7853 calls)

Classified by script: verify = an inspect/look/map within 2-3 calls of an act, near its coordinates; re-poll = the same tile inspected within the last 8 calls; fan-out = a radius-1 inspect sent with 3+ other calls in one model response.

| Purpose | Share | Opus baseline |
|---|---|---|
| ACTION | 22.0% | 36.8% |
| Survey/locate (inspect wide, map, find, look) | 30.4% | 23.1% |
| Single-tile inspect fan-out (probing tiles one by one) | 10.9% | 0.1% |
| Verify after act (inspect/look/map) | 10.8% | 12.9% |
| Re-poll the same spot + idle `wait` (nothing running) | 9.4% | 5.8% |
| Reference (recipes/techs/designs), 1.0% exact repeats | 4.7% | 2.5% |
| Coordination + board (report/ask/notes/status/tasks/work/marks) | 6.2% | 15.4% |
| Measure (production/diagnose) | 3.8% | 1.0% |
| Wait on running jobs | 1.8% | 2.3% |

What separates DeepSeek from Opus is the fan-out (10.9% vs 0.1%) and re-polling (7.2% vs 1.6%); verification after an act is about the same. Pro is worse than flash in both: pro fan-out 14.8% and re-poll 8.3%, against flash's 3.3% and 4.0%.

### The loops and what triggered them

A script found 60 chains of 4 or more inspects of the same tile within 25 calls (317 inspects). Of the 12 longest, 11 are at oil/fluid sites (pumpjack, refinery, chemical plant, pipes, or empty tiles probed before placing a refinery) and the 12th is a boiler fed by a burner inserter. Each one is a model trying to learn something no tool reports.

- **Pumpjack port probing (i43 claude-3, pro, 15:57:36-16:00:51; 77 calls, 58 of them inspects).** First 25 single-tile inspects in a 5x5 grid (15:57:36 and 15:57:43), all `{"entities":{}}`, just to learn whether a refinery fits. It then placed pipes on each side of the pumpjack and re-inspected the pumpjack after each one, looking for its status (`waiting_for_space_in_destination`) to change. Two missing facts drove this: which tiles are free, and where the fluid ports are. *Tool output insufficient.*
- **Burner inserter that never feeds the boiler (i43 claude-3, 15:37-15:51).** `inspect` showed the inserter `"status":"waiting_for_space_in_destination","inventories":[{"coal":1}]` next to a boiler holding 5 coal. Inspect doesn't report the inserter's direction or pickup/drop tiles, although `look` does (`from`/`to`). Seven inspects and 3 manual coal inserts followed (`insert: FAILED no coal in inventory` at 15:40:02). Eight minutes later came 17 more single-tile inspects of the same block. *Insufficient.*
- **Hand-smelting steel by polling one furnace (i43 claude-3, 15:24-15:45).** It placed 2 stone furnaces 90 tiles from the base, hand-inserted iron, then cycled inspect → `wait 45` → inspect → take. It happened again at 15:43:09-15:44:48: inspect, wait 75, inspect, wait 50, inspect, wait 25, inspect, then `take steel-plate 10`. There's no "wait until this entity has N of item X", so polling is the only way. *Tool design (missing wait condition) + model judgement.*
- **Belt direction flip-flop with idle waits (i41 ds-pro-all claude-1, 15:21-15:34).** At 15:21:16 it rotated six belts at x=39.5 to face south, and at 15:24:35 rotated the same six north. In between came `wait 12`, `wait 15`, `wait 20` with nothing running, each followed by `production`. That is 6 idle waits in 12 minutes, each used as "let it run, then check". `production` is a one-minute window, so the model can't see the effect of a change sooner. *Insufficient (no belt contents, lagging rates) + ambiguous map glyphs, below.*
- **Same-spot `look` polling before a cut-off (deep claude-1, pro, 17:52:19-17:53:51).** It called `look` with radius 10, 6, 8, 13 from the same position, then produced no tool call for about 95 s and was cut off at max_tokens (17:56:26).
- **Oil site (deep claude-3, pro, 17:42:59-17:54:28).** 51 inspects of the refinery and chemical plants (`fluid_ingredient_shortage`), 4 acts. The cause, found later by claude-2 (18:06): "the plant's west fluid port had no water — the water pipe run had a missing tile at (185,201) and its west input pipe was fed from the petgas". No tool shows fluid contents or port connections.

### Tool output that is insufficient, ambiguous or misleading (tools at `a2bcfe3`)

- **`inspect`**: "Details of whatever is at x,y: inventories, recipe, progress, status, ore amount." (`control.lua` `API.inspect`). It omits direction, inserter pickup/drop, drill drop tile, belt lane contents and every fluidbox. The `look` entity summary (`observe.lua` `entity_info`) does carry `dir`, `from`/`to` and `drops_at`. Inventories are an unlabelled list (`"inventories":[{"coal":3}]`: fuel, input or output?). An empty result serialises as `{"entities":{}}`. `energy` is a raw float (`2976579765`). A lone, unconnected pipe reports `"status":"working"` (i43 claude-3 15:58:19). *Insufficient + ambiguous.*
- **`map`** legend: "^>v< belt/inserter facing". The arrow comes from `e.direction` for both, but a belt's arrow is where items go, while an inserter's direction is where it *takes from* (ACTION_DOC: "inserters TAKE from the side they face"). The same `^` means opposite item flow. Of 377 rotate ops, 89 (24%) re-rotated a tile already rotated within the last 30 act calls, and 73 (19%) rotated something placed within the previous 10 act calls. *Ambiguous; likely contributor to direction errors (correlation, not proven).*
- **`production`** ("Items per minute produced/consumed by the whole base") and **`diagnose`** read only `get_item_production_statistics` (`late.lua:68`), so every fluid reads 0. Examples: `crude-oil made 0/min, used 0/min ... producers 2: working 2` (deep claude-2, 17:41:37); `water ... producers 0: none | LIKELY CAUSE: nothing makes water on nauvis` while an offshore pump fed the refineries. *Misleading.*
- **`place pumpjack`** returns "output drops at 167.5,193.5" (i42 ds-pro-all claude-2, 15:02:51); `look` repeats `drops_at` for pumpjacks. A pumpjack's output is fluid, through a port. *Misleading.*
- **`rotate`** on a chest returns OK: "rotate: OK rotated iron-chest to north" (i41 ds-pro-all claude-1, 15:33:30). *Misleading no-op success.*
- **`techs`** listed `"unlock_by":"mine-entity crude-oil"`, and the model hand-mined crude oil: "Found crude oil at (167,193). Let me go mine some to unlock oil processing." → `mine: FAILED mining is not progressing on crude-oil` (i42 ds-pro-all claude-2, 14:59:41). *Misleading; fixed in `3e0eaf0`.*

## 2. Tool-level failures and confusions

There were 351 failed actions across all worker transcripts, not counting "skipped: earlier job failed". The top groups:

| Failure | Count | Root cause |
|---|---|---|
| `move: no path to x,y (blocked by water/cliffs/buildings?)` + `move: stuck` | 35 + 10 | Targets inside buildings or water. Coordinates came from unclear map reading. Tool design: no "nearest reachable tile" fallback. |
| Teammate guard: `mine: transport-belt at x,y was built by claudeN ... force_pickup`, `connect: this line would feed into claudeN's belt` | 13 + 12 + 4 | Guard working as designed, but it costs a foreman round trip each time. The foreman had to authorise force_pickup on the lab belt (deep, 17:43:06). Tool/prompt design. |
| Pipes: `cannot place pipe at x,y: blocked by pipe` (13), `can't route pipe: no route found within search limit` (10), pipe/pipe-to-ground on water (9) | 32 | No fluid or port information, so pipes go on top of pipes. Tool design. |
| `connect: route needs N <item> but you have M` | 14 | `connect` doesn't craft or fetch the shortfall; the model re-plans by hand. Tool design (the HEAD `build` controller addresses this). |
| `place: create_entity failed for transport-belt/splitter` | 10 | Generic error that doesn't say why. Tool design. |
| `take: nothing to take from ...` | 35+ | Polling machines for output that isn't there yet. Model + missing wait condition. |
| `mine: nothing minable found near x,y` | 8 | Repeated the same failed mine 3 times (deep claude-3 at 185.9,200.6; the foreman intervened at 17:43:07). Model. |

Tool-level errors, the result of misunderstood semantics:

- `find` with item names (`sulfur`, `copper-plate`, `iron-plate`, `iron-gear-wheel`, `copper-cable`, `engine-unit`) returned `game error: Unknown entity name: sulfur` 9 times. The models wanted "where is item X stored". `find name=rock|tree|assembling-machine` (9 times) should be `type=`. The tool says "by prototype name (e.g. iron-ore, coal, crude-oil, stone-furnace) or type (e.g. tree, resource, assembling-machine)", and the error doesn't suggest `type`. *Tool design.*
- Tool names used as act ops: `unknown action op 'look'` (5), `'inspect'` (3), `'stamp'` (1). These surface as a Lua traceback string (`game error: __claude-crew__/scripts/jobs.lua:1036: unknown action op 'look'`). *Tool design: validate ops in Python and list them.*
- `stamp` refused for an uncleared area 27 times ("isn't clear: blocked by small-electric-pole..., crash-site-spaceship..."). It gives no alternative site, so the model goes back to fan-out inspects or map scans. *Tool design.*
- `research` failures read "could not queue logistic-robotics (missing prerequisites or queue full)" (deep foreman, 16:23:17). Two different causes share one message. The queue caps at 7, and logistic-robotics was "DROPPED again (queue max 7)" (foreman notes, 17:07). *Tool design.*
- `configure` filter misuse: claude-4 filtered the lab fast inserters to `automation-science-pack` only (17:36:37) and cleared the filter 14 min later (17:50:26). *Model.*

## 3. The deep run (16:22-18:15, 32 → 40 techs)

**Where the 8 techs came from (live.log RESEARCH FINISHED):** modules 17:04, railway 17:34, lubricant 17:38, electric-engine 17:43, battery 17:53, robotics 17:55, construction-robotics 17:57, advanced-material-processing-2 17:58. No tech finished in the first 42 minutes. Modules and railway (red+green only) were filler: the foreman moved them to the front because blue was starved ("I moved railway to the front because it only needs red and green", 17:07). AMP2 stood at 94% at the start. The foreman's `research construction-robotics first=true` (16:23:15) pushed it to the back of the queue, and it finished 95 min later. The 5 robot-chain techs ran in a 20-minute burst (17:38-17:57), fed by 246 sulfur claude-4 delivered by hand (17:19) and by hand-carried red packs, until claude-4 finally fixed the lab feed at 17:53.

**Critical-path blockers, in order:**
1. **The lab feed (16:22-17:53, 91 min).** All 11 labs were starved while 7 red assemblers sat at `full_output`. The real cause was a belt facing head-on into the red belt at (4.5,-43.5), plus the mall's gear/plate belt dumping junk into the x3.5 lab feeder. claude-4 (17:53): "the x3.5 lab feeder column had been filled solid with junk gears/iron plates ... I mined the 4 column belts and got 34 gears + 34 plates off them". No tool shows belt contents. The foreman, 16:48:50: "I couldn't see what's on the belt, so I'm guessing it's clogged ... or a belt at the junction is turned the wrong way." The task had 5 owners in turn (claude-1 → claude-4 → claude-2 → claude-1 → claude-4), and workers edited the same junction at the same time. claude-2, 16:53: "tile directions at (3-4,-49..-50) changed between my two map reads". claude-1's cut at 17:16 left a gap the foreman had to diagnose (17:20).
2. **Sulfur and water at the oil site (16:23-18:06).** There was no belt from the oil site to the blue block, no water within 300 tiles, and later a petgas/water pipe mix-up. Sulfur first came out at 18:06. Every worker said it was flying blind: the foreman, 17:56:12: "I can't see pipe contents from here"; claude-2, 17:49:08: "Fluid contents are invisible to my inspection tools, so blind pipe-cutting on claude-3's build risks making it worse."
3. **Copper (from ~17:40).** The (11,93) patch ran dry: copper plates dropped from 180/min to 39-75/min, and red science became copper-limited. At the end: "Labs 1/11 ... red made 9 because claude-1's hand-filled copper chest (-12.5,-51.5) ran dry" (foreman, 18:05).

**What the Opus foreman did:** 27 turns over 1 h 43 min, median about 21 s per turn. It made 76 `reply`, 27 `notes`, 16 `research`, 15 `diagnose`, 18 `inspect`, 11 `update_task` (7 of them reassignments) and 7 `post_task` calls. It sent step-level build orders with coordinates at 16:29, 16:33, 17:20, 17:41, 17:49 and 17:55. Whether these helped depended on whether its diagnosis was right:
- 16:29: a 3-step belt fix sent to claude-1. claude-1 (pro) didn't act on it. At 16:33 it went to claude-4 (flash), which built it, but it rested on the wrong diagnosis ("the belt fix I gave claude-4 didn't actually solve the red science problem", 16:48).
- 17:20: "Place ONE transport-belt at (3.5,-48.5) facing SOUTH." claude-1 built it and reported at 17:21. This one was correct and quick.
- 17:41 and 17:49: the junction location, then the lane explanation. claude-4 rebuilt the junction (17:45), then found the junk and got labs to 11/11 (17:53).

Flash workers carried out exact instructions quickly. The pro workers often didn't, because they were in a cut-off or a backoff (below). The health lines misled the foreman twice:
- At startup, every worker showed "last 10 min: 0 calls". The foreman read that as "none of the workers made a single call in the last 10 minutes. They may be stalled" (16:22:47).
- At 18:05 it declared claude-1 and claude-3 "dead (13-17 min idle)" and asked in chat for a restart. In fact claude-1 had two max_tokens cut-offs (17:56:26, 18:01:03) with 60 s and 120 s backoffs, then sat out the spend-cap pause (18:01-18:04). claude-3 was in a 51-inspect loop at the oil site (17:42-17:54, 4 acts), followed by a cut-off and the same pause. The health line doesn't say "backing off", "paused by spend cap" or "in a model call for N s". Reassigning work on these signals moved tasks to the productive flash workers (that helped), but it also caused the lab-belt churn.

**Late-game tools:**
- `diagnose` (71 worker calls, 15 foreman) was useful for locating distribution faults. claude-4 at 16:23 found sulfur "made 16/min but 0/min is consumed"; claude-2 found the adv-circuit/cable jam. Its fluid numbers are wrong (always 0; see section 1).
- `network`: 3 calls, every one "no logistic network".
- `configure`: 21 calls, all claude-4, all inserter filters for sulfur/plastic routing (one misuse, see section 2).
- `limit`: 1 call (capping the green-circuit chest so cable reaches the adv circuits).
- `copy`, `paste`, `order`, `equip`: never used. Construction robotics finished at 17:57, and only one roboport was built, at 18:08.
- The `blueprint` entities + `build_ghosts` act ops worked: the robot mall shell, 12 + 7 ghosts, at 16:29-16:30.

Hand logistics substituted for automation throughout. claude-1 (pro) made 151 manual inserts, 136 of them into labs, mostly on the foreman's orders ("EMERGENCY stopgap ... Put about 20 of each into every lab", 17:35:47).

## 4. Cost, latency, incomplete turns and context

| Model (role) | Model calls | Latency median / mean / p90 | Recorded cost | Cut-off turns |
|---|---|---|---|---|
| v4.1-flash (workers) | 2117 | 7.8 / 12.2 / 28 s | $1.22 total, $0.12 per agent-hour | 2 of 32 |
| v4-pro (workers) | 3056 | 7.7 / 13.8 / 34 s (cut-off calls about 100 s, not included) | $19.63, $1.23 per agent-hour | 25 of 67 |
| v4-pro (foreman, bench) | 189 | 10.0 / 16.1 / 35 s | $1.24 | 0 |
| Opus (foreman, deep + i43/i44) | 251 | 2.4 / 3.2 / 6 s | $5.40 after correction (recorded $32.0) | 0 |
| Opus workers, baseline i30/i31 | - | 3.2-4.2 s median | - | - |

**Bugs and gaps found:**
- **Claude-code cost is cumulative per session (harness bug, still at HEAD).** `ClaudeCodeBackend.turn` sets `stats.cost_usd = msg.total_cost_usd`, which is cumulative for the CLI session; `agent.py`/`foreman.py` then add it to `total_cost` and `record_spend` every turn.
  - The deep foreman's per-turn "costs" climb 0.23, 0.34, 0.57 ... 2.18, drop to 0.10 exactly at the context reset, then climb to 2.27. The input tokens per turn don't climb with them.
  - Naive sum $29.85, sum of session-final values $4.45.
  - Same pattern in i43 ($1.54 → $0.55), i44 ($0.63 → $0.40) and the round-13 foreman-opus runs (i31: $10.24 → $1.75 and $10.28 → $2.10). DECISIONS' "foreman ~$10 each" is really about $2.
  - Opus worker sequences are mixed (e.g. i30 claude-3: 1.70, 1.83, 2.55 within one session, but 5.51 → 1.67 elsewhere), so worker costs need checking too.
  - Consequence: the $25/h cap (`orchestrator.spend_ok`) paused workers 11 times between 18:01 and 18:10 on phantom spend.
- **The DeepSeek price basis looks off (unverified).** A least-squares fit of turn cost to tokens gives flash about $0.0015/M input and $0.34/M output, and pro about $0.023/M input and $2.20/M output. DECISIONS lists $0.30/$1.20 (flash) and $1.32/$3.96 (pro). Example: flash i41 claude-1's first turn recorded $0.051 for 6.0M input and 128k output; at $1.20/M the output alone would be $0.15. Input is about 99% cache hits, priced from the gateway's `input_cache_read`. Check one Vercel invoice line before trusting "20-40x cheaper per pack". If cache hits really bill at the usual 10-25% of input, pro's 335M input tokens alone cost $45-110, not $20.
- **Incomplete turns are invisible (harness bug).** Cost, tokens and errors are recorded only when a turn ends. Each benchmark worker's last turn averaged 584 s (16% of the hour; i43 claude-1: 1413 s) with nothing recorded. Estimated missing cost is +$2.56 on $18.57 (+14%). DECISIONS guessed "up to ~2x". The 6-min smoke (i40) completed zero worker turns, so it recorded $0 for both workers.
- **Turns end at the step cap, then the worker idles (harness bug in `OpenAIBackend.turn` and `ApiBackend.turn`).** 67 of 72 non-error worker turns ran exactly about 60 model calls; DeepSeek almost never ends a turn itself. Unlike the claude-code path, these backends don't return `error_max_turns`, so `agent._loop` sets mode idle unless the model happened to call `status working`. The idle check in `orchestrator.py:223` only fires after ≥90 s idle. That cost 88 min of between-turn gaps across 22 worker-runs (85-120 s per turn; deep claude-3 9.4 min, claude-4 9.2 min).
- **A max_tokens cut-off is treated as an API error (harness bug).** A v4-pro response that hits `max_tokens=16000` with no tool call ends the turn as `output cut off (max_tokens)`, then backs off 60, 120, 240 s (`agent.py` error branch). The cut-off call itself took 89-128 s, and in 17 of 27 cases it followed a `map` or `look` result. Backoff totals per worker include 960 s (i42 ds-pro-all claude-1, 5 errors) and 780 s (deep claude-1, 7 errors). `ApiBackend` has the mirror bug: `stop_reason == "max_tokens"` silently ends the turn.
- **Context growth.** The context is never trimmed within a turn, and reasoning is sent back (`keep_reasoning`).
  - Average input per model call is 111k (flash) and 125k (pro); single-turn averages reach 245k.
  - Tool output is small: about 2.7M tokens in total across about 7.9k calls, of which inspect is 36%, look 27% and map 17%. Output, including reasoning, is about 1.5k tokens per call. So retained reasoning is the likely bulk of the growth.
  - The reset rule (`agent.py`: `input_tokens / steps > 80_000`) divides by *tool calls*, not model calls, so parallel calls dilute it. Deep claude-2 never reset in 113 min at about 91k per model call (62k per tool call).
  - The reset is checked only at turn end, so a 60-call turn always runs to full size.

## 5. Generic harness problems vs DeepSeek-specific

**Would also hurt Sonnet workers (generic):**
- Claude-code cumulative cost, and the spend cap tripping on it: directly in the next setup's path. *Harness bug.*
- Invisible belt contents and fluids. The Opus foreman hit this itself (quotes in section 3); the two longest outages of the deep run came from it; and earlier Opus rounds lost 6+ min to "a copper lane clogged with iron" (findings.md). *Tool design.*
- Inspect missing direction and pickup/drop, and the map's shared belt/inserter arrow. Opus workers make fewer fan-outs, but both will still mis-rotate. *Tool design.*
- `production`/`diagnose` blind to fluids. *Harness bug.*
- Health line: no state (backoff, paused, thinking, starting) and, at HEAD, no credit for `build` (see the fix list). *Harness bug.*
- Several editors on one belt junction during reassignments; teammate-guard round trips. *Tool design / prompt.*
- Hand-feeding as an accepted stopgap that hides broken automation. It will also satisfy a `working labs ≥ N held 2 min` done_when check. *Prompt + tool design.*
- `find` without item search, unhelpful errors (`create_entity failed`, unknown op as a Lua traceback, "missing prerequisites or queue full"). *Tool design.*
- Step-cap → idle and max_tokens → backoff if any worker runs on the `api` or `openai` backend. The claude-code path handles `error_max_turns`. *Harness bug.*
- Incomplete-turn cost blind spot (Opus and Sonnet turns run 10-18 min too). *Harness bug.*

**Mostly DeepSeek-specific:**
- Runaway reasoning with no tool call (pro: 37% of turns, flash: 6%). *Model limitation; the harness response (backoff) made it worse.*
- Never ending turns voluntarily. *Model behaviour that exposes the step-cap bug.*
- Single-tile inspect fan-outs (pro 14.8% vs Opus 0.1%) and re-polling (8.3% vs 1.6%). *Model limitation, amplified by the tool gaps.*
- 2-3x slower model steps (7.7-7.8 s vs 3.2-4.2 s median). *Model limitation.*
- Reasoning kept in history driving the 100k+ per-call context. *Backend/provider specific.*
- The crude-oil hand-mining trap. *Prompt/tool text; already fixed.*

## Ranked harness fixes for the next setup (characterless Opus foreman + Sonnet workers with `build` and done_when tasks)

1. **Fix claude-code cost accounting before the next run** (*harness bug*). In `crew/backends.py` `ClaudeCodeBackend.turn`, record the delta `msg.total_cost_usd - self._session_cost` and reset `_session_cost` in `reset()`. Then re-derive the round 13-17 foreman costs. Without this the $25/h cap in `crew/orchestrator.py` (`spend_ok`) pauses Sonnet workers on phantom Opus spend (deep run: 11 pauses, 18:01-18:10), and every cost comparison in DECISIONS is skewed toward "the foreman is expensive".
2. **Make inspect tell the truth about flow** (*tool design*; `mod/claude-crew/control.lua` `API.inspect`, `scripts/observe.lua`). Add:
   - direction, inserter pickup/drop tiles, and drill/pumpjack output (fluid port for pumpjacks);
   - belt lane contents (`get_transport_line(1/2)` item counts) and whether a belt side-loads or meets head-on;
   - fluidbox contents per box, plus each port's position and whether it is connected (`fluidbox.get_pipe_connections`);
   - labelled inventories (fuel/input/output), `[]` for empty results, and drop `energy`.
   In `map`, use different glyphs for inserters (or draw the drop side). These would have shortened both 90-minute deep-run outages, and they serve the foreman, which diagnoses for Sonnet workers.
3. **Health line for the foreman** (*harness bug*; `crew/agent.py` `health_line`, `crew/foreman.py` worker block). At HEAD `acts` counts only `act/stamp/paste/order` and `last_act` only `act`, so a worker using `build` will show "0 build/act" and get reassigned. Also report the state: "in model call 95 s", "backing off 120 s after <error>", "paused: spend cap", "started 2 min ago". These are the two false "stalled/dead" verdicts in the deep run (16:22:47 and 18:05:24).
4. **done_when that can't be passed by hand-feeding, plus one owner per task zone** (*tool design*; `crew/board.py`, `mod/claude-crew/scripts/orders.lua` `check`).
   - Lab tasks should check rates (science made ≥ used for 5 min, `rate` on the pack) or fail when an agent inserted into the checked entities during the hold window. In the deep run, labs at "11/11" repeatedly meant hand-fed packs.
   - Tie the task's `zone` to an exclusive edit lock while it is claimed, so a reassignment hands over the lock instead of adding a second editor. The lab junction had 3-4 editors; claude-1's cut at 17:16 broke the line again.
   - Let the zone owner mine teammate builds inside its own zone without `force_pickup` round trips.
5. **Fluids in `diagnose`, `production` and done_when** (*harness bug*; `mod/claude-crew/scripts/late.lua:68`, `observe.lua:445`, and at HEAD `orders.lua:112`). Use `get_fluid_production_statistics` too, and count offshore pumps and pumpjacks as producers. Today `diagnose` says "nothing makes water" next to a working offshore pump. A done_when `rate` check on petroleum-gas, lubricant or sulfuric acid would always read 0 and could never pass.
6. **Turn-end handling in the non-claude-code backends** (*harness bug*; `crew/backends.py` `OpenAIBackend.turn`, `ApiBackend.turn`; `crew/agent.py` `_loop`).
   - Exhausting `max_steps` returns `error="error_max_turns"`, the same as the claude-code path.
   - `finish_reason == "length"` / `stop_reason == "max_tokens"` continues the same turn with a short "call one tool now" nudge instead of an error with exponential backoff.
   - Record cost and tokens per model call (append to the transcript, or a `call` record), so incomplete turns are counted and smoke runs report cost.
   This matters for Sonnet only if workers run on `api`, but the per-call cost record is useful everywhere.
7. **Context hygiene within a turn** (*harness*; `crew/backends.py`, `crew/agent.py:315`). Compute average context per *model call*, not per tool call. Check it after every model call, not only at turn end. Drop reasoning from all but the last few assistant messages, and collapse old `look`/`map`/`inspect` results to a one-line stub. Inspect, look and map are 80% of tool output.
8. **Replace polling with conditions** (*tool design*; `crew/tools.py` `t_wait`).
   - `wait until={"entity":[x,y],"has":{"steel-plate":10}}` or `until={"status_changes":[x,y]}` to replace the inspect-wait-inspect loops (steel furnace, pumpjack, boiler).
   - A "can I place X here / find_space w h near x,y" query to replace single-tile sweeps (25 inspects before one refinery). The `build` controller places things but still needs a site.
9. **Better errors and semantics** (*tool design*).
   - `find` (`crew/tools.py` `t_find`): answer item names by searching chests and belts, and suggest `type=` for `rock/tree/assembling-machine`.
   - Validate act ops in Python and list the valid ones (`look`/`inspect`/`stamp` as ops, 9 times).
   - `create_entity failed` should name the reason.
   - `research` (`crew/late_tools.py`/`crew/foreman.py`): split "queue full (7)" from "missing prerequisites: X". `first=true` should never push back a tech that is ≥90% done.
   - `rotate` on a non-rotatable entity should report a no-op.
   - Don't report `drops_at` for fluid miners.
10. **Prompt cleanup** (*prompt/instructions*; `crew/prompt.py`).
    - Remove "Size builds with real ratios (ask the architect)" (the architect is off).
    - Replace "After building, verify with look/inspect" with "verify once, via the task's done_when or one status check".
    - Make hand-feeding labs or science assemblers an explicit last resort that must be paired with a task to automate it.
    - Tell the foreman that a worker showing no calls may be in a model call or a backoff; check the state field before reassigning.
