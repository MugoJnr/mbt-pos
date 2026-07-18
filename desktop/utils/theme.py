"""
MBT POS — Design System v7  (Lovable / Design System port)
MugoByte Technologies | mugobyte.com

Two complete themes: DARK (default) + LIGHT
Tokens mirror lovable_export/src/styles.css
Global switch via ThemeManager.apply(is_light)
Font: Manrope when available, Segoe UI fallback

CRITICAL Qt QSS rule:
  CSS 8-digit hex (#RRGGBBAA) is WRONG in Qt — Qt uses #AARRGGBB.
  Appending alpha like f\"{{C['err']}}22\" becomes opaque olive, not translucent red.
  Always use qss_alpha() / rgba() helpers below.
"""
import os
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


# ── DARK PALETTE (commercial refine — keep MBT gold identity) ─────────────────
# Aligned with POS redesign tokens: bg #0B1220, surface #16213A, hover #1E2E4A
# text2/muted bumped for WCAG-ish contrast on card (#16213A) — headers/labels.
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
    'gold_lt':   '#F5B301',
    'gold_dk':   '#C08A00',
    'gold_fg':   '#0B1220',
    # dim tokens are solid-ish panel mixes (NOT CSS #RRGGBBAA — Qt misreads those)
    'gold_dim':  '#1C1808',
    'text':      '#FFFFFF',
    'text2':     '#B4C2D6',   # secondary / form labels / table headers
    'muted':     '#8B9BB0',   # captions / placeholders (was #64748B — too low)
    'disabled':  '#1C2A3A',
    'ok':        '#00D084',
    'ok_dim':    '#0A1F18',
    'warn':      '#FFB000',
    'warn_dim':  '#1A1508',
    'err':       '#FF4D6D',
    'err_dim':   '#2A1018',   # solid danger chip bg (readable vs translucent)
    'info':      '#3B82F6',
    'info_dim':  '#0C1424',
    'border':    '#2A4060',   # slightly brighter separators
    'border2':   '#3A5270',   # input borders — visible on card
    'sep':       '#121A2C',
    'divider':   '#2A4060',
    'focus':     '#FBBF24',
    'on_danger': '#FFFFFF',
    'on_success':'#FFFFFF',
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
    'gold':      '#B87000',
    'gold_lt':   '#D48800',
    'gold_dk':   '#8C5400',
    'gold_fg':   '#FFFFFF',
    'gold_dim':  '#F7EED9',
    'text':      '#0C1828',
    'text2':     '#2E4460',   # stronger secondary for labels
    'muted':     '#5A7390',   # placeholders still readable on white
    'disabled':  '#C0CCD8',
    'ok':        '#006B48',
    'ok_dim':    '#E6F5EF',
    'warn':      '#A05800',
    'warn_dim':  '#F7EED9',
    'err':       '#B81C2C',
    'err_dim':   '#FDECEA',
    'info':      '#1850A8',
    'info_dim':  '#E8EEF8',
    'border':    '#CDD8E8',
    'border2':   '#A8BDD4',
    'sep':       '#E0E8F0',
    'divider':   '#CDD8E8',
    'focus':     '#B87000',
    'on_danger': '#FFFFFF',
    'on_success':'#FFFFFF',
    'primary':   '#B87000',
    'success':   '#006B48',
    'warning':   '#A05800',
    'danger':    '#B81C2C',
}

# Radius scale — commercial cards use 16px
RADIUS = {
    'sm': 6,
    'md': 8,
    'lg': 12,
    'xl': 16,
    '2xl': 20,
}

# POS layout rhythm (PyQt5 modular redesign)
PADDING = 20
GAP = 18
ANIMATION_MS = 150
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
    cal_arrow = _calendar_icon_qss().replace('{p_muted}', p['muted'])
    return f"""
* {{
    font-family: {ff};
    font-size: 14px;
    color: {p['text']};
    outline: none;
}}
QMainWindow {{ background: {p['app']}; border: none; }}
QDialog {{ background: {p['surface']}; border: none; }}
/* Lovable: app shell outer = --app, main column = --surface */
QWidget {{ background: transparent; border: none; }}
#appRoot {{ background: {p['app']}; }}
#content, #pageStack, #mbtPageInner {{
    background: {p['surface']};
}}
QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QFrame {{ border: none; }}

/* ── SIDEBAR (AppShell) ── */
#sidebar {{
    background: {p['sidebar']};
    border-right: 1px solid {p['border']};
    min-width: 228px; max-width: 228px;
}}
#sidebarLogo {{
    background: {p['sidebar']};
    min-height: 76px; max-height: 76px;
    border-bottom: 1px solid {p['border']};
}}
#sidebarLogoText {{
    color: {p['gold']};
    font-size: 18px; font-weight: 800; letter-spacing: 1px;
    background: transparent;
}}
#sidebarLogoSub {{
    color: {p['text2']};
    font-size: 10px; letter-spacing: 3px; font-weight: 600;
    background: transparent;
}}
#navBtn {{
    background: transparent;
    color: {p['text2']};
    border: none;
    padding: 10px 12px 10px 16px;
    text-align: left;
    font-size: 13px; font-weight: 500;
    border-radius: {r_md}px;
    margin: 2px 8px;
    min-height: 40px;
}}
#navBtn:hover {{
    background: {nav_hover_soft};
    color: {p['text']};
}}
#navBtn:checked {{
    background: {p['hover']};
    color: {p['gold']};
    font-weight: 600;
    border-left: 3px solid {p['gold']};
    padding-left: 13px;
}}
#navBtn:checked:hover {{
    background: {p['hover']};
    color: {p['gold']};
}}
#sidebarUser {{
    background: {p['panel']};
    border-top: 1px solid {p['border']};
    min-height: 88px;
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
    padding: 6px 12px;
    font-size: 13px;
    margin-top: 6px;
    min-height: 0;
}}
#logoutBtn:hover {{
    color: {p['err']};
    border-color: {p['err']};
    background: {p['err_dim']};
}}

/* ── TOPBAR ── */
#topbar {{
    background: {p['panel']};
    border-bottom: 1px solid {p['border']};
    min-height: 56px; max-height: 56px;
}}
#pageTitle {{
    color: {p['text']};
    font-size: 15px; font-weight: 600;
    background: transparent;
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
    min-height: 0;
}}
#refreshBtn:hover {{ color: {p['text']}; background: {p['hover']}; border-color: {gold_border_hover}; }}
#themeBtn {{
    background: {p['card']};
    color: {p['text']};
    border: 1px solid {p['border']};
    border-radius: {r_md}px;
    font-size: 12px; font-weight: 500;
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
    background: {p['border2']}; color: {p['muted']};
}}
QPushButton[objectName="successBtn"] {{
    background: {p['ok']}; color: {p.get('on_success', '#FFFFFF')}; border: none; font-weight: 600; border-radius: {r_md}px;
}}
QPushButton[objectName="dangerBtn"]  {{
    background: {p['err']}; color: {p.get('on_danger', '#FFFFFF')}; border: none; font-weight: 600; border-radius: {r_md}px;
}}
QPushButton[objectName="dangerBtn"]:hover {{ background: {p['err']}; color: {p.get('on_danger', '#FFFFFF')}; }}
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
    background: transparent; width: 8px; border-radius: 4px; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {p['border2']}; border-radius: 4px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {p['gold']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: transparent; height: 8px; border-radius: 4px;
}}
QScrollBar::handle:horizontal {{
    background: {p['border2']}; border-radius: 4px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

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
QCheckBox::indicator:checked {{ background: {p['gold']}; border-color: {p['gold']}; }}
QRadioButton::indicator {{ border-radius: 9px; }}
QRadioButton::indicator:checked {{ background: {p['gold']}; border-color: {p['gold']}; }}

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

/* ── DIALOGS ── */
QMessageBox {{
    background: {p['card2']};
    border: 1px solid {p['border2']};
    border-radius: {r_xl}px;
}}
QMessageBox QLabel {{
    color: {p['text']}; font-size: 14px; background: transparent;
}}
QMessageBox QPushButton {{ min-width: 90px; color: {p['text']}; }}

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

/* ── MISC ── */
QSplitter::handle {{ background: {p['border']}; width: 1px; height: 1px; }}

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
QPushButton#loginBtn:disabled {{ background: {p['border2']}; color: {p['muted']}; }}
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
    min-height: 40px;
}}
#posPayToggle:checked {{
    background: {gold_tint};
    color: {p['gold']};
    border-color: {p['gold']};
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
        global MBT_STYLESHEET
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
