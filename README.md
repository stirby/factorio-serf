# Claude Crew

Claude agents that play Factorio 2.0 (Space Age) **as players, alongside humans, in multiplayer**. You talk to
them in game chat; they walk, mine, craft and build under the same rules you do, split work on a shared task
board, and report back.

```
otterplex: @all get a starter base going: automated iron and copper, then red science
 claude-1: Plan: claude-2 takes iron (east patch [gps=75,58]), I take stone/copper/coal in the south.
 claude-2: First iron drill+furnace running at [gps=77,62]. I need stone and coal for more.
 claude-1: Added 4 more iron drill+furnace pairs at [gps=78,73]. Coal is the bottleneck: claude-2, please...
```

## How it works

```
Factorio server (headless, or a game hosted from a client)
  claude-crew mod (Lua): agent characters, job queue, pathfinding, observations, Crew panel
        ▲  RCON: /crew {json}  ⇄  rcon.print(json)
        ▼
crew orchestrator (Python): game link · chat router · task board · one Claude loop per agent
        ▲  tools: look, map, find, inspect, act, say, board, notes, status ...
        ▼
Claude: Agent SDK on your Claude login, or the API with a key. The model is set per agent.
```

- **Agents are real `character` entities** driven by script, not network clients (Factorio multiplayer is
  lockstep, so a bot client would have to run the whole simulation). To you they look and act like players.
- **Legit by default:** they pathfind and walk, hand-mine at normal speed, need the items in their inventory,
  craft in real time, and must be within reach. A `claude-crew-cheat` map setting switches to teleport and
  instant crafting.
- **Why RCON:** mods can't open sockets or read files. RCON works on any server, and its commands go through
  the game's deterministic input stream, so every player stays in sync.
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

- **Dedicated server:** start it with `--rcon-port 27015 --rcon-password ...`, add `claude-crew` to its mods,
  then `crew up --server host:27015 --password ...`.
- **Hosting from your own client:** add `--rcon-port 27015 --rcon-password ...` to Factorio's launch options
  (Steam → Properties), then **Multiplayer → Host saved game**. RCON only listens while hosting.
- Every human player needs the mod, because Factorio requires everyone to run the same mods.

## Talking to the crew

| You say | What happens |
|---|---|
| `@claude-1 put a furnace line on that iron` | wakes claude-1 |
| `@all ...` / `@crew ...` | the foreman (Opus, no character) plans, posts board tasks with checks, assigns workers |
| `@foreman ...` | ask the foreman directly |
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

[foreman]                   # the brain: no character, decides what the crew works on
model = "claude-opus-5-5"

[[agent]]
name = "claude-1"
focus = "production"
personality = "Calm, dry humor, likes tidy layouts."
```

`crew.toml` is watched while the crew runs: change a model or a limit, or add or remove an `[[agent]]`, and it
applies within a few seconds without a restart. A backend change still needs one. Removed agents go
"off duty" and their characters stay in the game.

Each agent has `max_turns_per_hour` and `max_autonomous_turns` limits, so it can't run away with your usage.
State (board, notes, transcripts) lives in `~/.local/state/claude-crew/`.

## Running unattended

```bash
ln -s $PWD/systemd/*.service $PWD/systemd/*.timer ~/.config/systemd/user/ && systemctl --user daemon-reload
systemctl --user enable --now claude-crew.service claude-crew-snapshot.timer   # restarts on crash; logs to logs/live.log
scripts/snapshot.py my-label     # save a named stage now; snapshots/manifest.jsonl records what the base had
```

Peaceful mode, if you want it: `scripts/rc.py eval '{"code":"game.surfaces.nauvis.peaceful_mode=true return 1"}'`.

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
(skills-based; agents teleport). Claude Crew is aimed at several agents playing *with* humans in a shared
multiplayer game, commanded from chat.
