# Status (2026-10-17)

## Done
- Headless server 2.0.77 (Space Age) in `server/` (gitignored). `scripts/server.sh start|stop|log|password`.
  Save: `server/factorio/saves/crew-test.zip`, bound to 127.0.0.1, RCON 27015, password in `server/rcon-password`.
  auto_pause is off, so agents act with nobody connected. Admin: otterplex.
- Mod `mod/claude-crew` (symlinked into the server's mods dir):
  agents as script-driven characters (name tag, color, speech bubble, death and respawn),
  a per-agent job queue (move with pathfinding, mine, craft, place, insert, take, set_recipe, rotate, research, wait, say),
  observe/self/nearby/map (ASCII)/find/world/recipes/techs/production/inspect, and poll (chat, job results, events).
  RCON API: `/crew {"op":...}` returns JSON. Cheat-mode runtime setting.
- `crew/rcon.py`: async RCON client and `Crew.call(op, **kw)`. `scripts/rc.py <op> '<json>'` is the dev CLI.
- **Verified live:** spawn; walk 37 tiles by pathfinder; hand-mine 15 iron at legit speed; place furnace;
  fuel and load it; hand-craft gears; place a burner drill and fuel it; take smelted plates.

## Next
1. Restart the server so it loads the `approach()` fix (stale `walking_to` in job status), then retest.
   Untested: set_recipe, rotate, research, trees/rocks mining, place sidestep, death/respawn, cheat mode.
2. Orchestrator `crew/`: per-agent Claude loop with tools mapped to the API, chat routing (`@claude-1`, `@all`),
   job-result wakeups, shared task board, `crew.toml` (backend `claude-code` via Agent SDK on the subscription,
   or `api`; model per agent, Opus 5.5 for the demo), CLI `crew up`.
3. Scripted no-LLM tests via RCON, then an LLM end-to-end test ("make 20 iron plates").
4. Install for the user's client: symlink the mod into `~/.factorio/mods` (it must match the server), then join 127.0.0.1.
5. README and packaging.

Old browser-made advisor: `legacy/`.
