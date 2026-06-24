#!/usr/bin/env bash
# One-time backend provisioning on a fresh Ubuntu/Debian VPS.
# Run as root (or with sudo). Edit the variables below first.
set -euo pipefail

APP_DIR=/srv/loko/backend
REPO_URL="https://github.com/<you>/loko.git"   # or rsync your code to $APP_DIR

echo "▸ System packages…"
apt-get update
apt-get install -y python3-venv python3-pip postgresql nginx-light curl git

echo "▸ App user + directory…"
id loko &>/dev/null || useradd -m -s /bin/bash loko
mkdir -p "$APP_DIR"

echo "▸ Code…  (git clone or rsync your project into $APP_DIR)"
# git clone "$REPO_URL" /srv/loko

echo "▸ Python venv + deps…"
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "▸ Django migrate + collectstatic + seed…"
cd "$APP_DIR"
set -a; source "$APP_DIR/.env"; set +a
"$APP_DIR/venv/bin/python" manage.py migrate
"$APP_DIR/venv/bin/python" manage.py collectstatic --noinput
"$APP_DIR/venv/bin/python" manage.py seed

echo "▸ Install cloudflared…"
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
  -o /usr/local/bin/cloudflared && chmod +x /usr/local/bin/cloudflared

cat <<'NEXT'

NEXT STEPS (manual):
  1. cp deploy/loko-backend.service /etc/systemd/system/ && systemctl enable --now loko-backend
  2. cloudflared tunnel login && cloudflared tunnel create loko-api
  3. cp deploy/cloudflared-config.yml /etc/cloudflared/config.yml  (edit TUNNEL_ID)
  4. cloudflared tunnel route dns loko-api api.loko.kg
  5. cloudflared service install && systemctl enable --now cloudflared
Backend is now live at https://api.loko.kg behind Cloudflare.
NEXT
