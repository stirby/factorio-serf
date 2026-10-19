# Factorio Serf

An AI teammate (a Claude agent) that plays Factorio 2.0 (Space Age) **as a player, next to you**, in single player
or multiplayer. You talk to it in game chat; it walks, mines, crafts and builds under the same rules you do, and
reports back.

It's called a **serf**. Everyone brings their own: start your game, run the `serf` app with your own Claude
login, type `/serf add`, and a fella just joins. (A multi-agent crew with an Opus foreman was built and paused:
[docs/crew-design.md](docs/crew-design.md).)

```
otterplex: /serf add
     serf: serf here (Sonnet 5.5). Ready to build with you, otterplex. Talk to me with @serf.
     serf: Nothing is researching and I have almost no inventory. I could (1) hand-bootstrap iron and copper
           smelting, (2) get the labs fed with red science, or (3) fix power. What do you want first?
otterplex: @serf add the iron patch I'm standing on, belt it to the train stop
```

## Quick start: a serf in your own game (no server)

1. Install the mod: copy `dist/factorio-serf_<version>.zip` (`scripts/package-mod.sh` builds it) into your Factorio
   `mods` folder and enable it. In multiplayer, everyone needs the same zip.
2. Start Factorio with the launch option `--enable-lua-udp 27200` (Steam: right-click Factorio → Properties →
   Launch options). That lets the mod talk to the app on your own computer; nothing leaves it.
3. Install the app and log in once (Python 3.11+):
   ```bash
   uv tool install git+https://github.com/stirby/factorio-serf    # or: pipx install git+...
   claude login        # Claude subscription (Claude Code), or: serf key   (an Anthropic API key)
   ```
4. Load a game, run `serf`, and type `/serf add` in game. Talk to it with `@serf ...`. `/serf remove` sends it
   away (you get its items), `/serf list` shows who's here.

Works in single player and as a client in someone else's multiplayer game: each player runs their own `serf`,
and each serf runs on its owner's login. Your serf waits in the save; run `serf` again and it picks up.
Server admins can turn player serfs off or cap them (mod settings), or host serfs for players without the app
([DEPLOY.md](DEPLOY.md)).

## How it works

```
Your game (single player or a multiplayer client), or a server
  factorio-serf mod (Lua): agent characters, job queue, pathfinding, observations, panel, /serf
        ▲  localhost UDP (your own `serf` app)  or  RCON (a server operator's `crew up`)
        ▼
orchestrator (Python): game link · chat router · task board · one Claude loop per agent
        ▲  tools: look, map, find, inspect, act, say, board, notes, status ...
        ▼
Claude: Agent SDK on your Claude login, or the API with a key. The model is set per agent.
```

- **Agents are real `character` entities** driven by script, not network clients (Factorio multiplayer is
  lockstep, so a bot client would have to run the whole simulation). To you they look and act like players.
- **Legit by default:** they pathfind and walk, hand-mine at normal speed, need the items in their inventory,
  craft in real time, and must be within reach. A `factorio-serf-cheat` map setting switches to teleport and
  instant crafting.
- **How the app talks to the game:** mods can't make web requests, so the model runs in a small app on your
  computer. Factorio 2.0 lets a mod exchange UDP packets with localhost (`--enable-lua-udp`); an incoming packet
  becomes an input action, so in multiplayer every machine runs the request the same way and only yours sends
  the reply. Servers can also use RCON, which works on any headless server.
- **The mod does the heavy lifting:** multi-step jobs ("walk there and mine 20 iron"), A* belt/pipe/pole
  routing, ASCII maps and compact observations. Each RCON round trip stays small and each tool call does a lot.

## Quick start (local)

```bash
uv venv && uv pip install -e .              # Python 3.11+
scripts/server.sh new my-map                # fresh map (Space Age if the headless build includes it)
scripts/server.sh start my-map              # headless server on 127.0.0.1, RCON on 27015
cp crew.example.toml crew.toml              # pick agents, models, personalities
.venv/bin/crew up                           # agents spawn and say hello in chat
```

Then join from your game: run `scripts/install-client-mod.sh` once (with Factorio closed), start Factorio, and
go to **Multiplayer → Connect to address → `127.0.0.1`**. Allow the mod sync when it asks. The headless server
must be the same Factorio version as your client (`scripts/server.sh` expects it in `server/factorio`).

Without a client you can still drive it: `crew say "@claude-1 build some iron smelting"`.

## Playing with friends

**Full guide for a dedicated server: [DEPLOY.md](DEPLOY.md).**


The crew attaches to any game where the host runs the mod and gives you RCON access:

- **Dedicated server:** start it with `--rcon-port 27015 --rcon-password ...`, add `factorio-serf` to its mods,
  then `crew up --server host:27015 --password ...`.
- **Hosting from your own client:** add `--rcon-port 27015 --rcon-password ...` to Factorio's launch options
  (Steam → Properties), then **Multiplayer → Host saved game**. RCON only listens while hosting.
- Every human player needs the mod, because Factorio requires everyone to run the same mods.

## Talking to the crew

| You say | What happens |
|---|---|
| `@claude-1 put a furnace line on that iron` | wakes claude-1 |
| `@all ...` / `@crew ...` | every agent (or the foreman, if you run a crew) |
| `claude-2, how much copper are we making?` | bare names work too |
| `@claude-1 come here` / `follow me` | starts moving right away, no model call; the agent then acknowledges |
| `@claude-2 stop` | cancels its jobs right away |
| other chat | agents see it on their next turn but don't wake |

The **Crew panel** (top left; `/crew-panel` toggles it) shows each agent's current job and status line.

## Configuration (`crew.toml`)

```toml
[defaults]
backend = "claude-code"     # your Claude Code login (subscription), or "api" (ANTHROPIC_API_KEY)
model = "claude-sonnet-5-5" # for a demo: "claude-opus-5-5", or `crew up --model claude-opus-5-5`

[[agent]]                   # one player; add [foreman] and more agents for a crew (docs/crew-design.md)
name = "claude-1"
personality = "Calm, dry humor, likes tidy layouts."
```

`crew.toml` is watched while the crew runs: change a model or a limit, or add or remove an `[[agent]]`, and it
applies within a few seconds without a restart. A backend change still needs one. Removed agents go
"off duty" and their characters stay in the game.

Each agent has `max_turns_per_hour` and `max_autonomous_turns` limits, so it can't run away with your usage.
State (board, notes, transcripts) lives in `~/.local/state/factorio-serf/`.

## Running unattended

```bash
ln -s $PWD/systemd/*.service $PWD/systemd/*.timer ~/.config/systemd/user/ && systemctl --user daemon-reload
systemctl --user enable --now claude-crew.service claude-crew-snapshot.timer   # restarts on crash; logs to logs/live.log
scripts/snapshot.py my-label     # save a named stage now; snapshots/manifest.jsonl records what the base had
```

Tests always run with biters off (`crew/peace.py`, applied by `scripts/server.sh` and `scripts/instance.py`
on start; never run those on a world people play). Peaceful mode on a real game, if you want it: `scripts/rc.py eval '{"code":"game.surfaces.nauvis.peaceful_mode=true return 1"}'`.

## Development

- `tests/smoke.py`: 56 checks of every mod action against a running server, no LLM involved
  (run it on a scratch save, because it resets research).
- `scripts/rc.py <op> '<json>'`: call the mod API directly. `scripts/server.sh log` shows the server log.
- Gotcha we hit: hand-crafting by a character with no player doesn't count toward production stats or 2.0
  trigger techs. The mod records agent crafts, builds and mining itself (`scripts/triggers.lua`).

## Prior art

[Factorio Learning Environment](https://github.com/JackHopkins/factorio-learning-environment) (research
benchmark; agents write Python against a game API; takes over the whole surface),
[AI Companion](https://mods.factorio.com/mod/ai-companion) (closest: legit companions via Claude Code and MCP),
[AI Player v3](https://mods.factorio.com/mod/ai-player-v3) / [AI Coworker](https://mods.factorio.com/mod/ai-coworker)
(skills-based; agents teleport). Factorio Serf is aimed at several agents playing *with* humans in a shared
multiplayer game, commanded from chat.

## License

MIT ([LICENSE](LICENSE)). Factorio is a trademark of Wube Software; this is an unofficial fan project. Claude is a
trademark of Anthropic; the serf runs on your own Claude login or API key.
