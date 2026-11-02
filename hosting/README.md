# Hosting a shared world

Everything a Linux server (Ubuntu 24.04 or 26.04; we use an OVH B3-16) needs to host one Factorio 2.1 world with the
serf mod, and what a Claude Code session on that server needs to look after it.

- `server/`
  - `setup.sh`: one-time setup, safe to run again: Factorio headless, keys-only SSH, a firewall that lets in only SSH
    and the game, the `factorio` service, backups every 6 hours, the `serf-flags` service.
  - `factorio-ctl`: status, log, save, start/stop, backup, install a world or mods.
  - `factorio-rcon`: send one command to the running game.
  - `serf-flags`: saves a player's `!` line (with the world, who was online and what each serf was doing) in
    `/opt/factorio/flags/` for the serf's developers, and thanks them in chat.
  - `CLAUDE.md`: what the server's Claude reads first (the layout, the tools, the rules).
  - `claude-settings.json`: lets that Claude run the safe commands without asking.
- `pc/push-mods.py`: run on your PC: sends the mods you play with (and a folder mod such as the serf, zipped).

The server runs no AI: every player who wants a serf runs the serf app on their own computer with their own Claude
login (see the main README). The server needs only the mod.

## Set up a server

Below, the server is `ubuntu@SERVER` and your key `~/.ssh/KEY`.

1. On the server: get this repo and run the setup (pick a game password, or leave it out for a random one):
   ```
   git clone https://github.com/stirby/factorio-serf ~/factorio-serf
   sudo GAME_PASSWORD='pick-one' ADMINS='yourname' bash ~/factorio-serf/hosting/server/setup.sh
   ```
   It prints the game password. Log out and back in.
2. On the server: give its Claude the notes:
   ```
   mkdir -p ~/.claude
   cp ~/factorio-serf/hosting/server/CLAUDE.md ~/.claude/CLAUDE.md
   cp ~/factorio-serf/hosting/server/claude-settings.json ~/.claude/settings.json
   ```
3. On your PC, with your game on the same Factorio version and the world you want to host saved:
   ```
   python3 pc/push-mods.py ubuntu@SERVER --key ~/.ssh/KEY
   scp -i ~/.ssh/KEY ~/.factorio/saves/"My world.zip" ubuntu@SERVER:~/incoming/
   ```
4. On the server: mods first, then the world:
   ```
   sudo factorio-ctl install-mods ~/incoming/mods-<time>      # the folder push-mods printed
   sudo factorio-ctl install-save ~/incoming/"My world.zip"
   factorio-ctl status
   ```
5. Players join with Multiplayer, Connect to address, `SERVER` and the game password.

## Update

`cd ~/factorio-serf && git pull`, then `sudo bash hosting/server/setup.sh` (installs the newer tools; keeps the world,
mods, settings and passwords) and copy `CLAUDE.md` again. The world's mods change only through `install-mods`, and
must match what players get from the mod portal.
