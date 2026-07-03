#!/usr/bin/env bash
#
# MBT POS — Ubuntu cloud server installer (Oracle Cloud Free Tier, etc.)
#
# Hosts the web dashboard 24/7 at https://<subdomain>.mugobyte.com via Cloudflare Tunnel.
# Your shop PC is no longer required once this is running.
#
# BEFORE YOU RUN (on your Windows PC):
#   1. Copy this entire mbt_pos folder to the server (scp / zip / git).
#   2. Copy your shop database: data/mbt_pos.db (and config/ if you have custom settings).
#
# ON THE SERVER (Ubuntu 22.04+):
#   export CLOUDFLARE_API_TOKEN="your_token"   # required on headless servers
#   sudo bash deploy/ubuntu-server.sh --subdomain trading --shop "Trading"
#
# Optional:
#   --install-dir /opt/mbt-pos    (default)
#   --skip-cloudflare             (only install app + systemd; run setup-cloudflare.sh later)
#   --no-start                    (install but do not enable services yet)
#
set -euo pipefail

INSTALL_DIR="${MBT_INSTALL_DIR:-/opt/mbt-pos}"
SUBDOMAIN="${MBT_SUBDOMAIN:-trading}"
SHOP_NAME="${MBT_SHOP_NAME:-Trading}"
SERVICE_USER="mbt"
SKIP_CF=0
NO_START=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --subdomain) SUBDOMAIN="$2"; shift 2 ;;
    --shop) SHOP_NAME="$2"; shift 2 ;;
    --install-dir) INSTALL_DIR="$2"; shift 2 ;;
    --skip-cloudflare) SKIP_CF=1; shift ;;
    --no-start) NO_START=1; shift ;;
    -h|--help)
      sed -n '2,20p' "$0"
      exit 0
      ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo bash deploy/ubuntu-server.sh"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=============================================="
echo " MBT POS — Ubuntu cloud install"
echo " Install dir : $INSTALL_DIR"
echo " Remote URL  : https://${SUBDOMAIN}.mugobyte.com"
echo " Source      : $SRC_DIR"
echo "=============================================="
echo

echo "[1/8] Installing system packages..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip curl ca-certificates rsync

echo "[2/8] Creating service user '$SERVICE_USER'..."
if ! id "$SERVICE_USER" &>/dev/null; then
  useradd --system --home-dir "/home/$SERVICE_USER" --create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi

echo "[3/8] Copying application to $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"
rsync -a --delete \
  --exclude 'venv' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude 'build' \
  --exclude 'dist' \
  --exclude '.git' \
  --exclude 'cloudflared.exe' \
  "$SRC_DIR/" "$INSTALL_DIR/"

mkdir -p "$INSTALL_DIR/logs" "$INSTALL_DIR/data" "$INSTALL_DIR/config" "$INSTALL_DIR/exports"
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

echo "[4/8] Python virtualenv + web dependencies..."
sudo -u "$SERVICE_USER" python3 -m venv "$INSTALL_DIR/venv"
sudo -u "$SERVICE_USER" "$INSTALL_DIR/venv/bin/pip" install -q --upgrade pip
sudo -u "$SERVICE_USER" "$INSTALL_DIR/venv/bin/pip" install -q -r "$INSTALL_DIR/deploy/requirements-web.txt"

if [[ ! -f "$INSTALL_DIR/data/mbt_pos.db" ]]; then
  echo "WARN: No database at $INSTALL_DIR/data/mbt_pos.db"
  echo "      Copy your shop DB from Windows before going live, then restart:"
  echo "      sudo systemctl restart mbt-pos-web"
fi

echo "[5/8] Installing cloudflared..."
CF_BIN="/usr/local/bin/cloudflared"
if ! command -v cloudflared &>/dev/null && [[ ! -x "$CF_BIN" ]]; then
  ARCH="$(uname -m)"
  case "$ARCH" in
    x86_64|amd64) CF_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64" ;;
    aarch64|arm64) CF_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64" ;;
    *) echo "Unsupported architecture: $ARCH"; exit 1 ;;
  esac
  curl -fsSL "$CF_URL" -o "$CF_BIN"
  chmod 755 "$CF_BIN"
fi
# Also place a copy in the app dir for the tunnel service fallback
if [[ -x "$CF_BIN" ]]; then
  cp -f "$CF_BIN" "$INSTALL_DIR/cloudflared"
  chmod 755 "$INSTALL_DIR/cloudflared"
  chown "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR/cloudflared"
fi

echo "[6/8] Cloudflare tunnel setup..."
if [[ "$SKIP_CF" -eq 0 ]]; then
  if [[ -z "${CLOUDFLARE_API_TOKEN:-}" ]] && [[ ! -f "$INSTALL_DIR/config/deploy.local.json" ]]; then
    echo "ERROR: Cloudflare API token required on a headless server."
    echo
    echo "  export CLOUDFLARE_API_TOKEN='your_token'"
    echo "  sudo -E bash deploy/ubuntu-server.sh --subdomain $SUBDOMAIN"
    echo
    echo "Or create $INSTALL_DIR/config/deploy.local.json with:"
    echo '  { "cloudflare_api_token": "your_token" }'
    exit 1
  fi
  export MBT_SUBDOMAIN="$SUBDOMAIN"
  export MBT_SHOP_NAME="$SHOP_NAME"
  export PYTHONPATH="$INSTALL_DIR"
  if [[ -n "${CLOUDFLARE_API_TOKEN:-}" ]]; then
    sudo -u "$SERVICE_USER" env CLOUDFLARE_API_TOKEN="$CLOUDFLARE_API_TOKEN" \
      bash "$INSTALL_DIR/deploy/setup-cloudflare.sh" --subdomain "$SUBDOMAIN" --shop "$SHOP_NAME"
  else
    sudo -u "$SERVICE_USER" bash "$INSTALL_DIR/deploy/setup-cloudflare.sh" --subdomain "$SUBDOMAIN" --shop "$SHOP_NAME"
  fi
  chown -R "$SERVICE_USER:$SERVICE_USER" "/home/$SERVICE_USER/.cloudflared" 2>/dev/null || true
else
  echo "Skipped (--skip-cloudflare). Run later:"
  echo "  sudo -u $SERVICE_USER bash $INSTALL_DIR/deploy/setup-cloudflare.sh --subdomain $SUBDOMAIN"
fi

echo "[7/8] Installing systemd services..."
sed "s|/opt/mbt-pos|$INSTALL_DIR|g" "$INSTALL_DIR/deploy/mbt-pos-web.service" \
  > /etc/systemd/system/mbt-pos-web.service
sed "s|/opt/mbt-pos|$INSTALL_DIR|g; s|/home/mbt|/home/$SERVICE_USER|g" \
  "$INSTALL_DIR/deploy/mbt-pos-tunnel.service" \
  > /etc/systemd/system/mbt-pos-tunnel.service
systemctl daemon-reload

echo "[8/8] Starting services..."
if [[ "$NO_START" -eq 0 ]]; then
  systemctl enable mbt-pos-web mbt-pos-tunnel
  systemctl restart mbt-pos-web
  sleep 3
  if [[ "$SKIP_CF" -eq 0 ]]; then
    systemctl restart mbt-pos-tunnel
  fi
fi

echo
echo "=============================================="
echo " DONE"
echo "=============================================="
echo " Remote : https://${SUBDOMAIN}.mugobyte.com"
echo " Logs   : $INSTALL_DIR/logs/"
echo
echo " Useful commands:"
echo "   systemctl status mbt-pos-web mbt-pos-tunnel"
echo "   journalctl -u mbt-pos-web -f"
echo "   curl -s http://127.0.0.1:5050/api/health"
echo
if [[ "$SKIP_CF" -eq 0 ]]; then
  echo " DNS may take 2–5 minutes. Then open https://${SUBDOMAIN}.mugobyte.com"
fi
echo
