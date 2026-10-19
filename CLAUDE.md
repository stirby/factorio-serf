# Claude Crew: notes for coding agents

LLM agents play Factorio 2.0 + Space Age as script characters alongside humans, commanded from game chat.
Lua mod in `mod/claude-crew` (characters, job queue, observations, RCON JSON API `/crew {json}`); Python
orchestrator in `crew/` (one Opus foreman with no character, Sonnet worker characters, a shared task board).
Design: `docs/architecture.md`. What went wrong before and why: `docs/log-analysis/README.md`.

## If you were asked to deploy this to someone's server

Follow `DEPLOY.md`. In short: `scripts/package-mod.sh` -> copy the zip to the server's `mods/` and every player's
client, start the server with RCON, `uv venv && uv pip install -e .`, write `crew.toml` from
`crew.example.toml`, `crew status`, then `crew up`.

## Rules

- **Never overwrite or modify a real save.** Copy it first; work on the copy. Back up before adding the mod.
- **Never send `/c` or `/sc`** (or `scripts/rc.py --raw`) to a save people play: it disables achievements
  permanently. The mod's own `/crew` API is fine.
- Don't change mod files while players are connected. A mod change means: bump `version` in `info.json`,
  repackage, redistribute the zip to the server and every client, restart the server, players restart Factorio.
- Never put keys in tracked files. `crew.toml` and `crew-*.toml` are gitignored; keys go in env vars or
  `~/.config/claude-crew/env`.
- Don't expose RCON to the internet.
- Factorio binaries and third-party mods are not in this repo and must not be committed (`server/` is ignored).

## Working on the code

- `tests/smoke.py`: every mod action against a running server, no LLM (resets research: scratch saves only).
  `tests/test_foreman.py` and `tests/test_openai_backend.py` run without a server.
- `scripts/server.sh` runs a local headless server from `server/factorio` (download the headless build yourself).
  `scripts/rc.py <op> '<json>'` calls the mod API directly.
- Keep it simple. A previous order/scheduler/actor layer was built and removed because it regressed
  (docs/architecture.md build log). Check `docs/prior-art.md` before building something new.
