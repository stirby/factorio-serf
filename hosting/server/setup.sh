#!/usr/bin/env bash
# One-time setup of the shared Factorio server on a fresh Ubuntu 24.04 or 26.04 box. Safe to run again (it keeps saves, mods,
# settings and passwords that are already there). Run from the kit's server/ folder:
#
#     sudo GAME_PASSWORD='something' bash setup.sh        # or leave GAME_PASSWORD out for a random one
#
# FACTORIO_VERSION picks the game version (default below). Everyone who joins must run exactly this version.
set -euo pipefail

VERSION=${FACTORIO_VERSION:-2.1.24}
ADMINS=${ADMINS:-otterplex}          # Factorio names, comma-separated
F=/opt/factorio
KIT=$(cd "$(dirname "$0")" && pwd)
ME=${SUDO_USER:-ubuntu}

[ "$(id -u)" = 0 ] || { echo "run it with sudo" >&2; exit 1; }

echo "== packages"
apt-get update -q
DEBIAN_FRONTEND=noninteractive apt-get install -yq tmux jq unzip xz-utils rsync htop ufw unattended-upgrades curl python3
# security updates install themselves (Ubuntu's default list: security fixes only)
printf 'APT::Periodic::Update-Package-Lists "1";\nAPT::Periodic::Unattended-Upgrade "1";\n' > /etc/apt/apt.conf.d/20auto-upgrades

echo "== ssh: keys only, no root login"
cat > /etc/ssh/sshd_config.d/10-keys-only.conf <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
EOF
sshd -t && systemctl reload ssh

echo "== firewall: ssh and the game only"
ufw allow OpenSSH >/dev/null      # first, so enabling the firewall can't lock you out
ufw allow 34197/udp >/dev/null
ufw --force enable >/dev/null
ufw status | sed -n '1,8p'

echo "== factorio user and folders"
id factorio >/dev/null 2>&1 || useradd --system --home-dir "$F" --shell /usr/sbin/nologin factorio
usermod -aG factorio,systemd-journal "$ME"  # systemd-journal: factorio-ctl log/save read the game log
mkdir -p "$F"/{saves,mods,config,backups,flags}
install -d -o "$ME" -g "$ME" "/home/$ME/incoming"

echo "== factorio $VERSION"
have=$("$F"/bin/x64/factorio --version 2>/dev/null | sed -n 's/^Version: \([0-9.]*\).*/\1/p' || true)
if [ "$have" != "$VERSION" ]; then
  if systemctl is-active --quiet factorio; then
    echo "the server is running $have; stop it first (sudo factorio-ctl stop), then run this again" >&2; exit 1
  fi
  tmp=$(mktemp -d)
  curl -fsSL -o "$tmp/factorio.tar.xz" "https://www.factorio.com/get-download/$VERSION/headless/linux64"
  tar -xJf "$tmp/factorio.tar.xz" -C "$tmp"
  cp -a "$tmp"/factorio/. "$F"/            # game files only (bin, data); saves, mods and config are left alone
  rm -rf "$tmp"
fi
"$F"/bin/x64/factorio --version | head -1

echo "== settings"
if [ ! -f "$F/config/server-settings.json" ]; then
  pw=${GAME_PASSWORD:-$(python3 -c 'import secrets; print(secrets.token_urlsafe(9))')}
  jq --arg pw "$pw" '.game_password = $pw' "$KIT/server-settings.json" > "$F/config/server-settings.json"
fi
[ -f "$F/config/server-adminlist.json" ] || jq -n --arg a "$ADMINS" '$a | split(",")' > "$F/config/server-adminlist.json"
[ -f "$F/config/rcon-password" ] || python3 -c 'import secrets; print(secrets.token_hex(16))' > "$F/config/rcon-password"
chown -R factorio:factorio "$F"
chmod 2775 "$F" "$F"/{saves,mods,config,backups,flags}
chmod 640 "$F/config/rcon-password" "$F/config/server-settings.json"

echo "== tools and service"
install -m 755 "$KIT/factorio-ctl" "$KIT/factorio-rcon" "$KIT/serf-flags" /usr/local/bin/
install -m 644 "$KIT/factorio.service" "$KIT/serf-flags.service" /etc/systemd/system/
printf 'PATH=/usr/local/bin:/usr/bin:/bin\n15 */6 * * * root /usr/local/bin/factorio-ctl backup >/dev/null\n' > /etc/cron.d/factorio-backup
systemctl daemon-reload
systemctl enable factorio >/dev/null
systemctl enable --now serf-flags >/dev/null  # players' "!" notes -> $F/flags

echo
echo "Done. Game password: $(jq -r .game_password "$F/config/server-settings.json")"
echo "Admins: $(jq -r 'join(", ")' "$F/config/server-adminlist.json")"
echo "Log out and back in (for the factorio group), then send the world and mods from your PC (see README.md)."
