# Sonnet workers: what went wrong (log analysis)

Analysis of the 2026-10-17/18 Sonnet sessions, written for the next setup: a characterless Opus foreman, Sonnet
workers, board tasks with game-evaluated `done_when`, and the `build` macro. Read-only analysis; no code was changed.

## Summary

In the live session (00:45:18–01:04:15, four Sonnet workers under an Opus foreman with a character), the Sonnet
workers spent **68% of their wall time outside any turn** (asleep in mode idle), 16% with the character executing
actions, 6% in `wait` and only 9% thinking. Almost none of that idle time came from turn budgets or an empty board.
**31% was harness restarts** that left everyone asleep with no wake event. **34% was idle the workers chose
themselves**: they set `mode=idle` after finishing one sub-step, in 4 of 6 cases while still holding a claimed,
unfinished task. That ran into the foreman being stuck for 541 s inside a synchronous architect consult. Once
concrete step-level tasks arrived (01:00:55), the same four workers placed about 13x as many entities per minute
(95 placements plus about 270 belts and poles in 3.3 min). Execution speed was never the bottleneck. The
Sonnet-specific weaknesses were orientation: inserters were right on the first try 1/13 times when Sonnet chose the
direction, against 22/22 when the spec spelled out pickup and drop. The other was misreading two tool outputs that
are still misleading in the current code (`connect` says OK before it builds; `inspect` hides inserter direction).
Most of the idle problem is now partly fixed (idle sweep, characterless foreman), but not the root cause: the
worker prompt and the status tool still tell Sonnet to go to sleep when it finishes something.

## Data and windows

| Window | Models | Source |
|---|---|---|
| e2e1–e2e5, 10-17 22:48–23:45 | 1–2 Sonnet agents, no lead (claude-1 posted tasks as a peer) | `logs/e2e*.log`, transcripts (e2e4/e2e5 only) |
| live, 10-18 00:27–00:45:13 | all Opus (claude-3/4/5 spawned at 00:35:34 as `claude-opus-5-5`) | `live.log` 1–620 (contrast only) |
| **live, 10-18 00:45:18–01:04:15** | **claude-1 Opus foreman with a character; claude-2..5 Sonnet**; architect (Opus) from 00:51:40 | `live.log` 620–1376 |
| live, 01:04:47–01:13:44 | 3 Opus (claude-2/3 switched live at 01:04:04; claude-4/5 off duty at 01:04:10/15) | contrast |
| live, 10:26–12:43 | Opus workers, later harness (idle sweep, pipelining, characterless foreman from 11:09) | contrast |

The brief said Sonnet ran from about 00:41. The harness says otherwise. The startup lines at 00:35:34
(`live.log:129-131`) show claude-3/4/5 as `claude-opus-5-5`, and the 00:45:18 restart (`live.log:626-629`) is the
first time they show as `claude-sonnet-5-5`. Per-turn cost agrees. claude-3's turn ending 00:41:35 cost $0.95 per
million input tokens; its turn ending 00:54:01 cost $0.48. claude-5's numbers are $0.82 and $0.40. So the Sonnet
live window is about 19 minutes. There are 4 workers, 13 turns and 185 tool calls; the samples are small, so treat
the percentages as indicative.

## 1. What the Sonnet workers did with their time

Time split per agent, computed from the transcripts (prompt-to-turn intervals; tool time measured from each call to
its result; model time is turn time minus tool time; the 00:51:36 restart cuts the turns it killed):

| Agent (live, Sonnet) | Span | Turns | Model thinking | Acting (`act`) | `wait` | Out of turn (idle) |
|---|---|---|---|---|---|---|
| claude-2 | 1126 s | 3 | 123 s (11%) | 218 s (19%) | 60 s (5%) | **724 s (64%)** |
| claude-3 | 1126 s | 2 | 84 s (7%) | 143 s (13%) | 38 s (3%) | **861 s (76%)** |
| claude-4 | 1132 s | 4 | 60 s (5%) | 223 s (20%) | 13 s (1%) | **836 s (74%)** |
| claude-5 | 1137 s | 4 | 154 s (14%) | 160 s (14%) | 170 s (15%) | **653 s (57%)** |
| **All 4** | 4521 s | 13 | 422 s (9%) | 743 s (16%) | 281 s (6%) | **3074 s (68%)** |
| claude-1 (Opus foreman) | 1126 s | 3 | 226 s (20%) | 11 s (1%) | 31 s (3%) + **consult 541 s (48%)** | 315 s (28%) |

Contrast:
- **Opus workers, same harness and base (00:35–00:45):** out of turn 10%, 47%, 10% and 28% (24% on average); acting
  30–70%.
- **Sonnet, no lead (e2e4):** claude-1 was out of turn 1% of the time and claude-2 33%; in e2e5 the figures were
  34% and 42%.
- **Opus with the later harness (10:26–12:43):** out of turn 0–21%.

The character was standing still for at least 78% of the Sonnet window, which is what the in-game Crew panel
showed. It prints "idle" whenever the character has no job (`mod/claude-crew/scripts/panel.lua:22`), and that
includes thinking time.

### Where "idle waiting for direction" came from

The 3074 worker-seconds out of turn break down like this:

| Source | Worker-seconds | Share of worker time | Root cause |
|---|---|---|---|
| Harness restarts left everyone asleep | 1388 | 31% | harness bug |
| Workers chose idle after a sub-step | 1539 | 34% | prompt/instructions + model tendency |
| Human sent claude-4/5 off duty | 144 | 3% | legitimate |

**Restarts.** The crew restarted at 00:45:13 (to switch to Sonnet) and at 00:51:36 (to add the architect).
- Each restart started fresh sessions and sent **no wake event**. The first wakes came by accident: claude-1 from
  `RESEARCH FINISHED: logistics` at 00:48:38; claude-4 and claude-5 from claude-1's chat at 00:50:16; claude-3 only
  from the human at 00:52:40, after **443 s asleep**.
- The 00:51:36 restart also killed claude-2's and claude-5's in-flight turns
  (`turn error (error_during_execution)`, `live.log:734-735`).
- The human noticed: "Hey @all guys you may have had a little memory lapse there… claude-1 i don't know if you
  remember but ur the foreman." (otterplex, 00:52:20)

**Self-chosen idle.** Every turn ended with `status mode=idle`, and the tool replied
`status set; mode=idle (you'll sleep until someone needs you)`. With no idle sweep, they slept until pinged.

| Agent | Idle from | Duration | Status text | What it still held |
|---|---|---|---|---|
| claude-4 | 00:50:43 | 117 s | "coal run done; idle" | #8 claimed: "I haven't started the iron supply for the belt line (task #8). I'm idle now." |
| claude-4 | 00:53:48 | 350 s | "Delivered 300 iron plates… Ready for next haul." | #8 (ongoing: "Keep both above 50") |
| claude-3 | 00:54:01 | 419 s | "Lab 2 built; red science supply is bottleneck" | #6 half done: "Not started: Stockpiling stone and building a furnace line… I've added a note to the task and set myself idle." |
| claude-2 | 00:54:07 | 419 s | "Green sci running; needs restock" | #11: "I'm out of materials, so someone needs to top up both input chests… I've set my status to idle." |
| claude-5 | 00:56:03 | 215 s | "Coal drills done; idle for next task" | nothing: "Someone needs to haul it to the boiler fuel chest… I've set my status to idle and have no task queued." |
| claude-2 | 01:03:44 | 19 s+ | "Trunk done; idle" | #14 just finished |

Across every Sonnet session, **18 of 23 `status` calls set idle (78%)**; two of those were the off-duty order. Seven named their own next step and
still slept:
- "copper up; next: coal drills, then lab" (claude-1, 23:34:51)
- "Power done; next: coal for boiler" (claude-2, 23:44:02)
- "copper smelting online; next: more drills" (claude-1, e2e3 23:15:22)

Opus under the same harness set idle 6 times out of 13 (46%).

**Why Sonnet slept.** The instructions contradict each other, and Sonnet follows the most literal, most recent one.
- On one side, the prompt says "Never sit idle waiting on someone else while a goal is open… Go idle only when the
  human's goal is done".
- On the other side, the same prompt says "Each turn: … report. Then set status (working/idle)", the auto-continue
  nudge says "…act, and set status idle when done", and the status tool says "'idle' = sleep until someone needs
  you".
- The goal rule at the time (now `GOAL_WAIT`) said "everyone else waits for that plan (you'll be pinged)". The
  router added "(follow-up) … Check the board for the foreman's plan and your task" to every @all message.
- Sonnet also frames each turn as a request-and-response episode: it ended all 8 completed turns with a
  user-facing markdown report averaging 733 characters, which nobody reads, and then slept.

**The foreman was the second half of the stall.** claude-1 consulted the architect synchronously from 00:52:37 to
01:01:38 (one 541-s turn, 23 tool calls, $1.69). No new work reached the board until the architect posted #12–#17
at 01:00:55–01:01:18. Each idle worker started within 2–5 s of its assignment.

**Ruled out:**
- **Turn budgets:** no "budget reached" lines in any Sonnet window. The autonomy cap (40, `agent.py`) was never
  reached, because Sonnet almost never chose `working`.
- **An empty board:** that only applies to claude-5. The other three were holding claimed tasks.

**Effect when direction arrived.** From 00:45:18 to 01:00:54 (15.6 min) the four workers made 35 single
placements. From 01:00:55 to 01:04:15 (3.3 min) they made 95 single placements plus about 270 belts and poles via
`connect`. The earlier window also had about 99 `connect` tiles, but most were claude-5's duplicate routes (section
2d), so they're left out of the comparison.

## 2. Concrete Sonnet failure modes (counted)

### 2a. Inserter and belt orientation (tool design, then model limitation)

- **When Sonnet chose the direction:** 1 of 13 inserters was right on the first try.
  - claude-2, green science at 00:50:24: 0 of 8. It placed `direction=east` at (-1.5,-37.5) to move items east;
    the tool reads `direction` as the pickup side.
  - claude-2, base taps at 01:03:05: 1 of 4.
  - claude-3, lab feed at 00:53:17: 0 of 1.
- **When the spec said where to pick up and drop:** 22 of 22 were right. claude-3's IRON-2 column at 01:03:37 came
  from a spec reading "Input inserters x=75.5 facing EAST (they pick up from the ore belt at 76.5 and drop into the
  furnace)".
- **The spec can contradict itself.** The architect wrote for claude-2 "inserter (-19.5,-28.5) facing SOUTH into the
  gear assembler (-19.5,-30.5)", but the assembler is north of the inserter. claude-2 placed it north, rotated it
  south, back north, then south again (01:03:05–01:03:33).
- **24 `rotate` operations in 19 minutes,** 21 of them by claude-2. Opus under the same harness made 0 in the 18
  minutes before. Opus with the later harness made 73 over 138 inserters and 552 belts, so the convention costs both
  models; Sonnet is just worse at it.
- **`rotate reverse=true` was used as a 180° flip.** claude-2 did this on 8 inserters at 00:50:32. In the mod it
  turns 90° counter-clockwise (`e.rotate{reverse=true}`), so every inserter ended up sideways:
  `#757 rotate: OK rotated inserter to north`. It took a second batch with explicit directions at 00:53:28 to fix
  them. The green science line sat unproductive from 00:50:24 to 00:53:28.
- **Flip-flopping back to the wrong state.** At 00:53:23 claude-3 corrected its lab inserter to `east`, which was
  right. It then saw `waiting_for_space_in_destination`, rotated it back to `west` (wrong) at 00:53:43, and
  reported: "I checked the direction and it points the right way now."
- claude-2's own verdict was: "Inserter directions behaved inconsistently when I placed them, so I rotated three of
  them by hand." (01:03:44)
- **A belt corner was wrong.** claude-4 built IRON-1 as two `connect` legs, (99.5,56.5)→(76.5,56.5) and
  (76.5,55.5)→(76.5,25.5), with no `end_direction`. The corner tile kept facing west, and the whole iron column
  starved. Opus claude-2 found and fixed it at 01:07:25: "A corner belt at [gps=76,56] faced the wrong way and
  jammed it; all 11 furnaces are smelting again."

### 2b. Going idle, giving up, or asking instead of acting (prompt, then model)

- Idle statuses: 18 of 23, covered in section 1.
- Seven requests broadcast to nobody in particular:
  - "someone with plates please top them up" (claude-2, 00:54:03)
  - "If anyone has spare electric-mining-drills, drop them" (claude-5, 01:01:27)
  - "does anyone know where it is?" (claude-1, e2e4 23:36:06)
  - "Idle now, ping me for iron or refuel runs" (claude-2, 23:37:23)
  - "The boiler has only 10 coal, so someone needs to feed it." (claude-2, 23:44:01)
  - "waiting on stone from claude-2 [idle]" (claude-1, e2e3 23:16:10)
  - "claude-1, send stone if you can" (claude-2, 23:26:25)
- Giving up: "I can't search for water with my tools; I'd need to spot '~' on a map. Idle now" (claude-2, e2e4
  23:37:23). The tool really couldn't find water then (fixed in `20ff10e`), but `map` was available and Sonnet
  didn't use it.

### 2c. Hand-feeding instead of automating (mostly scenario and foreman plans)

- **Volume.** In the live window Sonnet made 44 fuel inserts, 26 other inserts and 74 takes, against 143
  placements.
- **claude-4 spent its whole session refuelling the burner array and hauling plates** (30 fuel inserts, 29 takes;
  status "Ready for next haul"). At 00:52:47 it took 100 coal back out of the boiler fuel chest it had filled at
  00:50:41 for claude-1, to refuel the drills.
- **claude-3 took inputs from a production machine.** It took 12 copper out of the red-science assembler
  (`take x=-20.5 y=-33.5`, 00:52:49) to craft a lab, then reported "red science supply is bottleneck".
- e2e4: "Hand-feeding 4 extra furnaces at [gps=73,67] to bootstrap plates" (claude-2, 23:29:44) and "Fuel upkeep is
  the manual burden; I'll run refuel rounds" (23:34:52).
- **Caveat.** Opus workers under the same harness hand-fed more: 91 fuel inserts in 10 minutes. The base was a
  burner base, and 3 of the foreman's 5 tasks prescribed manual hauling (section 3). The Sonnet-specific part is
  that it never turned repeated hauling into automation on its own. claude-4 wrote "electric drills would be
  better" in a task note at 00:53:44, then went idle.

### 2d. Misreading tool output (tool design and harness bug)

- **The `connect` loop (claude-5, 00:53:04–00:54:54).** `connect` returned
  `OK routed 196 tiles; placing 34 small-electric-pole`. Then `wait 60` returned "no jobs running", and `find`
  showed only 4 poles, so Sonnet concluded it had failed. It re-issued `connect` five more times. Two of those
  failed with "start tile … is blocked" by a pole its own earlier `connect` had just placed, two queued duplicate
  routes, and one was skipped behind a failed `move`. It also mined its own chest and pole along the way. About
  105 s passed before the character walked the line.
- **Status read as direction.** claude-3 took `waiting_for_space_in_destination` to mean "wrong direction" (2a).
- **Done claimed without checking:**
  - claude-4: "IRON-1 built" (01:02:37), with the broken corner.
  - claude-2: "Task #14 done… I haven't tested it with plates" (01:03:44).
  - claude-5: "That should be about 120 coal/min… I didn't measure it" (00:56:03).

  These were honest, but nothing checked them.
- **A false warning.** In e2e1 claude-1 moved a working drill twice after a "WARNING: no resource under it" and
  concluded "Map coordinates seem offset" (22:49:24). That warning was a harness bug, since fixed.

### 2e. Repeating failed actions (mostly fixed harness and tools; some model)

- **Live failure rate:** 19 real failures in 72 `act` calls (26%), which skipped 52 queued actions. Opus workers
  under the same harness had 2 in 55, on different and simpler tasks.
- **Identical retries:**
  - claude-1 repeated the same `move` 3 times (`stuck at 8.7,86.6`, e2e4 23:34:20/27/33) before mining the trees.
  - claude-2 repeated a `move` twice (e2e3 23:17:24/29).
  - Two agents tried to insert coal into wood-fuelled burners in 4 batches (e2e4 23:26:51–23:32:39). The fix was a
    fuel swap.
  - claude-5 re-issued `connect` 5 times after the first one succeeded.
  - claude-5 hit "route needs 41 transport-belt but you have 37" twice (01:02:45/49).

### 2f. Conflicts with teammates and the human (harness and plan)

- **The off-duty chests.** At 00:59:38 the human told claude-4 and claude-5 to put everything in chests and say
  where. 77–93 s later the foreman/architect assigned them #12 and #15. They accepted, and at 01:00:57–01:01:27
  **four workers raced for those same chests**: claude-4 took 200 iron and 33 copper, claude-3 took 158 iron plus
  inserters, poles and a furnace, and claude-2 and claude-5 got "nothing to take".
- **Then the off-duty workers left.** claude-4 and claude-5 went off duty mid-build (01:04:10/15). CU-2 (claude-4)
  was never built, so the copper ore belt dead-ended. Next turn Opus found "Copper drills at y103.5 x4-20 are all
  waiting_for_space" (claude-1 task at 01:05:37).
- **Competing plans (e2e3).** Both Sonnets posted plans within 7 s (23:12:48–57), and claude-1 had to say "Ignore my
  earlier assignment."

## 3. The Opus foreman (claude-1) and the architect

**Bottleneck.**
- 48% of claude-1's window was inside one consult and 28% was out of turn.
- When it acted, it did chores: 37 fuel inserts and 14 takes, such as "Picked up 200 coal… On my way to refuel the
  iron array" (01:03:10).
- It posted one task itself in the window: #11, green science, at 00:48:59. It handed out boiler duty in chat rather
  than on the board: "claude-4 and claude-5 will top it up with coal" (00:50:16).
- There were no worker-to-foreman questions in this window (no `ask_foreman` tool yet). Workers broadcast needs into
  chat instead (2b).

**Plan quality.** The architect's #12–#17 were the best direction the Sonnet workers got all night: exact
coordinates, pickup and drop sides, counts, a materials list, "critical path" notes, and reserved rows. Sonnet built
each one in about 3 minutes. The flaws:
1. They took 9 minutes, and the foreman was blocked the whole time.
2. They cost $1.69, more than all four Sonnet workers' recorded turns combined (about $1.24).
3. 2 of the 6 went to workers the human had sent off duty 77 s earlier.
4. They formed two cross-worker dependency chains (IRON-1→2→3 and CU-1→2→3) with nobody sequencing them.
5. Some "facing" wording contradicted itself.
6. None had checks.

The foreman's own tasks often prescribed hand-feeding (3 of 5): #8 "Haul plates to belt-line input chests… Keep both
above 50", #10 "drills… outputting into" chests, and #11 "Feed iron plates/gears/circuits from a chest you stock".

**Chat volume is not the problem.** Over 19 minutes the Sonnet workers sent 14 chat messages (2,060 characters) and
claude-1 sent 8 (1,213). The Sonnet tool mix was 39% `act`, 38% observation, 18% talk and board, and 5% `wait`;
Opus workers under the same harness used more talk (26%). The real costs were the end-of-turn prose reports and
up to 12 lines of crew chatter pasted into each briefing (8 in claude-3's at 01:01:00).

## 4. Tool outputs and harness behaviours that misled Sonnet

The "Status now" column describes the current HEAD (`bb38fdc`).

| # | Behaviour | Evidence | Status now | Class |
|---|---|---|---|---|
| a | `direction` on an inserter means the **pickup** side ("inserters TAKE from the side they face"); models read it as "points toward the destination" | 1/13 first-try (2a) | **Open**: `crew/tools.py:74`, `crew/prompt.py` "Inserters take from the side they face", `crew/foreman.py:65` | tool design |
| b | `rotate reverse=true` turns 90° counter-clockwise, not 180° | 8 inserters turned sideways at 00:50:32 | **Open**: `mod/claude-crew/scripts/jobs.lua:540`, `crew/tools.py:52` | tool design |
| c | `inspect` doesn't show inserter direction, pickup or drop tiles, belt direction or `by`; it only shows status and energy | claude-3's flip-flop; Sonnet used `inspect` 31 times and `look` 19 times | **Open**: `mod/claude-crew/control.lua:249-279` (`look` has `from/to`, `observe.lua:42-44`) | tool design |
| d | `rotate` result is "rotated inserter to west", with no pickup or drop tiles (`place` does report them) | claude-2 and claude-3 couldn't confirm after rotating | **Open**: `jobs.lua:542` | tool design |
| e | `connect` returns OK once it has *queued* the placements. The spawned `place` jobs aren't tracked, so `wait` says "no jobs running", and placement failures after the OK are never reported | claude-5's loop (2d) | **Open, and worse**: `jobs.lua:846-853`; `t_wait` (`tools.py:241-265`) now adds "Your character is idle while you wait" while it's placing; `Controller.connect` (`crew/controller.py:249-289`) returns `done` before the last leg is placed | harness bug |
| f | `connect`'s last tile keeps the last step's direction unless `end_direction` is given, so two-leg routes break at the corner | claude-4's IRON-1 corner | **Open, now automated**: `controller.py:273` passes `end_direction` only on the final leg; split legs share the midpoint (`:284`), so the next leg's start slides to a neighbouring tile (`jobs.lua` `free_tile`). Likely corner gaps; matches the "long line routes still fail" known issue in `docs/architecture.md` (not verified in game) | harness bug |
| g | Crafting-queue nag on every result with ≥20 plates | 52 nags in 185 Sonnet calls, followed about 3 times | **Open**: `tools.py:201-203` | tool design |
| h | Status tool "'idle' = sleep until someone needs you", nudge "set status idle when done", prompt "Then set status (working/idle)" | 18/23 idle | **Open**: `tools.py` `t_status`, `crew/agent.py:349-350`, `prompt.py:12` | prompt/instructions |
| i | Goal rule "waits for that plan (you'll be pinged)" and the 20-s "(follow-up) … Check the board for the foreman's plan" | every @all at 00:36:30 and 00:52:40 | **Config-dependent**: `crew.toml` sets `foreman_first=false` (GOAL_GO), but the code default is still wait (`prompt.py:202`, `orchestrator.py:188`) | prompt/instructions |
| j | False "no resource under it" warning | e2e1 22:49:19–28 | Fixed | harness bug |
| k | Coal refused when wood is in the fuel slot | e2e4, 4 batches | Fixed (fuel swap, `20ff10e`) | tool design |
| l | No water search | e2e4 23:37:23 give-up | Fixed (`20ff10e`) | tool design |
| m | `connect` failed when a start or end tile was occupied | claude-5, 4 failures | Fixed (endpoint sliding, `402a779`) | tool design |

## 5. What Sonnet did well (keep these)

- **It executes precise specs fast.**
  - IRON-2: 11 furnaces, 22 inserters and 12 poles "built to spec", powered and fuelled in 3 minutes (claude-3,
    01:01:00–01:04:16).
  - The 143-belt trunk plus poles and taps took 2.6 minutes (claude-2).
  - In e2e5, steam power plus a lab researching automation took about 2.6 minutes with no help (23:40:43–23:43:19).
- **It is fast and cheap per step:** about 2.3 s of model time per tool call, against 3.1 s for Opus under the same
  harness. Turns cost $0.04–0.30; the four workers' recorded turns came to about $1.24.
- **It batches big action lists**, with 15–21 placements per `act`.
- **It recovers from many errors after one look:**
  - "Trees block. Mine nearby ones then retry." (claude-5, 01:04:02)
  - "Guessing is wasteful; use the map." (claude-5, 00:59:48)
  - "Direction is reversed; rotate it." (claude-3, one second after the `place` result showed the pickup and drop
    tiles)
- **It reports honestly,** with coordinates and caveats: "I haven't tested it with plates", "I didn't measure it".
  This is ideal input for `done_when` checks.
- **It follows humans immediately.** Both off-duty requests were done in 6–18 s with exact chest coordinates.
- **It uses background crafting when told to:** `craft inserter count=19 wait=False`,
  `craft electric-mining-drill count=7 wait=False`.

## 6. Which failures are fixed now, and which are open

| Failure | Later change | Verdict |
|---|---|---|
| No wake after a restart (31%) | Idle sweep (`2e4a608`): wakes a worker idle >90 s if `open_work` is non-empty (`orchestrator.py:215-232`) | **Mostly fixed.** Up to about 2 min lost per restart; no wake at all if there are no tasks, roadmap, ghosts or requests yet |
| Foreman blocked by the architect; foreman doing chores | Async per-asker consults, architect off by default, characterless foreman with `ask_foreman` returning at once | **Fixed** |
| Workers choosing idle after a sub-step (34%) | Prompt "Never wait for direction… call `work`"; idle sweep | **Partly.** The idle instructions (4h) are still there. The sweep re-wakes only after 90 s and then at most every 180 s (`orchestrator.py:223`), so a worker that idles after every short task still loses 1.5–3.5 min per cycle. Marking a `done_when` task done puts it in `verifying`; a Sonnet worker will then likely sleep until the check passes (2 min hold) |
| No new task when one finishes | Board checks wake the **worker** ("Pick your next work") | **Open.** `_tell_lead` notes the foreman with `wake=False` (`orchestrator.py:272-276`), so the foreman learns of finished, blocked or impossible tasks only at its next question or its 5-minute review (`foreman.py:73`) |
| Inserter and belt orientation | `stamp`/`designs` (validated in 4 rotations) and the `build` macro | **Fixed for standard sections** if the foreman hands out `build` plans. **Open** for custom glue (taps, lab chains, corners) and in `inspect`/`rotate` (4a–d) |
| `connect` misread | Endpoint sliding | **Open** (4e, 4f), and `build kind=line` inherits it |
| Unverified "done" | `done_when` must hold 2 min | **Fixed where tasks carry checks**; optional in `post_task` |
| Lost job results and long waits | `2495766` + 20-s cap on idle waits | **Fixed** (not a big Sonnet factor: `wait` was 6%) |
| Character idle while the model thinks | `act` defaults to `until_last` | Fixed (it helps Opus more, since Sonnet steps are short) |
| Science or fuel outages unnoticed | Alerts + vitals line | Fixed |
| Off-duty and human orders ignored by the plan | The foreman gets a note of chat addressed to workers (`orchestrator.py:176-177`) | **Open**: no availability state; the foreman can still assign; chests stocked for a human aren't protected |
| Cross-worker dependency chains | Order dependencies were removed in `bb38fdc` | **Open**: `Task` has no `after` field (`crew/board.py:12-26`) |
| Hand-feeding by plan | Foreman prompt "Fix causes, not symptoms" | **Partly** (prompt only) |
| Prompt load for Sonnet | — | **Worse**: the worker prompt now carries the late-game, marks, zones, `stamp`+`build_ghosts` and `build` paragraphs (`prompt.py:111-145`), with two different ways to build |

## Ranked fixes

These are ranked by expected gain for Sonnet workers under a characterless Opus foreman that hands out board tasks
with `done_when`, with workers using `build`.

1. **Don't let a worker sleep while it owns unfinished work.** (prompt/instructions + harness)
   - In `crew/agent.py:339-350`: if the worker owns a `claimed` task, or a `verifying` task whose check is failing,
     ignore `mode=idle` and queue `(continue) you own #N: <check state>. Keep going, or mark it blocked with what you
     need.`
   - In `crew/tools.py` `t_status`: refuse `idle` while the worker owns an open task, and say so.
   - Remove "set status idle when done" (`agent.py:350`) and "Then set status (working/idle)" (`prompt.py:12`).
     Make `working` the default for workers, and require `ask_foreman` or `report` before idling.
   - Targets the 34% self-idle; in 4 of 6 cases the worker held a claimed task.
2. **Close the "task done → next task" gap.** (harness)
   - Wake the foreman on task done, blocked or impossible-check, and when a worker goes idle with nothing owned:
     `fm.note(..., wake=True)` in `orchestrator.py:272-276`, plus a hook on `status idle`.
   - Let the foreman queue a **next** task per worker: a `queued` status, shown in the briefing as `[next task]`, and
     auto-claimed when the current one passes.
   - Drop `REVIEW_EVERY` (`foreman.py:73`) to about 90 s while any worker shows `[IDLE]`.
   - Without these, the foreman notices finished work only at its next question or its 5-minute review, which is
     claude-1's consult stall in a new form.
3. **Make `connect`/`line` report the truth.** (harness bug)
   - In `jobs.lua:846-853`, return the spawned job ids, or make `connect` a single job that ticks through its
     placements and finishes only when the last piece is down, listing skipped and failed tiles.
   - Track those ids in `pending_jobs` and in `Controller._do`.
   - Make `t_wait` (`tools.py:241-265`) check the mod queue before claiming "your character is idle".
   - In `Controller.connect` (`controller.py:249-289`), set each leg's `end_direction` toward the next leg's start,
     and don't share the midpoint tile between legs.
   - Add a smoke check: a two-leg line carries items end to end.
4. **Make orientation unambiguous.** (tool design)
   - Let `place` and `rotate` take `pickup=[x,y]`/`drop=[x,y]`, or `drop=<dir>`, for inserters, and derive the
     direction in the mod.
   - Make `rotate` results and `inspect` (`control.lua:249`) show `dir`, `from` and `to` for inserters, belt
     direction, and `by`.
   - Make `reverse=true` a 180° flip (`jobs.lua:540`), or remove it.
   - Change the foreman's and architect's wording rule (`foreman.py:65`) to "picks from X, drops into Y", never
     "facing".
   - Evidence: 1/13 vs 22/22 first-try rates, 24 rotations in 19 minutes, and one jammed iron line.
5. **Let the foreman make the spatial decisions and the workers execute.** (prompt + tool design)
   - Give `post_task` an optional `build` spec (kind/name/x/y/rotation/zone, or `line` from/to/item) shown to the
     worker as a ready call, and require `done_when` for assigned tasks. Default it to `ghosts_cleared` plus
     `working` in the zone (`tools.py` `t_post_task`, `board.py` `Task`).
   - In the foreman prompt (`foreman.py` SYSTEM), for Sonnet workers prefer "design + exact spot + check" over bare
     outcomes. Sonnet was excellent at executing specs and weak at choosing layouts and directions.
   - Give each worker an **end-to-end slice** (drills → column → trunk) instead of a three-worker chain, or add
     `after=[ids]` to `Task` with the board showing "waiting on #N".
6. **Slim and de-conflict the Sonnet worker prompt.** (prompt/instructions)
   - Build a model-specific `PARALLEL`: one build path (`build`), no late-game paragraph until bots exist, no
     `stamp`→`build_ghosts` duplicate (`prompt.py:111-145`).
   - Replace the end-of-turn prose report with a one-line `report` call.
   - Rate-limit the crafting nag to once per 5 minutes, or drop it (`tools.py:201-203`).
7. **Respect human availability and human stock.** (harness)
   - Add per-worker `available` state set by human chat ("off duty"); show it in the foreman's `[workers]` list, and
     have `post_task` refuse unavailable assignees.
   - Let `mark kind=reserved` (or "for <player>") make `take` refuse those chests unless a human asks.
   - Prevents the four-way chest race and the half-built IRON-1/CU-1 left when claude-4/5 went off duty.
8. **Resume cleanly after a restart.** (harness)
   - In `Orchestrator.start`, wake every worker once with `(resume) you own #N…` plus its notes, instead of waiting
     for the idle sweep or a human.
   - Prefer the live model switch (already supported, used at 01:04:04) over restarts.
9. **Flag hand-feeding in the health line.** (harness + prompt)
   - Count repeated `insert`/`take` of the same item into the same entity, or between the same chests; at 3 in 10
     minutes, append "automate this or ask the foreman" to the act result and show "hand-feeding" in the foreman's
     health line (`agent.py` `health_line`).
   - Sonnet noticed this itself ("electric drills would be better") but never acted on it.
10. **Measure Sonnet's specific losses.** Add to `experiments/digest.py`:
    - idle seconds while owning a task;
    - rotations per inserter placed;
    - `connect` re-issues within 60 s;
    - time from task done to the next assignment.

    Then run one benchmark with Sonnet workers before the next live session; there are none yet.

## Caveats

- **Small sample.** There are about 19 minutes and 185 calls of live Sonnet, plus two short e2e runs. The Opus
  contrast windows had different tasks, so the failure rates (26% vs 4% of acts) are not like-for-like.
- **What the stall percentages depend on.** They include two operator restarts and the human's off-duty order. Under
  the current harness the restart share would be about 2 minutes per restart, not 3.7–7.4 minutes.
- **Cost is approximate.** It counts only completed turns; turns killed by restarts aren't recorded.
- **One finding is inferred, not tested.** The leg-midpoint corner issue in 4f comes from reading the code, not from
  a run in the game.
