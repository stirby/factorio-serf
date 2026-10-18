# Claude Advisor for Factorio 2.0

Mods can't do network I/O, so it's two halves:

- **Mod** (`claude-advisor_0.1.0.zip`): every game minute writes `script-output/claude-advisor/state.json` (research, entity counts, all-time item totals, alerts, inventories, evolution). Chat lines go to `chat.jsonl`; messages starting with `@claude` trigger a fresh snapshot. Registers `/claude_say` (RCON/admin only) to print to chat.
- **Bridge** (`advisor.py`): tails those files, diffs totals into items/min plus deficits, asks Claude. Answers `@claude` questions immediately; every 5 min does a passive check and stays silent unless something is actionable.

## Setup (Linux)

1. Drop the zip in `~/.factorio/mods/`.
2. Launch Factorio with `--rcon-port 27015 --rcon-password <pw>` (Steam launch options).
3. Load your save via **Multiplayer → Host saved game** (RCON is only live when hosting; can be private, no other players needed). If RCON still doesn't answer, run a local headless server with the same flags and connect to it.
4. Run the bridge:
   ```
   pip install anthropic
   export ANTHROPIC_API_KEY=... FACTORIO_RCON_PASSWORD=<pw>
   python3 advisor.py
   ```

Steam/Flatpak installs may put user data elsewhere; set `FACTORIO_SCRIPT_OUTPUT` if `~/.factorio/script-output` is wrong.

## Knobs

`CLAUDE_MODEL` (default `claude-sonnet-5-5`), `ADVISE_EVERY_SEC` (300). Snapshot interval is `SNAPSHOT_TICKS` in `control.lua`. Cost per call is small: state is summarized to top-25 rates, deficits and counts.
