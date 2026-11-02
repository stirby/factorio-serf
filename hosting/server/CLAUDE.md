# This server: otterplex's shared Factorio world

An OVH Public Cloud B3-16 (4 vCPU, 16 GB RAM, 100 GB NVMe, Ubuntu 24.04) that hosts one Factorio 2.1 Space Age
multiplayer world for otterplex (the owner) and a friend. You help run it. The owner prefers short, plain answers.

## Layout
| | |
|---|---|
| `/opt/factorio` | the game (headless, version in `setup.sh`), owned by user `factorio` |
| `/opt/factorio/saves` | the live world. The service loads the newest zip here |
| `/opt/factorio/mods` | mods: exactly the same zips as the players' games, sent from the owner's PC |
| `/opt/factorio/config` | `server-settings.json` (has the game password), `server-adminlist.json`, `rcon-password` |
| `/opt/factorio/backups` | `world-<time>.zip` every 6 hours (kept 60 days), plus old saves/mods from installs |
| `/opt/factorio/flags` | players' `!` notes: `<time>-<player>/flag.json` + `world.zip` (the `serf-flags` service) |
| `~/incoming` | where the owner's PC drops saves and mods |
| `~/factorio-serf` | a checkout of github.com/stirby/factorio-serf: the serf app and mod, and this kit in `hosting/` |
| `~/factorio-serf/server/factorio` | a separate Factorio 2.1.24 for the serf's test slots, with copies of test saves |

## The tools
- `factorio-ctl status | log [N] | say TEXT | save`: safe at any time.
- `sudo factorio-ctl start | stop | restart | backup`: stop saves the world first. Stop and restart refuse while
  anyone is online.
- `sudo factorio-ctl install-save FILE`: makes FILE the world. The old saves move to `backups/`.
- `sudo factorio-ctl install-mods DIR`: uses the mods in DIR, which `push-mods.py` sends from the PC.
- `factorio-rcon <command>`: one RCON command (`/players online`, `/server-save`, `/admins`, `/time`, `/version`).
  Plain text goes to the game chat.
- The service is `factorio`; its log is `journalctl -u factorio`. `serf-flags` (log: `journalctl -u serf-flags`)
  saves each `!` line players type, with the world at that moment.

## Rules
1. **Never overwrite or delete a world save or a backup.** Change the world only with `factorio-ctl install-save`,
   which keeps the old one. The world is the one thing here that can't be rebuilt.
2. **Don't kick players.** Stop or restart only when `factorio-ctl status` shows 0 online, unless the owner says so
   (then `FORCE=1`).
3. **No Lua commands on the world** (`/c`, `/sc`, `/command`, `/silent-command`, `/measured-command`) unless the owner
   asks for that exact thing. The first one turns achievements off for that save, for good.
4. **The server and every player must run the same Factorio version and the same mods**, down to the version number.
   Mods come from the owner's PC (`push-mods.py`). Don't download or update mods here on your own: a mod that differs
   from the players' blocks them from joining.
5. **Keep it closed.** RCON stays on `127.0.0.1`. The firewall (ufw) allows only 22/tcp and 34197/udp. SSH is keys
   only. Ask before changing any of that.
6. **Don't print secrets**: the RCON password, the game password (unless the owner asks for it), or anything in
   `~/.claude`.
7. **Ask before**: upgrading Factorio (both players have to upgrade too), changing `server-settings.json`, deleting
   anything, or installing packages. Say which `sudo` command you'll run and why before running it.
8. **Check after every change**: `factorio-ctl status`, and the log when something looks off. Don't say it worked
   without checking.

## How things are done
- **New world or a world from the PC:** the owner runs `scp -i ~/.ssh/slimebox <save>.zip ubuntu@<ip>:~/incoming/`.
  Then run `sudo factorio-ctl install-save ~/incoming/<save>.zip`. **Mods go in first:** a world loaded without its
  mods loses everything they added, and the next stop saves it that way (`install-save` refuses until mods are in).
- **Mods changed:** on the PC, `python3 push-mods.py ubuntu@<ip>`. Then
  `sudo factorio-ctl install-mods ~/incoming/mods-<time>`.
- **"Can't join":**
  - "mod mismatch": the mods differ; send them again from the PC.
  - "version mismatch": the game versions differ.
  - Timeout: check that the server is up and that ufw still allows 34197/udp.
  - Wrong password: it's `game_password` in `server-settings.json`.
- **Upgrading Factorio** (after the owner agrees and the players have the new version):
  `sudo factorio-ctl stop`, then `sudo FACTORIO_VERSION=<x.y.z> bash ~/factorio-serf/hosting/server/setup.sh`, then
  `sudo factorio-ctl start`. Saves made in a newer version can't go back to an older one, so back up first.
- **Slow game for everyone:** Factorio runs on mostly one core, and the server sets the pace. Look at CPU in `htop`.
  If the base outgrows this box, a higher-clock instance helps more than more cores.
- **Settings:**
  - `auto_pause` is on: the world stops when nobody is on.
  - Autosave runs every 10 minutes, into 10 slots.
  - `non_blocking_saving` is off, because the game calls it experimental and saves could be lost.

## Working on the serf here
This box is also where the serf is developed and tested (`~/factorio-serf`, its own `README.md` and `docs/`):
- Test servers (`scripts/instance.py`, slots 60-99) use `~/factorio-serf/server/factorio`, never `/opt/factorio`.
  They take copies of saves, listen on their own ports (game 34200+slot, RCON 27100+slot on 127.0.0.1) that the
  firewall keeps closed, and never touch the shared world. Run them with `nice -n 10` so the shared world keeps its
  CPU, and at most two at a time.
- A flag from `/opt/factorio/flags` becomes a test case by loading a copy of its `world.zip` in a test slot.
- `/c`-style commands are fine on test slots; never on the shared world.
- Push to GitHub when a change is tested; the owner wants every copy in sync.

## Background
- The world started on the owner's PC in 2.0.77. It was converted to 2.1 with the Dectorio fork `dectorio-fixes`; a
  one-time helper (`dectorio-wall-rename`) kept the renamed walls. The converted save doesn't need the helper.
- `factorio-serf` is the owner's own mod for an AI teammate (a "serf"), github.com/stirby/factorio-serf. The server
  has only the mod (sent by `push-mods.py` like the others), and it must be the same version as on the mod portal,
  where players' games get it when they join. **Players' serfs don't run here**: each player runs the serf app on
  their own PC with their own Claude login, and the mod lets each app drive only that player's serfs. Never put a
  player's Claude login or API key on this server. (The owner's own login here is for developing and testing the
  serf, on test slots.)
