# Working on factorio-serf

The serf is an AI teammate for Factorio 2.1. `jev/` is the app (Python; the name is historical), `mod/factorio-serf`
is the mod (Lua), `hosting/` is the kit for the shared server, and `docs/DESIGN.md` explains how the parts fit.
Development happens on the OVH server (`~/factorio-serf`); the server's own notes are `hosting/server/CLAUDE.md`.

## What good looks like
- The goal is a helpful teammate in the owner's own world. It replies in seconds, does what the player meant, says
  what it's doing, stops when told, and works on any planet.
- Judge changes on real requests from live play (`bench/live_cases`, `/opt/factorio/flags`), not on the benchmark
  ladder or long campaigns. Don't start big test runs (campaigns, ladders, batches) unless asked.
- Commit and push to GitHub (`git push origin main`) once a change is tested. No need to ask.

## How the owner works
- Work independently. They've said so in capitals: don't ask them to approve routine commands. Ask only about what's
  really theirs to decide, like something public or hard to undo.
- Never overwrite one of their saves. Work on a clone of the world (Oct 25: a test copy got saved over a solo save).
- Biters stay off in tests and benches. In live sessions, follow what they last said.
- Be straight about what was and wasn't tested. Never print keys or tokens.
- Read `media/review/user-feedback.md` before changing how the serf behaves. It has what they've asked for and
  complained about, in their own words, ranked by how much it mattered. `media/review/logs-review.md` has the defects
  found in the logs of the Oct 30 session.

## Testing
- `.venv/bin/python tests/test_units.py`: offline, seconds. Run it after every app change.
- `.venv/bin/python tests/test_chat_replay.py`: chat regressions, offline.
- `nice -n 10 .venv/bin/python tests/live_checks.py --instance 61 --only a,b`: in-game checks on a test slot. The
  check names are in the dict at the bottom of the file, and with no `--only` it runs all of them (150 checks).
- `tests/byo_flow.py`: the bring-your-own-serf flow. `tests/gui_smoke.lua`: panel GUI code off-game.
- Test slots are 60-99 and use `server/factorio`, never `/opt/factorio`. Run at most two at a time, and never send
  `/c` to the shared world.
- Each live check sets up its own start: teleport the serf there. Earlier checks leave it far away (`fetchfar`
  leaves it 600 tiles off), and a check that relies on where the serf stands passes alone but fails in a full run.
- Before blaming the serf, check the fixture with a fault-free dry run.

## Mod releases
- The shared world runs exactly the version on the mod portal, because players' games download it from there.
- `scripts/publish_mod.py` builds `dist/factorio-serf_<version>.zip`. With `--send` it uploads, which needs a portal
  API key. Until the owner has one, they upload by hand. Also attach the zip to a GitHub pre-release (`mod-<version>`).
- The app goes live before the mod does. A step that needs new mod behaviour checks the mod version (ping) and
  refuses on an older mod.
- Keep the mod loadable at every commit (`luac -p`), since players load it.

## Gotchas
- Never `pkill` with a pattern that your own shell's command line also matches. Kill specific PIDs
  (`pgrep -f "bin/x64/[f]actorio -c <dir>"`).
- Stopping a background task kills everything it started, `setsid nohup` children included.
- Starting a run kills whatever server holds its slot, so two runs must never share slots.
- Don't `git stash`. Runs write tracked files (`bench/results.jsonl`, `library/*.jsonl`, `library/playbooks.json`).
- After fixing a harness bug, grep `library/lessons.jsonl` for planner lessons that route around it. Move the
  false ones to `lessons_retired.jsonl` with a reason, or they steer every later plan away from the fixed tool.
- For bug hunting, mine `actor.jsonl` (kind `act`: op, ok, msg, secs) for the time lost per failure message.
  Project and strategist journals name failures in plain words.
- Factorio facts that cost time:
  - A fluid segment longer than 320 tiles fills but delivers nothing.
  - A script character gets no chunk generation; the mod generates chunks around the serf.
  - `character_mining_progress` goes back to 0 after every ore unit.
  - Stopping a server saves over the file it loaded.

## Where things are
- `bench/live_cases`: cases from the owner's live sessions (Oct 25 to 30), each with its save and logs.
- `media/`: review reports (`media/review`), the join page source (`media/join`), and report and dashboard sources.
- `bench/campaigns`: the 2.0-era campaigns (journals and saves).
- `~/pc-archive`: what came over from the owner's PC: serf app logs, old bench runs, and save backups.
- `!` flags from the shared world are in `/opt/factorio/flags/<time>-<player>/` (world.zip and flag.json).
- The friends' join page is https://claude.ai/artifact/7Y4BokTpcA3rgKG2Wj4EDA (private; no password on it).

## Where things stand (2026-11-02)
- **Mod:** 0.4.1 is built and on a GitHub pre-release (`mod-0.4.1`). The portal and the shared world are still on
  0.4.0, because the owner wants one more live test before uploading it.
- **After the owner uploads 0.4.1:** update the shared world. Refuse if anyone is online, back up, then run
  `sudo factorio-ctl install-mods <dir>` with the 0.4.1 zip plus the current mods and mod list. Check the checksum
  matches the portal's.
- **Look at first in the next live test:** robots bringing a build's items (`Runner.robots_bring`). The owner's top
  complaint was the serf hand-crafting what the logistic network holds. The live checks pass, but it hasn't been seen
  in a real game yet. Spare items going to storage chests (`tidy`) has no check of its own.
- **Known test failure:** `pipes` ("the audit traces both dry machines' lines") fails in full `live_checks` runs and
  passes alone. The cause isn't diagnosed.
- **Waiting on the owner:**
  - The Todo List interface: an upstream PR from `stirby/factorio-todo-list`, or publishing the fork under another
    name.
  - Whether to open one password-protected test port so they can join a test slot from their own game.
  - `gh auth login` on the server. It can pull from GitHub but can't push until then.
- **Asked for, not started:** combat, tank and danger awareness; the wiki handing over blueprints; physical
  build-area claims (only planner hints exist).
