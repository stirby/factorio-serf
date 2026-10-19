# Deploying Claude Crew to a dedicated server

For running the crew in a real multiplayer game on someone's own server. Two pieces:

1. **The mod** (`mod/claude-crew`) runs inside Factorio, on the server *and* on every player's client.
2. **The orchestrator** (`crew/`, the `crew` command) runs on any machine that can reach the server's RCON port.
   It runs the models: one Opus foreman (no character) and Sonnet workers (characters in the game).

Tested on Factorio **2.0.77** with Space Age, alongside 18 other mods (Quality, Space Age, and QoL mods). The mod
declares `factorio_version = "2.0"`; newer 2.0.x builds should work.

## 1. Build and install the mod

```bash
scripts/package-mod.sh                       # -> dist/claude-crew_<version>.zip
scripts/package-mod.sh /path/to/server/mods  # or build and copy straight into the server's mods folder
```

- Put the zip in the server's `mods/` folder and add `{"name": "claude-crew", "enabled": true}` to its
  `mods/mod-list.json` (or the host panel's mod list).
- **Every player needs the same zip** in their own mods folder (`~/.factorio/mods`, `%APPDATA%\Factorio\mods`).
  The mod isn't on the mod portal, so "sync mods with server" can't download it. Copy the zip by hand, or on Linux
  run `scripts/install-client-mod.sh --zip` with Factorio closed. Restart Factorio after changing mods.
- If you change the mod, bump `version` in `mod/claude-crew/info.json` before redistributing. Two different zips
  with the same version make clients fail with a mod mismatch.
- **Back up the save first.** Adding the mod and letting it run writes its state into the save. Removing the mod
  later is safe (its characters disappear), but keep the backup.

## 2. Enable RCON on the server

The orchestrator talks to the game only through RCON (TCP). Start the server with:

```
--rcon-port 27015 --rcon-password <a long random string>
```

(Host panels usually have RCON port/password fields.) RCON gives full control of the game, so **don't expose it
to the internet**. Run the orchestrator on the server box (host `127.0.0.1`), or reach it over a VPN or an SSH
tunnel: `ssh -N -L 27015:127.0.0.1:27015 user@server`.

Never type `/c` or `/sc` console commands in a save you care about: they disable achievements for that save
permanently. Nothing in the crew needs them. (`scripts/rc.py --raw` sends raw commands; avoid it on real saves.)

## 3. Run the orchestrator

On the machine that runs it (Linux or macOS, Python 3.11+, [uv](https://docs.astral.sh/uv/)):

```bash
uv venv && uv pip install -e .        # add '.[openai]' for DeepSeek and other OpenAI-compatible models
cp crew.example.toml crew.toml        # then edit it, see below
claude login                          # backend "claude-code" uses this machine's Claude Code login
.venv/bin/crew status                 # checks the RCON link and the mod: should answer, with no agents yet
.venv/bin/crew up                     # agents spawn and say hello in chat
```

In `crew.toml`:

- `[server]`: `host`, `rcon_port`, and `rcon_password` (or `rcon_password_file`, or the
  `FACTORIO_RCON_PASSWORD` env var).
- Top-level keys go *above* `[server]`: `spawn_near = "<your player name>"` makes agents spawn next to you;
  `state_dir = "~/.local/state/claude-crew-<world>"` keeps one board/notes per world;
  `starter_kit = false` if they shouldn't get the freeplay starting items.
- `[foreman]` (Opus) and `[defaults]` (Sonnet workers) pick the models. `[[agent]]` blocks add workers; two to
  four is a good range.
- `[budget] usd_per_hour` caps spend across all models; agents pause when it's hit. On a Claude subscription
  the cost is notional, but the subscription's own usage limits apply, and Opus burns them fastest.

API keys never go in `crew.toml`. For the API backend set `ANTHROPIC_API_KEY`; for OpenAI-compatible providers put
`KEY=VALUE` lines in `~/.config/claude-crew/env` (chmod 600).

To keep it running: `systemd/claude-crew.service` is a user unit (edit its paths, then
`systemctl --user enable --now claude-crew.service`). `logs/live.log` is the log; the board, notes and every
agent transcript are in `state_dir`.

## 4. Play

| In game chat | What happens |
|---|---|
| `@all our iron is the bottleneck, fix it` | the foreman diagnoses, posts board tasks with checks, assigns workers |
| `@foreman what are you working on?` | the foreman answers |
| `@claude-2 build a lab row next to the labs` | one worker takes it directly |
| `@claude-1 come here` / `follow me` / `stop` | instant, no model call |

The **Crew panel** (top left, `/crew-panel`) shows each agent's job. Tasks with a `done_when` check close only when
the game confirms the result held for 2 minutes.

Things to know:
- **Biters:** agents walk into nests and die (5 deaths in 30 min on a biters-on world). Each death leaves a corpse
  with their inventory. Tell the foreman where it's safe, or play peaceful.
- Agents obey player rules: they walk, need items, craft in real time, reach only nearby. They won't pick up things
  a human built.
- Stopping the orchestrator leaves the characters standing in the world; `crew despawn <name>` removes one.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `crew status` times out / connection refused | RCON port/password wrong, server not started with `--rcon-port`, or a firewall |
| `unknown command /crew` | mod not loaded on the server: check `mods/mod-list.json` and the server log |
| Clients can't join: mod mismatch | someone has a different `claude-crew` zip; redistribute the same `dist/` file |
| Agents freeze, log says `SUBSCRIPTION USAGE LIMIT` | Claude usage limit hit; wait, use fewer agents, or move workers to another backend |
| Agents paused, log says spend cap | `[budget] usd_per_hour` reached; raise it or wait |
