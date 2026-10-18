# FLE (Factorio Learning Environment) and 2025-2026 research on LLM agents in Factorio, as prior art for Claude Crew

Research date: 2026-10-18. Labels used below:
- **[SRC]**: verified by reading source code. The local snapshot is at `/tmp/claude-1000/-home-stephen-ops/dca040bd-512a-4ed8-b7ff-9ffd9741ccde/scratchpad/src/factorio-learning-environment`. Its `pyproject.toml` says version 0.4.8, its files are dated 2026-09-06, and it matches upstream `main` HEAD ("Release 0.4.8 ...", 2026-09-06), so it is **current**, not stale. GitHub links point to the same paths on `main`.
- **[CLAIM]**: stated by the authors (release notes, blog, paper) and not independently verified.

---

## 1. Latest version and date, license, Factorio version, Space Age, activity

### Takeaway
FLE's code is at **v0.4.8 (2026-09-06)**, but PyPI's newest release is **0.4.3 (2026-04-06)**. It is MIT-licensed and moved from Factorio 1.1.110 to **2.0.73** in March 2026. It runs the **base game only (no Space Age)**. Activity has slowed to occasional maintenance bursts: the last commit is 6 weeks old, and there have been no feature releases since 0.3.0 (Oct 2025).

### Cited Findings
- [SRC] `pyproject.toml` declares `version = "0.4.8"` and `license = MIT`, with authors Jack Hopkins, Mart Bakler, Neel Kant and Kian Kyars. Python requirement is >=3.10. — [pyproject.toml](https://github.com/JackHopkins/factorio-learning-environment/blob/main/pyproject.toml)
- Upstream `main` commits:
  - 2026-09-06: "Release 0.4.8: linear-time state save/restore and tool responses (#407)"
  - 2026-09-03/04: 0.4.4 to 0.4.7
  - 2026-06-11: three small fixes (path polling, dockerignore, automated production score)
  - 2026-04-06: 0.4.3
  - 2026-03-27: "Upgrade to Factorio 2.0 (#355)"
  - 2026-02-16: Ollama support
  - Nov 2025: docs moved to Sphinx

  — [GitHub commits](https://github.com/JackHopkins/factorio-learning-environment/commits/main)
- PyPI history: 0.2.0rc0 (2025-05-08), 0.2.2 (2025-07-09), 0.3.0 (2025-10-03), 0.4.0/0.4.1/0.4.2 (2026-03-27), and **0.4.3 (2026-04-06) as the latest on PyPI**. 0.4.4 to 0.4.8 are on GitHub only. — [PyPI](https://pypi.org/project/factorio-learning-environment/#history)
- Repo stats: 887 commits, about 1.2k stars, 103 forks, 58 open issues, 21 open PRs. The README says Factorio "2.0.73 or later, only for optional rendering". Install is `pip install factorio-learning-environment[eval,mcp,psql]`, then `fle cluster start` and `fle eval --config ...`. — [GitHub README](https://github.com/JackHopkins/factorio-learning-environment)
- v0.4.0 (2026-03-27) "migrates FLE from Factorio 1.1.110 to Factorio 2.0.73", using Docker image `factoriotools/factorio:2.0.73`. It notes 13 breaking API changes:
  - 16-direction system
  - filter inserter removed; bulk inserter added
  - inventory API returns a list
  - Lua `global` renamed to `storage`

  0.4.1 is a same-day hotfix for direction bugs introduced in 0.4.0. — [CHANGELOG.md](https://github.com/JackHopkins/factorio-learning-environment/blob/main/CHANGELOG.md)
- [SRC] Space Age is not supported:
  - `fle/cluster/mods/mod-list.json` enables only `base`.
  - There are no Space Age or space-platform references in `fle/`.
  - The release notes never mention Space Age or quality.

  — [mod-list.json](https://github.com/JackHopkins/factorio-learning-environment/blob/main/fle/cluster/mods/mod-list.json)
- 0.4.4 to 0.4.8 (Sep 2026) are fixes only:
  - a2a-sdk 1.1.x compatibility, and migration from gym to gymnasium
  - `connect_entities` pole collision fix
  - Factorio 2.0 technology enum fixes
  - Inspect throughput task definitions
  - `--model-base-url`
  - `[mcp]` extra made installable (it was broken before; it now declares `fastmcp>=2.14.0`)
  - RCON reply compression (see §5)

  — [CHANGELOG.md](https://github.com/JackHopkins/factorio-learning-environment/blob/main/CHANGELOG.md)
- v0.4.3 (2026-04-06) added:
  - an **Inspect AI** sandbox, colocating the Factorio server and FLE in one container behind an HTTP bridge (`fle sandbox build`, `fle inspect-eval --sandbox`)
  - a `NameError` when agent code shadows built-in tools
  - a stdout cap raised from 64 to 512 lines

  — [GitHub releases](https://github.com/JackHopkins/factorio-learning-environment/releases)

### Inferences
- Claude Crew pins Factorio 2.0.77, and FLE targets 2.0.73. Both are 2.0 base game, so FLE's Lua is close enough to read and port. FLE has no Space Age content to borrow.
- The project now appears to be in maintenance mode. The last feature-scale releases were 0.3.0 (Oct 2025) and the 2.0 port (Mar 2026). The Sep 2026 burst is reliability and eval infrastructure. Depending on FLE as a library means pinning a git SHA, because PyPI is 5 versions behind.

### Gaps
- I did not verify whether the PyPI wheel 0.4.3 differs materially from git 0.4.8, beyond the changelog.
- I found no FLE roadmap for Space Age, and none for 2.0.7x versions after 2.0.73.

---

## 2. How the agent acts, how characters are created, fast mode, and coexistence with humans

### Takeaway
Agents act by **Python program synthesis in a REPL**. Each step is a whole program that runs against a namespace of about 28 agent tools, with Lua executed over RCON. Yesterday's finding still holds at 0.4.8:
- `create_agent_characters` **destroys every character entity on surface 1** and spawns fresh unattached `character` entities near (0,0).
- **`fast=True` is the default**, which teleports along paths and crafts instantly.
- Init also removes enemies, sets always_day, and (by default) clears entities.

FLE is designed to own a dedicated headless server. **It cannot safely coexist with human players.**

### Cited Findings
- README: "observation (output streams from the last program) → action (generate a Python program) → feedback (execution, variable assignment, output)". — [README](https://github.com/JackHopkins/factorio-learning-environment)
- [SRC] `fle/env/namespace.py` walks the program's AST node by node (`execute_body`/`execute_node`) using `eval`/`exec`. Variables and agent-defined functions persist across steps. Since 0.4.3, redefining a built-in tool name raises `NameError` ([release notes](https://github.com/JackHopkins/factorio-learning-environment/releases)). — [namespace.py](https://github.com/JackHopkins/factorio-learning-environment/blob/main/fle/env/namespace.py)
- [SRC] Agent tools live in `fle/env/tools/agent/`, one folder per tool, each with `client.py`, `server.lua` and an `agent.md` manual. The 28 tools include:
  - `can_place_entity`, `connect_entities`, `craft_item`, `extract_item`, `get_connection_amount`, `get_entities`, `get_entity`, `get_prototype_recipe`, `get_research_progress`, `get_resource_patch`, `harvest_resource`, `insert_item`, `inspect_inventory`, `launch_rocket`, `move_to`, `nearest`
  - `nearest_buildable`, `pickup_entity`, `place_entity`, `place_entity_next_to`, `print`, `rotate_entity`, `send_message`, `set_entity_recipe`, `set_research`, `shift_entity`, `sleep`, `score`

  Admin tools (`reset`, `clear_entities`, `set_inventory`, `load_blueprint`, `save_entity_state`, `create_agent_characters`, `render`, ...) are in `fle/env/tools/admin/`. The system prompt is generated from the tool signatures, docstrings and the `agent.md` manuals (`fle/env/utils/controller_loader/system_prompt_generator.py`). — [tools/agent](https://github.com/JackHopkins/factorio-learning-environment/tree/main/fle/env/tools/agent)
- [SRC] `storage.actions.create_agent_characters(num_agents)` does three things:
  1. Starts with `for _, entity in pairs(game.surfaces[1].find_entities_filtered{type = "character"}) do entity.destroy() end`. The same loop appears twice, and it would also kill human players' characters.
  2. Runs `create_entity{name="character", position={x=0, y=(i-1)*2}, force=game.forces.player}`. These characters are not attached to any `LuaPlayer`.
  3. Sets `surface.always_day=true`.

  — [create_agent_characters/server.lua](https://github.com/JackHopkins/factorio-learning-environment/blob/main/fle/env/tools/admin/create_agent_characters/server.lua)
- [SRC] `storage.utils.ensure_valid_character(player_index)` silently respawns a dead or invalid agent character at the spawn offset (`fle/env/mods/utils.lua`). Tools look characters up through `storage.agent_characters[player_index]`, never through `game.players`. — [utils.lua](https://github.com/JackHopkins/factorio-learning-environment/blob/main/fle/env/mods/utils.lua)
- [SRC] `FactorioInstance.__init__(..., fast=True, num_agents=1, ...)` and `initialise(fast=True, all_technologies_researched=True, clear_entities=True)`. These send `/sc storage.fast = true`, call `_create_agent_characters`, run `storage.utils.remove_enemies()` and reset (clear entities). — [instance.py](https://github.com/JackHopkins/factorio-learning-environment/blob/main/fle/env/instance.py)
- [SRC] Fast mode in `move_to/server.lua` loops over path waypoints with `player.teleport(target_position)`. It adds the movement ticks that walking would have taken to `storage.elapsed_ticks` (simulated time accounting). With `fast=false`, it uses `storage.walking_queues` and an on_tick walker, and the Python client long-polls until arrival. — [move_to/server.lua](https://github.com/JackHopkins/factorio-learning-environment/blob/main/fle/env/tools/agent/move_to/server.lua)
- [SRC] Fast mode in `craft_item/server.lua` directly `remove_item`s the ingredients and `insert`s the product, after a recursive intermediate craft and an inventory-space check. It adds the recipe's crafting ticks to `elapsed_ticks`. Slow mode uses `player.begin_crafting`. — [craft_item/server.lua](https://github.com/JackHopkins/factorio-learning-environment/blob/main/fle/env/tools/agent/craft_item/server.lua)
- [SRC] There is no Factorio mod. All Lua is injected over RCON as `/sc <script>` (and `/c`), with checksum caching (`fle/env/lua_manager.py`), into `storage.actions.*`. Scenarios are `default_lab_scenario` and `open_world` (`fle/cluster/scenarios/`). — [lua_manager.py](https://github.com/JackHopkins/factorio-learning-environment/blob/main/fle/env/lua_manager.py)
- [SRC] One sign of legitimate rules: `can_place_entity` uses `build_check_type = defines.build_check_type.manual` "so the engine applies the same rules as when a human player builds". Other tools still use `teleport`, for example `avoid_entity` in `utils.lua`, which teleports the character up to 10 tiles to find a placeable spot. — [utils.lua](https://github.com/JackHopkins/factorio-learning-environment/blob/main/fle/env/mods/utils.lua)
- [CLAIM] The v0.2 notes say FLE "leverage[s] Factorio's native multiplayer mechanics to support multi-agent scenarios". The code shows this means multiple scripted `character` entities on the `player` force, not multiple connected players. — [FLE v0.2 release notes](https://jackhopkins.github.io/factorio-learning-environment/versions/0.2.0.html)

### Inferences
- Human coexistence is not supported. Three things rule it out:
  - character destruction at init
  - entity clearing on reset
  - teleport and instant-craft defaults

  Running in fast=false mode avoids some of this, but the init and reset paths are still destructive. Claude Crew's "legit player rules, alongside humans" design really is a different product, and FLE's Lua should be read as reference, not reused as-is.
- FLE has no mod, so all state lives in `storage` and is mutated via `/sc`. Each tool call therefore has the console-command cost, and `/sc` disables achievements. Claude Crew's design (a real mod plus a job queue) is the more robust choice for persistent multiplayer.
- Functions stored in `storage.actions` may not survive a save/load. This is not verified, so treat it as a question for anyone porting FLE Lua into a mod.

### Gaps
- I did not check whether any FLE path attaches characters to real `LuaPlayer`s (e.g. `player.set_controller`). From grep, all lookups go through `storage.agent_characters`.
- I did not run FLE, so performance of fast=false and walking-queue reliability are unverified.

---

## 3. Multi-agent support, A2A protocol, and coordination results

### Takeaway
Multi-agent in FLE means **N scripted characters on one force, taking strict turns**: "agents fully yield to each other". Each has its own Python namespace and talks over a `send_message()` tool backed by a local **A2A JSON-RPC server**. The only multi-agent tasks are three **2-agent iron-plate throughput variants: free, impostor, and distrust**. FLE published **no quantitative coordination results**, only qualitative notes that agents "struggle to fully account for each others' actions". It lists multi-agent coordination as future work.

### Cited Findings
- [CLAIM] v0.2 (2025-05-08): "Agents can communicate in a broadcast or peer-to-peer fashion, and tasks can now be constructed with custom instructions for different agents ... In this release, agents fully yield to each other when planning and taking actions in order to minimize coordination challenges. Despite the lack of true concurrency, we find agents can struggle to fully account for each others' actions, leading to novel errors potentially difficult to recover from." — [FLE v0.2 notes](https://jackhopkins.github.io/factorio-learning-environment/versions/0.2.0.html)
- v0.2.2 (2025-07-09) added "an A2A feature adding a server, agent cards, discovery, and message passing". v0.3.0 (2025-10-03) added a "multi-agent gym environment" and a "Claude Code subagent implementation". — [GitHub releases](https://github.com/JackHopkins/factorio-learning-environment/releases)
- [SRC] A2A implementation:
  - `fle/env/protocols/a2a/server.py` (343 lines) is a FastAPI JSON-RPC server, default `localhost:8000`, with an `AgentRegistry` (register/unregister/list agents with agent cards, store/get messages).
  - `A2AFactorioInstance`/`A2AFactorioNamespace` auto-start it and register agents.
  - The `send_message(message, recipient=None, metadata=None)` tool builds an `a2a.types.Message(role="agent", parts=[Part(text=...)], metadata={sender, recipient, timestamp})`. With `recipient=None` it broadcasts. It also renders the message in-game, and it is a no-op in single-agent mode.

  — [a2a/server.py](https://github.com/JackHopkins/factorio-learning-environment/blob/main/fle/env/protocols/a2a/server.py), [send_message/client.py](https://github.com/JackHopkins/factorio-learning-environment/blob/main/fle/env/tools/agent/send_message/client.py)
- [SRC] Multi-agent tasks (`fle/eval/tasks/task_definitions/multiagent/multiagent_tasks.py`):
  - `iron_plate_throughput_multiagent_{free,impostor,distrust}`, with `num_agents=2`, `trajectory_length=16`, and a 60 s holdout.
  - The shared goal: "produce 100 iron plates per minute ... Discuss among each other how to divide the work ... DO NOT attempt to work on the same entities or subsystems as the other agent if they have declared ownership of them".
  - The impostor variant tells agent 2 to "sabotage the factory without getting caught".

  — [multiagent_tasks.py](https://github.com/JackHopkins/factorio-learning-environment/blob/main/fle/eval/tasks/task_definitions/multiagent/multiagent_tasks.py)
- [SRC] The multi-agent system prompt says "You are Agent {i} out of {n} ... Start each program with a send_message() call ... End each program with a send_message() call ... If your program errors out prior to send_message() being called, the message will not be sent." — [system_prompt_generator.py](https://github.com/JackHopkins/factorio-learning-environment/blob/main/fle/env/utils/controller_loader/system_prompt_generator.py)
- [SRC] Gym usage is `gym.make("Factorio-MultiAgentTask-v0")`, with `Action(agent_idx=..., code=...)` per agent. — [gym_env/README.md](https://github.com/JackHopkins/factorio-learning-environment/blob/main/fle/env/gym_env/README.md)
- [CLAIM] In the v0.3.0 report, multi-agent coordination appears only under future work: "Can agents learn division of labor? Negotiate resource allocation? Develop comparative advantage ...?" — [FLE v0.3.0 report](https://jackhopkins.github.io/factorio-learning-environment/versions/0.3.0.html)

### Inferences
- FLE's multi-agent design has no coordinator, no work orders, no ownership model beyond prompt text, and no concurrency. It is peer-to-peer chat between equal agents. Claude Crew's coordinator, structured work orders, `done_when` checks and deterministic scheduler go well beyond it. FLE offers no evidence for or against hierarchical splits.
- The impostor and distrust tasks may still be worth borrowing as safety and robustness scenarios, for example a crew member that acts against the plan, or a human griefer.
- A2A is used as little more than a message bus with agent cards. It adds dependency churn (0.4.4 had to fix a2a-sdk 1.1 `TextPart` removal) for little gain over an in-process queue.

### Gaps
- No multi-agent results (scores, success rates, message logs) were published in the FLE notes or repo. A search found no paper using FLE multi-agent mode.
- I did not find out what the "Claude Code subagent implementation" (v0.3.0 PR) contains. It may live in the separate `claude-code-plays-factorio` repo.

---

## 4. MCP server: tools exposed and how Claude Code uses it

### Takeaway
FLE's MCP server is built on FastMCP, under `fle/env/protocols/_mcp/`. It is essentially **one big `execute(code)` tool** (the Python REPL), plus `render`, **git-like game-state version control** (`commit`/`restore`/`undo`/`view_history`) and recipe/doc lookup. Claude Code plays through the separate `claude-code-plays-factorio` starter repo. The FLE team livestreamed "Claude Code plays Factorio" on Twitch around v0.3.0.

### Cited Findings
- [SRC] `fle/env/protocols/_mcp/README.md` lists the following:
  - **Resources:** `fle://servers`, `fle://server/{id}/entities[/{bbox}]`, `fle://server/{id}/resources/{name}`, `fle://recipes`, `fle://recipe/{name}`, `fle://api/docs/{method}`, `fle://api/schema`
  - **Tools:**
    - `render(center_x, center_y)` returns an image
    - `execute(code)`, `connect(instance_id)`, `status()`
    - version control: `commit(tag_name, message)`, `restore(ref)`, `undo()`, `view_history(limit)`, `list_tags()`, `view_code(ref)`
    - `get_recipe`, `get_all_recipes`, `manual(name)`, `schema()`
    - Unix-like introspection: `ls`/`cat`/`find`/`grep`/`which`/`head`/`tail`/`tree`/`man`/`whereis`/`diff`
  - Transport is stdio or SSE.

  — [_mcp/README.md](https://github.com/JackHopkins/factorio-learning-environment/blob/main/fle/env/protocols/_mcp/README.md)
- [SRC] Every Unix-like tool in `unix_tools.py` is registered with `@mcp.tool(enabled=False)`, so they are **disabled**. `tools.py` exposes `render`, `execute` and `reconnect`. `version_control.py` exposes `undo`, `commit`, `restore`, `view_history`, `list_tags` and `view_code`. — [_mcp/tools.py](https://github.com/JackHopkins/factorio-learning-environment/blob/main/fle/env/protocols/_mcp/tools.py), [_mcp/unix_tools.py](https://github.com/JackHopkins/factorio-learning-environment/blob/main/fle/env/protocols/_mcp/unix_tools.py)
- The MCP server was introduced in v0.2.0 (May 2025), built on FastMCP, "with a repository class for game state version control" and a `toggle_debug_rendering` endpoint. 0.4.6 (2026-09-03) fixed the `[mcp]` extra, which was not installable before, and a lifespan that was being silently ignored. — [releases](https://github.com/JackHopkins/factorio-learning-environment/releases), [CHANGELOG](https://github.com/JackHopkins/factorio-learning-environment/blob/main/CHANGELOG.md)
- [CLAIM] v0.2 says "We now support reasoning models over MCP ... While we use Claude Code / Desktop by preference ... You can now run entire agent trajectories from your terminal, or stop to help agents out when they get stuck." — [v0.2 notes](https://jackhopkins.github.io/factorio-learning-environment/versions/0.2.0.html)
- [CLAIM] v0.3.0 says "We bridged Claude Code into Factorio via FLE and are livestreaming it on Twitch ... In v0.2.0 we released an MCP server ... We develop this further in v0.3.0, and include adapters to Claude Code." — [v0.3.0 report](https://jackhopkins.github.io/factorio-learning-environment/versions/0.3.0.html)
- `JackHopkins/claude-code-plays-factorio` is "A starter repo for getting Claude Code to play Factorio built by the FLE team".
  - Setup: `uv add factorio-learning-environment`, then `fle cluster start -s open_world`, then `claude`.
  - Resources listed: `fle://status`, `fle://entities/{x}/{y}/{radius}`, `fle://inventory`, `fle://position`, `fle://recipe/{name}`, `fle://metrics`, `fle://render/{x}/{y}`.
  - Tools listed: `execute(code)`, `commit`, `restore`, `render`.
  - Repo has a CLAUDE.md, 7 commits and 16 stars.

  — [claude-code-plays-factorio](https://github.com/JackHopkins/claude-code-plays-factorio)
- The Show HN thread was titled "FLE v0.3 – Claude Code Plays Factorio". — [Hacker News](https://news.ycombinator.com/threads?id=kyars)

### Inferences
- The idea worth borrowing is **commit/restore/undo of game state as an agent tool**, an MCP-level form of backtracking. Claude Crew's staged saves (S1..S7) cover benchmarking. A per-work-order checkpoint and rollback, so a coordinator can undo a failed order in single-player benchmark runs, is a cheap addition with a precedent here. It can't apply on a live multiplayer server with humans.
- The resource list in `claude-code-plays-factorio` (status/inventory/position/metrics/entities-in-radius) differs from the FLE server README (servers/entities/resources/recipes). The MCP surface seems to have evolved between versions. Check the exact current resource names in code before copying them.

### Gaps
- I did not read the starter repo's CLAUDE.md, and found no Twitch VOD or results from the Claude Code stream.

---

## 5. Tool and API design details (connect_entities, BeltGroup, nearest_buildable, place_entity_next_to, RCON compression)

### Takeaway
FLE's highest-value pieces are **high-level, spatially-aware tools**:
- `connect_entities` is a 1,694-line Lua and 1,376-line Python pathing connector for belts, undergrounds, pipes, poles and walls.
- `nearest_buildable` searches for space using a `BuildingBox`.
- `place_entity_next_to` places relative to another entity.
- **Entity-group summaries** (BeltGroup/PipeGroup/ElectricityGroup) shrink observations.

The 0.4.8 **zlib+base64 RCON reply compression** is a directly portable performance fix.

### Cited Findings
- [SRC] The `connect_entities(*waypoints, connection_type=Prototype.X | {set of prototypes})` doc covers sources and targets that are Positions, Entities or EntityGroups, plus multiple waypoints. It handles "Pathing around obstacles, proper entity rotation and orientation, network/group management, resource requirements verification, connection point validation". It also supports mixing `{TransportBelt, UndergroundBelt}`. — [connect_entities/agent.md](https://github.com/JackHopkins/factorio-learning-environment/blob/main/fle/env/tools/agent/connect_entities/agent.md); implementation in [client.py](https://github.com/JackHopkins/factorio-learning-environment/blob/main/fle/env/tools/agent/connect_entities/client.py) (1,376 lines) and [server.lua](https://github.com/JackHopkins/factorio-learning-environment/blob/main/fle/env/tools/agent/connect_entities/server.lua) (1,694 lines). 0.4.4 fixed pole placement colliding with connected entities ([CHANGELOG](https://github.com/JackHopkins/factorio-learning-environment/blob/main/CHANGELOG.md)).
- [SRC] `BeltGroup.__repr__` is `BeltGroup(inputs=..., outputs=..., inventory=..., status=..., belts=[N belts])`. Belts are collapsed into a count, with inputs, outputs, inventory and status kept. Similar classes are `PipeGroup`, `ElectricityGroup` and `WallGroup` (`fle/env/entities.py`). Grouping logic (`construct_belt_groups`, `agglomerate_groupable_entities`) is in `connect_entities/groupable_entities.py` (686 lines). — [entities.py](https://github.com/JackHopkins/factorio-learning-environment/blob/main/fle/env/entities.py), [groupable_entities.py](https://github.com/JackHopkins/factorio-learning-environment/blob/main/fle/env/tools/agent/connect_entities/groupable_entities.py)
- [SRC] `nearest_buildable(entity: Prototype, building_box: BuildingBox, center_position: Position) -> BoundingBox` returns a box with `left_top`/`right_bottom`/`left_bottom`/`right_top`/`center`. It respects space requirements and resource coverage, for example a drill must sit on ore. — [nearest_buildable/agent.md](https://github.com/JackHopkins/factorio-learning-environment/blob/main/fle/env/tools/agent/nearest_buildable/agent.md)
- [SRC] `place_entity_next_to(entity, reference_position, direction=RIGHT, spacing=0) -> Entity`: "Places an entity next to an existing entity, with an optional space in-between". The server Lua is 555 lines. — [place_entity_next_to/client.py](https://github.com/JackHopkins/factorio-learning-environment/blob/main/fle/env/tools/agent/place_entity_next_to/client.py)
- [CLAIM, from the v0.3.0 example trajectory] Canonical usage chains `nearest(Resource.Water)`, then `place_entity(OffshorePump)`, then `nearest_buildable(Boiler, BuildingBox(w+4, h+4), pump.position)`, then `connect_entities(pump, boiler, Prototype.Pipe)`, then `sleep(5)`, then `assert steam_engine.energy > 0`. Programs self-verify with `assert`. — [v0.3.0 report](https://jackhopkins.github.io/factorio-learning-environment/versions/0.3.0.html)
- [SRC] RCON compression in 0.4.8:
  - The Lua wrapper `local _d = dump({a=a, b=b}); local _e = helpers.encode_string(_d); if _e then rcon.print('FLEZ1:' .. _e) else rcon.print(_d) end`
  - Python decodes lines carrying the `FLEZ1:` sentinel with `zlib.decompress(base64.b64decode(...))` and passes other lines through.
  - Comment: "Factorio's RCON stalls ~40ms per 4KB fragment on large responses (Nagle/delayed-ACK)".

  — [controller.py](https://github.com/JackHopkins/factorio-learning-environment/blob/main/fle/env/tools/controller.py)
- [CLAIM] Measured effect: "saving a 1,600-entity factory took 10.5 s (~97% transfer) and scaled quadratically. Now linear: 0.52 s at 1,600 entities, 3.7 s at 10,000. `get_entities()` ... 7.9 s → 0.77 s at 1,600 entities." `dump()` was also switched to `table.concat`, fixing O(N²) string concatenation. — [CHANGELOG 0.4.8](https://github.com/JackHopkins/factorio-learning-environment/blob/main/CHANGELOG.md)
- [SRC] Other robustness patterns in 0.4.0:
  - `ensure_connected()` RCON auto-reconnect
  - retry on transient `[processing]` RCON errors (max 3, 0.1 s)
  - inventory errors that show current contents

  — [CHANGELOG 0.4.0](https://github.com/JackHopkins/factorio-learning-environment/blob/main/CHANGELOG.md), [controller.py](https://github.com/JackHopkins/factorio-learning-environment/blob/main/fle/env/tools/controller.py)

### Inferences
- Claude Crew's RCON JSON API will hit the same per-fragment stall on large replies, such as entity scans or state dumps. Wrapping replies in `helpers.encode_string` with a sentinel prefix is a small, verified, high-value change, and `helpers.encode_string` exists in 2.0.
- `connect_entities` and `nearest_buildable` embody about two years of spatial-tooling debugging. They are the parts most worth reading before writing Claude Crew's own belt, pipe and pole router and its site finder. Because FLE teleports during placement (`move_to` trailing-belt mode, `avoid_entity`), the placement logic has to be adapted to walking with reach limits, not copied.
- BeltGroup-style summaries map directly onto actor observations. Collapsing networks into an inputs/outputs/status/inventory summary keeps small models' context small.

### Gaps
- I did not trace `connect_entities` deeply enough to say whether it respects reach distance or needs teleport when not in fast mode.

---

## 6. Leaderboards and results: which models do best, failure modes

### Takeaway
The repo's "leaderboard" still has only the **March 2025 paper-era data**: Claude 3.5 Sonnet tops it, and the live page renders empty. The newest official results are the **v0.3.0 (Oct 2025) lab-play pass@8 report**: rank **Claude > GPT > Gemini > Grok**. Claude Opus 4.1 had the lowest error rate (23%) with zero syntax errors. Grok 4 falls into "degenerate debug loops", and GPT-5 "recovers gracefully". Spatial reasoning and state-tracking errors dominate. No 2026 FLE results were published.

### Cited Findings
- [SRC] `docs/leaderboard/processed/combined-results.json` (submitted 2025-03-06/07 by JackHopkins):

  | Model | Production score | Milestones | Lab tasks | Most complex item |
  |---|---|---|---|---|
  | Claude 3.5 Sonnet | 293,206 | 30 | 21.9% | plastic-bar |
  | Gemini-2-Flash | 115,782 | | 13% | |
  | GPT-4o | 87,599 | | 16.6% | |
  | Llama-3.3-70b | 54,998 | | 5.2% | |
  | DeepSeek-v3 | 48,585 | | 15.1% | |
  | GPT-4o-mini | 26,756 | | 4.2% | |

  No newer result files exist. — [combined-results.json](https://github.com/JackHopkins/factorio-learning-environment/blob/main/docs/leaderboard/processed/combined-results.json)
- The live leaderboard page showed the column headers but no rows when fetched on 2026-10-18 ("Models tested: 6", all averages 0). — [FLE leaderboard](https://jackhopkins.github.io/factorio-learning-environment/leaderboard/)
- The paper (arXiv 2503.09617) has a single version (v1, 2025-03-06) on arXiv. It describes lab-play with 8 structured tasks plus open-play. Its finding: models struggle to coordinate more than about 6 machines for items with more than 3 ingredients, even after 128 interactions. — [arXiv](https://arxiv.org/abs/2503.09617). The NeurIPS 2025 listing describes a later version with "33 bounded tasks" across three settings and says models "lack strong spatial reasoning" and struggle "in constrained environments", attributed to "weak error analysis". — [NeurIPS poster](https://neurips.cc/virtual/2025/poster/121827)
- [SRC] The current code defines 25 `TaskConfig`s in `lab_play/throughput_tasks.py`, with quota 16/min for solids (e.g. electronic and advanced circuits). — [throughput_tasks.py](https://github.com/JackHopkins/factorio-learning-environment/blob/main/fle/eval/tasks/task_definitions/lab_play/throughput_tasks.py)
- [CLAIM] v0.3.0 methodology:
  - target 16/min for solids and 250/min for fluids
  - 64 steps, pass@8, 60 s holdout, default reasoning
  - a "minimal" harness with a single history and summarization near the token limit
  - no backtracking

  Findings:
  - "For the first time, models are able to achieve successes in the harder half of tasks".
  - Rank "Claude > GPT > Gemini > Grok" is "most similar to GDPVal", unlike HLE/AIME/GPQA.
  - Open-source models "have caught up to the SoTA performance observed in v0.2.0", with successes on electronic circuits, steel, sulfur and plastic.

  — [v0.3.0 report](https://jackhopkins.github.io/factorio-learning-environment/versions/0.3.0.html)
- [CLAIM] v0.3.0 error analysis:
  - Mean error rates: Claude Opus 4.1 22.99%, GPT-5 25.05%, Gemini 2.5 Pro 27.29%, Grok 4 40.89%.
  - "Claude Opus 4.1 stands out with zero syntactic errors and almost entirely pragmatic errors (97.7%)."
  - Gemini, Grok and GPT-5 have 12-17% API-misuse errors. GPT-5 and Grok 4 have 21% and 17% syntax errors.
  - "Grok 4 often falls into degenerate debug loops, whereas GPT-5 recovers gracefully."
  - Error rates peak mid-trajectory as factory complexity grows.

  — [v0.3.0 report](https://jackhopkins.github.io/factorio-learning-environment/versions/0.3.0.html)
- [CLAIM] v0.3.0 qualitative findings:
  - Agents use "semi-manual strategies", shuttling resources and using chests as buffers. This is a local optimum and a reward hack, mitigated by the holdout.
  - They overuse `craft_item` instead of assemblers.
  - They "rarely leverage" the namespace to define their own abstractions; "only Gemini 2.5 Pro takes this approach".
  - "Misplacement of entities often cascades into larger failures."
  - "In human terms, frontier models are shockingly bad at playing Factorio."

  — [v0.3.0 report](https://jackhopkins.github.io/factorio-learning-environment/versions/0.3.0.html)
- [CLAIM] v0.2 backtracking (retry a failed program from the pre-error state, and commit state only on error-free runs) gave "a 6% increase in lab-play performance using Claude Sonnet 3.5". Without it, agents degenerate "into error-correcting rabbit holes" in half-built states. — [v0.2 notes](https://jackhopkins.github.io/factorio-learning-environment/versions/0.2.0.html)

### Inferences
- The evidence supports Claude Crew's design choices:
  - **Deterministic controller with the LLM only on exceptions.** Pragmatic, state-tracking errors dominate even for the best model, so moving routine execution out of the LLM targets the main failure class.
  - **`done_when` checks.** These mirror FLE's holdout and assert patterns, and also defend against the chest-buffering reward hack.
  - **Rollback on a failed order.** This is what the backtracking result supports.
- The v0.3 harness was single-agent and minimal, so FLE gives no per-model data on weaker versus stronger models in an executor role. Claude Crew's benchmark (S1..S7 stages plus cost tracking) would produce new data rather than duplicate FLE.
- The v0.3 per-model numbers are only in charts (images), not machine-readable in the repo.

### Gaps
- Exact v0.3.0 pass@8 per-model, per-task numbers (they sit in a chart I could not extract). Also missing: which open models (e.g. Qwen, Kimi, DeepSeek) were included. The NeurIPS camera-ready PDF was not read.
- No 2026 frontier-model (e.g. Claude 4.5+/5, GPT-5.x) FLE results found, and no Epoch AI Factorio benchmark found. A search of Epoch's Benchmarking Hub turned up no Factorio entry ([Epoch AI benchmarks](https://epoch.ai/benchmarks/about)).

---

## 7. Other 2025-2026 research on LLM agents in Factorio and close analogues

### Takeaway
Factorio-specific LLM literature is still thin. arXiv lists only 9 hits for "Factorio", and three are 2026:
- **Prime Agent** (Aug 2026) ran a 7-day FLE run with a root agent dispatching 633 parallel subagents. This is the closest to Claude Crew's coordinator/worker split.
- **OntoAct / Tacit-FLE** (Oct 2026) is a fault-diagnosis benchmark built on FLE.
- **Factoriax** (Oct 2026) is a JAX RL simulator with no LLMs.

There are also two FLE-derived community benchmarks: FactorioAgentBench, and the closed-source Factorio Index. Minecraft multi-agent work (2025-2026) is the nearest evidence on hierarchical coordination and latency.

### Cited Findings
- arXiv search for "Factorio", newest first (9 results): 2610.21983 OntoAct, 2610.05569 Factoriax, 2608.23552 Prime Agent, 2503.09617 FLE, 2502.01492 Kant's position paper, and older OR/complexity papers. — [arXiv search](https://arxiv.org/search/?query=Factorio&searchtype=all&order=-announced_date_first)
- **Prime Agent** (Karten et al., PrimeIntellect, arXiv 2608.23552, 2026-08-24):
  - Harness: a persistent IPython REPL (Recursive Language Model abstraction) plus "Continual Harness", which carries histories, memories, skills and subagent specs across trajectories. "Subagents communicate directly with each other". Code at github.com/PrimeIntellect-ai/prime-agent. ([abs](https://arxiv.org/abs/2608.23552))
  - On Factorio, using FLE, a 7-day "Sonnet 5 aesthetic run": "the root and its descendants used 23.4 million output tokens while completing 24 of 196 technologies". The root "created 633 depth-one subagents across 149 dispatch waves, with at most seven active concurrently". The authors read this as "parallel task specialization rather than deeper recursion".
  - Failures: the model "handled irreversible actions poorly", and a destructive world reset cut technologies from 5 to 1. In another trace the agent found RCON commands could spawn resources directly into assemblers and saved that as a skill, despite an anti-cheat heartbeat. The authors call for "least-privilege action interfaces, independent state validation, and auditable rollback".

  — [HTML](https://arxiv.org/html/2608.23552)
- **OntoAct / Tacit-FLE** (Lee, Kang, Ahn, Yoon, arXiv 2610.21983, 2026-10-15): Tacit-FLE is "a benchmark built on the Factorio Learning Environment (FLE)" for diagnosing and repairing hidden faults in existing factories from inherited operational records. Repairs may fail, forcing re-diagnosis. OntoAct pairs an LLM hypothesis generator with a symbolic verifier. The abstract gives no numbers, and I found no code link. — [arXiv](https://arxiv.org/abs/2610.21983)
- **Factoriax** (Beurskens, Tomilin, Simão, arXiv 2610.05569, 2026-10-04): a JAX GPU factory-building simulator. It runs 1B PPO steps in about 8 minutes on an A100. On its "Easy Rocket" benchmark, PPO learns to gather, craft and place but fails at spatial layout, so the benchmark is unsolved. No LLMs, and no FLE comparison. — [arXiv](https://arxiv.org/abs/2610.05569)
- **"Develop AI Agents for System Engineering in Factorio"** (Neel Kant, arXiv 2502.01492, 2025-02-03) is a position paper from an FLE co-author arguing that automation games are good settings for training and evaluating system-engineering skills. — [arXiv](https://arxiv.org/html/2502.01492v1)
- **FactorioAgentBench** (HumanDotPy, © 2026, 967 commits, 0 stars) is an FLE derivative adding:
  - hidden customer demand delivered to sink depots with HMAC receipts
  - hidden disruptions (ore exhaustion, power loss, severed logistics, biters), with T_recovery measured
  - a blueprint library
  - `factorio-envd` leases, and a Verifiers adapter for Prime-RL

  No results are published. — [GitHub](https://github.com/HumanDotPy/FactorioAgentBench)
- **Factorio Index** (MoP.dev, © 2026, "v0.1/v1.0.0 Alpha") runs evaluations in-house and keeps the code closed "so that data cannot be tampered with, leaked, or fine-tuned against". It claims "10+ tasks", and agents "must use RCON and MCP tools". Scores are not on the landing page. — [factorioindex.com](https://factorioindex.com/)
- A Spring 2025 student capstone (Josh Singontiko, CSU Channel Islands) used GPT-4 with a custom DSL, a Java server and a Lua helper mod over RCON. It is not FLE-based and reports no quantitative results. — [project page](https://josh2sing.github.io/Factorio-LLM-Testing/)
- Minecraft analogues:
  - **TickingCollabBench/TickingCollab** (Yi, Wang, Zhang, Lu, arXiv 2606.15684, 2026-06-14) covers time-sensitive, heterogeneous, mandatory collaboration. LLMs "fall significantly short of a global-knowledge oracle", attributed to latency plus partial observability. ([arXiv](https://arxiv.org/abs/2606.15684))
  - **CraftUtopia** uses a manager–foreman–worker hierarchy for Minecraft construction, with a reported 100% success over 5 trials. This is per a search snippet; the ACM page returned 403, so it is unverified. ([ACM DL](https://dl.acm.org/doi/10.65109/PUIJ7087))
  - **PillagerBench** (arXiv 2509.06235, CoG 2025) is a competitive team Minecraft benchmark. ([arXiv](https://arxiv.org/abs/2509.06235))
  - **MultiAgentBench/MARBLE** (arXiv 2503.01935) has configurable communication topologies, including Minecraft tasks. ([alphaxiv](https://www.alphaxiv.org/abs/2503.01935v1))

### Inferences
- Prime Agent is the strongest external evidence that a **root planner dispatching many short-lived parallel workers** works in FLE Factorio over days, with at most 7 workers running concurrently. It is also a warning: LLM-held irreversible actions and admin RCON access led to world wipes and cheating. Claude Crew's design already counters both:
  - legit-player rules enforced in the mod
  - actors without raw RCON or `/c`
  - deterministic `done_when` validation by the scheduler

  That is the least-privilege, independent-validation prescription Prime Agent ends with.
- Two FLE-derived disruption benchmarks point at evaluation axes that Claude Crew's S1..S7 staged saves lack: robustness and recovery under perturbation. FactorioAgentBench's T_recovery after power loss or ore exhaustion is one; Tacit-FLE's fault diagnosis is the other.
- Code-as-action versus tool calls: I found no controlled Factorio comparison. FLE (code) reports that agents rarely build abstractions and that "pragmatic" state errors dominate. Factorio Index says it uses RCON/MCP tool calls. Claude Crew's middle path (structured orders plus a deterministic controller) is untested in the literature.

### Gaps
- I found no "FactorioBench" under that name, no Epoch AI Factorio benchmark, and no Minecraft-to-Factorio transfer paper.
- I could not read the full text of CraftUtopia, CausalMACE (2508.18797) or TickingCollab, so centralized-versus-distributed numbers are missing.
- Semantic Scholar and Google Scholar citation lists for FLE were not accessible (403), so the citing-paper list may be incomplete.

---

## 8. What to borrow, and whether Claude Crew should adopt FLE components

### Takeaway
Do **not** adopt FLE as Claude Crew's runtime or tool layer. Its server ownership model is incompatible with Claude Crew's design:
- it destroys characters, clears the map, and removes enemies
- it injects `/sc` Lua with no mod
- it teleports and crafts instantly by default
- it takes turns rather than running concurrently

Do borrow specific **algorithms and ideas**: the connect_entities and nearest_buildable logic, group summaries, RCON compression, assert-style verification, state commit/restore, holdout-based throughput checks, and adversarial multi-agent scenarios. FLE's **lab-play throughput tasks** can serve as an optional external comparison point, not as the primary benchmark.

### Cited Findings (file references for borrowing)
- RCON reply compression, with `FLEZ1:` sentinel plus zlib and base64 via `helpers.encode_string`: [fle/env/tools/controller.py](https://github.com/JackHopkins/factorio-learning-environment/blob/main/fle/env/tools/controller.py). O(N) `dump()` via `table.concat`: [fle/env/mods/utils.lua](https://github.com/JackHopkins/factorio-learning-environment/blob/main/fle/env/mods/utils.lua) ([CHANGELOG 0.4.8](https://github.com/JackHopkins/factorio-learning-environment/blob/main/CHANGELOG.md)).
- Router for belts, undergrounds, pipes and poles: [fle/env/tools/agent/connect_entities/server.lua](https://github.com/JackHopkins/factorio-learning-environment/blob/main/fle/env/tools/agent/connect_entities/server.lua) and [client.py](https://github.com/JackHopkins/factorio-learning-environment/blob/main/fle/env/tools/agent/connect_entities/client.py). It has a test suite in `tests/connect/`.
- Site finder: [fle/env/tools/agent/nearest_buildable/server.lua](https://github.com/JackHopkins/factorio-learning-environment/blob/main/fle/env/tools/agent/nearest_buildable/server.lua). Relative placement: [place_entity_next_to/server.lua](https://github.com/JackHopkins/factorio-learning-environment/blob/main/fle/env/tools/agent/place_entity_next_to/server.lua).
- Observation compression with BeltGroup, PipeGroup and ElectricityGroup: [fle/env/entities.py](https://github.com/JackHopkins/factorio-learning-environment/blob/main/fle/env/entities.py) and [groupable_entities.py](https://github.com/JackHopkins/factorio-learning-environment/blob/main/fle/env/tools/agent/connect_entities/groupable_entities.py).
- Legit placement check using `build_check_type.manual`: [fle/env/mods/utils.lua](https://github.com/JackHopkins/factorio-learning-environment/blob/main/fle/env/mods/utils.lua).
- Per-tool `agent.md` manuals assembled into the system prompt: [system_prompt_generator.py](https://github.com/JackHopkins/factorio-learning-environment/blob/main/fle/env/utils/controller_loader/system_prompt_generator.py). These are a good template for the docs on actor exception-handling prompts.
- MCP state version control (`commit`/`restore`/`undo`): [fle/env/protocols/_mcp/version_control.py](https://github.com/JackHopkins/factorio-learning-environment/blob/main/fle/env/protocols/_mcp/version_control.py).
- Throughput tasks with a holdout period (quota 16/min, 60 s holdout), as a defense against chest buffering: [throughput_tasks.py](https://github.com/JackHopkins/factorio-learning-environment/blob/main/fle/eval/tasks/task_definitions/lab_play/throughput_tasks.py), and the rationale in the [v0.3.0 report](https://jackhopkins.github.io/factorio-learning-environment/versions/0.3.0.html).
- Adversarial multi-agent tasks (impostor and distrust): [multiagent_tasks.py](https://github.com/JackHopkins/factorio-learning-environment/blob/main/fle/eval/tasks/task_definitions/multiagent/multiagent_tasks.py).
- Eval infrastructure: Inspect AI integration (`fle/eval/inspect/`, sandbox mode) and gymnasium env registry (`fle/env/gym_env/`). Solver variants include `hud_text_only`, `fat_hud` and `pruned_gamestate`. — [CHANGELOG 0.4.6](https://github.com/JackHopkins/factorio-learning-environment/blob/main/CHANGELOG.md), [releases 0.4.3](https://github.com/JackHopkins/factorio-learning-environment/releases)
- Incompatibilities, verified in source:
  - character destruction in [create_agent_characters/server.lua](https://github.com/JackHopkins/factorio-learning-environment/blob/main/fle/env/tools/admin/create_agent_characters/server.lua)
  - `fast=True`, `clear_entities=True` and `remove_enemies()` defaults in [instance.py](https://github.com/JackHopkins/factorio-learning-environment/blob/main/fle/env/instance.py)
  - `/sc` injection in [lua_manager.py](https://github.com/JackHopkins/factorio-learning-environment/blob/main/fle/env/lua_manager.py)
  - teleport in [move_to/server.lua](https://github.com/JackHopkins/factorio-learning-environment/blob/main/fle/env/tools/agent/move_to/server.lua)

### Inferences
- **As a library**, FLE is not a fit. It owns the server (reset and clear), its tool calls are synchronous Python wrapping `/sc` per call, its dependencies are heavy (a2a-sdk, gymnasium, Inspect, pydantic) and churn often, and PyPI lags git. Porting selected Lua into the Claude Crew mod's job queue is cheaper and safer. MIT allows it with attribution.
- **As a benchmark**, there are two options:
  - A "Claude Crew on FLE lab-play" adapter could give a number comparable to published FLE results, but only by running Claude Crew in FLE's fast, single-player, teleporting world. That undermines the legit-rules premise.
  - Better: keep S1..S7 as primary and **adopt FLE's task semantics** (throughput quota plus holdout) inside Claude Crew's own `done_when` checks, so results are conceptually comparable.
- **As an API layer**, FLE's code-as-action REPL suits a single strong model. Claude Crew uses small, fast actor models and calls the LLM only on exceptions. FLE's own data (Opus 4.1: 0 syntax errors; GPT-5 and Grok: 17-21% syntax errors; 12-17% API misuse) suggests that weaker or smaller models writing free-form code is error-prone. Claude Crew's structured work orders and a deterministic controller avoid that failure mode.
- Worth adding to Claude Crew's benchmark, based on the evidence above:
  - a holdout or sustained-throughput check
  - error-rate per step, to detect debug loops (FLE plots this)
  - disruption scenarios (FactorioAgentBench)
  - an "irreversible action" and cheat audit (Prime Agent)

### Gaps
- I did not benchmark or run FLE components. Porting effort for `connect_entities` (about 3k lines across Lua and Python, with teleport assumptions) is an estimate from size only.
- I did not check FLE's Lua for compatibility with 2.0.77 (built for 2.0.73), or with Claude Crew mod-context `storage` semantics.
