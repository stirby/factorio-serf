# Prior art at source level: factorio-crewmate, factorio-codex, alina-ai-teammate (vs Claude Crew)

Method: all three repos were shallow-read from local clones on 2026-10-18 (crewmate `master` @ `f466486`, codex `main` @ `90de437`, alina `main` @ `99e72d4`). Repo stats come from the GitHub web pages on 2026-10-18; the API was rate-limited. "Verified" means read in source. "README claim" means asserted in docs and not checked in code. Nothing was executed.

Link prefixes used below:
- CM = https://github.com/quartermeat/factorio-crewmate/blob/f466486/
- CX = https://github.com/LukaVodopivec/factorio-codex/blob/90de437/
- AL = https://github.com/KORTY-DEV/alina-ai-teammate/blob/99e72d4/

## Q1. Identity, dates, license, popularity, Factorio version, maturity/tests

### Takeaway
- **Crewmate** is a 4.5-hour, 19-commit, unlicensed solo experiment on Factorio 2.0.
- **Codex** is the most mature project by far: a 600+ commit, MIT-licensed fork of Agentic-Factorio, built and tested against Factorio **2.0.77**, the same version as Claude Crew, with about 116 test files.
- **Alina** is a 5-commit, source-available "all rights reserved" drop that targets Factorio **2.1** and can't be legally forked.

### Cited Findings

**factorio-crewmate (quartermeat)**
- All 19 commits fall on 2026-09-12, from 18:56 (`v0.1.0: Crewmate`) to 23:21 -0400 (`v0.12.1`). Each commit is a version bump. Verified via `git log` — [repo](https://github.com/quartermeat/factorio-crewmate)
- The repo has no LICENSE file, and GitHub shows no license, so legally it is all-rights-reserved by default. Stats: 0 stars, 0 forks, no releases — [GitHub page](https://github.com/quartermeat/factorio-crewmate)
- `mod/info.json` declares `"factorio_version": "2.0"`, `"dependencies": ["base >= 2.0"]`, mod version 0.12.0. VERSION is 0.12.1 — [CM mod/info.json](https://github.com/quartermeat/factorio-crewmate/blob/f466486/mod/info.json)
- Stack: a Lua mod (about 130 KB) plus a stdlib-only Go bridge that hosts the headless server, speaks RCON and serves MCP over stdio for Claude Code. Tests are 37 Go `func Test*`. 15 of them are integration tests that generate a map, host a server and drive the body (`CREWMATE_INTEGRATION=1`, about 7 s according to the README) — [CM bridge/integration_test.go](https://github.com/quartermeat/factorio-crewmate/blob/f466486/bridge/integration_test.go), [CM README](https://github.com/quartermeat/factorio-crewmate/blob/f466486/README.md)
- The README roadmap lists v0.10 to v0.12 as not done: "sense of place", "initiative", and "manners", meaning an audit log, per-player permissions and undo. The commit subjects reuse those version numbers for different features, so README and tags disagree — [CM README](https://github.com/quartermeat/factorio-crewmate/blob/f466486/README.md)

**factorio-codex (LukaVodopivec)**
- History starts at Matteo Mekhail's Agentic-Factorio: 61 commits from 2026-07-14 ("V1, wow"). LukaVodopivec's first commit is 2026-09-02 ("establish factorio-codex repository contract"). The last commit is 2026-10-11 (`release: 0.38.1`). The repo has 617 commits: 555 by LukaVodopivec, 154 in September and 402 in October — [repo](https://github.com/LukaVodopivec/factorio-codex), [CX UPSTREAM.md](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/UPSTREAM.md)
- MIT license, copyright Matteo Mekhail and LukaVodopivec. Stats: 1 star, 0 forks, 7 open PRs (likely dependabot; not verified), no GitHub releases — [CX LICENSE](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/LICENSE), [GitHub page](https://github.com/LukaVodopivec/factorio-codex)
- Mod `agentic-companion` 0.38.1, `"factorio_version": "2.0"`. The tests ship API fixtures `factorio-2.0.77-runtime-members.lua` and `factorio-2.0.77-linked-game-controls.lua`, and docs cite "Linux Factorio 2.0.77" — [CX info.json](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/mod/agentic-companion/info.json), [CX AGENT-PLAY-PERFORMANCE.md](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/docs/AGENT-PLAY-PERFORMANCE.md)
- Size: about 6 MB of repo. 96 Lua mod unit tests (`tests/mod/*_test.lua`, with a Factorio API mock) and 20 TypeScript tests (`companion/test/*.test.ts`), including `two-brain-contract.test.ts` and `writer-fence.test.ts`. There is also a 112 KB live-validation procedure and CI — [CX tests/mod](https://github.com/LukaVodopivec/factorio-codex/tree/90de437/tests/mod), [CX docs/LIVE-VALIDATION.md](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/docs/LIVE-VALIDATION.md)

**alina-ai-teammate (KORTY-DEV)**
- 5 commits, 2026-08-11 23:28 to 2026-08-12 00:39 (+0400), from "Initial public release: Alina AI Teammate 0.1.0" to "Add full Russian README". This is a code dump, not visible development history — [repo](https://github.com/KORTY-DEV/alina-ai-teammate)
- The license is source-available: "No permission is granted to copy, modify, publish, distribute, sublicense, sell, relicense, or create derivative works… without prior written permission." Stats: 0 stars, 0 forks. It has a donation link — [AL LICENSE](https://github.com/KORTY-DEV/alina-ai-teammate/blob/99e72d4/LICENSE), [AL README](https://github.com/KORTY-DEV/alina-ai-teammate/blob/99e72d4/README.md)
- `info.json`: `"factorio_version": "2.1"`, `"base >= 2.1.0"`, `"? space-age >= 2.1.0"`. CURRENT_STATUS says it was checked on 2026-08-11 against Factorio **2.1.12** — [AL info.json](https://github.com/KORTY-DEV/alina-ai-teammate/blob/99e72d4/factorio-mod/alina-ai-teammate_0.1.0/info.json), [AL docs/CURRENT_STATUS.md](https://github.com/KORTY-DEV/alina-ai-teammate/blob/99e72d4/docs/CURRENT_STATUS.md)
- Stack: a Lua mod of about 1 MB, including a 98 KB `line_expander.lua`, 79 KB `fluid_planner.lua` and 75 KB `local_planner.lua`. The optional bridge is C#/.NET 8 talking to Ollama. CI on windows-latest builds the bridge and runs its "15/15 contract tests". In-game E2E runs through PowerShell scripts and 7 fixture test-mods. The docs are mostly Russian — [AL .github/workflows/ci.yml](https://github.com/KORTY-DEV/alina-ai-teammate/blob/99e72d4/.github/workflows/ci.yml), [AL scripts/](https://github.com/KORTY-DEV/alina-ai-teammate/tree/99e72d4/scripts)

### Inferences
- Codex is the only one with enough engineering depth and a compatible license (MIT) to borrow code from directly. It also runs on the exact same Factorio build as Claude Crew.
- Crewmate code can't be copied without asking the author. Its ideas and lessons are free to use.
- Alina code can't be reused at all, and its 2.1 API target won't load on 2.0.77 as-is.

### Gaps
- Creation dates from the GitHub API weren't available because of the rate limit. First-commit dates stand in for them.
- No issues were inspected, because the API was rate-limited. The GitHub pages show no issue counts.
- I couldn't check whether the 7 Codex PRs are dependabot PRs.

## Q2. Architecture of each

### Takeaway
- **Crewmate:** one scripted character, a Lua plan runner and an MCP/RCON bridge. No model is built in. Claude Code is the optional supervisor.
- **Codex:** one **real connected player** named "Codex" as the body. Two Codex-CLI sessions (strategist and pilot) talk to it over MCP → Node RCON bridge → mod. The mod does all the chores as queued FIFO plans.
- **Alina:** one scripted character with a large deterministic in-mod planner and executor. An optional local Ollama model handles rare free-text intents, in single-player only.

### Cited Findings
- **Crewmate:**
  - Directives are JSON files. The Go bridge resolves `$param`s, `include`s and anchors, then "compiles a directive into absolute steps and hands the whole thing over in one call" to the mod. The mod runs the steps on `on_nth_tick(15)` — [CM README](https://github.com/quartermeat/factorio-crewmate/blob/f466486/README.md), [CM mod/script/plan.lua](https://github.com/quartermeat/factorio-crewmate/blob/f466486/mod/script/plan.lua)
  - The mod can't read files, so `/crew do` queues a request. A bridge daemon polls `take_requests` over RCON: "a plain polling loop on purpose" — [CM bridge/daemon.go](https://github.com/quartermeat/factorio-crewmate/blob/f466486/bridge/daemon.go)
  - MCP tools: `factory_status`, `crew_look/hear/say/spawn/walk_to/follow/halt`, `directive_list/run`, `plan_status/cancel`, `crew_carrying`, `crew_screenshot` — [CM bridge/mcp.go](https://github.com/quartermeat/factorio-crewmate/blob/f466486/bridge/mcp.go)
- **Codex:**
  - "The mod binds the connected player named exactly `Codex` and uses that player's own character as the body; it never creates one." The body is a real client running the native game, standalone build, with username `Codex`.
  - The full MCP surface has 54 tools. The read-only surface has 23.
  - Heavy reads run in-game as tick-spread jobs. Rule: no handler may take more than about 8 ms of Lua per tick, and nothing scans the whole surface.
  - Sources: [CX README](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/README.md), [CX AGENTS.md](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/AGENTS.md)
  - The mod owns line tracking: machines are grouped into "lines" with state `running/starved/output_full/depleted/no_fuel/no_power/no_heat/frozen/disabled/idle` plus `rate_per_min/max_per_min/utilisation`.
  - The mod also owns auto-supply: fetch from own chests or outputs → smelt → hand-craft up to 4 levels → hand-gather. It also does auto-clear of trees and rocks, upkeep (refuel burners within 96 tiles, feed labs), and charting every minute — [CX README "What the mod does by itself"](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/README.md)
- **Alina:**
  - Layers: World Model (event-driven entity index, tick-budgeted) → coordinator/local_planner (fixed priority list) → Task Manager (one high-level task at a time) → executors (mining, acquisition, power, line_expander, upgrader, loadout) → verification and transactional rollback.
  - "LLM не управляет тиками" (the LLM does not drive ticks) — [AL docs/ARCHITECTURE.md](https://github.com/KORTY-DEV/alina-ai-teammate/blob/99e72d4/docs/ARCHITECTURE.md)
  - Autonomy priority order: (1) explicit player command, ban or marker; (2) delegated research; (3) critical power; (4) proven production deficit; (5) safe upgrade of a loaded machine; (6) extend an existing repeatable block; (7) new full chain or assembly block; (8) equipment and construction reserve. The idle re-plan interval defaults to 180 game-seconds — [AL docs/ARCHITECTURE.md](https://github.com/KORTY-DEV/alina-ai-teammate/blob/99e72d4/docs/ARCHITECTURE.md)

### Inferences
- All three use one body. None has several LLM-driven characters, a characterless coordinator or a scheduler over multiple actors, which are Claude Crew's core features.
- Codex's "real player as body" choice sidesteps the scripted-character limitations that Crewmate documents (see Q8). It costs a whole game-client process per body, which doesn't scale to "several actors".

### Gaps
- I didn't trace Codex's `autonomy.lua` (82 KB) or `tasks.lua` (133 KB) in full. The line-state and upkeep claims are from the README, checked against the line-state enum in `ledger.ts` only.

## Q3. Job/directive data format and how checks are expressed and evaluated

### Takeaway
- **Crewmate's directives** are the closest analogue to Claude Crew's work orders. They're JSON step lists with verbs (`stamp` from a blueprint, `build_ghosts`, `drill_row`, `belt_line`, `pole_line`, `make`, `mine`), `$param` substitution, `include`, `label` and `jump`. They have `when` guards made of in-game conditions (`carrying`, `exists`, `resource_within`) and a `check_power` post-check.
- **Codex's build packages** carry a free-text `success_check` plus up to 3 typed `verify` metrics, `{item, per_min_at_least}` or `{line_at, state}`, measured once 2 game-minutes after completion. They are measurement only, with no auto-fix.
- **Alina** has no user-facing job format. The model may emit only 1 action of 4 enum intents.

### Cited Findings

**Crewmate**
- Directive fields: `name, title, description, anchor{find,radius}, blueprint, align, parameters{default,description}, supplies[{name,count}], steps[], requires_recipes[]` — [CM directives/coal-power-loop.json](https://github.com/quartermeat/factorio-crewmate/blob/f466486/directives/coal-power-loop.json)
- Step verbs: `say, goto, stamp, build_ghosts, insert, place, connect, wait, find_resource, find_site, drill_row, belt_line, pole_line, check_power, survey, explore, mine, make, craft, label, jump, include` — [CM README](https://github.com/quartermeat/factorio-crewmate/blob/f466486/README.md)
- "Marks" are named positions written by `find_resource`, `drill_row` and others (`"as": "coal"`) and read by later steps (`"from": "drills_lane_to"`). `insert` targets an entity by name (`"into": "boiler"`) rather than coordinates — [CM coal-power-loop.json](https://github.com/quartermeat/factorio-crewmate/blob/f466486/directives/coal-power-loop.json)
- All conditions are evaluated in-mod: `carrying {item, at_least|less_than}`, `exists {entity, within, at_least}` via `count_entities_filtered` around the body, and `resource_within {resource, within}`. `Conditions.hold` ANDs all keys and returns `false, detail` with a human-readable reason — [CM mod/script/conditions.lua](https://github.com/quartermeat/factorio-crewmate/blob/f466486/mod/script/conditions.lua)
- `stock-coal` loops with `label` and `jump` guarded by `when: {carrying: {item: coal, less_than: $amount}}` and `"limit": 20`. Exceeding the limit fails with "this directive is going round in circles" — [CM directives/stock-coal.json](https://github.com/quartermeat/factorio-crewmate/blob/f466486/directives/stock-coal.json), [CM plan.lua](https://github.com/quartermeat/factorio-crewmate/blob/f466486/mod/script/plan.lua)
- The `check_power` step fails the plan with "the %s are not on the %s's network -- the pole run did not join up". The README's rationale: "A directive that reports 'done' when the pole run never joined up is worse than one that admits it" — [CM plan.lua](https://github.com/quartermeat/factorio-crewmate/blob/f466486/mod/script/plan.lua)
- `make` rewrites its own plan: it expands the recipe to raw materials, spends what's carried, and splices the needed `mine` steps ahead of `craft`. "The plan is data, so a step can write more steps." Recipes that need a machine are refused up front with the missing item named — [CM README](https://github.com/quartermeat/factorio-crewmate/blob/f466486/README.md)
- `requires_recipes` gates availability against `LuaRecipe.enabled` per force. `/crew do` lists unavailable directives under "not yet" with the missing recipe — [CM mod/script/api.lua](https://github.com/quartermeat/factorio-crewmate/blob/f466486/mod/script/api.lua)
- AGENTS.md rules: "Prefer a condition to a decision made elsewhere… that belongs in `when`, not in a prompt." "Directives are data… If it cannot be expressed in the existing verbs, add a verb." "Layout belongs in blueprint strings" — [CM AGENTS.md](https://github.com/quartermeat/factorio-crewmate/blob/f466486/AGENTS.md)

**Codex**
- The package schema is strict zod: `package_id, serves: NOW|NEXT, intent (≤240 chars), after_package_id, source_tick, anchor{x,y}, required_items (≤16), steps (packageStepSchema, ≤MAX_PLAN_STEPS), success_check (text ≤240), notes (≤3 notebook paths), verify (1–3 metrics), surface`.
- Limits: at most 2 packages per update, at most 8192 bytes of package JSON in total, and research at most 7 technologies.
- Dependency cycles between packages are rejected.
- Source: [CX companion/src/coordination/ledger.ts](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/companion/src/coordination/ledger.ts)
- Verify metrics: `{item, per_min_at_least, surface?}` read from the game's production statistics over the last minute, or `{line_at:{x,y}, state ∈ LINE_STATES}`. The pilot's bridge measures "once, 2 minutes of game time after the package's plan ends".
- Outcome events are `package_verified` / `package_unmet`, or `not_measured` if the plan failed. "Measurement only: nothing is fixed or queued again" — [CX ledger.ts VERIFY_RULE](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/companion/src/coordination/ledger.ts)
- Plan steps (about 30): `walk_to, mine, pickup_items, place_entity, craft_items, insert_items, extract_items, set_recipe, rotate_entity, inspect_entities, wait_for_item, wait_for_research, get_items, build_layout, explore, move_entity, blueprint_place, build_ghosts, deconstruct_area, upgrade_area, copy_settings, configure_entity, place_tiles, set_requests, create_platform, launch_rocket, set_platform_route, travel, equip, flush_fluid`.
- Plans are "sequential and nontransactional: completed steps stay committed". `after_plan_id` chains plans, and a successor is cancelled if its predecessor fails — [CX README](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/README.md)
- The strategist must dry-run every layout with `check_only: true` before publishing. The dry run reports `on_ore`, `mixed_ore`, `open_fluid_ports`, `port_fluids` and `belt_joins` — [CX GOAL-STRATEGIST-v1.md](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/.agents/skills/factorio-player/GOAL-STRATEGIST-v1.md)
- Priorities NOW/NEXT/LATER each have only `objective, strategic_reason, completion_condition, essential_prerequisite` (≤160 chars) and are "coordinate-free" — [CX GOAL-STRATEGIST-v1.md](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/.agents/skills/factorio-player/GOAL-STRATEGIST-v1.md)

**Alina**
- The model output schema (`protocol-v1.schema.json`) is `{version:1, request_id, intent ∈ {mine_resource, resolve_shortage, repair_power, continue_factory, respond_only}, reply (≤240), requires_confirmation, actions (maxItems 1)}`. Args are tightly typed: `mineResourceArgs.amount` is an integer from 1 to 100 — [AL schemas/protocol-v1.schema.json](https://github.com/KORTY-DEV/alina-ai-teammate/blob/99e72d4/schemas/protocol-v1.schema.json)
- Checks are hard-coded in executors:
  - An upgrade measures output for 900 ticks before and after an atomic fast-replace and rolls back if the gain is under 2%.
  - Construction "completes only after an observed result".
  - Acquisition fails if the item count doesn't grow within 900 ticks.
  - Sources: [AL docs/ARCHITECTURE.md](https://github.com/KORTY-DEV/alina-ai-teammate/blob/99e72d4/docs/ARCHITECTURE.md), [AL scripts/executor/acquisition.lua](https://github.com/KORTY-DEV/alina-ai-teammate/blob/99e72d4/factorio-mod/alina-ai-teammate_0.1.0/scripts/executor/acquisition.lua)

### Inferences
- Claude Crew's `done_when` checks (`ghosts_cleared / working / exists / rate`) line up as follows:
  - Crewmate's `exists` matches Crew's `exists`.
  - Codex's `{item, per_min_at_least}` matches `rate`.
  - Codex's `{line_at, state}` is roughly a richer `working`, since it carries a cause such as starved, output_full or no_power.
  - Crewmate's `check_power` (same electric network) is a check Claude Crew lacks and should consider: a cheap `connected`/`powered` check catches the commonest silent failure.
- Codex's deliberate choice to measure but never auto-fix leaves repair to the strategist. That matches Crew's escalate-to-coordinator path. Codex adds a fixed **2-game-minute settle delay** before measuring, which Crew's `rate` check should copy if it doesn't have one.
- Crewmate's `when`/`label`/`jump`/`include` gives work orders internal control flow without a model. Claude Crew's plan kinds don't appear to have conditional steps. A `when` guard on a work-order step, such as "only if carrying < N", is a cheap addition.
- Crewmate's "marks" (named positions resolved at runtime) and Codex's `anchor` plus relative layout match Claude Crew's zone plus stamp/paste.

### Gaps
- I didn't read Codex's `packageStepSchema` (in `companion/src/mcp/runPlan.ts`) field by field.

## Q4. Controller / scripted-loop layer: what runs without a model; how failures escalate

### Takeaway
- **Crewmate** runs everything without a model. On failure the plan just **stops, records why and announces it in chat**; a human or an MCP-connected agent picks it up via `plan_status`. There is no automatic model call.
- **Codex** gives the mod in-action recoveries (one re-approach, one partial-insert retry, step off belts or footprints), FIFO plans, auto-supply and upkeep. Failures flow up as typed `next_event` codes with a `repeat` counter to a permanently looping low-effort pilot, then to the strategist for package redesign.
- **Alina** is fully deterministic with timeouts and transactional rollback. The LLM is never in the failure path.

### Cited Findings

**Crewmate**
- `fail()` sets `plan.state="failed"`, records the reason, halts the body and announces "stopped at step %d of %d: %s". Timeouts: `STEP_TIMEOUT = 60*60` ticks (1 minute of no progress) and `BUILD_TIMEOUT` of 4 minutes — [CM plan.lua](https://github.com/quartermeat/factorio-crewmate/blob/f466486/mod/script/plan.lua)
- `build_ghosts` builds the nearest reachable ghost. If a ghost can't be reached within `REACH_ATTEMPT` it is set aside (`plan.unreachable[key]=true`, "Setting one aside is progress"). The step finishes with "built what I could; N pieces I could not get to or place" rather than failing. A spot taken since it was marked is skipped, not fatal — [CM plan.lua](https://github.com/quartermeat/factorio-crewmate/blob/f466486/mod/script/plan.lua)
- Ore hunting: "Fifteen seconds without gaining ground sets that one aside and tries the next nearest". The search widens in rings out to 512 tiles and reports what it can see — [CM README](https://github.com/quartermeat/factorio-crewmate/blob/f466486/README.md)
- Philosophy, from AGENTS.md: "When something goes wrong the runner stops, records why, and says so in chat -- that is the point at which a person or an agent is worth involving. Adding a feature that needs a model in the loop to work at all is going the wrong way." Also: "A game-side failure is a tool result flagged `isError`, never a protocol error" — [CM AGENTS.md](https://github.com/quartermeat/factorio-crewmate/blob/f466486/AGENTS.md)
- Personalities add model-free standing orders, for example Sparks runs `mine-coal` every 600 ticks `when carrying coal < 50`, plus a research path steered via `force.add_research` — [CM personalities/sparks.json](https://github.com/quartermeat/factorio-crewmate/blob/f466486/personalities/sparks.json), [CM mod/script/personality.lua](https://github.com/quartermeat/factorio-crewmate/blob/f466486/mod/script/personality.lua)

**Codex**
- In-action recoveries: "Stepping off a belt, leaving a placement footprint, mining an owned blocker that encloses the body, one re-approach after an out-of-reach result, and one retry of a partial insert happen inside the action" — [CX README](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/README.md)
- Auto-supply fails with `SUPPLY_SHORTFALL`, listing each missing item and why, plus `rate_per_min` and `expected_minutes` from own lines that make it. `build_layout` "fetches its whole bill in one supply before the first placement" and fails `LAYOUT_CHECK_FAILED` with nothing placed — [CX README](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/README.md)
- Repeat counter: "a failed or partial step's code, kept per action and target in storage.repeats… the n-th repeat = n". It is surfaced on `plan_ended` as `repeat` — [CX scripts/tasks.lua](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/mod/agentic-companion/scripts/tasks.lua)
- `next_event` long-polls for up to 25 s. Event types: `plan_ended, research_finished, queue_empty, new_problem, watch_fired, entities_lost, package_failed, orders_changed, human_hold_started/ended, rocket_*`, platform and travel events, or `timeout`. Watches: up to 16 per role on rates — [CX README](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/README.md)
- Escalation ladder:
  - The pilot handles a failed or partial own plan, an empty queue ("never wait for a package with an empty queue"), and judgment calls. On `package_failed`, it must "leave the redesign to the strategist and never rebuild a package's purpose or geometry yourself".
  - The strategist "on `package_failed`, redesign[s] from fresh reads; never resubmit it unchanged".
  - Sources: [CX GOAL-PILOT-v1.md](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/.agents/skills/factorio-player/GOAL-PILOT-v1.md), [CX GOAL-STRATEGIST-v1.md](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/.agents/skills/factorio-player/GOAL-STRATEGIST-v1.md)
- Upkeep runs while no queued plan needs the body: it refuels dry or low burners within 96 tiles and brings the current research's packs to labs, as plans with source `upkeep`. A queued plan pre-empts it at the next step boundary — [CX README](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/README.md)
- AGENTS.md rule: "Anything deterministic (monitoring, supply, recoveries, layout arithmetic, upkeep) belongs in the mod as a tool, not in the bots' instructions" — [CX AGENTS.md](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/AGENTS.md)

**Alina**
- Construction is a transaction. `construction/transaction.lua` records created entities, ghosts and fast-replacements, keyed by surface, force, position and unit_number. Rollback removes only this task's entities, preserves anything a player changed, and reverts fast-replacements — [AL docs/ARCHITECTURE.md](https://github.com/KORTY-DEV/alina-ai-teammate/blob/99e72d4/docs/ARCHITECTURE.md), [AL scripts/construction/transaction.lua](https://github.com/KORTY-DEV/alina-ai-teammate/blob/99e72d4/factorio-mod/alina-ai-teammate_0.1.0/scripts/construction/transaction.lua)
- Acquisition plans dependencies before moving: (1) a ready item from an accessible chest or machine output; (2) mine raw; (3) short hand-craft; (4) heavy craft only in a "free, empty, unconnected" assembler. "A working player line is not captured and its inserters are not switched off" — [AL docs/ARCHITECTURE.md](https://github.com/KORTY-DEV/alina-ai-teammate/blob/99e72d4/docs/ARCHITECTURE.md)

### Inferences
- Claude Crew's ladder (3 local retries → 2 model attempts → escalate) is more automatic than Crewmate's stop-and-announce and similar in shape to Codex's ladder (mod recoveries → pilot → strategist). Codex keeps the pilot as an always-on model loop, though, not an exception-only caller.
- Ideas Crew could adopt:
  - Codex's persistent per-(action, target) `repeat` counter, which stops a model from retrying the same failure.
  - Codex's all-or-nothing bill-of-materials pre-fetch before the first placement (`LAYOUT_CHECK_FAILED` with nothing placed).
  - Crewmate's "set aside unreachable ghost and finish with a partial report" behaviour. These map directly onto Crew's local-retry tier.
- Alina's transaction/rollback ledger of agent-owned entities is the strongest "protect human builds" mechanism of the three, but only the idea can be reused (license).

### Gaps
- I didn't measure how often the Codex pilot gets woken: its token cost per hour and its idle share. Those are in the telemetry docs and weren't extracted.

## Q5. Two-model split (strategist vs fast executor) and model/effort choices

### Takeaway
- Only **Codex** has a two-model split:
  - Strategist: `gpt-6.1-sol`, medium reasoning, read-only MCP, sole ledger writer.
  - Pilot: `gpt-6-luna`, low reasoning, "fast mode", sole gameplay writer, sits in a `next_event` loop.
- This is Claude Crew's Opus coordinator + small-actor split, but with **one body**. The ledger file is the only channel, there is a strict single-writer fence on each side, and the pilot is a continuous loop rather than exception-only.
- **Crewmate** has no built-in model.
- **Alina** uses one small local model (`qwen3.5:4b`, temperature 0, `think:false`, strict JSON schema) for rare intents only.

### Cited Findings
- Codex roles are recorded in `run-identity.json`: `{"id":"pilot","model":"gpt-6-luna","reasoning":"low","fast":true,"ledger_writer":false}` and `{"id":"strategist","model":"gpt-6.1-sol","reasoning":"medium","fast":false,"ledger_writer":true}`. Allowed models are `gpt-6-luna, gpt-6.1-sol, gpt-6-sol, gpt-6-astra` — [CX README](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/README.md)
- Both sessions launch with isolation flags: `web_search="disabled"`, `agents.enabled=false`, `features.memories=false`, `features.multi_agent_v2=false`. The planner gets only the `factorio-readonly` MCP server, where 4 build tools are forced dry-run — [CX README](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/README.md), [CX .codex/config.toml](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/.codex/config.toml)
- "The pilot validates advice against newer physical evidence and continues fail-open when the strategist or the ledger is stale or unavailable" — [CX AGENT-PLAY-PERFORMANCE.md](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/docs/AGENT-PLAY-PERFORMANCE.md)
- Package delivery is model-free. The pilot's MCP process (`--role pilot`) "about once a second… reads the ledger and queues each new package into the body's FIFO, in ledger order, after the mod's placement check". Research in the ledger is queued the same way — [CX README](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/README.md)
- The strategist's reasoning summaries are relayed to an in-game panel (the "thought feed", at most 1 line/s, ≤600 chars). That is output only: "game chat never controls the bot" — [CX README](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/README.md)
- There is an opt-in benchmark campaign: "fresh twenty-minute benchmark campaign with one to four reasoning sessions, varied GPT-6 profiles and a fixed native cutoff" — [CX README](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/README.md), [CX docs/BENCHMARK-CAMPAIGN.md](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/docs/BENCHMARK-CAMPAIGN.md)
- Alina's Ollama call sets `think = false`, `format = decisionSchema`, `temperature = 0.0` and `keep_alive` from config (the docs say `keep_alive: 0` frees VRAM after each decision).
  - The model was chosen for VRAM next to Factorio: a 7612 MiB peak with Factorio on High sprites on an 8 GB card. Cold answers take about 6.6–6.8 s, of which about 4.0–4.3 s is model load. 8B/9B models were rejected on VRAM.
  - Sources: [AL bridge/Alina.Bridge/Ollama/OllamaClient.cs](https://github.com/KORTY-DEV/alina-ai-teammate/blob/99e72d4/bridge/Alina.Bridge/Ollama/OllamaClient.cs), [AL docs/MODEL_SELECTION.md](https://github.com/KORTY-DEV/alina-ai-teammate/blob/99e72d4/docs/MODEL_SELECTION.md)
- Alina's `IntentRouter` pre-classifies Russian commands with keyword lists ("не хватает", "добуд", "продолжай развивать базу"…) before any model call, and the plan is then checked by `PlanValidator` — [AL bridge/Alina.Bridge/Planning/IntentRouter.cs](https://github.com/KORTY-DEV/alina-ai-teammate/blob/99e72d4/bridge/Alina.Bridge/Planning/IntentRouter.cs), [AL PlanValidator.cs](https://github.com/KORTY-DEV/alina-ai-teammate/blob/99e72d4/bridge/Alina.Bridge/Planning/PlanValidator.cs)
- Crewmate deliberately has no model: "Do not build a general planner… the interesting version of that is a small local model collapsing a big tree into a few steps" (future) — [CM AGENTS.md](https://github.com/quartermeat/factorio-crewmate/blob/f466486/AGENTS.md)

### Inferences
- Codex shows the strategist/foreman split works with a mid-effort planner and a low-effort fast executor on the same game version. It validates Claude Crew's Opus coordinator + small actor-model choice in principle.
- Two Codex patterns worth copying:
  - The strategist gets a **mechanically read-only tool surface**, with build tools forced to dry-run. Crew's coordinator should be equally unable to move bodies.
  - The **ledger as the only channel**, with a strict schema and byte caps: 8 KB of packages, ≤2 per update.
- Where Codex differs, and why Crew's choice is probably better for multi-actor:
  - The Codex pilot loops continuously on `next_event`, so the model is part of the engine.
  - Crew calls actor models only on exceptions. That is cheaper and scales to several actors.
- Alina's keyword router before the model is a cheap trick for Crew's chat: deterministic parsing of `@name come/stop/mine X` before spending a model call.

### Gaps
- I found no published token or cost figures per role for Codex in the files read.
- The `gpt-6*` model names are as written in the repo. I didn't independently verify those models.

## Q6. Multiplayer safety: desync, yielding to humans, protecting human builds, chat commands

### Takeaway
- **Alina** has the most complete "co-op with humans" safety model:
  - player-activity cells expire after 30 s and block Alina within about 20 tiles;
  - owner-only protected areas;
  - transactional rollback of only her own entities;
  - research pause and priority ownership;
  - the LLM/UDP path fails closed whenever `game.is_multiplayer()`;
  - E2E tests check for no `desync-report-*.zip`.
- **Codex** isn't co-op: every non-Codex client is forced to a characterless spectator and their character is destroyed. A human "yields" only by taking over the Codex body; real inputs park the FIFO and it resumes about 5 s after the last input. Game chat never controls the bot.
- **Crewmate** runs on a dedicated server with humans joining, has a `/crew` command set, and documents the `on_load` desync trap. It has no permissions or protection yet.

### Cited Findings

**Alina**
- `Conflict.mark_player_activity` stores per 16×16 cell `{expires_tick = game.tick + seconds*60}`, where `alina-player-active-seconds` defaults to 30. `is_blocked` checks protected areas, then any fresh human activity within `ACTIVE_RADIUS = 20` across the 5×5 neighbouring cells.
- In-code comment: "A direct order can change Alina's goal, but it never grants permission to build over any human's fresh work."
- Protected areas can be removed only by their `owner_player_index`.
- Source: [AL scripts/conflict/manager.lua](https://github.com/KORTY-DEV/alina-ai-teammate/blob/99e72d4/factorio-mod/alina-ai-teammate_0.1.0/scripts/conflict/manager.lua)
- Activity is fed from `on_built_entity, on_robot_built_entity, on_player_mined_entity, on_robot_mined_entity, on_player_rotated_entity, on_entity_settings_pasted`, among others — [AL control.lua](https://github.com/KORTY-DEV/alina-ai-teammate/blob/99e72d4/factorio-mod/alina-ai-teammate_0.1.0/control.lua)
- Placement re-checks right before acting: `Conflict.is_blocked(...)` and then `can_place_entity`. Otherwise it reports "Выбранное место заняли до строительства; ничего не перезаписываю" ("someone took the spot before construction; I'm not overwriting anything") — [AL scripts/executor/building.lua](https://github.com/KORTY-DEV/alina-ai-teammate/blob/99e72d4/factorio-mod/alina-ai-teammate_0.1.0/scripts/executor/building.lua)
- `IncomingUdp.poll`: `if game.is_multiplayer() then root.bridge.status = "multiplayer_safe"; root.bridge.udp_disabled = true; return end`. Architecture doc: "In multiplayer external changes go through Factorio's synchronized server input; clients do not apply private UDP commands" — [AL scripts/core/incoming_udp.lua](https://github.com/KORTY-DEV/alina-ai-teammate/blob/99e72d4/factorio-mod/alina-ai-teammate_0.1.0/scripts/core/incoming_udp.lua), [AL docs/ARCHITECTURE.md](https://github.com/KORTY-DEV/alina-ai-teammate/blob/99e72d4/docs/ARCHITECTURE.md)
- Multiplayer tests:
  - README claim: "host + 2 clients, disconnect/rejoin, no desync report". CURRENT_STATUS details 3 `InGame` transitions, 3 joins, 0 connection refusals, and no desync report.
  - The rail-safety script verifiably throws if `desync-report-*.zip` appears in the client archive.
  - `Test-Project.ps1` contains two `--mp-connect` client launches. I didn't trace the full two-client flow.
  - Sources: [AL scripts/Test-AlinaRailSafety.ps1](https://github.com/KORTY-DEV/alina-ai-teammate/blob/99e72d4/scripts/Test-AlinaRailSafety.ps1), [AL docs/CURRENT_STATUS.md](https://github.com/KORTY-DEV/alina-ai-teammate/blob/99e72d4/docs/CURRENT_STATUS.md)
- Chat: name aliases "Алина/Аля/Алечка" plus custom aliases from a setting. A direct router handles protect, unprotect, research pause, priority, markers and "continue developing the base". Research respects a manual player choice ("Ручной выбор игрока не заменяется" — a player's manual choice is never overridden) — [AL scripts/core/names.lua](https://github.com/KORTY-DEV/alina-ai-teammate/blob/99e72d4/factorio-mod/alina-ai-teammate_0.1.0/scripts/core/names.lua), [AL scripts/chat/direct_router.lua](https://github.com/KORTY-DEV/alina-ai-teammate/blob/99e72d4/factorio-mod/alina-ai-teammate_0.1.0/scripts/chat/direct_router.lua)

**Codex**
- `make_viewer`: "All non-Codex clients are viewers… destroying the detached join character prevents a second physical body". It runs `player.set_controller({type = defines.controllers.spectator})` and `detached.destroy()`. Spectators are teleported to follow the body — [CX scripts/companion.lua](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/mod/agentic-companion/scripts/companion.lua)
- Human takeover:
  - `data.lua` links a keyless custom input to about 40 game controls (move, mine, build, open-gui, craft, …), listed in `human_inputs.lua`.
  - Real input "parks the FIFO; nothing is cancelled", and work resumes about 5 s after the last input. Hovering, map view and camera never park it. `human_hold_started/ended` events are emitted.
  - To tell human walking from its own walking, the mod records every `walking_state` it commands and treats anything else as human input.
  - Sources: [CX scripts/human_inputs.lua](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/mod/agentic-companion/scripts/human_inputs.lua), [CX README](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/README.md)
- AGENTS.md non-goals include "game-chat control" and "multiple controllable bodies or gameplay writers". There is no `on_console_chat` handler in the mod (grep found none) — [CX AGENTS.md](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/AGENTS.md)
- The supported save is "permanently peaceful": no enemy bases on Nauvis, no demolishers on Vulcanus — [CX README](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/README.md)

**Crewmate**
- Desync lesson: "Never register an event handler in `script.on_load`… every join fails with `script-event-mismatch`". Fix: do first-tick work from an always-registered handler (`Plan.on_first_tick`). Shipped as `v0.9.1: stop breaking multiplayer joins from on_load` — [CM AGENTS.md](https://github.com/quartermeat/factorio-crewmate/blob/f466486/AGENTS.md)
- `/crew` and `/agent` commands: `come, take <item> [n], give, do [<directive>], mine <ore> [n], stop, personality`. `/crew take` moves the player's own items into the character, because "Factorio has no way to put items into another character's inventory". Chat is captured via `on_console_chat` for the bridge's `crew_hear` — [CM README](https://github.com/quartermeat/factorio-crewmate/blob/f466486/README.md), [CM mod/script/senses.lua](https://github.com/quartermeat/factorio-crewmate/blob/f466486/mod/script/senses.lua)
- Operational gotchas from the README:
  - `game.reload_mods()` does nothing in multiplayer, so a mod edit means a server bounce (about 1.6 s).
  - Bumping `info.json` without a restart traps clients in a mod-sync loop.
  - Hosting a save rewrites `mod-list.json`.
  - Stop the headless server with SIGTERM, not SIGINT, which leaves a half-quit state.
  - Lua empty tables serialise as `{}`, so the bridge rewrites them to `[]`.
  - Source: [CM README](https://github.com/quartermeat/factorio-crewmate/blob/f466486/README.md), [CM AGENTS.md](https://github.com/quartermeat/factorio-crewmate/blob/f466486/AGENTS.md)

### Inferences
- For Claude Crew's "play alongside humans", Alina's model is the one to emulate:
  - expiring human-activity cells, fed from build/mine/rotate/paste events, that block agent placement nearby;
  - owner-only protected zones settable from chat;
  - an agent-owned entity registry so rollback or deconstruct never touches human builds;
  - a re-check of block status and `can_place` at the moment of placement, not only at planning time.
- Codex's input-park-and-resume is a nice pattern if Crew ever lets a human puppet an actor. Its spectator-only policy is the opposite of Crew's goal.
- Crew should add a desync regression test in the style of Alina and Crewmate: host plus a real client, do work, assert no `desync-report-*.zip`. It should also keep the no-`on_load`-registration rule.

### Gaps
- I couldn't verify from the visible PowerShell that the Alina 2-client test exercises the agent building while both clients are connected. That rests on the doc claim.

## Q7. Space Age support

### Takeaway
- **Codex** has real Space Age support: rocket launches, platform creation and routing, the body travelling by rocket and landing pod, per-surface factory status, Aquilo `frozen`, Gleba nutrients as fuel, and quality. The goal is a rocket launch, with "solar system edge" as the long goal.
- **Alina** loads with Space Age but says "planets: not in 0.1.0".
- **Crewmate** only handles Space Age crafting categories and lists platforms in status.

### Cited Findings
- Codex requires Space Age. Every save enables `space-age`, `quality` and `elevated-rails`.
  - Tools: `create_platform, launch_rocket, set_platform_route, travel, platform_status`.
  - The body travels "by rocket up to a platform, aboard while it flies its route, and down by pod". Platforms are built remotely from ghosts their hub fulfils, "as the game's remote view allows".
  - Machines on Aquilo show `frozen`, and biochambers are refuelled with nutrients.
  - Sources: [CX README](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/README.md), [CX NOTICE.md](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/NOTICE.md)
- The rocket/platform stage landed on 2026-10-05 (`feat: 0.22.2 stage B, rocket launches and space platforms`). Tests include `platforms_test.lua`, `platform_building_test.lua`, `rocket_launch_test.lua`, `planet_roots_test.lua`, `multi_surface_reads_test.lua` and `surface_conditions_test.lua` — [CX tests/mod](https://github.com/LukaVodopivec/factorio-codex/tree/90de437/tests/mod)
- Alina's roadmap: "🪐 Planets | not in 0.1.0". It was tested on a K2SO-modded save — [AL README](https://github.com/KORTY-DEV/alina-ai-teammate/blob/99e72d4/README.md)
- Crewmate: "Hand-craftability is not `category == "crafting"`. In Space Age a transport belt is category "pressing"… The character prototype's `crafting_categories` is the only correct answer." Personality steering knows that "steam-power unlocks by crafting 50 iron-plate, not by research" (Space Age trigger techs) — [CM README](https://github.com/quartermeat/factorio-crewmate/blob/f466486/README.md), [CM mod/script/craft.lua](https://github.com/quartermeat/factorio-crewmate/blob/f466486/mod/script/craft.lua)

### Inferences
- If Claude Crew's late-game tools need platforms or planets, Codex's `platforms.lua` (53 KB), `actions/travel.lua` and `actions/rocket.lua` are MIT-licensed, written against 2.0.77, and the best available reference by a wide margin.
- Crewmate's crafting-category and trigger-tech notes are cheap correctness fixes Crew should check it already has.

### Gaps
- I didn't confirm whether Codex has actually achieved a first rocket launch in a recorded run. Docs and tests cover the `rocket_launched` milestone, and a test parses a run_snapshot "through… a rocket launch", but I found no recorded live launch result in the files read.

## Q8. Legit vs cheat actions (code quotes)

### Takeaway
- All three place entities with `surface.create_entity` (or `ghost.revive`) and then **remove one item from the body's inventory**, gated by reach and `can_place_entity`. None uses a player's `build_from_cursor`. This is the same "legit by convention" pattern Claude Crew likely uses.
- Mining differs:
  - **Codex** drives native `mining_state` on a real player's character.
  - **Crewmate** decrements `resource.amount` by script, paced by game mining time.
  - **Alina** sets `mining_state` on a player-less character and watches for inventory growth.
- Crewmate states explicitly that `mining_state` is ignored without an attached player, which conflicts with Alina's approach; see Gaps.

### Cited Findings
- Crewmate ghost build, from `Hands.build_nearest_ghost`: `if Hands.carrying(body, item) < 1 then return nil, "I have no " .. item end … local _, built = closest.revive{raise_revive = true} … body.get_main_inventory().remove{name = item, count = 1}`. It steps off the footprint first, because "A player gets shoved aside when they build where they stand; a scripted revive just fails." — [CM mod/script/hands.lua](https://github.com/quartermeat/factorio-crewmate/blob/f466486/mod/script/hands.lua)
- Crewmate hand mining: `if entity.type == "resource" and entity.amount and entity.amount > 1 then entity.amount = entity.amount - 1; inventory.insert{name = product, count = 1} elseif not entity.mine{inventory = inventory, raise_destroyed = true} then …`.
  - Pacing is `mining_ticks = max(6, floor(mining_time / character.mining_speed * 60))`, checked against `resource_reach_distance`.
  - The rationale is in the code comment: "A character with no player attached ignores mining_state -- that logic lives in the player controller -- so the digging is scripted, but paced by the same numbers the game would use."
  - Source: [CM mod/script/hands.lua](https://github.com/quartermeat/factorio-crewmate/blob/f466486/mod/script/hands.lua)
- Crewmate crafting uses the real queue: `body.begin_crafting{count = count, recipe = recipe.name, silent = true}` — [CM mod/script/craft.lua](https://github.com/quartermeat/factorio-crewmate/blob/f466486/mod/script/craft.lua)
- Crewmate principle: "No cheat mode, no indestructible flag, no teleporting where walking would do, nothing spawned from nothing" — [CM README](https://github.com/quartermeat/factorio-crewmate/blob/f466486/README.md)
- Codex placement (`actions/build.lua`): after `placement_geometry.can_place(...)` and an approach to `build_distance`, it runs `local built = c.surface.create_entity({ name = task._entity_name, position = task.position, direction = task.direction, …, force = c.force, raise_built = true })` and then `c.remove_item({ name = task.item, count = 1 })` — [CX scripts/actions/build.lua](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/mod/agentic-companion/scripts/actions/build.lua)
- Codex mining uses native `c.mining_state = { mining = true, position = e.position }` with `selected` set and `can_reach_entity` checks. This works natively because the body is a connected player. "The mod never creates, replaces or teleports that character." Its only `teleport` call moves spectators to follow the body — [CX scripts/actions/mine.lua](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/mod/agentic-companion/scripts/actions/mine.lua), [CX scripts/companion.lua](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/mod/agentic-companion/scripts/companion.lua)
- Codex exceptions, stated explicitly in AGENTS.md: "Space platforms are the exception: `create_platform` and steps that name a `platform` act on that platform without the body, as the game's remote view does". `flush_fluid` destroys fluid. A supervisor "teleport recovery" exists only as an operator action that marks a run `assisted`, which is excluded from benchmark verdicts — [CX AGENTS.md](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/AGENTS.md), [CX README](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/README.md)
- Alina placement: `local removed = agent.remove_item({name = building.item_name, count = building.item_count}) … local entity = agent.surface.create_entity({ name = building.entity_name, position = building.position, force = agent.force, raise_built = true, create_build_effect_smoke = true })`. The item is refunded if placement fails. It navigates to `build_distance - 1` first — [AL scripts/executor/building.lua](https://github.com/KORTY-DEV/alina-ai-teammate/blob/99e72d4/factorio-mod/alina-ai-teammate_0.1.0/scripts/executor/building.lua)
- Alina mining: `agent.selected = operation.target; agent.mining_state = {mining = true, position = operation.target.position}` on a `create_entity`'d character with no player. It fails if the item count doesn't grow within 900 ticks. Crafting uses `agent.begin_crafting`. Chest and machine transfers are `remove_item`/`insert` pairs within `reach_distance` — [AL scripts/executor/acquisition.lua](https://github.com/KORTY-DEV/alina-ai-teammate/blob/99e72d4/factorio-mod/alina-ai-teammate_0.1.0/scripts/executor/acquisition.lua), [AL scripts/agent/agent.lua](https://github.com/KORTY-DEV/alina-ai-teammate/blob/99e72d4/factorio-mod/alina-ai-teammate_0.1.0/scripts/agent/agent.lua)
- Alina can use construction robots and "her own Spidertron" as transport. `SitePolicy.can_plan` reserves a tree-obstructed site only if it lies inside an active construction network — [AL scripts/construction/site_policy.lua](https://github.com/KORTY-DEV/alina-ai-teammate/blob/99e72d4/factorio-mod/alina-ai-teammate_0.1.0/scripts/construction/site_policy.lua)

### Inferences
- Crewmate's "mining_state is ignored without a player" lesson matters directly for Claude Crew, whose actors are script characters on 2.0.77. Crew either already scripts mining like Crewmate (amount decrement paced by mining_time/mining_speed) or needs to.
- Codex sidesteps the problem by using real players. That needs one game client per body, which isn't viable for "several actors".
- `create_entity` + `remove_item` + reach check is the shared industry pattern. The remaining legit gaps vs a real player are the same everywhere:
  - no build-time animation or delay per entity (Crewmate and Alina place one entity per tick-step);
  - Crewmate scripts mining;
  - Codex acts on platforms without the body via the remote view.

### Gaps
- **Conflict:** Crewmate says (and works around) that `mining_state` on a player-less character "does not stick". Alina relies on exactly that, with a progress timeout, on Factorio 2.1.12. Either 2.1 changed the behaviour, or Alina's mining relies on something else such as `selected` (`agent.selected` is also set), or its mining silently fails and falls back. I couldn't resolve this without running it. Claude Crew should test it on 2.0.77.

## Q9. Results, demos and known issues

### Takeaway
- **Crewmate:** integration tests show an unattended coal → steam → electric-mining loop and hand-gathering. There are no long-run results.
- **Codex:** a long series of supervised 20-minute benchmark runs. The best recorded early run, Candidate B R7, reached about 49 iron plates, Electronics and Steam Power by the 20-minute cutoff, far from a rocket. Since then the work has been relentless hardening, which docs and tests describe. No live rocket launch is evidenced in the files read.
- **Alina:** strong measured claims. A 4-machine gear block was built and verified on a real K2SO save copy, plus a fluids E2E and a megabase endurance test. The figures are self-reported.

### Cited Findings
- Crewmate integration tests: `TestIntegrationDirectiveBuildsPowerBlock`, `TestIntegrationDirectiveClosesTheCoalLoop`, `TestIntegrationInGameRequestStartsADirective`, `TestIntegrationMinesEachStartingMaterial`, `TestIntegrationMakePlansItsOwnMaterials`, `TestIntegrationPersonalitySteersResearchAndActs`, among others — [CM bridge/integration_test.go](https://github.com/quartermeat/factorio-crewmate/blob/f466486/bridge/integration_test.go)
- Codex baselines:
  - "The prior one-shot live baseline required 22 MCP calls for the initial mine/craft/place/fuel/inspect milestone" (Linux 2.0.77, app 0.8.0).
  - Candidate B R7 (2026-09-03): "exact pre-deadline lower bound is therefore 49 processed iron plates… Electronics unlock… This is a satisfactory automation-first progress vector… not rocket completion."
  - Remaining bottlenecks listed: "manual tree-fuel trips, manual chest/furnace transfers, recovery from one initially trapped layout, and master ledger/message lag that produced stale envelopes".
  - Source: [CX docs/AGENT-PLAY-PERFORMANCE.md](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/docs/AGENT-PLAY-PERFORMANCE.md)
- Codex has a run recorder (5-minute samples, thought feed, `runs compare`) and a 4K timelapse of the "first-rocket" rendered client-side — [CX README](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/README.md)
- Alina's figures, all from CURRENT_STATUS (self-reported):
  - A K2SO save copy (SHA-256 `325FB98B…`) got its first `expand_line` task after 1170 ticks: a 4-parallel-machine iron-gear block with buffers, built and verified, with the save hash unchanged afterwards.
  - Fluids E2E: 4 pumpjacks, 4 refineries, 4 chemical plants, 412 pipe elements, 3/3 pumps powered, 159 units of output.
  - Performance A/B on 29,241 entities: +0.0465 ms/tick.
  - Megabase endurance: 34,360 entities, 60 game-minutes, 8 tasks, **1 useful factory change**, 0 desyncs.
  - Stated limits: no trains (crossing only), no planets, the planner is "confident with early and some mid item-based chains", and "free conversation during play is not part of the reliable gameplay contract".
  - Source: [AL docs/CURRENT_STATUS.md](https://github.com/KORTY-DEV/alina-ai-teammate/blob/99e72d4/docs/CURRENT_STATUS.md)

### Inferences
- None of the three shows a multi-hour autonomous run reaching a rocket.
- Codex's measurement discipline is the best template for Crew's benchmark harness with staged saves:
  - immutable baseline save SHA, fixed GO tick and deadline;
  - frozen post-deadline snapshot;
  - "assisted" runs excluded from verdicts.
- Alina's "1 useful change in 60 min" on a megabase shows how conservative a deterministic-only teammate ends up being.

### Gaps
- No video or demo links were found for any project in the files read.

## Q10. What each does better than Claude Crew, what to borrow, and adopt/fork vs own design

### Takeaway
- **Don't adopt or fork any of them wholesale.** None supports several model-driven script characters co-playing with humans and commanded from chat, which is Claude Crew's core. Codex explicitly makes that a non-goal (one body, spectators only, no chat control).
- **Codex (MIT, 2.0.77) is a code quarry**, especially line-state tracking, auto-supply/BOM pre-fetch, the repeat counter, placement geometry, platforms and travel, the tick-budget job runner and benchmark discipline.
- **Crewmate is an idea quarry** for the directive format and Factorio gotchas (no license, so no code).
- **Alina is an idea-only reference** (all rights reserved; 2.1 API) for human-protection and transactional rollback.

### Cited Findings
- Codex non-goals: "multiple controllable bodies or gameplay writers… game-chat control… built-in model loops" — [CX AGENTS.md](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/AGENTS.md)
- Alina license forbids derivative works — [AL LICENSE](https://github.com/KORTY-DEV/alina-ai-teammate/blob/99e72d4/LICENSE)
- Crewmate has no LICENSE file — [repo](https://github.com/quartermeat/factorio-crewmate)

**Candidates to borrow from Codex (MIT, copy with attribution):**
- `scripts/autonomy.lua` and `factory_status.lua`: line grouping and line states with `cause`, `rate_per_min/max_per_min/utilisation`, `hand_fed/self_sustaining`. These are a ready-made backend for Crew's `working` and `rate` checks and for coordinator observations.
- `scripts/actions/supply.lua` (74 KB): fetch → smelt → hand-craft up to 4 levels → hand-gather, with `SUPPLY_SHORTFALL` reasons and ETA from own lines.
- `build_layout` whole-bill pre-supply with `LAYOUT_CHECK_FAILED`/nothing-placed semantics.
- The dry-run diagnostics `on_ore/mixed_ore/open_fluid_ports/port_fluids/belt_joins`.
- `scripts/jobs.lua`: tick-budgeted jobs (about 8 ms/tick).
- `scripts/tasks.lua`: per-(action, target) `storage.repeats` counter.
- `scripts/watches.lua`: rate watches that fire once and re-arm.
- `scripts/platforms.lua`, `actions/travel.lua`, `actions/rocket.lua` for Space Age.
- `companion/src/coordination/ledger.ts`: a strict-schema single-writer ledger with byte caps and a `--schema` help output.
- `writer-fence.test.ts` / `writer_fence_test.lua`: proof that only one role can write.
- Run-recorder and benchmark-campaign methodology.
- Sources: [CX README](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/README.md), [CX ledger.ts](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/companion/src/coordination/ledger.ts), [CX AGENTS.md](https://github.com/LukaVodopivec/factorio-codex/blob/90de437/AGENTS.md)

**Ideas from Crewmate:**
- `when` guards with `label`/`jump` (with a loop `limit`) and `include` with `$param` aliasing in work orders.
- Named marks that steps write and later steps read.
- `check_power` same-network verification.
- `requires_recipes` gating against `LuaRecipe.enabled`.
- A `make` step that splices raw-material gathering into the plan.
- "Build the far end of a site first" (nearest-first walls the body in).
- `can_place_entity` ignores ghosts, so footprints should be checked for existing ghosts when laying plans.
- Step off the footprint before revive.
- A 15 s no-progress rule to set aside unreachable ore.
- `create_entities_from_blueprint_string` "only works in menu simulations", so place ghosts individually.
- No event registration in `on_load`.
- `/c` vs mod `storage` contexts.
- Source: [CM README](https://github.com/quartermeat/factorio-crewmate/blob/f466486/README.md), [CM AGENTS.md](https://github.com/quartermeat/factorio-crewmate/blob/f466486/AGENTS.md)

**Ideas from Alina:**
- Expiring human-activity cells (30 s, radius 20, neighbour-cell check) blocking agent work.
- Owner-only protected areas from chat.
- A transaction log of agent-created entities and fast-replaces for rollback that never touches human-modified entities.
- Measured before/after upgrade with rollback below a 2% gain.
- Acquisition that never steals from a working player line, uses only "free, empty, unconnected" assemblers, and keeps a reserve in chests.
- Normal-quality items only, with quality items never treated as free stock.
- Disable the external model channel when `game.is_multiplayer()` unless input goes through server-synchronised paths.
- Fixed priority order with power-critical first.
- Source: [AL docs/ARCHITECTURE.md](https://github.com/KORTY-DEV/alina-ai-teammate/blob/99e72d4/docs/ARCHITECTURE.md), [AL docs/CURRENT_STATUS.md](https://github.com/KORTY-DEV/alina-ai-teammate/blob/99e72d4/docs/CURRENT_STATUS.md)

### Inferences

**Where each is ahead of Claude Crew:**
- **Crewmate:** a simpler, fully data-driven job language with in-plan control flow; personality-driven standing orders.
- **Codex:** much deeper deterministic chores and observability; Space Age end-to-end; a hardened single-writer coordination contract; serious test coverage (116 test files with a 2.0.77 API mock); benchmark rigour.
- **Alina:** human-coexistence safety and rollback; mod-awareness (runtime prototypes, not vanilla names); a performance budget measured on megabases.

**Where Claude Crew is ahead or different:**
- several bodies;
- chat `@name`/`@all` command;
- characterless coordinator with zones;
- exception-only actor model calls;
- `done_when` checks evaluated in-game as part of a work order rather than measured after the fact.

**Recommendation:**
- Keep Claude Crew's own design.
- Selectively port MIT Codex modules, with attribution to Matteo Mekhail and LukaVodopivec, where they fill gaps: line states for the `working`/`rate` checks, supply/BOM pre-fetch, the repeat counter, tick-budget jobs, platforms and travel.
- Adapt the parts that assume a connected-player body: native `mining_state`, linked-input takeover detection.
- Re-implement Crewmate's and Alina's ideas without copying their code.

### Gaps
- I didn't diff Codex module dependencies, for example how tightly `supply.lua` couples to its `companion.lua` single-body model. The porting effort is unestimated.
- I didn't read Claude Crew's own source for this note. The comparisons rely on the description given in the assignment.
