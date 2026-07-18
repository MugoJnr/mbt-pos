#!/usr/bin/env python3
"""
Generate offline category SVG icons + icon_index.json from QA catalog.
100% local — no CDN. Run once; commit resulting assets/icons/.
"""
from __future__ import annotations

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG_CANDIDATES = [
    os.path.join(os.path.expanduser('~'), 'OneDrive', 'Desktop', 'QA_CLAUDE_ICONS', 'catalog.json'),
    r'c:\Users\mugoj\OneDrive\Desktop\QA_CLAUDE_ICONS\catalog.json',
]
OUT_DIR = os.path.join(ROOT, 'assets', 'icons')

SECTION_FOLDER = {
    'Grocery & Supermarket': 'food',
    'Fresh Produce & Meat': 'food',
    'Pharmacy & Chemist': 'pharmacy',
    'Household & Cleaning': 'home',
    'Beauty & Personal Care': 'beauty',
    'Clothing & Apparel': 'clothing',
    'Electronics & Phones': 'electronics',
    'Hardware & Building': 'hardware',
    'Agrovet & Animal Feeds': 'agriculture',
    'Food Service & Restaurant': 'restaurant',
    'Stationery & School': 'office',
    'Auto Parts & Workshop': 'automotive',
    'Entertainment & Toys': 'toys',
    'Home & Furniture': 'furniture',
    'Kitchen & Cookware': 'home',
    'Pet Supplies': 'pets',
    'Energy & Utilities': 'logistics',
    'General / Default': 'generic',
}

# Label keyword overrides → folder (more specific than section)
LABEL_FOLDER_OVERRIDES = [
    (('juice', 'soda', 'drink', 'water', 'milk', 'bar'), 'drinks'),
    (('bread', 'biscuit', 'cake', 'pastry', 'cereal'), 'bakery'),
    (('book', 'textbook', 'exercise'), 'books'),
    (('football', 'cricket', 'fitness', 'gym', 'sport'), 'sports'),
    (('cement', 'construction', 'ladder', 'brick'), 'construction'),
    (('finance', 'cash', 'money', 'wallet'), 'finance'),
    (('service', 'subscription', 'salon', 'barber'), 'services'),
]


def _slug(label: str) -> str:
    s = label.lower().strip()
    s = re.sub(r'[/&]+', '-', s)
    s = re.sub(r'[^a-z0-9]+', '-', s)
    return s.strip('-') or 'icon'


def _folder_for(section: str, label: str) -> str:
    low = label.lower()
    for keys, folder in LABEL_FOLDER_OVERRIDES:
        if any(k in low for k in keys):
            return folder
    return SECTION_FOLDER.get(section, 'generic')


def _keywords(label: str, section: str, emoji: str) -> list:
    parts = re.split(r'[/&\s,]+', label.lower())
    parts += re.split(r'[/&\s,]+', section.lower())
    parts = [p for p in parts if len(p) > 1]
    if emoji:
        parts.append(emoji)
    # unique preserve order
    seen, out = set(), []
    for p in parts:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _contrast_fg(bg_hex: str) -> str:
    h = (bg_hex or '#888888').lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except Exception:
        return '#1e293b'
    # relative luminance
    lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0
    return '#0f172a' if lum > 0.55 else '#f8fafc'


# Simple geometric glyph library keyed by keyword → SVG inner paths (viewBox 0 0 64 64)
_GLYPHS = {
    'phone': '<rect x="22" y="10" width="20" height="44" rx="4" fill="none" stroke="currentColor" stroke-width="2.5"/><circle cx="32" cy="46" r="2" fill="currentColor"/>',
    'laptop': '<rect x="10" y="16" width="44" height="28" rx="2" fill="none" stroke="currentColor" stroke-width="2.5"/><path d="M6 48h52" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/>',
    'pill': '<rect x="18" y="24" width="28" height="16" rx="8" fill="none" stroke="currentColor" stroke-width="2.5"/><line x1="32" y1="24" x2="32" y2="40" stroke="currentColor" stroke-width="2"/>',
    'shirt': '<path d="M20 18l12-6 12 6 8-2 4 10-8 4v20H16V30l-8-4 4-10z" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linejoin="round"/>',
    'cart': '<circle cx="22" cy="50" r="3" fill="currentColor"/><circle cx="46" cy="50" r="3" fill="currentColor"/><path d="M8 12h6l6 28h28l6-18H18" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>',
    'home': '<path d="M10 30L32 12l22 18v22H38V36H26v16H10z" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linejoin="round"/>',
    'hammer': '<path d="M14 40l20-20 8 8-20 20z" fill="none" stroke="currentColor" stroke-width="2.5"/><path d="M34 20l8-8 6 6-8 8" fill="none" stroke="currentColor" stroke-width="2.5"/>',
    'leaf': '<path d="M32 52C18 44 12 28 20 16c14 4 28 16 28 32-8 2-12 4-16 4z" fill="none" stroke="currentColor" stroke-width="2.5"/><path d="M32 52V28" stroke="currentColor" stroke-width="2"/>',
    'paw': '<circle cx="22" cy="22" r="5" fill="currentColor"/><circle cx="42" cy="22" r="5" fill="currentColor"/><circle cx="16" cy="34" r="4" fill="currentColor"/><circle cx="48" cy="34" r="4" fill="currentColor"/><ellipse cx="32" cy="42" rx="10" ry="8" fill="currentColor"/>',
    'car': '<path d="M10 36l6-12h32l6 12v10H10z" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linejoin="round"/><circle cx="20" cy="46" r="4" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="44" cy="46" r="4" fill="none" stroke="currentColor" stroke-width="2"/>',
    'book': '<path d="M14 12h16c4 0 6 2 6 6v34c0-4-2-6-6-6H14zM50 12H34c-4 0-6 2-6 6v34c0-4 2-6 6-6h16z" fill="none" stroke="currentColor" stroke-width="2.5"/>',
    'food': '<circle cx="32" cy="28" r="14" fill="none" stroke="currentColor" stroke-width="2.5"/><path d="M18 48h28" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/><path d="M32 14v6M24 18l4 4M40 18l-4 4" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
    'bottle': '<path d="M26 10h12v8l4 6v28a4 4 0 01-4 4H26a4 4 0 01-4-4V24l4-6z" fill="none" stroke="currentColor" stroke-width="2.5"/>',
    'box': '<path d="M12 22l20-10 20 10v24L32 56 12 46z" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linejoin="round"/><path d="M12 22l20 10 20-10M32 32v24" stroke="currentColor" stroke-width="2"/>',
    'star': '<path d="M32 10l5 14h15l-12 9 5 15-13-9-13 9 5-15-12-9h15z" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linejoin="round"/>',
    'bolt': '<path d="M36 8L18 34h12l-4 22 20-28H34z" fill="currentColor"/>',
    'heart': '<path d="M32 50s-18-10-18-24a10 10 0 0118-6 10 10 0 0118 6c0 14-18 24-18 24z" fill="none" stroke="currentColor" stroke-width="2.5"/>',
    'game': '<rect x="10" y="22" width="44" height="24" rx="8" fill="none" stroke="currentColor" stroke-width="2.5"/><circle cx="42" cy="30" r="3" fill="currentColor"/><circle cx="48" cy="36" r="3" fill="currentColor"/><path d="M20 34h8M24 30v8" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/>',
    'drop': '<path d="M32 10c0 0-14 18-14 28a14 14 0 0028 0c0-10-14-28-14-28z" fill="none" stroke="currentColor" stroke-width="2.5"/>',
    'sun': '<circle cx="32" cy="32" r="10" fill="none" stroke="currentColor" stroke-width="2.5"/><path d="M32 8v6M32 50v6M8 32h6M50 32h6M14 14l4 4M46 46l4 4M14 50l4-4M46 18l4-4" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/>',
    'wrench': '<path d="M42 14a10 10 0 00-12 12L14 42l8 8 16-16a10 10 0 0012-12l-8 4-4-4z" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linejoin="round"/>',
    'chair': '<path d="M18 28h28v8H18zM22 36v16M42 36v16M20 20h24v8H20z" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linejoin="round"/>',
    'tag': '<path d="M10 28L28 10h18v18L28 46z" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linejoin="round"/><circle cx="40" cy="18" r="3" fill="currentColor"/>',
}


def _glyph_for(label: str, folder: str) -> str:
    low = label.lower()
    checks = [
        (('phone', 'mobile'), 'phone'),
        (('laptop', 'computer', 'keyboard', 'mouse', 'printer', 'router', 'wifi'), 'laptop'),
        (('tablet', 'pill', 'medicine', 'syrup', 'vitamin', 'injection'), 'pill'),
        (('shirt', 'dress', 'trouser', 'jean', 'jacket', 'coat', 'uniform', 'sock', 'underwear'), 'shirt'),
        (('cart', 'retail', 'shop', 'bag'), 'cart'),
        (('home', 'sofa', 'bed', 'furniture', 'mirror', 'decor', 'storage'), 'home'),
        (('hammer', 'screw', 'nail', 'saw', 'tool', 'hardware', 'wrench', 'spanner'), 'hammer'),
        (('seed', 'leaf', 'plant', 'garden', 'feed', 'agro', 'fertilis', 'fertiliz', 'maize', 'bean'), 'leaf'),
        (('dog', 'cat', 'pet', 'bird', 'paw'), 'paw'),
        (('car', 'tyre', 'engine', 'fuel', 'auto', 'battery'), 'car'),
        (('book', 'pencil', 'pen', 'school', 'file', 'office', 'stationery'), 'book'),
        (('burger', 'pizza', 'food', 'meal', 'grill', 'salad', 'noodle', 'snack', 'breakfast'), 'food'),
        (('oil', 'bottle', 'drink', 'soda', 'juice', 'milk', 'water', 'beer'), 'bottle'),
        (('box', 'pack', 'general', 'product'), 'box'),
        (('star', 'feature', 'promo'), 'star'),
        (('electric', 'bolt', 'power', 'token', 'solar'), 'bolt'),
        (('beauty', 'lip', 'cosmetic', 'perfume', 'heart', 'care'), 'heart'),
        (('game', 'toy', 'puzzle', 'music', 'party'), 'game'),
        (('water', 'drop', 'bleach', 'liquid'), 'drop'),
        (('sun', 'solar', 'light', 'bulb', 'torch'), 'sun'),
        (('wrench', 'workshop', 'diy', 'repair'), 'wrench'),
        (('chair', 'seat'), 'chair'),
        (('tag', 'label', 'promo', 'discount'), 'tag'),
    ]
    for keys, g in checks:
        if any(k in low for k in keys):
            return _GLYPHS[g]
    folder_default = {
        'food': 'food', 'drinks': 'bottle', 'bakery': 'food', 'pharmacy': 'pill',
        'agriculture': 'leaf', 'hardware': 'hammer', 'electronics': 'phone',
        'clothing': 'shirt', 'beauty': 'heart', 'furniture': 'chair',
        'office': 'book', 'pets': 'paw', 'automotive': 'car', 'logistics': 'box',
        'finance': 'tag', 'restaurant': 'food', 'services': 'star', 'sports': 'star',
        'home': 'home', 'construction': 'hammer', 'toys': 'game', 'books': 'book',
        'generic': 'box',
    }
    return _GLYPHS.get(folder_default.get(folder, 'box'), _GLYPHS['box'])


def make_svg(label: str, folder: str, bg: str, emoji: str) -> str:
    fg = _contrast_fg(bg)
    glyph = _glyph_for(label, folder)
    # Professional tile: rounded rect bg + geometric glyph + small emoji accent
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64" role="img" aria-label="{_esc(label)}">
  <rect width="64" height="64" rx="14" fill="{bg}"/>
  <g color="{fg}" transform="translate(0,0)">{glyph}</g>
  <text x="52" y="14" font-size="10" text-anchor="middle" dominant-baseline="middle">{emoji}</text>
</svg>
'''


def _esc(s: str) -> str:
    return (s or '').replace('&', '&amp;').replace('<', '&lt;').replace('"', '&quot;')


def load_catalog() -> dict:
    for p in CATALOG_CANDIDATES:
        if os.path.isfile(p):
            with open(p, encoding='utf-8') as f:
                return json.load(f)
    raise FileNotFoundError('catalog.json not found in QA_CLAUDE_ICONS')


def main():
    catalog = load_catalog()
    index = {
        'version': 1,
        'total': 0,
        'folders': [],
        'icons': [],
    }
    folders_seen = set()
    used_ids = set()

    for section in catalog.get('sections', []):
        cat_name = section.get('category') or 'General'
        for icon in section.get('icons', []):
            label = (icon.get('label') or 'Icon').strip()
            emoji = icon.get('emoji') or '📦'
            bg = icon.get('bg') or '#e2e8f0'
            folder = _folder_for(cat_name, label)
            folders_seen.add(folder)
            base = _slug(label)
            fname = f'{base}.svg'
            icon_id = f'{folder}/{base}'
            n = 2
            while icon_id in used_ids:
                fname = f'{base}-{n}.svg'
                icon_id = f'{folder}/{base}-{n}'
                n += 1
            used_ids.add(icon_id)

            rel = f'{folder}/{fname}'
            abs_dir = os.path.join(OUT_DIR, folder)
            os.makedirs(abs_dir, exist_ok=True)
            path = os.path.join(abs_dir, fname)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(make_svg(label, folder, bg, emoji))

            tags = [folder, cat_name.lower()]
            kw = _keywords(label, cat_name, emoji)
            index['icons'].append({
                'id': icon_id,
                'name': label,
                'category': folder,
                'section': cat_name,
                'path': rel.replace('\\', '/'),
                'keywords': kw,
                'tags': tags,
                'emoji': emoji,
                'bg': bg,
            })

    index['total'] = len(index['icons'])
    index['folders'] = sorted(folders_seen)
    # Ensure empty folders from spec also exist
    for extra in (
        'food', 'drinks', 'bakery', 'pharmacy', 'agriculture', 'hardware',
        'electronics', 'clothing', 'beauty', 'furniture', 'office', 'pets',
        'automotive', 'logistics', 'finance', 'restaurant', 'services',
        'sports', 'home', 'construction', 'toys', 'books', 'generic',
    ):
        os.makedirs(os.path.join(OUT_DIR, extra), exist_ok=True)
        folders_seen.add(extra)
    index['folders'] = sorted(folders_seen)

    # Placeholder generic
    ph = os.path.join(OUT_DIR, 'generic', '_placeholder.svg')
    with open(ph, 'w', encoding='utf-8') as f:
        f.write(make_svg('Placeholder', 'generic', '#e2e8f0', '📦'))

    idx_path = os.path.join(OUT_DIR, 'icon_index.json')
    with open(idx_path, 'w', encoding='utf-8') as f:
        json.dump(index, f, indent=2, ensure_ascii=False)

    print(f'Generated {index["total"]} icons in {len(index["folders"])} folders')
    print(f'Index: {idx_path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
