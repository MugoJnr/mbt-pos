#!/usr/bin/env python3
"""Download Twemoji PNGs for icon_index.json (offline colour emoji tiles)."""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IDX = ROOT / 'assets' / 'icons' / 'icon_index.json'
OUT = ROOT / 'assets' / 'icons' / 'emoji_png'
BASE = 'https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/72x72/{}.png'

# Emoji codepoints not in Twemoji 14 → nearest substitute
FALLBACKS = {
    'food/ghee-margarine': '1f9c8',
    'food/green-peas': '1fad8',
    'beauty/hair-brush-comb': '1f488',
    'pets/grooming': '1f488',
}


def cps(emoji: str) -> str:
    return '-'.join(f'{ord(ch):x}' for ch in emoji if ord(ch) != 0xfe0f)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    idx = json.loads(IDX.read_text(encoding='utf-8'))
    ok = fail = 0
    for ic in idx['icons']:
        iid = ic['id']
        cid = iid.replace('/', '__')
        dest = OUT / f'{cid}.png'
        emoji = (ic.get('emoji') or '').strip()
        names = []
        if iid in FALLBACKS:
            names.append(FALLBACKS[iid])
        if emoji:
            names.append(cps(emoji))
        got = False
        for name in names:
            try:
                urllib.request.urlretrieve(BASE.format(name), dest)
                if dest.stat().st_size > 100:
                    ic['emoji_png'] = f'emoji_png/{cid}.png'
                    ok += 1
                    got = True
                    break
            except Exception:
                pass
        if not got:
            print('FAIL', iid)
            fail += 1
    IDX.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'OK {ok} FAIL {fail} pngs={len(list(OUT.glob("*.png")))}')


if __name__ == '__main__':
    main()
