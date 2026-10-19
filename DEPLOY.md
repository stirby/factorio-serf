# Deploying Factorio Serf to a dedicated server

For running it on a dedicated server. (Just want a serf in your own game? See the README quick start: no server,
no RCON, each player runs the `serf` app on their own computer and types `/serf add`.) Two pieces:

1. **The mod** (`mod/factorio-serf`) runs inside Factorio, on the server *and* on every player's client.
2. **The orchestrator** (`crew/`, the `crew` command) runs on any machine that can reach the server's RCON port.
   It runs the model behind each agent character. The default is one agent per person, on that person's own
   Claude login; a multi-agent crew with an Opus foreman is optional (`docs/crew-design.md`).

Tested on Factorio **2.0.77** with Space Age, alongside 18 other mods (Quality, Space Age, and QoL mods). The mod
declares `factorio_version = "2.0"`; newer 2.0.x builds should work.

## 1. Build and install the mod

```bash
scripts/package-mod.sh                       # -> dist/factorio-serf_<version>.zip
scripts/package-mod.sh /path/to/server/mods  # or build and copy straight into the server's mods folder
```

- Put the zip in the server's `mods/` folder and add `{"name": "factorio-serf", "enabled": true}` to its
  `mods/mod-list.json` (or the host panel's mod list).
- **Every player needs the same zip** in their own mods folder (`~/.factorio/mods`, `%APPDATA%\Factorio\mods`).
  The mod isn't on the mod portal, so "sync mods with server" can't download it. Copy the zip by hand, or on Linux
  run `scripts/install-client-mod.sh --zip` with Factorio closed. Restart Factorio after changing mods.
- If you change the mod, bump `version` in `mod/factorio-serf/info.json` before redistributing. Two different zips
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
  `state_dir = "~/.local/state/factorio-serf-<world>"` keeps one board/notes per world;
  `starter_kit = false` if they shouldn't get the freeplay starting items.
- `[defaults]` picks the model (Sonnet; Opus is slower and pricier). One `[[agent]]` is the default.
- Several orchestrators can share a server (mod 0.2.0+): each reads chat from its own cursor and gets results only
  for its own agents. Give each `crew up` its own name with `[server] client = "..."` (default `"rcon"`).
- `[budget] usd_per_hour` caps spend across all models; agents pause when it's hit. On a Claude subscription
  the cost is notional, but the subscription's own usage limits apply, and Opus burns them fastest.

API keys never go in `crew.toml`. For the API backend set `ANTHROPIC_API_KEY`; for OpenAI-compatible providers put
`KEY=VALUE` lines in `~/.config/factorio-serf/env` (chmod 600).

To keep it running: `systemd/claude-crew.service` is a user unit (edit its paths, then
`systemctl --user enable --now claude-crew.service`). `logs/live.log` is the log; the board, notes and every
agent transcript are in `state_dir`.

## Player serfs (`/serf add`)

With mod 0.2.0+, any player can type `/serf add`. That works when the player runs the `serf` app on their own
computer (Factorio started with `--enable-lua-udp 27200`; the serf runs on that player's own Claude login), or
when an operator's orchestrator hosts serfs: `crew up --host-serfs` (add `--join` to spawn nobody at start).
Hosted serfs run on the operator's login, one per player. `/serf remove` dismisses a serf (its items go to its
player); `/serf list` shows who's here.

Mod settings (Settings → Mod settings → Map): **Players can bring serfs** (on by default) and **Serfs per player**
(2). A player's app can only drive the serfs it owns; it can't run code or inject chat (RCON-only ops), and in
multiplayer serfs get no free starter items.

**Don't start a dedicated server with `--enable-lua-udp`.** On 2.0.77 a headless server crashes when a Lua UDP
packet arrives ("Trying to add invalid input action to the closure"). Players' own games are where UDP belongs.

## 4. Play

| In game chat | What happens |
|---|---|
| `/serf add` | your serf joins next to you (`/serf remove`, `/serf list`) |
| `@serf our iron is the bottleneck, fix it` | it diagnoses, plans and builds; reports back and asks what's next |
| `@serf what are you working on?` | it answers |
| `@all ...` | every agent hears it |
| `@serf come here` / `follow me` / `stop` | instant, no model call |

`@serf` always means *your* serf, whatever it's called (the second one in a world is `serf-<player>`).

The **panel** (top left, `/crew-panel`) shows each agent's job, its owner and what it's thinking. Tasks with a `done_when` check close only when
the game confirms the result held for 2 minutes.

Things to know:
- **Biters:** agents walk into nests and die (5 deaths in 30 min on a biters-on world). Each death leaves a corpse
  with their inventory. Tell it where it's safe, or play peaceful. (Don't use `scripts/server.sh` or
  `scripts/biters_off.py` on your real server: those are test tools that delete every enemy for good.)
- Agents obey player rules: they walk, need items, craft in real time, reach only nearby. They won't pick up things
  a human built.
- Stopping the orchestrator leaves the characters standing in the world; `crew despawn <name>` removes one.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `crew status` times out / connection refused | RCON port/password wrong, server not started with `--rcon-port`, or a firewall |
| `unknown command /crew` | mod not loaded on the server: check `mods/mod-list.json` and the server log |
| Clients can't join: mod mismatch | someone has a different `factorio-serf` zip; redistribute the same `dist/` file |
| Agents freeze, log says `SUBSCRIPTION USAGE LIMIT` | Claude usage limit hit; wait, use fewer agents, or move workers to another backend |
| Agents paused, log says spend cap | `[budget] usd_per_hour` reached; raise it or wait |
