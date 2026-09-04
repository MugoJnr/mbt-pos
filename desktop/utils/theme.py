"""
MBT POS — Design System v8 (Live Dashboard / Figma brief aligned)
MugoByte Technologies | mugobyte.com

Two complete themes: DARK (default) + LIGHT
Tokens align with web/dashboard-ui styles.css + FIGMA_UI_MODERNIZATION_SOURCE.md
Global switch via ThemeManager.apply(is_light)
Font: Manrope when available, Segoe UI fallback
C dict API is stable — tabs read C['…'] keys; do not rename keys.

CRITICAL Qt QSS rule:
  CSS 8-digit hex (#RRGGBBAA) is WRONG in Qt — Qt uses #AARRGGBB.
  Appending alpha like f\"{{C['err']}}22\" becomes opaque olive, not translucent red.
  Always use qss_alpha() / rgba() helpers below.
"""
import os
import re
import sys


def _parse_hex(color: str):
    """Return (r, g, b) from #RGB / #RRGGBB / #AARRGGBB / #RRGGBBAA-ish input."""
    h = (color or '').strip().lstrip('#')
    if len(h) == 3:
        h = ''.join(ch * 2 for ch in h)
    if len(h) == 8:
        # Prefer treating full 8 as AARRGGBB when alpha nibble looks like alpha
        # Callers should pass 6-digit brand tokens; strip leading AA if present.
        h = h[2:]
    if len(h) != 6:
        return 0, 0, 0
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def qss_alpha(color: str, alpha: float = 0.13) -> str:
    """
    Qt-safe translucent color for QSS.
    alpha: 0.0–1.0  →  rgba(r,g,b,0–255)
    """
    r, g, b = _parse_hex(color)
    a = max(0, min(255, int(round(float(alpha) * 255))))
    return f'rgba({r}, {g}, {b}, {a})'


def qss_hex_aa(color: str, alpha: float = 0.13) -> str:
    """Same as qss_alpha but as #AARRGGBB (also Qt-valid)."""
    r, g, b = _parse_hex(color)
    a = max(0, min(255, int(round(float(alpha) * 255))))
    return f'#{a:02X}{r:02X}{g:02X}{b:02X}'


# ── DARK PALETTE (premium navy + gold — clearer hierarchy) ────────────────────
# Surfaces step: app/sidebar → panel → card → card2/hover for elevation.
# text2/muted tuned for WCAG-ish contrast on card (#16213A).
DARK = {
    'app':       '#0B1220',
    'surface':   '#0B1220',
    'panel':     '#0E1628',
    'card':      '#16213A',
    'card2':     '#1B2943',
    'sidebar':   '#0A101C',
    'input':     '#101A2E',
    'hover':     '#1E2E4A',
    'selected':  '#243554',
    'gold':      '#FBBF24',
    'gold_lt':   '#FCD34D',
    'gold_dk':   '#D97706',
    'gold_fg':   '#0B1220',
    # Accent text sitting on a 10-25% gold tint (chips, selected pills, tips).
    # On a dark tint the bright gold already reads; light mode needs deeper ink.
    'gold_ink':  '#FBBF24',
    # dim tokens are solid-ish panel mixes (NOT CSS #RRGGBBAA — Qt misreads those)
    'gold_dim':  '#1C1808',
    'text':      '#FFFFFF',
    'text2':     '#B4C2D6',   # secondary / form labels / table headers
    'muted':     '#8B9BB0',   # captions / placeholders
    'disabled':  '#1C2A3A',
    'ok':        '#00D084',
    # Hover/pressed fills for success + danger buttons, which previously had no
    # state feedback at all. Both keep >=4.5:1 with their on-tone ink.
    'ok_lt':     '#2BE39B',
    'ok_dk':     '#00A868',
    'ok_dim':    '#0A1F18',
    'warn':      '#FFB000',
    'warn_dim':  '#1A1508',
    'err':       '#FF4D6D',
    'err_lt':    '#FF7A92',
    'err_dk':    '#F04A66',
    'err_dim':   '#2A1018',   # solid danger chip bg (readable vs translucent)
    'info':      '#60A5FA',   # 6.3:1 on card (old #3B82F6 measured 4.35:1)
    'info_dim':  '#0C1424',
    'border':    '#2A4060',
    'border2':   '#587AA6',   # control boundaries — 3.2:1+ on card/card2/input
    'sep':       '#121A2C',
    'divider':   '#2A4060',
    'focus':     '#FBBF24',
    # Ink printed on a saturated fill. Bright dark-theme tones cannot carry
    # white text at 4.5:1, so on-tone ink is the deep navy used by gold buttons.
    'on_danger': '#0B1220',
    'on_success':'#0B1220',
    # Semantic aliases used by POS modular components
    'primary':   '#FBBF24',
    'success':   '#00D084',
    'warning':   '#FFB000',
    'danger':    '#FF4D6D',
}

# ── LIGHT PALETTE (Lovable .light) ────────────────────────────────────────────
LIGHT = {
    'app':       '#F0F4FA',
    'surface':   '#FFFFFF',
    'panel':     '#E8EDF6',
    'card':      '#FFFFFF',
    'card2':     '#F4F7FC',
    'sidebar':   '#E2E8F2',
    'input':     '#FFFFFF',
    'hover':     '#DDE6F2',
    'selected':  '#CDDAEE',
    'gold':      '#8F5600',   # 5.95:1 on white (old #B87000 measured 3.92:1)
    'gold_lt':   '#A66400',   # hover fill stays >=4.5:1 with white ink
    'gold_dk':   '#714400',
    'gold_fg':   '#FFFFFF',
    'gold_ink':  '#6B4000',   # 4.9:1 on a 22% gold tint, 9.2:1 on white
    'gold_dim':  '#F7EED9',
    'text':      '#0C1828',
    'text2':     '#2E4460',   # stronger secondary for labels
    'muted':     '#4F667F',   # 5.0:1 on panel, 5.9:1 on white
    'disabled':  '#C0CCD8',
    'ok':        '#006B48',
    'ok_lt':     '#00805A',
    'ok_dk':     '#00543A',
    'ok_dim':    '#E6F5EF',
    'warn':      '#A05800',
    'warn_dim':  '#F7EED9',
    'err':       '#B81C2C',
    'err_lt':    '#C81F30',
    'err_dk':    '#94151F',
    'err_dim':   '#FDECEA',
    'info':      '#1850A8',
    'info_dim':  '#E8EEF8',
    'border':    '#CDD8E8',
    'border2':   '#68849F',   # control boundaries — 3.3:1 on panel, 3.9:1 on white
    'sep':       '#E0E8F0',
    'divider':   '#CDD8E8',
    'focus':     '#8F5600',
    'on_danger': '#FFFFFF',
    'on_success':'#FFFFFF',
    'primary':   '#8F5600',
    'success':   '#006B48',
    'warning':   '#A05800',
    'danger':    '#B81C2C',
}

# Radius scale — brief: 6 / 8 / 12 / 16 / 20
RADIUS = {
    'sm': 6,
    'md': 8,
    'lg': 12,
    'xl': 16,
    '2xl': 20,
}

# POS layout rhythm (PyQt5 modular redesign) — spacing 8/12/16/20/24/32
PADDING = 20
GAP = 16
ANIMATION_MS = 180
TOUCH_MIN = 44  # touch-friendly control minimum height/width where practical

_FONT_LOADED = False
_FONT_FAMILY = "'Segoe UI', 'Inter', Arial, sans-serif"


def _assets_root():
    """Resolve bundled assets/ next to project root or PyInstaller MEIPASS."""
    if getattr(sys, 'frozen', False):
        base = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
        for cand in (
            os.path.join(base, 'assets'),
            os.path.join(base, 'desktop', 'assets'),
            os.path.join(os.path.dirname(sys.executable), 'assets'),
        ):
            if os.path.isdir(cand):
                return cand
    here = os.path.dirname(os.path.abspath(__file__))
    # desktop/utils → mbt_pos/assets
    root = os.path.dirname(os.path.dirname(here))
    return os.path.join(root, 'assets')


def ensure_fonts():
    """
    Load Manrope from assets/fonts when present.
    Safe no-op if files missing or Qt not ready — callers fall back to Segoe UI.
    Retries once QApplication exists if first attempt was too early.
    """
    global _FONT_LOADED, _FONT_FAMILY
    if _FONT_LOADED:
        return _FONT_FAMILY
    try:
        from PyQt5.QtGui import QFontDatabase, QFont
        from PyQt5.QtWidgets import QApplication
        # Prefer loading after QApplication exists (more reliable on Windows)
        if QApplication.instance() is None:
            return _FONT_FAMILY
        fonts_dir = os.path.join(_assets_root(), 'fonts')
        loaded = []
        if os.path.isdir(fonts_dir):
            for name in (
                'Manrope-Regular.ttf', 'Manrope-Medium.ttf',
                'Manrope-SemiBold.ttf', 'Manrope-Bold.ttf',
                'Manrope-ExtraBold.ttf',
            ):
                path = os.path.join(fonts_dir, name)
                if os.path.isfile(path):
                    fid = QFontDatabase.addApplicationFont(path)
                    if fid >= 0:
                        families = QFontDatabase.applicationFontFamilies(fid)
                        if families:
                            loaded.append(families[0])
        _FONT_LOADED = True
        if loaded:
            fam = loaded[0]
            _FONT_FAMILY = f"'{fam}', 'Segoe UI', 'Inter', Arial, sans-serif"
            QApplication.instance().setFont(QFont(fam, 13))
    except Exception:
        _FONT_LOADED = True
    return _FONT_FAMILY


def font_stack():
    """CSS font-family string for QSS (Manrope if loaded)."""
    ensure_fonts()
    return _FONT_FAMILY

# Active palette — starts dark, toggled by ThemeManager
C = dict(DARK)

COLORS = {
    'accent': C['gold'], 'success': C['ok'], 'danger': C['err'],
    'warning': C['warn'], 'info': C['info'],
    'text_primary': C['text'], 'text_secondary': C['text2'],
    'text_muted': C['muted'], 'bg_card': C['card'],
    'bg_sidebar': C['sidebar'], 'border': C['border'],
    'border_strong': C['border2'],
}


# ══════════════════════════════════════════════════════════════════════════════
# Themed inline-style registry
# ══════════════════════════════════════════════════════════════════════════════
# Widget-level QSS is written with the palette that happens to be live when the
# widget is built (``setStyleSheet(f"color:{C['text2']}")``).  Those hexes freeze:
# a tab built in dark mode keeps dark ink after switching to light.
#
# Instead of rewriting hexes after the fact (which cannot tell ``#FFFFFF`` used
# as a card background from ``#FFFFFF`` used as danger-button ink), every
# stylesheet is converted to a *token template* at the moment it is applied,
# while the palette that produced it is still known.  The template is stored on
# the widget and re-rendered from the live palette on every theme change, so the
# transform is lossless and idempotent.
#
#   setStyleSheet("color:#B4C2D6")  ->  template "color:@@text2@@"
#   theme switch                    ->  "color:#2E4460"
#
# Hexes that cannot be attributed to a single token (and whose candidates would
# render very differently) are deliberately left literal rather than guessed.

QSS_TEMPLATE_PROPERTY = 'mbtQssTpl'
QSS_STATIC_PROPERTY = 'mbtQssStatic'
QSS_GEN_PROPERTY = 'mbtQssGen'
QSS_STALE_PROPERTY = 'mbtQssStale'

_TOKEN_RE = re.compile(r'@@([a-z0-9_]+)(![a-z]+)?@@')
_COLOR_RE = re.compile(
    r'#[0-9A-Fa-f]{8}(?![0-9A-Fa-f])'
    r'|#[0-9A-Fa-f]{6}(?![0-9A-Fa-f])'
    r'|rgba?\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*(?:,\s*[\d.]+\s*)?\)'
)
_BG_DECL_RE = re.compile(
    r'(?:^|[;{])\s*(?:background|background-color)\s*:([^;}]*)', re.IGNORECASE)
_BLOCK_RE = re.compile(r'\{[^{}]*\}')

# Which palette tokens may legitimately appear behind a given CSS property.
_INK_TOKENS = frozenset({
    'text', 'text2', 'muted', 'disabled', 'gold', 'gold_lt', 'gold_dk',
    'gold_fg', 'gold_ink', 'ok', 'warn', 'err', 'info', 'on_danger',
    'on_success', 'primary', 'success', 'warning', 'danger',
})
_SURFACE_TOKENS = frozenset({
    'app', 'surface', 'panel', 'card', 'card2', 'sidebar', 'input', 'hover',
    'selected', 'disabled', 'gold_dim', 'ok_dim', 'warn_dim', 'err_dim',
    'info_dim', 'sep', 'gold', 'ok', 'ok_lt', 'ok_dk', 'warn', 'err',
    'err_lt', 'err_dk', 'info', 'primary', 'success', 'warning', 'danger',
})
_BORDER_TOKENS = frozenset({
    'border', 'border2', 'divider', 'sep', 'focus', 'gold', 'gold_lt',
    'gold_dk', 'ok', 'warn', 'err', 'info', 'muted', 'disabled', 'primary',
    'success', 'warning', 'danger',
})
# Preference order used when several tokens share a hex and agree on the result.
_INK_ORDER = (
    'text', 'text2', 'muted', 'gold', 'gold_lt', 'gold_dk', 'ok', 'warn',
    'err', 'info', 'gold_fg', 'on_danger', 'on_success', 'disabled',
    'primary', 'success', 'warning', 'danger', 'gold_ink',
)
_SURFACE_ORDER = (
    'card', 'panel', 'card2', 'surface', 'input', 'app', 'sidebar', 'hover',
    'selected', 'gold_dim', 'ok_dim', 'warn_dim', 'err_dim', 'info_dim',
    'disabled', 'sep', 'gold', 'ok', 'warn', 'err', 'info', 'ok_lt', 'ok_dk',
    'err_lt', 'err_dk',
)
_BORDER_ORDER = (
    'border', 'border2', 'divider', 'sep', 'gold', 'focus', 'gold_lt',
    'gold_dk', 'ok', 'warn', 'err', 'info', 'muted', 'disabled',
)
_CATEGORY = {
    'ink': (_INK_TOKENS, _INK_ORDER),
    'surface': (_SURFACE_TOKENS, _SURFACE_ORDER),
    'border': (_BORDER_TOKENS, _BORDER_ORDER),
}
# Saturated fills that carry "on-tone" ink instead of body text.
_GOLDISH = frozenset({'gold', 'gold_lt', 'gold_dk', 'primary', 'focus',
                      'warn', 'warning'})
_DANGERISH = frozenset({'err', 'danger', 'err_lt', 'err_dk'})
_SUCCESSISH = frozenset({'ok', 'success', 'ok_lt', 'ok_dk'})
_TONE_TOKENS = _GOLDISH | _DANGERISH | _SUCCESSISH | {'info'}

# Two candidate results this close are visually interchangeable, so an
# otherwise ambiguous hex can still be tokenised.
_CLOSE_ENOUGH = 56

_theme_generation = 0
_index_generation = -1
_hex_tokens: dict = {}
_other_palette: dict = {}
_in_restyle = False


def _rebuild_style_index():
    """Cache hex -> token lookups for the live palette and its counterpart."""
    global _index_generation, _hex_tokens, _other_palette
    live_is_light = C.get('app') == LIGHT.get('app')
    _other_palette = dict(DARK if live_is_light else LIGHT)
    table: dict = {}
    for token, value in C.items():
        if not isinstance(value, str) or len(value) != 7 or value[0] != '#':
            continue
        if token not in _other_palette:
            continue
        table.setdefault(value.lower(), []).append(token)
    _hex_tokens = table
    _index_generation = _theme_generation


def _ensure_style_index():
    if _index_generation != _theme_generation or not _hex_tokens:
        _rebuild_style_index()


def _close_enough(values) -> bool:
    vals = [v for v in values if isinstance(v, str) and len(v) == 7]
    if len(vals) != len(list(values)):
        return False
    rgbs = [_parse_hex(v) for v in vals]
    for i in range(len(rgbs)):
        for j in range(i + 1, len(rgbs)):
            if max(abs(a - b) for a, b in zip(rgbs[i], rgbs[j])) > _CLOSE_ENOUGH:
                return False
    return True


def _pick(pool, order):
    for token in order:
        if token in pool:
            return token
    return pool[0]


def _classify_property(prop: str) -> str:
    p = (prop or '').strip().lower()
    if 'background' in p:
        return 'surface'
    if 'border' in p or 'gridline' in p or 'outline' in p:
        return 'border'
    if p.endswith('color'):
        return 'ink'
    return 'ink'


def _resolve_token(hex_lc: str, category: str, bg_token, bg_opaque=True):
    """Map a literal hex to the palette token it was almost certainly built from."""
    candidates = _hex_tokens.get(hex_lc)
    if not candidates:
        return None
    allowed, order = _CATEGORY.get(category, _CATEGORY['ink'])
    pool = [t for t in candidates if t in allowed] or list(candidates)
    on_tone = bool(bg_token) and bg_token in _TONE_TOKENS and bg_opaque
    if category == 'ink' and on_tone:
        if bg_token in _GOLDISH and 'gold_fg' in pool:
            return 'gold_fg'
        if bg_token in _DANGERISH and 'on_danger' in pool:
            return 'on_danger'
        if bg_token in _SUCCESSISH and 'on_success' in pool:
            return 'on_success'
    # Accent ink on a translucent tint of itself (chips, cue strips, selected
    # pills): the tint-specific ink token is the one designed to stay legible
    # once the surface underneath flips.
    if (category == 'ink' and bg_token in _GOLDISH and not bg_opaque
            and 'gold_ink' in pool):
        return 'gold_ink'
    results = {_other_palette.get(t) for t in pool}
    if len(results) == 1:
        return _pick(pool, order)
    if category == 'ink':
        if on_tone:
            # Ink sitting on a saturated fill — guessing here is how white
            # button text ends up dark navy on a red button.  Leave it alone.
            return None
        if 'text' in pool:
            return 'text'
    if _close_enough(results):
        return _pick(pool, order)
    return None


def _hex_from_match(text: str):
    """Return (rgb_hex_lower, kind, alpha_prefix/suffix) for a colour match."""
    if text.startswith('#'):
        body = text[1:]
        if len(body) == 8:
            return '#' + body[2:].lower(), 'hex8', body[:2]
        return text.lower(), 'hex6', ''
    inner = text[text.index('(') + 1:text.rindex(')')]
    parts = [p.strip() for p in inner.split(',')]
    if len(parts) < 3:
        return None, None, ''
    try:
        r, g, b = (int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return None, None, ''
    alpha = parts[3] if len(parts) > 3 else None
    return '#%02x%02x%02x' % (r, g, b), 'rgb', alpha


def _block_spans(sheet: str):
    """(start, end, bg_token, bg_opaque) for every declaration block."""
    spans = []
    for m in _BLOCK_RE.finditer(sheet):
        spans.append((m.start() + 1, m.end() - 1))
    if not spans:
        spans = [(0, len(sheet))]
    out = []
    for start, end in spans:
        token, opaque = _background_token(sheet[start:end])
        out.append((start, end, token, opaque))
    return out


def _background_token(block: str):
    """(token, opaque) for a block's background, or (None, True) if unknown.

    Opacity matters: ink on a *solid* status fill is on-tone ink, while ink on
    a 12% tint of the same colour is accent ink on the page surface.  Treating
    both the same is how a gold caption on a gold tint ended up frozen.
    """
    m = _BG_DECL_RE.search(block)
    if not m:
        return None, True
    value = m.group(1)
    cm = _COLOR_RE.search(value)
    if not cm:
        return None, True
    text = cm.group(0)
    hex_lc, kind, alpha = _hex_from_match(text)
    if not hex_lc:
        return None, True
    opaque = True
    if kind == 'hex8':
        opaque = int(alpha, 16) >= 128
    elif kind == 'rgb' and alpha is not None:
        # Qt QSS `rgba()` takes 0-255, CSS takes 0-1, and `qss_alpha` emits the
        # Qt form — accept both rather than reading `31` as fully opaque.
        try:
            value = float(alpha)
        except ValueError:
            value = 255.0
        opaque = (value >= 0.5) if '.' in alpha else (value >= 128)
    tokens = _hex_tokens.get(hex_lc)
    if not tokens:
        return None, opaque
    for token in tokens:
        if token in _TONE_TOKENS:
            return token, opaque
    return tokens[0], opaque


def _property_at(sheet: str, block_start: int, pos: int) -> str:
    head = sheet[block_start:pos]
    cut = max(head.rfind(';'), head.rfind('{'), head.rfind('}'))
    decl = head[cut + 1:]
    colon = decl.find(':')
    return decl[:colon] if colon >= 0 else decl


def tokenize_style(sheet: str):
    """Convert a rendered stylesheet into a ``@@token@@`` template.

    Returns ``None`` when the sheet holds no colour that belongs to the live
    palette (nothing to keep in sync).
    """
    if not sheet:
        return None
    if '#' not in sheet and 'rgb' not in sheet:
        return None
    _ensure_style_index()
    if not _hex_tokens:
        return None
    blocks = _block_spans(sheet)
    out = []
    cursor = 0
    changed = False
    for match in _COLOR_RE.finditer(sheet):
        start, end = match.span()
        block_start, block_bg, block_opaque = 0, None, True
        for bs, be, bg, opaque in blocks:
            if bs <= start < be:
                block_start, block_bg, block_opaque = bs, bg, opaque
                break
        hex_lc, kind, alpha = _hex_from_match(match.group(0))
        if not hex_lc:
            continue
        category = _classify_property(_property_at(sheet, block_start, start))
        token = _resolve_token(hex_lc, category, block_bg, block_opaque)
        if not token:
            continue
        if kind == 'hex6':
            repl = f'@@{token}@@'
        elif kind == 'hex8':
            repl = f'#{alpha}@@{token}!raw@@'
        else:
            repl = (f'rgba(@@{token}!rgb@@, {alpha})' if alpha is not None
                    else f'rgb(@@{token}!rgb@@)')
        out.append(sheet[cursor:start])
        out.append(repl)
        cursor = end
        changed = True
    if not changed:
        return None
    out.append(sheet[cursor:])
    return ''.join(out)


def render_style(template: str) -> str:
    """Render a ``@@token@@`` template against the live palette."""
    def _sub(match):
        token, kind = match.group(1), match.group(2)
        value = C.get(token)
        if not value:
            return match.group(0)
        if kind == '!raw':
            return value.lstrip('#')
        if kind == '!rgb':
            r, g, b = _parse_hex(value)
            return f'{r}, {g}, {b}'
        return value
    return _TOKEN_RE.sub(_sub, template)


def _relative_luminance(color: str) -> float:
    def _lin(channel: int) -> float:
        c = channel / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = _parse_hex(color)
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast_ratio(fg: str, bg: str) -> float:
    """WCAG 2.1 contrast ratio between two opaque colours."""
    try:
        a, b = _relative_luminance(fg), _relative_luminance(bg)
    except Exception:
        return 0.0
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def readable_ink(preferred: str, bg: str, minimum: float = 4.5,
                 fallback: str = None) -> str:
    """`preferred` when it is legible on `bg`, otherwise body text.

    Accent tones double as borders and fills where a lower ratio is fine, but
    the same tone used as text can fall below the minimum (bright dark-mode
    green on a card, light-mode blue on navy).
    """
    if preferred and contrast_ratio(preferred, bg) >= minimum:
        return preferred
    return fallback or C['text']


def accent_ref(value):
    """Convert a palette colour into a token name that survives a theme change.

    Components that cache an accent (`self._accent = C['ok']`) replay that
    frozen hex on every refresh, which is how a dark-theme KPI tile kept
    painting bright green on a white card.  Storing the token name instead
    means the colour is resolved from the live palette each time.
    Unknown colours (per-category brand accents) are returned unchanged.
    """
    if not value:
        return ''
    text = str(value).lower()
    for palette in (C, DARK, LIGHT):
        for token, token_value in palette.items():
            if isinstance(token_value, str) and token_value.lower() == text:
                return token
    return str(value)


def accent_value(ref, default=None):
    """Resolve an `accent_ref` against the live palette."""
    if not ref:
        return default
    return C.get(ref, ref)


def mark_style_static(widget) -> None:
    """Opt a widget out of theme-tracking (keeps its literal colours forever)."""
    try:
        widget.setProperty(QSS_STATIC_PROPERTY, True)
        widget.setProperty(QSS_TEMPLATE_PROPERTY, None)
    except Exception:
        pass


def _capture_style(widget, sheet):
    """Record the token template behind `sheet` so theme changes can replay it."""
    try:
        if widget.property(QSS_STATIC_PROPERTY):
            return
        template = tokenize_style(sheet)
        widget.setProperty(QSS_TEMPLATE_PROPERTY, template or None)
        # The caller just painted with the live palette, so this template is
        # already current — do not re-render it on the next toggle-in-flight.
        widget.setProperty(QSS_GEN_PROPERTY, _theme_generation)
    except Exception:
        pass


def apply_themed_style(widget, template: str) -> None:
    """Apply a ``@@token@@`` template directly (bypasses hex inference)."""
    global _in_restyle
    if widget is None:
        return
    rendered = render_style(template)
    prev, _in_restyle = _in_restyle, True
    try:
        widget.setStyleSheet(rendered)
    finally:
        _in_restyle = prev
    try:
        widget.setProperty(QSS_TEMPLATE_PROPERTY, template)
        widget.setProperty(QSS_GEN_PROPERTY, _theme_generation)
    except Exception:
        pass


def _mark_stale(widget) -> None:
    """Flag `widget` and its ancestors as holding an unrendered template.

    The ancestor trail is what makes the show-time catch-up cheap: a Show
    event only has to look at one property to know whether anything below it
    still needs re-rendering.
    """
    node = widget
    while node is not None:
        try:
            node.setProperty(QSS_STALE_PROPERTY, _theme_generation)
            node = node.parentWidget()
        except (RuntimeError, TypeError):
            return


def restyle_themed_widgets(root=None, visible_only: bool = False) -> int:
    """Re-render every tracked inline stylesheet from the live palette.

    `root` limits the walk to one subtree; the default covers the whole
    application, including dialogs and lazily built tabs.  With
    `visible_only`, off-screen widgets are only flagged, and are re-rendered
    by `_restyle_on_show` the moment they become visible — that is what keeps
    a theme toggle proportional to what the user can actually see instead of
    to every tab ever warmed.
    """
    global _in_restyle
    try:
        from PyQt5 import sip
        from PyQt5.QtWidgets import QApplication
    except Exception:
        return 0
    if root is not None and hasattr(root, 'findChildren'):
        from PyQt5.QtWidgets import QWidget
        widgets = [root] + root.findChildren(QWidget)
    else:
        app = QApplication.instance()
        if app is None:
            return 0
        widgets = app.allWidgets()
    gen = _theme_generation
    now, deferred = [], []
    # Two phases: clearing the stale trail while it is still being rebuilt
    # would drop markers for ancestors visited later in this arbitrary order.
    for widget in widgets:
        try:
            if sip.isdeleted(widget):
                continue
            if widget.property(QSS_STALE_PROPERTY) is not None:
                widget.setProperty(QSS_STALE_PROPERTY, None)
            template = widget.property(QSS_TEMPLATE_PROPERTY)
            if not template or widget.property(QSS_GEN_PROPERTY) == gen:
                continue
            # `isVisibleTo(window)` rather than `isVisible()`: it means "on
            # screen if this window is", so a non-current stack page is
            # deferred while a widget in a not-yet-mapped window is still
            # painted before it appears.
            if visible_only and not widget.isVisibleTo(widget.window()):
                deferred.append(widget)
            else:
                now.append((widget, template))
        except (RuntimeError, TypeError):
            continue

    count = 0
    prev, _in_restyle = _in_restyle, True
    try:
        for widget, template in now:
            try:
                if sip.isdeleted(widget):
                    continue
                rendered = render_style(template)
                if rendered != widget.styleSheet():
                    widget.setStyleSheet(rendered)
                    count += 1
                widget.setProperty(QSS_GEN_PROPERTY, gen)
            except (RuntimeError, TypeError):
                continue
    finally:
        _in_restyle = prev
    for widget in deferred:
        try:
            if not sip.isdeleted(widget):
                _mark_stale(widget)
        except (RuntimeError, TypeError):
            continue
    return count


_theme_hooks = []


def register_theme_hook(fn) -> None:
    """Run `fn()` after every palette change, once the QSS has been applied.

    Used for state that lives outside stylesheets (item view roles, painted
    chrome) and therefore cannot be replayed from a style template.
    """
    if fn not in _theme_hooks:
        _theme_hooks.append(fn)


def _run_theme_hooks() -> None:
    for fn in list(_theme_hooks):
        try:
            fn()
        except Exception:
            pass


_capture_installed = False


def install_style_capture() -> bool:
    """Make ``QWidget.setStyleSheet`` theme-aware application-wide.

    Every inline stylesheet is stored as a palette-token template next to the
    widget, which is what lets ``restyle_themed_widgets`` repaint surfaces the
    object-name/dynamic-property handlers never knew about (POS panels, the
    wizard, activation, one-off dialog chrome).
    """
    global _capture_installed
    if _capture_installed:
        return True
    if os.environ.get('MBT_NO_THEME_CAPTURE'):
        return False
    try:
        from PyQt5.QtWidgets import QWidget
    except Exception:
        return False
    original = QWidget.setStyleSheet

    def setStyleSheet(self, sheet):  # noqa: N802 — Qt API name
        original(self, sheet)
        if not _in_restyle:
            _capture_style(self, sheet)

    setStyleSheet.__doc__ = original.__doc__
    setStyleSheet._mbt_original = original
    try:
        QWidget.setStyleSheet = setStyleSheet
    except (AttributeError, TypeError):
        return False
    _capture_installed = True
    return True


_show_catch_up = None


def install_show_catch_up() -> bool:
    """Re-render deferred templates the instant an off-screen surface appears.

    A toggle only repaints what is visible; this is the other half of that
    deal, so a lazily warmed tab or a dialog constructed under the previous
    palette still shows up fully themed rather than one frame late.
    """
    global _show_catch_up
    if _show_catch_up is not None:
        return True
    try:
        from PyQt5.QtCore import QEvent, QObject
        from PyQt5.QtWidgets import QApplication
    except Exception:
        return False
    app = QApplication.instance()
    if app is None:
        return False

    show_type = QEvent.Show

    class ShowCatchUp(QObject):
        def eventFilter(self, obj, event):  # noqa: N802 — Qt API name
            try:
                if event.type() == show_type and not _in_restyle:
                    if obj.property(QSS_STALE_PROPERTY) == _theme_generation:
                        restyle_themed_widgets(obj)
            except (RuntimeError, TypeError, AttributeError):
                pass
            return False

    try:
        _show_catch_up = ShowCatchUp(app)
        app.installEventFilter(_show_catch_up)
    except Exception:
        _show_catch_up = None
        return False
    return True


def _calendar_icon_qss() -> str:
    """QDateEdit drop-down affordance — calendar SVG when bundled, else chevron."""
    path = os.path.join(_assets_root(), 'icons', 'calendar.svg')
    if os.path.isfile(path):
        url = path.replace('\\', '/')
        return (
            f"image: url(\"{url}\");"
            f"width: 14px; height: 14px;"
            f"border: none; margin-right: 6px;"
        )
    return (
        "image: none; width: 0; height: 0;"
        f"border-left: 5px solid transparent;"
        f"border-right: 5px solid transparent;"
        f"border-top: 6px solid {{p_muted}};"
        f"margin-right: 8px;"
    )


def biz_day_button_qss(*, date_width: int | None = None, micro: bool = False) -> str:
    """Widget-level QSS for the POS business-day picker button.

    Applied directly on ``_BizDayButton`` so the outline survives the global
    ``QPushButton {{ border: none; }}`` / ``QFrame {{ border: none; }}`` rules.
    """
    p = C
    r_md = RADIUS['md']
    gold_border_hover = qss_alpha(p['gold'], 0.45)
    min_h = 32 if micro else 34

    if micro:
        dw = date_width or 104
        width_block = f"min-width:{dw}px;max-width:{max(dw + 40, 144)}px;"
        pad = "padding:3px 10px;font-size:11px;"
    elif date_width is not None and date_width < 130:
        dw = date_width
        width_block = f"min-width:{dw}px;max-width:{max(dw + 80, 160)}px;"
        pad = "padding:4px 12px;font-size:12px;"
    elif date_width is not None:
        width_block = f"min-width:{date_width}px;"
        pad = "padding:6px 14px;font-size:13px;"
    else:
        width_block = "min-width:220px;"
        pad = "padding:6px 14px;font-size:13px;"

    return f"""
QPushButton#posBizDayBtn {{
    background-color: transparent;
    color: {p['text']};
    border: 1px solid {p['border2']};
    border-radius: {r_md}px;
    min-height: {min_h}px;
    text-align: left;
    font-weight: 600;
    {width_block}
    {pad}
}}
QPushButton#posBizDayBtn:hover {{
    background-color: {p['hover']};
    border-color: {gold_border_hover};
    color: {p['text']};
}}
QPushButton#posBizDayBtn:pressed {{
    background-color: {p['hover']};
    border-color: {p['gold']};
}}
QPushButton#posBizDayBtn:focus {{
    outline: none;
    border-color: {p['gold']};
    background-color: {p['hover']};
}}
QPushButton#posBizDayBtn:disabled {{
    color: {p['muted']};
    border-color: {p['border']};
    background-color: {p['panel']};
}}
"""


def biz_day_picker_qss(*, date_width: int | None = None, micro: bool = False) -> str:
    """Backward-compatible alias — prefer ``biz_day_button_qss``."""
    return biz_day_button_qss(date_width=date_width, micro=micro)


def _build_stylesheet(p):
    """Build the full QSS stylesheet from palette p (Lovable-aligned)."""
    ff = font_stack()
    r_md, r_lg, r_xl = RADIUS['md'], RADIUS['lg'], RADIUS['xl']
    # Lovable cards use rounded-xl (14px)
    r_card = RADIUS['xl']
    gold_fg = p.get('gold_fg', '#0A0F1A')
    gold_border_hover = qss_alpha(p['gold'], 0.45)
    gold_border_soft = qss_alpha(p['gold'], 0.35)
    gold_tint = qss_alpha(p['gold'], 0.14)
    nav_hover_soft = qss_alpha(p['hover'], 0.55)
    # Single source of truth for the shell gutter width — the handle paints
    # itself against this rect, so QSS and the widget must never disagree.
    from desktop.utils.shell_splitter import HANDLE_W as shell_handle_w
    cal_arrow = _calendar_icon_qss().replace('{p_muted}', p['muted'])
    check_path = os.path.join(_assets_root(), 'icons', 'ui', 'check.svg')
    radio_path = os.path.join(_assets_root(), 'icons', 'ui', 'radio-dot.svg')
    check_url = check_path.replace('\\', '/') if os.path.isfile(check_path) else ''
    radio_url = radio_path.replace('\\', '/') if os.path.isfile(radio_path) else ''
    return f"""
* {{
    font-family: {ff};
    font-size: 14px;
    color: {p['text']};
    outline: none;
}}
/* Lovable: app shell outer = --app, main column = --surface.
   This reset MUST stay above the window rules below: QWidget and QDialog are
   both plain type selectors, so they have equal specificity and the LAST rule
   wins.  With the reset last, every top-level QDialog inherited a transparent
   background and painted as raw black on Windows. */
QWidget {{ background: transparent; border: none; }}
QMainWindow {{ background: {p['app']}; border: none; }}
QDialog {{ background: {p['surface']}; border: none; }}
#appRoot {{ background: {p['app']}; }}
#content, #pageStack, #mbtPageInner {{
    background: {p['surface']};
}}
QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QFrame {{ border: none; }}
/* POS business-day picker — explicit ID beats global border resets on Windows */
QFrame#posBusinessDayBar QPushButton#posBizDayBtn {{
    background-color: transparent;
    border: 1px solid {p['border2']};
    border-radius: {r_md}px;
    min-height: 34px;
    text-align: left;
    font-weight: 600;
}}

/* ── SIDEBAR (AppShell) ── */
/* Width is owned by MainWindow._apply_sidebar_state (collapse + QSplitter drag).
   A min-width/max-width here would fight the splitter, so only paint lives in QSS. */
#sidebar {{
    background: {p['sidebar']};
    border-right: 1px solid {p['border']};
}}
/* The gutter is painted by ShellSplitterHandle (track + grip pill + gold hover)
   so it stays visible on both themes. QSS only reserves the width — a background
   here would paint over the grip and we would be back to a bare divider line. */
#shellSplitter::handle:horizontal {{
    background: transparent;
    width: {shell_handle_w}px;
    margin: 0px;
    padding: 0px;
}}
#sidebarLogo {{
    background: {p['sidebar']};
    min-height: 80px; max-height: 80px;
    border-bottom: 1px solid {p['border']};
}}
/* Reads as a button, not a bare icon: a filled chip on the sidebar fill with a
   control-grade border. ``border``/transparent was near-invisible on both themes. */
#sidebarToggle {{
    background: {p['card']};
    border: 1px solid {p['border2']};
    border-radius: {r_md}px;
    min-width: 32px; max-width: 32px;
    min-height: 32px; max-height: 32px;
    padding: 0px;
}}
#sidebarToggle:hover {{
    background: {gold_tint};
    border: 1px solid {p['gold']};
}}
#sidebarToggle:pressed {{
    background: {nav_hover_soft};
    border: 1px solid {p['gold']};
}}
#sidebarToggle:focus {{
    border: 1px solid {p['gold']};
}}
#sidebarLogoText {{
    color: {p['gold']};
    font-size: 18px; font-weight: 800; letter-spacing: 1px;
    background: transparent;
}}
#sidebarLogoSub {{
    color: {p['text2']};
    font-size: 10px; letter-spacing: 2.5px; font-weight: 700;
    background: transparent;
}}
#navBtn {{
    background: transparent;
    color: {p['text2']};
    border: none;
    border-left: 3px solid transparent;
    padding: 10px 12px 10px 13px;
    text-align: left;
    font-size: 13px; font-weight: 500;
    border-radius: {r_lg}px;
    margin: 2px 10px;
    min-height: 44px;
}}
#navBtn:hover {{
    background: {nav_hover_soft};
    color: {p['text']};
}}
#navBtn:checked {{
    background: {gold_tint};
    color: {p['gold']};
    font-weight: 700;
    border-left: 3px solid {p['gold']};
    padding-left: 13px;
}}
#navBtn:checked:hover {{
    background: {gold_tint};
    color: {p['gold']};
}}
/* Icon-only rail. Same object name + :checked highlight as expanded mode, so the
   active section stays identifiable and role gating is untouched. */
#navBtn[navCollapsed="true"] {{
    padding: 10px 0px 10px 0px;
    text-align: center;
    margin: 2px 6px;
    min-height: 44px;
}}
#navBtn[navCollapsed="true"]:checked {{
    padding-left: 0px;
}}
#sidebarUser {{
    background: {p['panel']};
    border-top: 1px solid {p['border']};
    min-height: 92px;
}}
#sidebarUserName {{
    color: {p['text']};
    font-size: 13px; font-weight: 600;
    background: transparent;
}}
#sidebarUserRole {{
    color: {p['gold']};
    font-size: 10px; letter-spacing: 2px; font-weight: 700;
    background: transparent;
}}
#logoutBtn {{
    background: {p['card']};
    color: {p['text']};
    border: 1px solid {p['border']};
    border-radius: {r_md}px;
    padding: 8px 12px;
    font-size: 13px;
    margin-top: 6px;
    min-height: 40px;
}}
#logoutBtn:hover {{
    color: {p['err']};
    border-color: {p['err']};
    background: {p['err_dim']};
}}
#logoutBtn[navCollapsed="true"] {{
    padding: 8px 0px;
    margin-top: 0px;
}}
#sidebarUser[navCollapsed="true"] {{
    min-height: 0px;
}}

/* ── TOPBAR ── */
#topbar {{
    background: {p['panel']};
    border-bottom: 1px solid {p['border']};
    min-height: 56px; max-height: 56px;
}}
#pageTitle {{
    color: {p['text']};
    font-size: 16px; font-weight: 700;
    letter-spacing: -0.3px;
    background: transparent;
}}
#mbtPageChrome {{
    background: transparent;
    border: none;
}}
#mbtToolbar {{
    background: transparent;
    border: none;
}}
QFrame#mbtCard {{
    background: {p['card']};
    border: 1px solid {p['border']};
    border-radius: {r_card}px;
}}
#connBadge {{
    font-size: 12px; font-weight: 600;
    padding: 4px 10px;
    border-radius: {r_md}px;
    background: transparent;
}}
#syncLbl  {{ color: {p['text2']}; font-size: 12px; background: transparent; }}
#clockLbl {{
    color: {p['text2']};
    font-size: 12px;
    font-family: 'Consolas', 'JetBrains Mono', 'Courier New', monospace;
    background: transparent; padding: 0 8px;
    border-left: 1px solid {p['border']};
}}
#refreshBtn {{
    background: {p['card']};
    color: {p['text']};
    border: 1px solid {p['border']};
    border-radius: {r_md}px;
    padding: 6px 12px;
    font-size: 13px; font-weight: 500;
    min-height: 36px;
}}
#refreshBtn:hover {{ color: {p['text']}; background: {p['hover']}; border-color: {gold_border_hover}; }}
#themeBtn {{
    background: {p['card']};
    color: {p['text']};
    border: 1px solid {p['border']};
    border-radius: {r_md}px;
    font-size: 12px; font-weight: 500;
    min-height: 36px;
}}
#themeBtn:hover {{ border-color: {p['gold']}; color: {p['gold']}; }}

/* ── STATUSBAR / FOOTER ── */
#statusBar {{
    background: {p['panel']};
    border-top: 1px solid {p['border']};
    min-height: 36px; max-height: 36px;
}}
QWidget#statusBar {{
    background-color: {p['panel']};
    border-top: 1px solid {p['border']};
}}
#statusLeft  {{ color: {p['text2']}; font-size: 11px; background: transparent; }}
#statusRight {{
    color: {p['text2']}; font-size: 11px; background: transparent;
    font-family: 'Consolas', 'JetBrains Mono', 'Courier New', monospace;
}}
#pageStack   {{ background: {p['surface']}; }}
#content     {{ background: {p['surface']}; }}

/* ── BUTTONS ── */
QPushButton {{
    background: {p['card2']};
    color: {p['text']};
    border: 1px solid {p['border2']};
    border-radius: {r_md}px;
    padding: 8px 16px;
    font-size: 13px; font-weight: 500;
    min-height: 36px;
}}
QPushButton:hover   {{ background: {p['hover']}; color: {p['text']}; border-color: {gold_border_soft}; }}
QPushButton:pressed {{ background: {p['app']}; color: {p['text']}; }}
QPushButton:disabled {{ background: {p['panel']}; color: {p['muted']}; border-color: {p['border2']}; }}

QPushButton#primaryBtn, QPushButton[objectName="primaryBtn"] {{
    background: {p['gold']};
    color: {gold_fg};
    border: none;
    font-weight: 700; font-size: 13px;
    border-radius: {r_md}px;
    letter-spacing: 0.2px;
}}
QPushButton#primaryBtn:hover, QPushButton[objectName="primaryBtn"]:hover {{
    background: {p['gold_lt']}; color: {gold_fg};
}}
QPushButton#primaryBtn:pressed, QPushButton[objectName="primaryBtn"]:pressed {{
    background: {p['gold_dk']}; color: {gold_fg};
}}
QPushButton#primaryBtn:disabled, QPushButton[objectName="primaryBtn"]:disabled {{
    /* `border2` is a boundary tone, far too light to carry `muted` ink
       (1.5:1 in light mode). The panel surface keeps the label readable. */
    background: {p['panel']}; color: {p['muted']};
    border: 1px solid {p['border']};
}}
QPushButton[objectName="successBtn"] {{
    background: {p['ok']}; color: {p['on_success']}; border: none; font-weight: 600; border-radius: {r_md}px;
}}
QPushButton[objectName="successBtn"]:hover {{ background: {p['ok_lt']}; color: {p['on_success']}; }}
QPushButton[objectName="successBtn"]:pressed {{ background: {p['ok_dk']}; color: {p['on_success']}; }}
QPushButton[objectName="dangerBtn"]  {{
    background: {p['err']}; color: {p['on_danger']}; border: none; font-weight: 600; border-radius: {r_md}px;
}}
QPushButton[objectName="dangerBtn"]:hover {{ background: {p['err_lt']}; color: {p['on_danger']}; }}
QPushButton[objectName="dangerBtn"]:pressed {{ background: {p['err_dk']}; color: {p['on_danger']}; }}
QPushButton[objectName="ghostBtn"] {{
    background: transparent; color: {p['text2']};
    border: none; border-radius: {r_md}px; font-weight: 500;
}}
QPushButton[objectName="ghostBtn"]:hover {{
    background: {p['hover']}; color: {p['text']};
}}
QPushButton[objectName="outlineBtn"] {{
    background: transparent; color: {p['text']};
    border: 1px solid {p['border2']}; border-radius: {r_md}px; font-weight: 500;
}}
QPushButton[objectName="outlineBtn"]:hover {{
    background: {p['hover']}; border-color: {gold_border_hover};
}}
/* Section pills (Settings "Jump:" row). Global so :checked follows the theme
   without a per-state inline stylesheet that freezes at build time. */
QPushButton[objectName="sectionPill"] {{
    background: transparent; color: {p['text2']};
    border: 1px solid {p['border']}; border-radius: {r_md}px;
    font-size: 12px; font-weight: 600; padding: 4px 10px;
}}
QPushButton[objectName="sectionPill"]:hover {{
    color: {p['text']}; border-color: {gold_border_hover};
}}
QPushButton[objectName="sectionPill"]:checked {{
    background: {qss_alpha(p['gold'], 0.22)};
    color: {p.get('gold_ink', p['gold'])};
    border: 1px solid {qss_alpha(p['gold'], 0.45)};
    font-weight: 700;
}}

/* ── INPUTS ── */
QLineEdit, QTextEdit, QPlainTextEdit {{
    background: {p['input']};
    color: {p['text']};
    border: 1px solid {p['border2']};
    border-radius: {r_md}px;
    padding: 8px 12px;
    font-size: 14px;
    selection-background-color: {p['gold']};
    selection-color: {gold_fg};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border-color: {p['gold']};
    background: {p['input']};
}}
QLineEdit[readOnly="true"] {{
    color: {p['text2']};
    border-color: {p['border2']};
    background: {p['panel']};
}}

QSpinBox, QDoubleSpinBox {{
    background: {p['input']};
    color: {p['text']};
    border: 1px solid {p['border2']};
    border-radius: {r_md}px;
    padding: 6px 10px;
    font-size: 14px;
}}
QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {p['gold']}; }}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    background: {p['border2']}; border: none; width: 22px; border-radius: 4px;
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{
    background: {p['gold']};
}}

QComboBox {{
    background: {p['input']};
    color: {p['text']};
    border: 1px solid {p['border2']};
    border-radius: {r_md}px;
    padding: 6px 12px;
    font-size: 14px;
}}
QComboBox:focus {{ border-color: {p['gold']}; }}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox QAbstractItemView {{
    background: {p['card']};
    color: {p['text']};
    border: 1px solid {p['border2']};
    selection-background-color: {p['selected']};
    selection-color: {p['text']};
    padding: 4px;
    max-height: 280px;
    outline: 0;
}}
QComboBox QAbstractItemView::item {{
    padding: 8px 12px; min-height: 32px;
    color: {p['text']}; background: {p['card']};
}}
QComboBox QAbstractItemView::item:selected {{
    background: {p['selected']}; color: {p['text']};
}}
QComboBox QAbstractItemView::item:hover {{
    background: {p['hover']}; color: {p['text']};
}}

/* ── TABLES ── */
QTableWidget, QTableView {{
    background: {p['card']};
    color: {p['text']};
    gridline-color: transparent;
    border: none;
    border-radius: {r_card}px;
    font-size: 14px;
    /* Zebra via item BackgroundRole only — do not use alternate-background-color
       (QSS overrides BackgroundRole and can leak opposite-theme row fills). */
    alternate-background-color: {p['card']};
    selection-background-color: {p['selected']};
    selection-color: {p['text']};
    show-decoration-selected: 1;
}}
QTableWidget::item, QTableView::item {{
    padding: 10px 14px;
    border: none;
    border-bottom: 1px solid {p['border']};
}}
/* Do not set background/color on ::item — any ::item background (even
   transparent) makes Qt ignore item BackgroundRole/ForegroundRole.
   Zebra + text come from apply_table_row_backgrounds / retint_table_items. */
QTableWidget::item:selected, QTableView::item:selected {{
    color: {p['text']};
    background: {p['selected']};
}}
QTableWidget::item:hover:!selected, QTableView::item:hover:!selected {{
    background: {p['hover']};
    color: {p['text']};
}}
QHeaderView::section {{
    background: {p['panel']};
    color: {p['text2']};
    font-size: 11px; font-weight: 800;
    letter-spacing: 1.2px;
    padding: 12px 14px;
    border: none;
    border-bottom: 1px solid {p['border']};
    text-transform: uppercase;
}}
QHeaderView {{ border: none; background: transparent; color: {p['text2']}; }}
QTableCornerButton::section {{ background: {p['panel']}; border: none; }}

/* ── TABS ── */
QTabWidget::pane {{
    background: {p['card']};
    border: 1px solid {p['border']};
    border-radius: {r_card}px;
    border-top-left-radius: 0;
}}
QTabBar {{ background: transparent; }}
QTabBar::tab {{
    background: transparent;
    color: {p['text2']};
    border: none;
    border-bottom: 2px solid transparent;
    padding: 10px 20px;
    margin-right: 2px;
    font-size: 13px; font-weight: 600;
}}
QTabBar::tab:selected {{
    color: {p['gold']};
    border-bottom: 2px solid {p['gold']};
    font-weight: 700;
}}
QTabBar::tab:hover:!selected {{ color: {p['text']}; }}

/* ── SCROLLBARS ── */
QScrollBar:vertical {{
    background: transparent; width: 6px; border-radius: 3px; margin: 0px;
}}
QScrollBar::handle:vertical {{
    background: {p['border2']}; border-radius: 3px; min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: {p['gold']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{
    background: transparent; height: 6px; border-radius: 3px; margin: 0px;
}}
QScrollBar::handle:horizontal {{
    background: {p['border2']}; border-radius: 3px; min-width: 28px;
}}
QScrollBar::handle:horizontal:hover {{ background: {p['gold']}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}

/* ── GROUPBOX ── */
QGroupBox {{
    border: 1px solid {p['border2']};
    border-radius: {r_card}px;
    margin-top: 20px;
    padding: 18px 16px 14px 16px;
    background: {p['card']};
    font-size: 13px;
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 16px; padding: 0 8px;
    color: {p['gold']};
    font-size: 10px; font-weight: 800; letter-spacing: 1.5px;
}}

/* ── CHECKBOXES / RADIO ── */
QCheckBox, QRadioButton {{
    color: {p['text']}; font-size: 14px; spacing: 10px; background: transparent;
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 18px; height: 18px;
    border: 2px solid {p['border2']};
    border-radius: 4px;
    background: {p['input']};
}}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
    border-color: {p['gold']};
}}
QCheckBox::indicator:checked {{
    background: {p['gold']};
    border-color: {p['gold']};
    image: url("{check_url}");
}}
QCheckBox::indicator:checked:disabled {{
    background: {p['muted']};
    border-color: {p['muted']};
}}
QRadioButton::indicator {{ border-radius: 9px; }}
QRadioButton::indicator:checked {{
    background: {p['gold']};
    border-color: {p['gold']};
    image: url("{radio_url}");
}}

/* Form labels — prefer text2 (readable) over inheriting muted/disabled */
QLabel#formLabel {{
    color: {p['text2']};
    font-size: 13px;
    font-weight: 600;
    background: transparent;
}}

/* ── PROGRESS ── */
QProgressBar {{
    background: {p['border2']};
    border: none; border-radius: 4px;
    height: 5px; text-align: center; color: transparent;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 {p['gold']}, stop:1 {p['gold_lt']});
    border-radius: 4px;
}}

/* --- DIALOGS / MESSAGE BOX (Fusion + QSS; avoid white Win chrome) --- */
QMessageBox {{
    background: {p['card2']};
    color: {p['text']};
    border: 1px solid {p['border2']};
    border-radius: {r_xl}px;
}}
QMessageBox QLabel {{
    color: {p['text']}; font-size: 14px; background: transparent; min-width: 280px;
}}
QMessageBox QPushButton {{
    background: {p['card']}; color: {p['text']};
    border: 1px solid {p['border2']}; border-radius: {r_md}px;
    min-width: 90px; min-height: 34px; padding: 6px 16px; font-weight: 700;
}}
QMessageBox QPushButton:hover {{ border-color: {p['gold']}; color: {p['gold']}; }}
QMessageBox QPushButton:default {{
    background: {p['gold']}; color: {gold_fg}; border: none;
}}

QDialogButtonBox QPushButton {{
    background: {p['card2']}; color: {p['text']};
    border: 1px solid {p['border2']}; border-radius: {r_md}px;
    padding: 8px 20px; font-size: 13px; font-weight: 600;
    min-height: 34px; min-width: 84px;
}}
QDialogButtonBox QPushButton:hover {{
    background: {p['hover']}; color: {p['text']};
}}
QDialogButtonBox QPushButton[text="OK"],
QDialogButtonBox QPushButton[text="Save"] {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 {p['gold_lt']}, stop:1 {p['gold']});
    color: {gold_fg}; border: none; font-weight: 700;
}}

/* ── TOOLTIPS / MENUS / TOOLBUTTONS / SLIDERS ── */
/* Without these Qt falls back to the native (light) palette, which is the
   classic "white tooltip on a navy app" hybrid. */
QToolTip {{
    background: {p['card2']};
    color: {p['text']};
    border: 1px solid {p['border2']};
    border-radius: {r_md}px;
    padding: 6px 10px;
    font-size: 12px;
}}
QMenu {{
    background: {p['card']};
    color: {p['text']};
    border: 1px solid {p['border2']};
    border-radius: {r_md}px;
    padding: 6px;
}}
QMenu::item {{
    background: transparent;
    color: {p['text']};
    padding: 7px 18px;
    border-radius: {RADIUS['sm']}px;
}}
QMenu::item:selected {{ background: {p['selected']}; color: {p['text']}; }}
QMenu::item:disabled {{ color: {p['muted']}; }}
QMenu::separator {{ height: 1px; background: {p['border']}; margin: 5px 8px; }}
QToolButton {{
    background: transparent;
    color: {p['text']};
    border: 1px solid transparent;
    border-radius: {r_md}px;
    padding: 5px 9px;
}}
QToolButton:hover {{ background: {p['hover']}; border-color: {gold_border_hover}; }}
QToolButton:pressed {{ background: {p['selected']}; }}
QToolButton:checked {{ background: {gold_tint}; color: {p['gold']}; }}
QToolButton:disabled {{ color: {p['muted']}; }}
QSlider::groove:horizontal {{
    background: {p['border2']}; height: 5px; border-radius: 3px;
}}
QSlider::sub-page:horizontal {{ background: {p['gold']}; border-radius: 3px; }}
QSlider::handle:horizontal {{
    background: {p['gold']}; border: none; width: 16px;
    margin: -6px 0; border-radius: 8px;
}}
QSlider::handle:horizontal:disabled {{ background: {p['muted']}; }}
QAbstractScrollArea::corner {{ background: transparent; border: none; }}
QStatusBar {{ background: {p['panel']}; color: {p['text2']}; }}

/* Disabled inputs must read as disabled without dropping below 4.5:1 */
QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled,
QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled,
QDateEdit:disabled {{
    background: {p['panel']};
    color: {p['muted']};
    border-color: {p['border']};
}}
QLabel:disabled, QCheckBox:disabled, QRadioButton:disabled {{ color: {p['muted']}; }}

/* ── MISC ── */
/* Do NOT pin handle width/height to 1px — that made POS gutters un-grabbable.
   POS PosSplitter sets its own 14px handle size; other splitters keep a usable 6px. */
QSplitter::handle {{ background: {p['border']}; width: 6px; height: 6px; }}
QSplitter#posSplitter::handle,
QSplitter#posCartSplitter::handle {{
    background: transparent;
    width: 16px;
    height: 16px;
}}

QListWidget {{
    background: {p['card']}; color: {p['text']};
    border: none; border-radius: {r_card}px; outline: none;
}}
QListWidget::item {{
    padding: 10px 12px; border: none; border-radius: {r_md}px; margin: 1px 4px;
}}
QListWidget::item:selected {{ background: {p['selected']}; color: {p['gold']}; }}
QListWidget::item:hover:!selected {{ background: {p['hover']}; }}

QDateEdit {{
    background: {p['input']}; color: {p['text']};
    border: 1px solid {p['border2']}; border-radius: {r_md}px;
    padding: 6px 34px 6px 12px; font-size: 13px;
    min-height: 28px; min-width: 140px;
}}
QDateEdit:focus {{ border-color: {p['gold']}; }}
QDateEdit::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 30px;
    border: none;
    border-left: 1px solid {p['border']};
    background: transparent;
}}
QDateEdit::drop-down:hover {{ background: {p['hover']}; }}
QDateEdit::down-arrow {{
    {cal_arrow}
}}
QCalendarWidget {{
    background: {p['card']}; color: {p['text']};
    border: 1px solid {p['border']};
}}
QCalendarWidget QWidget {{ alternate-background-color: {p['card2']}; }}
QCalendarWidget QToolButton {{
    color: {p['text']}; background: transparent;
    border: none; border-radius: {r_md}px;
    padding: 4px 8px; font-weight: 700;
}}
QCalendarWidget QToolButton:hover {{ background: {p['hover']}; color: {p['gold']}; }}
QCalendarWidget QMenu {{ background: {p['card']}; color: {p['text']}; }}
QCalendarWidget QSpinBox {{
    background: {p['input']}; color: {p['text']};
    border: 1px solid {p['border2']}; border-radius: 4px;
}}
QCalendarWidget QAbstractItemView:enabled {{
    color: {p['text']}; background: {p['card']};
    selection-background-color: {p['selected']}; selection-color: {p['gold']};
}}

/* ── LOGIN ── */
#loginBrand {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 {p['app']}, stop:0.5 {p['sidebar']}, stop:1 {p['card']});
    border-bottom: 2px solid {p['gold']};
}}
#logoText {{
    color: {p['gold']};
    font-size: 48px; font-weight: 800;
    letter-spacing: 12px; background: transparent;
}}
#loginTitle    {{ color: {p['text']};  font-size: 11px; font-weight: 800; letter-spacing: 5px; background: transparent; }}
#loginSubtitle {{ color: {p['gold']}; font-size: 12px; font-weight: 600; letter-spacing: 1px; background: transparent; }}
#loginForm     {{ background: {p['surface']}; }}
#loginStatus   {{ font-size: 13px; color: {p['text2']}; min-height: 30px; background: transparent; }}
QLineEdit#loginInput {{
    font-size: 15px; padding: 12px 14px; border-radius: {r_md}px;
    background: {p['input']}; color: {p['text']};
    border: 1px solid {p['border2']};
}}
QLineEdit#loginInput:focus {{ border-color: {p['gold']}; }}
QPushButton#loginBtn {{
    background: {p['gold']};
    color: {gold_fg};
    font-size: 14px; font-weight: 800; letter-spacing: 2px;
    padding: 12px; border: none; border-radius: {r_md}px; min-height: 48px;
}}
QPushButton#loginBtn:hover   {{ background: {p['gold_lt']}; color: {gold_fg}; }}
QPushButton#loginBtn:pressed {{ background: {p['gold_dk']}; color: {gold_fg}; }}
QPushButton#loginBtn:disabled {{
    /* `border2` is a boundary tone; `muted` ink on it measures 1.8:1. */
    background: {p['panel']}; color: {p['muted']}; border: 1px solid {p['border']};
}}
QPushButton#loginEyeBtn {{
    background: {p['card2']}; color: {p['text2']};
    border: 1px solid {p['border2']}; border-radius: {r_md}px;
    font-size: 16px; min-width: 44px; max-width: 44px; min-height: 48px;
}}
QPushButton#loginEyeBtn:hover {{ color: {p['gold']}; border-color: {p['gold']}; }}
#loginFooter {{ font-size: 11px; color: {p['text2']}; background: transparent; }}

/* ── LABELS ── */
#kpiLabel {{ color: {p['muted']}; font-size: 10px; font-weight: 800; letter-spacing: 1.2px; background: transparent; }}
#kpiSub   {{ color: {p['text2']}; font-size: 12px; background: transparent; }}
#sectionEyebrow {{ color: {p['muted']}; font-size: 10px; font-weight: 800; letter-spacing: 2px; background: transparent; }}
#sectionTitle   {{ color: {p['text']}; font-size: 15px; font-weight: 600; background: transparent; }}

/* ── POS product / shell cards ── */
#posProductPanel, #posCartPanel {{
    background: {p['card']};
    border: 1px solid {p['border']};
    border-radius: {r_card}px;
}}
#posPayToggle {{
    background: {p['card2']};
    color: {p['text2']};
    border: 1px solid {p['border']};
    border-radius: {r_md}px;
    font-size: 12px; font-weight: 600;
    min-height: 44px;
}}
#posPayToggle:checked {{
    background: {gold_tint};
    color: {p['gold']};
    border-color: {p['gold']};
}}

/* Business day — one bordered button (caption + date + chevron) */
QFrame#posBusinessDayBar QPushButton#posBizDayBtn {{
    background: transparent;
    color: {p['text']};
    border: 1px solid {p['border2']};
    border-radius: {r_md}px;
    min-height: 34px;
    text-align: left;
    font-weight: 600;
    padding: 6px 14px;
}}
QFrame#posBusinessDayBar QPushButton#posBizDayBtn:hover {{
    background: {p['hover']};
    border-color: {gold_border_hover};
}}
QFrame#posBusinessDayBar QPushButton#posBizDayBtn:focus {{
    border-color: {p['gold']};
    background: {p['hover']};
}}
QFrame#posBusinessDayBar QPushButton#posBizDayBtn:disabled {{
    color: {p['muted']};
    border-color: {p['border']};
    background: {p['panel']};
}}

/* Empty states */
QFrame#mbtEmptyState {{
    background: transparent;
    border: none;
}}

/* Nested tab panes — avoid double-border when parent already cards */
QTabWidget#mbtInnerTabs::pane {{
    background: {p['surface']};
    border: none;
    border-radius: 0;
}}
"""


MBT_STYLESHEET = _build_stylesheet(DARK)


class ThemeManager:
    """
    Toggle between DARK and LIGHT globally.
    Call ThemeManager.apply(is_light) from any widget.
    The QApplication stylesheet is updated — all widgets repaint.
    """
    _is_light = False

    @classmethod
    def is_light(cls):
        return cls._is_light

    @classmethod
    def apply(cls, is_light: bool, force: bool = False):
        global MBT_STYLESHEET, _theme_generation
        from PyQt5.QtWidgets import QApplication
        ensure_fonts()
        want = bool(is_light)
        app = QApplication.instance()
        # Skip only when already on theme AND app sheet matches (avoid stale MainWindow copy issues)
        if (
            not force
            and cls._is_light == want
            and MBT_STYLESHEET
            and app is not None
            and app.styleSheet() == MBT_STYLESHEET
        ):
            return MBT_STYLESHEET
        cls._is_light = want
        p = LIGHT if cls._is_light else DARK
        # Update global C in-place so all existing widget references stay valid
        C.clear()
        C.update(p)
        _theme_generation += 1
        _rebuild_style_index()
        COLORS.update({
            'accent': C['gold'], 'success': C['ok'], 'danger': C['err'],
            'warning': C['warn'], 'info': C['info'],
            'text_primary': C['text'], 'text_secondary': C['text2'],
            'text_muted': C['muted'], 'bg_card': C['card'],
            'bg_sidebar': C['sidebar'], 'border': C['border'],
            'border_strong': C['border2'],
        })
        MBT_STYLESHEET = _build_stylesheet(p)
        if app:
            app.setStyleSheet(MBT_STYLESHEET)
            # Native palette for placeholders / combo popups Fusion may ignore in QSS
            try:
                from PyQt5.QtGui import QColor, QPalette
                pal = app.palette()
                pal.setColor(QPalette.Window, QColor(p['app']))
                pal.setColor(QPalette.WindowText, QColor(p['text']))
                pal.setColor(QPalette.Base, QColor(p['input']))
                pal.setColor(QPalette.AlternateBase, QColor(p['card2']))
                pal.setColor(QPalette.Text, QColor(p['text']))
                pal.setColor(QPalette.Button, QColor(p['card2']))
                pal.setColor(QPalette.ButtonText, QColor(p['text']))
                pal.setColor(QPalette.Highlight, QColor(p['selected']))
                pal.setColor(QPalette.HighlightedText, QColor(p['text']))
                pal.setColor(QPalette.PlaceholderText, QColor(p['muted']))
                pal.setColor(QPalette.Disabled, QPalette.Text, QColor(p['muted']))
                pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(p['muted']))
                app.setPalette(pal)
            except Exception:
                pass
            # Replay every tracked inline stylesheet so widgets built under the
            # previous palette cannot keep the other theme's colours.  Hidden
            # surfaces are deferred to their next Show so the toggle stays
            # proportional to what is on screen.
            try:
                install_show_catch_up()
                restyle_themed_widgets(visible_only=True)
            except Exception:
                pass
            _run_theme_hooks()
        return MBT_STYLESHEET

    @classmethod
    def toggle(cls):
        return cls.apply(not cls._is_light)

    @classmethod
    def palette(cls):
        return LIGHT if cls._is_light else DARK


def is_light_mode() -> bool:
    return ThemeManager.is_light()


def set_light_mode(enabled: bool) -> str:
    """Compatibility wrapper — prefer ThemeManager.apply()."""
    return ThemeManager.apply(enabled)


def apply_themed_dialog(dialog) -> None:
    """
    Paint a QDialog from the live C palette (light + dark).

    Do NOT paste full MBT_STYLESHEET onto dialogs: that sheet sets
    QWidget{background:transparent}, and without WA_StyledBackground the
    native frame shows black behind light-mode dark labels (hybrid theme).
    """
    try:
        from PyQt5.QtCore import Qt
        from PyQt5.QtGui import QColor, QPalette
        dialog.setAttribute(Qt.WA_StyledBackground, True)
        dialog.setAutoFillBackground(True)
        # Clear any frozen dark sheet first
        dialog.setStyleSheet('')
        pal = dialog.palette()
        pal.setColor(QPalette.Window, QColor(C['surface']))
        pal.setColor(QPalette.WindowText, QColor(C['text']))
        pal.setColor(QPalette.Base, QColor(C['input']))
        pal.setColor(QPalette.Text, QColor(C['text']))
        pal.setColor(QPalette.Button, QColor(C['card2']))
        pal.setColor(QPalette.ButtonText, QColor(C['text']))
        pal.setColor(QPalette.Highlight, QColor(C['selected']))
        pal.setColor(QPalette.HighlightedText, QColor(C['text']))
        pal.setColor(QPalette.PlaceholderText, QColor(C['muted']))
        dialog.setPalette(pal)
        r = RADIUS['md']
        dialog.setStyleSheet(
            f"QDialog{{background:{C['surface']};color:{C['text']};}}"
            f"QLabel{{color:{C['text2']};background:transparent;}}"
            f"QLineEdit,QTextEdit,QPlainTextEdit,QSpinBox,QDoubleSpinBox,"
            f"QDateEdit,QComboBox,QAbstractSpinBox{{"
            f"background:{C['input']};color:{C['text']};"
            f"border:1px solid {C['border2']};border-radius:{r}px;"
            f"padding:6px 10px;}}"
            f"QLineEdit:focus,QTextEdit:focus,QSpinBox:focus,QDoubleSpinBox:focus,"
            f"QDateEdit:focus,QComboBox:focus{{border-color:{C['gold']};}}"
            f"QComboBox QAbstractItemView{{"
            f"background:{C['card']};color:{C['text']};"
            f"border:1px solid {C['border']};outline:0;}}"
            f"QComboBox QAbstractItemView::item{{"
            f"color:{C['text']};background:{C['card']};min-height:28px;}}"
            f"QCheckBox{{color:{C['text']};background:transparent;}}"
            f"QFrame{{background:transparent;}}"
            f"QDialogButtonBox QPushButton{{"
            f"background:{C['card2']};color:{C['text']};"
            f"border:1px solid {C['border2']};border-radius:{r}px;"
            f"min-height:36px;padding:6px 16px;font-weight:700;}}"
            f"QDialogButtonBox QPushButton:hover{{border-color:{C['gold']};"
            f"color:{C['gold']};}}"
            f"QDialogButtonBox QPushButton[text='OK'],"
            f"QDialogButtonBox QPushButton[text='Save']{{"
            f"background:{C['gold']};color:{C.get('gold_fg', '#0B1220')};"
            f"border:none;}}"
        )
        # Retheme nested Select / SearchableSelect if present
        try:
            from desktop.utils.select_controls import refresh_select_controls
            refresh_select_controls(dialog)
        except Exception:
            pass
        try:
            from desktop.utils.audio_manager import play as _audio_play
            _audio_play('dialog_open')
        except Exception:
            pass
    except Exception:
        pass


# Installed at import so every widget built by the app — tabs, dialogs, POS
# panels, wizard, activation — carries a replayable style template.
install_style_capture()
