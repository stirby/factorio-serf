# Factorio LLM bridges, MCP servers and automation tools (not character-playing mods): prior art for Claude Crew

Research date: 2026-10-18. Scope: bridge/MCP/automation projects. Character-playing companion mods (lveillard/factorio-ai-companion, WidAmi/FactoMCP, sbarisic/FactorioMCP, factorioctl, Danconnolly/factorio-player-mcp) are only inventoried here (see Q6), because other researchers cover them.

Labels used below:
- **[verified]**: read from primary data. That means the mod portal JSON API (`/api/mods/<name>/full`), the GitHub REST API, raw repo files, or the official Factorio release API.
- **[listing claim]**: the author's own description on a portal or registry page, with no source code checked.
- **[secondary]**: search summaries or third-party hosting blogs.

---

## Q1. Is Factorio 2.1 released or stable as of 2026-10-18, and what does that mean for 2.1-only mods?

### Takeaway
Factorio 2.1 is **experimental only** (2.1.22). **Stable is still 2.0.77**, which is exactly the version Claude Crew targets. Any mod whose info.json says `factorio_version: "2.1"` (the chengjiang MCP mod is one) is built for the experimental branch and will not load on 2.0.77.

### Cited Findings
- [verified] Official release API on 2026-10-18 returns experimental `{"alpha":"2.1.22","expansion":"2.1.22","headless":"2.1.22"}` and stable `{"alpha":"2.0.77","expansion":"2.0.77","headless":"2.0.77"}`. Source: [factorio.com/api/latest-releases](https://factorio.com/api/latest-releases)
- [secondary] 2.1 shipped as experimental on 26 June 2026 (FFF #444) and has stayed experimental to give mod authors time. Wube planned a stable release "by end of summer" but has given no firm date. Wube calls 2.1 "our last major update", with long-term support to follow. Sources: [FFF #440 – 2.1 plan](https://factorio.com/blog/post/fff-440), [supercraft.host 2.1 experimental guide](https://supercraft.host/wiki/factorio/factorio_2_1_experimental_server_guide/), [gameserverkings 2.1 experimental server](https://www.gameserverkings.com/knowledge-base/factorio/factorio-2-1-experimental-server/). These came from a search summary. I did not open FFF #440/#444 myself.
- [verified] The chengjiang `factorio-mcp-server` releases 1.0.0–1.0.3 all declare `factorio_version: 2.1`, and the description says "Requirements: Factorio **2.1.x**". Source: [mod portal API](https://mods.factorio.com/api/mods/factorio-mcp-server/full)

### Inferences
- Factorio's mod loader matches the major.minor in `factorio_version`, so a `2.1` mod is unavailable on a 2.0.77 server. The chengjiang mod therefore can't be dropped into Claude Crew's game tonight. This comes from how the loader works, not from a test.
- 2.1 has sat on experimental for about 4 months. A stable 2.1 could land at any time, and Claude Crew will then need an info.json bump plus a check for API changes. `hjfmailbox/factorio-docs-mcp` (Q6) indexes the API docs and does cross-version diffs, which could help with that migration.

### Gaps
- I did not read the 2.1 changelog to see which Lua API changes (if any) affect Claude Crew's calls: pathfinding, `begin_crafting`, `LuaPlayer` APIs, `helpers.*`.

---

## Q2. Profiles: version, dates, license, Factorio version, activity, adoption

### Takeaway
Only **AI Agent Bridge** is actively maintained and has real users (384 downloads, 10 releases in a month, a large test suite). Every other project is either brand new (chengjiang: 14 downloads), dormant (FV Embodied Agent: last release 2025-12-19, source repo now 404), a solo research log (Schwalbe262: 0 stars, no license), or abandoned (dested: "this doesnt work lol").

### Cited Findings

**Factorio MCP Server, by chengjiang** ([portal](https://mods.factorio.com/mod/factorio-mcp-server), [API](https://mods.factorio.com/api/mods/factorio-mcp-server/full)) [verified from portal API]
- Created 2026-10-06T09:19Z. Releases 1.0.0, 1.0.1 and 1.0.3 all came out on 2026-10-06 (1.0.2 appears in the changelog but not in the release list). Last update 2026-10-06T10:18Z, so 12 days old with nothing since.
- License GPL-3.0. Category: utilities. **Downloads: 14.** No `source_url` and no GitHub link: no public source repo is linked.
- Dependencies: `base >= 2.0.0`, optional `space-age` and `quality`. But `factorio_version` is 2.1 (see Q1).
- Testing claims [listing claim]: "42 bridge unit tests, 39 in-game self tests, 45 MCP/REST end-to-end tests, and all 37 tools called live against a real headless server."

**AI Agent Bridge (AAB), by bits-orio** ([portal](https://mods.factorio.com/mod/ai-agent-bridge), [GitHub](https://github.com/bits-orio/ai-agent-bridge)) [verified]
- Portal: created 2026-09-11. Ten releases, 1.0.0 (2026-09-11) through 1.0.9 (2026-10-11). `factorio_version` 2.0, `base >= 2.0`. MIT. **384 downloads.** Source: [portal API](https://mods.factorio.com/api/mods/ai-agent-bridge/full)
- GitHub: created 2026-09-11, last push 2026-10-11, 2 stars, 1 fork, 0 open issues, language Go, MIT. The repo has about 308 files, 11 ADRs, CI/e2e workflows, Lua unit tests with a fake game (`tests/lua/fakegame.lua`), and a Python e2e rig (`tests/e2e/rig.py`). It also contains a `CLAUDE.md`, and the portal says it was "Developed with AI coding assistants alongside human review". Source: [GitHub API](https://api.github.com/repos/bits-orio/ai-agent-bridge)
- [listing claim] "In use on 2.0 dedicated servers, vanilla and with Multi-Team Support, with and without Space Age." Part of the "MTS family" of mods (Multi-Team Support, Open Discord Bridge). Source: [portal](https://mods.factorio.com/mod/ai-agent-bridge)
- The portal API reports `score: -43.17` for this mod. What that field means is undocumented, so I am not drawing conclusions from it.

**FV Embodied Agent, by harsooo** ([portal](https://mods.factorio.com/mod/fv_embodied_agent), [API](https://mods.factorio.com/api/mods/fv_embodied_agent/full)) [verified from portal API]
- Releases 0.1.0 through 0.1.3, 2025-12-15 to 2025-12-19. **Nothing since 2025-12-19 (10 months stale).** `factorio_version` 2.0, MIT, category "content", **24 downloads**.
- `source_url` = `github.com/hrshtt/FactoryVerse/tree/main/src/fv_embodied_agent`. The GitHub API returns **404 Not Found** for `hrshtt/FactoryVerse`, and that user's public repo list doesn't include it. The Wayback CDX shows the repo page was publicly reachable on 2025-09-25, so it has since been deleted or made private. I couldn't retrieve the archived snapshot. Sources: [GitHub API repo](https://api.github.com/repos/hrshtt/FactoryVerse), [hrshtt repos](https://api.github.com/users/hrshtt/repos), [Wayback availability](https://archive.org/wayback/available?url=github.com/hrshtt/FactoryVerse)
- The same user maintains forks of `factorio-learning-environment` (FLE, pushed 2025-09-20), `factorio-docker`, and `factorio-data-collector`. That suggests FactoryVerse is a research environment in the FLE lineage. Source: [hrshtt repos](https://api.github.com/users/hrshtt/repos)

**Schwalbe262/Factorio_automation** ([GitHub](https://github.com/Schwalbe262/Factorio_automation)) [verified]
- Created 2026-06-12. The `master` head commit is 2026-06-15 ("Part 126: …"). The most recent pushes (2026-09-30, five of them) went to branch `feat/deterministic-space-age-autoplayer`. Other branches: `chore/part129-…`, `chore/part130-unattended-qwen9-supervisor`. 0 stars, 0 forks. **No license file** (GitHub `license: null`), so default copyright applies. Python. The pyproject author is "NEC". The workflow is Windows `.bat` launchers. Sources: [repo API](https://api.github.com/repos/Schwalbe262/Factorio_automation), [branches](https://api.github.com/repos/Schwalbe262/Factorio_automation/branches), [pyproject.toml](https://github.com/Schwalbe262/Factorio_automation/blob/master/pyproject.toml)
- The optional mod `factorio_ai_autoplayer` 0.1.0 declares `factorio_version` 2.0. LLM planning runs on Slurm vLLM workers using Qwen3.5 4B/9B/27B with `--max-model-len 32768`. Sources: [mods/factorio_ai_autoplayer/info.json](https://github.com/Schwalbe262/Factorio_automation/blob/master/mods/factorio_ai_autoplayer/info.json), [README](https://github.com/Schwalbe262/Factorio_automation/blob/master/README.md)

**dested/factorio-mcp-server** ([GitHub](https://github.com/dested/factorio-mcp-server)) [verified]
- Created 2025-03-12. Three commits, all that day. The last is "readme". The previous one is titled "initial scoping and kinda working but wholey broken". 0 stars, Unlicense, TypeScript. The README opens with **"this doesnt work lol"**. Sources: [repo API](https://api.github.com/repos/dested/factorio-mcp-server), [README](https://github.com/dested/factorio-mcp-server/blob/main/README.md)
- It is the **only** server under mcp.so's `#factorio` tag ("added 2 years ago" per mcp.so). Source: [mcp.so/tags/factorio](https://mcp.so/tags/factorio)

**"Factori MCP" (hosted connector on MCPBundles)**
- This is **not Factorio-related**. It connects an assistant to a "Factori workspace": data on places, people, movement and markets across 229 countries. It is hosted at `mcp.mcpbundles.com/bundle/mcpfactoriaimcp` with OAuth sign-in. Sources: [mcpbundles listing](https://www.mcpbundles.com/skills/mcpfactoriaimcp), [mcpservers.org listing](https://mcpservers.org/zh-CN/servers/docs-factori-ai-docs-model-context-protocol). This is a search-summary finding, but the name and domain (factori.ai) match.

### Inferences
- Adoption across this whole niche is tiny. Even the leader (AAB) has 384 downloads and 2 stars. None of these is battle-tested enough to sit on the critical path of tonight's multiplayer session.
- The FactoryVerse source vanished, and FV is listed under "content". Its value is design ideas from the portal description, not code. (The mod zip on the portal would still contain the Lua, but downloading needs a Factorio account token, and I installed nothing.)

### Gaps
- The chengjiang mod's source is only inside the portal zip, which needs a login to download. None of its 37 tools or 15 REST endpoints are listed by name in public text, so the tool list is a listing claim only.
- I couldn't retrieve the FactoryVerse archived README.
- The mod portal discussion tabs for all three mods showed only the "Bugs"/"Announcements" filters and no threads in the server-rendered HTML. Threads are either absent or loaded by JavaScript. Unverified.

---

## Q3. What each project exposes, its transport and auth, multiplayer behaviour, and how an LLM drives it

### Takeaway
All of the live projects use the same skeleton as Claude Crew: **a Lua mod plus an external process, talking over RCON, with one JSON object in and one JSON line out via `rcon.print`**. The differences that matter for Claude Crew:
- AAB keeps a **question ring in mod `storage`** that the service **polls with a cursor**, and the mod renders typed answer "artifacts" into chat.
- chengjiang puts a **Node HTTP/MCP/REST edge with token auth** in front of RCON.
- FV pushes action lifecycle events by **UDP** instead of being polled.
- Schwalbe262 shows what a **no-mod** `/silent-command` approach can and cannot do.

### Cited Findings

**chengjiang Factorio MCP Server** [listing claims, from the portal description and changelog; no source available]
- Two parts. The mod handles event capture, behaviour sampling and the game-side tool implementations. A zero-dependency Node bridge (Node ≥18, bundled inside the mod zip's `bridge/` folder since 1.0.3) handles the HTTP/HTTPS listener, MCP protocol, tokens, TLS, shell and file access. The two talk over RCON: "The bridge asks, the game answers with one compact JSON line." Source: [portal API description/changelog](https://mods.factorio.com/api/mods/factorio-mcp-server/full)
- MCP JSON-RPC `2024-11-05` over Streamable HTTP with sessions, SSE event streams, resources and prompt templates, plus **15 REST endpoints** for non-MCP clients and a `/health` endpoint. Auth is an `X-API-Key` header with either an "auto-rotating (a fresh token each start) or persistent" token. TLS uses PEM or Java keystores. Source: [portal](https://mods.factorio.com/mod/factorio-mcp-server)
- 37 tools in five groups:
  - Monitoring: snapshot, performance, memory, entity census, recent/player events, chat and command history.
  - World/players: player detail, forces/research, surfaces, production stats, factory overview, logistic networks, item/inventory inspection.
  - **Behaviour recording**: "high-frequency sampling of 23 core fields per player (position, movement, health, hand items, inventory snapshots) written asynchronously to JSONL, with time-range queries and CSV export".
  - Files: read/write/append/delete/list.
  - Control: console commands, game speed, pause, save, broadcast.
  - Also `execute_shell`, which is "off by default" and gated by `shell.enabled` plus `shell.denyPatterns`.

  Source: [portal](https://mods.factorio.com/mod/factorio-mcp-server)
- In-game commands: `/mcp-health`, `/mcp-tools`, `/mcp-rpc <tool> [json]`, `/mcp-selftest` (with a `json` variant). In 1.0.2 the output switched from `rcon.print` to the calling player, because "a player typing /mcp-selftest … saw nothing". "The mod is active only while the bridge is connected. Without it, the mod just records behaviour locally." The listing also claims "Every tool that the Lua sandbox cannot honour says so explicitly instead of pretending to succeed." Source: [portal changelog](https://mods.factorio.com/api/mods/factorio-mcp-server/full)
- "No gameplay changes … The mod only *reads* state and exposes it, plus a small set of explicit control actions." It adds no characters, items or GUIs. Source: [portal](https://mods.factorio.com/mod/factorio-mcp-server)

**AI Agent Bridge** [verified from repo]
- Protocol `aab-rpc-v1`: one console command, `/aab-rpc <json>`. "One JSON object in, one JSON object out through `rcon.print`." Every request carries `"v":1`. Replies are `{"ok":true,"r":...}` or `{"ok":false,"e":"<code>","m":"<detail>"}`. Ops: `status`, `providers`, `manifest`, `tools`, `call {i,f,a}`, `calls` (batch), `labels`, `poll {after,limit}`, `answer {qid,artifact}`, `answers`. Error codes: `bad_json, bad_version, bad_op, no_provider, no_tool, provider_error, bad_artifact, bad_result, too_large, no_question`. Sources: [companion-mod/README.md](https://github.com/bits-orio/ai-agent-bridge/blob/main/companion-mod/README.md), [companion-mod/scripts/rpc.lua](https://github.com/bits-orio/ai-agent-bridge/blob/main/companion-mod/scripts/rpc.lua)
- **Players cannot run it**: "The command answers RCON and the server console only; a player typing it into their own console gets one private line and nothing runs." Source: [companion README](https://github.com/bits-orio/ai-agent-bridge/blob/main/companion-mod/README.md), [SECURITY.md](https://github.com/bits-orio/ai-agent-bridge/blob/main/SECURITY.md)
- How the LLM is used:
  1. A player types `/ask …`, or a chat line with a configurable prefix such as `?` or `@ai `.
  2. The question goes into a bounded ring in `storage`.
  3. The Go service polls `poll` about once a second.
  4. The service reads the tool catalog, which providers build by scanning `remote.interfaces` for an `agent_tools_v1` probe.
  5. The service runs the model (Anthropic native or OpenRouter, "bring your own key").
  6. The answer goes back as a typed **artifact**: `summary`, `notice`, `list`, `table`, `comparison` or `art`. The mod renders it with item icons (`[img=item.iron-plate]`) and clickable map pings.

  Follow-ups share a session (3-minute idle timeout, `/ask new`, `/ask #name`). Sources: [companion README](https://github.com/bits-orio/ai-agent-bridge/blob/main/companion-mod/README.md), [ADR 0002](https://github.com/bits-orio/ai-agent-bridge/blob/main/docs/adr/0002-three-seams.md), [CONTEXT.md](https://github.com/bits-orio/ai-agent-bridge/blob/main/CONTEXT.md)
- **Read-only tools**: "every tool is a bounded read". The model "cannot … invent a tool … write anything". Source: [SECURITY.md](https://github.com/bits-orio/ai-agent-bridge/blob/main/SECURITY.md)
- **Multiplayer**: the mod must be installed "on the server and on every client" because it is a normal mod. It is multi-force aware: team-only chat gets team-only answers, and it integrates with Multi-Team Support. It works on hosted servers with no shell (pull over RCON). Event-log history is read locally or over SFTP (`service/internal/transport/sftp.go`). Sources: [companion README](https://github.com/bits-orio/ai-agent-bridge/blob/main/companion-mod/README.md), [ADR 0001](https://github.com/bits-orio/ai-agent-bridge/blob/main/docs/adr/0001-pull-over-rcon.md)
- Measured RCON floor: "roughly the measured 105 ms RCON floor" per round trip. Five calls took about 525 ms, and one 21-lookup question spent about 2.2 s on network alone. That led to the `calls` batch op (one trip per model round), with a separate reply cap `CAPS.calls` of 65536. Source: [ADR 0011](https://github.com/bits-orio/ai-agent-bridge/blob/main/docs/adr/0011-calls-batch-op.md)
- Reply caps: `call` 8,000 bytes, `tools`/`manifest` 32,768, everything else 65,536. "A reply over its cap is refused whole as `too_large`, never cut." Sources: [rpc.lua](https://github.com/bits-orio/ai-agent-bridge/blob/main/companion-mod/scripts/rpc.lua), [companion README](https://github.com/bits-orio/ai-agent-bridge/blob/main/companion-mod/README.md). (The ADR text says `call` rose to 16384 while the fetched `rpc.lua` head shows `call = 8000`. That is a minor doc/code inconsistency.)
- Game-thread cost discipline: "Every tool runs inside the RCON command on the game thread, so a slow tool is a stutter every player feels". `find_entities` is hard-capped at 2,000 entities, and the service logs any tool call over 100 ms. Source: [SECURITY.md](https://github.com/bits-orio/ai-agent-bridge/blob/main/SECURITY.md)
- Cost and spam guards:
  - Per-player cooldown of 5 s, 30 asks per minute server-wide, 400-byte question cap.
  - 20 questions per player per hour, 120 per hour server-wide, **$5.00 per rolling day**.
  - 20k tokens per question, 6 rounds, 30 lookups, 4 KB per tool result.
  - "Player-typed text … reaches the model as data."

  Source: [SECURITY.md](https://github.com/bits-orio/ai-agent-bridge/blob/main/SECURITY.md)

**FV Embodied Agent** [listing claims from the portal description; source repo 404]
- External control over RCON through remote interfaces:
  - An admin interface `agent` handles create/destroy/list.
  - **Each agent gets its own remote interface (`agent_1`, `agent_2`, …)**.
  - "Schema Export: Full method schemas with parameter validation for external bindings", with "ParamSpec" normalization and validation.

  Source: [portal API](https://mods.factorio.com/api/mods/fv_embodied_agent/full)
- Async actions return immediately, and **completion is pushed via UDP**: `walk_to` (pathfinding, adjusts the goal if it lands inside an entity), `mine_resource` (incremental `max_count` or deplete), and `craft_enqueue`. Sync actions are `place_entity`, `set_entity_recipe`, `set_entity_filter`, `set_inventory_limit`, `get/set_inventory_item`, `pickup_entity`, `enqueue_research`/`cancel_current_research` and `chart_view`. Queries are `inspect`, `get_reachable`, `get_placement_cues`, `get_recipes` and `get_technologies`. Per-tick state machines for walking, mining and crafting emit UDP events: "queued, progress, completed, cancelled". Source: [portal](https://mods.factorio.com/mod/fv_embodied_agent)
- Each agent can have its own force or share a common one. State persists through "Factorio's metatable registration" (`script.register_metatable`), and the mod raises custom events `on_agent_created`, `on_agent_removed` and `on_chunk_charted`. Files: `walking.lua, mining.lua, crafting.lua, placement.lua, entity_ops.lua, charting.lua, researching.lua, reachability.lua, RemoteInterface.lua`. Source: [portal](https://mods.factorio.com/mod/fv_embodied_agent)
- [verified] What the engine provides for UDP push: `helpers.send_udp(port, data, for_player?)` needs the instance to be started with `--enable-lua-udp`. It sends to **localhost only**, and `for_player = 0` "will only send from the server". `recv_udp` has a 256 KB receive buffer and data is lost if it overflows. Inbound packets are injected as input actions and "all this data will have to go through the multiplayer server and be distributed to all clients". Source: [Lua API 2.0.77 LuaHelpers](https://lua-api.factorio.com/2.0.77/classes/LuaHelpers.html)

**Schwalbe262/Factorio_automation** [verified from repo]
- There are two adapters:
  - **(1) No-custom-mod** RCON `/silent-command` Lua. "Other players do not need the Factorio AI mod, but RCON `/silent-command` Lua disables achievements for that save." This is now "the preferred path when multiplayer compatibility matters".
  - **(2) Custom mod** exposing `/ai_observe`, `/ai_action <json>` and `/ai_wait <ticks>`. Every MP client then needs the mod.

  Source: [README](https://github.com/Schwalbe262/Factorio_automation/blob/master/README.md)
- No-mod mechanics: Python builds one large Lua chunk per call (shared `_COMMON_LUA` prelude plus the action, compacted onto one line). It embeds the JSON action through `helpers.json_to_table`, replies via `helpers.table_to_json` and `rcon.print`, auto-accepts the "Lua console disables achievements" prompt by sending a dummy command first, and checks actions against an allowlist (`build, chart, connect_power, craft, insert, mine, move_to, …`) in Python. Source: [src/factorio_ai/modless_lua.py](https://github.com/Schwalbe262/Factorio_automation/blob/master/src/factorio_ai/modless_lua.py) (≈1,455 lines; `ALLOWED_ACTION_TYPES` near line 12, `execute_json_lua_command` near line 65, `build_modless_action_command` near line 93)
- Control philosophy: the strategic LLM picks a high-level skill (`produce_iron_plate`, `setup_power`, …) and deterministic skill code executes it. "If the strategic LLM selects a skill whose executor does not exist yet, the controller must not fake or improvise game actions. It records the missing skill in `runtime/missing-skills.jsonl`". Deterministic guardrails rewrite obvious mistakes, for example promoting `produce_electronic_circuit` to `automate_electronic_circuit_line` and logging the change. Strategy prompts carry a bounded state payload of about 16 KB of JSON for the 4B worker. Source: [README](https://github.com/Schwalbe262/Factorio_automation/blob/master/README.md)

**dested/factorio-mcp-server** [verified]
- A stdio MCP server (`StdioServerTransport`) whose tools edit an **offline blueprint**: `create_entity(ies)`, `read_entity`, `remove_entity`, `move_entity`, `create_tile`, `remove_tile`, `get_blueprint_info`, `get_blueprint_string`, `list_entity_types`, `get_entity_info`, `reset_blueprint`. It is built on `@fbe/editor` and `factorio-blueprint`. It makes **no RCON connection**: a grep for rcon in `index.ts` found nothing. Sources: [index.ts](https://github.com/dested/factorio-mcp-server/blob/main/index.ts), [package.json](https://github.com/dested/factorio-mcp-server/blob/main/package.json)

### Inferences
- AAB is the clearest proof that a **poll-based RCON design works on hosted multiplayer servers**. Its numbers (about 105 ms RCON floor, 1 Hz poll) are a good baseline for Claude Crew's 0.4 s poll: each poll costs roughly a quarter of the interval in latency floor, so batching everything into one command per tick of the orchestrator matters.
- FV-style UDP push only works if the orchestrator runs **on the same host as the Factorio server process** (localhost-only) **and** that server was started with `--enable-lua-udp`. Neither is guaranteed when a friend hosts or uses a rented server, so polling has to remain the fallback.

### Gaps
- The chengjiang REST endpoint paths beyond `/health`, `/mcp` and `/api/bridge` aren't published.
- It is unclear how the chengjiang mod detects whether the bridge is connected (possibly a `/mcp-health` heartbeat). Unverified.
- FV's UDP message format and port configuration are unknown because the source is gone.

---

## Q4. Does it control characters? Legit or cheat actions? Multiple agents?

### Takeaway
- **chengjiang and AAB do not control characters at all.** They are observation/admin and Q&A bridges.
- **FV** controls multiple script-created characters through legit-looking mechanics (pathfinding walk, mining state machine, the real crafting queue). That makes it the closest architectural match to Claude Crew, but it is dormant and its source is gone.
- **Schwalbe262's** no-mod path cannot walk a character legitimately and falls back to teleporting a "virtual" agent and crafting instantly. That is direct evidence that a mod (or OS-level input) is needed for legit movement.
- **dested** doesn't touch a running game.

### Cited Findings
- chengjiang: "Nothing is added to the game. No prototypes, no new items, no GUIs". Its control set is console command, game speed, pause, save and broadcast. Source: [portal](https://mods.factorio.com/mod/factorio-mcp-server) [listing claim]
- AAB: the mod "is not an AI … The model can call the tools in the catalog … write anything: [cannot]". Every tool is a bounded read, and the only write is rendering an answer. Source: [SECURITY.md](https://github.com/bits-orio/ai-agent-bridge/blob/main/SECURITY.md)
- FV: multi-agent support ("Create and manage multiple agents with unique IDs"), per-agent remote interfaces, pathfinding `walk_to`, a mining state machine with special handling for stochastic resources ("huge-rock"), and a crafting state machine that tracks the agent's crafting queue. `get_inventory_item`/`set_inventory_item` take items from and put items into entities. The listing doesn't say whether reach is enforced on sync actions such as `place_entity`. Source: [portal](https://mods.factorio.com/mod/fv_embodied_agent) [listing claim]
- Schwalbe262 no-mod, from [modless_lua.py](https://github.com/Schwalbe262/Factorio_automation/blob/master/src/factorio_ai/modless_lua.py):
  - **`move_to`** (around line 1177): the server/virtual agent is **teleported** (`set_server_agent_position`). For a real player it returns the error `"RCON Lua walking_state moves only one tick; use GUI input movement executor for real-player move_to"`. The README says real-player mode sends **OS-level WASD input** (`FACTORIO_AI_USE_GUI_INPUT_FOR_MOVEMENT=1`) to a GUI client. Source: [README](https://github.com/Schwalbe262/Factorio_automation/blob/master/README.md)
  - **`virtual_craft`** (around line 1155): it removes ingredients and **inserts results instantly**, using a hard-coded `VIRTUAL_RECIPES` table. Crafting a `lab` **sets the `automation-science-pack` technology to researched**. Real players go through `player.begin_crafting`, which is legit.
  - **`action_mine`** (around line 1226): for resources it **inserts ore directly and decrements `amount`**, with reach set by `action.reach or 10`. For other entities it calls `entity.mine{inventory=…}`.
  - **`action_build`** (around line 1268): it removes the item, then calls `surface.create_entity` after a `can_place_entity` manual build check. Reach is set by `action.reach or 32`, so the caller chooses it rather than the game's reach distance.
  - In short: inventory is consumed, but crafting time, mining time and walking are skipped for the virtual agent.

### Inferences
- Of these projects, **none** (except the defunct FV) matches Claude Crew's "several legit script characters alongside humans" model. Claude Crew is the more ambitious design in this space, and nothing here can replace its mod.
- The Schwalbe262 finding confirms that **a vanilla server with no mod cannot give a script character real walking**. `walking_state` set over RCON lasts one tick, and there is no `on_tick` handler to keep re-asserting it. Claude Crew's choice of a mod with a per-tick job queue is justified.
- Registering `script.on_event` from a console command to fake an on_tick handler is a known desync and save/load hazard in multiplayer. I did not verify this for 2.0.77, so treat it as such.

### Gaps
- I couldn't verify whether FV enforces reach distance or real crafting time for `place_entity`/`set_inventory_item`. The source is unavailable.

---

## Q5. Specific ideas and code worth borrowing (with file references)

### Takeaway
The high-value borrowings are almost all from **AI Agent Bridge** (MIT, well documented): batched RCON calls, hard reply caps with whole-reply refusal, bounded and self-describing entity walks, a storage ring plus cursor for chat commands, idempotent writes, a player-proof RPC command, typed chat artifacts with icons and map pings, and per-player rate and cost caps. Secondary ideas: FV's per-action lifecycle events and optional UDP push, chengjiang's per-player behaviour recording and in-game `/selftest`, and Schwalbe262's "missing skill" log and deterministic guardrails.

### Cited Findings

From **AI Agent Bridge** (MIT):
1. **One RCON trip per round (`calls` batch op).** One array of calls in, one array of results out, dispatched through the same path as a single call, and additive to the protocol. It cut N×105 ms down to about 105 ms. Claude Crew equivalent: fold "poll all actor/job states + drain chat commands + submit new jobs" into **one** RCON command per 0.4 s cycle. Sources: [docs/adr/0011-calls-batch-op.md](https://github.com/bits-orio/ai-agent-bridge/blob/main/docs/adr/0011-calls-batch-op.md), [companion-mod/scripts/rpc.lua](https://github.com/bits-orio/ai-agent-bridge/blob/main/companion-mod/scripts/rpc.lua)
2. **Per-op reply caps; refuse the whole reply as `too_large`, never truncate.** This keeps JSON parseable and lets the client page or narrow the request. Source: [rpc.lua `CAPS`/`reply_cap`](https://github.com/bits-orio/ai-agent-bridge/blob/main/companion-mod/scripts/rpc.lua)
3. **Bounded walks that describe their own coverage.** Entity scans are capped (2,000 entities, 64-tile radius by default). Every reply carries `covered`, `examined`, `budget` and `exhausted`. A missing anchor returns `refused`/`why`/`accepts`, which the model treats as an ordinary result. "Counter-backed reads always sweep every force … in one call", so the engine's own counters (production statistics, `get_item_count` on a logistic network) come before `find_entities_filtered`. "Policy in Lua cannot be argued with the way a prompt instruction can." This applies directly to Claude Crew's bottleneck-diagnosis and logistic-network tools, which run on the game thread. Source: [docs/adr/0009-tiers-and-bounded-walks.md](https://github.com/bits-orio/ai-agent-bridge/blob/main/docs/adr/0009-tiers-and-bounded-walks.md)
4. **Chat commands go into a storage ring, and a cursor poll reads them** (`poll {after, limit}`; `status.last_id` gives "from here on"). "an agent that restarts re-answers nothing." This is more robust than scraping chat from logs and survives orchestrator restarts mid-session. Sources: [companion README "Questions"](https://github.com/bits-orio/ai-agent-bridge/blob/main/companion-mod/README.md), [ADR 0001](https://github.com/bits-orio/ai-agent-bridge/blob/main/docs/adr/0001-pull-over-rcon.md)
5. **Idempotent write ops.** `answer` checks `question.answered` and returns ok without re-rendering, "so a retry costs the asker nothing". Validation and rendering happen before state is marked. Claude Crew equivalent: client-assigned job IDs so a retried `submit_job` after an RCON timeout never enqueues the job twice. Source: [rpc.lua `OPS.answer`](https://github.com/bits-orio/ai-agent-bridge/blob/main/companion-mod/scripts/rpc.lua)
6. **The RPC command refuses players.** Only RCON and the server console can run `/aab-rpc`; players get one private line. Claude Crew's JSON command must do the same (check `command.player_index == nil`), or any friend could type raw API calls. Source: [SECURITY.md](https://github.com/bits-orio/ai-agent-bridge/blob/main/SECURITY.md)
7. **Typed answer artifacts rendered by the mod.** `summary`/`notice`/`list`/`table`/`comparison`/`art` have hard caps (for example 3 lines for a summary, 8 rows for a table). The mod handles rich-text icons, map pings, control-character scrubbing (so a player name can't forge a line) and UTF-8-safe cutting. An over-cap answer goes back to the model to rewrite at most twice. `to_asker: true` makes a reply private. This fits Claude Crew's crew status and acknowledgement messages ("on it: fixing iron at [gps=…]"). Sources: [companion README "Artifacts"](https://github.com/bits-orio/ai-agent-bridge/blob/main/companion-mod/README.md), [CONTEXT.md](https://github.com/bits-orio/ai-agent-bridge/blob/main/CONTEXT.md)
8. **Guards for chat-triggered spending.** Per-player cooldown, per-minute and per-hour caps, a daily USD cap, per-question token, round and lookup caps, and "player-typed text reaches the model as data". Claude Crew's coordinator (Opus) is triggered by chat, so it needs at least a cooldown and a daily cap. Source: [SECURITY.md](https://github.com/bits-orio/ai-agent-bridge/blob/main/SECURITY.md)
9. **Testing scaffolding.** `tests/lua/fakegame.lua` with `luarun.py` runs mod Lua outside the game, and `tests/e2e/rig.py`/`scenarios.py` run against a real server. It also has a `rpc_selftest` op. Source: [repo tree](https://github.com/bits-orio/ai-agent-bridge)
10. **Pull, not push; no periodic handler in the mod.** "The companion registers no periodic handler. Every read happens inside the console command." This keeps per-tick cost at zero for all peers. Claude Crew does need on_tick for its actors, but its *diagnostic* reads can follow this rule. Source: [ADR 0001](https://github.com/bits-orio/ai-agent-bridge/blob/main/docs/adr/0001-pull-over-rcon.md)
11. **Extensible tool discovery.** Any mod can expose an `agent_tools_v1` probe on its remote interface, and the catalog is rebuilt by scanning `remote.interfaces`. This is low priority for Claude Crew. Source: [ADR 0002](https://github.com/bits-orio/ai-agent-bridge/blob/main/docs/adr/0002-three-seams.md)
12. **Prompt-cache-friendly layout.** The briefing goes in the user turn (`docs/adr/0008-briefing-in-the-user-turn.md`), and there is a test for it (`service/internal/agent/prompt_cache_test.go`). I only saw the file names and did not read their content. Source: [repo tree](https://github.com/bits-orio/ai-agent-bridge)

From **FV Embodied Agent** (MIT; ideas only, source 404):

13. **An action lifecycle event stream:** `queued → progress → completed | cancelled` for every async action, emitted by per-tick state machines. The listing also describes per-agent remote interfaces and schema export with parameter validation (ParamSpec). For Claude Crew, a per-job event log is easy to drain in each poll and makes "minimal idle time" measurable. Source: [portal](https://mods.factorio.com/mod/fv_embodied_agent)
14. **Optional UDP push.** `helpers.send_udp(port, json, 0)` on job completion, so the orchestrator wakes immediately instead of waiting up to 0.4 s. It requires `--enable-lua-udp` and a localhost orchestrator, and `for_player=0` means only the server sends, which avoids duplicate packets from every peer. Sources: [LuaHelpers 2.0.77](https://lua-api.factorio.com/2.0.77/classes/LuaHelpers.html), [FV portal](https://mods.factorio.com/mod/fv_embodied_agent)
15. **`walk_to` goal adjustment** "if target position is inside an entity", and `get_placement_cues(entity_name)`. Source: [portal](https://mods.factorio.com/mod/fv_embodied_agent)

From **chengjiang Factorio MCP Server** (GPL-3.0; ideas only, since copying code would impose GPL):

16. **Per-player behaviour recording to JSONL**: 23 fields per sample, written asynchronously, queryable by time range, exportable to CSV. For Claude Crew this could record the human friend's and the actors' traces for the benchmark harness and idle-time analysis. Source: [portal](https://mods.factorio.com/mod/factorio-mcp-server)
17. **In-game `/…-selftest` and `/…-health` commands** that print to the calling player (the 1.0.2 fix: `rcon.print` alone is invisible to players), with a short verdict in chat and the full report in a `json` variant. Source: [portal changelog](https://mods.factorio.com/api/mods/factorio-mcp-server/full)
18. **"Honest about limits"**: tools return an explicit "cannot" instead of faking success. **Lenient config parsing** with fallback to defaults. **Auto-rotating API token** printed with a ready-to-paste MCP config. Graceful ordered shutdown of RCON and sockets. Source: [portal](https://mods.factorio.com/mod/factorio-mcp-server)

From **Schwalbe262/Factorio_automation** (no license, so ideas only):

19. **Log missing skills instead of improvising**: `runtime/missing-skills.jsonl`. There are also **deterministic guardrails that rewrite LLM choices** (for example hand-craft becomes automate-line) and log each rewrite. This maps onto Claude Crew's coordinator/scheduler split: the scheduler can reject or rewrite work orders that have no executor. Source: [README](https://github.com/Schwalbe262/Factorio_automation/blob/master/README.md)
20. **No-mod JSON-over-`/silent-command`** using `helpers.json_to_table` and `helpers.table_to_json`, with the achievement prompt pre-accepted. This is a fallback for *read-only observation* on servers where the Claude Crew mod can't be installed. Source: [modless_lua.py](https://github.com/Schwalbe262/Factorio_automation/blob/master/src/factorio_ai/modless_lua.py)

From other registry entries:

21. **phiresky/factorio-mcp** tool menu, for coverage ideas: `get_player_surroundings` (nearby entities, resources, enemies, GUI state, cursor stack, vehicle, walking state), `get_electric_network` (satisfaction), `get_alerts`, `get_space_platforms`, `get_planets`, `get_train_info`. `get_space_platforms` and `get_alerts` are directly relevant to helping a friend with their first space platform. Source: [phiresky/factorio-mcp README](https://github.com/phiresky/factorio-mcp)
22. **jerome3o/factorio-mcp** puts an HTTP backend with an `X-API-Key` header in front of RCON, which "isolates the RCON password". Source: [README](https://github.com/jerome3o/factorio-mcp)

### Inferences
- Priority for tonight (robustness with humans present): items 1, 4, 5, 6, 8 and 17 are cheap and cut real failure modes (lag, duplicate jobs, lost commands after a restart, friends triggering raw API calls, runaway Opus spend). Items 3 and 13 matter next, for late-game diagnostic tools and idle-time measurement. Items 14 and 16 are later work.
- Licenses: AAB (MIT) and FV (MIT) code can be adapted with attribution. chengjiang (GPL-3.0) and Schwalbe262 (no license) are idea-only sources.

### Gaps
- I read AAB's `poll.go`, `runner.go` and `briefing.go` by file name only. I did not inspect the Go implementation details: retry/backoff, RCON reconnect behaviour.

---

## Q6. Other Factorio entries in MCP registries (mcp.so, glama.ai, smithery, mcpbundles, pulsemcp)

### Takeaway
Registries list about 15 Factorio MCP projects, all small: 0–14 stars, mostly one-shot repos from 2024–2026. Most are either raw RCON/Lua escape hatches (admin) or character-playing attempts covered by other researchers. None is a mature component.

### Cited Findings
- **mcp.so** `#factorio`: only `dested/factorio-mcp-server`. Source: [mcp.so/tags/factorio](https://mcp.so/tags/factorio)
- **PulseMCP**: lveillard "Factorio AI Companion" (released 2026-01-18) and WidAmi "FactoMCP" (2026-04-12). No visitor stats. Source: [pulsemcp search](https://www.pulsemcp.com/servers?q=factorio)
- **Glama** search "factorio" lists: Danconnolly/factorio-player-mcp, PlasmaChroma/FactorioMCP, greenhat616/factorio-recipe-mcp, hjfmailbox/factorio-docs-mcp, linsyking/factorio-mcp, lveillard/factorio-ai-companion, mmckeen-nv/factorio-companion, phiresky/factorio-mcp. Source: [glama.ai search](https://glama.ai/mcp/servers?query=factorio)
- **mcpbundles**: "Factori MCP" is unrelated (Factori.ai data). Source: [mcpbundles](https://www.mcpbundles.com/skills/mcpfactoriaimcp)
- **Smithery**: no Factorio entries surfaced in my searches. I did not query Smithery directly.
- GitHub metadata [verified via GitHub API, 2026-10-18]:

| Repo | What | Created | Last push | Stars | Lang | License |
|---|---|---|---|---|---|---|
| [phiresky/factorio-mcp](https://github.com/phiresky/factorio-mcp) | stdio MCP; 2.0 admin + game-state reads + `lua_exec`/`rcon_command` escape hatches | 2026-06-30 | 2026-06-30 | 0 | TS | none |
| [jerome3o/factorio-mcp](https://github.com/jerome3o/factorio-mcp) | FastMCP + FastAPI RCON proxy with API key; `run_lua`, `give_items`, `teleport_player`, screenshots (cheat/admin) | 2024-12-07 | 2024-12-07 | 10 | Py | none |
| [WidAmi/FactoMCP](https://github.com/WidAmi/FactoMCP) | character play via RCON (walk/mine/craft/place) + `run_lua` | 2026-04-11 | 2026-04-20 | 10 | Py | MIT |
| [MarkMcCaskey/factorioctl](https://github.com/MarkMcCaskey/factorioctl) | Rust CLI + tools for Claude Code to play | 2026-01-26 | 2026-01-26 | 11 | Rust | none |
| [lveillard/factorio-ai-companion](https://github.com/lveillard/factorio-ai-companion) | companions via MCP, "51 RCON commands", chat mod | 2026-01-17 | 2026-09-13 | 14 | Lua | MIT |
| [sbarisic/FactorioMCP](https://github.com/sbarisic/FactorioMCP) | C# "play without cheating" | 2026-04-01 | 2026-04-05 | 13 | HTML | MIT |
| [jessiqa1118/factorio-mcp](https://github.com/jessiqa1118/factorio-mcp) | TS RCON bridge for Claude Desktop/Cline | 2025-04-05 | 2025-04-05 | 1 | JS | none |
| [Danconnolly/factorio-player-mcp](https://github.com/Danconnolly/factorio-player-mcp) | "connects to the game as a player" | 2026-09-13 | 2026-09-22 | 0 | Py | MIT |
| [PlasmaChroma/FactorioMCP](https://github.com/PlasmaChroma/FactorioMCP) | (no description) | 2026-09-07 | 2026-09-08 | 1 | TS | none |
| [linsyking/factorio-mcp](https://github.com/linsyking/factorio-mcp) | (no description; Lua-heavy, likely mod-side) | 2026-09-23 | 2026-09-30 | 2 | Lua | MIT |
| [greenhat616/factorio-recipe-mcp](https://github.com/greenhat616/factorio-recipe-mcp) | recipe data MCP | 2026-09-15 | 2026-10-05 | 0 | Py | none |
| [hjfmailbox/factorio-docs-mcp](https://github.com/hjfmailbox/factorio-docs-mcp) | syncs the official mod API docs into SQLite; search + **cross-version diff** for migrating between major versions | 2026-07-29 | 2026-07-29 | 0 | TS | MIT |
| [mmckeen-nv/factorio-companion](https://github.com/mmckeen-nv/factorio-companion) | "helping players" MCP | 2026-07-18 | 2026-07-18 | 0 | JS | Apache-2.0 |

  Sources: GitHub REST API per repo; descriptions from the repo `description` fields and the READMEs for phiresky and jerome3o.
- The WidAmi FactoMCP forum thread (2026-04-21): its author reports "limited success". The agent "relies too heavily on hand crafting and mining" and built no end-to-end working line, only red and green science assemblers hand-fed from chests. A later reply (2026-06-08) argues that coding-agent harnesses lack memory and rule-tracking for this task. Source: [Factorio forums thread](https://forums.factorio.com/viewtopic.php?p=691533)

### Inferences
- The pattern across the field: generic "LLM + raw Lua/RCON tool" setups stall at hand-crafting. The projects that last (AAB, Schwalbe262) move the work into deterministic skill or tool code and keep the LLM at the planning or answering level. Claude Crew's coordinator → scheduler → deterministic controller design already follows this.
- `hjfmailbox/factorio-docs-mcp` (API cross-version diff) is the one registry entry with practical use for Claude Crew, as a dev aid for the 2.0 → 2.1 migration. It is a 0-star single-commit repo, so treat it as unproven.

### Gaps
- I did not open the READMEs of Danconnolly, PlasmaChroma, linsyking, greenhat616 or mmckeen-nv, so their capabilities are known from names and descriptions only.
- Smithery wasn't queried directly.

---

## Q7. Fit vs Claude Crew: adopt as a component, borrow ideas, or ignore

### Takeaway
**Adopt nothing as a runtime component for tonight. Borrow heavily from AI Agent Bridge, selectively from FV, chengjiang and Schwalbe262, and ignore dested, Factori MCP and the raw-Lua MCP servers.**

### Cited Findings (basis for each verdict)
- **chengjiang Factorio MCP Server: ignore as a component; borrow ideas (behaviour recording, selftest, honest-limits).**
  - It targets Factorio **2.1** and Claude Crew runs **2.0.77** (current stable). Sources: [mod API](https://mods.factorio.com/api/mods/factorio-mcp-server/full), [release API](https://factorio.com/api/latest-releases)
  - It does no character control and has a read/admin focus. Source: [portal](https://mods.factorio.com/mod/factorio-mcp-server)
  - 12 days old, 14 downloads, GPL-3.0, no public repo.
  - It ships file read/write/delete and an optional host shell to the LLM. That is a big attack surface on a server with friends. Source: [portal](https://mods.factorio.com/mod/factorio-mcp-server)
- **AI Agent Bridge: borrow ideas and code (MIT). Don't run it alongside Claude Crew tonight.**
  - It is read-only Q&A with no actions, so it can't "go fix our iron bottleneck". Source: [SECURITY.md](https://github.com/bits-orio/ai-agent-bridge/blob/main/SECURITY.md)
  - It would add a second mod every client must install, a Go service, a second model key and budget, and a second RCON poller on the same server. It does claim to coexist with another RCON user (Open Discord Bridge). Source: [portal](https://mods.factorio.com/mod/ai-agent-bridge)
  - Its protocol, safety and bounded-read designs are the best-documented patterns in this space (Q5 items 1–12).
- **FV Embodied Agent: borrow design ideas only.**
  - It is architecturally the closest: multiple script characters, per-agent interfaces, async actions with lifecycle events, UDP push.
  - But it is dormant since 2025-12-19, the source repo returns 404, and it has 24 downloads. Sources: [portal API](https://mods.factorio.com/api/mods/fv_embodied_agent/full), [GitHub 404](https://api.github.com/repos/hrshtt/FactoryVerse)
- **Schwalbe262/Factorio_automation: ignore as a component; borrow lessons.**
  - Its no-mod track gives up legit walking (teleport for the virtual agent; OS keyboard input for a real player), crafts instantly, and inserts ore directly. That conflicts with Claude Crew's legit-player rules. Source: [modless_lua.py](https://github.com/Schwalbe262/Factorio_automation/blob/master/src/factorio_ai/modless_lua.py)
  - It has no license and is Windows/Slurm-centric. Source: [README](https://github.com/Schwalbe262/Factorio_automation/blob/master/README.md)
  - Lessons worth keeping: the missing-skill log, the deterministic guardrails, and the confirmation that Claude Crew's mod is necessary.
- **dested/factorio-mcp-server: ignore.** It is abandoned, self-described as broken, and works on offline blueprints only. Source: [README](https://github.com/dested/factorio-mcp-server/blob/main/README.md)
- **"Factori MCP": ignore.** It is not a Factorio product. Source: [mcpbundles](https://www.mcpbundles.com/skills/mcpfactoriaimcp)
- **phiresky / jerome3o / jessiqa1118 raw RCON MCPs: ignore as components.** Their tools are `lua_exec`/`give_items`/`teleport` escape hatches, which are cheats under Claude Crew's rules. phiresky's read-tool list is a useful checklist (Q5 item 21). Sources: [phiresky README](https://github.com/phiresky/factorio-mcp), [jerome3o README](https://github.com/jerome3o/factorio-mcp)

### Inferences
- **Claude Crew is ahead of all of these on the dimension that matters:** multiple *legit* characters taking actions from chat, with deterministic execution. None of the bridges does that. The prior art's value is in transport robustness, safety and bounded diagnostics, not in gameplay.
- **Concrete pre-session checklist from this research:**
  1. Make sure the Claude Crew RCON JSON command rejects player invocations.
  2. Make job submission idempotent.
  3. Batch each 0.4 s poll into one RCON command.
  4. Add a per-player cooldown and a daily spend cap on chat-triggered coordinator calls.
  5. Cap the reply size of every diagnostic tool and the entity count of every scan.
  6. Add an in-game `/crew-selftest` that prints to the caller.

### Gaps
- I have no evidence on how any of these projects behaves in a *long* multiplayer session with humans present (desyncs, UPS impact). None publishes such reports, apart from AAB's general per-call timing logs.
