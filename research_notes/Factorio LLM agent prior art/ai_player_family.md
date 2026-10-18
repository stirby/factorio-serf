# The "AI Player" family of Factorio LLM-agent mods (ob_105 AI Player → AI Player v3 → ChatGPT fork / AI Coworker / pi-factorio), compared against Claude Crew

Research date 2026-10-18. Method: shallow-cloned current upstream repos and read the source. Local tarballs from 2026-10-17 at `scratchpad/src/` are byte-identical to upstream `mod/` for ai-player-v3 (0.4.2) and factorio-ai-coworker (0.2.0), so nothing changed overnight. Commits read: ai-player-v3 `2806aed` (master), ai-player-chatgpt `64cacbc` (branch `chatgpt-subscription`), factorio-ai-coworker `62b60b4` (main), and pi-factorio `ba814e8` (the ai-player-v3 author's newer harness, included because the author points to it as the project's direction). ob_105's original "AI Player" has **no public source**: the mod portal lists no source_url, and downloads need a Factorio login, which I did not use. Everything about ob_105 below comes from the portal description and discussion threads, not from code.

Abbreviations used in citations:
- A = `https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b`
- C = `https://github.com/ethanrcohen/ai-player-chatgpt/blob/64cacbc5a5229c8273c4a68e9cbbee3bab7b57e1`
- W = `https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9`
- P = `https://github.com/thedemon117/pi-factorio/blob/ba814e8072104ffb213a428df79c6a7e4fd2f02b`

(The links below spell these prefixes out in full.)

---

## Q1. Version, dates, license, Factorio version, Space Age, popularity, commit activity, maintainer responsiveness

### Takeaway
All four are small hobby projects for Factorio 2.0 with no Space Age-specific support, and each has hardcoded `nauvis` paths. The most-used is ob_105's abandoned original (about 1.45K downloads, last release 2026-01-11). AI Player v3 has 261 downloads and has been quiet since 2026-08-29, which is stale. The two October 2026 offshoots (the ChatGPT fork and AI Coworker) are days old with 0–1 stars and very few users.

### Cited Findings
**ob_105 "AI Player" (`ai-player`)**
- Releases 0.1.0 (2026-01-10), 0.1.1 (2026-01-11), and 0.1.2 (2026-01-11), all `factorio_version 2.0` with dependency `base >= 2.0`. MIT license. 1446 downloads. No source_url. **Over 9 months old, so stale.** [Mod portal API](https://mods.factorio.com/api/mods/ai-player/full)
- The author abandoned it: "Warning I will not continue working on this mod… It is still functional but it's not great. Multiplayer does not work and I never have plans to make it work." [Mod page](https://mods.factorio.com/mod/ai-player)
- About 23 discussion threads, mostly setup failures: the wrong pip package (`factorio-rcon` should be `factorio-rcon-py`), RCON not enabled, Windows-only paths, and a UTF-8 decode error in the bridge. [Discussion list](https://mods.factorio.com/mod/ai-player/discussion); [Bridge script bug](https://mods.factorio.com/mod/ai-player/discussion/69814e405cabac6fad40d05b); [Hardcoded for Windows](https://mods.factorio.com/mod/ai-player/discussion/697c7546442f1ca6e3d17499); [Error in the Bridge](https://mods.factorio.com/mod/ai-player/discussion/697fa2420978b22f36d86356)
- The maintainer did answer some threads within days back in 2026-01, but answers like "That is strange and I do not know how to fix that" show limited capacity. [ERROR thread](https://mods.factorio.com/mod/ai-player/discussion/696a092b30a2a975a9a66cfc)

**AI Player v3 (`ai-player-v3`, by Demon117_ / GitHub thedemon117)**
- Portal releases: 0.3.2 and 0.3.3 (2026-06-28), 0.3.4 (2026-07-11), 0.3.5 (2026-07-12), and 0.4.2 (2026-08-29). Factorio 2.0, `base >= 2.0` only. Portal license MIT. 261 downloads. [Mod portal API](https://mods.factorio.com/api/mods/ai-player-v3/full)
- GitHub: created 2026-06-28, last push 2026-08-29, 9 stars, 6 forks, 2 open issues, and **no LICENSE file** (the API reports `license: null`, which conflicts with the portal's MIT). 22 commits, all between 2026-06-28 and 2026-08-29. **Last activity is about 7 weeks old, so borderline stale.** [GitHub API](https://api.github.com/repos/thedemon117/ai-player-v3)
- The README says it builds on ob_105's ai-player and lvshrd's factorio-agent, and that it was built "using claude." [Mod page](https://mods.factorio.com/mod/ai-player-v3)
- Responsiveness: two detailed bug reports filed 2026-09-13 (#1 and #2) got a reply only on 2026-10-15 ("apologies for the extremely late response. Will take a look"), with no fix committed. [Issue #1](https://github.com/thedemon117/ai-player-v3/issues/1); [Issue #2](https://github.com/thedemon117/ai-player-v3/issues/2)
- About a month ago the author wrote: "This has set me back a bit, so I haven't built anything further with pi or the mod itself." [Pi Coding Harness thread](https://mods.factorio.com/mod/ai-player-v3/discussion/6a6a1fdabf84e2fe914c9209)
- Forks: ethanrcohen/ai-player-chatgpt (active in October), plus pwmcintyre, lex, StevenLi-phoenix, aaronsrhodes2, and skyline624, all 0 stars with no activity after the fork date. [Forks API](https://api.github.com/repos/thedemon117/ai-player-v3/forks)

**AI Player ChatGPT Edition (ethanrcohen/ai-player-chatgpt)**
- A GitHub fork only; it is not on the mod portal. It **reuses the mod name `ai-player-v3`** and bumps `info.json` to 0.5.2, titled "AI Player — ChatGPT Edition". The README warns: "do not enable this edition and the original as separate mods." [info.json](https://github.com/ethanrcohen/ai-player-chatgpt/blob/64cacbc5a5229c8273c4a68e9cbbee3bab7b57e1/mod/info.json); [README](https://github.com/ethanrcohen/ai-player-chatgpt/blob/64cacbc5a5229c8273c4a68e9cbbee3bab7b57e1/README.md)
- 8 commits on top of upstream, 2026-10-07 to 2026-10-14. Changelog: 0.5.0 (2026-10-07) ChatGPT subscription sign-in; 0.5.1 (2026-10-11) `/ai-goal`; 0.5.2 (2026-10-14) `scan_area` plus an investigation loop. 0 stars, 0 issues, no license file. [changelog](https://github.com/ethanrcohen/ai-player-chatgpt/blob/64cacbc5a5229c8273c4a68e9cbbee3bab7b57e1/mod/changelog.txt); [GitHub API](https://api.github.com/repos/ethanrcohen/ai-player-chatgpt)
- The fork's own iteration log says its last live check failed: "Model investigation and a separate minimal sign-in test both failed with HTTP 520. No model construction commands were submitted." [investigation-iteration.md](https://github.com/ethanrcohen/ai-player-chatgpt/blob/64cacbc5a5229c8273c4a68e9cbbee3bab7b57e1/docs/investigation-iteration.md)

**Factorio AI Coworker (`ai-coworker`, portal owner joshuasui, GitHub Suixinlei)**
- Portal: 0.1.0 and 0.2.0, both released 2026-10-08. Factorio 2.0, `base >= 2.0`. MIT. 27 downloads. [Mod portal API](https://mods.factorio.com/api/mods/ai-coworker/full)
- GitHub: created 2026-10-05, last push 2026-10-08, 1 star, 0 forks, 0 issues, MIT LICENSE present. The public history is 8 commits, all on 2026-10-08. [GitHub API](https://api.github.com/repos/Suixinlei/factorio-ai-coworker)
- Internal audits mention mod versions 0.5.0, 0.7.0, and 0.8.4 before the public restart at 0.1.0, so a long private history was squashed. [mining-outpost audit](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/audits/2026-10-08-mining-outpost-e2e.md); [dynamic-role audit](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/audits/2026-10-04-dynamic-role-e2e.md)
- Most docs (SKILL.md, AGENTS.md, opencode agent prompts, most audits) are in Chinese. The README credits ai-player-v3 as inspiration, but its link points to `Suixinlei/factorio-ai-player-workspace`, which now redirects (likely a renamed repo). [README](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/README.md)
- Its audits were run on **Factorio 2.0.77**, the same version as Claude Crew, and one local test server had **space-age** loaded. [mining-outpost audit](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/audits/2026-10-08-mining-outpost-e2e.md)
- Issue reporters ran ai-player-v3 on **Factorio 2.0.77**. [Issue #1](https://github.com/thedemon117/ai-player-v3/issues/1)

**Space Age (all projects)**
- ai-player-v3 and Coworker both hardcode `local SURFACE_NAME = "nauvis"` for spawning and registry reconcile. ai-player-v3's control.lua also hardcodes `game.surfaces["nauvis"]` for blueprint import/export, character reconcile, and `/remove-ai-player`. [A character.lua L6, L77](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/scripts/character.lua#L6); [A control.lua L114, L181, L249](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/control.lua#L114); [W character.lua L6](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/mod/scripts/character.lua#L6)
- ob_105 crash report: "Unknown item name: spores … ai_perception.lua:285: in function 'get_craftable_items'" (0.1.2). [Item: Spore error](https://mods.factorio.com/mod/ai-player/discussion/6976b90294b63fda4500faee)
- A user notes that ob_105's mod "will lag, freeze, or cause RCON exceptions on overhaul mods (Krastorio 2, Warptorio) due to hidden system entities… and multi-surface maps." [Complit thread](https://mods.factorio.com/mod/ai-player/discussion/6a7a8f4605a4cf437b325fe0)

### Inferences
- None of these is a mature dependency. They are useful as idea and code quarries, not as something to install tonight next to Claude Crew.
- None of them would help on a Space Age platform. Characters always spawn on nauvis and nothing models platform hubs or other surfaces. The "spores" crash looks like a Space Age-content crash, but that is unconfirmed.
- Coworker is the most engineering-heavy: it has audits and was tested on 2.0.77 with space-age loaded. It is also the least battle-tested by outside users (27 downloads, no issues).

### Gaps
- Exact ob_105 code: there is no public repo, and the portal zip needs authentication.
- Coworker's private pre-0.1.0 history and real-world usage are not visible.
- No independent reviews or benchmarks of any of these mods were found.

---

## Q2. Architecture: how the LLM is in the loop, transport, models and providers

### Takeaway
The family has evolved from a per-tick LLM router to an external coding agent driving tools. ob_105 and ai-player-v3 run a mod-initiated request cycle (script-output JSON file, Python bridge, LLM, RCON command back) where the model picks 1–3 skills or primitives per call. AI Player v3 also exposes the same skills to Claude Code and other agents through an MCP server, and pi-factorio does the same through a pi extension. The ChatGPT fork adds a bounded read-only query loop before acting. Coworker drops the in-mod LLM loop entirely: an external agent (OpenCode with GLM models) calls a one-shot CLI over RCON.

### Cited Findings
**ob_105**
- Uses LM Studio (default model Qwen3-VL-4B on port 1234) or OpenAI. A Python `lm_studio_bridge.py` watches `script-output/ai-player` and talks to Factorio over RCON. RCON only works when the game is hosted as multiplayer. [Mod page](https://mods.factorio.com/mod/ai-player); [Not working on linux](https://mods.factorio.com/mod/ai-player/discussion/69668a32021bf9a52aea9332); [Rcon dont work](https://mods.factorio.com/mod/ai-player/discussion/6aab3e77dcdb72877e1f7e75)
- A user's log shows the protocol: the model returns `[{"action":"craft",...},{"action":"place",...}]`, and the bridge sends `/ai-response 60|[...]` via RCON. One request took about 2 minutes ("Sending to LM Studio at 19:09:56" … "raw response" at 19:11:57) with about 3058 prompt tokens. [Error in the Bridge](https://mods.factorio.com/mod/ai-player/discussion/697fa2420978b22f36d86356)

**ai-player-v3, autonomous mode**
- Each decision tick (default 300 ticks, about 5 s), the mod gathers perception and writes `ai-player/request_<id>.json` with `helpers.write_file`. Only one request can be pending at a time. The bridge polls the directory, builds the prompt, calls the LLM, and returns via the `/ai-response <req_id>|<json>` console command. The mod parses the JSON with a hand-rolled regex parser and executes it synchronously. [A brain.lua](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/scripts/brain.lua); [A control.lua L417-464, L776-788](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/control.lua#L417-L464); [A watcher.py](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/bridge/factorio/watcher.py)
- The LLM is a router. The system prompt says "You operate by choosing SKILLS… Respond with a JSON ARRAY… Keep it to 1–3 entries per turn." [A prompt.py](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/bridge/prompt.py)
- Providers: `lmstudio` (also Ollama, vLLM, llama.cpp), `openai`, `custom` (any OpenAI-compatible endpoint), and `anthropic`. [A providers/__init__.py](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/bridge/providers/__init__.py)
- Recommended models: the portal suggests local qwen/qwen3-coder-next, and Sonnet (maybe Haiku) for Claude Code; the README suggests qwen2.5-7b or mistral-7b locally, and Claude Sonnet or GPT-4o in the cloud. [Mod page](https://mods.factorio.com/mod/ai-player-v3); [A README](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/README.md)
- The mod writes provider name, model, API key, and RCON password into `script-output/ai-player/config.json` from mod settings, as plaintext. [A brain.lua write_bridge_config](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/scripts/brain.lua)

**ai-player-v3, external-agent mode (0.4.x)**
- A `remote.add_interface("ai_player", …)` exposes `run_skill`, `run_primitive`, `query`, `get_state`, `set_autonomy`, `set_coop`, `get_chat`, `import_blueprint`, and `export_blueprint`. These are called as `/sc rcon.print(game.table_to_json(remote.call(...)))`. `set_autonomy(false)` stops the built-in router so it doesn't compete. [A control.lua L23-214](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/control.lua#L23-L214)
- The FastMCP stdio server (`bridge/factorio/mcp_server.py`) wraps these and adds `run_lua` (arbitrary Lua), all behind one RCON lock. [A mcp_server.py](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/bridge/factorio/mcp_server.py)
- pi-factorio is a TypeScript extension for the "pi" coding agent with about 38 tools over RCON. It adds a persistent JSON "ledger" that survives context compaction, and a SKILL.md with a "Deliberation budget: at most 3 instances of 'Actually,' / 'Wait'". [P SKILL.md](https://github.com/thedemon117/pi-factorio/blob/ba814e8072104ffb213a428df79c6a7e4fd2f02b/skills/factorio-play/SKILL.md); [P ledger.ts](https://github.com/thedemon117/pi-factorio/blob/ba814e8072104ffb213a428df79c6a7e4fd2f02b/src/ledger.ts)
- The author says GLM 5.2 "actually played the game" under pi, but Nemotron-nano could not. [Pi Coding Harness thread](https://mods.factorio.com/mod/ai-player-v3/discussion/6a6a1fdabf84e2fe914c9209)

**ChatGPT fork**
- Adds a `chatgpt` provider that uses "Sign in with ChatGPT" OAuth (`auth.openai.com`, scopes including `chatgpt.tokens.use.direct`) and the streamed Responses endpoint with `store=false`. [C chatgpt_auth.py](https://github.com/ethanrcohen/ai-player-chatgpt/blob/64cacbc5a5229c8273c4a68e9cbbee3bab7b57e1/bridge/chatgpt_auth.py); [C README](https://github.com/ethanrcohen/ai-player-chatgpt/blob/64cacbc5a5229c8273c4a68e9cbbee3bab7b57e1/README.md)
- `investigate()` lets the model return `{"queries":[…]}` instead of actions. Limits: at most 4 query rounds of 3 queries each, a typed allowlist (`scan_area`, `get_recipe`, `inspect_entity`, `nearest_buildable`, `can_place`, `get_resource_patch`, `get_character_state`), results over 16000 chars replaced by an error, and one shared deadline. [C investigation.py](https://github.com/ethanrcohen/ai-player-chatgpt/blob/64cacbc5a5229c8273c4a68e9cbbee3bab7b57e1/bridge/investigation.py)
- It defaults to observation-only (`AI_OBSERVATION_ONLY=1`), which allows only chat, summary, and wait. [C investigation-iteration.md](https://github.com/ethanrcohen/ai-player-chatgpt/blob/64cacbc5a5229c8273c4a68e9cbbee3bab7b57e1/docs/investigation-iteration.md)

**Coworker**
- An external agent runs `python -m cli --agent-id ID step '[{"action":…}]'` as a one-shot process over RCON. The in-mod autonomous bridge is disabled: `set_autonomy(true)` returns "autonomous file bridge disabled in this MCP fork". [W control.lua](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/mod/control.lua); [W SKILL.md](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/skills/factorio-ai-coworker/SKILL.md)
- AGENTS.md says game operations go through the CLI, not the MCP facade. The OpenCode agent configs use `glm-fengyue/glm-5.3` for the coordinator and `glm-5.3-flash` for the executor. [W AGENTS.md](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/AGENTS.md); [W .opencode/agents](https://github.com/Suixinlei/factorio-ai-coworker/tree/62b60b47472b83090249a37e240e7014a3e178a9/.opencode/agents)
- Earlier audits tested Claude Code, Codex, and OpenCode MCP clients against multiple roles. [W dynamic-role audit](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/audits/2026-10-04-dynamic-role-e2e.md)
- One audit has "GPT-6 SOL" driving the CLI. [W gpt6-sol audit](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/audits/2026-10-08-gpt6-sol-production-e2e.md)

### Inferences
- The file-plus-RCON transport is fragile. It needs the script-output path to be readable, has request-file timeouts, and uses a regex JSON parser in Lua. Claude Crew's pure RCON JSON API is cleaner. The one useful idea is that the timeout pushed into the mod derives from the bridge's LLM timeout (`set_request_timeout`), which avoids "Unknown request id" errors.
- None of these has Claude Crew's split between a coordinator, a deterministic scheduler, and an actor that calls the model only on exceptions. The closest is Coworker's human-written "coordinator / work-unit executor" OpenCode prompts, which have no automatic dispatch: "不设置自动派工" means "no automatic work assignment".

### Gaps
- No token or cost numbers were published for any of them. ai-player-v3 has `metrics.jsonl` and a `bridge.report` tool, but no published results.

---

## Q3. Characters: real script `character` entities? multiple agents? coexistence with human players in multiplayer?

### Takeaway
All of them use real `character` entities created with `surface.create_entity{name="character"}` and no LuaPlayer. ai-player-v3 supports exactly one AI and deletes extras. Coworker supports up to 8 (configurable to 64) named roles, using a clever context-swap shim. Multiplayer: ob_105 desyncs and is abandoned. ai-player-v3 claims co-op via `/ai-coop` but has known body-blocking bugs. Coworker was run on a dedicated server with RCON. None of them warns about the multiplayer hazards that matter to Claude Crew.

### Cited Findings
- ai-player-v3 spawns with `surface.create_entity{name="character", position=pos, force=force}` 20 tiles from the lowest-index connected player and gives a generous starter kit (100 coal, 50 iron plate, 4 burner drills, 4 furnaces, 2 assemblers, a full steam-power set, a lab, and more). [A character.lua L8-26, L71-102](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/scripts/character.lua#L71-L102)
- Co-op/solo switch: the default `force_name="player"` (co-op) shares the human force. Solo uses `ai_player_force`, set friendly and cease-fire. [A character.lua L28-69](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/scripts/character.lua#L28-L69); [A control.lua init_storage](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/control.lua#L220-L240)
- Exactly one AI: `reconcile_character()` identifies AI characters as those with `c.player == nil and c.associated_player == nil` and destroys duplicates ("[AI] Removing duplicate character"). [A control.lua L246-293](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/control.lua#L246-L293)
- **Hazard for Claude Crew:** if ai-player-v3 were installed in the same game, this reconcile would destroy every playerless character on the force. That would include Claude Crew's characters, after a mod update or config change.
- ai-player-v3 has a co-op safety guard: `/ai-collect` is refused in co-op because "it would mine the shared base". [A control.lua L646-681](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/control.lua#L646-L681)
- Character stacking fix (0.3.5): "Characters don't collide with each other, so find_non_colliding_position happily returns the target's exact position — landing a teleport there stacks the two characters and can trap the human". Fixed with `position_beside()`. [A control.lua L583-599](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/control.lua#L583-L599); [portal changelog 0.3.5](https://mods.factorio.com/mod/ai-player-v3)
- Issue #1 (2026-09-13, Factorio 2.0.77 headless): `build_miner` fails because "The blocker is the **AI character itself** (plus the human player standing nearby)". [Issue #1](https://github.com/thedemon117/ai-player-v3/issues/1)
- The FAQ claims "Does it work in multiplayer / co-op? Yes. Toggle co-op with `/ai-coop on`". There are no desync warnings. [A FAQ.md](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/FAQ.md)
- ob_105: "Yes it desyncs if you try to play multiplayer… I'm still trying to figure out why". The fix was never shipped, and the author later stated there are no plans for multiplayer. [Multiplayer server on Linux](https://mods.factorio.com/mod/ai-player/discussion/696436a562b05be899e95d42); [Mod page](https://mods.factorio.com/mod/ai-player)
- Coworker multi-agent: per-role profiles live in `storage.ai_agents[id]`. `AIAgents.with(id, fn)` temporarily points the legacy global `storage.ai_player` at the role's profile, runs the single-agent code, and restores it even on error. [W agents.lua](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/mod/scripts/agents.lua)
- Coworker role limit: `ai-player-max-agents` (default 8, max 64). Roles not touched for `ai-player-idle-timeout-minutes` (default 30) are **deleted, character destroyed**, by `cleanup_agents()` every 3600 ticks. [W control.lua L163-193, L242-265](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/mod/control.lua#L242-L265); [W settings.lua](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/mod/settings.lua)
- Each Coworker role gets a map chart tag and an overhead `rendering.draw_text` label (`markers()`). [W control.lua L31-60](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/mod/control.lua#L31-L60)
- Coworker audit: four roles (`codex-1`, `codex-2`, `claude-1`, `opencode-1`) were created on a remote dedicated 2.0.77 server, each with a distinct unit number. A human client joining was "not yet observed". [W dynamic-role audit](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/audits/2026-10-04-dynamic-role-e2e.md)
- Coworker's own audit found a leftover builder character "standing at (57,36), its collision box covering a corner of the footprint", which made drill revives fail. `clear_area` now teleports the character back to its start "(multi-agent surprise)". [W mining-outpost audit](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/audits/2026-10-08-mining-outpost-e2e.md); [W batch_actions.lua L1245-1251](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/mod/scripts/batch_actions.lua#L1245-L1251)

### Inferences
- The recurring bug across the family is AI characters body-blocking their own build sites, and humans' sites too. Claude Crew should keep or add a "step-aside" check: before placing or reviving, test whether any character (AI or human) overlaps the footprint and walk off it. With legit walking this costs real time, so build-position selection should pick a standing tile outside the footprint but within reach.
- Coworker's idle-timeout cleanup that destroys characters is a design to avoid. Destroying a character deletes its inventory. Claude Crew should never auto-delete characters on inactivity.
- Coworker's `AIAgents.with` swap pattern is a cheap way to make single-agent Lua multi-agent. It only works because Factorio runs scripts single-threaded, and it relies on a pcall restore.

### Gaps
- No project documents testing with several *human* clients connected at once while AIs act, which is Claude Crew's main scenario.
- I could not determine whether ai-player-v3 co-op ever caused desyncs. Nothing was reported, but the user base is tiny.

---

## Q4. Legit play vs cheats (with code quotes)

### Takeaway
Every project in the family cheats heavily. Movement is `character.teleport`. Mining is `character.mine_entity(target, true)`, which is instant and force-mined, looped up to 150 times in one tick. Construction is `ghost.revive{}` or `surface.create_entity{}` with no reach check. Chest and machine transfers work across up to 128 tiles. Crafting is the only legit mechanic (`begin_crafting`). The ai-player-v3 FAQ claim "No. The AI plays by normal rules… only acts on what it actually has and can reach" is **contradicted by its own code**. Legality checks exist for *placement* only (`can_place_entity{build_check_type=manual}`). The author himself writes "the ai cheats over RCON - illegal placement of machines".

### Cited Findings
- **Teleport movement (ai-player-v3):** `action_move` walks up to 16 tiles but ends in `character.teleport(best)`. [A primitives.lua L174-214](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/scripts/primitives.lua#L174-L214)
- `goto`: `local safe = surface.find_non_colliding_position("character", target, 5, 0.5) or target; character.teleport(safe)`. Teleport is to any map coordinate. [A skills.lua L524-534](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/scripts/skills.lua#L524-L534)
- `return_home` also teleports (`character.teleport(sp)`), even though the prompt describes it as "Walk back". [A skills.lua L453-461](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/scripts/skills.lua#L453-L461)
- **Instant mining:** `gather` runs `for _ = 1, 150 do … if sp then character.teleport(sp) end … character.mine_entity(src, true)`, capped at `math.min(p.count or 50, 300)` items, inside one game tick. [A skills.lua L22-60](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/scripts/skills.lua#L22-L60)
- The `mine` primitive also calls `character.mine_entity(target, true)`, and the target is searched around `action.position`, not the character. [A primitives.lua L216-250, L96-98](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/scripts/primitives.lua#L216-L250)
- **Revive without reach:** "NB: do NOT teleport the character to the ghost first… revive() is a force-level op and needs no character reach. `local _, ent = g.revive{raise_revive = false}`". `build_ghosts` iterates **every ghost on the surface** (`find_entities_filtered{type = "entity-ghost"}`, no force filter) in one call after one teleport to the nearest ghost. [A skills.lua L330-395](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/scripts/skills.lua#L330-L395)
- **Placement without reach, but with legality check:** `place` checks `surface.can_place_entity{… build_check_type = defines.build_check_type.manual}` plus custom rules (offshore pump must touch water, drills must cover a resource), then calls `surface.create_entity{…}` and `inv.remove{name=item_name, count=1}`. The comment admits "create_entity (used below) bypasses these rules". [A primitives.lua L252-339](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/scripts/primitives.lua#L252-L339)
- `build_miner` comment: "place/insert here all use explicit positions (find_entity searches around action.position, not the character), so no character reach is needed." [A skills.lua L142-146](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/scripts/skills.lua#L142-L146)
- **Remote transfers:** `loot_chests` pulls everything from every `container`/`logistic-container` within `math.min(p.radius or 32, 128)` tiles, "(any force)". `fuel_all` refuels every burner within 64 tiles. `deposit_to_chest` reaches up to 128 tiles. [A skills.lua L190-324](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/scripts/skills.lua#L190-L324)
- `pickup` destroys `item-entity`s within the radius and inserts their stacks. [A primitives.lua L471-497](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/scripts/primitives.lua#L471-L497)
- `/ai-collect` uses `e.mine{inventory = char_inv}` on every entity of the force across the surface (solo only). [A control.lua L646-681](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/control.lua#L646-L681)
- **Legit crafting:** `character.begin_crafting{recipe=action.recipe, count=count}` is real hand-crafting with real time. [A primitives.lua L363-373](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/scripts/primitives.lua#L363-L373)
- FAQ claim: "Does it cheat or spawn items? No. The AI plays by normal rules… It only acts on what it actually has and can reach." [A FAQ.md](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/FAQ.md). The portal description by the same author lists under Challenges: "Triple burner miners - the ai cheats over RCON - illegal placement of machines". [Mod page](https://mods.factorio.com/mod/ai-player-v3)
- **Coworker keeps all of these:** `goto` → `character.teleport(safe)`; `mine` → `character.mine_entity(target, true)`; `build_ghost` → `ghost.revive{raise_revive = false}`; `place` → `surface.create_entity`; `batch_mine` gather teleports adjacent and mines. Its own action table describes `goto` as "Absolute teleport to coordinates" and `move` as "One teleport step, capped at 16 tiles". [W atomic_actions.lua L216-269, L363-400](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/mod/scripts/atomic_actions.lua#L216-L269); [W batch_actions.lua L162-210](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/mod/scripts/batch_actions.lua#L162-L210); [W action-classification audit](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/audits/2026-10-08-action-classification.md)
- Coworker does restrict some things: `batch_take` "must specify exact items and quantities; no take-all mode", and `batch_mine` clear mode "only clears trees, rocks and marked objects, never unmarked buildings". It also blocks arbitrary Lua in the CLI. [W SKILL.md](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/skills/factorio-ai-coworker/SKILL.md)
- ob_105 (no code available): the maintainer explained a recurring "LuaEntity API call when LuaEntity was invalid" error as "The AI is trying to mine something out of its range", which suggests some range concept existed in the original. [Error executing action](https://mods.factorio.com/mod/ai-player/discussion/6973fd9874697d7be3362eae)

### Inferences
- On legitimacy, Claude Crew is strictly ahead: pathfinding walk, reach, mining time, and no remote revive. The flip side is that these mods have **zero idle time from travel or mining**, because skills complete in one tick. This is why they feel productive with slow LLMs (about 5 s tick interval, minutes per local-model call). Claude Crew cannot copy that without breaking its rules. Its idle-time lever has to be the deterministic controller pipelining walk, mine, and craft, not instantaneous skills.
- Their *placement legality* layer is worth borrowing, since Claude Crew's characters also have no LuaPlayer and probably use create_entity or revive too: `can_place_entity{build_check_type=manual}` plus the domain-specific `placement_problem()` messages.

### Gaps
- Whether ob_105's original teleported or walked can't be verified without its source.

---

## Q5. Skills / macro-actions: inventory, robustness, work per LLM call

### Takeaway
ai-player-v3 has 11 coarse skills and 18 primitives, executed synchronously. Error strings are actionable, but there are no retries, no verification beyond inventory deltas, and frequent silent action drops. Coworker refactors this into 8 `batch_*` actions and about 25 atomic actions. It is notably more robust: an exact-coordinate contract, atomic inventory pre-checks, live-ghost plan records, a mandatory post-build status audit, an optimistic-concurrency `state_hash`, and a prototype-derived mining-outpost planner. Per LLM call, ai-player-v3 runs 1–3 entries; one `gather` can mine 300 items or `build_ghosts` can build every ghost on the map. Coworker allows up to 4 inline entries, or 256 from a file, with up to 500–1000 entities per batch.

### Cited Findings
**ai-player-v3**
- Skills (registry): `build_ghosts`, `deconstruct`, `gather(item,count≤300)`, `build_miner(resource,output=chest|furnace|belt)`, `build_smelter(ore,count≤6)`, `fuel_all`, `loot_chests(radius≤128,items)`, `deposit_to_chest(radius,keep)`, `return_home`, `research(tech?)`, `goto(position)`. [A skills.lua L539-551](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/scripts/skills.lua#L539-L551)
- Primitives: `move`, `mine`, `place`, `set_recipe`, `craft`, `insert`, `take`, `shoot`, `pickup`, `chat`, `summary`, `add_note`, `view_notes`, `create_todo`, `add_todo`, `complete_todo`, `view_todo`, `wait`. [A primitives.lua L572-591](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/scripts/primitives.lua#L572-L591)
- Robustness details:
  - Every handler is wrapped in `pcall`.
  - Results `{action, ok, detail}` go into `last_action_results` and are fed back next turn as "[OK]/[FAILED] …".
  - Mine success is judged by inventory delta, because "mine_entity's return value is unreliable for RESOURCES: it returns false whenever the patch isn't fully depleted".
  - The fluid-vs-item error says "'water' is a FLUID, not an item".
  - The insert error hints "coal goes in 'fuel', ore in 'input'".
  - Research handles 2.0 `research_trigger` techs ("is unlocked by CRAFTING, not queuing").
  
  [A primitives.lua L22-32, L216-250, L375-417](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/scripts/primitives.lua#L216-L250); [A skills.lua L468-517, L582-590](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/scripts/skills.lua#L468-L517)
- Weak spots:
  - `build_smelter` places furnaces at `base.x + i*2` around the character, wherever it stands.
  - When missing an item, `build_miner` and `build_smelter` queue one craft and return "retry next turn".
  - `deconstruct` breaks on the first failure ("stop rather than spin").
  
  The README's own Challenges list: "Infinite bootstrap, always dropping and starving furnaces". [A skills.lua L66-185](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/scripts/skills.lua#L66-L185); [Mod page](https://mods.factorio.com/mod/ai-player-v3)
- Silent drops (Issue #2): when the model writes `{"skill":"craft",…}`, the bridge validator drops it ("Unknown skill craft at index 0 — dropped") because craft is a primitive. "I saw it repeatedly across a short run… quiet data loss in the hot path." The reporter suggests coercing between the keys and feeding rejections back to the model. [Issue #2](https://github.com/thedemon117/ai-player-v3/issues/2); [A api.py](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/bridge/factorio/api.py)
- The 0.3.4 changelog fixed "the bridge getting stuck repeating `build_ghosts` forever when ghosts couldn't be built". The prompt now drops the hard gate if the last `build_ghosts` failed. [portal changelog](https://mods.factorio.com/mod/ai-player-v3); [A prompt.py](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/bridge/prompt.py)
- `/ai-do <skill>` runs a skill with no LLM. `/ai-force <skill>` locks the router to one skill. [A control.lua L683-774](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/control.lua#L683-L774)
- Blueprint round-trip: `import_blueprint` creates an `item-on-ground` blueprint stack, calls `stack.build_blueprint{force_build=true}`, and falls back to `create_entity{name="entity-ghost", inner_name=be.name, direction=be.direction}` from `get_blueprint_entities()` when `build_blueprint` returns nothing. That fallback drops recipes and other entity settings. `export_blueprint` uses `create_blueprint` over an area. [A control.lua L107-213](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/control.lua#L107-L213)

**Coworker 0.2.0**
- Batch actions:
  - `batch_build_ghost` (area, radius, an explicit `entities` list of up to 500, or `use:"last_plan"`)
  - `batch_mine` (gather, deconstruct, or clear area)
  - `batch_create_ghost` (an explicit list, or `layout="mining_outpost"`)
  - `batch_review_build`
  - `batch_remove_ghost`
  - `batch_insert` (fill or deposit)
  - `batch_take` (exact items only)
  - `batch_pickup`
  
  Atomic actions include `move`, `goto`, `mine`, `place`, `create_ghost`, `build_ghost`, `review_build`, `remove_ghost`, `set_recipe`, `craft`, `insert`, `take`, and `research`. [W SKILL.md](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/skills/factorio-ai-coworker/SKILL.md); [W mod/changelog.txt](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/mod/changelog.txt)
- Exact-coordinate contract: `aligned_position()` rejects misaligned anchors instead of snapping them, and states the legal value: "%s is %dx%d — %s must be n+0.5 (got %g; use %g)". It is rotation-aware (east/west swap w and h). The comment: "the old parity snap moved anchors by up to half a tile, so agents could no longer reason about where things actually landed". [W batch_actions.lua L28-70](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/mod/scripts/batch_actions.lua#L28-L70)
- Atomic pre-check: an explicit-list build matches every entry to an existing ghost (with direction-mismatch detection), then "Atomic inventory pre-check: any shortage builds NOTHING" ("shortage — 3x … (have 1); nothing placed"). [W batch_actions.lua L1388-1501](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/mod/scripts/batch_actions.lua#L1388-L1501)
- Plan memory: `remember_plan()` stores **live ghost LuaEntity refs** per character, so "reviving or clearing a ghost invalidates its ref, so the record always reflects what is still unbuilt". Re-runs merge. [W batch_actions.lua L131-160](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/mod/scripts/batch_actions.lua#L131-L160)
- Mandatory post-build audit: `audit_entities()` runs `review_build` on every built entity. It reports status buckets and lists problem entities such as no_power, no_fuel, or a flipped inserter, plus unbuilt ghosts left in scope. [W batch_actions.lua L84-118, L1516-1568](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/mod/scripts/batch_actions.lua#L1516-L1568)
- Ghost scoping: `batch_build_ghost` filters by `force = character.force` and an optional area or radius "so a batch never consumes unrelated ghosts belonging to another plan or another agent". [W batch_actions.lua L979-1076](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/mod/scripts/batch_actions.lua#L979-L1076)
- Mining-outpost planner (`batch_action_plan_mining_outpost`):
  - Derives the lattice from `drill_proto.mining_drill_radius` with step `S = 2H+1`, and pairs drill rows facing a shared belt.
  - Pole streets come from pole supply and wire reach. A preflight rejects under-reaching poles ("rows 13 apart, needs reach 7 — pass a bigger pole (e.g. substation)").
  - Rejects crude-oil and uranium.
  - Is idempotent: a re-run only fills missing slots.
  - Audit result: 79 drills, 650 belts, 49 medium poles, 99% coverage, 79/79 powered.
  
  [W batch_actions.lua L272-633](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/mod/scripts/batch_actions.lua#L272-L633); [W mining-outpost audit](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/audits/2026-10-08-mining-outpost-e2e.md)
- 2.0.77 quirk recorded in that audit: pole prototype getters threw "Invalid QualityID" inside the RCON sandbox, even with valid quality prototypes. Workaround order: getter, then a Wiki table, then conservative small-pole defaults. Also, `resource_searching_radius` was renamed to `mining_drill_radius` in 2.0. [W mining-outpost audit](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/audits/2026-10-08-mining-outpost-e2e.md); [W batch_actions.lua L213-270](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/mod/scripts/batch_actions.lua#L213-L270)
- CLI optimistic concurrency: `state` returns a 12-hex `state_hash` (sha256 of the state JSON). `step --expected-state HASH` re-reads state and rejects the whole batch with `{"reason":"state_changed"}` on mismatch. Steps stop on the first failure unless `--continue-on-failure` is given, and `--dry-run` validates without touching the game. [W cli/main.py L67-70, L251-291](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/cli/main.py#L251-L291)
- Validated production result in the audit: a burner drill → burner inserter → chest line for iron and copper. "Two 5-second CLI samples recorded both chest contents rising from 22 to 25 ore… verifies real downstream transport rather than hand-inserted ore". The steam-power attempt failed because the boiler steam output was unconnected, and the audit "does not claim the electric generator is complete". [W gpt6-sol audit](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/audits/2026-10-08-gpt6-sol-production-e2e.md)

**ChatGPT fork**
- Invalid batches are rejected whole: "Reject the entire dependent batch if any entry is invalid." It keeps an 8-entry `recent_execution_history` across turns. [C agent.py](https://github.com/ethanrcohen/ai-player-chatgpt/blob/64cacbc5a5229c8273c4a68e9cbbee3bab7b57e1/bridge/agent.py)

### Inferences
- How much happens per call is the main difference from Claude Crew. These mods do a lot per call only because they cheat. Claude Crew's work orders, with a deterministic controller and done_when checks, are the right granularity for legit play. Several Coworker robustness ideas map straight onto Claude Crew's controller: the atomic pre-check, the live-ref plan record, the post-build audit, the exact coordinates, and the state hash.
- Coworker's "post-build audit" is a cheap, generic done_when: no problem statuses among the built entities and zero ghosts left in scope. Claude Crew could adopt it as a default check for any build order.

### Gaps
- No success-rate statistics over long runs exist for any project. ai-player-v3 collects metrics but publishes none.

---

## Q6. Planning, coordination, and chat commands

### Takeaway
ai-player-v3 has no planner. It has a priority ladder (ghosts > deconstruction > forced skill > free choice), a soft chat "directive" with a 30 s TTL, todo/note memory, and an immediate model-free chat acknowledgement. Ghosts and deconstruction marks are treated as the human's plan. Coworker's coordination is human-authored prompt convention (a coordinator writes "work units" to status files), with no automatic dispatch and no chat commands. Nothing in the family approaches Claude Crew's coordinator, structured work orders, and scheduler.

### Cited Findings
- Chat directive parsing (ai-player-v3): any player's message prefixed `ai: `, `ai, `, `!ai `, or `ai ` becomes a directive. The mod immediately prints "[AI] Got it — working on: <directive>" ("Immediate, model-independent acknowledgement… does not wait on the (possibly slow) LLM"). It stores `pending_user_message` so a message sent while a request is in flight still reaches the next request, and calls `request_decision`. [A control.lua L498-543](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/control.lua#L498-L543)
- The directive lives 1800 ticks (30 s) via `set_directive(directive, 1800)`. If its first word names a skill, the router is hard-gated to that skill until expiry. [A brain.lua set_directive](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/scripts/brain.lua)
- All chat lines go into a 100-entry ring buffer (`chat_log`), readable via `remote.call('ai_player','get_chat',{since=tick})`. [A control.lua L485-508, L88-104](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/control.lua#L485-L508)
- Priority ladder in the prompt: "If ghosts.count > 0, do build_ghosts FIRST… this is the human telling you what to build", then deconstruction. The hard gate is "placed LAST for recency: small models ignore priority rules buried mid-prompt". [A prompt.py](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/bridge/prompt.py)
- Memory primitives: `summary`, `add_note`, `create_todo`, `add_todo`, `complete_todo`, kept in `storage.ai_player.memory` (recent_actions capped at 6). [A primitives.lua L507-566](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/scripts/primitives.lua#L507-L566)
- The ChatGPT fork adds `/ai-goal <goal>` as a persistent long-term goal, distinct from temporary `ai:` directives that "take priority without deleting" it. [C control.lua ai-goal](https://github.com/ethanrcohen/ai-player-chatgpt/blob/64cacbc5a5229c8273c4a68e9cbbee3bab7b57e1/mod/control.lua); [C README](https://github.com/ethanrcohen/ai-player-chatgpt/blob/64cacbc5a5229c8273c4a68e9cbbee3bab7b57e1/README.md)
- The ChatGPT fork's design doc proposes durable task records (objective, constraints, discovered sources and consumers, evidence ticks, created entity IDs), treating observations as "facts that can expire", stopping dependent steps on failure, and tracking ownership. Acceptance criteria include "Sustains the agreed engine rate across multiple observation windows without the agent hand-feeding ingredients". These are proposals, not implemented. [C docs/agent-research.md](https://github.com/ethanrcohen/ai-player-chatgpt/blob/64cacbc5a5229c8273c4a68e9cbbee3bab7b57e1/docs/agent-research.md)
- pi-factorio keeps a durable ledger (tech, blocks with produces/status, goals, and an events ring buffer). A compaction hook injects it into the summary. [P ledger.ts](https://github.com/thedemon117/pi-factorio/blob/ba814e8072104ffb213a428df79c6a7e4fd2f02b/src/ledger.ts); [P SKILL.md](https://github.com/thedemon117/pi-factorio/blob/ba814e8072104ffb213a428df79c6a7e4fd2f02b/skills/factorio-play/SKILL.md)
- Coworker coordination is entirely prompt convention: the `factorio-coordinator` agent does "read-only survey, plan comparison and WU orchestration… each WU must designate executor, sole responsibility, inputs/outputs, prohibited boundaries, verification conditions and status file… no automatic dispatch". Executors do one bounded work unit, must serialize writes to shared facilities and the research queue, and verify after writing. [W .opencode/agents/factorio-coordinator.md](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/.opencode/agents/factorio-coordinator.md); [W .opencode/agents/factorio-builder.md](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/.opencode/agents/factorio-builder.md)
- An archived audit tested an `ao-router.sh` that delivered a work unit to role sessions and reported OFFLINE roles honestly. It was later removed ("archive"). [W archive/2026-10-06-agent-router-e2e.md](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/audits/archive/2026-10-06-agent-router-e2e.md)
- Coworker's `on_console_chat` only appends chat to every role's log. No directive parsing and no LLM trigger. [W control.lua](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/mod/control.lua)
- Coworker annotations: `annotate --label/--icon/--map-tag-json` puts plan labels on the map as `[type] name @role`. [W SKILL.md](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/skills/factorio-ai-coworker/SKILL.md); [W map-perception audit](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/audits/2026-10-06-map-perception-planning.md)

### Inferences
- The instant, model-free chat acknowledgement and the "queue the message if a request is in flight" behaviour are directly relevant to Claude Crew's "@name" UX and to keeping humans informed while Opus plans.
- The ghosts-as-human-intent priority is a good default for "help my friend": if the friend lays ghosts (for example for platform parts built on nauvis), crew actors should treat them as top-priority work orders. Claude Crew already builds ghosts; the borrowable part is making a human's fresh ghosts preempt idle work automatically.
- Coworker's map chart tags labelling who owns what are a cheap way to make multi-agent ownership visible to humans.

### Gaps
- No project implements real multi-agent conflict resolution: claims, reservations, or locks on chests and areas. Coworker only states it as a rule in prompts.

---

## Q7. Observation design: what the model sees and how it is compressed

### Takeaway
ai-player-v3 sends one JSON perception blob per decision:
- the character
- the full inventory (up to 100 stacks)
- craftable recipes (up to 25)
- the nearest 25 entities within the vision radius (default 20)
- grouped resources
- up to 10 enemies
- up to 5 water tiles
- research
- game phase (0–6)
- a registry-backed whole-factory summary (counts by type and status, a nearest-first attention list, and the full roster only when small)
- needs buckets
- power
- production per minute
- ghost and deconstruction counts with lists capped at 25

Coworker adds an ASCII terrain grid map (up to 128×128) and exact geometry: bounding boxes, fluid connection targets and connected flags, and inserter pickup/drop positions. The ChatGPT fork adds paginated filtered `scan_area` with exact half-tile coordinates.

### Cited Findings
- `AIPerception.gather()`: inventory via `summarize_inventory(char_inv, 100)`, with the comment "Truncating to the top-N by count hid low-count buildables (e.g. 4 burner-mining-drill), so the model thought it had 0". Nearest-first 25-entity cap "so the 25-cap keeps the closest entities… instead of an arbitrary slice that belts/poles could crowd out". [A perception.lua L402-612](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/scripts/perception.lua#L402-L612)
- The vision radius default is 20 and the tick interval default is 300 (mod settings). [A settings.lua](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/settings.lua)
- Factory view `gather_factory()`: reads an event-maintained registry (built/removed events plus a full reconcile every 600 ticks) of tracked machine types. It emits `by_type`, `by_status`, an `attention` list of problem-status machines sorted by distance and capped at ATTENTION_LIMIT, `needs` buckets (`burners_low_fuel`, `machines_no_recipe`, `machines_no_input`, `outputs_full`), and a full roster only when `total <= FACTORY_DETAIL_THRESHOLD`. [A perception.lua L281-340](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/scripts/perception.lua#L281-L340); [A registry.lua](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/scripts/registry.lua)
- Production stats via `force.get_item_production_statistics(surface)` (added in 0.3.4: "all-time totals and per-minute rates for key items… plus researched-tech count"). [A perception.lua L229-280](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/scripts/perception.lua#L229-L280); [portal changelog](https://mods.factorio.com/mod/ai-player-v3)
- Ghosts and deconstruction are scanned across the **entire surface** every decision (`find_entities_filtered{type="entity-ghost"}`, `{to_be_deconstructed=true}`). [A perception.lua](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/scripts/perception.lua)
- The prompt dumps perception as `json.dumps(perception, indent=1)` plus a per-phase hint string. [A prompt.py](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/bridge/prompt.py)
- The ChatGPT fork's own critique: "perception.lua caps local detail at 25 nearest entities. Belts can fill that sample and hide the relevant machines… The shared entity description floors coordinates and omits belt-lane contents, belt connectivity, and inserter pickup/drop positions." [C docs/agent-research.md](https://github.com/ethanrcohen/ai-player-chatgpt/blob/64cacbc5a5229c8273c4a68e9cbbee3bab7b57e1/docs/agent-research.md)
- `scan_area` (ChatGPT fork 0.5.2) filters before paging (name, type, recipe), returns `total`/`offset`/`next_offset`, exact positions, direction, and inserter pickup/drop positions, with the note "proximity does not establish a logistics connection". [C queries.lua](https://github.com/ethanrcohen/ai-player-chatgpt/blob/64cacbc5a5229c8273c4a68e9cbbee3bab7b57e1/mod/scripts/queries.lua)
- Coworker's `map`/`scan_area` returns a terrain grid where `?` is unexplored, `W` water, `T` tree, `R` rock, `B` own building, `g` ghost, and `i/u/c/s/o/U/x` are resources (side ≤ 128). Entities carry a rotated `bounding_box`, `fluid_connections.target_position`/`connected`, pipe `segment_contents`, and inserter pickup/drop and fuel. `get_resource_patch all=true` clusters every charted patch. [W SKILL.md](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/skills/factorio-ai-coworker/SKILL.md); [W queries.lua L528+](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/mod/scripts/queries.lua#L528); [W map-perception audit](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/audits/2026-10-06-map-perception-planning.md)
- The map-perception audit was motivated by user feedback that "AI can't see the overall map, causing messy wiring/belts and smelting lines laid on top of ore". [W map-perception audit](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/audits/2026-10-06-map-perception-planning.md)

### Inferences
- For Claude Crew's bottleneck diagnosis, the ai-player-v3 pattern (registry plus status buckets, a nearest-first attention list, and named needs buckets) is a good compact first layer. Coworker's fluid-connection `connected=false` and inserter endpoints are exactly what a coordinator needs to explain why a machine is idle, as in the failed steam-engine case.
- Scanning ghosts across the whole surface every decision would be a UPS risk on a big multiplayer base. Claude Crew should scope by area or force, as Coworker does.

### Gaps
- No measurements of prompt size or token cost per decision, apart from one ob_105 log line showing about 3058 prompt tokens.

---

## Q8. Known bugs and limits (issues, discussions, changelogs)

### Takeaway
The documented failures are poor factory competence, cheating placement, silent action drops, self-body-blocking, setup and RCON friction, an ob_105 multiplayer desync, and crashes on unknown items. Users of the original report a week of play yielding about 4 furnaces.

### Cited Findings
- ob_105 effectiveness: "I have left this running for a week, it explored maybe 2x the starting map size, build 4 furnice's and 1 piece conveyer, even used an LLM on a really fast server so responses were coming back every 30 seconds." [Anyone had the AI actually build a factory?](https://mods.factorio.com/mod/ai-player/discussion/69826db0767ade210ebce16c)
- Demon117_ in the same thread: "the fuel and ore inputs for the furnace is even more challenging… getting the ai-player to follow the rules and not place buildings where they shouldn't - offshore pump on an crude oil output with a boiler and some pipe". [same thread](https://mods.factorio.com/mod/ai-player/discussion/69826db0767ade210ebce16c)
- ai-player-v3 Challenges: "Infinite bootstrap, always dropping and starving furnaces; Triple burner miners - the ai cheats over RCON - illegal placement of machines". [Mod page](https://mods.factorio.com/mod/ai-player-v3)
- Issue #2: valid craft and place actions are silently dropped due to the skill/action key confusion (2.0.77, mod 0.4.2, qwen2.5-coder:7b via Ollama). Open as of 2026-10-18. [Issue #2](https://github.com/thedemon117/ai-player-v3/issues/2)
- Issue #1: `build_miner` fails when the AI or a human stands on the nearest ore tile. There is also an API inconsistency: `can_place` wants `{entity,x,y}` while `place` wants `{item,position}`. Open. [Issue #1](https://github.com/thedemon117/ai-player-v3/issues/1)
- Changelog fixes: 0.3.4 fixed a load crash ("`goto` is a reserved keyword in Lua 5.2") and the infinite `build_ghosts` loop; 0.3.5 fixed teleports stacking characters. [portal changelog](https://mods.factorio.com/mod/ai-player-v3)
- ob_105 multiplayer desync. [Multiplayer server on Linux](https://mods.factorio.com/mod/ai-player/discussion/696436a562b05be899e95d42)
- ob_105 crash on the `spores` item. [Spore error](https://mods.factorio.com/mod/ai-player/discussion/6976b90294b63fda4500faee)
- ob_105 setup: RCON needs Ctrl+Alt+Settings → "The rest" `local-rcon-socket`/`local-rcon-password` for menu-hosted games. "In standard single-player mode, Factorio physically closes the RCON port!". The bridge overwrote config.json and wiped the password. [Complit](https://mods.factorio.com/mod/ai-player/discussion/6a7a8f4605a4cf437b325fe0)
- The ChatGPT fork's `play.py` edits Factorio `config.ini` `[other]` `local-rcon-socket`/`local-rcon-password` (with a backup) and launches Steam Factorio with `--rcon-bind`. It is macOS-only. [C bridge/play.py](https://github.com/ethanrcohen/ai-player-chatgpt/blob/64cacbc5a5229c8273c4a68e9cbbee3bab7b57e1/bridge/play.py)
- Coworker 2.0.77 quirks: "Invalid QualityID" from pole getters under RCON; `resource_searching_radius` → `mining_drill_radius`; the 16-direction map accepted "northeast" for a drill layout (fixed to 4 directions); a headless server was killed by SIGTERM when launched with `nohup … &` from the harness process group (fixed with `start_new_session=True`). [W mining-outpost audit](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/audits/2026-10-08-mining-outpost-e2e.md)
- Coworker `wait` "is a no-op/log operation and needs a later timing fix if real waiting is required". [W action-classification audit](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/audits/2026-10-08-action-classification.md)
- A user reports ob_105 freezing or RCON exceptions on overhaul mods and multi-surface maps. [Complit](https://mods.factorio.com/mod/ai-player/discussion/6a7a8f4605a4cf437b325fe0)

### Inferences
- Even with cheats, every project in this family stalls at early-game burner/steam competence. That supports Claude Crew's choice to have a strong coordinator plan and deterministic code execute, rather than a small model improvising placements.
- The 2.0.77 "Invalid QualityID" RCON quirk is worth checking in Claude Crew's late-game tools, since copy/paste blueprints and upgrade planners touch quality-parameterized prototype APIs.

### Gaps
- There is no issue tracker for the Coworker or ChatGPT forks with any entries, so their real-world failure modes are unknown.

---

## Q9. What they do better than Claude Crew, what Claude Crew does that they don't, and what to borrow

### Takeaway
Claude Crew is ahead on nearly every requirement that matters tonight: legit play, multiple agents with humans, @name chat commands, a coordinator with work orders and done_when checks, a scheduler, late-game tools, benchmarks, and cost tracking. The family's useful contributions are tactical:
- ai-player-v3: placement-legality checks and actionable error strings, a model-free chat ack and message queueing, ghosts-as-intent priority, and registry-based factory status compression.
- Coworker: the exact-coordinate contract, atomic pre-checks, live-ghost plan records, post-build audits, state-hash concurrency, rich geometry queries, a prototype-derived mining-outpost planner, per-agent map labels, and documented 2.0.77 quirks.
- ChatGPT fork: a bounded read-only investigation loop and reject-whole-batch semantics.
- pi-factorio: a compaction-surviving ledger and a deliberation-budget prompt.

### Cited Findings
**Where they are "better" or different (with caveats)**
- Zero travel and mining latency per skill, because everything is teleport or instant (Q4). Feedback is immediate and every action reports a precise `detail` string. [A skills.lua](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/scripts/skills.lua)
- LLM-free operation and debugging: `/ai-do` and `/ai-force` let a human run any skill deterministically from chat. [A control.lua L683-774](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/control.lua#L683-L774)
- Mining-outpost auto-layout from prototypes, with a power-coverage preflight (Coworker). [W batch_actions.lua L272-633](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/mod/scripts/batch_actions.lua#L272-L633)
- Rich connection geometry (fluid targets and connected flags, inserter endpoints) in queries (Coworker, ChatGPT fork). [W SKILL.md](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/skills/factorio-ai-coworker/SKILL.md)
- Local-model-first design (LM Studio or Ollama) and ChatGPT-subscription sign-in. [A providers](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/bridge/providers/__init__.py); [C chatgpt_auth.py](https://github.com/ethanrcohen/ai-player-chatgpt/blob/64cacbc5a5229c8273c4a68e9cbbee3bab7b57e1/bridge/chatgpt_auth.py)

**What Claude Crew has that none of them do** (from the assignment's description of Claude Crew, checked against the code above)
- Legit-rules execution: walking with pathfinding, reach, and real mining time (all of them teleport and instant-mine, Q4).
- Multiple characters commanded by @name/@all from chat. ai-player-v3 has one AI and an `ai:` prefix; Coworker has no chat dispatch (Q3, Q6).
- A coordinator model producing structured work orders with in-game done_when checks, plus a deterministic scheduler. Coworker's coordinator is a manual prompt convention with "no automatic dispatch" (Q6).
- A deterministic actor controller that calls the model only on exceptions. ai-player-v3 calls the LLM every 5 s tick regardless (Q2).
- Late-game tools: bottleneck diagnosis, copy/paste of builds, upgrade/deconstruct planners, logistic network, requester/filter configuration, armor. The family tops out at burner/steam, mining outposts, and raw blueprint import/export.
- A benchmark harness with staged saves and cost tracking. ai-player-v3 has per-turn metrics and a latency benchmark only. [A bridge/report.py](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/bridge/report.py); [A bridge/benchmark.py](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/bridge/benchmark.py)

**Concrete borrow list (file and function references)**
1. **Placement legality before `create_entity`/revive.** `placement_problem()` (offshore pump on water, drill on a resource) plus `surface.can_place_entity{…, build_check_type = defines.build_check_type.manual}` with model-readable reasons. [A primitives.lua L252-319](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/scripts/primitives.lua#L252-L319)
2. **Mine success by inventory delta, not the `mine_entity` return value.** The return value is false for partially mined resource tiles. [A primitives.lua L225-250](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/scripts/primitives.lua#L225-L250)
3. **Actionable error strings for small models.** `item_problem()` for fluid vs item, the insert slot hints, and the `research` trigger-tech message ("unlocked by CRAFTING, not queuing"). [A primitives.lua L22-32](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/scripts/primitives.lua#L22-L32); [A skills.lua L480-517](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/scripts/skills.lua#L480-L517)
4. **Model-free instant chat ack plus queued pending message** while a request is in flight. [A control.lua L524-542](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/control.lua#L524-L542); [A brain.lua request_decision](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/scripts/brain.lua)
5. **`position_beside()` and a step-aside check.** Characters don't collide with each other, so don't stack them, and move the actor off a footprint before building (Issue #1). [A control.lua L583-599](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/control.lua#L583-L599); [Issue #1](https://github.com/thedemon117/ai-player-v3/issues/1)
6. **Registry-backed factory status compression.** `AIRegistry` (event add/remove, 600-tick reconcile, lazy prune) and `gather_factory()` (by_status counts, nearest-first attention cap, needs buckets). This is a cheap first pass for "fix our iron bottleneck". [A registry.lua](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/scripts/registry.lua); [A perception.lua L281-340](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/mod/scripts/perception.lua#L281-L340)
7. **Anti-loop gating.** If the last attempt of X failed, forbid X this turn and point at the missing items (`_failed_detail`, ghost escape hatch). Map this onto Claude Crew's exception path so the small actor model doesn't retry identical failures. [A prompt.py](https://github.com/thedemon117/ai-player-v3/blob/2806aed808a1966db21f4edebc8060dd30cc332b/bridge/prompt.py)
8. **Coerce instead of drop on schema slips** (skill vs action key), and feed rejections back to the model. [Issue #2](https://github.com/thedemon117/ai-player-v3/issues/2)
9. **Exact-coordinate contract.** `aligned_position()` is rotation-aware and rejects misaligned anchors, suggesting the legal value. [W batch_actions.lua L28-70](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/mod/scripts/batch_actions.lua#L28-L70)
10. **All-or-nothing material pre-check** for a build list ("any shortage builds NOTHING"), plus per-entry direction-mismatch detection. [W batch_actions.lua L1388-1501](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/mod/scripts/batch_actions.lua#L1388-L1501)
11. **Live-ghost plan record** (`remember_plan`, keyed per character unit_number, with merge on re-run) as a cheap "what's left" for a work order. [W batch_actions.lua L131-160](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/mod/scripts/batch_actions.lua#L131-L160)
12. **Post-build commissioning audit** (`audit_entities`/`batch_action_review_build`) as a generic default done_when: no problem statuses and no unbuilt ghosts in scope. [W batch_actions.lua L84-118, L1516-1568](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/mod/scripts/batch_actions.lua#L1516-L1568)
13. **Force- and area-scoped ghost selection** so agents never consume another agent's or a human's unrelated ghosts. [W batch_actions.lua L979-1010](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/mod/scripts/batch_actions.lua#L979-L1010)
14. **Optimistic concurrency** (`state_hash` plus `--expected-state`) for coordinator-issued orders when humans change the world mid-plan. [W cli/main.py L67-70, L251-291](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/cli/main.py#L251-L291)
15. **Mining-outpost planner** (`batch_action_plan_mining_outpost`): lattice step from `mining_drill_radius`, pole streets from supply and wire reach, a power-coverage preflight, idempotent re-runs. Useful when "fix our iron bottleneck" means "add drills". [W batch_actions.lua L213-633](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/mod/scripts/batch_actions.lua#L213-L633)
16. **Geometry-rich `scan_area`/`inspect_entity`** (rotated bounding box, fluid connection target and connected flag, pipe segment contents, inserter pickup/drop) and the ASCII terrain grid `map`. [W queries.lua](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/mod/scripts/queries.lua)
17. **Per-agent visibility for humans.** A map chart tag and overhead `rendering.draw_text` label per role (`markers()`). Avoid Coworker's idle-timeout auto-delete. [W control.lua L31-60, L242-265](https://github.com/Suixinlei/factorio-ai-coworker/blob/62b60b47472b83090249a37e240e7014a3e178a9/mod/control.lua#L31-L60)
18. **Bounded read-only investigation loop.** Typed allowlisted queries, at most 4 rounds × 3 queries, a 16 KB result cap, a shared deadline, never mixing queries and actions, and rejecting the whole dependent batch on any invalid entry. Good for actor exception handling with a small model. [C investigation.py](https://github.com/ethanrcohen/ai-player-chatgpt/blob/64cacbc5a5229c8273c4a68e9cbbee3bab7b57e1/bridge/investigation.py); [C agent.py](https://github.com/ethanrcohen/ai-player-chatgpt/blob/64cacbc5a5229c8273c4a68e9cbbee3bab7b57e1/bridge/agent.py)
19. **Evaluation discipline.** Acceptance means sustained delivery measured over multiple windows, with no hand-feeding and no coordinate coaching. This could be added as a benchmark criterion. [C docs/agent-research.md](https://github.com/ethanrcohen/ai-player-chatgpt/blob/64cacbc5a5229c8273c4a68e9cbbee3bab7b57e1/docs/agent-research.md)
20. **Compaction-surviving ledger** (blocks, goals, events) and a "deliberation budget" prompt line for the Claude Agent SDK backend. [P ledger.ts](https://github.com/thedemon117/pi-factorio/blob/ba814e8072104ffb213a428df79c6a7e4fd2f02b/src/ledger.ts); [P SKILL.md](https://github.com/thedemon117/pi-factorio/blob/ba814e8072104ffb213a428df79c6a7e4fd2f02b/skills/factorio-play/SKILL.md)
21. **Persistent goal vs. temporary directive split** (`/ai-goal` vs `ai:`). [C control.lua](https://github.com/ethanrcohen/ai-player-chatgpt/blob/64cacbc5a5229c8273c4a68e9cbbee3bab7b57e1/mod/control.lua)

### Inferences
- For tonight's session, nothing here should be installed alongside Claude Crew:
  - ai-player-v3's `reconcile_character()` would destroy playerless characters on its force, which in default co-op is the `player` force.
  - It uses the same remote interface name, `ai_player`, which is also used by Coworker and pi-factorio. That collides if Claude Crew happens to use the same name.
  - It cheats, and teleports a character beside humans.
- The quickest wins to port before playing are #4 (instant ack plus queue), #5 (step-aside before build), #10 (atomic pre-check), #12 (post-build audit as default done_when), and #13 (scoped ghosts). They are small, deterministic, and target the multiplayer-with-humans failure modes this family actually hit.

### Gaps
- I could not verify that `LuaItemStack.build_blueprint` really "returns nothing" in 2.0 as ai-player-v3's comment claims. Claude Crew's copy/paste tool should rely on its own testing, not on that comment.
- I did not verify whether Claude Crew's remote interface name collides with `ai_player`, because that is outside this research scope.
