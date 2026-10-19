# Order system (round 17) log analysis: why 0 techs in 45 minutes

Runs: `experiments/runs/20261018-190724-s3-research-rush-orders-opus-haiku-i47` (i47) and `...-i48` (i48), plus the
14-min shakedown (`scratchpad/orders-shake`). Code as run: commit `19987cd` (`crew/actor.py`, `crew/orders.py`,
`crew/controller.py`, `crew/foreman.py`, `mod/claude-crew/scripts/orders.lua`, `jobs.lua`). Comparison runs:
`20261018-074139-...-go-now-noadvisor-i26` (i26) and `20261018-134429-...-foreman-opus-i31` (i31).

## Summary

The order system never got the labs running. Science-pack consumption was zero in 19 of 44 one-minute samples (i47)
and 30 of 44 (i48). The player crews had only 2 zero samples each. At the 30-minute mark the order runs had used
55 and 28 packs, against 647 (i26) and 914 (i31).

The main causes:
- **Fixing the old base piece by piece.** The coordinator worked through the fragile s3 base one fault at a time. In
  that time the player crews hand-fed the labs (first packs consumed at 2-3 min), took the two free trigger techs
  (oil-processing at about 7 min, steel-axe) and stamped a fresh lab and science block within 5 min.
- **Done-checks that pass for a moment.** A `working` or base-wide `rate` check is true for an instant. It passed on
  hand-fed stopgaps and then regressed. This happened after 4 of 6 lab checks, 7 of 11 boiler checks and 4 of 4
  copper checks.
- **Plan errors and tool traps.** About 45% of 100 orders were refuel or fuel-logistics work. 29 orders were
  cancelled, 14 of them for coordinator spec errors.

The "$25 per run" figure is a harness accounting bug. The Claude Code backend sums a cumulative session cost, so
each run really cost about $4.7 (more in §4).

Classification legend: **[harness]** harness bug · **[tool]** tool design · **[prompt]** prompt/instructions ·
**[model]** model limitation · **[scenario]** fragility of the s3 save.

---

## 1. Timeline of each run

### Starting state (stage `stage-s3-steel-oil-ready`, the same for both runs)

From `result.json` `summary_start` and the first alerts:

- **Base size.** Game minute 106. 20 techs researched, with no research queued. 2 labs, 2 boilers, 4 steam engines,
  30 burner drills, 18 electric drills, 37 stone furnaces and 8 assembler-1s.
- **Output.** Iron 205/min was produced but not reaching the base. Copper was 0/min.
- **Alerts at 19:08:30 (i47).**
  - `POWER RISK: 1 boiler(s) out of fuel at [gps=-31.5,-43]`
  - `FUEL: 32 furnaces/drills are out of fuel`
  - `LABS IDLE: nothing is being researched`
- **Alert at 19:09:30 (i47).** `SCIENCE STARVED: 2 of 2 labs are missing science packs ... 3 science assembler(s) lack
  ingredients`.

Latent defects found during the runs [scenario]:
- **Boiler deadlock.** The boilers are fed by an electric inserter, so once power drops they can't be refuelled. i48
  19:17:53 foreman: "boilers out of fuel, and their feed inserters are electric (deadlock)". i47 19:20:07 says the
  same.
- **Iron belt dead end.** The iron belt corner at (71.5,-25.5) faces into nothing. It was fixed by i47 #6, and again
  in i48 by #33 (19:35:39 claude-3: "dead-ended at (71.5,-25.5), which was facing north into nothing").
- **Coal mine stalls.** Coal drills output into iron chests that fill up and stop. i48 19:28:50: "The electric drills
  there drop coal into iron chests that are now full".
- **Hand-fed burners.** The copper and iron burner fields only get coal when someone carries it.
- **Broken lab feed.** The labs sit 2 tiles apart with a one-way inserter (i47 #12). The red assembler's output
  inserter is reversed (i47 19:30:06).
- **No circuits.** Nothing makes circuits, so green science stops (i47 19:13:56).

### i47 (2666 s, 57 orders: 37 done, 17 cancelled, 3 active)

| Time (min) | Events | Packs used (from 180) |
|---|---|---|
| 0-2 | Foreman surveys (35 tool calls in turn 1). Queues `research-speed-1` and `electric-energy-distribution-1` at 19:08:34. Its first `chemical-science-pack` attempt failed at 19:08:11: "needs oil-processing first, a trigger tech". Orders #1-#6 go out: refuel boilers, coal mine and iron field; restart copper; copper belt; iron corner. | 180 |
| 2-10 | Copper reaches 44/min and iron 182/min, but the labs stay starved. #7 (red: gears have no iron) and #8 (green: no circuits) stall. Coal belt #9 to the boilers fails: "no route found within search limit". At 19:15:30 POWER RISK: both boilers are out again (#11). | 184 at 10.1 min (first consumption) |
| 10-24 | Trickle research of 1-8 packs/min. Power goes out at 19:19:30 (`BROWNOUT: 63 machines`) and again at 19:23:42 (#23 EMERGENCY). Iron collapses to 2/min (#19). Copper drops to 0 at 19:29. The red-science-5 block is stamped at 19:22 (#22) but has no inputs (#27, 434 s). | 230 at 24 min |
| 24-36 | Zero consumption from 19:31:34 to 19:36:30 and again from 19:38:31 to 19:42:32. A third power outage at 19:34:30 (`BROWNOUT: 95 machines`). The emergency order #35 sat ready behind a zone overlap (19:35:49 "cancelled zone overlapped #34; reissue"), and its replacement #36 overlapped another zone. #34 "red output to the labs" passed via 3 hand-crafted green packs. 19:42:09 foreman: "Order #34 ... was marked done, but the packs aren't getting there". | 236 at 35 min |
| 36-44 | The first new labs and science blocks, at 19:43:54. The stamps overlapped because of an anchor misunderstanding (19:45:39 foreman: "the stamp tool positions a design from about its top-left corner, not its centre as I'd assumed"). Labs reach 8 at 40 min, with 1 of 8 working. | 287 at 44.4 min (research-speed-1 at about 53%) |

### i48 (2667 s, 43 orders: 28 done, 12 cancelled, 3 active)

| Time (min) | Events | Packs used |
|---|---|---|
| 0-6 | Research queued at 19:07:44. #3 "Jumpstart red science from depot stock" got the first packs into the labs by 6 min, the best early move of either order run. #2 stamps a copper smelting column at the ore-belt end (copper 210/min by 19:14). The three connect orders #4, #5 and #6 are all cancelled with `coal is not placeable` / `copper-plate is not placeable`. | 188 at 6 min |
| 6-12 | Red block (#7) and gear block (#12) are stamped in 9-11 s each. Packs trickle in from the hand-fed jumpstart. | 208 at 12 min |
| 12-38 | **27 minutes at zero.** Packs are flat at 208 from 19:18:34 to 19:44:33, even though the lab row (#20) brought labs to 8 at 19:21. The causes, in the foreman's own successive diagnoses: brownout at 19:17:30 (`120 machines`, boiler deadlock); copper smelter out of coal (19:19:31, 19:24:08); coal field outputs into full chests (19:28:50); iron belt dead end (19:34:11); copper furnaces out of coal again (19:36:19); boiler out again at 19:36:30. The fault that blocked the labs directly was the red-pack belt from connect #21. That order was marked done in 0 s with "routed 6 tiles; placing 6 transport-belt from 35.5,-13.5 to 36.5,-17.5" and ended facing into nothing. Found at 19:42:09 by claude-3: "I rotated belt (36.5,-17.5) to face south. It was a dead end". Red and green were being made at 20 and 30 per min from 19:37 while the labs got nothing. A further POWER RISK came at 19:41:30: a burner inserter that actor claude-3 placed in #35 faced backwards. | 208 |
| 38-44 | 6 of 8 labs work at 19-23 packs/min. 6 more labs are stamped (14 total), and the pumpjack order (#43) is finally issued at 19:51:23. At the end coal was at 18/min (`summary_end`), so the next outage was already coming. | 352 (research-speed-1 at about 84%) |

### Where the 45 minutes went

Actor time by order category (started → done, blocked or cancelled) for 3 actors × 44.5 min = 133.5 actor-minutes:

| Category | i47 orders / actor-min / model calls | i48 orders / actor-min / model calls |
|---|---|---|
| Fuel and power emergencies and coal logistics (hand refuel, coal belts, boiler feed) | 28 (12 cancelled) / 36.7 / 25 | 20 (8 cancelled) / 45.2 / 23 |
| Plate logistics (copper and iron belts, smelter fixes) | 6 / 9.6 / 6 | 8 / 21.5 / 10 |
| Building new production (stamps: science blocks, lab rows, smelting) | 7 / 6.3 / 3 | 5 / 4.1 / 0 |
| Science hookup (feeding blocks, packs into labs) | 14 / 33.9 / 19 | 8 / 16.1 / 9 |
| Power expansion (new boiler block) | 2 / 1.7 / 1 | 1 / 8.3 / 2 |
| Oil (pumpjack) | 0 | 1 / 0.6 / 1 |
| **Idle (no order)** | **45.4 (34%)** | **37.7 (28%)** |

- Fuel and power was the largest single sink in both runs: 42% (i47) and 47% (i48) of the busy actor time.
- Building new production took only 6-10 min of actor time. The controller stamps fast (see §6), so the problem was
  not build speed; new production was simply ordered late. i47's first new lab came at 37 min; the player crews
  had 8 labs by 3-5 min.
- Cancelled orders (29) used about 34 actor-min in total. They also triggered 11 coordinator turns that were mostly
  spec repair.
- Idle time includes the coordinator's thinking latency. The scheduler sent "actors idle with no ready orders"
  7 times per run.

### Why research never advanced (ranked)

1. **The labs got no packs for most of the run.** 19 and 30 of 44 minutes had zero consumption, from power outages
   (4 in i47, 3 in i48) and feed defects. [scenario] + [tool] + [prompt]
2. **No early lab or science capacity.** i47 had 2 labs until minute 37. Two labs cap research-speed-1 (100 units ×
   30 s, red+green) at 8 packs/min, which is at least 25 minutes; the observed i47 maximum was exactly 8/min. i26
   finished the same tech at 12.8 min with 8 labs, all fed by 5 min. [prompt]/[model]
3. **The free techs were never taken.**
   - oil-processing only needs a powered pumpjack. It was roadmap item 6 of 7 and was ordered at 19:51 (i48) or
     never (i47).
   - steel-axe only needs 50 steel crafted. The i48 foreman saw `"steel-axe","unlock_by":"craft-item steel-plate x50"`
     at 19:07:45 and never ordered it.
   - These two were 2 of the 6 techs in both i26 and i31. [prompt]/[model]
4. **The runs were stopped while research-speed-1 was at 53% and 84%.** i48 would probably have recorded 1 tech a
   few minutes later. That is still far from +6.

---

## 2. Taxonomy of cancelled and blocked orders (29 cancelled, primary cause each)

| Root cause | Class | i47 | i48 | Total | Evidence |
|---|---|---|---|---|---|
| Impossible zone check (min > entities in zone) | [prompt]/[model]; [tool] (no auto-clamp) | #2, #19, #49 | – | 3 | #2: "asks for 8 but there are only 6 in the zone"; cancelled as "work done; 6/6 drills working". The shakedown lost 4-6 of 12 orders the same way. |
| Cargo given as the connect item | [tool] (ambiguous `item`) / [prompt] | #38 | #4, #5, #6 | 4 | "connect failed: coal is not placeable" (i48 19:13:01). In #38 the actor laid the belt itself with `transport-belt`; the controller then re-ran the original plan, failed, and the order was cancelled anyway [harness]. |
| Belt already existed (stale world view) | [model] (coordinator) | #21, #25 | #16 | 3 | i47 19:24:36 claude-1: "Coal already reaches the furnace feed: the coal line from the mine runs along y=58..." |
| Huge or overlapping zones blocked an emergency | [tool] (scheduler zone exclusivity) / [prompt] | #35, #36 | – | 2 | #34's zone was [-26,-42,47,-12], 73×30 tiles. Power was out while #35 waited: "19:35:49 cancelled zone overlapped #34". |
| Stamp anchor misunderstanding (overlapping stamps) | [tool] | #50 | – | 1 (+3 knock-on: #48 cleanup, #51 rebuild, #54 cascade) | #50: "stuck with 21 ghosts left ... blocked by something not marked for removal". The green block ended with 5 of 8 assemblers. |
| Check measured something outside the order's control | [prompt] | – | #11 | 1 | i48 19:22:26 claude-2: "check still fails because the copper smelter has no fuel, which is outside this order". |
| Route search limit (long belts, 190-220 tiles) | [tool] | #9 | #10 | 2 | "can't route transport-belt: no route found within search limit". Split by hand into legs (i47 #13-15, i48 #14/#19). |
| Teammate-belt guard (`join` missing) | [tool]/[prompt] | – | #15, #27 | 2 | "this line would feed into claude-3's belt at -26.5,-19.5; pick another end point, or pass join=true". |
| Dependency cascade (`after=` on a cancelled order) | [tool] (scheduler semantics) | #10, #20, #42, #54 | #17 | 5 | "a dependency failed or was cancelled". Each then cost a coordinator re-issue turn. |
| Actor stalled (stateless Haiku) | [model] | #7, #33 | #22 | 3 | i48 #22: claude-1 hand-mined `mine coal count=150` and waited about 8 min (19:24:04-19:32) instead of using the full coal chests. i47 #33: "stalled 4+ min on a tree". |
| Re-spec or preempted by the coordinator | [prompt]/[model] | #41 | #18, #34 | 3 | "broaden to red+green"; "replaced by #24 with owner"; "Power emergency takes priority". |
| **Total** | | **17** | **12** | **29** | |

By class (primary cause, 29 total):
- Coordinator spec or judgement errors: 14 (impossible checks 3, cargo item 4, stale view 3, zones 2, out-of-scope
  check 1, plus 1 stamp-anchor error that was partly the tool's fault).
- Tool or scheduler design: 9 (route limit 2, join guard 2, dependency cascade 5).
- Actor model stalls: 3.
- Coordinator re-plans: 3.

Other failure types beyond cancellations:
- **Controller exceptions escalated to an actor model call.** There were 43 "model call: exception" calls (i47 19,
  i48 24). In 15 orders the exception followed "the work is finished but the check fails", which means the check
  caught a premature "done" (§6).
- **Actor-introduced bugs.**
  - i48 #35: claude-3 placed a burner inserter at (-33.5,-43.5) facing backwards. That caused the 19:41:30 POWER RISK
    and needed order #38 to fix.
  - i48 #21: the connect's last tile faced into nothing. The tool picked the direction; no done check covered it.
- **`error_max_turns` on actor calls.** 9 of 91 calls (i47 5, i48 4) hit the cap. ACTOR_STEPS=14 was too few for
  "find, walk, fix" tasks; calls took up to 28 steps.

---

## 3. Did the done checks reflect reality?

The checks in this version are all instantaneous, evaluated in `orders.lua` `CHECKS`:
- `working` reads `entity.status == working` at one tick.
- `rate` is base-wide production over the last minute.

`actor._verify` retried every 15 s for up to 2 min, but it stopped at the first pass. Nothing watched a done order
afterwards.

**Recurrence after a passed check:**

| Check family | Passed | Regressed afterwards | Time to regression |
|---|---|---|---|
| Labs working (`working lab`) | 6 (i47 #12, #28, #34, #43; i48 #3, #36) | 4 (i47 #12, #28, #34; i48 #3) | Packs flat within 1 min (#12), about 1.5 min (#28), under 1 min (#34), 6 min (i48 #3). Only i48 #36 held to the end, and i47 #43 held 4 min at 8/min before dropping to 4/min. |
| Boilers working | 11 (i47 #1, #11, #17, #23, #24, #37; i48 #1, #13, #35, #38, #40) | 7 power failures followed | 6, 3.5, 2.3, 10 (#23 and #24 together) / 6.5, 16.6, 3.5 min |
| Copper rate (i47) | 4 (#3 44/min, #16 48, #31 56, #40 75) | 4 | Copper back at 0 by 19:18:47, 19:29:59, 19:35:14; at 19:50 the #40 belt was "empty at its end" (#56) |
| Iron or burner refuel | i47 #5, #26; i48 #32, #37 | at least 3 | i47 iron went 182 → 2/min by 19:21 (#19); i48 needed #42 for the same x=74 furnaces |

Repeated-fix counts:
- i47 issued 8 boiler-fuel orders and 9 burner-refuel orders.
- i48 issued 5 boiler orders and 5 burner-refuel orders.

**Hand-feeds satisfied checks while the automation part was skipped.** The actors said so themselves in 9 done
orders:
- i47 #12: "the fix is a hand-feed, not the layout the order asked for".
- i47 #31: "the self-feed part isn't built, so it will need refueling again in about 15 minutes".
- i47 #34: "hand-crafted 3 logistic (green) packs ... loaded 2 into the lab". The order was a belt from the red block
  to the labs.
- i47 #43: "hand-inserted 24 into each lab ... I did not build the belt".
- i47 #44: "The belt fix is still open".
- i47 #53: "hand-fed 40 copper ... the copper belt is still unfixed".
- i48 #8: "running on 100 hand-fed iron plates ... not a real supply".
- i48 #37: emptied 1,450 plates from 16 full furnaces by hand.
- i48 #40: "west head of the boiler belt ... had no feeder".

That is 9 of 65 done orders, about 14%. The actors were honest in chat. The system read only the check.

**Connect orders were marked done before the belt existed.** [harness] `H.connect` in `jobs.lua` only *queues*
`place` jobs and returns `ok("routed N tiles; placing N ...")`. The controller treats that as done:
- i47 #13 was done in 0 s with "routed 71 tiles; placing 71".
- i48 #21 and #28 were done in 0 s, and #31 in 1 s.

Connect orders also defaulted to no check (`done_when=[]`), so 11 of 12 done connects were "check passed []". Nothing
verified that items moved:
- The i47 coal belt (#13-15) was done at 19:18. Power went out at 19:23 and again at 19:34. At 19:35:14 the foreman
  found "The coal belt to the boilers is empty at the mine end".

**Would the next setup's 2-minute hold have helped?** It would have rejected 3 of the 4 lab regressions (#12, #28,
#34) and none of the 7 boiler regressions, which came 2.3-16.6 min later. Hand-fed buffers outlast 2 min: 24 packs
per lab at 4 packs/min is 6 min, and 50 coal per boiler is about 2-8 min depending on load. A hold catches flicker,
not stopgaps.

**A better check existed and went unused.** `rate` with `"kind": "used"` (consumption) is implemented in
`orders.lua` but appeared in neither prompt. It was used 0 times. For "labs fed",
`{"rate": {"item": "automation-science-pack", "kind": "used", "min": N}}` measures the outcome directly.

---

## 4. How the coordinator spent its time and money

**Cost correction [harness].** `ClaudeCodeBackend.turn` sets `stats.cost_usd = msg.total_cost_usd`
(`crew/backends.py:113`; still the same at HEAD). For a persistent `ClaudeSDKClient` session that value is cumulative,
and `Foreman._loop` and `Agent` then add it up turn after turn.

Evidence:
- The foreman's "turn cost" rose monotonically in 28 of 28 turns (i47), 20 of 20 (i48) and 16 of 16 (i31). It
  dropped only right after each `reset`.
- i47 turn 18 shows $1.37 for 1 step and 143k input tokens, which is about $9.6 per million: impossible with
  caching. The next turn, after a reset, shows $0.14 for 7 steps.

Real costs from the per-session deltas:

| Run | Reported | Real foreman | Actors | Real total |
|---|---|---|---|---|
| i47 | $24.84 | $4.36 (28 turns, mean $0.16 per turn) | $0.42 (50 Haiku calls) | **about $4.8** |
| i48 | $25.45 | $4.35 (20 turns, mean $0.22 per turn) | $0.33 (41 calls) | **about $4.7** |
| i31 (player + foreman) | $34.61 | $1.75 (reported $10.24) | workers $24.4 | **about $26.1** |
| shakedown | (doc says $3.18) | $1.21 (cumulative series 0.30 → 1.21) | about $0.12 | **about $1.3** |

Worker turns in the player runs are long and mostly one per session, so they are barely affected. i26's $22.2 stands.
Inflated spend also feeds `orch.record_spend`, so an hourly `usd_per_hour` cap would trip about 5× too early.

**Turns and context:**

| | i47 | i48 |
|---|---|---|
| Foreman turns | 28 (2 resets) | 20 (1 reset) |
| Time in turns | 16.8 min (38% of run) | 13.4 min (30% of run) |
| Tool calls | 189: order 57, notes 25, inspect 22, diagnose 20, cancel_order 17, map 14, reply 10 | 176: order 43, inspect 25, diagnose 18, map 17, notes 17, cancel_order 12 |
| Context per request | 12k → 77k tokens over 8 turns, reset; 10k → 72k, reset; 10k → 52k | 11k → 96k over 11 turns, reset; 13k → 47k |
| What triggered turns | alerts 11, blocked or dependency-failed orders 7, actor chat reports 5, idle nudges 3, human 1, request done 1 | alerts 9, blocked 4, idle 4, chat 2, human 1 |

- The coordinator was cheap and fast to react. POWER RISK at 19:15:30 led to order #11 at 19:15:48, done at
  19:15:57.
- It was reactive, though. 11 of 28 turns started from an alert, and 7 went to repairing its own malformed or blocked
  orders.

**Symptoms or causes?** The diagnoses were mostly right. The foreman named the electric-inserter deadlock (i48
19:17:53), the drills outputting into full chests (19:28:50), the iron dead end (19:34:11), the reversed burner
inserter (19:41:15) and the lab dead end (19:38:59). It also issued automation orders about as often as hand-fix
orders: about 13 fuel-automation orders against 14 hand refuels in i47, and 12 against 8 in i48.

The automation still didn't stick:
- Connects laid belts that nothing loaded at the source and nothing checked (§3).
- Actors did the hand-feed half of mixed orders and skipped the automation half (§3).
- The check vocabulary could not express "coal arrives at the boilers" or "packs arrive at the labs".

The strategic error was different. The coordinator spent its first 35 minutes repairing the old 2-lab base, one
fault per turn. It did not build fresh science capacity and take the free techs first, as both player crews did.

---

## 5. What the player-style Opus crews did differently (i26, i31)

Both runs reached +6 techs, at 30.0 min (i26) and 35.0 min (i31).

| | i26 (3 Opus players) | i31 (3 Opus players + Opus foreman) | i47 / i48 (orders) |
|---|---|---|---|
| Research queued | within 25 s, by all three agents | 13:44:40 | 19:08:34 / 19:07:44 |
| Boiler refuelled | 15 s (07:41:59) | 13:44:49 | 2 min (#1, 19:09:46) / 19:09:04 |
| First packs consumed | 3.0 min, from a hand-insert into the labs at 07:44:09 ("Hand-feeding labs to restart research now") | 2.0 min, from a hand-insert plus 20 hand-crafted red packs | 10.1 min / 6.0 min |
| 8 labs | 5.0 min | 3.0 min | 40 min / 14 min (unfed until 38 min) |
| oil-processing (pumpjack) | 6.8 min | 7.2 min | never / ordered at 44 min |
| steel-axe (craft 50 steel) | 29.7 min | 16.7 min | never |
| Packs used at 10/20/30 min | 123 / 377 / 647 | 73 / 289 / 914 | 4/37/55 · 26/28/28 |
| Zero-consumption minutes | 2 of 30 | 2 of 35 | 19 of 44 / 30 of 44 |

What worked for them:
1. **Directness.** The lead hand-crafted packs and inserted them into the labs within 1-3 min, while someone else
   carried coal to the boiler.
2. **New capacity instead of repair.** A 6-lab red+green block was laid at 07:43:16 (138 ghosts) in i26, and was
   building by 13:46 in i31.
3. **Free techs first.** Two of six techs in each run cost no packs.
4. **Replacing fragile infrastructure.** i26 replaced the dead burners with electric drills rather than refuelling
   them. i31 refuelled all 32 burners in one act, about 36 inserts, then built 4 boilers and 8 engines by 13 min.

Their tech choice also mattered. i26 took cheap techs (research-speed-1, electric-energy-distribution-1, radar,
toolbelt) at about 160 packs each. i31's foreman pushed the blue path (about 310 packs per tech) and needed 12 labs.

---

## 6. What worked in the order system (keep)

- **Controller stamps (deterministic, no model).** 11 of 13 stamp orders finished with 0 model calls:
  - i47 #22: red-science-5, "built 51 in 16s".
  - i47 #30: gear-circuit block, 50 in 20 s.
  - i48 #25: green-science-6, 87 in 37 s.
  - i48 #20: lab-row-6, 27 in 27 s.

  The 2 failures came from stamp *placement* (anchor and overlap, shore orientation), not execution. This is the
  `build` macro the next setup keeps.
- **Game-evaluated checks caught false "done" claims.** "The work is finished but the check fails" fired on 15
  orders (i47 8, i48 7). 11 of those later passed after an actor fix. It showed up after actor claims like "the lab
  check should pass now".
- **Impossible checks failed fast** (added in `3796588`). Orders were blocked in 21-33 s (#2, #19) instead of
  burning retries.
- **Actors were cheap and honest.** 91 Haiku calls cost $0.75 across both runs. Their chat summaries named exactly
  what was left undone ("not a real supply", "self-feed part isn't built").
- **Actors corrected bad plans.** Each of the 4 cargo-as-item connects was diagnosed by the actor ("`connect` needs
  a belt item, so I've corrected it to `transport-belt`"). They also crafted their own belt shortfalls: i48 #14, #19
  and #23 went from "route needs 124 transport-belt but you have 21" to done.
- **The coordinator's diagnosis with `diagnose`, `inspect` and `map`.** Its root-cause statements were accurate
  (see §4).
- **Fast scheduler dispatch.** Typically 0-3 s from ready to dispatched. The exceptions were zone overlaps (#35,
  #36) and orders queued behind busy actors (i48 #18 waited 231 s).
- **Order history lines** (`"19:35:49 cancelled zone overlapped #34; reissue"`). Per-item history made this
  analysis possible; board tasks should keep the same format.

---

## 7. Ranked fixes and lessons for the next setup

The next setup: a characterless Opus foreman, board tasks with optional `done_when` that must hold 2 min, and Sonnet
workers with a `build` macro.

1. **Fix cost accounting before comparing runs.** [harness] In `crew/backends.py:113` (`ClaudeCodeBackend.turn`),
   keep the previous `total_cost_usd` per client, report `cost_usd = total - prev`, and reset `prev` in `reset()`.
   Re-derive past results:
   - order runs: about $4.7, not $25;
   - i31: about $26, not $34.6.

   Otherwise the foreman looks 5× more expensive than it is, and any `usd_per_hour` cap trips early
   (`orch.record_spend`).
2. **Give the foreman an opening doctrine for "advance research", and ideally put it in the scenario's first board
   tasks.** [prompt] In `crew/foreman.py` SYSTEM:
   1. Queue research at once. Prefer cheap techs and trigger techs: the `techs` output should mark trigger techs as
      "free" and show unit time and total pack cost (`crew/tools.py:t_techs`, `mod/.../observe.lua:428`).
   2. A worker hand-feeds the labs (craft red, take green from chests) within 2 min.
   3. Within 5 min, one worker `build`s a fresh 6-lab row plus red-5 and green-6 next to known-good supply.
   4. Place a pumpjack on crude oil (oil-processing) and craft 50 steel (steel-axe) early.
   5. Fix the old chain only if it is one fault away.

   These were the four differences between +6 and 0 techs.
3. **Make checks measure delivery, not a snapshot.** [tool] In `mod/claude-crew/scripts/orders.lua` CHECKS and the
   `post_task` description in `crew/tools.py`:
   - Document `rate kind=used`. It was never used in 100 orders.
   - Prefer it for "labs fed" (`automation-science-pack used ≥ N/min`) and fuel ("coal used ≥ N").
   - Add a `fed` check: an entity's fuel or input inventory is not falling over the hold window, or a belt tile at
     x,y carries an item at ≥ N/min.
   - Make `working` mean "working in ≥ X% of samples over the hold", not "at the sample instant".
4. **Hold plus regression watch, not just a hold.** [harness] In `crew/orchestrator.py:_task_checks`:
   - The 2-min hold would have caught 3 of 4 lab regressions but none of 7 boiler regressions.
   - Keep evaluating done tasks for about 15 min and reopen them to the same owner with "regressed after N min" if
     the check fails.
   - Don't start the hold while the owner is still hand-inserting into entities the check counts. Track recent
     `insert` ops by workers inside the task zone. That closes the 9 cases where a hand-feed stood in for automation.
   - Sample every 10 s rather than 20 s. A 2-min hold with 20-s sampling is only 6 samples.
5. **Make `build line` honest.** [harness]+[tool] In `crew/controller.py:connect` and `mod/.../jobs.lua` `H.connect`
   (lines 850-852):
   - Return done only after the queued `place` jobs finish. Today the result says "placing N" and the order closed in
     0 s.
   - Report what the last tile feeds into ("dead end facing north into nothing", as in i48 #21, which starved 8 labs
     for about 22 min).
   - Report whether anything loads the first tile ("no inserter or drill puts items on this belt", as in the i47
     coal belt and i48 #40).

   HEAD already maps cargo names to belts (4 cancellations here) and splits long routes (2 cancellations), but
   `build` still reports "done" for queued placements.
6. **Auto-fix impossible checks instead of blocking.** [tool] When `working`/`exists` asks for more than the zone
   holds, clamp `min` to the zone total, or switch to `scope: base` if the base has enough, and tell the foreman.
   HEAD's `_task_checks` still sets `blocked`. This cost 3 orders and 3 coordinator turns in i47 and 4-6 of 12 orders
   in the shakedown.
7. **One anchor convention for stamp and paste, and return the footprint.** [tool] HEAD's `build` doc says stamp x,y
   is the top-left but paste x,y is the centre (`crew/late_tools.py:t_build`). The i47 overlap (#45/#46 →
   #48/#50/#51/#54) came from exactly this. Return the bbox and refuse overlaps with existing entities before laying
   ghosts. `designs` should show each design's size.
8. **Treat the s3 save's power as task zero.** [scenario]+[prompt] Power failed 3-4 times per run. Standard fix for
   the electric-inserter boiler deadlock: a burner inserter (correctly oriented; i48 #35 placed one backwards), a
   coal belt *loaded at the mine*, and extra boilers. i31 built 4 boilers and 8 engines by 13 min. Add the
   electric-inserter deadlock as a named alert in the vitals line, so the foreman doesn't rediscover it every run.
9. **Don't route judgement through stateless small-model calls.** [model] Haiku with a fresh context and a 14-step
   cap stalled 3 times, hit `max_turns` 8 times, hand-mined coal for about 8 min next to full chests, and introduced a
   reversed inserter. Sonnet workers with persistent context fix most of this. Keep the deterministic refuel path:
   `build kind=ghosts zone=Z` refuels every burner in Z from chests (`controller.fulfill` low_fuel branch). Document
   it as the way to "refuel a field", so a worker never hand-walks coal for minutes.
10. **Keep task zones small and never let zones block emergencies.** [tool] The scheduler is gone at HEAD, but board
    zones still exist. Zones should cover a build, not the base. Power and lab-starvation tasks must not wait on a
    zone claim; i47 #35 waited while power was out.
11. **Don't chain tasks with hard dependencies.** [tool] `after=` caused 5 cascade cancellations, each needing a
    foreman turn. Prefer one task with an outcome check, and let the worker sequence the steps.
12. **Context is not the bottleneck.** The foreman's real cost was $0.16-0.22 per turn with resets at about 80k tokens
    per request. Spend that budget on a periodic "are the labs consuming?" review rather than alert-driven turns:
    11 of 28 turns in i47 started from an alert.
