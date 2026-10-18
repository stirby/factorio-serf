# AI Companion family and Claude-Code-driven Factorio controllers (prior art for Claude Crew)

Research date: 2026-10-18. Scope: (A) AI Companion (mod portal `ai-companion`, repo `lveillard/factorio-ai-companion`); (B) factorioctl (`MarkMcCaskey/factorioctl`); (C) the forum thread "Factorio MCP Server" (t=133392 / p=691527). The thread turned out to be about a fourth codebase, **FactoMCP** (`WidAmi/FactoMCP`), so C is profiled as FactoMCP.

Source snapshots read:
- **A**: The local tarball at `.../scratchpad/src/factorio-ai-companion` **is current upstream `main`**. Its file mtimes (2026-09-13 02:18:57Z) match HEAD `4a37f783`, the PR #3 merge of 2026-09-13T02:18:57Z, and GitHub shows no push since 2026-09-13. The only newer work is open PR #7, which is unmerged. "Yesterday's" tarball is therefore not outdated.
- **B**: Fresh tarball of `main` @ `c3abe9ea` (2026-01-26).
- **C**: Fresh tarball of FactoMCP `HEAD` @ `f223f548` (2026-04-20).
- Nothing was installed or run.

Notation: **[src]** = verified by reading source; **[README]** = the project's own claim; **[inf]** = my inference.

---

## Q1. Identity, version, dates, license, Factorio version, Space Age, popularity, activity, maintainer

### Takeaway
AI Companion on the mod portal and `lveillard/factorio-ai-companion` on GitHub are one project. It was rebuilt in September 2026 (v0.18.x) and has been dormant since 2026-09-13. It is now Codex-first, with Claude Code as an optional MCP client. factorioctl is a one-night "vibe-coded" Rust experiment, frozen since 2026-01-26. The forum thread is about FactoMCP, a small Python MCP server frozen since 2026-04-20. All three are low-traffic hobby projects (10–14 stars each).

### Cited Findings
**A. AI Companion**
- **Same project.** The mod portal entry `ai-companion` (title "AI Companion", owner `lveillard`) lists `source_url` = github.com/lveillard/factorio-ai-companion. The repo's `factorio-mod/info.json` has `"name": "ai-companion"` and `"author": "lveillard"` — [mod portal API](https://mods.factorio.com/api/mods/ai-companion/full); [info.json](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/factorio-mod/info.json)
- **Releases.**
  - 0.13.0: 2026-01-17 (factorio_version 2.0, `base >= 2.0`)
  - 0.18.0: 2026-09-12
  - 0.18.3: 2026-09-13 (`base >= 2.0.77`)
  - The portal's `updated_at` is 2026-09-13T02:23Z. **Stale: no release for ~5 weeks.**
  - [mod portal API](https://mods.factorio.com/api/mods/ai-companion/full)
- **Changelog dates.** Entries 0.1.0–0.13.3 are dated "2025-01-10…2025-01-17". The repo was created 2026-01-17, so those dates are evidently typos for 2026 — [changelog.txt](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/factorio-mod/changelog.txt); [GitHub API](https://api.github.com/repos/lveillard/factorio-ai-companion)
- **License and counts.** MIT. 566 downloads. Portal score −9.6. Portal tags include **"cheats"**, "character", "combat", "manufacturing" — [mod portal API](https://mods.factorio.com/api/mods/ai-companion/full)
- **GitHub stats.** 14 stars, 7 forks, 5 open issues/PRs, created 2026-01-17, last push 2026-09-13T02:53Z. Commit count is **210**, matching yesterday's "~210" (derived from the API pagination `last` page = 210) — [GitHub API](https://api.github.com/repos/lveillard/factorio-ai-companion); [commits](https://github.com/lveillard/factorio-ai-companion/commits/main)
- **Contributors.** Maintainer Loïc Veillard (`lveillard`). Most of the engine came from **Zdendys79's PR #2**: 157 commits, opened 2026-06-25, merged 2026-09-13. Zdendys79 wrote "We've been building an AI agent on top of it", and that fork's commit messages reference a separate (apparently Python) agent ("Task #82 … no Python-visible trace") — [PR #2](https://github.com/lveillard/factorio-ai-companion/pull/2); [fork commits](https://github.com/Zdendys79/factorio-ai-companion/commits)
- **Factorio version.** Targets Factorio 2.0.77+ (README: "Requires Bun 1.4.2+ and Factorio 2.0.77+"). PR #2 claims "Factorio 2.1 compatibility + assorted 2.x API fixes" — [README](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/README.md); [PR #2](https://github.com/lveillard/factorio-ai-companion/pull/2)
- **Space Age.** The mod declares only `base >= 2.0.77`, no space-age dependency. Issue #9's reporter ran it with base, space-age, quality and elevated-rails, so it loads alongside Space Age. Inventory code carries `quality` through transfers. A grep of the mod for "platform"/"space" found nothing, so there is no space-platform-specific logic — [info.json](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/factorio-mod/info.json); [issue #9](https://github.com/lveillard/factorio-ai-companion/issues/9); [building.lua](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/factorio-mod/commands/building.lua) [src]
- **Recent issues.** Open since 2026-10-10: #9 (server crash) and #10 (GUI overflow). Open since 2026-09-13: #6 (research triggers) and PR #7 (automatic GitHub feedback reporting). #1 (Docker/HTTP MCP, 2026-01-29) is still open, although 0.18 implemented it — [issues](https://github.com/lveillard/factorio-ai-companion/issues?q=is%3Aissue)
- **Mod portal discussion tab:** 0 threads — [discussion](https://mods.factorio.com/mod/ai-companion/discussion)

**B. factorioctl**
- **Description:** "CLI to control Factorio + tools for Claude code to play Factorio" — [GitHub API](https://api.github.com/repos/MarkMcCaskey/factorioctl)
- **Repo stats.** Rust. 11 stars, 1 fork, 0 open issues. Created 2026-01-26T05:35Z, last push 2026-01-26T06:57Z. 74 commits, all made on 2026-01-25/26. **Stale ~9 months** — [GitHub API](https://api.github.com/repos/MarkMcCaskey/factorioctl); [commits](https://github.com/MarkMcCaskey/factorioctl/commits/main)
- **License.** README says "MIT", but GitHub reports `license: null` and the tarball has no LICENSE file — [README](https://github.com/MarkMcCaskey/factorioctl/blob/c3abe9ea/README.md) [src]
- **Author's own caveat:** "vibe coded in a weekend from my phone … I haven't even read it." There is a demo video (YouTube TQvqkc7ivIw) — [README](https://github.com/MarkMcCaskey/factorioctl/blob/c3abe9ea/README.md)
- **Factorio version.** Generated Lua uses 2.0 APIs (`prototypes.entity`, `helpers.table_to_json`) but also the pre-2.0 `global` table. `game.surfaces[1]` is hard-coded 41 times in `src/client/lua.rs`, so it has no multi-surface (Space Age) awareness — [lua.rs](https://github.com/MarkMcCaskey/factorioctl/blob/c3abe9ea/src/client/lua.rs) [src]
- No mod portal presence; it is not a mod. No MCP registry listing found (see Gaps).

**C. Forum thread / FactoMCP**
- **Thread.** "Factorio MCP Server", General discussion. Opening post (p=691527) by BeBoxer, 2026-04-21. Five replies, the last 2026-06-24 (ferrybig). The post links github.com/WidAmi/FactoMCP — [forum t=133392](https://forums.factorio.com/viewtopic.php?t=133392); [p=691527](https://forums.factorio.com/viewtopic.php?p=691527)
- **FactoMCP repo.** Python, MIT. 10 stars, 4 forks. Created 2026-04-11, last push 2026-04-20, 11 commits. **Stale ~6 months** — [GitHub API](https://api.github.com/repos/WidAmi/FactoMCP)
- "tested on 2.0" [README]. Single file `server.py`, 55 KB — [README](https://github.com/WidAmi/FactoMCP/blob/f223f548/README.md)

### Inferences
- None of the three is actively maintained today. AI Companion is the only one with a mod portal release, CI, tests and a 2026-09 rebuild.
- Yesterday's "multiple companions not parallelized yet" quote comes from the **mod portal description**, which still describes the January 0.13 Claude-Code-daemon era ("Requires using Claude Code (/model sonnet is fine)… most of them don't work properly yet… They are not parallelized yet"). That text is stale relative to 0.18.3 (see Q3) — [mod portal API](https://mods.factorio.com/api/mods/ai-companion/full)

### Gaps
- I could not date the mod portal description text; the API does not version it.
- Download counts per release are not exposed.

---

## Q2. Architecture: how the LLM is in the loop, transport, models

### Takeaway
- **AI Companion 0.18** is the most engineered of the three:
  - Factorio mod with a tick-driven native job engine.
  - Bun/TypeScript bridge with a single serialized RCON `GameBridge`.
  - One schema (`config/commands.json`) generates the MCP tools, Codex tools, browser forms and the Lua dispatch contract.
  - The built-in agent is **OpenAI Codex app-server** (ChatGPT subscription). Claude Code attaches as an external MCP client.
- **factorioctl** and **FactoMCP** are thin "Claude Code calls an MCP tool → tool sends Lua over RCON" servers with no in-game job engine. The model is in the loop for essentially every step.

### Cited Findings
**A. AI Companion**
- **Layering.** "Keep game actions in Lua, transport serialization in `GameBridge`/RCON, and Codex orchestration in `CompanionSession`. Browser forms and model tools derive from the same schema" — [AGENTS.md](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/AGENTS.md)
- **RCON entry point.** A single structured command, `/fac_api {tool,args}`, which parses JSON with `helpers.json_to_table`. The dispatcher validates `args` against the tool's `inputSchema` and runs declared `before` hooks (e.g. `companion_stop`) — [dispatch.lua L60-77](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/factorio-mod/commands/dispatch.lua) [src]
- **Built-in agent.**
  - Codex app-server, one persistent thread. Default model `gpt-5.6-terra` ([config/agent.json](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/config/agent.json)).
  - Turn limits from `config/settings.ts`: `MAX_TOOL_CALLS` 64/turn, `TURN_TIMEOUT_MS` 180000, `MAX_JOB_CONTINUATIONS` 12, `JOB_REVIEW_TIMEOUT_MS` 300000, `POLL_INTERVAL_MS` 2000, `productionReviewMs` 15000 — [settings.ts](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/config/settings.ts); [session.ts L572-590](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/src/runtime/session.ts) [src]
- **Claude Code / other harnesses.**
  - MCP over Streamable HTTP at `/mcp`, bearer token, protocol 2026-07-28 via MCP SDK 2.0.0 ("explicitly rejects older protocol handshakes"). There is also a stdio mode (`bun run mcp`).
  - `bun run claude` attaches the server to Claude Code; tested Claude Code version 2.1.270.
  - The README says to "Leave its Codex agent paused while controlling companions from your harness."
  - [README](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/README.md)
- **System prompt** [src] (key lines): "Companion 0 is the coordinator. Positive IDs are distinct characters… Act like a player: use carried materials and native mining/crafting/build queues… After scheduling native jobs, report progress and end the turn; the host wakes you when they finish… Never regenerate terrain, grant yourself items or control the human player's character" — [session.ts L57-68](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/src/runtime/session.ts)
- **Wake-up model** [src]
  - The host polls game chat every 2 s using a durable cursor.
  - When a native job ends, disappears or hits its review deadline, the host re-enqueues the request as a "continuation" with a fresh observation.
  - A `wait` tool (continuation "timer") schedules a review 15 s later and makes the model end its turn.
  - [session.ts L486-540, L600-628, L766-815](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/src/runtime/session.ts)
- **History (v0.13, Jan 2026).** That version had `src/daemon.ts`, `src/reactive-all.ts`, `src/companion-agent.ts` and subprocess "skills" (`auto-mine-resources.ts`, `build-smelter-line.ts`, `mine-until.ts`) driven by Claude Code. 0.18.0 removed them: "The old Claude daemons, subprocess skills, positional RCON endpoints… have been removed" — [v0.13.0 tree](https://github.com/lveillard/factorio-ai-companion/tree/v0.13.0); [README](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/README.md)

**B. factorioctl**
- **Architecture.** Claude → MCP server (stdio, Rust `rmcp`-style `#[tool]` functions, **44 tools**) → `FactorioClient`, which builds Lua strings and sends them over RCON. The CLI mirrors the tools. "Lua-over-RCON: All game interaction happens by sending Lua commands" — [README](https://github.com/MarkMcCaskey/factorioctl/blob/c3abe9ea/README.md); [mcp.rs](https://github.com/MarkMcCaskey/factorioctl/blob/c3abe9ea/src/bin/mcp.rs) [src]
- **Long-running actions are driven from Rust over RCON, not in-mod.** `walk_to` loops up to 500 times: it reads the position, sets `walking_state`, then sleeps, so the MCP call blocks until arrival, stuck or overshoot — [client/mod.rs L925-1030](https://github.com/MarkMcCaskey/factorioctl/blob/c3abe9ea/src/client/mod.rs) [src]
- **Agent memory.** Zones and protected ore patches are stored in `.agent_memory.json` outside the game — [README](https://github.com/MarkMcCaskey/factorioctl/blob/c3abe9ea/README.md)
- **Models.** Claude Code only, as documented. The README says "Claude Sonnet makes worse decisions but it's more entertaining" and "speed is key". The author never built "sub-agents or … an async task orchestration system" — [README](https://github.com/MarkMcCaskey/factorioctl/blob/c3abe9ea/README.md)

**C. FactoMCP**
- **Architecture.** Python FastMCP stdio server; each tool sends Lua over RCON. It must run on the same machine as Factorio [README]. Long actions (walk, mine) **register a temporary `script.on_event(defines.events.on_tick, …)` handler via RCON** and the Python side polls `storage.walk_done` / `storage.mine_done` — [server.py L393-562](https://github.com/WidAmi/FactoMCP/blob/f223f548/server.py) [src]
- **Models.** Built and tested with Claude Code (Pro plan). The author wrote that it "burns through" usage limits and planned to try OpenRouter free models, Hermes agent, or local LLMs — [forum](https://forums.factorio.com/viewtopic.php?t=133392)
- **Subagents.** The author's blog says Claude Code spins up Haiku subagents for resource collection, fueling and construction, which "seem" to stretch the 5-hour limit ("I don't have any hard measurements") — [widami blog 2026-04-19](https://widami.github.io/2026/04/19/claude-plays-factorio-3/)

### Inferences
- Only AI Companion moves physical work into the mod's tick loop (`script.on_nth_tick(5)`), which is the same design choice as Claude Crew's mod job queue. factorioctl's RCON-polled steering makes each walk a blocking, RCON-chatty operation.
- FactoMCP's approach of re-registering `on_tick` from a console command overwrites the handler slot for that event in the level script. **[inf]** That could clobber the scenario's own `on_tick` and is lost on save/load. It is unsafe for a real multiplayer save.
- **No project has a Claude Crew-style coordinator that writes work orders with in-game `done_when` checks.** AI Companion's "companion 0 = coordinator" is a prompt convention inside one model thread, not a separate planner.

### Gaps
- No token or cost numbers for AI Companion. The README mentions only "turn response/action timings"; no cost tracking was found.

---

## Q3. Characters: real script characters? How many, parallel? Coexistence with humans in real multiplayer?

### Takeaway
- **AI Companion** spawns real `character` entities with no attached `LuaPlayer`. There can be any number (IDs 1–1000), and all native jobs tick in parallel inside the mod. LLM turns, however, are serialized through one Codex thread. It is designed for hosted multiplayer with humans, but an **open bug (#9, 2026-10-10) crashes a dedicated server** when anyone clicks the Companions GUI while a companion exists.
- **factorioctl** and **FactoMCP** drive the *first connected / first* player's own character. That is one agent per game, and it would hijack a human's body in multiplayer.

### Cited Findings
**A. AI Companion**
- **Spawn code** (`companion_spawn`):
  - Calls `surface.create_entity{name="character", position=pos, force=force}`.
  - Position is `find_non_colliding_position` near the requesting player, or the force spawn when headless.
  - Inserts a "standard new-player starting kit" from `gameplay.json` (wood, pistol, 2 magazines, burner drill, stone furnace).
  - Adds a colored name label.
  - [companion.lua L26-63](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/factorio-mod/commands/companion.lua); [gameplay.json](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/config/gameplay.json) [src]
- **Native parallelism.** Each queue type (walking, harvest, gather, fuel, craft, build, belt, combat, blueprint) is a `storage.<kind>_queues[cid]` table, processed for every companion each `on_nth_tick(5)`. Each subsystem is wrapped in `guard_tick` (pcall) so one error cannot crash the scheduler — [control.lua L193-206, L499](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/factorio-mod/control.lua); [gameplay.json `queues`, `tick_interval: 5`](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/config/gameplay.json) [src]
- **Model-level serialization.** `CompanionSession.startNextTurn` returns early if `this.active` is set and processes the queue of messages one at a time on a single Codex `threadId` — [session.ts L488-540](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/src/runtime/session.ts) [src]
- **Multi-companion bookkeeping** [src]:
  - Per-companion material reservations (`storage.reserved[cid]`) and a task ledger — [task_pool_ledger.lua](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/factorio-mod/commands/task_pool_ledger.lua)
  - 0.18.0 changelog: "Separate material reservations per companion" — [changelog.txt](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/factorio-mod/changelog.txt)
- **Multiplayer requirement.** RCON requires hosting multiplayer; the README says "you can host a private local game and play alone with companions." There is also a Docker deployment against a remote headless server — [README](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/README.md)
- **Issue #9 (open, 2026-10-10).** "Clicking the in-game **Companions** button while at least one companion exists throws a non-recoverable Lua error and **kills the dedicated server** … Reproducible 100%". The error is `Invalid name "state"` at `gui.lua:108`, on Factorio 2.0.77 headless with space-age, quality and elevated-rails enabled — [issue #9](https://github.com/lveillard/factorio-ai-companion/issues/9)
- **Script characters and research triggers.** These characters do not fire `craft-item` research triggers ("Factorio only fires these for a real player"). The mod works around this with `fire_craft_triggers`, which sets `tech.researched = true` when a companion crafts the trigger item — [PR #2](https://github.com/lveillard/factorio-ai-companion/pull/2); [init.lua L228-243](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/factorio-mod/commands/init.lua) [src]
- **Stuck-character recovery.** `respawn_companion_entity` clones the character (preserving inventories, equipment grid and health) at a non-colliding spot and destroys the original when mining/selection stalls. It is also exposed as the `companion_respawn` tool — [queues_gather.lua L49-69](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/factorio-mod/commands/queues_gather.lua) [src]

**B. factorioctl**
- Every Lua snippet resolves the character as the first `p.character` in `game.connected_players`, falling back to `global.factorioctl_character` (created by `create_entity{name="character", position={0,0}}`) — [lua.rs L337-420](https://github.com/MarkMcCaskey/factorioctl/blob/c3abe9ea/src/client/lua.rs) [src]
- The repo's own bug note says teleport was "fixed" by making it "check connected players first", i.e. it acts on the human player's character — [bugs/2026-01-25-teleport-not-working.md](https://github.com/MarkMcCaskey/factorioctl/blob/c3abe9ea/bugs/2026-01-25-teleport-not-working.md)

**C. FactoMCP**
- All tools act on `game.players[1]` (walking_state, mining_state, cursor, build_from_cursor) — [server.py](https://github.com/WidAmi/FactoMCP/blob/f223f548/server.py) [src]

### Inferences
- For tonight's game with a human friend, **factorioctl and FactoMCP are unusable as-is**: they would puppet player 1 or the first connected player, who is a human.
- AI Companion is the only one with separate AI bodies, but its in-game GUI is a server-killer (#9). If Claude Crew borrows from it, avoid that GUI path.
- Script characters lacking a `LuaPlayer` is a shared constraint with Claude Crew. AI Companion's `fire_craft_triggers` hack is evidence that Claude Crew must handle research triggers (craft-item and probably build/mine triggers) itself. Note the hack marks the tech researched directly, which bypasses the normal trigger path.
- Space Age platform play: AI Companion spawns companions on the requesting player's surface (`p.surface`). If a friend on a space platform runs `/fac`, **[inf]** a character may be created on a platform surface, which Factorio's platform rules may not handle. This is unverified (see Gaps).

### Gaps
- No evidence either way on how AI Companion characters behave on space-platform surfaces. No reports or tests were found.

---

## Q4. Legit play vs cheats (teleport, instant craft, instant mine, revive without reach): quoted code

### Takeaway
- **AI Companion** is mostly legit: pathfinder walking, native `mining_state` for ore, native `begin_crafting`, reach checks on most actions. It still has several shortcuts:
  - Buildings appear via `surface.create_entity`, not `build_from_cursor`.
  - Obstacles and buildings are removed with instant `entity.mine{inventory=…}`.
  - A same-tick 10,000-tile teleport is used as a collision probe.
  - Research triggers are force-completed.
  - Blueprint ghosts are `revive`d instantly once in build reach.
- **FactoMCP** is the most legit (true `build_from_cursor`, per-tick mining progress) but exposes `run_lua`.
- **factorioctl** has real cheats: instant `mine_entity(…, true)`, `create_entity` with no reach check, `destroy()` without refund, a teleport function, and `execute_lua`.

### Cited Findings
**A. AI Companion** [src]
- **Walking: legit pathfinder.** `request_walk_path` calls `e.surface.request_path{bounding_box=proto.collision_box, collision_mask=proto.collision_mask, start=e.position, goal=q.target, radius=2, can_open_gates=true, entity_to_ignore=e, pathfind_flags={cache=false, low_priority=false}}`, then follows waypoints via `walking_state`. The comment says "CRITICAL: ignore the companion itself, otherwise its own collision box makes the START position collide -> pathfinder returns nil". Straight-line plus perpendicular bypass is the fallback; trees and rocks on the route are cleared with timed `mining_state` — [control.lua L214-260, L300-492](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/factorio-mod/control.lua)
- **Ore mining: legit timed mining.** `c.entity.selected = entity; c.entity.mining_state = {mining = true, position = entity.position}`. Progress is measured by inventory delta, with a 600-tick stall timeout and an adjacency check (`mine_adjacent_range: 2`) — [queues_harvest.lua L53-69, L82-140](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/factorio-mod/commands/queues_harvest.lua); [gameplay.json `queue_tuning`](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/config/gameplay.json)
- **Crafting: native queue with an extra artificial wait.** `local ticks = math.max(MIN_ACTION_TICKS, (proto.energy or 0.5) * 60)`. After waiting `ticks_per` it calls `c.entity.begin_crafting{recipe = q.recipe, count = 1}` and then waits for `crafting_queue_size == 0`. It refuses if `get_craftable_count < 1` and checks real character crafting categories and unlocked recipes — [queues_craft.lua L9-49](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/factorio-mod/commands/queues_craft.lua)
- **Placement (async `building_place_start`).**
  - Approaches until within `build_distance`, then waits `BUILD_TICKS` (60).
  - Checks `can_place_entity`, then calls `surf.create_entity{…}` and `c.entity.remove_item{name=q.entity,count=1}`. If the item is gone, it destroys the placed entity.
  - Collision probe: `c.entity.teleport({x = self_pos.x + 10000, y = self_pos.y + 10000})`, re-test `can_place_entity`, then `c.entity.teleport(self_pos)`. This is same-tick and invisible, used to detect self-collision before "stepping away" on foot.
  - [queues_build.lua L143-222](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/factorio-mod/commands/queues_build.lua)
- **Placement (sync `building_place`, contract description "(instant)").**
  - Reach check `dist > (c.entity.reach_distance or 10)`; requires the item in inventory.
  - Refuses if the companion is standing on the footprint ("A character cannot teleport, so REFUSE").
  - Clears trees and rocks with `o.mine{inventory=…}`, picks up item-entities, then `create_entity` and `inv.remove`.
  - [building.lua L21-77](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/factorio-mod/commands/building.lua)
- **Instant mining of entities.** `building_remove` (reach 10) and `building_mine` (reach **15**, above the default) call `t.mine{inventory = inv}`. Comment: "Never fabricate the item + free-destroy". Build-site clearing also mines obstacles instantly (`obs.mine{inventory = inv}`) — [building.lua L79-101, L272-295](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/factorio-mod/commands/building.lua); [queues_build.lua L42-53](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/factorio-mod/commands/queues_build.lua)
- **Blueprint manual build.** Walks until `distance <= entity.build_distance`, removes the item from inventory, then `ghost.revive{raise_revive=true, overflow=inv}`. If self-collision occurs it walks away "without teleporting the character". The `robots` mode leaves ghosts for real construction robots — [queues_blueprint.lua L100-155](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/factorio-mod/commands/queues_blueprint.lua)
- **Chest/machine transfers.**
  - `building_empty` / `building_fill` are reach-checked.
  - `ensure_item`'s `pull_nearby` takes from chests within radius 5 and furnace/assembler outputs within radius 5, as instant inventory moves.
  - `building_fuel` uses `fuel_reach: 6`.
  - [building.lua L152-267](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/factorio-mod/commands/building.lua); [task_pool_ensure_item.lua L40-66](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/factorio-mod/commands/task_pool_ensure_item.lua)
- **Research triggers force-completed:** `tech.researched = true` — [init.lua L228-243](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/factorio-mod/commands/init.lua)
- **Starting kit.** Inserted on spawn; the comment calls it "real, not a cheat — exactly what a fresh freeplay game grants" — [companion.lua L47-56](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/factorio-mod/commands/companion.lua)

**B. factorioctl** [src]
- **Mining.** `mine_at` (doc comment "Mine entity at position (instant - for compatibility)") calls `c.mine_entity(target, true)` in a loop of `count`. It walks first (client side). A separate legit `start_mining` uses `mining_state` and checks `resource_reach_distance` — [lua.rs L486-540, L586-680](https://github.com/MarkMcCaskey/factorioctl/blob/c3abe9ea/src/client/lua.rs); [client/mod.rs L393](https://github.com/MarkMcCaskey/factorioctl/blob/c3abe9ea/src/client/mod.rs)
- **Placement.** `place_entity` checks inventory and `can_place_entity{…, build_check_type = defines.build_check_type.manual}`, then `game.surfaces[1].create_entity{…}`. **No reach/distance check** in the snippet. It also `destroy()`s ground items it cannot pick up — [lua.rs L807-880](https://github.com/MarkMcCaskey/factorioctl/blob/c3abe9ea/src/client/lua.rs)
- **Removal.** `remove_entity_at` does `e.destroy()` with no item refund and no reach check — [lua.rs L1039-1055](https://github.com/MarkMcCaskey/factorioctl/blob/c3abe9ea/src/client/lua.rs)
- **Teleport.** `teleport_character` calls `c.teleport({x, y})`. It is a CLI command (`character teleport`); I did not find it among the MCP tools — [lua.rs L376-392](https://github.com/MarkMcCaskey/factorioctl/blob/c3abe9ea/src/client/lua.rs); [bug note](https://github.com/MarkMcCaskey/factorioctl/blob/c3abe9ea/bugs/2026-01-25-teleport-not-working.md)
- **Crafting.** Native `c.begin_crafting{recipe=…, count=…}`, which is legit — [lua.rs L754-790](https://github.com/MarkMcCaskey/factorioctl/blob/c3abe9ea/src/client/lua.rs)
- **Raw Lua.** MCP tool `execute_lua`: "Execute a raw Lua command. Use with caution" — [mcp.rs L1758-1759](https://github.com/MarkMcCaskey/factorioctl/blob/c3abe9ea/src/bin/mcp.rs)
- **Rules are prompt-only.** CLAUDE.md "Game Rules": "Must be near entities to interact (walk there first) / Craft and mine items legitimately - no spawning" — [CLAUDE.md](https://github.com/MarkMcCaskey/factorioctl/blob/c3abe9ea/CLAUDE.md)

**C. FactoMCP** [src]
- **Placement.** `build_entity` checks `dist > p.build_distance` and `can_place_entity`, then `p.cursor_stack.swap_stack(slot); p.build_from_cursor{position=pos, direction=…}`. It captures `on_built_entity` and `event.consumed_items` — [server.py L566-654](https://github.com/WidAmi/FactoMCP/blob/f223f548/server.py)
- **Walking.** `walk_to` uses "legitimate walking_state movement", 8-directional with stuck detection and a 40-tick perpendicular detour. It does not use the game pathfinder — [server.py L393-488](https://github.com/WidAmi/FactoMCP/blob/f223f548/server.py)
- **Mining.** `mine_resource` sets `p.mining_state` and counts completions by watching `mining_progress` fall back to 0 — [server.py L490-562](https://github.com/WidAmi/FactoMCP/blob/f223f548/server.py)
- **Crafting.** `craft` calls `p.begin_crafting` — [server.py L716-724](https://github.com/WidAmi/FactoMCP/blob/f223f548/server.py)
- **Raw Lua.** A `run_lua` tool exists. The forum post says the agent stays within the rules "as long as it's using tools other than the run_lua() one" — [server.py L98-101](https://github.com/WidAmi/FactoMCP/blob/f223f548/server.py); [forum](https://forums.factorio.com/viewtopic.php?t=133392)

### Inferences
- **AI Companion `create_entity` placement.** It does not pass `raise_built`, so other mods and scripts will not see `on_built_entity` / `script_raised_built` for companion builds. **[inf]** Blueprint revive does pass `raise_revive=true`.
- **AI Companion crafting time.** `start_craft` waits a full `ticks_per` (recipe energy × 60, crafting speed ignored) *before* the first `begin_crafting`. Each item is then crafted natively one at a time. **[inf]** The first item therefore takes roughly double time, and every item adds up to 5 ticks of poll latency. It is slower than a real player, not faster.
- For a "legit player rules" benchmark, FactoMCP's `build_from_cursor` pattern is the closest to true player placement. It natively enforces build distance, consumes the item and raises events. However, it needs a `LuaPlayer`, which script characters don't have. Claude Crew's controller should keep its current approach (or AI Companion's) of `can_place_entity` + `create_entity{raise_built=true}` + an explicit reach check + item removal.

### Gaps
- I did not check whether AI Companion's `item_pick` or the gather pipeline's auto-pickup applies a reach limit.

---

## Q5. Skills/macro-actions and autonomy: physical work per model call, failure handling and verification, idle time

### Takeaway
AI Companion has real macro-actions that keep running after the model's turn ends. Its `task_submit` pipeline is the closest analog to Claude Crew's deterministic controller: up to 32 steps, with a recursive `ensure_item` that resolves through nearby chests or machines, crafting and gathering. Model calls are capped and woken by job completion or a 15 s timer.

factorioctl and FactoMCP have no autonomy. Each tool call does one action (walk, mine N, place one entity or a line), and the LLM drives every step.

### Cited Findings
**A. AI Companion**
- **Tool contract.** 70 tools in `config/commands.json`. The macro tools are [src]:
  - `gather` ("Autonomously find reachable resources, walk and mine the requested number of NEW items"; `count` up to 10000)
  - `fuel_group` ("Walk to nearby burners and supply coal")
  - `belt_connect_start` ("Route and build transport belts … using carried items")
  - `blueprint_build` (auto/manual/robots)
  - `task_submit`, with steps `ensure_item, find_patch, verify_tile, pick_orientation, place, fuel, remove, find_existing, set_position, read_drop_position`, max 32 steps
  - [commands.json](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/config/commands.json)
- **`ensure_item` recursion** (max depth 4) [src]:
  1. Satisfied if carried.
  2. Otherwise, if the item has no recipe, `pull_nearby` from chests within 5 tiles, then `start_gather` (max 5 attempts).
  3. If it is not hand-craftable, pull from furnace/assembler output within 5 tiles and wait up to `smelt_wait_ticks: 14400` when a nearby machine is producing it.
  4. Otherwise craft.
  - Unmet needs give up after `needs_unmet_giveup_ticks: 6000`.
  - [task_pool_ensure_item.lua](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/factorio-mod/commands/task_pool_ensure_item.lua); [gameplay.json `task_tuning`](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/config/gameplay.json)
- **Task scheduling.** Per companion, `pick_next` runs the active task step nearest to the character, so instant steps win ties — [task_pool.lua L31-47](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/factorio-mod/commands/task_pool.lua) [src]
- **Failure handling** [src]:
  - Every queue records a terminal `state` / `error` / `failed` string and keeps the "previous" job readable (`core.previous`).
  - Harvest failures log diagnostic reasons such as "no candidate entity was ever within true mining adjacency" and "no progress for 600 ticks".
  - Build failures dump nearby entities and the tile.
  - Opt-in "rare symptom" save capture.
  - [queues_harvest.lua](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/factorio-mod/commands/queues_harvest.lua); [queues_build.lua L175-185](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/factorio-mod/commands/queues_build.lua); [gameplay.json `diagnostics`](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/config/gameplay.json)
- **Verification.** `blueprint_status`: "Completion means real construction, not ghost placement" [src]. The 0.18.3 changelog: "Count actual walking and mining progress before replanning or timing out a task" — [commands.json](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/config/commands.json); [changelog.txt](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/factorio-mod/changelog.txt)
- **Model budget.** 64 tool calls per turn. When exhausted: "Turn tool budget exhausted. End this turn now… native work continues and the host will review it". Repeated `wait` calls are rejected with "A review is already scheduled. End this turn; do not poll again" — [session.ts L572-600](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/src/runtime/session.ts) [src]

**B. factorioctl**
- **High-level CLI builders.** `build drill-array`, `build smelter-line`, `belt line`, `power line` [README]. The MCP surface instead exposes mostly primitives plus `route_belt` (A* with underground and zones), `get_machine_belt_positions`, `find_build_area`, `check_placement`, belt analysis (`analyze_belt_gaps`, `detect_sushi_belts`, `trace_belt_sources`) and `get_alerts` — [README](https://github.com/MarkMcCaskey/factorioctl/blob/c3abe9ea/README.md)
- **Walking bug.** The MCP `walk_to`'s description says "using pathfinding", but its body calls `client.walk_to(position, true)`. That is the *direct* walk ("Smooth walk to a target position (direct, no pathfinding)"); A* lives in a separate `walk_to_pathfind` — [mcp.rs L1200-1215](https://github.com/MarkMcCaskey/factorioctl/blob/c3abe9ea/src/bin/mcp.rs); [client/mod.rs L843-930](https://github.com/MarkMcCaskey/factorioctl/blob/c3abe9ea/src/client/mod.rs) [src]
- **Prompt guidance.** The play CLAUDE.md tells the model to cut verification ("Don't check status after every single action… Trust that placements worked unless you see an error") and to call `broadcast_thought` in parallel with actions to avoid dead air — [CLAUDE.md](https://github.com/MarkMcCaskey/factorioctl/blob/c3abe9ea/CLAUDE.md)
- **Self-reported bugs:** choppy walking and "Blocked or stuck" on clear paths; `craft` does not auto-queue intermediates — [bugs/](https://github.com/MarkMcCaskey/factorioctl/tree/c3abe9ea/bugs)

**C. FactoMCP**
- **Tools** (~25): `walk_to`, `mine_resource(count)`, `build_entity`, `build_line(count)`, `craft`, `load_entity`, `collect_from_entity`, `get_entity_status`, `diagnose_area`, `trace_fluid_network`, `check_fluid_connections`, research and recipe tools, `take_screenshot`, `get_stats`, `run_lua`, `stop` — [server.py](https://github.com/WidAmi/FactoMCP/blob/f223f548/server.py) [src]
- **Observed play.** The agent "will rely on hand crafting and mining far more than it should". It has never built an end-to-end ore→lab line and hand-fed assemblers from chests — [forum reply 2026-04-21](https://forums.factorio.com/viewtopic.php?t=133392)
- **Observed failure modes.** It "often jumps to conclusions that are wrong" from stale state, and spent about an hour failing to place a two-drill coal setup — [widami blog](https://widami.github.io/2026/04/19/claude-plays-factorio-3/)

### Inferences
- AI Companion's `task_submit` + `ensure_item` is roughly Claude Crew's "fetch from chests, craft, mine raw resources" controller, but per-companion and model-submitted. It has no coordinator-written `done_when`, and no scheduler that assigns work across idle characters.
- Idle time in AI Companion is bounded by the single serialized model thread. If companion 1's job finishes while the model is mid-turn on companion 2, its continuation waits in the queue. Claude Crew's design of a deterministic dispatcher plus per-actor small models avoids this.
- factorioctl's `walk_to` description/implementation mismatch is a concrete example of why LLM-facing tool descriptions need test coverage.

### Gaps
- No measured idle time, items/minute or success-rate numbers are published for any of the three.

---

## Q6. Chat commanding, multi-agent coordination, ghosts/blueprints, late-game support

### Takeaway
- **AI Companion** takes commands via `/fac [id] text` and a custom chat-bar GUI, not plain `@name` chat. Multi-agent coordination is limited to prompt-level "companion 0 = coordinator" plus per-companion reservations. Blueprints are covered: save, inspect, import/export, and build by hand or by robots, with construction tracking. There are no deconstruction/upgrade planners, logistics requests, armor, or bottleneck diagnosis.
- **factorioctl** piggybacks in-game chat onto every tool result and has strong belt and power diagnostics.
- **FactoMCP** has entity-status, fluid and screenshot diagnostics.

### Cited Findings
**A. AI Companion** [src]
- **`/fac` parsing.**
  - With no args, `/fac` opens the GUI.
  - `/fac <id|name> <text>` targets a companion.
  - Otherwise text goes to companion 0, the "Codex" coordinator.
  - Subcommands include `kill`, `clear` and `name`.
  - Messages go into `storage.companion_messages` (a bounded mailbox), which the bridge reads via `chat_poll` with a durable cursor.
  - There is no `on_console_chat` handler, so ordinary chat is not read.
  - [control.lua L95-147](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/factorio-mod/control.lua); [player_input.lua](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/factorio-mod/commands/player_input.lua)
- **In-game controls.** Movable chat bar with recipient selection. "Companions" panel with spawn/follow/stop/remove (0.18.3). Agent progress is mirrored into game chat — [changelog.txt](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/factorio-mod/changelog.txt); [README](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/README.md)
- **Command authorization.** `commands.add_command("fac_api", …)` has no check on `cmd.player_index` or admin status — [dispatch.lua L72-77](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/factorio-mod/commands/dispatch.lua)
- **Blueprints.**
  - `blueprint_save` takes an import string or structured entities; reusing a name replaces the blueprint.
  - `blueprint_inspect` returns the material bill, missing carried items, locked recipes and manual limits, and can export.
  - `blueprint_build` with `auto` uses robots only if "construction robots … cover every position" (`find_logistic_networks_by_construction_area`).
  - `blueprint_status` tracks real construction.
  - `max_plans: 32`.
  - [commands.json](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/config/commands.json); [queues_blueprint.lua L55-75](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/factorio-mod/commands/queues_blueprint.lua); [capabilities.lua L17-18](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/factorio-mod/commands/capabilities.lua)
- **Ghost scope.** `blueprint_build` builds only ghosts created by its own job. There is no tool to build arbitrary existing (human-placed) ghosts — [queues_blueprint.lua](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/factorio-mod/commands/queues_blueprint.lua)
- **Missing late-game tooling.** A grep for `order_deconstruction`, `order_upgrade`, requester/logistic slots and armor returned nothing beyond the construction-network lookup in `capabilities.lua`. Machine tools are `building_info`, `building_recipe`, `building_clear_wrong_output` and `inserter_set_filter` — [repo grep at 4a37f783](https://github.com/lveillard/factorio-ai-companion/tree/4a37f783/factorio-mod/commands)
- **Observations.** `world_observe` returns a bounded snapshot: 240 entities, 24 detailed machines, 512 water tiles, 32 tasks, 10 errors, vision radius 32. Ore and trees are grouped, 3 positions per group, in the automatic context — [gameplay.json `observation`](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/config/gameplay.json); [agent.json](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/config/agent.json)

**B. factorioctl** [src]
- **Chat delivery.** On every MCP tool call, `fetch_player_messages` registers a chat handler and drains queued player chat, then appends it as `--- Player Messages ---` to the tool result. The agent sees human chat without polling — [mcp.rs L573-600](https://github.com/MarkMcCaskey/factorioctl/blob/c3abe9ea/src/bin/mcp.rs); [lua.rs L1730](https://github.com/MarkMcCaskey/factorioctl/blob/c3abe9ea/src/client/lua.rs)
- **Narration.** `broadcast_thought` does in-game TTS and console narration — [README](https://github.com/MarkMcCaskey/factorioctl/blob/c3abe9ea/README.md)
- **Ghosts.** Ghost placement exists (`create_entity{name="entity-ghost", …}`), and there is a blueprint module — [lua.rs L995-1030](https://github.com/MarkMcCaskey/factorioctl/blob/c3abe9ea/src/client/lua.rs); [world/blueprint.rs](https://github.com/MarkMcCaskey/factorioctl/blob/c3abe9ea/src/world/blueprint.rs)
- **Power and belt diagnostics.** `get_power_networks`, `find_power_issues`, `analyze_belt_gaps`, `detect_sushi_belts`, `trace_belt_sources`, `analyze_inserters` — [README](https://github.com/MarkMcCaskey/factorioctl/blob/c3abe9ea/README.md)
- **Zones.** The zone system reserves map areas, and `scan_resources` protects ore patches so `check_placement` warns before building on ore — [README](https://github.com/MarkMcCaskey/factorioctl/blob/c3abe9ea/README.md)

**C. FactoMCP**
- **Diagnostics.**
  - `get_entity_status` reports pickup/drop targets, plus the drop position as a fallback when there is no drop target (commit 2026-04-20).
  - `diagnose_area`.
  - Fluid tracing.
  - `take_screenshot` via `game.take_screenshot` to script-output.
  - [server.py L842-1035, L1303](https://github.com/WidAmi/FactoMCP/blob/f223f548/server.py); [commits](https://github.com/WidAmi/FactoMCP/commits)
- **Chat.** No chat ingestion tool was found [src].

### Inferences
- None supports Claude Crew's `@name` / `@all` plain-chat addressing, coordinator work orders, upgrade/deconstruct planners, logistic network views, requester configuration or armor equip. Claude Crew's late-game scope is clearly beyond all three.
- AI Companion's unauthenticated `/fac_api`, plus `/fac kill` / `/fac clear` with no visible admin check, means **[inf]** any client in a multiplayer game can drive or kill companions with a console command. Claude Crew should restrict its RCON-only command to `cmd.player_index == nil` (RCON/server).

### Gaps
- I did not trace whether factorioctl's chat handler (registered via `script.on_event(on_console_chat)` from RCON) survives save/load or conflicts with scenario handlers.

---

## Q7. Known bugs/limits, token cost notes

### Takeaway
- **AI Companion**: one open **critical multiplayer crash** (#9), one GUI layout bug (#10), and a research-trigger visibility gap (#6). Its own portal page still calls it beta. It publishes no token data.
- **factorioctl**: an author-disowned prototype with self-filed walking and crafting bugs.
- **FactoMCP**: "slow, makes spatial reasoning mistakes, and burns through tokens fast". It does ship a per-tool token estimator.

### Cited Findings
- **AI Companion #9 (open, 2026-10-10).** Dedicated-server crash `Invalid name "state"` at `gui.lua:108` when opening the Companions panel with a companion present; "kills the dedicated server — it quits with status=255" — [issue #9](https://github.com/lveillard/factorio-ai-companion/issues/9)
- **AI Companion #10 (open, 2026-10-10).** The chat bar's Send button overflows the frame (`gui.lua:55-60`) — [issue #10](https://github.com/lveillard/factorio-ai-companion/issues/10)
- **AI Companion #6 (open, 2026-09-13, auto-filed by the agent's feedback tool).** `research_get` drops `research_trigger`, and `research_set` returns only "Failed" for trigger techs — [issue #6](https://github.com/lveillard/factorio-ai-companion/issues/6)
- **AI Companion stability fixes in 0.18.1–0.18.3:**
  - "Isolate queue failures per companion and stop failed jobs without repeated tick errors"
  - "Ignore obsolete path results after a walking job is replaced"
  - "Clear obstructing modded rocks without harvesting every nearby tree"
  - "Keep failed recovery attempts from destroying the companion"
  - [changelog.txt](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/factorio-mod/changelog.txt)
- **AI Companion tests.** 36 Lua regression tests via Fengari with engine doubles, 25 session tests, and a real headless-game suite (`bun run test:game`) — [tests/](https://github.com/lveillard/factorio-ai-companion/tree/4a37f783/tests); [README](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/README.md) [src]
- **factorioctl README lessons:**
  - "spatial layout is just a major pain point… fundamentally very difficult to get LLMs to solve"
  - "Offloading tasks from the LLM is the key… Don't make your LLM do path finding"
  - "Claude likes MCP a lot more than CLI tools"
  - "Claude code has a very limited understanding of planning in space"
  - Vibe coding "has diminishing returns"
  - No token figures
  - [README](https://github.com/MarkMcCaskey/factorioctl/blob/c3abe9ea/README.md)
- **FactoMCP cost notes.** `get_stats` reports per-tool call counts and estimated tokens in/out (commit 2026-04-14, "Add per-tool token usage tracking"). The author reports no hard numbers: "the Claude Pro plan is pretty opaque about actual usage" — [server.py L22-90](https://github.com/WidAmi/FactoMCP/blob/f223f548/server.py); [blog](https://widami.github.io/2026/04/19/claude-plays-factorio-3/); [forum](https://forums.factorio.com/viewtopic.php?t=133392)
- **Forum reply (gjani, 2026-06-08).** Coding-agent harnesses lack memory for game rules; suggests Voyager-style memory and GraphRAG over the wiki — [forum](https://forums.factorio.com/viewtopic.php?t=133392)

### Inferences
- If AI Companion is loaded on tonight's server at all, **#9 is a hard blocker for multiplayer use of its GUI**. It cannot be co-installed casually unless nobody clicks "Companions".

### Gaps
- No quantitative token or cost data exists for any of the three. FactoMCP's estimator is character-count based and no outputs were published.

---

## Q8. Better than Claude Crew / Claude Crew does but they don't / what to borrow / adopt or fork?

### Takeaway
None of these is mature enough to adopt or fork as Claude Crew's controller layer:
- **AI Companion** is the only serious candidate. It is architecturally parallel to Claude Crew (mod job queue + RCON JSON + bridge), but it is Codex-centric, has a single serialized model thread, crashes dedicated servers via its GUI, uses `create_entity` placement, has no late-game logistics tools, and has been dormant since 2026-09-13.
- It is best mined for specific modules and edge-case fixes.
- **factorioctl** contributes analysis ideas (belt graph, zones, chat piggyback).
- **FactoMCP** contributes `build_from_cursor`-style event fidelity and token telemetry ideas.

### Cited Findings (things they do that Claude Crew should check it has)
- **AI Companion: single schema source of truth.** `config/commands.json` generates MCP and Codex tool schemas, browser forms and the Lua contract (`commands/contract.lua`). Lua validates every call against the same `inputSchema` — [AGENTS.md](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/AGENTS.md); [dispatch.lua](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/factorio-mod/commands/dispatch.lua)
- **AI Companion: offline Lua regression tests.** Production Lua modules run in Fengari with deterministic engine doubles ("crafting completion/cancellation, partial mining results, inventory formats, reservations and belt routes"), plus a disposable real-headless-game suite — [README](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/README.md); [tests/lua.test.ts](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/tests/lua.test.ts)
- **AI Companion: pathfinder details.**
  - `request_path` with `entity_to_ignore = self` (otherwise the start position collides).
  - `can_open_gates`.
  - Stale-path-result rejection via `q.path_request_id ~= ev.id`.
  - Fallback to straight-line plus perpendicular bypass, clearing trees and rocks on the route.
  - [control.lua L214-260](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/factorio-mod/control.lua)
- **AI Companion: belt A* router.** `pathfind.lua` `M.find_path(surf, from, to, force)`:
  - Binary-heap A* with `MAX_NODES = 128000` and `MAX_SEARCH_MARGIN = 60`.
  - Memoized `can_place_entity("transport-belt")` blocking test, with ore tiles treated as blocked.
  - Shore buffer and penalty (8 / 3).
  - Underground entrance/exit pairs (`underground_max_distance: 5`) in `queues_belt.lua`.
  - [pathfind.lua](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/factorio-mod/commands/pathfind.lua); [queues_belt.lua](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/factorio-mod/commands/queues_belt.lua)
- **AI Companion: stuck-character recovery.** `respawn_companion_entity` uses `old.clone{…}` to keep inventories, equipment and health, then `destroy` — [queues_gather.lua L49-69](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/factorio-mod/commands/queues_gather.lua)
- **AI Companion: research triggers for script characters.** `fire_craft_triggers` — [init.lua L228-243](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/factorio-mod/commands/init.lua)
- **AI Companion: self-collision handling** (step off footprint, or probe by teleporting away and back in the same tick) — [queues_build.lua L153-175](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/factorio-mod/commands/queues_build.lua)
- **AI Companion: host-side model throttles.** "Tool budget exhausted → end turn; native work continues"; a `wait` tool that schedules a review instead of polling; continuation caps; and durable message state across restarts ("a restart starts paused and does not replay interrupted actions") — [session.ts](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/src/runtime/session.ts); [README](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/README.md)
- **AI Companion: `companion_capabilities`.** Exposes actual hand-crafting categories, reach and available construction robots to the agent — [commands.json](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/config/commands.json); [capabilities.lua](https://github.com/lveillard/factorio-ai-companion/blob/4a37f783/factorio-mod/commands/capabilities.lua)
- **AI Companion: agent-filed feedback (PR #7, open).** `feedback_report` / `feedback_list` let the agent file grouped, de-duplicated GitHub issues about tool friction. Issue #6 was created that way — [PR #7](https://github.com/lveillard/factorio-ai-companion/pull/7); [issue #6](https://github.com/lveillard/factorio-ai-companion/issues/6)
- **factorioctl: analysis and memory tools.**
  - Belt graph and analysis modules: `src/analyze/belt_graph.rs`, `belt_source_trace.rs`, `belt_sushi.rs`, `belt_gaps.rs`, `inserter.rs`.
  - `get_machine_belt_positions` (drill/furnace drop positions in all four orientations).
  - Zones and protected ore in `src/memory/mod.rs`.
  - Chat piggyback in `with_player_messages`.
  - [src/analyze](https://github.com/MarkMcCaskey/factorioctl/tree/c3abe9ea/src/analyze); [src/memory/mod.rs](https://github.com/MarkMcCaskey/factorioctl/blob/c3abe9ea/src/memory/mod.rs); [mcp.rs](https://github.com/MarkMcCaskey/factorioctl/blob/c3abe9ea/src/bin/mcp.rs)
- **FactoMCP: build event fidelity and telemetry.**
  - `build_entity` captures `on_built_entity` and reports `event.consumed_items` as proof of the build.
  - `get_entity_status` shows pickup/drop targets and positions, which helps the model verify alignment.
  - The `get_stats` token estimator wraps every tool call.
  - [server.py L566-654, L842-935, L22-90](https://github.com/WidAmi/FactoMCP/blob/f223f548/server.py)

### Inferences

**What these projects do better than Claude Crew (as described):**
1. AI Companion's generated single-schema contract and its Fengari offline Lua test harness are mature engineering that Claude Crew may lack.
2. AI Companion's pathfinder edge cases (self-ignore, stale result, gates, obstacle clearing) are field-tested.
3. AI Companion has a full browser dashboard with a live map and Docker remote deployment.
4. factorioctl's belt-network analysis (sushi, gaps, source trace) and zone and ore protection are richer than a generic "bottleneck by machine status" view for early-game belt debugging.
5. FactoMCP's `on_built_entity` / `consumed_items` verification.

**What Claude Crew does that none of them do:**
- Plain chat `@name` / `@all` (AI Companion uses `/fac`).
- A separate characterless coordinator writing structured work orders with in-game `done_when` checks.
- A deterministic scheduler dispatching across actors.
- A small model per actor, called only on exceptions. AI Companion uses one big-model thread for everything, serialized.
- Building existing human-placed ghosts.
- Copy/paste of existing builds as blueprints. AI Companion only imports strings or structured entity lists.
- Upgrade/deconstruct planners, logistic network views, requester/filter configuration (beyond inserter filters), and armor equip.
- A benchmark harness with staged saves and cost tracking.
- Explicit model-agnostic backends. AI Companion is Codex plus generic MCP.
- A robustness posture for a live multiplayer game: AI Companion's GUI crashes dedicated servers (#9).

**Borrow list** (concrete; paths at `lveillard/factorio-ai-companion@4a37f783` unless noted):
- `factorio-mod/control.lua` `request_walk_path` and `on_script_path_request_finished`: the `entity_to_ignore`, `can_open_gates` and `path_request_id` stale check.
- `factorio-mod/commands/pathfind.lua` `M.find_path`: belt A* with memoized placement checks, shore penalty, node cap. Pair it with the underground handling in `queues_belt.lua`.
- `factorio-mod/commands/queues_gather.lua` `respawn_companion_entity`: clone-based unstick.
- `factorio-mod/commands/init.lua` `fire_craft_triggers`: research triggers for script characters. Consider extending it to mine/build triggers.
- `factorio-mod/commands/queues_harvest.lua`: inventory-delta progress accounting, adjacency check, 600-tick stall detection with diagnostic messages.
- `factorio-mod/commands/task_pool_ensure_item.lua` `pull_nearby` / `start_ensure_item_action`: recursive procurement with depth cap and smelter-wait.
- `factorio-mod/commands/capabilities.lua` `M.robots`: `find_logistic_networks_by_construction_area`, to choose robot versus manual builds.
- `factorio-mod/commands/queues_blueprint.lua`: manual ghost revive loop with item removal before `revive{raise_revive=true, overflow=inv}`, rollback on failure and collision spill.
- `src/runtime/session.ts`: tool-budget and continuation and `wait`-review pattern for exception calls.
- `config/commands.json` → `commands/contract.lua` generation, and `tests/lua.test.ts` + `tests/fixtures/game.lua` (Fengari engine doubles).
- factorioctl `src/bin/mcp.rs` `with_player_messages`: append pending chat to every tool response.
- factorioctl `get_machine_belt_positions` and `src/analyze/*`: belt diagnostics.
- FactoMCP `server.py` `get_stats`: per-tool token accounting, comparable with Claude Crew's cost tracking.

**Avoid copying:**
- AI Companion's sync `building_place` and `building_mine` with reach 15 and instant `.mine{}`.
- The teleport-probe, if a strict "no teleport ever" rule is wanted.
- The pre-`begin_crafting` artificial wait.
- `create_entity` without `raise_built=true`.
- The unauthenticated `/fac_api`.
- `gui.lua` (crash #9).
- factorioctl's `mine_entity(…, true)`, unchecked `create_entity` and `destroy()`.
- FactoMCP's `script.on_event(on_tick)` registered from RCON.

**Adopt/fork verdict:** No.
- AI Companion's core assumptions differ from Claude Crew's: one model thread, Codex-first, companion 0 as an in-thread coordinator, `/fac`-only chat, and no work-order/`done_when` layer.
- It is dormant (last commit 2026-09-13) and has an open server-crash bug.
- Its license (MIT) permits lifting individual Lua modules with attribution, which is the better path.
- factorioctl (no LICENSE file despite the README's MIT claim; author disclaims the code) and FactoMCP (player-1 puppeting) are not fork candidates.

### Gaps
- I did not run any of the code, so the throughput, robustness and legitimacy claims are from source reading only.
- No MCP registry listings (glama.ai, mcp.so, smithery) were found for any of the three. One general search returned only unrelated servers, and I did not query each registry directly by name — [web search 2026-10-18](https://glama.ai/mcp/servers)
- The factorioctl demo video (YouTube TQvqkc7ivIw) was not reviewed.
