# Morning review: night of 2026-10-19

378 runs from 23:03 to 06:26: 15 train cycles plus a held-out check at each end. API-equivalent cost $115 of the $250 budget, with no usage-limit pauses. Train runs passed 360 of 370. The core didn't change during the night.

## Problems to review (indexed)

Core proposals come from the serfs' requests (sorted in the next section) and the failure counts. Each one lists its evidence. **None of these were fixed overnight.**

1. **No way to find items in storage.** `find` takes only entity names, so `find copper-plate` fails: 101 failures in 93 runs, the most common failure by runs. 198 debriefs ask "where is the stock". `Controller.source()` already searches chests and machine outputs for an item, but no tool exposes it. Proposal: `find item=<name>` over chest and machine contents.
2. **Belt lines don't fetch their own materials or say whether they joined.** "route needs N underground-belt" hit 57 times in 53 runs, plus 12 for `connect`. 63 debriefs ask for it. `Controller.connect` fetches only the belt item. The mod's `connect` now hand-crafts missing undergrounds (0.3.1), but `build line` fails first. The result doesn't say whether either end joined an existing belt. Proposal: fetch or craft every item before routing, and report "joined/not joined" for each end.
3. **Power is invisible.** 96 debriefs (requests 7 and 9). `inspect` shows `energy`, which is always 0 for poles. There's no network id, and build/stamp results say "done" for unpowered machines. The holdout `t-stamp-book` debrief found this on the first run of the night. A pole `connect` says "placed all" when the chain doesn't reach the network (6 runs). Proposal: powered/unpowered and network id on `inspect`, `place`, `build` and `stamp` results, and a warning in any result with unpowered machines.
4. **No base survey and no belt trace.** 116 debriefs (requests 4 and 8). The only scripts the serfs built tonight are both workarounds: `follow_belt` (3 versions) and `probe_col`. Later serfs used them 84 times. Proposal: promote a belt trace into the mod (where the line goes, where it breaks, what it carries), and a survey of ore patches, smelter columns and main belts. This is the survey tool from d2 #3.
5. **Thinking is 42% of all time (550 of 1323 min).** Looking itself costs seconds; its cost shows up as thinking about long results. `inspect` dumps every ore tile (46 debriefs ask for shorter output). Proposal: an `inspect` filter (skip resources by default) and shorter look results. Measure this as thinking time per call.
6. **Idle while checks hold: 13% of time (178 min).** Mostly the long tasks: 6.6 min per run on d2 and 8.5 min on f1 waiting with nothing running. Proposal: when the serf waits with nothing running and a goal is unmet, the wait result says what's still unmet and suggests the next step instead of sleeping.
7. **`build` says "paused, 0 ghosts left" when it's done.** 19 runs. `Controller.fulfill` checks the time limit before checking for remaining ghosts. Two-line fix.
8. **Small message fixes (misconceptions the core can head off).**
   - `look` ignores x,y (41 runs): honor it or say so.
   - Craft count is recipe runs and is silently capped (16 runs).
   - Inserter direction is the pickup side (37 runs).
   - Errors for calling an act op as a tool, or the reverse (17 runs).
   - `inspect` doesn't say whether an underground is an input or an output (5 runs).
9. **The agent layer barely grew.** In 378 runs: 2 scripts (both from one f1 run), 4 lessons, 3 designs, 0 playbooks, 0 friction notes. Serfs complained only when the debrief asked. Waste was flat across the 15 cycles (0.17–0.27), so there's no learning trend. Proposal (prompt, core): end every order with "save what you'd want next time" (a script, playbook or lesson), and point `friction` at the exact cases the debriefs raise.

## Test setup problems (not core; mine to fix or yours to decide)

1. **The short tests are too easy.** 10 of 13 short tests passed every run. They give little signal per dollar, and diversity is near zero on `d4-library`, `t-power-line` and `t-coal-boilers`. Proposal: drop repeats on saturated tests, make them harder (more distance, a broken piece to diagnose), and spend the saved budget on long tasks. Only $115 of $250 was used.
2. **The empty starting inventory is the biggest complaint (243 runs), plus 114 asking which chests are free.** Is fetching materials part of the skill we're testing? In a real base it is. Your call: give the micro tests a kit, or keep it realistic and label the supply chests.
3. **Micro tests run inside a stage base.** Its alerts, hand-fed boilers and science pull serfs off task (requests 5, 15 and 16). Two of the three `t-smelter-column` failures were the base's power dying. Proposal: run micro tests on an empty island, or mute alerts outside the test zone.
4. **Ops "not done yet" messages repeat without naming the item or place** (66 runs). That's the bench's wording. I'll fix it.
5. **Bench chat interrupts the serf's own scripts** ("stopped: a human said something": 4 failures in f1). Ops messages count as a human speaking. Scripts should only stop for real players.
6. **Fixed this morning:** the debrief capture missed or mislabeled about half the debriefs. They were recovered from transcripts; see decisions.md.

## Where the most time was lost

Thinking 42%, waiting on jobs 16%, idle 13%, hand building 11%, blueprint/line building 9%, walking 4%, failed calls 3%, crafting/fetching 2%. Failed calls cost little time directly. Their cost is the thinking around them: the 101 item-name `find` failures each start a search streak.

## Which tests produced the most diverse data

- **d2-science-steps:** 47 distinct failure kinds, 37 seen nowhere else, in only 4 runs (1 of 4 fully met). The best data per run: it's where survey, power and belt joins all come up together.
- **f1-feldspar-iron:** 22 kinds and 14 unique in 2 runs (0 of 2). A real 7,400/min base. Both serfs added furnaces or ore without reaching the target, and one built a 1,100-tile belt. It's also where the only scripts were born.
- **t-smelter-column:** 23 kinds and 13 unique. The best short test (27 of 30 passed).
- **t-brownout:** 22 kinds and 9 unique. The most `skill_run` use.
- **Lowest:** `d4-library` (0 failure kinds), `t-coal-boilers` (1), `t-power-line` (2), `t-stamp-book` (2).

## Held-out tasks, before vs after the night's library

All 4 passed both times. Cost went from $1.30 to $0.72 and calls from 131 to 95, with `t-circuit` taking 5 min before and 3 min after. None of the "after" runs used a script, so lessons and designs or plain variance explain it (n=1 per task). It's a hint, not a result.
