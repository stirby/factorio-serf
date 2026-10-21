# Jev + Opus: design

One character in Factorio, three parts.

| Part | Who | Job |
|---|---|---|
| Hands | the mod (forked from factorio-serf at `serf-v1-final`) | Legal player actions: walking, reach, real inventory, crafting, routing belts and poles (`connect`), ghosts, `fetch`. New in this fork: `scan` (an area in ~90 ms, exact footprints, neutral obstacles); `grab` (items off belts); `query` (read-only lookups allowed over UDP); fetching ingredients from storage before crafting; explicit wiring along a pole line. |
| Code | `world`, `steps`, `lint`, `router`, `rowgen`, `blueprints` | Everything exact. **World model:** belt lines and why they end, which inserter feeds what, why a machine is stopped, and faults with candidate fixes. **Steps:** fetch everything a plan needs in one trip; fall back to belts, crafting, then mining; keep a power step trying until nothing is unpowered; place pole lines in legs; build ghosts until none are left. **Plan checker:** simulates the plan before any of it is built. **Router:** many belts that never mix. **`row`:** machines along a belt. **Blocks:** game-tested designs. |
| Actor | Jev (`decide.py`, `actor.py`) | The judgment calls. Each is a narrow typed question over a small state that code prepares. |
| Thinker | Opus (`thinker.py`) | Never in the action loop. It is woken for orders the actor can't do alone and for plans that failed or missed. It reads the area through tools and submits one plan. |

## The layer between them: the plan

A plan has a goal, steps, checks (`expect`), chat lines, and optionally things to `watch`.

The step operations are:
- `place`, `rotate`, `set_recipe`, `connect` (lines over ~230 tiles go in legs), `ghosts` (with compact `repeat` and `line` notation), `row`, `block`, `design`, `route`, `merge_lanes`
- `upgrade` (a better tier in place, along a belt line or in an area), `clear` (pick up buildings in an area)
- `power`, `refuel`, `insert`, `take`, `empty_chest`, `fetch`, `craft`, `mine`, `mine_at`
- `research` (`tech="cheapest"`), `move`, `follow`, `wait`, `say`

Division of labour:
- Opus decides *what* and *where*.
- Code decides *how*, and checks the plan before it runs: problems go back to Opus in the same turn.
- Jev decides *what now* when something goes wrong.

`expect` checks are run by code: working, has_item, powered, belt_carries, built. A build plan without a `built` check gets one automatically. When a plan has no checks, Jev judges the goal against the area, at most three times.

## Jev's decisions

| Decision | State it sees | Notes |
|---|---|---|
| chat | message, speaker, what I'm doing, my last line | three questions in one call: for me? / kind / playbook |
| question type | the question | status, where and inventory are answered by code |
| fault | the player's words + faults code found, grouped by kind | picks a group; code fixes every member |
| scope | the order | one spot or many sites (wide-area fix) |
| recovery | step, error, tries, **facts code read off the error** | retry / get items / skip / replan |
| changes_plan | current job + new message | stops a running plan for a correction |
| not_done | finished job + new message | only real "not done" reopens an order |
| goal_met | goal + area summary (relative words) | only for plans without code checks |
| kit | the order | what to fetch while Opus plans |
| watch | area summary + the planner's conditions | while idle, over areas it built |
| quick build | the order, the products the nearby belts can make, what those belts carry | product, count, onto a belt?, chain?, sent elsewhere? |

What we learned about encoding, both from the lab and from TypeSafe's notes on Jev 1.13's rough edges:
- Jev never compares numbers; code turns them into words.
- Each option carries what it's for, what it's not for, and examples. That took chat sorting from 45/51 to 49/51.
- Facts code can read off a message go into the state as booleans. That took recovery from 52/65 to 63/65.
- Equivalent options are merged, so confidence isn't split between them.
- Narrow yes/no questions beat one broad one. A single "is this a simple row job" noul accepted 3 of 9 plain orders; four narrow checks (chain? sent elsewhere? onto a belt? which product?) got 31/32 with no wrong accepts.
- Distances are code's job: whether a named point is far (>40 tiles) decides how much Jev's "elsewhere" doubt counts.

## Fast paths (no Opus)

- **fix:** a point is named, so code finds the faults, Jev picks one, and the fix runs. If the order names many sites, code scans a grid of areas and fixes everything nearest-first.
- **deliver:** items and a chest are named.
- **route:** the order lists belt start/end pairs, so the router lays them all. This solves all five Transport Belt Madness levels in 1.5–18 s.
- **quick build:** the order points at belts and asks for one product off them ("make gears off this belt", "4 furnaces making steel", "an assembler making inserters from these belts"). Code lists what a row off the nearby belts could make (one belt, or two at row spacing; furnaces only if the belt carries fuel), Jev reads the order, code finds a free spot along the belt and lays the tested row step. The usual runner builds and checks it; if that fails, Opus gets the order plus what was tried. t-steel and t-inserter-mall pass this way with no Opus call.
- **quick answers:** status, location and inventory questions.

## The agent layer

`jev/library.py` holds what Opus writes for itself:
- **Lessons:** a general rule after an order that needed more than one plan.
- **Designs:** layouts saved with `save_design` and reused with a `design` step.

The test loop gives each run its own library under `bench/libraries/<tag>`. Lessons go stale when the code changes, so they need the daily review.

## Measuring

- `bench/run.py`, `batch.py` and `loop.py` use the serf's scenarios, scoring and scripted player.
- `bench/report_rows.py` compares runs with the serf.
- `bench/digest.py` is the daily review: pass rate, time per order, Jev's decisions with their confidence (low-confidence ones listed for labelling), recovery choices, what the checker caught, and new lessons.
- `lab/eval_*.py` replays Jev on labelled cases, without starting the game.
