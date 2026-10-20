# Overnight 2026-10-19: serf requests, clustered and sorted

Source: `runs.jsonl` (378 runs; 377 have a debrief, all `debrief_source: transcript`; missing: `20261020-061027-t-inserter-mall-sonnet-i2`). For **124 runs**, the transcript debrief is only a pointer ("I've posted the debrief in chat"). For those, and for 91 runs where the earlier chat capture held extra debrief lines, I also used the chat-captured text from the previous extraction, but only when it reads as a debrief (it says debrief, most time, missing or confused). That leaves 162 runs on transcript text alone. Quotes marked † come from that chat text; the rest are verbatim from the current `runs.jsonl`. Clusters were tagged by regex over all 377 texts after a full read, so counts are ±10%. One run can appear in several clusters.

Sort rule (RuneScape Bench): most complaints are wrong. **real core friction** = a tool/mod gap or bug that justifies a core change. **misconception** = the core already does it; fix with a tool message or a prompt line. **agent-layer** = a helper the serf could script itself. **scenario artifact** = caused by the test setup.

## Summary

| # | Request (as the serf would put it) | Runs | Sort |
|---|---|---|---|
| 1 | Start me with a kit (poles, copper, inserters) or put materials near the job | 243 | scenario artifact |
| 2 | Tell me where shared stock is: list chest contents, find by item | 198 | real core friction |
| 3 | Tell me which chests/rigs are free supply and which are test fixtures | 114 | scenario artifact |
| 4 | A whole-base survey: what exists and what feeds what | 68 | agent-layer |
| 5 | Don't repeat ops messages, and name the item or place in them | 66 | scenario artifact |
| 6 | `build line`/`connect` should join existing belt ends, fetch its own undergrounds, and say when it didn't join | 63 | real core friction |
| 7 | Warn me when something I placed has no power, and show pole coverage | 50 | real core friction |
| 8 | Follow a belt to its end and report where it breaks | 48 | real core friction |
| 9 | Tell me whether a build is on the grid (poles always read energy 0) | 46 | real core friction |
| 10 | Keep `inspect`/`look` output short: filter out ore tiles and belts | 46 | real core friction |
| 11 | Make tile-vs-centre coordinates unambiguous on the map | 42 | misconception |
| 12 | Let me look at a remote x,y without walking there | 41 | misconception |
| 13 | Place inserters by pickup/drop, and don't print odd drop offsets | 37 | misconception |
| 14 | Give me one clear rate number (production vs 10-min average vs ops counter) | 36 | misconception |
| 15 | Tell me which alerts are mine; the base alerts are noise | 34 | scenario artifact |
| 16 | Give me a roadmap/board with priorities | 33 | scenario artifact |
| 17 | Warn me when I queue a tech whose packs aren't made | 26 | misconception |
| 18 | Show power demand vs capacity per site | 26 | misconception |
| 19 | Show a design's footprint and IO before stamping; I need a design for my exact layout | 25 | agent-layer |
| 20 | `build` says "paused, 0 ghosts left" when it's done | 19 | real core friction |
| 21 | Clearer errors when I call an act op as a tool or a tool as an act op | 17 | misconception |
| 22 | Craft count should be items, and say when it's capped | 16 | misconception |
| 23 | Tell me when a tool moves my character | 15 | misconception |
| 24 | My context was cleared before the debrief | 11 | scenario artifact |
| 25 | `done_when` without a zone gets stuck in verifying | 8 | misconception |

Minor (<8 runs): A pole `connect` reports "placed all" while the chain doesn't reach the network (7.6-tile hop). (6, real core friction); `inspect` doesn't show whether an underground is an input or an output. (5, real core friction); A take from a chest caps at 100. (6, misconception); `act` returned "still running" without a result. (6, misconception); Refuel everything in a zone, or list the out-of-fuel machines. (5, agent-layer); `connect`/placement walled the character inside a furnace row ("no path"). (4, real core friction)

**Bottom line.** 7 of 25 main clusters are real core friction, and 301 of 377 runs raised at least one of them. Five fixes cover nearly all of it: (1) `find item=` over chest and machine contents, exposing what `Controller.source()` already does; (2) `connect`/`build line` should snap to a belt end within 1 tile, report joined yes/no for each end, and source its own undergrounds; (3) add an electric network id and powered/no_power to `inspect`, `place` and `build` results, and drop pole `energy`; (4) a mod-side belt `trace`; (5) an `inspect` filter that skips ore tiles. The `paused, 0 ghosts left` bug is a one-line reorder. The two largest clusters (empty start inventory, infinity-chest fixtures) plus the ops-message and alert noise are scenario artifacts, so fix those in the scenario briefs.

## Clusters

### 1. Start me with a kit (poles, copper, inserters) or put materials near the job

- **Runs:** 243. Scenarios: t-inserter-mall 28, t-steel 28, t-gear-cell 24, t-power-line 23, t-cross-bus 23, t-brownout 22, t-deliver 20, t-belt-ore 18, d4-library 17, t-smelter-column 16, t-red-block 11, t-starved 11, t-stamp-book 1, t-circuit 1
- **Sort:** scenario artifact. Every short scenario spawns the serf at 0,0 with ~8 iron plates, no copper or wood, far from the site; a real crew would carry a kit.
- **Code check:** Not a harness gap. Top failures confirm it: `cannot craft <x>: missing ingredients` (80 in 62 runs, mostly small-electric-pole) and `no <item> in inventory` (107 in 40 runs).
- > "A starter kit (assembler, inserters, chest, pole) or a copper chest would have cut this to about two minutes." (`20261019-231435-t-gear-cell-sonnet-i5`) †
- > "I had no copper cable, so I couldn't craft a pole and borrowed one from a redundant spot instead." (`20261020-001652-t-brownout-sonnet-i5`)

### 2. Tell me where shared stock is: list chest contents, find by item

- **Runs:** 198. Scenarios: t-cross-bus 29, t-deliver 29, t-gear-cell 25, t-smelter-column 19, t-steel 18, t-inserter-mall 15, t-power-line 14, t-belt-ore 14, t-brownout 12, t-starved 9, t-red-block 8, t-backed-up 2, t-coal-boilers 1, d4-library 1, f1-feldspar-iron 1, d3b-circuit-mall 1
- **Sort:** real core friction. The base held thousands of plates and a 100-inserter depot, but nothing could locate items; serfs inspected chests one by one.
- **Code check:** Verified. `find` only takes entity names; an item name errors with `no entity called copper-plate` (observe.lua `observe.find`). That is the #2 failure overall (101 in 93 runs). `marks` only lists marks agents placed, and none existed. `Controller.source()` already searches chests and machine outputs for items, but no tool exposes it. Fix: `find item=X` over containers and outputs. The depot being unmarked is partly the scenario's doing.
- > "`find` can't search for item stock in chests, and `find copper-plate` errored because plates aren't entities." (`20261020-042720-t-power-line-sonnet-i5`)
- > "a one-call "what's in the shared chests" view. marks showed nothing, so I scanned by hand." (`20261020-015957-t-deliver-sonnet-i2`) †

### 3. Tell me which chests/rigs are free supply and which are test fixtures

- **Runs:** 114. Scenarios: t-inserter-mall 27, t-steel 22, t-starved 20, t-brownout 12, t-red-block 10, t-gear-cell 8, t-power-line 4, t-deliver 4, t-circuit 2, t-smelter-column 2, t-cross-bus 2, t-backed-up 1
- **Sort:** scenario artifact. The infinity chests, energy interfaces and half-built test rigs belong to the scenario saves. The serf couldn't tell setup from real base, or whether it could take from them.
- **Code check:** Scenario setup. One line per scenario brief ("infinity chests at X are free supply") fixes it.
- > "Taking parts from the infinity chests worked well, but the order didn't say I could, and I had to assume it." (`20261020-012220-t-inserter-mall-sonnet-i1`) †
- > "The infinity chests and the energy interface made it unclear what counts as real automation." (`20261020-044941-t-starved-sonnet-i3`) †

### 4. A whole-base survey: what exists and what feeds what

- **Runs:** 68. Scenarios: t-starved 23, t-red-block 11, t-power-line 9, t-deliver 9, t-brownout 4, d2-science-steps 2, t-belt-ore 2, d4-library 2, t-stamp-book 1, t-cross-bus 1, t-gear-cell 1, d3b-circuit-mall 1, t-steel 1, t-smelter-column 1
- **Sort:** agent-layer. A do-everything 'explain the base' helper. The pieces already exist.
- **Code check:** `production`, `diagnose` (producers and consumers with sites), `find type=`, and `map x,y` (radius 24) all exist, so a survey script can be saved with `skill_save`. Most hits are t-starved (23 of 28 runs), where the labs sat 80 tiles from the pack assemblers on purpose.
- > "A base-wide overview of where each belt starts and ends, and which entities are test fixtures" (`20261019-232327-t-brownout-sonnet-i1`)
- > "a tool that walks a dependency chain and names the first broken link" (`20261020-013739-d3b-circuit-mall-sonnet-i2`) †

### 5. Don't repeat ops messages, and name the item or place in them

- **Runs:** 66. Scenarios: t-cross-bus 10, t-brownout 10, t-power-line 9, d4-library 7, t-deliver 7, t-smelter-column 5, t-belt-ore 4, t-red-block 4, t-inserter-mall 2, t-gear-cell 2, t-starved 2, t-stamp-book 1, t-coal-boilers 1, d2-science-steps 1, t-steel 1
- **Sort:** scenario artifact. The scripted ops pings re-sent orders after completion and used referents like "them" or "between them". This is a test-harness artifact.
- **Code check:** Fix in the scenario scripts (ops nudges), not in the core.
- > "The same ops message arrived three times after the work was already done, so I answered it twice with no new information." (`20261019-234602-d4-library-sonnet-i1`) †
- > "I couldn't tell what "them" meant in your "take them from stock or craft them" message." (`20261020-024006-t-deliver-sonnet-i2`) †

### 6. `build line`/`connect` should join existing belt ends, fetch its own undergrounds, and say when it didn't join

- **Runs:** 63. Scenarios: t-cross-bus 25, t-belt-ore 25, t-smelter-column 3, t-red-block 3, t-gear-cell 3, t-starved 2, t-brownout 1, t-coal-boilers 1
- **Sort:** real core friction. This is a real bug. The line lands one row off or one tile short and still reports "placed all". It hit 25 of 30 t-belt-ore runs and 25 of 30 t-cross-bus runs.
- **Code check:** Verified. In jobs.lua `H.connect`, `from` and `to` snap to a belt only when the coordinate lands on that exact tile (`belt_at`). Otherwise `free_tile()` slides to a neighbouring free tile, so the line starts parallel to the belt or stops short, and the result never says whether either end joined. Separately, `Controller.connect` (controller.py) only sources the line item, not undergrounds: `route needs N underground-belt` is 57 failures in 53 runs. Fix: snap to a belt end within 1 tile, report joined yes/no per end, and source undergrounds.
- > "`build line` shifted my start from y=82.5 to y=81.5 and said "done" without noting that it hadn't joined the existing belt." (`20261020-040439-t-cross-bus-sonnet-i6`)
- > "The `build kind=line` result said "placed all", but its first and last tiles didn't connect to the existing belts." (`20261020-011542-t-belt-ore-sonnet-i1`)

### 7. Warn me when something I placed has no power, and show pole coverage

- **Runs:** 50. Scenarios: t-inserter-mall 22, t-gear-cell 16, t-red-block 5, t-steel 3, t-brownout 3, d4-library 1
- **Sort:** real core friction. The serf left an inserter outside the 5x5 supply area and only found out by inspecting it later. Cheap to surface.
- **Code check:** Verified. The `place` result reports pickup and drop but not power status, the map has no coverage layer, and ACTION_DOC never mentions the 5x5 supply area. Fix: list any `no_power` entities in the place/build result. Partly a game-rule misconception.
- > "the unpowered status only showed up when I inspected the inserter, not in the place result." (`20261020-014850-t-inserter-mall-sonnet-i5`)
- > "The map also doesn't show the pole coverage area, so I worked it out from entity positions." (`20261020-025902-t-inserter-mall-sonnet-i4`)

### 8. Follow a belt to its end and report where it breaks

- **Runs:** 48. Scenarios: t-belt-ore 14, t-starved 11, t-brownout 8, t-cross-bus 3, d3b-circuit-mall 3, t-coal-boilers 2, f1-feldspar-iron 2, t-smelter-column 2, t-backed-up 1, d2-science-steps 1, t-power-line 1
- **Sort:** real core friction. The agent layer tried this with its own `follow_belt`/`probe_col` scripts, which lose the line at turns, gaps and undergrounds. The primitive is missing.
- **Code check:** Verified. No trace tool exists. `library/skills/follow_belt.json` is agent-written (it hit the 60-call limit, among other failures). jobs.lua already has `belt_at`, `line_end` and `feeder_of`, so a mod-side `trace` that returns tiles, lane contents, and the first break or dead end is small.
- > "I also lost a lot of time tracing mixed belts by hand with `follow_belt`, which only walks one direction well and kept losing the trail." (`20261020-024604-f1-feldspar-iron-sonnet-i2`)
- > "A way to check belt continuity over a long distance in one call." (`20261020-024604-f1-feldspar-iron-sonnet-i1`)

### 9. Tell me whether a build is on the grid (poles always read energy 0)

- **Runs:** 46. Scenarios: d4-library 20, t-power-line 7, t-brownout 4, t-starved 3, t-red-block 2, t-inserter-mall 2, t-gear-cell 2, t-steel 1, d2-science-steps 1, t-smelter-column 1, t-deliver 1, t-stamp-book 1, t-circuit 1
- **Sort:** real core friction. This is a misleading field plus a missing check. Every d4-library stamp ended with the serf inferring power from inserter status.
- **Code check:** Verified. `API.inspect` (control.lua) returns `e.energy`, which is always 0 for poles because they have no buffer. It returns no `electric_network_id` and no satisfaction figure, and the stamp/build results don't report unpowered entities. Fix: drop pole energy, add network id plus a powered or no_power count to inspect and build results.
- > "Poles always show energy 0, so I judged by the inserters, which showed energy. A grid-connected check would have helped." (`20261020-001956-d4-library-sonnet-i6`) †
- > "The slow part was working out whether they were powered, since the build result never says." (`20261020-052526-d4-library-sonnet-i1`) †

### 10. Keep `inspect`/`look` output short: filter out ore tiles and belts

- **Runs:** 46. Scenarios: d4-library 7, t-starved 7, t-deliver 6, t-brownout 4, t-smelter-column 4, t-inserter-mall 3, t-red-block 3, d2-science-steps 2, t-gear-cell 2, d3b-circuit-mall 2, t-power-line 2, t-backed-up 1, t-cross-bus 1, t-steel 1, f1-feldspar-iron 1
- **Sort:** real core friction. One inspect on an ore field or belt area costs thousands of tokens.
- **Code check:** Verified. `API.inspect` has no type or name filter and returns every resource tile with its amount. `look` (radius up to 48) lists every belt. Fix: skip resources unless asked, add `name`/`type` filters, and summarize belts.
- > "`inspect` with a radius dumped a huge amount of text for the furnace column." (`20261020-040439-t-power-line-sonnet-i4`)
- > "one inspect returned thousands of ore tiles" (`20261020-010734-t-starved-sonnet-i1`) †

### 11. Make tile-vs-centre coordinates unambiguous on the map

- **Runs:** 42. Scenarios: t-belt-ore 8, t-inserter-mall 7, t-cross-bus 7, t-smelter-column 5, t-gear-cell 3, t-brownout 3, t-circuit 2, t-starved 2, d4-library 2, d2-science-steps 1, t-red-block 1, t-steel 1
- **Sort:** misconception. The rule is documented. The serf misread the map's integer rows against .5 entity centres.
- **Code check:** ACTION_DOC states it ("tile (x,y) spans x..x+1; 1x1 entities sit at .5 centers"). This compounds the line_join bug. Prompt or tool-message fix: print centres in the map header and in line results.
- > "the map's tile rows and the entity coordinates use different offsets, and nothing in the tools says so." (`20261020-053158-t-belt-ore-sonnet-i2`)
- > "Belt "y=84.5" is the tile 84..85, so my first inserter picked from an empty tile" (`20261020-053836-t-gear-cell-sonnet-i4`)

### 12. Let me look at a remote x,y without walking there

- **Runs:** 41. Scenarios: t-starved 17, t-power-line 8, t-belt-ore 6, t-brownout 5, t-deliver 2, t-gear-cell 1, t-red-block 1, t-inserter-mall 1
- **Sort:** misconception. `look` takes only a radius. `map x,y` and `inspect x,y radius` already do this.
- **Code check:** Verified. tools.py `t_look` silently ignores x,y. Fix: accept x,y, or reject them with "use map/inspect for a remote spot".
- > "My first `look` at [gps=128,-51] showed my own surroundings instead, because `look` has no x,y option." (`20261020-053158-t-power-line-sonnet-i3`)
- > "`look` also ignores its x,y arguments, so I had to use `inspect` to see the far labs." (`20261020-012651-t-starved-sonnet-i3`)

### 13. Place inserters by pickup/drop, and don't print odd drop offsets

- **Runs:** 37. Scenarios: t-smelter-column 8, t-inserter-mall 8, t-starved 5, t-steel 5, t-gear-cell 4, t-red-block 4, d2-science-steps 2, t-cross-bus 1
- **Sort:** misconception. `place` already takes `pickup=`/`drop=`, and the docs call it "always right". The .7/.2 drop offsets are the game's real drop position.
- **Code check:** Verified (jobs.lua `place`). One small real gap: the `blueprint entities=[...]` op has no pickup/drop, so stamped inserters need a direction. Rotate's semantics could also be spelled out in its result.
- > "`rotate direction=south` on an inserter makes it pick up from the south, which is the opposite of how I read it." (`20261020-030342-t-starved-sonnet-i6`)
- > "I placed the inserters with a direction and they came out backwards." (`20261020-025125-t-smelter-column-sonnet-i3`)

### 14. Give me one clear rate number (production vs 10-min average vs ops counter)

- **Runs:** 36. Scenarios: t-steel 9, t-inserter-mall 7, t-red-block 5, t-gear-cell 4, t-smelter-column 3, t-starved 2, d4-library 1, f1-feldspar-iron 1, t-power-line 1, t-brownout 1, t-belt-ore 1, t-cross-bus 1
- **Sort:** misconception. The serf mixed up warm-up readings, the 10-minute average and the scenario's own counters.
- **Code check:** `production` is per minute and `diagnose` shows a 10-minute average next to it. The 'gears made' / 'red made' counters come from scenario ops checks. Clearer labels are enough.
- > "The steel rate went from 8 to 16 per minute with no change from me, and I didn't investigate." (`20261020-010529-t-steel-sonnet-i5`)
- > "the "red made" figure looked cumulative while `production` showed a rate" (`20261020-044213-t-red-block-sonnet-i4`)

### 15. Tell me which alerts are mine; the base alerts are noise

- **Runs:** 34. Scenarios: t-power-line 7, t-brownout 5, t-red-block 3, t-smelter-column 3, t-steel 3, t-backed-up 2, t-starved 2, d2-science-steps 2, t-inserter-mall 2, d4-library 2, t-deliver 1, d3b-circuit-mall 1, t-cross-bus 1
- **Sort:** scenario artifact. Every save carries the same dead boiler, 32 unfuelled legacy burners and idle labs, unrelated to the order.
- **Code check:** Scenario base state. Ship a clean base, or say in the brief that the alerts are out of scope.
- > "The alerts about fuel starvation and idle labs were far bigger than my order, and I had no way to tell what was urgent." (`20261020-033903-t-power-line-sonnet-i4`)
- > "the fuel alert counts dead burner drills as outages" (`20261019-235426-d2-science-steps-sonnet-i2`) †

### 16. Give me a roadmap/board with priorities

- **Runs:** 33. Scenarios: t-red-block 10, t-smelter-column 6, t-power-line 4, t-belt-ore 4, t-deliver 3, t-gear-cell 2, d4-library 1, f1-feldspar-iron 1, t-brownout 1, d3b-circuit-mall 1
- **Sort:** scenario artifact. Short tasks start with an empty board and roadmap by design.
- **Code check:** Not a core gap. `roadmap`/`post_task` exist and the serf could set its own.
- > "The board and roadmap were empty, so I had no priorities." (`20261020-000024-t-gear-cell-sonnet-i5`)
- > "I was missing a clear order from you and a roadmap." (`20261020-000158-t-red-block-sonnet-i4`) †

### 17. Warn me when I queue a tech whose packs aren't made

- **Runs:** 26. Scenarios: t-starved 11, t-deliver 6, t-red-block 3, t-gear-cell 1, t-smelter-column 1, d4-library 1, t-steel 1, t-brownout 1, d2-science-steps 1
- **Sort:** misconception. `techs` already lists each tech's packs. The serf didn't read them.
- **Code check:** Verified (observe.lua `techs` returns `packs`). Tool-message fix: the research op could append "needs logistic-science-pack: none made".
- > "I queued research-speed-1 without checking which packs it needs, and the labs starved on logistic packs for a while." (`20261020-001157-t-starved-sonnet-i6`)
- > "The `techs` list also doesn't flag which techs need green science, so I queued research-speed-1 first and it couldn't run." (`20261020-015625-t-starved-sonnet-i2`)

### 18. Show power demand vs capacity per site

- **Runs:** 26. Scenarios: t-brownout 16, t-starved 4, t-smelter-column 3, t-red-block 1, t-cross-bus 1, d3b-circuit-mall 1
- **Sort:** misconception. `diagnose steam` gives steam made vs used. The serf asked for `electricity`, which isn't an item.
- **Code check:** Partly verified. `diagnose item=electricity` answers "nothing makes electricity" instead of redirecting to steam. Fix the message; brownout scenarios account for 16 of the 26 hits.
- > "A power-demand-versus-capacity readout per site would also have saved the guessing." (`20261020-035218-t-brownout-sonnet-i1`)
- > "The `diagnose item=electricity` call said nothing makes electricity, which was wrong." (`20261020-021755-t-brownout-sonnet-i5`)

### 19. Show a design's footprint and IO before stamping; I need a design for my exact layout

- **Runs:** 25. Scenarios: t-red-block 8, d4-library 8, t-smelter-column 6, t-starved 1, t-brownout 1, t-circuit 1
- **Sort:** agent-layer. `designs` already lists size, inputs and outputs. Custom layouts are what `copy` with a note is for.
- **Code check:** Agent layer: save each verified build with `copy note=`. One real nit: stamped furnaces come out partly unfuelled (east 6 empty, west 6 with coal), which is worth a look in the controller's refuel step.
- > "Missing: a note on what the stamped designs expect (which side input and output are on, ghost orientation)" (`20261019-235741-t-smelter-column-sonnet-i4`) †
- > "the 5-assembler red-science stamp assumes copper and gears are already on one belt" (`20261020-034641-t-red-block-sonnet-i5`)

### 20. `build` says "paused, 0 ghosts left" when it's done

- **Runs:** 19. Scenarios: d4-library 18, t-brownout 1
- **Sort:** real core friction. This is a real bug. 18 of 30 d4-library runs re-ran or re-inspected a finished stamp.
- **Code check:** Verified. `Controller.fulfill` (crew/controller.py) checks the deadline before it checks `ghosts == 0`, so a build that finishes at the time limit reports "paused". Fix: check for zero ghosts first.
- > "The "paused with 0 ghosts left" message looked like a failure when it meant done." (`20261020-035810-d4-library-sonnet-i3`)
- > ""paused with 0 ghosts left" doesn't say whether the build is complete." (`20261020-035555-d4-library-sonnet-i3`) †

### 21. Clearer errors when I call an act op as a tool or a tool as an act op

- **Runs:** 17. Scenarios: t-deliver 5, t-inserter-mall 3, t-smelter-column 3, t-steel 2, t-gear-cell 2, t-belt-ore 1, t-stamp-book 1
- **Sort:** misconception. `inspect`, `look`, `stop` and `research` were called in the wrong place.
- **Code check:** The error is just `unknown action op 'inspect'` (jobs.lua). Make it say "inspect is a tool, not an act op".
- > "the `research` call isn't a separate tool, it's an `act` op." (`20261020-055037-t-deliver-sonnet-i3`)
- > "My first `act` call failed because the tool is named `mcp__game__act`." (`20261020-054216-t-inserter-mall-sonnet-i6`)

### 22. Craft count should be items, and say when it's capped

- **Runs:** 16. Scenarios: t-deliver 8, t-red-block 4, t-brownout 2, t-steel 1, t-power-line 1
- **Sort:** misconception. `count` means recipe runs, and the craft is silently capped at what's craftable.
- **Code check:** Verified (jobs.lua `H.craft`: `n = min(count, craftable)`). Tool-message fix: "50 crafts = 100 belts; capped at 5 by ingredients".
- > "`craft count` counts crafts, not items, so I made 100 belts instead of 50." (`20261020-035455-t-deliver-sonnet-i4`)
- > "I queued 18 inserters but only 5 were crafted (it silently capped on materials)." (`20261020-000508-t-red-block-sonnet-i6`) †

### 23. Tell me when a tool moves my character

- **Runs:** 15. Scenarios: t-cross-bus 5, t-inserter-mall 2, t-power-line 2, t-red-block 2, t-gear-cell 2, t-starved 1, t-belt-ore 1
- **Sort:** misconception. The build controller walks to chests to fetch items. The serf saw its position jump.
- **Code check:** Expected behaviour. The build/line result should say "walked to the depot at X".
- > "My position jumped from [gps=0,0] to [gps=118,-47] between calls. I don't know why." (`20261020-020626-t-power-line-sonnet-i4`)
- > "The build tool then moved me there on its own without telling me, which cost time." (`20261020-022555-t-cross-bus-sonnet-i6`)

### 24. My context was cleared before the debrief

- **Runs:** 11. Scenarios: t-smelter-column 5, t-red-block 3, t-belt-ore 3
- **Sort:** scenario artifact. Some debriefs were asked after a context reset, so there was nothing to report.
- **Code check:** Bench artifact. Ask for the debrief before compaction or reset.
- > "My memory was cleared, and the notes held nothing about what I'd built or where." (`20261020-014313-t-smelter-column-sonnet-i5`)
- > "my earlier context was cleared, so I can't give details of what took longest." (`20261019-233634-t-red-block-sonnet-i5`) †

### 25. `done_when` without a zone gets stuck in verifying

- **Runs:** 8. Scenarios: t-power-line 2, t-smelter-column 2, t-starved 1, t-red-block 1, t-brownout 1, t-gear-cell 1
- **Sort:** misconception. The post_task doc says "or add scope: base". The serf omitted it or put it in the wrong place.
- **Code check:** Verified (orders.lua: non-rate checks need a zone unless `scope: "base"` is inside the condition). Fix: reject at `post_task` time with the exact shape, instead of letting the task sit in verifying.
- > "Task #1's check failed with "needs a zone" and stayed in verifying even though the job was done." (`20261019-233055-t-power-line-sonnet-i4`) †
- > "The task check "working" needed a zone, so it never closed." (`20261020-050649-t-power-line-sonnet-i4`) †

### Minor

| Request | Runs | Sort | Quote | Note |
|---|---|---|---|---|
| A pole `connect` reports "placed all" while the chain doesn't reach the network (7.6-tile hop). | 6 (t-red-block 4, t-gear-cell 2) | real core friction | "The `connect` and `build line` pole result said "placed all 3" with no warning that the chain didn't reach the existing network." `20261020-041017-t-gear-cell-sonnet-i5` | Same fix as grid: report network connected yes/no. I didn't check `pole_hops` itself. |
| `inspect` doesn't show whether an underground is an input or an output. | 5 (d3b-circuit-mall 3, t-brownout 1, t-cross-bus 1) | real core friction | "Underground belts also don't show whether they're an input or an output, so I found the bad exit by guessing." `20261020-013739-d3b-circuit-mall-sonnet-i1` | Verified: `API.inspect` omits `belt_to_ground_type`. Small fix. |
| A take from a chest caps at 100. | 6 (t-red-block 5, t-brownout 1) | misconception | "Each infinity-chest take is capped at 100" `20261020-010015-t-red-block-sonnet-i3` | Probably the infinity-chest stack. Only seen in red-block. |
| `act` returned "still running" without a result. | 6 (t-deliver 2, t-inserter-mall 1, t-steel 1, t-gear-cell 1, t-smelter-column 1) | misconception | "the first act call said "still running" and left me without a result" `20261020-011139-t-deliver-sonnet-i2` | Documented `wait='until_last'` behaviour. |
| Refuel everything in a zone, or list the out-of-fuel machines. | 5 (t-power-line 4, t-red-block 1) | agent-layer | "A bulk refuel-in-zone action would help." `20261019-235426-t-power-line-sonnet-i5` † | `build` refuels burners in its zone. Otherwise this is a script. |
| `connect`/placement walled the character inside a furnace row ("no path"). | 4 (t-smelter-column 2, t-deliver 1, t-steel 1) | real core friction | "`connect` then boxed me into the furnace row and couldn't path out." `20261020-040854-t-smelter-column-sonnet-i2` | The router doesn't keep a walking gap. Rare. |

## Cross-check: top_failures

623 failure events across 203 runs, normalized (numbers become N, entity and item names are templated). `top_failures` holds each run's top few, so the counts are a lower bound.

| # | Normalized failure | Count | Distinct runs | Matches cluster |
|---|---|---|---|---|
| 1 | place: no <item> in inventory | 107 | 40 | kit (#1) |
| 2 | `find`: no entity called <item> (an item name such as copper-plate or iron-plate) | 101 | 93 | stock (#2) |
| 3 | take: nothing to take from <entity> (<item>) | 81 | 18 | stock (guessing which furnace holds plates) |
| 4 | craft: cannot craft <x>: missing ingredients (mostly small-electric-pole) | 80 | 62 | kit (#1), coverage |
| 5 | place: cannot place <x>: blocked by <entity> | 75 | 30 | coords |
| 6 | `build line`: route needs N underground-belt but you have N | 57 | 53 | line_join |
| 7 | insert: <entity> won't accept <item> | 17 | 9 | (insert at a wrong tile) |
| 8 | move: no path to N,N | 16 | 7 | boxed (minor) |
| 9 | `connect`: route needs N <item> but you have N | 12 | 11 | line_join |
| 10 | no machine at N,N | 12 | 2 | coords |

The failures agree with the debriefs. The two inventory failures are the empty-kit artifact. The top distinct-run failure is the missing item search: 93 runs called `find` with a plate name (copper-plate 56, iron-plate 36). The line-tool failures come from it not sourcing its own undergrounds and belts (57 events in 53 runs for undergrounds, plus 12 in 11 runs from `connect`).
