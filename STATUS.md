# Status (2026-10-18, late)

Milestone: two Sonnet agents took an empty Space Age map to automation research in ~20 game-minutes
(e2e-4 + e2e-5 on save `crew-e2e4`). The review page for the user: https://claude.ai/artifact/VZzanDrygAnMR6Z3ZRKFNR
Added since: connect (A* belts/pipes/poles), follow, instant come/follow, foreman-first planning,
water search with pump spots, fuel swap. Smoke test is at 40 checks.

Live (2026-10-18 00:45): the user joined and played alongside a 5-agent crew (foreman on Opus, workers on Sonnet),
under systemd, with a snapshot every 30 min and peaceful mode on. Corpse looting is pending: it's a mod change, so wait
until the user disconnects.

WAS NEXT: the user joins from their client (scripts/install-client-mod.sh with Factorio closed, connect to 127.0.0.1).


## Working
- **Mod** `mod/claude-crew`: agent characters (name tag, color, speech bubble, death/respawn, freeplay starter kit),
  job queue (move/mine/craft/place/insert/take/set_recipe/rotate/research/wait), observations
  (look/map/find/inspect/techs/recipes/production), "built by" tracking (agents won't pick up human builds),
  trigger-tech accounting (playerless characters' crafts/builds/mines don't count natively; the mod records them),
  research-finished events, an in-game Crew panel (`/crew-panel` toggles it), and RCON JSON API `/crew {...}`.
- **Orchestrator** `crew/` (`.venv/bin/crew up`): one Claude per agent, on the `claude-code` backend
  (Agent SDK, your subscription) or `api` (ANTHROPIC_API_KEY). Chat router (@name, @all, bare names, "stop"),
  shared task board, per-agent notes, working/idle autonomy with budgets, human messages interrupt long waits.
  Config: `crew.toml` (see `crew.example.toml`); `--model claude-opus-5-5` for the demo.
- **Tests:** `tests/smoke.py` (36 checks, no LLM; run on the crew-test save because it resets research).
- **LLM e2e (Sonnet 5.5, subscription):** one agent built iron smelting from a single chat request in 80s.
  Two agents split "iron + copper + electronics" via the board: 4 iron pairs and 3 copper pairs, unprompted
  coordination, about $0.15 per agent-turn notional.

## Fixed after e2e (not yet re-run with LLMs)
- False "no ore under drill" warning (it made the agent move a drill that was fine).
- Crew chatter no longer cuts waits short; only humans do.
- Drill placement guidance (avoid patch edges); clearer placement errors.
- Agents now learn when research finishes (they didn't know electronics had unlocked).

## Next
1. Re-run the 2-agent e2e on a fresh map; push toward red science and automation research.
2. Join test with the real client: put the mod in `~/.factorio/mods` (ask the user first), connect to 127.0.0.1.
3. Demo polish: "@claude come here" (follow player), Q&A from data, README and install script.
