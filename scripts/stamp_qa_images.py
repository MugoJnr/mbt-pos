"""Stamp a unique QA banner on screenshots so ChatGPT accepts re-uploads."""
from __future__ import annotations

import hashlib
import random
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def stamp(src: Path, dest: Path, label: str) -> Path:
    im = Image.open(src).convert('RGB')
    # Per-label border color so perceptual hash differs strongly
    colors = {
        'PRO': (212, 168, 75),
        'EXPLORER': (56, 189, 248),
        'CLASSIC': (52, 211, 153),
    }
    key = 'PRO'
    for k in colors:
        if k in label.upper():
            key = k
            break
    border = colors[key]
    # Strong uniqueness: random pad + banner height + pixel noise (ChatGPT dup-hash)
    rng = random.Random(hashlib.sha1(f'{label}-{time.time_ns()}'.encode()).hexdigest())
    ban_h = 36 + rng.randint(0, 18)
    pad = 8 + rng.randint(0, 12)
    w, h = im.size
    # Tiny content jitter so perceptual hash changes
    pixels = im.load()
    for _ in range(40):
        x = rng.randint(0, w - 1)
        y = rng.randint(0, h - 1)
        r, g, b = pixels[x, y]
        pixels[x, y] = ((r + rng.randint(1, 7)) % 256, (g + rng.randint(1, 7)) % 256, (b + rng.randint(1, 7)) % 256)
    out = Image.new('RGB', (w + pad * 2, h + ban_h + pad * 2), border)
    out.paste(im, (pad, pad))
    draw = ImageDraw.Draw(out)
    draw.rectangle([0, h + pad * 2, out.size[0], out.size[1]], fill=(18, 24, 38))
    nonce = rng.randint(100000, 999999)
    text = f'MBT POS QA GATE  {label}  {time.strftime("%Y-%m-%d %H:%M:%S")}  #{nonce}'
    try:
        font = ImageFont.truetype('arial.ttf', 16)
    except Exception:
        font = ImageFont.load_default()
    draw.text((12, h + pad * 2 + 8), text, fill=border, font=font)
    # unique noise stripe
    for x in range(0, out.size[0], 3):
        draw.point((x, out.size[1] - 3), fill=((x * 11 + nonce) % 255, (nonce // 3) % 255, 50))
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Unique JPEG quality also shifts bytes
    out.save(dest, quality=88 + rng.randint(0, 7))
    return dest


if __name__ == '__main__':
    import sys
    it = sys.argv[1] if len(sys.argv) > 1 else '20'
    root = Path(__file__).resolve().parents[1]
    src_dir = root / '_qa_checkout_pro_design' / f'iter_{it}'
    dst_dir = root / '_qa_full_system_polish' / f'desktop_iter{it}' / 'chatgpt_upload'
    stamp_id = str(int(time.time()))
    for name, label in (
        ('checkout_pro.png', 'PRO'),
        ('product_explorer.png', 'EXPLORER'),
        ('retail_classic.png', 'CLASSIC'),
    ):
        s = src_dir / name
        d = dst_dir / f'{label.lower()}_{stamp_id}.jpg'
        stamp(s, d, f'{label}-{stamp_id}')
        print('STAMPED', d.name, d.stat().st_size)
