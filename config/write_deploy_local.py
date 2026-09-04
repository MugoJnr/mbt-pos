"""Merge CLOUDFLARE_API_TOKEN env into config/deploy.local.json before BUILD."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOCAL = ROOT / 'deploy.local.json'


def say(text: str) -> None:
    """Print without ever aborting the build on a non-ANSI glyph.

    The build console runs cp1252, so an arrow or ellipsis in a token
    validation message used to raise UnicodeEncodeError mid-build.
    """
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, 'encoding', None) or 'ascii'
        print(text.encode(encoding, 'replace').decode(encoding, 'replace'))


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
            say('  [ERROR] CLOUDFLARE_API_TOKEN is a tunnel connector token '
                '— use a management cfat_… token')
            return 1
        data['cloudflare_api_token'] = tok
        LOCAL.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
        say(f'  [OK] cloudflare_api_token saved to {LOCAL.name}')
    sys.path.insert(0, str(ROOT.parent))
    from config.deploy import verify_cloudflare_token
    ok, msg = verify_cloudflare_token()
    say(f'  [OK] {msg}' if ok else f'  [WARN] {msg}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
