"""
MBT POS — Offline category visual system
Icon index, CategoryVisual widget, image uploads, prefs, smart suggestions.
100% offline — assets/icons/ + AppData uploads/preferences.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sys
import time
import uuid
from typing import Any, Optional

from PyQt5.QtCore import Qt, QSize, QByteArray
from PyQt5.QtGui import QPixmap, QIcon, QColor, QPainter, QFont
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtWidgets import QLabel, QFrame, QSizePolicy

from desktop.utils.theme import C, qss_alpha

logger = logging.getLogger('category_visuals')

# ── Paths ─────────────────────────────────────────────────────────────────────

def _project_source_root() -> str:
    """Repo / bundle root (not AppData) — where assets/icons live."""
    if getattr(sys, 'frozen', False):
        # PyInstaller onedir: assets next to exe or in _MEIPASS
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass and os.path.isdir(os.path.join(meipass, 'assets', 'icons')):
            return meipass
        exe_dir = os.path.dirname(sys.executable)
        if os.path.isdir(os.path.join(exe_dir, 'assets', 'icons')):
            return exe_dir
        return meipass or exe_dir
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def icons_root() -> str:
    return os.path.join(_project_source_root(), 'assets', 'icons')


def index_path() -> str:
    return os.path.join(icons_root(), 'icon_index.json')


def uploads_dir() -> str:
    from mbt_paths import get_project_root
    d = os.path.join(get_project_root(), 'uploads', 'categories')
    os.makedirs(d, exist_ok=True)
    os.makedirs(os.path.join(d, 'thumbs'), exist_ok=True)
    return d


def prefs_path() -> str:
    from mbt_paths import get_project_root
    d = os.path.join(get_project_root(), 'config')
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, 'category_visual_prefs.json')


def favorites_path() -> str:
    from mbt_paths import get_project_root
    d = os.path.join(get_project_root(), 'config')
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, 'category_icon_favorites.json')


# ── Contrast ──────────────────────────────────────────────────────────────────

def parse_hex(color: str):
    h = (color or '').strip().lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    if len(h) == 8:
        h = h[-6:]
    if len(h) != 6:
        return 59, 130, 246  # #3B82F6
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def relative_luminance(color: str) -> float:
    r, g, b = parse_hex(color)
    def lin(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def accessible_fg(bg_hex: str, light='#F8FAFC', dark='#0F172A') -> str:
    """Pick light or dark foreground for WCAG-ish contrast on accent bg."""
    return dark if relative_luminance(bg_hex) > 0.45 else light


def contrast_ratio(c1: str, c2: str) -> float:
    l1, l2 = relative_luminance(c1), relative_luminance(c2)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


# ── Icon index (lazy, cached) ─────────────────────────────────────────────────

_INDEX: Optional[dict] = None
_PIXMAP_CACHE: dict = {}
_THUMB_CACHE: dict = {}


def load_icon_index(force: bool = False) -> dict:
    global _INDEX
    if _INDEX is not None and not force:
        return _INDEX
    path = index_path()
    try:
        with open(path, encoding='utf-8') as f:
            _INDEX = json.load(f)
    except Exception as e:
        logger.warning('icon_index load failed: %s', e)
        _INDEX = {'version': 1, 'total': 0, 'folders': [], 'icons': []}
    return _INDEX


def all_icons() -> list:
    return list(load_icon_index().get('icons') or [])


def icon_folders() -> list:
    return list(load_icon_index().get('folders') or [])


def find_icon(icon_id_or_name: str) -> Optional[dict]:
    if not icon_id_or_name:
        return None
    key = icon_id_or_name.strip().lower()
    for ic in all_icons():
        if (ic.get('id') or '').lower() == key:
            return ic
        if (ic.get('path') or '').lower() == key:
            return ic
        if (ic.get('name') or '').lower() == key:
            return ic
        # bare filename / slug
        p = (ic.get('path') or '').lower()
        if p.endswith('/' + key) or p.endswith('/' + key + '.svg'):
            return ic
        if os.path.splitext(os.path.basename(p))[0] == key:
            return ic
    return None


def resolve_icon_path(icon_ref: str) -> Optional[str]:
    """Return absolute path to SVG for icon id / relative path / name."""
    if not icon_ref:
        return None
    # Absolute existing file
    if os.path.isfile(icon_ref):
        return icon_ref
    root = icons_root()
    # Relative path from index
    cand = os.path.join(root, icon_ref.replace('/', os.sep))
    if os.path.isfile(cand):
        return cand
    ic = find_icon(icon_ref)
    if ic:
        p = os.path.join(root, (ic.get('path') or '').replace('/', os.sep))
        if os.path.isfile(p):
            return p
    # Placeholder
    ph = os.path.join(root, 'generic', '_placeholder.svg')
    return ph if os.path.isfile(ph) else None


def search_icons(query: str, folder: str = None, limit: int = 200) -> list:
    """Index-based search — no folder scan."""
    q = (query or '').strip().lower()
    tokens = [t for t in re.split(r'\s+', q) if t] if q else []
    out = []
    for ic in all_icons():
        if folder and folder != 'all' and (ic.get('category') or '') != folder:
            continue
        if not tokens:
            out.append(ic)
        else:
            hay = ' '.join([
                ic.get('id') or '',
                ic.get('name') or '',
                ic.get('category') or '',
                ic.get('section') or '',
                ' '.join(ic.get('keywords') or []),
                ' '.join(ic.get('tags') or []),
                ic.get('emoji') or '',
            ]).lower()
            if all(t in hay for t in tokens):
                out.append(ic)
        if len(out) >= limit:
            break
    return out


def suggest_icons_for_name(name: str, limit: int = 8) -> list:
    """Smart suggestions when typing a category name."""
    if not (name or '').strip():
        return search_icons('', limit=limit)
    tokens = [t for t in re.split(r'[^a-z0-9]+', name.lower()) if len(t) > 1]
    scored = []
    for ic in all_icons():
        hay = ' '.join([
            ic.get('name') or '',
            ' '.join(ic.get('keywords') or []),
            ic.get('category') or '',
            ic.get('section') or '',
        ]).lower()
        score = 0
        for t in tokens:
            if t in hay:
                score += 3 if t in (ic.get('name') or '').lower() else 1
            if any(t in k for k in (ic.get('keywords') or [])):
                score += 2
        if score:
            scored.append((score, ic))
    scored.sort(key=lambda x: -x[0])
    return [ic for _, ic in scored[:limit]]


# ── Pixmap loading ────────────────────────────────────────────────────────────

def svg_to_pixmap(svg_path: str, size: int = 48) -> QPixmap:
    cache_key = (svg_path, size)
    if cache_key in _PIXMAP_CACHE:
        return _PIXMAP_CACHE[cache_key]
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    if not svg_path or not os.path.isfile(svg_path):
        _PIXMAP_CACHE[cache_key] = pm
        return pm
    try:
        renderer = QSvgRenderer(svg_path)
        if renderer.isValid():
            p = QPainter(pm)
            renderer.render(p)
            p.end()
        else:
            # Fallback: try as image
            img = QPixmap(svg_path)
            if not img.isNull():
                pm = img.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    except Exception as e:
        logger.debug('svg render failed %s: %s', svg_path, e)
    _PIXMAP_CACHE[cache_key] = pm
    return pm


def load_image_pixmap(path: str, size: int = 48, fit: str = 'cover') -> QPixmap:
    if not path or not os.path.isfile(path):
        return QPixmap()
    # Prefer thumb cache
    thumb = _thumb_path_for(path, size)
    if os.path.isfile(thumb):
        pm = QPixmap(thumb)
        if not pm.isNull():
            return pm
    pm = QPixmap(path)
    if pm.isNull():
        return QPixmap()
    mode = Qt.KeepAspectRatioByExpanding if fit == 'cover' else Qt.KeepAspectRatio
    scaled = pm.scaled(size, size, mode, Qt.SmoothTransformation)
    if fit == 'cover' and (scaled.width() > size or scaled.height() > size):
        x = max(0, (scaled.width() - size) // 2)
        y = max(0, (scaled.height() - size) // 2)
        scaled = scaled.copy(x, y, size, size)
    return scaled


def _thumb_path_for(src: str, size: int) -> str:
    base = os.path.splitext(os.path.basename(src))[0]
    return os.path.join(uploads_dir(), 'thumbs', f'{base}_{size}.png')


# ── Image upload ──────────────────────────────────────────────────────────────

_ALLOWED_EXT = {'.png', '.jpg', '.jpeg', '.webp', '.svg'}


def save_category_image(source_path: str, max_side: int = 512) -> Optional[str]:
    """
    Copy/compress image into AppData uploads/categories/.
    Returns relative path (uploads/categories/<file>) or absolute under uploads.
    """
    if not source_path or not os.path.isfile(source_path):
        return None
    ext = os.path.splitext(source_path)[1].lower()
    if ext not in _ALLOWED_EXT:
        raise ValueError(f'Unsupported image type: {ext}')
    dest_dir = uploads_dir()
    uid = uuid.uuid4().hex[:12]
    # SVG: copy as-is
    if ext == '.svg':
        dest = os.path.join(dest_dir, f'{uid}.svg')
        shutil.copy2(source_path, dest)
        return dest

    dest_name = f'{uid}.webp'
    dest = os.path.join(dest_dir, dest_name)
    try:
        from PIL import Image
        im = Image.open(source_path)
        if im.mode in ('P', 'RGBA'):
            bg = Image.new('RGB', im.size, (255, 255, 255))
            if im.mode == 'P':
                im = im.convert('RGBA')
            bg.paste(im, mask=im.split()[-1] if im.mode == 'RGBA' else None)
            im = bg
        elif im.mode != 'RGB':
            im = im.convert('RGB')
        w, h = im.size
        scale = min(1.0, float(max_side) / max(w, h))
        if scale < 1.0:
            im = im.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        im.save(dest, 'WEBP', quality=82, method=4)
        # thumbs
        for sz in (48, 64, 96, 128):
            t = im.copy()
            t.thumbnail((sz, sz), Image.LANCZOS)
            t.save(_thumb_path_for(dest, sz), 'PNG')
        return dest
    except ImportError:
        # No Pillow — copy + Qt-based resize to PNG
        dest = os.path.join(dest_dir, f'{uid}.png')
        pm = QPixmap(source_path)
        if pm.isNull():
            shutil.copy2(source_path, dest)
            return dest
        if max(pm.width(), pm.height()) > max_side:
            pm = pm.scaled(max_side, max_side, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        pm.save(dest, 'PNG')
        for sz in (48, 64, 96, 128):
            pm.scaled(sz, sz, Qt.KeepAspectRatio, Qt.SmoothTransformation).save(
                _thumb_path_for(dest, sz), 'PNG')
        return dest


# ── Favorites / recent / settings prefs ───────────────────────────────────────

_DEFAULT_PREFS = {
    'tile_size': 48,
    'corner_radius': 12,
    'image_fit': 'cover',  # cover | contain
    'show_labels': True,
    'show_accent': True,
    'compact_mode': False,
    'default_placeholder': 'generic/_placeholder.svg',
}


def load_visual_prefs() -> dict:
    p = dict(_DEFAULT_PREFS)
    try:
        if os.path.isfile(prefs_path()):
            with open(prefs_path(), encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                p.update({k: data[k] for k in _DEFAULT_PREFS if k in data})
    except Exception:
        pass
    return p


def save_visual_prefs(prefs: dict) -> None:
    cur = load_visual_prefs()
    cur.update(prefs or {})
    with open(prefs_path(), 'w', encoding='utf-8') as f:
        json.dump(cur, f, indent=2)


def load_favorites_state() -> dict:
    try:
        if os.path.isfile(favorites_path()):
            with open(favorites_path(), encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {'favorites': [], 'recent': []}


def save_favorites_state(state: dict) -> None:
    with open(favorites_path(), 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)


def toggle_favorite(icon_id: str) -> bool:
    st = load_favorites_state()
    favs = list(st.get('favorites') or [])
    if icon_id in favs:
        favs.remove(icon_id)
        is_fav = False
    else:
        favs.insert(0, icon_id)
        is_fav = True
    st['favorites'] = favs[:100]
    save_favorites_state(st)
    return is_fav


def push_recent(icon_id: str) -> None:
    st = load_favorites_state()
    recent = [r for r in (st.get('recent') or []) if r != icon_id]
    recent.insert(0, icon_id)
    st['recent'] = recent[:40]
    save_favorites_state(st)


def favorite_ids() -> list:
    return list(load_favorites_state().get('favorites') or [])


def recent_ids() -> list:
    return list(load_favorites_state().get('recent') or [])


# ── Smart category seed matching ──────────────────────────────────────────────

from desktop.utils.category_suggest import suggest_visual_for_category_name  # noqa: E402


# ── CategoryVisual widget ─────────────────────────────────────────────────────

class CategoryVisual(QFrame):
    """
    Reusable tile: custom image → icon SVG → placeholder.
    Fixed size, aspect ratio, theme-aware accent ring.
    """

    def __init__(
        self,
        category: dict = None,
        size: int = None,
        show_label: bool = None,
        parent=None,
    ):
        super().__init__(parent)
        prefs = load_visual_prefs()
        self._size = int(size if size is not None else prefs.get('tile_size', 48))
        self._radius = int(prefs.get('corner_radius', 12))
        self._fit = prefs.get('image_fit', 'cover')
        self._show_label = prefs.get('show_labels', True) if show_label is None else show_label
        self._show_accent = bool(prefs.get('show_accent', True))
        self._compact = bool(prefs.get('compact_mode', False))
        self._category = category or {}
        self.setObjectName('categoryVisual')
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        self._img = QLabel(self)
        self._img.setAlignment(Qt.AlignCenter)
        self._img.setObjectName('categoryVisualImg')

        self._lbl = QLabel(self)
        self._lbl.setAlignment(Qt.AlignCenter)
        self._lbl.setObjectName('categoryVisualLbl')
        self._lbl.setWordWrap(True)

        self._apply_geometry()
        self.refresh()

    def _apply_geometry(self):
        s = self._size
        label_h = 0 if (self._compact or not self._show_label) else 18
        self.setFixedSize(s + 4, s + 4 + label_h)
        self._img.setFixedSize(s, s)
        self._img.move(2, 2)
        if label_h:
            self._lbl.setGeometry(0, s + 2, s + 4, label_h)
            self._lbl.show()
        else:
            self._lbl.hide()

    def set_category(self, category: dict = None, name: str = None):
        """Accept full category dict or just a name string via name=."""
        if category is not None:
            self._category = category or {}
        elif name is not None:
            self._category = {'name': name}
        self.refresh()

    def set_visual(
        self,
        visual_type: str = 'icon',
        icon_name: str = None,
        image_path: str = None,
        accent_color: str = None,
        name: str = None,
    ):
        cat = dict(self._category or {})
        if name is not None:
            cat['name'] = name
        cat['visual_type'] = visual_type
        cat['icon_name'] = icon_name
        cat['image_path'] = image_path
        cat['accent_color'] = accent_color or cat.get('accent_color') or '#3B82F6'
        self._category = cat
        self.refresh()

    def refresh_theme(self):
        self.refresh()

    def refresh(self):
        prefs = load_visual_prefs()
        # live prefs for size if not explicitly locked — keep constructor size
        cat = self._category or {}
        name = (cat.get('name') or cat.get('category') or '').strip()
        vtype = (cat.get('visual_type') or 'icon').lower()
        accent = cat.get('accent_color') or '#3B82F6'
        icon_name = cat.get('icon_name') or ''
        image_path = cat.get('image_path') or ''
        s = self._size
        r = self._radius

        pm = QPixmap()
        if vtype == 'image' and image_path:
            path = image_path
            if not os.path.isabs(path):
                from mbt_paths import get_project_root
                path = os.path.join(get_project_root(), path)
            if not os.path.isfile(path) and os.path.isfile(image_path):
                path = image_path
            pm = load_image_pixmap(path, s, fit=self._fit)

        if pm.isNull() and icon_name:
            svg = resolve_icon_path(icon_name)
            if svg:
                pm = svg_to_pixmap(svg, s)

        if pm.isNull():
            # Name-based suggestion fallback
            if name:
                sug = suggest_visual_for_category_name(name)
                svg = resolve_icon_path(sug.get('icon_name'))
                if svg:
                    pm = svg_to_pixmap(svg, s)
                    if not accent or accent == '#3B82F6':
                        accent = sug.get('accent_color') or accent

        if pm.isNull():
            ph = resolve_icon_path(prefs.get('default_placeholder') or 'generic/_placeholder.svg')
            if ph:
                pm = svg_to_pixmap(ph, s)

        if pm.isNull():
            # Last resort: colored tile with initial
            pm = QPixmap(s, s)
            pm.fill(Qt.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing)
            p.setBrush(QColor(accent))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(0, 0, s, s, r, r)
            p.setPen(QColor(accessible_fg(accent)))
            f = QFont()
            f.setPixelSize(max(14, s // 2))
            f.setBold(True)
            p.setFont(f)
            initial = (name[:1] or '?').upper()
            p.drawText(pm.rect(), Qt.AlignCenter, initial)
            p.end()

        self._img.setPixmap(pm)
        border = accent if self._show_accent else 'transparent'
        bg = qss_alpha(accent, 0.12) if self._show_accent else 'transparent'
        self.setStyleSheet(
            f"#categoryVisual {{ background:{bg}; border:2px solid {qss_alpha(border, 0.45)}; "
            f"border-radius:{r}px; }}"
            f"#categoryVisualImg {{ background:transparent; border:none; border-radius:{max(4, r - 2)}px; }}"
            f"#categoryVisualLbl {{ color:{C.get('text2', '#94a3b8')}; font-size:10px; "
            f"background:transparent; border:none; }}"
        )
        if self._show_label and not self._compact:
            self._lbl.setText(name[:18] if name else '')
            self._lbl.setToolTip(name)
        self.setToolTip(name or icon_name or 'Category')


def category_dict_from_product(product: dict, categories_by_name: dict = None) -> dict:
    """
    Resolve visual for a product: product image → category image → category icon → placeholder.
    """
    product = product or {}
    cat_name = product.get('category') or 'General'
    cat = {}
    if categories_by_name:
        cat = dict(categories_by_name.get(cat_name) or categories_by_name.get(cat_name.lower()) or {})
    if not cat:
        cat = {'name': cat_name}
    else:
        cat.setdefault('name', cat_name)

    # Product-level image wins
    pimg = product.get('image_path') or product.get('image') or ''
    if pimg and os.path.isfile(str(pimg)):
        return {
            'name': cat_name,
            'visual_type': 'image',
            'image_path': pimg,
            'icon_name': cat.get('icon_name'),
            'accent_color': cat.get('accent_color') or '#3B82F6',
        }
    return {
        'name': cat_name,
        'visual_type': cat.get('visual_type') or 'icon',
        'image_path': cat.get('image_path'),
        'icon_name': cat.get('icon_name'),
        'accent_color': cat.get('accent_color') or '#3B82F6',
    }
