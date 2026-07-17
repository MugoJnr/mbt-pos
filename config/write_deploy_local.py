"""Merge CLOUDFLARE_API_TOKEN env into config/deploy.local.json before BUILD."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOCAL = ROOT / 'deploy.local.json'

def main() -> int:
    data = {}
    if LOCAL.is_file():
        try:
            data = json.loads(LOCAL.read_text(encoding='utf-8'))
        except Exception:
            pass
    tok = os.environ.get('CLOUDFLARE_API_TOKEN', '').strip()
    if tok:
        if tok.lower().startswith('cfut_') or tok.startswith('eyJ'):
            print('  [ERROR] CLOUDFLARE_API_TOKEN is a tunnel connector token — use a management cfat_… token')
            return 1
        data['cloudflare_api_token'] = tok
        LOCAL.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
        print(f'  [OK] cloudflare_api_token saved to {LOCAL.name}')
    sys.path.insert(0, str(ROOT.parent))
    from config.deploy import verify_cloudflare_token
    ok, msg = verify_cloudflare_token()
    if ok:
        print(f'  [OK] {msg}')
        return 0
    print(f'  [WARN] {msg}')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
