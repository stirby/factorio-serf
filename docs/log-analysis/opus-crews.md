# Opus player crews on s3-research-rush: what goes wrong inside the best runs

Seven runs, all reaching +6 techs. Two used a characterless Opus foreman (i31a, i31b). Five had no lead (i26, i28, i29 at effort medium, i30a, i30b). Each had 3 Opus worker characters. Sources: bench.log, timeline.jsonl, events.jsonl, the transcripts, and the crew code. Timestamps are the bench.log wall clock, given as `run HH:MM:SS`.

## Summary

The 2x spread (30 to 59 min) is mostly not about play quality:

- **Research choice.** The score counts any 6 techs. Tech choice alone moves the pack bill 1.9x: 647 packs in i26 vs 1188-1242 in i30a, i30b, i31a and i31b.
- **i28 was partly quota.** It lost its last 21 minutes to the Claude subscription session limit ("You've hit your session limit · resets 12:40pm" at 09:16:32). That is not a turn-budget or idle problem.

Measured as research work done (time to 600 packs consumed), the runs span 25-39 min. The two best are i31b (foreman, 25.1 min) and i29 (25.1 min).

Inside the runs, the real losses come from four things:

- **A broken belt corner already in the save.** It took 1.5-20 min to find.
- **Late lab scale-up.** Science sat on an 8-lab cap of about 27/min for 7-15 min.
- **Lane and fuel mix-ups.** Coal or the wrong item ended up on ore and pack lanes.
- **Building off-target blue-science infrastructure.** The goal text invites it, and the foreman actively ordered it.

**Costs are overstated.** The reported costs are inflated 1.2-1.7x by a harness bug: `total_cost_usd` is cumulative per session but summed per turn. The foreman really costs about $2 a run (8-9% of spend), not $10. The foreman's main value was decisive, fast domain arbitration (about 11 s median reply). Its main harm was strategic: expensive techs, a blue-chain push, one "shed load" order that removed 2 labs, and a 16-minute iron misdiagnosis.

## 0. Measurement problems to fix before reading any more A/B results

| # | Problem | Evidence | Class |
|---|---|---|---|
| M1 | **i28 hit the subscription session limit.** All 3 agents stopped doing anything at 38.2 min. | `i28 09:16:32 claude-3 thinks You've hit your session limit · resets 12:40pm`, then `backing off 60s/120s/240s/480s/960s` for every agent. The last two techs (toolbelt 09:26:14, sulfur-processing 09:37:25) finished with nobody playing. i28 and i29 ran at the same time on one subscription. The same thing happened at 04:53 to i22/i23 (`i22 04:53:37 … resets 7:40am`). i28 is not in `experiments/invalid_runs.txt`, and DECISIONS 10:26 treats it as a valid 59-min data point. | harness |
| M2 | **Reported cost is the running session total, added up every turn.** | `crew/backends.py:113` stores `msg.total_cost_usd`, which is cumulative for a persistent `ClaudeSDKClient` session. `agent.py:327` and `foreman.py:279` then add it per turn. Per-turn cost rises monotonically inside every session in all 22 transcripts and drops only after a `reset`. Example: the foreman in i31a bills $1.034 for a 1-step, 12 s turn. Real costs (sum of each session's last value): i26 $16.8 (reported 22.2), i29 $21.2 (31.7), i31b **$19.9** (34.6), i31a $26.2 (43.5), i30b $25.9 (41.4), i30a $30.6 (46.0), i28 $24.6 (37.0). The foreman: $2.10 and $1.75 (reported about $10.2 each). This also trips `orch.record_spend`, so the hourly cap fires about 1.5x early. | harness |
| M3 | **"+6 techs" depends on which techs get picked.** | Pack cost from the `techs` output: radar 20, rs1 200, toolbelt 200, EED-1 240, sulfur 300, plastics 400, advanced-circuit 400. Oil-processing (mine crude) and steel-axe (craft 50 steel-plate) are free trigger techs. i26 finished rs1+EED-1+radar+toolbelt, 647 packs, only because claude-3 queued radar at `i26 07:41:59`. Every other run did 1-3 of plastics, sulfur and AC: 914-1242 packs. At i26's own rate of about 26/min, i30b's tech set would have taken i26 about 53 min. The cheapest possible 6 (radar, repair-pack, heavy-armor, military-science plus 2 triggers) is about 135 packs. The goal text ("research toward oil processing and chemical (blue) science") pushes toward the expensive set. | scenario |
| M4 | **Effort medium did not make steps faster.** | Mean gap between tool calls: i29 (medium) 5.7 s, default runs 4.7-6.4 s. Output tokens per call: 431 vs 320-482. Single run, but no sign of the hoped-for latency gain. | (data) |

The fair comparison metric is time to N packs consumed:

| run | setup | time to +6 | packs used | time to 300 / 600 / 900 packs | first ≥15 sci/min | peak labs | true cost |
|---|---|---|---|---|---|---|---|
| i26 | no lead | 30.0 | 647 | 18.0 / 29.0 / – | 5.0 | 11 | $16.8 |
| i29 | no lead, effort medium | 34.0 | 1044 | 19.0 / **25.1** / 31.0 | 8.1 | 14 | $21.2 |
| i31b | foreman | 35.0 | 1232 | 21.0 / **25.1** / **30.0** | 9.1 | 12 | $19.9 |
| i31a | foreman | 45.0 | 1188 | 27.1 / 34.0 / 38.1 | 15.0 | 14 | $26.2 |
| i30b | no lead | 46.0 | 1242 | 26.1 / 34.0 / 40.1 | 7.1 | 19 | $25.9 |
| i30a | no lead | 49.0 | 1238 | 25.1 / 36.0 / 44.0 | 7.1 | 16 | $30.6 |
| i28 | no lead (quota-killed at 38 min) | 59.0 | 914 | 26.1 / 39.1 / 59.0 | 11.1 | 13 | $24.6 |

## 1. What separates fast from slow: critical-path blockers

Every run starts with the same broken save:

- **Labs starved.** 2 labs and 3 science assemblers lack ingredients, so research makes no progress.
- **Iron dead-ends** at a belt corner at (71,-25) that faces the wrong way.
- **Copper is at 0/min.** The ore belt dead-ends at (0,79) with no furnaces.
- **A boiler is out of fuel** at (-31,-43).
- **About 32 abandoned burner drills** at (74,69)/(81,66) are out of fuel and mined out.

How fast these get fixed, and how early the lab count goes past 8, decides the run.

### Blockers common to all runs (ranked by minutes lost)

1. **The 8-lab cap.** With 8 labs, science sits at about 22-29 packs/min for 30 s/unit techs while the assemblers back up. When labs reached 12-14, every run jumped to 50-85/min.

   | run | labs >8 at | plateau and loss |
   |---|---|---|
   | i29 | **16-17 m** | – |
   | i31b | 18-19 m | – |
   | i26 | 30 m | plateau 13-29 m |
   | i31a | 29-31 m | plateau 16-31 m |
   | i30a | 37-41 m | plateau 20-36 m |
   | i28 | 25 m | broke again repeatedly afterwards |

   - Detected right: `i29 08:54:02 claude-1: "Labs are the cap now (6 labs at 30s/unit), so I'm adding a second row"`.
   - Detected late: `i26 ~08:09:43 claude-1: "science assemblers are backed up (full output), so the labs are the bottleneck"`, 28 min in.
   - Estimated loss: 7 min (i30a), about 10-12 min (i31a), hidden by cheap techs in i26.
   - Class: **model limitation + tool design.** Nothing shows lab utilisation against pack supply. The `[base]` line shows "labs N/M working", which reads "8/8 working" even when the labs are the cap.
2. **The iron corner at (71,-25)** (save trap). Fix time: i29 1.5 m, i26 about 4-11 m, i28 4.5 m (`i28 08:43:56 "corner at [gps=71,-25] pointed wrong way, 1100 plates were stuck"`), i31b 4.8 m, i30b 9.9 m, i30a 10.7 m, **i31a 20.1 m**.
   - In i31a the foreman twice accepted wrong diagnoses: "false alarm, output belt backed up" (13:01:53), and "It only makes about 180/min, steel takes most" (13:06:48). It started a second iron column instead.
   - Class: **scenario** (the trap), plus **model limitation**: nobody read "source backed up while the destination belt is empty" as a break in the line.
3. **Coal or the wrong item on a lane.** All of these are class **tool design** (the belt observe sums both lanes; see 3.4) plus **model limitation**.

   | run | what happened | time to find / fix | cost |
   |---|---|---|---|
   | i30b | Coal put on the iron-ore lane on purpose (`14:39:57 claude-2: "I picked up your 3 north-side iron drills so coal can ride the north lane"`). It jammed (`14:50:18 "140 coal vs 44 ore"`), was fixed at 14:54:08, and came back (`15:06:58 "the belt carries mostly coal"`). | – | about 15 min of iron at 94-312/min, green science at 1/min |
   | i29 | Coal curving onto the ore lane (`08:56:17`) | about 7 min to fix | – |
   | i30a | Coal in the circuit belt to green science (`13:42:25`) | – | – |
   | i28 | Coal belt auto-routed into the circuit block (`08:52:15`) | – | – |
   | i28 | Iron on both lanes of the gear feed jammed green (`09:06:01`) | – | sci 0 at 27-28 m |
   | i28 | Red and green on one lane (`08:59:04 "fixed a lane mix-up starving green"`) | – | green 0 for 14-21 m |
   | i26 | Red and green on one lane (`07:49:47 "red and green packs were on the same belt lane so red got blocked"`) | – | about 3 min degraded |
4. **Starting a new science block instead of feeding the old labs.** In every run claude-1 stamped red-science-5, green-science-6 and lab-row-6 from the depot stock in the first 2 minutes. Only i26 also hand-fed the existing labs (`07:42:39 "Hand-feeding labs to restart research now"`), and it was the only run with science above 0 at 3 m. i30a and i30b were at 0 until 6 m. i31a ran at about 7/min on 2 labs until 9 m. Cost: 3-6 min per run. Class: **prompt.**
5. **Chest-fed blocks running dry, and overflow chests stealing iron.**
   - i30b went to 0 sci at 11-16 m when depot-stocked chests emptied before belts arrived (`14:32:57 "8 of 8 labs" starved`).
   - Overflow chests ate science iron in i30b (`14:30:24` added, found 26 min later at `14:56:31`) and in i30a (`13:47:14`).
   - Class: **model limitation.**
6. **Free trigger techs left late.** They are a third of the target.

   | run | oil-processing | steel-axe |
   |---|---|---|
   | i28 | **2.0 m** | 23.2 m |
   | i26 | 6.8 m | 29.7 m |
   | i31b | 7.2 m | 16.7 m |
   | i29 | 14.1 m | **11.1 m** |
   | i30b | 14.7 m | 34.1 m |
   | i31a | 15.9 m | 9.9 m |
   | i30a | 25.6 m | 33.7 m |

   - In i26 steel-axe was co-critical: 29.7 m, right after a steel column came up at 08:10:58.
   - Class: **prompt.** Nothing says that "craft 50 steel" means one furnace of steel now.
7. **Power and coal supply.**
   - i30a boilers ran dry 4 times between 3 and 21 m. The coal drills were electric and fed by the same boilers (`13:16:10 claude-3: "chicken-and-egg"`).
   - In i31b nobody measured coal made vs used until the foreman caught it at 27.3 m ("Coal produced is 21/min"). Science fell from 85 to about 45/min for 28-33 m.
   - Class: **model limitation** (fuel was treated as a routing job, not a rate).

### Per-run storyline (short)

- **i26 (30 m).**
  - What went right: hand-fed labs at 3 m, a quick lane fix at 8-9 m, and the cheap tech set.
  - What hurt: the lab cap from 13 to 29 m at about 27/min, which was the worst steady throughput of any run.
- **i29 (34 m).**
  - Iron corner fixed at 1.5 m, depot iron hand-stocked (1200 plates), the earliest lab-cap diagnosis (16 m), and a circuit block at 09:11:26 that raised circuits from 40 to 107/min.
  - Brownout at 5-6 m. Coal on the ore lane at 9-11 m was buffered by the depot.
- **i31b (35 m, foreman).**
  - Corner fixed at 4.8 m. The foreman's task at 17.0 m ("Second lab-row-6 … 6 labs use only 12/min") took labs to 12 and science to 85/min by 24 m.
  - Losses: 2 labs removed at 10 m on the foreman's "shed load" advice (labs stayed at 6 until 18 m), and coal starvation at 28-33 m.
- **i31a (45 m, foreman).**
  - 2 labs until 9 m, the iron corner unfixed until 20.1 m, and a red-limited plateau at 16-31 m. During that plateau claude-1 built blue blocks with the foreman's approval while the foreman sat silent from 22.5 to 31.2 m (`REVIEW_EVERY` was 600 s then).
- **i30b (46 m).**
  - 19 labs by 22 m but only about 40/min: supply-bound. The coal-on-ore jam took about 15 min. Research queue churn at `14:39:12` replaced a cheap queue with plastics, AC and chem.
- **i30a (49 m).**
  - claude-1 tore down a working red-science intake built by claude-2 (`13:14:22`, force_pickup), which ran into a tree-blocked copper belt tile and a copper-jammed red lane. Red was at 0/min from 14 to 23 m, and science hit 0 at 18 m.
  - Lab cap until 37 m. Oil-processing only at 25.6 m. Research clutter: solar, railway, circuit-network and concrete queued at 13:21:46, then removed.
- **i28 (59 m).**
  - Startup 0-10 m, then green at 0 for 14-21 m (lane mix-up), and sci 0 at 27-28 m and 34-35 m (the green circuit feed belt was "never connected", `09:13:36`).
  - From 38.2 m on there was no agent (M1); labs starved from 40 to 47 m and nobody responded.
  - On its pre-quota rate (about 23 packs/min) it would have finished around 52-53 min, so the quota cost it about 6-7 min. It was the slowest run anyway.

## 2. Where agent time goes

| run | model thinking | act | wait | between turns |
|---|---|---|---|---|
| i26 | 53-71% | 23-28% | 5-19% | ≤1% |
| i29 | 49-71% | 12-46% | 4-14% | ≤1% |
| i31a | 46-65% | 20-37% | **14-26%** | ≤1% |
| i31b | 49-62% | 21-35% | **12-16%** | ≤1% |
| i30a | 65-74% | 18-24% | 7-8% | 0-4% |
| i30b | 56-58% | 25-28% | 12-16% | 1-3% |
| i28 | 42-48% | 17-21% | 6-9% | **29%** |

- **Model latency is the largest bucket.** Runs make 693-986 tool calls in total, at a median of 2.9-3.6 s per gap and a mean of 4.7-6.4 s; p90 is 7-16 s per agent. **41-45% of all calls are observation calls** (look, map, inspect, find, production, techs, recipes, designs, board, marks), against 33-41% act or stamp. Map, look and inspect make up 57% of all tool-output characters (look averages 3.6k characters per call).
- **i28's 29% "between turns" is entirely the session limit plus exponential backoff** (`crew/agent.py:308-312`: `delay = min(60 * 2 ** (error_streak - 1), 1800)`). Each agent slept 60+120+240+480 s and then started a 960 s sleep that the bench cut off at 59 min.
  - The SDK reports the limit as a `ResultMessage` with `is_error` and subtype `success`. The harness logs `turn error (success)` and never parses "resets 12:40pm".
  - Nothing aborts or flags the run.
  - It was not caused by turn budgets (`max_turns_per_hour=120` was never reached), idle mode, or context resets.
- **Step cap.** `MAX_STEPS_PER_TURN=60` (`backends.py:28`) ends a turn every 7-15 min (about 70-90 tool uses, since parallel calls count once per step). It resumes immediately with "(continue)". That costs ≤0.5 min per agent per run. This is fine.
- **Context resets.** These fire when the average context per step goes above 80k (`agent.py:21`), typically after turn 2 (about 20 min in) at 92-145k per step. After a reset an agent needs a median of about 33 s (range 6-136 s) before its first act. That is small in time, but turn-2 costs are 2-3x turn-1 costs because of the context growth.
- **Wait.** In the no-lead runs, waits are mostly walks (`move` jobs) and "watch the effect" waits of 60-75 s.
  - In the foreman runs the extra wait is **hand-crafting for off-target builds**: i31a claude-1 spent 7.8 min waiting on crafts of asm2, labs, fast inserters and pipes, and i31a claude-3 spent 5.5 min (`craft pipe 150 → wait 60 ×4` for the 280-tile lake pipeline).
  - Waiting for the foreman's answers was at most 0.9 min per worker. `ask_foreman` never blocks.

## 3. Failure census

Totals over 21 worker transcripts:
- **Failure rate:** 0.07-0.39 failed ops per act call (i30a claude-3 is the worst at 56 failures; 12 of them "nothing minable found").
- **Top failure messages:** "built by claudeN" ownership refusals 35, "nothing minable found" 26, "no path" 22, "route needs N belts but you have M" 19, "stuck" 15, pole routing "no route" 22.
- **Trees:** placements blocked by a tree or tree stump came to about 50 (16 belt, 11 pipe-to-ground, 7 drill, 6 pole, 6 refinery…). Trees are the largest single physical nuisance.

1. **Phantom teammates.** The save's `storage.built_by` names claude-4 and claude-5, who don't exist in these crews. 12 of the 35 ownership refusals (34%) were against them.
   - Agents address them in chat: `i26 07:44:56 claude-2: "claude-5: your coal belt dead-ended…"`.
   - They assign them tasks: `i28 08:46:18 post_task assignee "claude-4"`, and the same in `i29 08:40:16`.
   - They wait for their consent: `i29 08:57:14 "@claude-4 … I'll go ahead in ~5 min unless you object"`, about 4 min of hesitation.
   - Class: **scenario/harness.**
2. **Alert noise.**
   - `FUEL: 32 furnaces/drills are out of fuel (e.g. [gps=74,69]…)` repeats every 5 min in every run (7-12 times), mostly about the same dead, mined-out burner pairs (`crew/orchestrator.py:315`).
   - The crafting nag "(your crafting queue is idle: queue something useful…)" (`crew/tools.py:203`) appears in **47-91 tool results per agent**, about 25% of all results.
   - Class: **tool design.**
3. **The production rate is read as a shortage.** "Copper 80/min" was taken for a supply problem while the furnaces were `full_output`. This happened in i26 (`08:12:34`), i29 (`09:04:05`), i30a (`13:23:11`), i30b (`15:00:11`) and i31a (foreman #7, #15, reversed after 89 s). Each cost a trip or a task. Class: **tool design.** `production` doesn't say "demand-limited".
4. **Lanes are invisible.** `mod/claude-crew/scripts/observe.lua:118-123` sums both lanes' items into one belt-group `items` map. Agents can't see that red and green, or coal and ore, share a lane until something stalls. That is behind every lane bug in section 1. Class: **tool design.**
5. **Conflicts and duplicated work.**
   - **i28 iron column 2:** claude-1 and claude-2 both built it (`08:55:15-08:56:42`; "my build_ghosts also built part of your column-2 ghosts").
   - **i28 belt assembler:** claude-3's belt assembler made 742 belts and ate about 50 iron/min that science needed (`08:53:51`).
   - **i30a intake:** claude-1 tore down claude-2's freshly built intake (see section 1).
   - **i30b drills:** claude-2 picked up claude-3's drills to make room for coal.
   - **i26 coal belt:** claude-2 rerouted claude-3's coal belt onto the copper belt (`07:44:56`).
   - **Research queue:** all 3 agents queued research in the first 15 s of i26.
   - **Classes:** the conflicts are **prompt/coordination**. The `connect` "would feed into claudeN's belt" guard (10 refusals) and the ownership guard prevented worse.
6. **Error messages that waste calls.**
   - `mine: nothing minable found near X,Y` reports the character's position, not the target. In `i30a 13:13:26-29` claude-3 got 8 of these in 3 s.
   - "route needs N transport-belt but you have M" (19 times) happens because `connect` does not craft.
   - Class: **tool design.** The `build line` controller now crafts and fetches, which should remove most of these.

## 4. The characterless foreman (i31a, i31b)

- **Questions.**
  - 28 asks: 18 in i31a and 10 in i31b.
  - Replies took 4-37 s (median about 11 s), batched for 12 s (`BATCH_WAIT`, `crew/foreman.py`).
  - 47 and 35 replies in total, of which 23 and 21 were unsolicited pushes.
  - 27 `report` calls, which wake nobody. The foreman acted on them 1.7-7.7 min later.
- **Answer quality.**

  | run | helpful | approvals / neutral | harmful or wrong |
  |---|---|---|---|
  | i31a | 6 | 6 rubber-stamp "Approved"/"Yes" for in-domain work (the prompt says not to ask) | 6 |
  | i31b | 7 | 2 neutral | 1 |

  Helpful answers gave exact tiles, sourced materials from full_output machines, or stopped wasted work (`i31b #8: "that field is the only coal within 300 tiles. Don't build a new 220-belt line"`; `i31a 13:43:23: "Stop clearing trees. The iron fix … is YOUR job"`).

  Harmful or wrong answers:
  - `i31a 13:01:53` accepted "false alarm" on the iron corner.
  - `13:06:48` misdiagnosed iron as smelter capacity.
  - `13:15:12 "Approved: build the mall … Then start the blue blocks"`, while red was at 12/min.
  - `13:28:49 "Blue science is now the critical path"`.
  - Copper sent south at 13:41:45 and recalled 89 s later.
  - `i31b 13:53:45 "To shed load … pick up the old duplicate science assemblers"`, after which claude-1 mined 6 assemblers **and 2 labs** (labs 8→6 at 10 m).
- **Its own decisions.**
  - It moved chemical-science-pack to the front (i31a at 15.9 m, i31b at 7.2 m), with plastics, AC, sulfur and chem ahead of rs1, EED-1 and toolbelt: **about 1250 packs** vs 660 for the cheap set. The roadmap had 3 of 7 goals in the blue chain.
  - Board tasks: 11 and 14 posted, 7 and 8 done, all marked done by assertion (no done_when yet).
  - **Best calls:** the i31b second lab row (17.0 m) and the coal emergency (27.3 m), plus firm domain splits.
  - **Worst calls:** the blue-chain push, which took claude-3 off onto a 280-tile pipeline; the 9-minute silence in i31a; and a power ownership flip-flop within 2 min.
- **Did it help?**
  - **Time:** mixed (35 and 45 min). On work done, i31b ties i29 as the best (25.1 min to 600 packs). i31a is mid-pack.
  - **Cost:** true run cost was $19.9 and $26.2, against $16.8-30.6 for the no-lead runs. The foreman itself is about $2.
  - **Wait:** the higher worker wait (14-26%) is not waiting on the foreman. It is hand-crafting for the builds the foreman approved.
  - **Net:** cheap and fast arbitration that is worth keeping. Its strategy needs guardrails, and it must not approve "permission" asks in bulk.

## 5. Keep vs fix

**Keep:**
- Hand-feeding the existing labs in minute 1 (i26).
- Stamping proven science and lab designs.
- An early, measured lab-cap diagnosis (i29 at 16 m, i31b foreman at 17 m).
- Sourcing from full_output machines and depot chests.
- The non-blocking `ask_foreman` with short, specific replies.
- The teammate guards (`connect` join guard, ownership guard). They stopped several worse conflicts.
- The SCIENCE STARVED alert. It was followed up within 1-2 min in most runs.
- Splitting domains so that every worker owns a resource (iron, copper or power) and reports in numbers.

**Anti-patterns:**
- Building new instead of feeding what exists.
- Tearing down a teammate's working line.
- Putting coal on ore lanes.
- Overflow chests on the main science belt.
- Reading consumption as production capacity.
- Off-target builds (blue chain, mall, long pipelines) while labs are capped.
- Research queue churn.
- About 45% observation calls.
- 60-75 s "watch" waits while the crafting queue is empty.

## Ranked fixes for the next setup: characterless Opus foreman, board tasks with done_when (held 2 min), Sonnet worker characters with `build`

1. **Make the benchmark honest before comparing anything** (harness/scenario).
   - Fix the cost bug: use the per-turn delta of `total_cost_usd` (`crew/backends.py:113`), or reset a baseline each session. Re-derive `orch.record_spend`.
   - Detect "session limit" or "resets <time>" in the turn text or error. Mark the run invalid and stop it, don't back off (`crew/agent.py:308-312`, `experiments/run_matrix.py`). Add i28 to `invalid_runs.txt`.
   - Score s3-research-rush on `science_packs_used`, time to N packs, or a fixed tech list, not "+6 any techs" (`experiments/scenarios/…s3-research-rush`).
   - Run at most 1 Opus run at a time on the subscription, or 2 with Sonnet workers.
2. **Foreman research policy** (prompt, `crew/foreman.py` SYSTEM).
   - "Research is the clock: rank the queue by packs needed for the goal. Trigger techs first: power a pumpjack on crude in the first 5 min, and smelt 50 steel. Don't reorder toward blue science until labs exceed 12 and supply holds."
   - Show packs per tech in `techs` output to the foreman, already sorted.
   - This would have saved about 10-12 min in i30a, i30b, i31a and i31b (section 0, M3).
3. **First-tasks template for the foreman** (prompt and done_when).
   - Post these 4 tasks at t=0, each with a game-checked done_when:
     - (a) existing labs researching: `labs_working ≥ 2`
     - (b) iron reaching the base: `rate iron-plate ≥ X` at the science area
     - (c) power: `no boiler no_fuel`
     - (d) labs: `labs ≥ 12` with `science consumed ≥ 40/min` held 2 min
   - The 2-minute hold catches the "chest-fed block runs dry" failure (i30b, 11-16 m).
   - A task like (d) would have moved the lab scale-up from 29-37 m to about 15 m in i26, i30a and i31a.
4. **Lab utilisation in vitals and done_when** (tool design: `crew/tools.py` vitals_line and the `[base]` line).
   - Report "labs N working, research rate X units/min, lab-bound / pack-bound", plus pack made vs used.
   - Add done_when check kinds `labs_bound=false` and `consumed rate ≥ X`. Without this, nobody detected the lab cap until 16-36 min.
5. **Per-lane belt contents** (tool design: `mod/claude-crew/scripts/observe.lua:118-123`, `inspect`/`look`).
   - Report `left: {...} right: {...}` per belt group, and flag "mixed lane" (two item types on one lane, or coal on an ore or pack belt).
   - Have `build line` refuse to side-load onto a lane that already carries another item unless join=true, and print which lane the cargo lands on.
   - This targets the bug class that cost i30b about 15 min and i28 about 10.
6. **Production says why** (tool design: `production`/`diagnose` in `crew/late_tools.py:40`).
   - Mark items as `demand-limited (producers full_output)` vs `supply-limited`. The current numbers are misread in 5 of 7 runs.
   - Make `diagnose` the worker's first call for any shortage. The foreman already has it, and Sonnet workers need it more.
7. **Clean up the stage save and the alerts** (scenario: stage-s3 build, `crew/orchestrator.py:300-320`).
   - Clear `storage.built_by` for builders outside the crew, or map them to "previous crew", so builds aren't guarded.
   - Fix or keep the (71,-25) corner trap deliberately, but document it.
   - Exclude `no_minable_resources` drills, and burner pairs whose ore is gone, from FUEL. Report each alert only when the count changes.
   - Drop the crafting-queue nag (`crew/tools.py:203`) or show it at most once per 5 min.
8. **Foreman guardrails** (prompt and harness, `crew/foreman.py`).
   - "Never approve removing labs or science assemblers. In-domain 'may I' questions get 'yes, don't ask again'." Count rubber-stamp approvals in the worker health line.
   - Keep `REVIEW_EVERY=300` (i31a went silent for 9 min at 600). Also wake the foreman when the vitals show sci/min down 30% or labs starved, not only on a timer.
   - Act on `report`s that contain "fixed / done / blocked" within 1 batch, since they currently take 1.7-7.7 min.
   - Require a measured check before a diagnosis: "a backed-up source with an empty destination belt means a break; walk the line" as a stock heuristic.
9. **Sonnet workers with `build`** (tool design: `crew/late_tools.py:109`, `crew/controller.py`).
   - `build line` and `build stamp` should auto-mark trees and rocks in the zone or path for removal before laying ghosts. Trees caused about 50 failed ops, and the controller only clears entities already `to_be_deconstructed` (`orders.lua:34`).
   - `mine` failures should name the target coordinates.
   - Sonnet will need step-level tasks: the foreman should post coordinates plus a design name, and the worker should call `build` once.
10. **Cut observation churn** (tool design and prompt).
    - Look, map and inspect are 57% of tool output. Offer a compact `look` (counts and statuses only) by default, and reserve full `map` for planning.
    - Lower the context reset threshold, or reset mid-turn at 60k per step. Turn-2 costs run 2-3x turn-1 (`crew/agent.py:21`).
11. **Starting-state prompt line** (prompt, `crew/prompt.py` Momentum):
    > "Before building anything new, get the existing labs researching from stock in your first minute (insert packs by hand), then automate."

    Only i26 did this, and it was the only run with science above 0 at 3 min.
12. **Effort setting.** Don't expect effort=medium to buy speed. Per-step latency was unchanged (5.7 s mean). Re-test only after fixes 1-3 make runs comparable, with at least 3 repeats per arm.
