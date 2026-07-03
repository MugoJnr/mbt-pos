#!/usr/bin/env bash
# One-time Cloudflare tunnel setup for a headless Linux server.
# Requires CLOUDFLARE_API_TOKEN or config/deploy.local.json with cloudflare_api_token.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SUBDOMAIN="${MBT_SUBDOMAIN:-trading}"
SHOP_NAME="${MBT_SHOP_NAME:-Trading}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --subdomain) SUBDOMAIN="$2"; shift 2 ;;
    --shop) SHOP_NAME="$2"; shift 2 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

cd "$APP_DIR"

if [[ -z "${CLOUDFLARE_API_TOKEN:-}" ]] && [[ ! -f config/deploy.local.json ]]; then
  echo "ERROR: Set CLOUDFLARE_API_TOKEN or create config/deploy.local.json"
    echo "  dash.cloudflare.com → My Profile → API Tokens"
    echo "  Permissions: Account → Cloudflare Tunnel → Edit"
    echo "               Zone  → DNS → Edit (mugobyte.com)"
    exit 1
fi

VENV_PY="$APP_DIR/venv/bin/python"
if [[ ! -x "$VENV_PY" ]]; then
  VENV_PY="python3"
fi

export PYTHONPATH="$APP_DIR"
"$VENV_PY" -c "
import sys
sys.path.insert(0, r'$APP_DIR')
from backend.cloudflare_setup import CloudflareSetup

def log(level, msg):
    print(f'[{level}] {msg}')

result = CloudflareSetup(
    '$SHOP_NAME',
    subdomain='$SUBDOMAIN',
    log_callback=log,
).run()
if not result.get('ok'):
    sys.exit(1)
print()
print('Remote URL: https://' + result['domain'])
"
