"""
MBT POS — Modular Point-of-Sale widgets (PyQt5)
MugoByte Technologies

Reusable cashier-speed components. Theme via desktop.utils.theme (C / ThemeManager).
No CustomTkinter — keeps PyInstaller / Fusion stack intact.
"""
from __future__ import annotations

from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *

from desktop.utils.theme import C, RADIUS, PADDING, GAP, TOUCH_MIN, qss_alpha
from desktop.utils.widgets import PrimaryBtn, SecondaryBtn


def _parse_hex_rgb(color: str):
    """(r, g, b) from a '#RRGGBB' token — for QColor-based effects (shadows),
    which need real ints, not the QSS rgba()/#AARRGGBB strings qss_alpha() makes."""
    h = (color or '').strip().lstrip('#')
    if len(h) == 3:
        h = ''.join(ch * 2 for ch in h)
    if len(h) != 6:
        return 0, 0, 0
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


# ── Category visual language ──────────────────────────────────────────────────

_CATEGORY_STYLE = {
    'general':     ('🛒', '#3B82F6'),
    'food':        ('🍔', '#F59E0B'),
    'beverage':    ('🥤', '#06B6D4'),
    'drinks':      ('🥤', '#06B6D4'),
    'electronics': ('📱', '#8B5CF6'),
    'clothing':    ('👕', '#EC4899'),
    'pharmacy':    ('💊', '#10B981'),
    'grocery':     ('🥬', '#22C55E'),
    'hardware':    ('🔧', '#64748B'),
    'beauty':      ('💄', '#F472B6'),
    'stationery':  ('📒', '#A78BFA'),
    'services':    ('⚙️', '#94A3B8'),
    'fertilizer':  ('🌱', '#22C55E'),
    'fertiliser':  ('🌱', '#22C55E'),
    'seed':        ('🌾', '#F59E0B'),
    'seeds':       ('🌾', '#F59E0B'),
    'agro':        ('🌾', '#16A34A'),
    'chemical':    ('🧪', '#8B5CF6'),
}


def category_visual(category: str):
    """Return (emoji, accent_hex) for a category name."""
    key = (category or 'general').strip().lower()
    if key in _CATEGORY_STYLE:
        return _CATEGORY_STYLE[key]
    for k, v in _CATEGORY_STYLE.items():
        if k in key or key in k:
            return v
    # Stable color from name hash so unknown cats aren't all blue
    palette = (
        '#3B82F6', '#F59E0B', '#10B981', '#EC4899',
        '#8B5CF6', '#06B6D4', '#F97316', '#64748B',
    )
    accent = palette[sum(ord(c) for c in key) % len(palette)]
    return ('📦', accent)


def safe_price(v) -> str:
    """Compact money for product cards — drop .00 on whole amounts to reduce clip."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return '0'
    if abs(f - round(f)) < 0.009:
        return f'{int(round(f)):,}'
    return f'{f:,.2f}'


def fmt_stock_short(n) -> str:
    try:
        f = float(n)
    except (TypeError, ValueError):
        return '0'
    if abs(f - round(f)) < 1e-9:
        return str(int(round(f)))
    return f'{f:g}'


def round_qty(v, step=0.25, minimum=None) -> float:
    try:
        q = float(v)
    except (TypeError, ValueError):
        q = float(step) if step else 0.0
    step = float(step) if step else 0.25
    mn = float(step if minimum is None else minimum)
    if step <= 0:
        return max(mn, round(q, 2))
    snapped = round(round(q / step) * step, 2)
    return max(mn, snapped)


# ── CategoryIcon ──────────────────────────────────────────────────────────────

class CategoryIcon(QLabel):
    """Category visual tile — SVG/image when available, emoji fallback."""

    def __init__(self, category='General', size=48, parent=None, category_meta=None):
        super().__init__(parent)
        self._category = category or 'General'
        self._meta = category_meta or {}
        self._size = int(size)
        self.setFixedSize(self._size, self._size)
        self.setAlignment(Qt.AlignCenter)
        self.refresh_theme()

    def set_category(self, category: str, category_meta: dict = None):
        self._category = category or 'General'
        if category_meta is not None:
            self._meta = category_meta or {}
        self.refresh_theme()

    def set_category_meta(self, meta: dict):
        self._meta = meta or {}
        self.refresh_theme()

    def refresh_theme(self):
        # Prefer offline CategoryVisual rendering into this label
        try:
            from desktop.utils.category_visuals import (
                resolve_icon_path, svg_to_pixmap, load_image_pixmap,
                suggest_visual_for_category_name, accessible_fg,
                find_icon, emoji_tile_pixmap, section_tile_bg, icon_to_pixmap,
            )
            meta = dict(self._meta or {})
            meta.setdefault('name', self._category)
            accent = meta.get('accent_color') or category_visual(self._category)[1]
            vtype = (meta.get('visual_type') or 'icon').lower()
            pm = None
            if vtype == 'image' and meta.get('image_path'):
                import os
                path = meta['image_path']
                if not os.path.isabs(path):
                    try:
                        from mbt_paths import get_project_root
                        path = os.path.join(get_project_root(), path)
                    except Exception:
                        pass
                pm = load_image_pixmap(path, self._size)
            if (pm is None or pm.isNull()) and meta.get('icon_name'):
                pm = icon_to_pixmap(icon_id=meta.get('icon_name'), size=self._size)
                ic = find_icon(meta.get('icon_name'))
                if ic and ic.get('bg') and (not meta.get('accent_color')):
                    accent = ic.get('bg')
            if pm is None or pm.isNull():
                sug = suggest_visual_for_category_name(self._category)
                pm = icon_to_pixmap(icon_id=sug.get('icon_name'), size=self._size)
                accent = meta.get('accent_color') or sug.get('accent_color') or accent
            if pm is not None and not pm.isNull():
                self.setPixmap(pm)
                self.setText('')
                r = self._size // 2
                self.setStyleSheet(
                    f"QLabel {{ background:transparent; "
                    f"border-radius:{r}px; border:none; }}")
                return
        except Exception:
            pass
        # Never paint raw emoji as QLabel text — mojibake on many Windows PCs.
        # Twemoji PNG / SVG paths above are preferred; letter tile is the safe fallback.
        _, accent = category_visual(self._category)
        if self._meta.get('accent_color'):
            accent = self._meta['accent_color']
        letter = (self._category or '?').strip()[:1].upper() or '?'
        self.setPixmap(QPixmap())
        self.setText(letter)
        r = self._size // 2
        self.setStyleSheet(
            f"QLabel {{ background:{qss_alpha(accent, 0.18)}; color:{accent}; "
            f"border-radius:{r}px; font-size:{max(14, self._size // 2)}px; "
            f"font-weight:800; border:none; }}")


# ── StockBadge ────────────────────────────────────────────────────────────────

class StockBadge(QLabel):
    """Compact stock status pill (OK / Low / Out)."""

    def __init__(self, stock=0, unit='pcs', parent=None):
        # Always prefer a real parent — parentless QLabel becomes a free HWND
        # that flashes at screen-center during product-grid rebuilds.
        super().__init__(parent)
        self.setObjectName('posStockBadge')
        try:
            from PyQt5.QtCore import Qt as _Qt
            if parent is None:
                self.setAttribute(_Qt.WA_DontShowOnScreen, True)
                self.hide()
        except Exception:
            pass
        self._stock = stock
        self._unit = unit or 'pcs'
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(22)
        # Never steal width from the product name / price column
        sp = self.sizePolicy()
        sp.setHorizontalPolicy(QSizePolicy.Maximum)
        sp.setVerticalPolicy(QSizePolicy.Fixed)
        self.setSizePolicy(sp)
        self.setMaximumWidth(88)
        self.refresh_from(stock, unit)

    def refresh_from(self, stock, unit='pcs'):
        self._stock = stock
        self._unit = unit or 'pcs'
        try:
            n = float(stock)
        except (TypeError, ValueError):
            n = 0.0
        unit_s = (self._unit or 'pcs').strip()
        qty = fmt_stock_short(n)
        # One pattern everywhere: "N left" with color for state (Out / Low / OK)
        if n <= 0:
            tone, text = 'err', '0 left'
        elif n < 10:
            tone, text = 'warn', f'{qty} left'
        else:
            tone, text = 'ok', f'{qty} left'
        if tone == 'ok':
            color = C['text2']
        elif tone == 'warn':
            color = C['warn']
        else:
            color = C['err']
        # Elide if still too wide for the card
        fm = self.fontMetrics()
        text = fm.elidedText(text, Qt.ElideRight, 78)
        self.setText(text)
        self.setProperty('mbtBadgeTone', 'err' if n <= 0 else ('warn' if n < 10 else 'muted'))
        self.setToolTip(
            'Out of stock' if n <= 0 else f'{n:g} {unit_s} in stock')
        # Counter-legible: larger than 9px muted pills
        self.setStyleSheet(
            f"QLabel {{ color:{color}; font-size:11px; font-weight:700; "
            f"background:{qss_alpha(color, 0.12)}; border:1px solid {qss_alpha(color, 0.28)}; "
            f"border-radius:5px; padding:2px 6px; min-height:20px; max-height:22px; }}")
        try:
            self.setFixedHeight(22)
            self.setMinimumHeight(20)
        except Exception:
            pass


# ── ProductCard ───────────────────────────────────────────────────────────────

class ProductCard(QFrame):
    """
    Clickable product tile. Category emoji in colored circle when no image.
    Never shows broken/empty image placeholders.
    """
    clicked = pyqtSignal(dict)

    def __init__(self, product: dict, currency='KES', card_size=(214, 148),
                 parent=None, category_meta=None, *, compact=False):
        super().__init__(parent)
        self._product = product or {}
        self._currency = currency
        self._active = True
        self._compact = bool(compact)
        self._category_meta = category_meta or {}
        self.setObjectName('posProdCard')
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        w, h = card_size
        self._card_h = int(h)
        self._design_w = int(w)
        self.setFixedSize(int(w), int(h))
        # Compact cards may sit under touch min — intentional for density
        self.setMinimumHeight(int(h) if self._compact else TOUCH_MIN * 2)
        # Keep name/badge paint inside card bounds (no edge clipping)
        self.setContentsMargins(0, 0, 0, 0)

        try:
            from desktop.utils.display_category import (
                display_category, normalize_product_name,
            )
            raw_name = (self._product.get('name') or '').strip()
            name = normalize_product_name(raw_name)
            cat, _cat_tip = display_category(
                self._product.get('category') or '', raw_name)
            if cat == 'Uncategorized':
                cat = 'General'
        except Exception:
            name = (self._product.get('name') or '').strip()
            cat = self._product.get('category') or 'General'
        sku = (self._product.get('sku') or '').strip()
        price = self._product.get('price', 0)
        stock = self._product.get('stock', 0) or 0
        unit = self._product.get('unit', 'pcs') or 'pcs'
        try:
            stock_n = float(stock)
        except (TypeError, ValueError):
            stock_n = 0.0
        try:
            price_n = float(price)
        except (TypeError, ValueError):
            price_n = 0.0
        self._oos = stock_n <= 0
        self._unpriced = price_n <= 0.009

        pad = 10 if self._compact else 12
        vpad = 8 if self._compact else 10
        self._pad = pad
        lay = QVBoxLayout(self)
        # Extra right pad so stock badge / price never clips the card edge
        lay.setContentsMargins(pad, vpad, pad + 6, vpad)
        lay.setSpacing(4 if self._compact else 6)

        top = QHBoxLayout()
        top.setSpacing(8 if self._compact else 10)
        icon_sz = 28 if self._compact else 44
        self._icon_sz = icon_sz
        self._icon = CategoryIcon(cat, size=icon_sz, category_meta=self._category_meta)
        top.addWidget(self._icon, 0, Qt.AlignTop)

        tcol = QVBoxLayout()
        tcol.setSpacing(2 if self._compact else 3)
        tcol.setContentsMargins(0, 0, 0, 0)
        self._name = QLabel()
        self._name.setObjectName('posProdName')
        # Wrap up to 3 lines (taller cards) — badge lives on the bottom row, not beside name
        self._name.setWordWrap(True)
        self._name.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._display_name = name
        self._name_lines = 2 if self._compact else 3
        tcol.addWidget(self._name)
        if sku:
            self._sku = QLabel(sku)
            self._sku.setObjectName('posProdSku')
            self._sku_text = sku
            tcol.addWidget(self._sku)
        else:
            self._sku = None
            self._sku_text = ''
        if self._compact:
            # Zero price → muted "not priced" (never bold KES 0.00)
            if self._unpriced:
                self._price = QLabel('—')
                self._price.setToolTip('No sell price set')
                self._price_text = '—'
            else:
                price_txt = f'{self._currency} {safe_price(price)}'
                self._price = QLabel()
                self._price_text = price_txt
                self._price.setToolTip(price_txt)
            self._price.setObjectName('posProdPrice')
            self._badge = StockBadge(stock_n, unit, parent=self)
            self._badge.setObjectName('posStockBadge')
            self._badge.setVisible(True)
            tcol.addWidget(self._price)
            badge_row = QHBoxLayout()
            badge_row.setContentsMargins(0, 0, 0, 0)
            badge_row.setSpacing(4)
            badge_row.addWidget(self._badge, 0, Qt.AlignLeft | Qt.AlignVCenter)
            badge_row.addStretch(1)
            tcol.addLayout(badge_row)
        top.addLayout(tcol, 1)
        lay.addLayout(top)

        if not self._compact:
            lay.addStretch(1)
            bot = QHBoxLayout()
            bot.setSpacing(6)
            if self._unpriced:
                self._price = QLabel('—')
                self._price.setToolTip('No sell price set')
                self._price_text = '—'
            else:
                price_txt = f'{self._currency} {safe_price(price)}'
                self._price = QLabel()
                self._price_text = price_txt
                self._price.setToolTip(price_txt)
            self._price.setObjectName('posProdPrice')
            bot.addWidget(self._price, 1)
            self._badge = StockBadge(stock_n, unit, parent=self)
            self._badge.setObjectName('posStockBadge')
            self._badge.setVisible(True)
            bot.addWidget(self._badge, 0, Qt.AlignRight | Qt.AlignVCenter)
            lay.addLayout(bot)

        self.set_card_active(not self._oos)
        tip_bits = []
        if self._oos:
            tip_bits.append('Out of stock')
        if self._unpriced:
            tip_bits.append('No sell price set')
        if not tip_bits:
            tip_bits.append(f"{name}\nStock: {stock} {unit}")
        else:
            tip_bits.insert(0, name)
            tip_bits.append(f'Stock: {stock} {unit}')
        self.setToolTip('\n'.join(tip_bits))
        self._name.setToolTip(name)
        self._reflow_text()
        # Real elevation — QSS alone can't do soft shadows in Qt; this is what
        # gives cards a "lifted" modern feel instead of a flat outlined box.
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(18)
        self._shadow.setOffset(0, 3)
        self.setGraphicsEffect(self._shadow)
        self.refresh_theme()

    def _name_width_budget(self) -> int:
        """Width available for the product name (icon column only — badge is bottom-row)."""
        w = max(int(self.width() or 0), int(getattr(self, '_card_h', 0) and self.minimumWidth() or 0),
                int(self.minimumWidth() or 0))
        if w < 80:
            w = int(self.sizeHint().width() or 0) or 220
            # Prefer designed card width stored at construct
            try:
                w = max(w, int(self.maximumWidth() if self.maximumWidth() < 10000 else 0) or 0)
            except Exception:
                pass
            # Fall back to fixed size from construct
            try:
                fw = int(self.size().width() or 0)
                if fw > 80:
                    w = fw
            except Exception:
                pass
        # Use stored design width when still unknown (pre-show)
        design_w = int(getattr(self, '_design_w', 0) or 0)
        if design_w > 80:
            w = max(w, design_w)
        icon_sz = int(getattr(self, '_icon_sz', 44) or 44)
        pad = int(getattr(self, '_pad', 12) or 12)
        return max(96, w - (icon_sz + pad * 2 + 18))

    def _reflow_text(self):
        """Re-wrap name/sku/price for current card width (fixes clip on stretch)."""
        name = getattr(self, '_display_name', '') or ''
        name_w = self._name_width_budget()
        lines = int(getattr(self, '_name_lines', 2) or 2)
        if hasattr(self, '_name') and self._name is not None:
            self._set_elided(self._name, name, name_w, lines)
            self._name.setToolTip(name)
        sku = getattr(self, '_sku_text', '') or ''
        if self._sku is not None and sku:
            self._set_elided(self._sku, sku, name_w, 1)
        price_txt = getattr(self, '_price_text', '') or ''
        if hasattr(self, '_price') and self._price is not None and price_txt and price_txt != '—':
            # Leave room for stock badge on the price row (~88px) in non-compact
            if getattr(self, '_compact', False):
                pw = name_w
            else:
                pad = int(getattr(self, '_pad', 12) or 12)
                pw = max(70, int(self.width() or getattr(self, '_design_w', 220) or 220) - (pad * 2 + 96))
            self._set_elided(self._price, price_txt, pw, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        try:
            self._reflow_text()
        except Exception:
            pass

    def unlock_width(self, min_w: int | None = None):
        """Allow horizontal stretch in Checkout Pro 2-column grid."""
        # Prefer the designed card height — self.height() can be wrong pre-show
        h = int(getattr(self, '_card_h', 0) or self.height() or self.minimumHeight() or 132)
        if min_w:
            self.setMinimumWidth(int(min_w))
        else:
            self.setMinimumWidth(0)
        self.setMaximumWidth(16777215)
        self.setFixedHeight(h)
        sp = self.sizePolicy()
        sp.setHorizontalPolicy(QSizePolicy.Expanding)
        self.setSizePolicy(sp)
        try:
            self._reflow_text()
        except Exception:
            pass

    @staticmethod
    def _set_elided(label: QLabel, text: str, width: int, max_lines: int):
        safe = (text or '').strip()
        if not safe:
            label.setText('')
            return
        fm = label.fontMetrics()
        if max_lines <= 1:
            label.setText(fm.elidedText(safe, Qt.ElideRight, max(40, width)))
            return
        # Simple 2-line wrap + ellipsis
        words, lines, cur = safe.split(), [], ''
        for word in words:
            probe = (cur + ' ' + word).strip()
            if fm.horizontalAdvance(probe) <= width:
                cur = probe
            else:
                if cur:
                    lines.append(cur)
                if len(lines) >= max_lines:
                    cur = ''
                    break
                cur = word if fm.horizontalAdvance(word) <= width else fm.elidedText(
                    word, Qt.ElideRight, width)
        if cur and len(lines) < max_lines:
            lines.append(cur)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
        if lines and ' '.join(lines) != safe:
            lines[-1] = fm.elidedText(lines[-1], Qt.ElideRight, width)
        label.setText('\n'.join(lines[:max_lines]))

    def product(self) -> dict:
        return self._product

    def set_card_active(self, active: bool):
        self._active = bool(active)
        self.setCursor(Qt.PointingHandCursor if self._active else Qt.ArrowCursor)

    def mousePressEvent(self, event):
        if self._active and event.button() == Qt.LeftButton:
            self.clicked.emit(self._product)
            event.accept()
            return
        super().mousePressEvent(event)

    def enterEvent(self, event):
        if self._active:
            self.setProperty('hovered', True)
            self.refresh_theme(hover=True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setProperty('hovered', False)
        self.refresh_theme(hover=False)
        super().leaveEvent(event)

    def refresh_theme(self, hover=False):
        r = RADIUS['lg'] if getattr(self, '_compact', False) else RADIUS['xl']
        if self._oos:
            self.setStyleSheet(
                f"QFrame#posProdCard{{background:{C['panel']};border:1px dashed {C['border']};"
                f"border-radius:{r}px;}}")
        elif hover:
            self.setStyleSheet(
                f"QFrame#posProdCard{{background:{C['hover']};border:1px solid {C['gold']};"
                f"border-radius:{r}px;}}")
        else:
            self.setStyleSheet(
                f"QFrame#posProdCard{{background:{C['card2']};border:1px solid {C['border']};"
                f"border-radius:{r}px;}}"
                f"QFrame#posProdCard:hover{{background:{C['hover']};border-color:{C['gold']};}}")
        # Elevation — flat for out-of-stock (reads as disabled/receded), soft lift
        # at rest, a touch stronger + gold-tinted on hover so the tile feels "pressable".
        sh = getattr(self, '_shadow', None)
        if sh is not None:
            if self._oos:
                sh.setEnabled(False)
            else:
                sh.setEnabled(True)
                if hover:
                    sh.setBlurRadius(26)
                    sh.setOffset(0, 5)
                    sh.setColor(QColor(*_parse_hex_rgb(C['gold']), 90))
                else:
                    sh.setBlurRadius(16)
                    sh.setOffset(0, 3)
                    sh.setColor(QColor(0, 0, 0, 70))
        name_sz = '13px' if getattr(self, '_compact', False) else '14px'
        name_color = C['muted'] if self._oos else C['text']
        self._name.setStyleSheet(
            f"QLabel#posProdName{{color:{name_color}; font-size:{name_sz}; font-weight:800; "
            f"line-height:1.2; background:transparent; border:none;}}")
        if self._sku is not None:
            # Secondary metadata — readable at retail counter (was 9px muted)
            self._sku.setStyleSheet(
                f"QLabel#posProdSku{{color:{C['text2']}; font-size:12px; font-weight:600; "
                f"letter-spacing:0.2px; background:transparent; border:none;}}")
        # Slightly smaller so "KES 1,070.00" never clips card edge
        price_sz = '14px' if getattr(self, '_compact', False) else '15px'
        if getattr(self, '_unpriced', False) or self._oos:
            self._price.setStyleSheet(
                f"QLabel#posProdPrice{{color:{C['muted']}; font-size:13px; font-weight:600; "
                f"background:transparent; border:none;}}")
        else:
            self._price.setStyleSheet(
                f"QLabel#posProdPrice{{color:{C['text']}; font-size:{price_sz}; font-weight:800; "
                f"background:transparent; border:none;}}")
        self._icon.refresh_theme()
        self._badge.refresh_from(self._product.get('stock', 0) or 0,
                                 self._product.get('unit', 'pcs') or 'pcs')


# ── QuantityControl ───────────────────────────────────────────────────────────

class QuantityControl(QWidget):
    """
    Flat − | value | + stepper for cart Qty / Disc.
    Single outer shell (no nested button boxes) so dark mode does not clip glyphs.
    Touch-friendly (≥44px) when touch=True.
    """
    valueChanged = pyqtSignal(float)

    def __init__(
        self,
        value=1.0,
        step=0.25,
        parent=None,
        *,
        minimum=None,
        maximum=99999.0,
        snap=True,
        decimals=2,
        width=124,
        touch=False,
        height=None,
    ):
        super().__init__(parent)
        self._step = float(step) if step else 0.25
        self._snap = bool(snap)
        self._minimum = float(self._step if minimum is None else minimum)
        self._maximum = float(maximum)
        self._touch = bool(touch)
        if height is not None:
            shell_h = max(24, int(height))
        else:
            shell_h = TOUCH_MIN if self._touch else 36
        btn_w = 40 if self._touch else (26 if shell_h <= 30 else 30)
        btn_h = max(18, shell_h - 4)
        spin_h = max(18, shell_h - 4)
        self.setObjectName('qtyControl')
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(shell_h)
        self.setFixedWidth(int(max(width, 140 if self._touch else width)))
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(0)

        # ASCII +/- render reliably; Unicode minus often clips under Fusion + radius
        self._minus = QPushButton('-')
        self._plus = QPushButton('+')
        for b in (self._minus, self._plus):
            b.setObjectName('qtyBtn')
            b.setFixedSize(btn_w, btn_h)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            b.setFlat(True)

        self._spin = QDoubleSpinBox()
        self._spin.setObjectName('qtyInput')
        self._spin.setRange(self._minimum, self._maximum)
        self._spin.setDecimals(int(decimals))
        self._spin.setSingleStep(self._step)
        self._spin.setValue(self._coerce(value))
        self._spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self._spin.setAlignment(Qt.AlignCenter)
        self._spin.setFixedHeight(spin_h)
        self._spin.setFrame(False)
        le = self._spin.lineEdit()
        if le:
            le.setAlignment(Qt.AlignCenter)
            le.setFrame(False)

        self._spin.valueChanged.connect(self._on_spin)
        self._minus.clicked.connect(lambda: self._bump(-self._step))
        self._plus.clicked.connect(lambda: self._bump(self._step))
        lay.addWidget(self._minus)
        lay.addWidget(self._spin, 1)
        lay.addWidget(self._plus)
        self.refresh_theme()

    def _coerce(self, v) -> float:
        if self._snap:
            return round_qty(v, self._step, minimum=self._minimum)
        try:
            return max(self._minimum, min(self._maximum, round(float(v), 2)))
        except (TypeError, ValueError):
            return self._minimum

    def value(self) -> float:
        return float(self._spin.value())

    def setValue(self, v):
        self._spin.blockSignals(True)
        self._spin.setValue(self._coerce(v))
        self._spin.blockSignals(False)

    def _bump(self, delta):
        self.setValue(self.value() + delta)
        self.valueChanged.emit(self.value())

    def _on_spin(self, v):
        q = self._coerce(v)
        if abs(q - float(v)) > 1e-9:
            self._spin.blockSignals(True)
            self._spin.setValue(q)
            self._spin.blockSignals(False)
        self.valueChanged.emit(q)

    def refresh_theme(self):
        shell = C['input']
        fg = C['text']
        bd = C['border2']
        hover = C['hover']
        gold = C['gold']
        btn_min = 38 if getattr(self, '_touch', False) else max(22, int(self.height() or 34) - 8)
        font_sz = 18 if getattr(self, '_touch', False) else 15
        # Flat shell only — buttons/spin stay transparent (avoids dark semicircle artifacts)
        self.setStyleSheet(
            f"QWidget#qtyControl{{background:{shell};border:1.5px solid {bd};"
            f"border-radius:10px;}}"
            f"QPushButton#qtyBtn{{background:transparent;color:{fg};border:none;"
            f"border-radius:8px;font-size:{font_sz}px;font-weight:800;padding:0;"
            f"min-width:{btn_min}px;max-width:{btn_min + 4}px;min-height:{btn_min}px;}}"
            f"QPushButton#qtyBtn:hover{{background:{hover};color:{gold};}}"
            f"QPushButton#qtyBtn:pressed{{background:{qss_alpha(gold, 0.18)};color:{gold};}}"
            f"QDoubleSpinBox#qtyInput{{background:transparent;color:{fg};border:none;"
            f"padding:0;margin:0;font-size:14px;font-weight:700;}}"
            f"QDoubleSpinBox#qtyInput:focus{{background:transparent;}}"
            f"QDoubleSpinBox#qtyInput::up-button,QDoubleSpinBox#qtyInput::down-button{{"
            f"width:0;height:0;border:none;}}"
        )


# ── Cart table geometry ───────────────────────────────────────────────────────
# Single source of truth for the table-density cart. The column header is built
# from the same numbers as the rows, so the two can never drift apart again.
CART_ROW_H = 56
CART_CTRL_H = 34
CART_ROW_MARGINS = (10, 10, 10, 10)
CART_ROW_SPACING = 8
CART_COL_IDX_W = 22
CART_COL_QTY_W = 100
CART_COL_PRICE_W = 88
CART_COL_DISC_W = 100
CART_COL_TOTAL_W = 96
CART_COL_RM_W = 28
CART_COL_NAME_STRETCH = 3
# Cashier viewport: 5 complete compact rows (name/qty/price); Review still expands.
CART_CASHIER_ROWS = 5
CART_TABLE_ROW_GAP = 4
CART_COL_HDR_H = 28
CART_FLASH_MS = 520


def cart_viewport_px(rows: int = CART_CASHIER_ROWS, *, include_header: bool = False) -> int:
    """Pixel height for ``rows`` complete table-density cart lines."""
    n = max(1, int(rows or CART_CASHIER_ROWS))
    body = n * CART_ROW_H + max(0, n - 1) * CART_TABLE_ROW_GAP + 8
    if include_header:
        body += CART_COL_HDR_H
    return body


class MoneyEdit(QDoubleSpinBox):
    """Right-aligned KES editor for cart price — typed, not stepped.

    A ± stepper would need ~120px; the price column is 96px so the extra 26px
    goes to the product name instead. Exposes ``_spin`` / ``refresh_theme`` so
    it is drop-in compatible with QuantityControl inside CartLineRow.
    """

    def __init__(self, value=0.0, parent=None, *, width=CART_COL_PRICE_W, height=42):
        super().__init__(parent)
        self.setObjectName('posCartMoneyEdit')
        self._spin = self
        self.setRange(0.0, 99999999.0)
        self.setDecimals(2)
        self.setSingleStep(1.0)
        self.setValue(float(value or 0))
        self.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.setFixedWidth(int(width))
        self.setFixedHeight(int(height))
        self.setFrame(False)
        self.refresh_theme()

    def refresh_theme(self):
        self.setStyleSheet(
            f"QDoubleSpinBox#posCartMoneyEdit{{background:{C['input']};color:{C['text']};"
            f"border:1.5px solid {C['border2']};border-radius:10px;"
            f"padding:0 8px;font-size:14px;font-weight:700;}}"
            f"QDoubleSpinBox#posCartMoneyEdit:focus{{border-color:{C['gold']};}}"
            f"QDoubleSpinBox#posCartMoneyEdit::up-button,"
            f"QDoubleSpinBox#posCartMoneyEdit::down-button{{width:0;height:0;border:none;}}")


def build_cart_column_header(parent=None) -> QWidget:
    """Cart column header sharing CartLineRow's exact column geometry.

    Each caption is given the same fixed width and alignment as the control it
    labels, so headers stay locked to their column at every panel width.
    """
    hdr = QWidget(parent)
    hdr.setObjectName('posCartColHdr')
    hdr.setAttribute(Qt.WA_StyledBackground, True)
    hl = QHBoxLayout(hdr)
    left, _top, right, _bot = CART_ROW_MARGINS
    hl.setContentsMargins(left, 6, right, 6)
    hl.setSpacing(CART_ROW_SPACING)

    def cap(text: str, width: int | None, align, stretch: int = 0, tip: str = ''):
        lab = QLabel(text)
        lab.setObjectName('posCartColLab')
        lab.setAlignment(align | Qt.AlignVCenter)
        if tip:
            lab.setToolTip(tip)
        if width is not None:
            lab.setFixedWidth(width)
        if stretch:
            hl.addWidget(lab, stretch)
        else:
            hl.addWidget(lab, 0)
        return lab

    cap('#', CART_COL_IDX_W, Qt.AlignCenter)
    cap('Product', None, Qt.AlignLeft, CART_COL_NAME_STRETCH)
    cap('Qty', CART_COL_QTY_W, Qt.AlignCenter, 0, 'Line quantity — use − / + or type')
    cap('Price', CART_COL_PRICE_W, Qt.AlignRight, 0, 'Unit price — double-click a row to edit')
    cap('Disc', CART_COL_DISC_W, Qt.AlignCenter, 0, 'Per-item discount (KES) — editable on every line')
    cap('Total', CART_COL_TOTAL_W, Qt.AlignRight, 0, 'Line total after discount')
    # Spacer matching the remove button so every caption above stays on column
    spacer = QLabel('')
    spacer.setObjectName('posCartColLab')
    spacer.setFixedWidth(CART_COL_RM_W)
    hl.addWidget(spacer, 0)
    return hdr


# ── Cart line (shopping-cart row — not spreadsheet) ───────────────────────────

class CartLineRow(QFrame):
    """Cart row — card density (explorer) or compact table density (Checkout Pro)."""
    qtyChanged = pyqtSignal(float)
    discChanged = pyqtSignal(float)
    priceChanged = pyqtSignal(float)
    removeClicked = pyqtSignal()
    rowClicked = pyqtSignal()

    def __init__(self, item: dict, currency='KES', parent=None, *,
                 density='table', index=1):
        super().__init__(parent)
        self._item = item or {}
        self._currency = currency or 'KES'
        self._selected = False
        self._flashing = False
        self._density = 'table'
        self._index = int(index)
        self.setObjectName('posCartLine')
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        self._build_table()
        # Drop-shadow on 56px rows blurs the product name into dashed noise.
        self._shadow = None
        self._sync_labels()
        self.refresh_theme()

    def _build_table(self):
        """Compact-but-legible: # | Product | Qty ± | Price/Disc labels | Total | trash."""
        self._editing_money = False
        # Compact POS list row — 5+ lines visible; not a hero product card.
        self.setFixedHeight(CART_ROW_H)
        self.setMinimumHeight(CART_ROW_H)
        self.setMaximumHeight(CART_ROW_H)
        try:
            self.setAttribute(Qt.WA_StyledBackground, True)
        except Exception:
            pass
        root = QHBoxLayout(self)
        root.setContentsMargins(*CART_ROW_MARGINS)
        root.setSpacing(CART_ROW_SPACING)

        self._idx_lbl = QLabel(str(self._index))
        self._idx_lbl.setObjectName('posCartIdx')
        self._idx_lbl.setFixedWidth(CART_COL_IDX_W)
        self._idx_lbl.setAlignment(Qt.AlignCenter)
        root.addWidget(self._idx_lbl)

        # Single-line name — SKU in tooltip (stacked name+sku overflowed 40px rows)
        pname = (self._item.get('product_name') or '').strip() or 'Item'
        sku = (self._item.get('sku') or '').strip()
        self._name = QLabel(pname)
        self._name.setObjectName('posCartName')
        self._name.setWordWrap(False)
        self._name.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._name.setMinimumHeight(22)
        try:
            nf = QFont(self._name.font())
            nf.setPixelSize(15)
            nf.setBold(True)
            nf.setStyleStrategy(QFont.PreferAntialias)
            self._name.setFont(nf)
        except Exception:
            pass
        tip = f'{pname}\n{sku}' if sku else pname
        self._name.setToolTip(tip)
        root.addWidget(self._name, CART_COL_NAME_STRETCH)
        self._sku = QLabel('')
        self._sku.hide()

        self._thumb = None
        self._unit_lbl = QLabel()
        self._unit_lbl.hide()
        self._save_lbl = QLabel('')
        self._save_lbl.hide()

        self._qty = QuantityControl(
            value=float(self._item.get('quantity') or 1),
            step=0.25, minimum=0.25, width=CART_COL_QTY_W, touch=False, height=CART_CTRL_H)
        self._qty.valueChanged.connect(self.qtyChanged.emit)
        root.addWidget(self._qty, 0)

        # Contextual money editors — label by default, typed editor on double-click.
        # Both are the same fixed width so the column never shifts while editing.
        self._price = MoneyEdit(
            float(self._item.get('unit_price') or 0), width=CART_COL_PRICE_W, height=CART_CTRL_H)
        self._price.valueChanged.connect(self.priceChanged.emit)
        self._price_lbl = QLabel()
        self._price_lbl.setObjectName('posCartMoneyLbl')
        self._price_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._price_lbl.setFixedWidth(CART_COL_PRICE_W)
        self._price_lbl.setToolTip('Double-click row to edit price')
        self._price_lbl.setCursor(Qt.PointingHandCursor)
        money_price = QWidget()
        money_price.setFixedWidth(CART_COL_PRICE_W)
        mpl = QHBoxLayout(money_price)
        mpl.setContentsMargins(0, 0, 0, 0)
        mpl.setSpacing(0)
        mpl.addWidget(self._price_lbl)
        mpl.addWidget(self._price)
        root.addWidget(money_price, 0)

        self._disc = QuantityControl(
            value=float(self._item.get('discount') or 0),
            step=10.0, minimum=0.0, maximum=999999.0,
            snap=False, width=CART_COL_DISC_W, touch=False, height=CART_CTRL_H)
        self._disc.valueChanged.connect(self.discChanged.emit)
        self._disc.setToolTip('Per-item discount (KES)')
        self._disc_lbl = QLabel()
        self._disc_lbl.setObjectName('posCartMoneyLbl')
        self._disc_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._disc_lbl.setFixedWidth(CART_COL_DISC_W)
        self._disc_lbl.setToolTip('Per-item discount (KES)')
        self._disc_lbl.setCursor(Qt.PointingHandCursor)
        self._disc_lbl.hide()  # filled in _sync_labels
        money_disc = QWidget()
        money_disc.setFixedWidth(CART_COL_DISC_W)
        mdl = QHBoxLayout(money_disc)
        mdl.setContentsMargins(0, 0, 0, 0)
        mdl.setSpacing(0)
        mdl.addWidget(self._disc_lbl)
        mdl.addWidget(self._disc)
        root.addWidget(money_disc, 0)
        self._disc.hide()

        self._line_total = QLabel()
        self._line_total.setObjectName('posCartLineTot')
        self._line_total.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._line_total.setFixedWidth(CART_COL_TOTAL_W)
        root.addWidget(self._line_total, 0)

        self._rm = QPushButton('×')
        self._rm.setObjectName('posCartRemove')
        self._rm.setFixedSize(CART_COL_RM_W, CART_COL_RM_W)
        self._rm.setCursor(Qt.PointingHandCursor)
        self._rm.setToolTip('Remove line')
        self._rm.setFlat(True)
        self._rm.clicked.connect(self.removeClicked.emit)
        root.addWidget(self._rm, 0)
        self._set_money_edit_mode(False)

    def _build_card(self):
        """Legacy card density — same compact table row (hero cards hid the cart)."""
        self._density = 'table'
        self._build_table()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.rowClicked.emit()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self._density == 'table' and event.button() == Qt.LeftButton:
            self._set_money_edit_mode(True)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _set_money_edit_mode(self, on: bool):
        """Table density: price/disc spinboxes on demand — idle rows show labels."""
        if self._density != 'table':
            return
        self._editing_money = bool(on)
        show_edit = self._editing_money
        if getattr(self, '_price_lbl', None) is not None:
            self._price_lbl.setVisible(not show_edit)
        self._price.setVisible(show_edit)
        if getattr(self, '_disc_lbl', None) is not None:
            self._disc_lbl.setVisible(not show_edit)
        self._disc.setVisible(show_edit)
        if show_edit:
            try:
                spin = getattr(self._price, '_spin', None)
                if spin is not None:
                    spin.setFocus(Qt.OtherFocusReason)
                    spin.selectAll()
            except Exception:
                pass

    def set_selected(self, on: bool):
        self._selected = bool(on)
        # Leaving selection collapses money editors (labels only) — reduces misclicks
        if self._density == 'table' and not on:
            self._set_money_edit_mode(False)
        if not getattr(self, '_flashing', False):
            self.refresh_theme()

    def is_selected(self) -> bool:
        return bool(self._selected)

    def flash_added(self, ms: int = CART_FLASH_MS):
        """Brief gold wash when a line is newly added — does not change selection."""
        self._flashing = True
        try:
            self.setStyleSheet(
                f"QFrame#posCartLine{{background:{qss_alpha(C['gold'], 0.28)};"
                f"border:2px solid {C['gold']};border-radius:{RADIUS['sm']}px;}}"
                f"QLabel{{background:transparent;}}")
        except Exception:
            pass
        try:
            QTimer.singleShot(max(120, int(ms)), self._end_flash)
        except Exception:
            self._end_flash()

    def _end_flash(self):
        self._flashing = False
        try:
            self.refresh_theme()
        except Exception:
            pass

    def focus_qty_editor(self):
        try:
            spin = getattr(self._qty, '_spin', None)
            if spin is not None:
                spin.setFocus(Qt.OtherFocusReason)
                spin.selectAll()
        except Exception:
            pass

    def _sync_labels(self):
        cur = self._currency
        up = float(self._item.get('unit_price') or 0)
        tot = float(self._item.get('total') or 0)
        disc = float(self._item.get('discount') or 0)
        if self._unit_lbl is not None and self._unit_lbl.isVisible():
            self._unit_lbl.setText(f'{cur} {up:,.2f} each')
        # Table density: omit currency prefix so totals never clip against remove btn
        if self._density == 'table':
            self._line_total.setText(f'{tot:,.2f}')
        else:
            self._line_total.setText(f'{cur} {tot:,.2f}')
        if getattr(self, '_price_lbl', None) is not None:
            self._price_lbl.setText(f'{up:,.2f}')
        if getattr(self, '_disc_lbl', None) is not None:
            self._disc_lbl.setText('—' if disc <= 0.009 else f'{disc:,.2f}')
            self._disc_lbl.setProperty('mbtHasDisc', '1' if disc > 0.009 else '0')
            self._disc_lbl.style().unpolish(self._disc_lbl); self._disc_lbl.style().polish(self._disc_lbl)
        if self._save_lbl is not None:
            if disc > 0.009 and self._density != 'table':
                self._save_lbl.setText(f'Save {cur} {disc:,.2f}')
                self._save_lbl.show()
            else:
                self._save_lbl.hide()
        if self._idx_lbl is not None:
            self._idx_lbl.setText(str(self._index))

    def update_item(self, item: dict):
        self._item = item or {}
        self._qty.blockSignals(True)
        self._disc.blockSignals(True)
        self._price.blockSignals(True)
        try:
            self._qty.setValue(float(self._item.get('quantity') or 1))
            self._disc.setValue(float(self._item.get('discount') or 0))
            self._price.setValue(float(self._item.get('unit_price') or 0))
        finally:
            self._qty.blockSignals(False)
            self._disc.blockSignals(False)
            self._price.blockSignals(False)
        name = (self._item.get('product_name') or '').strip() or 'Item'
        self._name.setText(name)
        sku = (self._item.get('sku') or '').strip()
        self._sku.setText(sku if sku else f"#{self._item.get('product_id', '')}")
        self._sync_labels()

    def set_index(self, index: int):
        self._index = int(index)
        if self._idx_lbl is not None:
            self._idx_lbl.setText(str(self._index))

    def refresh_theme(self):
        if getattr(self, '_flashing', False):
            return
        # Selection gold only when selected — avoid yellow wash on every control
        border = C['gold'] if self._selected else C['border']
        stripe = C['card'] if (int(getattr(self, '_index', 1) or 1) % 2) else C['card2']
        bg = qss_alpha(C['gold'], 0.10) if self._selected else stripe
        hover_bg = C['hover'] if not self._selected else qss_alpha(C['gold'], 0.14)
        rad = RADIUS['sm'] if self._density == 'table' else RADIUS['lg']
        bw = '2px' if self._selected else ('1px' if self._density == 'table' else '1.5px')
        rm_pad = '0' if self._density == 'table' else '0 10px'
        rm_size = '17px' if self._density == 'table' else '12px'
        name_sz = '15px'
        tot_sz = '15px'
        money_sz = '14px'
        if self._density == 'table':
            rm_bg, rm_bd = 'transparent', 'transparent'
            rm_hover = f"background:{C['err_dim']};color:{C['err']};"
        else:
            rm_bg, rm_bd = C['err_dim'], qss_alpha(C['err'], 0.45)
            rm_hover = f"background:{C['err']};color:#FFFFFF;"
        self.setStyleSheet(
            f"QFrame#posCartLine{{background:{bg};border:{bw} solid {border};"
            f"border-radius:{rad}px;}}"
            f"QFrame#posCartLine:hover{{border-color:{qss_alpha(C['gold'], 0.55)};"
            f"background:{hover_bg};}}"
            f"QFrame#posCartQtyBox,QFrame#posCartPriceBox{{background:{C['input']};"
            f"border:1px solid {C['border']};border-radius:10px;}}"
            f"QFrame#posCartDiscBox{{background:{C['input']};"
            f"border:1px solid {C['border']};border-radius:10px;}}"
            f"QLabel#posCartName{{color:{C['text']};font-size:{name_sz};font-weight:800;"
            f"background:transparent;min-height:22px;padding:0;}}"
            f"QLabel#posCartSku{{color:{C['text2']};font-size:11px;font-weight:600;"
            f"background:transparent;}}"
            f"QLabel#posCartIdx{{color:{C['text2']};"
            f"font-size:{'12px' if self._density == 'table' else '11px'};font-weight:800;"
            f"background:transparent;}}"
            f"QLabel#posCartUnit{{color:{C['text2']};font-size:12px;font-weight:600;"
            f"background:transparent;}}"
            f"QLabel#posCartCap{{color:{C['text2']};font-size:11px;font-weight:800;"
            f"background:transparent;min-width:28px;}}"
            f"QLabel#posCartDiscCap{{color:{C['text2']};font-size:11px;font-weight:800;"
            f"background:transparent;}}"
            f"QLabel#posCartMoneyLbl{{color:{C['text2']};font-size:{money_sz};font-weight:600;"
            f"background:transparent;padding:0 4px;}}"
            f"QLabel#posCartMoneyLbl[mbtHasDisc=\"1\"]{{color:{C['ok']};font-weight:800;"
            f"background:transparent;padding:0 4px;}}"
            f"QLabel#posCartLineTot{{color:{C['text']};font-size:{tot_sz};font-weight:900;"
            f"background:transparent;min-width:72px;}}"
            f"QLabel#posCartSave{{color:{C['ok']};font-size:11px;font-weight:800;"
            f"background:transparent;}}"
            f"QPushButton#posCartRemove{{background:{rm_bg};color:{C['err']};"
            f"border:1px solid {rm_bd};border-radius:6px;"
            f"font-weight:800;font-size:{rm_size};padding:{rm_pad};}}"
            f"QPushButton#posCartRemove:hover{{{rm_hover}}}"
        )
        sh = getattr(self, '_shadow', None)
        if sh is not None:
            sh.setEnabled(self._selected)
            if self._selected:
                sh.setColor(QColor(*_parse_hex_rgb(C['gold']), 70))
        for qc in (self._qty, self._disc, self._price):
            qc.refresh_theme()
        if self._thumb is not None:
            self._thumb.refresh_theme()


class CartList(QWidget):
    """Scrollable stack of CartLineRow — card or compact table density."""
    qtyChanged = pyqtSignal(int, float)
    discChanged = pyqtSignal(int, float)
    priceChanged = pyqtSignal(int, float)
    removeClicked = pyqtSignal(int)
    selectionChanged = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('posCartList')
        self._rows = []
        self._selected_idx = -1
        self._density = 'table'
        self._col_hdr = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._outer = outer

        self._scroll = QScrollArea()
        self._scroll.setObjectName('posCartListScroll')
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setMinimumHeight(cart_viewport_px(CART_CASHIER_ROWS))
        self._scroll.setMaximumHeight(16777215)
        self._scroll.setStyleSheet('QScrollArea{border:none;background:transparent;}')
        try:
            from desktop.utils.no_wheel_small_scroll import mark_wheel_scroll
            mark_wheel_scroll(self._scroll, True)
        except Exception:
            pass
        self._scroll.setFocusPolicy(Qt.StrongFocus)

        self._body = QWidget()
        self._body.setObjectName('posCartListBody')
        self._lay = QVBoxLayout(self._body)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(CART_TABLE_ROW_GAP)
        self._empty = QLabel('Cart is empty\nTap a product to add it.')
        self._empty.setAlignment(Qt.AlignCenter)
        self._empty.setObjectName('posCartEmpty')
        self._lay.addWidget(self._empty)
        self._cart_room_hint = QLabel('Scan or tap products to add more…')
        self._cart_room_hint.setObjectName('posCartRoomHint')
        self._cart_room_hint.setAlignment(Qt.AlignCenter)
        self._cart_room_hint.hide()
        self._lay.addWidget(self._cart_room_hint)
        self._lay.addStretch(1)
        self._scroll.setWidget(self._body)
        outer.addWidget(self._scroll)
        self._expanded = False
        # 0 = legacy sizing; N = fixed viewport of N table rows (Review lifts via expanded).
        self._cashier_rows = 0
        self.refresh_theme()

    def selected_index(self) -> int:
        return int(self._selected_idx)

    def set_density(self, density: str):
        density = 'table'
        if self._density == density:
            return
        self._density = density
        self._lay.setSpacing(CART_TABLE_ROW_GAP)
        # Force rebuild on next set_items
        items = [dict(r._item) for r in self._rows]
        cur = self._currency if hasattr(self, '_currency') else 'KES'
        sel = self._selected_idx
        if items:
            self.set_items(items, currency=cur, select_index=sel if sel >= 0 else None)

    def set_column_header(self, hdr: QWidget | None):
        # Remove previous header from outer layout
        if self._col_hdr is not None:
            self._outer.removeWidget(self._col_hdr)
            try:
                from desktop.utils.quiet_ui import safe_detach
                safe_detach(self._col_hdr)
            except Exception:
                self._col_hdr.hide()
                self._col_hdr.setParent(None)
        self._col_hdr = hdr
        if hdr is not None:
            self._outer.insertWidget(0, hdr)
            hdr.show()

    def set_expanded(self, expanded: bool):
        """Review mode: lift the cashier viewport so extra tall rows can fill the pane.

        When False and ``set_cashier_viewport`` is active, the list keeps at least
        CART_CASHIER_ROWS complete lines visible and only the cart body scrolls.
        """
        self._expanded = bool(expanded)
        self._fit_scroll_to_rows()

    def set_cashier_viewport(self, rows: int = CART_CASHIER_ROWS):
        """Fix the cart body to ``rows`` complete table lines (header stays above).

        Review (``set_expanded(True)``) overrides this until Restore. Pass 0 to
        disable and fall back to legacy hug/expand sizing.
        """
        self._cashier_rows = max(0, int(rows or 0))
        self._fit_scroll_to_rows()

    def cashier_viewport_height(self) -> int:
        """Pixel height of the fixed cart-body viewport (scroll area only)."""
        rows = int(getattr(self, '_cashier_rows', 0) or 0) or CART_CASHIER_ROWS
        return cart_viewport_px(rows)

    def _fit_scroll_to_rows(self):
        """Size cart scroll — cashier viewport, Review expand, or legacy hug."""
        n = len(getattr(self, '_rows', []) or [])
        row_h = CART_ROW_H
        spacing = CART_TABLE_ROW_GAP
        needed = max(n, 1) * row_h + max(n - 1, 0) * spacing + 12
        hdr = 0
        if self._col_hdr is not None and self._col_hdr.isVisible():
            try:
                hdr = max(22, int(self._col_hdr.sizeHint().height()))
            except Exception:
                hdr = 22
        cashier = int(getattr(self, '_cashier_rows', 0) or 0)
        if self._expanded:
            # Review: pane height is owned by the cart splitter — soft floor only.
            self._scroll.setMinimumHeight(80)
            self._scroll.setMaximumHeight(16777215)
            try:
                sp = self.sizePolicy()
                sp.setVerticalPolicy(QSizePolicy.Expanding)
                self.setSizePolicy(sp)
                self.setMaximumHeight(16777215)
                self.setMinimumHeight(80)
            except Exception:
                pass
        elif cashier > 0 and self._density == 'table':
            # Cashier mode: at least N rows visible; body scrolls when more
            # items exist. Grows with the cart↔summary splitter so payment /
            # summary can shrink and give the list more room.
            viewport_h = cart_viewport_px(cashier)
            self._scroll.setMinimumHeight(viewport_h)
            self._scroll.setMaximumHeight(16777215)
            try:
                sp = self.sizePolicy()
                sp.setVerticalPolicy(QSizePolicy.Expanding)
                self.setSizePolicy(sp)
                self.setMinimumHeight(viewport_h + max(hdr, CART_COL_HDR_H))
                self.setMaximumHeight(16777215)
            except Exception:
                pass
        elif self._density == 'table' and n and n <= 10:
            # Table carts (non-cashier): hug content so summary sits under last row
            self._scroll.setMinimumHeight(needed)
            self._scroll.setMaximumHeight(needed + 4)
            try:
                sp = self.sizePolicy()
                sp.setVerticalPolicy(QSizePolicy.Maximum)
                self.setSizePolicy(sp)
                self.setMinimumHeight(needed + hdr)
                self.setMaximumHeight(needed + hdr + 8)
            except Exception:
                pass
        else:
            floor = cart_viewport_px(CART_CASHIER_ROWS)
            self._scroll.setMinimumHeight(min(max(needed, floor), max(floor, 420)))
            self._scroll.setMaximumHeight(16777215)
            try:
                sp = self.sizePolicy()
                sp.setVerticalPolicy(QSizePolicy.Expanding)
                self.setSizePolicy(sp)
                self.setMaximumHeight(16777215)
                self.setMinimumHeight(0)
            except Exception:
                pass
        try:
            self._scroll.updateGeometry()
            self.updateGeometry()
        except Exception:
            pass

    def clear_rows(self):
        while self._rows:
            w = self._rows.pop()
            try:
                self._lay.removeWidget(w)
            except Exception:
                pass
            try:
                from desktop.utils.quiet_ui import safe_detach
                safe_detach(w)
            except Exception:
                try:
                    w.hide()
                    w.setParent(None)
                except Exception:
                    pass
            # Immediate delete — deleteLater leaves ghost rows that paint over table density
            try:
                from PyQt5 import sip
                if not sip.isdeleted(w):
                    sip.delete(w)
            except Exception:
                try:
                    w.deleteLater()
                except Exception:
                    pass
        self._selected_idx = -1
        self._empty.show()

    def set_items(self, items: list, currency='KES', select_index=None):
        """Rebuild rows. select_index: keep/select that line (default = last item)."""
        self._currency = currency or 'KES'
        self.clear_rows()
        items = items or []
        if not items:
            self._empty.show()
            self._fit_scroll_to_rows()
            return
        self._empty.hide()
        if hasattr(self, '_cart_room_hint') and self._cart_room_hint is not None:
            # Hint only when cart is sparse AND card density (table carts already dense)
            show_hint = len(items) < 4 and self._density != 'table'
            self._cart_room_hint.setVisible(show_hint)
        stretch_idx = self._lay.count() - 1
        for i, item in enumerate(items):
            row = CartLineRow(
                item, currency=currency, density=self._density, index=i + 1)
            row.qtyChanged.connect(lambda v, idx=i: self.qtyChanged.emit(idx, v))
            row.discChanged.connect(lambda v, idx=i: self.discChanged.emit(idx, v))
            row.priceChanged.connect(lambda v, idx=i: self.priceChanged.emit(idx, v))
            row.removeClicked.connect(lambda idx=i: self.removeClicked.emit(idx))
            row.rowClicked.connect(lambda idx=i: self.select_index(idx, focus_qty=False))
            self._lay.insertWidget(stretch_idx + i, row)
            try:
                from PyQt5.QtCore import Qt as _Qt
                row.setAttribute(_Qt.WA_DontShowOnScreen, False)
            except Exception:
                pass
            try:
                from desktop.utils.quiet_ui import safe_show
                safe_show(row)
            except Exception:
                try:
                    row.show()
                except Exception:
                    pass
            self._rows.append(row)
        self._fit_scroll_to_rows()
        if select_index is None:
            select_index = len(self._rows) - 1
        self.select_index(select_index, focus_qty=True, scroll=True)
        # Newest line: ensure visible + brief highlight (cashier scan feedback).
        try:
            flash_idx = int(select_index)
            if 0 <= flash_idx < len(self._rows):
                QTimer.singleShot(0, lambda i=flash_idx: self._scroll_and_flash(i))
        except Exception:
            pass

    def select_index(self, idx: int, focus_qty: bool = False, scroll: bool = True):
        if not self._rows:
            self._selected_idx = -1
            return
        idx = max(0, min(int(idx), len(self._rows) - 1))
        prev = self._selected_idx
        self._selected_idx = idx
        for i, row in enumerate(self._rows):
            row.set_selected(i == idx)
        if scroll:
            self.scroll_to_index(idx)
        if focus_qty:
            QTimer.singleShot(0, self._rows[idx].focus_qty_editor)
        if prev != idx:
            self.selectionChanged.emit(idx)

    def scroll_to_index(self, idx: int):
        if not (0 <= idx < len(self._rows)):
            return
        row = self._rows[idx]
        try:
            self._scroll.ensureWidgetVisible(row, 0, 24)
        except Exception:
            pass

    def _scroll_and_flash(self, idx: int):
        if not (0 <= idx < len(self._rows)):
            return
        self.scroll_to_index(idx)
        row = self._rows[idx]
        if hasattr(row, 'flash_added'):
            try:
                row.flash_added()
            except Exception:
                pass

    def update_row(self, idx: int, item: dict):
        if 0 <= idx < len(self._rows):
            self._rows[idx].update_item(item)

    def refresh_theme(self):
        self.setStyleSheet(
            f"QWidget#posCartList,QWidget#posCartListBody{{background:transparent;}}"
            f"QLabel#posCartEmpty{{color:{C['muted']};font-size:13px;font-weight:600;"
            f"background:transparent;padding:28px 12px;}}"
            f"QLabel#posCartRoomHint{{color:{C['muted']};font-size:12px;font-weight:600;"
            f"background:transparent;padding:28px 12px;}}")
        for r in self._rows:
            r.refresh_theme()


# ── PaymentButton / PaymentSegment ────────────────────────────────────────────

class PaymentButton(QPushButton):
    """Large checkable payment method tile."""

    def __init__(self, key: str, label: str, parent=None, *, enabled=True, secondary=False):
        super().__init__(label, parent)
        self.method_key = key
        self._secondary = bool(secondary)
        self._compact = False
        self.setObjectName('posPayToggle')
        self.setCheckable(True)
        self.setEnabled(bool(enabled))
        self.setCursor(Qt.PointingHandCursor if enabled else Qt.ForbiddenCursor)
        self.setMinimumHeight(56)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(14)
        self._shadow.setOffset(0, 2)
        self._shadow.setEnabled(False)
        self.setGraphicsEffect(self._shadow)
        self.toggled.connect(self._sync_shadow)
        self.refresh_theme()

    def _sync_shadow(self, *_args):
        sh = getattr(self, '_shadow', None)
        if sh is None:
            return
        checked = self.isChecked() and self.isEnabled() and not self._secondary
        sh.setEnabled(checked)
        if checked:
            sh.setColor(QColor(*_parse_hex_rgb(C['gold']), 80))

    def set_compact_style(self, compact: bool = True):
        self._compact = bool(compact)
        h = 40 if self._compact else 56
        self.setMinimumHeight(h)
        self.setMaximumHeight(h + 6)
        if self._compact:
            self.setMinimumWidth(0)
        self.refresh_theme()

    def refresh_theme(self):
        muted = C['muted']
        mh = 40 if getattr(self, '_compact', False) else 56
        pad = '4px 2px' if getattr(self, '_compact', False) else '8px 4px'
        fsz = '12px' if getattr(self, '_compact', False) else '13px'
        if not self.isEnabled() or self._secondary:
            self.setStyleSheet(
                f"QPushButton#posPayToggle{{background:{C['panel']};color:{muted};"
                f"border:1px dashed {C['border2']};border-radius:{RADIUS['md']}px;"
                f"font-size:11px;font-weight:700;min-height:{mh}px;padding:{pad};}}"
                f"QPushButton#posPayToggle:disabled{{color:{muted};}}")
            self._sync_shadow()
            return
        self.setStyleSheet(
            f"QPushButton#posPayToggle{{background:{C['card2']};color:{C['text2']};"
            f"border:1.5px solid {C['border']};border-radius:{RADIUS['md']}px;"
            f"font-size:{fsz};font-weight:700;min-height:{mh}px;padding:{pad};}}"
            f"QPushButton#posPayToggle:checked{{background:{qss_alpha(C['gold'], 0.14)};"
            f"color:{C['text']};border:2px solid {C['gold']};font-weight:800;}}"
            f"QPushButton#posPayToggle:hover:!checked{{background:{C['hover']};"
            f"color:{C['text']};border-color:{qss_alpha(C['gold'], 0.40)};}}"
            f"QPushButton#posPayToggle:pressed{{background:{qss_alpha(C['gold'], 0.12)};}}"
        )
        self._sync_shadow()


class PaymentSegment(QWidget):
    """Cash | M-Pesa | Card | Bank | Split tiles (no Gift/STK placeholders)."""
    methodChanged = pyqtSignal(str)

    # Display key → payment combo text (POS_PAYMENT_METHODS)
    # Gift Card omitted until implemented (U05 — no dead/coming-soon tiles).
    TILES = (
        ('Cash', 'Cash\nCash', True),
        ('M-Pesa', 'M-Pesa\nTill', True),
        ('Card', 'Card\nCard', True),
        ('Bank Transfer', 'Bank\nTransfer', True),
        ('Mixed', 'Split\nPay', True),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('posPaySegment')
        lay = QGridLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setHorizontalSpacing(8)
        lay.setVerticalSpacing(8)
        self._btns = {}
        for i, (key, label, enabled) in enumerate(self.TILES):
            # ASCII / plain labels — emoji fonts are unreliable across Windows PCs
            pretty = {
                'Cash': 'Cash',
                'M-Pesa': 'M-Pesa',
                'Card': 'Card',
                'Bank Transfer': 'Bank',
                'Mixed': 'Split',
            }.get(key, label)
            b = PaymentButton(key, pretty, enabled=enabled, secondary=not enabled)
            if key == 'Mixed':
                b.setToolTip(
                    'Split Pay — two tenders on one sale (cash + M-Pesa/card/bank). '
                    'With Paid now, tenders must cover the total. '
                    'With Part pay, leftover becomes customer debt.')
            if enabled:
                b.clicked.connect(lambda _=False, k=key: self.select(k, emit=True))
            lay.addWidget(b, i // 3, i % 3)
            self._btns[key] = b
        self.select('Cash', emit=False)

    def select(self, method: str, emit=True):
        # Map alternate labels
        alias = {
            'Bank': 'Bank Transfer',
            'Split': 'Mixed',
        }
        method = alias.get(method, method)
        for k, b in self._btns.items():
            if not b.isEnabled():
                continue
            b.blockSignals(True)
            b.setChecked(k == method)
            b.blockSignals(False)
        if emit and method in self._btns and self._btns[method].isEnabled():
            self.methodChanged.emit(method)

    def current(self) -> str:
        for k, b in self._btns.items():
            if b.isEnabled() and b.isChecked():
                return k
        return 'Cash'

    def refresh_theme(self):
        for b in self._btns.values():
            b.refresh_theme()

    def set_compact(self, compact: bool = True):
        """Tighter tiles for Checkout Pro narrow rail."""
        for b in self._btns.values():
            try:
                b.set_compact_style(compact)
            except Exception:
                h = 40 if compact else 56
                b.setMinimumHeight(h)
                b.setMaximumHeight(h + 6)
                try:
                    b.refresh_theme()
                except Exception:
                    pass
        lay = self.layout()
        if lay is not None:
            gap = 5 if compact else 8
            try:
                lay.setSpacing(gap)
            except Exception:
                pass
            if hasattr(lay, 'setHorizontalSpacing'):
                lay.setHorizontalSpacing(gap)
            if hasattr(lay, 'setVerticalSpacing'):
                lay.setVerticalSpacing(gap)

    def set_row_layout(self, row: bool = True):
        """Checkout Pro: five equal tiles in one horizontal row (or 3×2 grid when narrow)."""
        old = self.layout()
        keys = list(self._btns.keys())
        widgets = [self._btns[k] for k in keys]
        if old is not None:
            while old.count():
                old.takeAt(0)
            sink = QWidget()
            from PyQt5.QtCore import Qt as _Qt
            sink.setAttribute(_Qt.WA_DontShowOnScreen, True)
            sink.hide()
            sink.setLayout(old)
            sink.deleteLater()
        if row:
            lay = QHBoxLayout(self)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(6)
            for b in widgets:
                b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                b.setMinimumWidth(0)
                lay.addWidget(b, 1)
        else:
            lay = QGridLayout(self)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setHorizontalSpacing(5)
            lay.setVerticalSpacing(5)
            for i, b in enumerate(widgets):
                b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                b.setMinimumWidth(0)
                lay.addWidget(b, i // 3, i % 3)
        self.refresh_theme()


# ── SummaryCard ───────────────────────────────────────────────────────────────

class SummaryCard(QFrame):
    """Checkout totals panel — Grand Total dominant with subtle pulse on change."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('posTotFrame')
        self._last_total_text = ''
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)
        self._body = lay
        hdr = QLabel('Order Summary')
        hdr.setObjectName('posTotSection')
        lay.addWidget(hdr)
        self._section = hdr
        self._sub_lbl = self._row('Subtotal')
        self.disc_label = QLabel('Discount (KES)')
        self.disc_edit = None  # set by host (KES QLineEdit)
        self._tax_lbl = self._row('Tax')
        self._tax_row_w = getattr(self._tax_lbl, '_row_w', None)
        self._savings_row_w = QWidget()
        srl = QHBoxLayout(self._savings_row_w)
        srl.setContentsMargins(0, 0, 0, 0)
        self._savings_cap = QLabel('You save')
        self._savings_cap.setObjectName('posTotMute')
        self._savings_lbl = QLabel('KES 0.00')
        self._savings_lbl.setObjectName('posTotSave')
        srl.addWidget(self._savings_cap)
        srl.addStretch()
        srl.addWidget(self._savings_lbl)
        self._savings_row_w.hide()
        lay.addWidget(self._savings_row_w)
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setObjectName('posTotSep')
        lay.addWidget(sep)
        self._sep = sep
        tot = QHBoxLayout()
        self._total_hdr = QLabel('Grand Total')
        self._tot_lbl = QLabel('KES 0.00')
        self._tot_lbl.setObjectName('posGrandTotal')
        tot.addWidget(self._total_hdr)
        tot.addStretch()
        tot.addWidget(self._tot_lbl)
        lay.addLayout(tot)
        # No drop-shadow: SummaryCard sits under the cart splitter handle. A
        # QGraphicsDropShadowEffect paints into the gutter and makes drag feel
        # broken even though the handle still shows its tooltip.
        self.refresh_theme()

    def set_pro_chrome(self, enabled: bool = True):
        """Checkout Pro: drop 'Order Summary' chrome; keep totals + You save parity."""
        self._pro = bool(enabled)
        if hasattr(self, '_section') and self._section is not None:
            self._section.setVisible(not self._pro)
        lay = self.layout()
        if lay is not None:
            lay.setContentsMargins(12, 10, 12, 10)
            lay.setSpacing(6 if self._pro else 8)
        # Always kill drop-shadow — it paints into the cart/summary splitter
        # handle on Classic/Explorer and makes the yellow grip look dead.
        try:
            self.setGraphicsEffect(None)
        except Exception:
            pass
        self.refresh_theme()

    def set_review_compact(self, enabled: bool = True):
        """Review Cart: tighter margins so Order Summary stays a strip under rows."""
        self._review_compact = bool(enabled)
        self._apply_density()
        try:
            self.setGraphicsEffect(None)
        except Exception:
            pass
        self.updateGeometry()

    def set_pinned_strip(self, enabled: bool = True):
        """Always-visible cashier strip (foot): Subtotal / Discount / Tax / Total due."""
        self._pinned_strip = bool(enabled)
        if hasattr(self, '_section') and self._section is not None:
            # Foot already sits under Amount Paid — skip duplicate "Order Summary" chrome.
            self._section.setVisible(not self._pinned_strip)
        if self._pinned_strip:
            try:
                self._total_hdr.setText('Total due')
            except Exception:
                pass
        elif getattr(self, '_total_hdr', None) is not None:
            try:
                self._total_hdr.setText('Grand Total')
            except Exception:
                pass
        self._apply_density()
        try:
            self.setGraphicsEffect(None)
        except Exception:
            pass
        self.updateGeometry()

    def _apply_density(self):
        lay = self.layout()
        if lay is None:
            return
        compact = bool(getattr(self, '_review_compact', False) or getattr(self, '_pinned_strip', False))
        if compact:
            lay.setContentsMargins(10, 6, 10, 8)
            lay.setSpacing(4)
        elif getattr(self, '_pro', False):
            lay.setContentsMargins(12, 10, 12, 10)
            lay.setSpacing(6)
        else:
            lay.setContentsMargins(16, 14, 16, 14)
            lay.setSpacing(8)

    def _row(self, label: str) -> QLabel:
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        l = QLabel(label)
        l.setObjectName('posTotMute')
        v = QLabel('KES 0.00')
        v.setObjectName('posTotVal')
        row.addWidget(l)
        row.addStretch()
        row.addWidget(v)
        v._row_w = w
        self._body.addWidget(w)
        return v

    def set_amounts(self, currency, sub, tax, total, discount=0.0):
        cur = currency or 'KES'
        self._sub_lbl.setText(f'{cur} {sub:,.2f}')
        self._tax_lbl.setText(f'{cur} {tax:,.2f}')
        tax_row = getattr(self, '_tax_row_w', None) or getattr(self._tax_lbl, '_row_w', None)
        if tax_row is not None:
            try:
                tax_row.setVisible(abs(float(tax or 0)) > 0.009)
            except Exception:
                tax_row.setVisible(True)
        text = f'{cur} {total:,.2f}'
        self._tot_lbl.setText(text)
        try:
            sav = float(discount or 0)
        except (TypeError, ValueError):
            sav = 0.0
        # Same savings disclosure across Pro / Explorer / Classic
        if sav > 0.009:
            self._savings_lbl.setText(f'− {cur} {sav:,.2f}')
            self._savings_row_w.show()
        else:
            self._savings_row_w.hide()
        if text != self._last_total_text:
            self._last_total_text = text
            self._pulse_total()

    def _pulse_total(self):
        """Brief gold highlight when Grand Total changes — no heavy deps."""
        try:
            gold = C['gold']
            compact = bool(getattr(self, '_review_compact', False) or getattr(self, '_pinned_strip', False))
            px = 22 if compact else 30
            flash_px = 24 if compact else 32
            base = (
                f"color:{gold};font-size:{px}px;font-weight:900;background:transparent;")
            flash = (
                f"color:{C.get('gold_lt', gold)};font-size:{flash_px}px;font-weight:900;"
                f"background:transparent;")
            self._tot_lbl.setStyleSheet(flash)
            QTimer.singleShot(160, lambda: self._tot_lbl.setStyleSheet(base))
        except Exception:
            pass

    def refresh_theme(self):
        compact = bool(getattr(self, '_review_compact', False) or getattr(self, '_pinned_strip', False))
        tot_px = 22 if compact else 30
        hdr_px = 13 if compact else 15
        mute_px = 13 if compact else 14
        self.setStyleSheet(
            f"QFrame#posTotFrame{{background:{C['panel']};border:1px solid {C['border']};"
            f"border-radius:{RADIUS['lg']}px;}}")
        self._sep.setStyleSheet(f"background:{C['border']};border:none;")
        self._section.setStyleSheet(
            f"color:{C['muted']};font-size:11px;font-weight:800;letter-spacing:0.8px;"
            f"text-transform:uppercase;background:transparent;")
        self._total_hdr.setStyleSheet(
            f"color:{C['text']};font-size:{hdr_px}px;font-weight:800;background:transparent;")
        self._tot_lbl.setStyleSheet(
            f"color:{C['gold']};font-size:{tot_px}px;font-weight:900;background:transparent;")
        for w in self.findChildren(QLabel):
            if w.objectName() == 'posTotMute':
                w.setStyleSheet(
                    f"color:{C['text2']};font-size:{mute_px}px;font-weight:600;background:transparent;")
            elif w.objectName() == 'posTotVal':
                w.setStyleSheet(
                    f"color:{C['text']};font-size:{mute_px}px;font-weight:700;background:transparent;")
            elif w.objectName() == 'posTotSave':
                w.setStyleSheet(
                    f"color:{C['ok']};font-size:{mute_px}px;font-weight:700;background:transparent;")
        self.disc_label.setStyleSheet(
            f"color:{C['text2']};font-size:{mute_px}px;font-weight:600;background:transparent;")


# ── CustomerCard ──────────────────────────────────────────────────────────────

class CustomerCard(QFrame):
    """
    Compact customer chip for Current Sale — saves cart vertical space.
    Click opens picker: Walk-in | saved customers | Add new.
    Keeps an embedded CustomerSelector for sales_tab API compatibility.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('posCustomerCard')
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._api = None
        self._customers_cache = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Hidden selector — sales_tab talks to this (load/select/walk-in/signals)
        self.selector = CustomerSelector()
        self.selector.hide()
        self.selector.currentIndexChanged.connect(self._sync_chip_from_selector)

        self._btn = QPushButton('Walk-in Customer')
        self._btn.setObjectName('posCustChip')
        self._btn.setCursor(Qt.PointingHandCursor)
        self._btn.setMinimumHeight(TOUCH_MIN)
        self._btn.setToolTip('Tap to choose a saved customer or add a new one')
        self._btn.clicked.connect(self._open_picker)
        lay.addWidget(self._btn)

        self._pro_row = None
        self._new_btn_slot = None
        self.refresh_theme()

    def set_pro_row(self, enabled: bool = True, new_btn=None):
        """Checkout Pro: Walk-in chip + New Customer on one compact row."""
        lay = self.layout()
        if lay is None:
            return
        if enabled:
            if self._pro_row is None:
                row = QWidget()
                row.setObjectName('posCustProRow')
                rl = QHBoxLayout(row)
                rl.setContentsMargins(0, 0, 0, 0)
                rl.setSpacing(8)
                # Move chip into row
                lay.removeWidget(self._btn)
                rl.addWidget(self._btn, 1)
                if new_btn is not None:
                    rl.addWidget(new_btn, 0)
                    new_btn.show()
                    self._new_btn_slot = new_btn
                lay.addWidget(row)
                self._pro_row = row
            else:
                self._pro_row.show()
                if new_btn is not None:
                    if new_btn.parent() is not self._pro_row:
                        self._pro_row.layout().addWidget(new_btn)
                    new_btn.show()
                    self._new_btn_slot = new_btn
            self._btn.setMinimumHeight(36)
        else:
            if self._pro_row is not None:
                rl = self._pro_row.layout()
                if rl is not None:
                    rl.removeWidget(self._btn)
                lay.removeWidget(self._pro_row)
                self._pro_row.hide()
                lay.addWidget(self._btn)
            if self._new_btn_slot is not None:
                self._new_btn_slot.hide()
            self._btn.setMinimumHeight(TOUCH_MIN)
        self.refresh_theme()

    def set_api(self, api):
        """Optional — enables Add Customer from the chip picker."""
        self._api = api

    def set_customers_cache(self, customers: list):
        self._customers_cache = list(customers or [])

    def set_customer(self, customer: dict = None, *, walk_in=False):
        """Update chip label from a customer dict (or walk-in)."""
        if walk_in or not customer:
            self._btn.setText('Walk-in Customer')
            self._btn.setToolTip('Tap to choose a saved customer or add a new one')
            self.refresh_theme()
            return
        name = (customer.get('name') or 'Customer').strip()
        phone = (customer.get('phone') or '').strip()
        label = f'{name}  ·  {phone}' if phone else name
        wallet = float(customer.get('wallet_balance') or 0)
        owing = float(customer.get('total_outstanding') or 0)
        limit = float(customer.get('credit_limit') or 0)
        if owing > 0.009:
            label = f'{label}  ·  Debt {owing:,.0f}'
        elif wallet > 0.009:
            label = f'{label}  ·  Credit {wallet:,.0f}'
        tip_bits = [name]
        if phone:
            tip_bits.append(phone)
        if owing > 0.009:
            tip_bits.append(f'Outstanding debt: {owing:,.2f}')
        if limit > 0.009:
            tip_bits.append(f'Credit limit: {limit:,.2f}')
        if wallet > 0.009:
            tip_bits.append(f'Store credit: {wallet:,.2f}')
        self._btn.setText(label)
        self._btn.setToolTip(' · '.join(tip_bits))
        self.refresh_theme()

    def _sync_chip_from_selector(self, *_args):
        cid = self.selector.selected_id()
        if not cid:
            self.set_customer(None, walk_in=True)
            return
        cust = None
        for c in self._customers_cache:
            if c.get('id') == cid:
                cust = c
                break
        if cust:
            self.set_customer(cust, walk_in=False)
        else:
            # Fallback to combo display text
            text = (self.selector.currentText() or 'Customer').split('  ·  ')[0].strip()
            if 'walk-in' in text.lower():
                self.set_customer(None, walk_in=True)
            else:
                self._btn.setText(text or 'Customer')
                self.refresh_theme()

    def _open_picker(self):
        from desktop.dialogs.credit_customer_dialogs import (
            CustomerPickerDialog, QuickCustomerDialog,
        )
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel

        dlg = QDialog(self.window())
        dlg.setWindowTitle('Customer')
        dlg.setMinimumWidth(420)
        from desktop.utils.theme import apply_themed_dialog
        apply_themed_dialog(dlg)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.setSpacing(12)
        tip = QLabel('Choose who this sale is for. Cart stays intact.')
        tip.setWordWrap(True)
        tip.setStyleSheet(
            f"color:{C['text2']};font-size:12px;background:transparent;")
        lay.addWidget(tip)

        walk = PrimaryBtn('Walk-in Customer', 48)
        walk.clicked.connect(lambda: self._pick_walk_in(dlg))
        lay.addWidget(walk)

        existing = PrimaryBtn('Select Saved Customer', 48)
        existing.setStyleSheet(
            f"QPushButton{{background:{C['card2']};color:{C['gold']};"
            f"border:2px solid {C['gold']};border-radius:10px;"
            f"font-size:15px;font-weight:800;}}"
            f"QPushButton:hover{{background:{qss_alpha(C['gold'], 0.12)};}}")
        existing.clicked.connect(lambda: self._pick_existing(dlg))
        lay.addWidget(existing)

        create = SecondaryBtn('+  Add New Customer', 44)
        create.clicked.connect(lambda: self._pick_create(dlg))
        lay.addWidget(create)

        cancel = SecondaryBtn('Cancel', 40)
        cancel.clicked.connect(dlg.reject)
        lay.addWidget(cancel)

        from desktop.utils.state_reset import StateResetManager
        StateResetManager.clear_modal_on_close(dlg)
        dlg.exec_()

    def _pick_walk_in(self, dlg):
        self.selector.select_walk_in()
        self.set_customer(None, walk_in=True)
        dlg.accept()

    def _pick_existing(self, parent_dlg):
        from desktop.dialogs.credit_customer_dialogs import CustomerPickerDialog
        api = self._api
        if api is None:
            # Try parent SalesTab
            w = self.window()
            api = getattr(w, 'api', None) or getattr(self.parent(), 'api', None)
        if api is None:
            from desktop.utils.quiet_ui import soft_warn
            soft_warn(self, 'Customer list is not available yet.')
            return
        picker = CustomerPickerDialog(self.window(), api)
        if picker.exec_() != picker.Accepted:
            return
        cid = picker.selected_id
        if cid is None:
            return
        # Refresh selector list if needed, then select
        try:
            customers = api.get_customers() or []
            self.set_customers_cache(customers)
            self.selector.load_customers(customers)
        except Exception:
            pass
        applied = False
        if hasattr(self.selector, 'select_customer'):
            applied = bool(self.selector.select_customer(cid))
        if not applied:
            idx = self.selector.findData(cid)
            if idx < 0:
                idx = self.selector.findData(int(cid))
            if idx >= 0:
                self.selector.blockSignals(True)
                self.selector.setCurrentIndex(0 if idx != 0 else min(1, self.selector.count() - 1))
                self.selector.blockSignals(False)
                self.selector.setCurrentIndex(idx)
                applied = True
        cust = next(
            (c for c in self._customers_cache
             if c.get('id') == cid or c.get('id') == int(cid)),
            None,
        )
        self.set_customer(cust, walk_in=False)
        # Ensure SalesTab handlers run even if combo index was unchanged
        try:
            self.selector.currentIndexChanged.emit(self.selector.currentIndex())
        except Exception:
            pass
        parent_dlg.accept()

    def _pick_create(self, parent_dlg):
        from desktop.dialogs.credit_customer_dialogs import QuickCustomerDialog
        api = self._api
        if api is None:
            w = self.window()
            api = getattr(w, 'api', None) or getattr(self.parent(), 'api', None)
        if api is None:
            from desktop.utils.quiet_ui import soft_warn
            soft_warn(self, 'Cannot add customer — API unavailable.')
            return
        create = QuickCustomerDialog(self.window(), api)
        if create.exec_() != create.Accepted:
            return
        cid = create.customer_id
        if not cid:
            return
        try:
            customers = api.get_customers() or []
            self.set_customers_cache(customers)
            self.selector.load_customers(customers)
            self.selector.select_customer(cid)
            cust = next(
                (c for c in customers
                 if c.get('id') == cid or c.get('id') == int(cid)),
                None,
            )
            self.set_customer(cust, walk_in=False)
            try:
                self.selector.currentIndexChanged.emit(self.selector.currentIndex())
            except Exception:
                pass
        except Exception:
            pass
        if parent_dlg is not None and hasattr(parent_dlg, 'accept'):
            parent_dlg.accept()

    def refresh_theme(self):
        walk_in = 'walk-in' in (self._btn.text() or '').lower()
        border = C['gold'] if not walk_in else C['border']
        bg = qss_alpha(C['gold'], 0.12) if not walk_in else C['card2']
        self.setStyleSheet(
            f"QFrame#posCustomerCard{{background:transparent;border:none;}}"
            f"QPushButton#posCustChip{{background:{bg};color:{C['text']};"
            f"border:1.5px solid {border};border-radius:{RADIUS['md']}px;"
            f"font-size:13px;font-weight:800;text-align:left;padding:0 14px;"
            f"min-height:{TOUCH_MIN}px;}}"
            f"QPushButton#posCustChip:hover{{border-color:{C['gold']};"
            f"background:{qss_alpha(C['gold'], 0.14)};}}"
            f"QPushButton#posCustChip:pressed{{background:{qss_alpha(C['gold'], 0.20)};}}"
        )
        if hasattr(self.selector, 'refresh_theme'):
            self.selector.refresh_theme()


# ── CustomerSelector ──────────────────────────────────────────────────────────

class CustomerSelector(QComboBox):
    """Walk-in + named customers. Searchable with clear dropdown affordance."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('posCustomer')
        self.setMinimumHeight(TOUCH_MIN - 2)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(18)
        self._all = []  # (label, id)
        self.addItem('Walk-in Customer', None)
        le = self.lineEdit()
        if le:
            le.setPlaceholderText('Search customer…')
            le.textEdited.connect(self._filter)
            # Leading search + trailing chevron (QSS often hides native arrow)
            self._search_act = QAction('>', self)
            self._search_act.setToolTip('Type to search customers')
            le.addAction(self._search_act, QLineEdit.LeadingPosition)
            self._drop_act = QAction('v', self)
            self._drop_act.setToolTip('Browse customers')
            self._drop_act.triggered.connect(self.showPopup)
            le.addAction(self._drop_act, QLineEdit.TrailingPosition)
        self.refresh_theme()

    def load_customers(self, customers: list):
        cur = self.currentData()
        self._all = [('Walk-in Customer', None)]
        for c in customers or []:
            name = (c.get('name') or 'Customer').strip()
            phone = (c.get('phone') or '').strip()
            wallet = float(c.get('wallet_balance') or 0)
            label = f'{name}  ·  {phone}' if phone else name
            if wallet > 0.009:
                label = f'{label}  ·  Credit {wallet:,.2f}'
            self._all.append((label, c.get('id')))
        self._rebuild(keep=cur)

    def _rebuild(self, keep=None, query=''):
        q = (query or '').strip().lower()
        self.blockSignals(True)
        self.clear()
        # Always keep Walk-in at top
        self.addItem('Walk-in Customer', None)
        matched = 1
        for label, cid in self._all:
            if cid is None:
                continue
            if not q or q in label.lower():
                self.addItem(label, cid)
                matched += 1
        if matched <= 1 and q:
            self.addItem('No matches', None)
        if keep is not None:
            idx = self.findData(keep)
            self.setCurrentIndex(idx if idx >= 0 else 0)
        elif not q:
            self.setCurrentIndex(0)
        self.blockSignals(False)
        # Only auto-open dropdown while the cashier is typing in this field
        le = self.lineEdit()
        if (q and matched > 1 and not self.view().isVisible()
                and self.isVisible() and le is not None and le.hasFocus()):
            self.showPopup()

    def _filter(self, text: str):
        keep = self.currentData()
        self._rebuild(keep=keep, query=text)

    def select_customer(self, customer_id):
        """
        Select by id after reload; rebuild full list first.
        Always emits currentIndexChanged so SalesTab applies debt/credit profile
        even when the combo was already on Walk-in or the same index.
        """
        if customer_id is None:
            self.select_walk_in()
            return False
        try:
            cid = int(customer_id)
        except (TypeError, ValueError):
            cid = customer_id
        self._rebuild(keep=None, query='')
        idx = self.findData(cid)
        if idx < 0:
            idx = self.findData(customer_id)
        if idx < 0:
            return False
        # Force a real index change so Qt emits currentIndexChanged
        other = 0 if idx != 0 else (1 if self.count() > 1 else -1)
        self.blockSignals(True)
        if other >= 0:
            self.setCurrentIndex(other)
        self.blockSignals(False)
        self.setCurrentIndex(idx)
        le = self.lineEdit()
        if le is not None:
            le.blockSignals(True)
            le.setText(self.itemText(idx) or '')
            le.blockSignals(False)
        return True

    def selected_id(self):
        return self.currentData()

    def select_walk_in(self):
        """Force Walk-in Customer — clears search filter. Used after sale reset."""
        self._rebuild(keep=None, query='')
        self.blockSignals(True)
        try:
            if self.count() == 0:
                self.addItem('Walk-in Customer', None)
            idx = self.findData(None)
            if idx < 0:
                for i in range(self.count()):
                    if 'walk-in' in (self.itemText(i) or '').lower():
                        idx = i
                        break
            self.setCurrentIndex(idx if idx >= 0 else 0)
            le = self.lineEdit()
            if le is not None:
                le.blockSignals(True)
                le.setText(self.currentText() or 'Walk-in Customer')
                le.blockSignals(False)
        finally:
            self.blockSignals(False)
        # Notify listeners (chip + SalesTab) that Walk-in is active
        try:
            self.currentIndexChanged.emit(self.currentIndex())
        except Exception:
            pass

    def mousePressEvent(self, event):
        # Clicking the field opens the list (picker affordance)
        if event.button() == Qt.LeftButton:
            le = self.lineEdit()
            # If clicking near the trailing chevron zone, always open
            if le is not None and event.pos().x() > self.width() - 36:
                self.showPopup()
                event.accept()
                return
        super().mousePressEvent(event)

    def showPopup(self):
        self.refresh_theme()
        super().showPopup()
        try:
            from desktop.utils.pos_light_theme import _fit_combo_popup
            from PyQt5.QtCore import QTimer
            bg, fg, bd = C['card'], C['text'], C['border']
            _fit_combo_popup(self, bg=bg, fg=fg, border=bd, max_items=12)
            QTimer.singleShot(
                0, lambda: _fit_combo_popup(
                    self, bg=C['card'], fg=C['text'], border=C['border'],
                    max_items=12))
        except Exception:
            pass

    def refresh_theme(self):
        bg = C['card']
        fg = C['text']
        muted = C['text2']
        sel = C.get('selected', C['hover'])
        bd = C['border2']
        gold = C['gold']
        r = RADIUS['md']
        self.setStyleSheet(
            f"QComboBox#posCustomer{{background:{C['input']};color:{fg};"
            f"border:1px solid {bd};border-radius:{r}px;"
            f"padding:6px 10px;padding-right:8px;font-size:13px;"
            f"min-height:{TOUCH_MIN - 4}px;}}"
            f"QComboBox#posCustomer:hover{{border-color:{gold};}}"
            f"QComboBox#posCustomer:focus{{border-color:{gold};}}"
            f"QComboBox#posCustomer::drop-down{{subcontrol-origin:padding;"
            f"subcontrol-position:center right;width:28px;border:none;"
            f"background:transparent;}}"
            f"QComboBox#posCustomer::down-arrow{{image:none;width:0;height:0;}}"
            f"QComboBox#posCustomer QAbstractItemView{{background:{bg};"
            f"color:{fg};border:1px solid {C['border']};outline:0;"
            f"selection-background-color:{sel};selection-color:{fg};}}"
            f"QComboBox#posCustomer QAbstractItemView::item{{"
            f"color:{fg};background:{bg};min-height:32px;padding:6px 12px;}}"
            f"QComboBox#posCustomer QAbstractItemView::item:selected{{"
            f"background:{sel};color:{fg};}}"
            f"QComboBox#posCustomer QAbstractItemView::item:hover{{"
            f"background:{C['hover']};color:{fg};}}"
        )
        view = self.view()
        if view is not None:
            view.setAttribute(Qt.WA_StyledBackground, True)
            view.setAutoFillBackground(True)
            from PyQt5.QtGui import QColor, QPalette
            pal = view.palette()
            pal.setColor(QPalette.Base, QColor(bg))
            pal.setColor(QPalette.Text, QColor(fg))
            pal.setColor(QPalette.Window, QColor(bg))
            pal.setColor(QPalette.WindowText, QColor(fg))
            pal.setColor(QPalette.Highlight, QColor(sel))
            pal.setColor(QPalette.HighlightedText, QColor(fg))
            view.setPalette(pal)
            view.setStyleSheet(
                f"QAbstractItemView{{background:{bg};color:{fg};outline:0;}}"
                f"QAbstractItemView::item{{color:{fg};background:{bg};"
                f"min-height:32px;padding:6px 12px;}}")
        le = self.lineEdit()
        if le is not None:
            le.setStyleSheet(
                f"QLineEdit{{background:transparent;color:{fg};"
                f"border:none;padding:0;font-size:13px;}}"
                f"QLineEdit::placeholder{{color:{muted};}}")
            # Keep action icons readable
            for act in le.actions():
                act.setVisible(True)


# ── PosSearchBar ──────────────────────────────────────────────────────────────

class PosSearchBar(QLineEdit):
    """Search / barcode field — Enter submits scan. Optional Pro leading/trailing icons."""
    submitted = pyqtSignal(str)

    def __init__(self, placeholder='Search or scan barcode...', parent=None):
        super().__init__(parent)
        self.setObjectName('mbtSearchBar')
        self.setPlaceholderText(placeholder)
        self.setMinimumHeight(max(TOUCH_MIN + 4, 48))
        self.setClearButtonEnabled(True)
        self._pro_icons = False
        self._lead_act = None
        self._scan_act = None
        self.refresh_theme()

    def set_pro_icons(self, enabled: bool = True):
        self._pro_icons = bool(enabled)
        # Clear prior actions (except clear button managed by Qt)
        if self._lead_act is not None:
            self.removeAction(self._lead_act)
            self._lead_act = None
        if self._scan_act is not None:
            self.removeAction(self._scan_act)
            self._scan_act = None
        if self._pro_icons:
            # Painted house icons — the Qt stock icons here were a document page
            # and a desktop monitor, which read as placeholder art.
            try:
                from desktop.utils.nav_icons import icon_barcode, icon_search
                self._lead_act = self.addAction(
                    icon_search(16), QLineEdit.LeadingPosition)
                self._scan_act = self.addAction(
                    icon_barcode(16), QLineEdit.TrailingPosition)
                if self._scan_act is not None:
                    self._scan_act.setToolTip('Scan a barcode into this field')
            except Exception:
                self._lead_act = None
                self._scan_act = None
        self.refresh_theme()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.submitted.emit(self.text().strip())
            event.accept()
            return
        super().keyPressEvent(event)

    def refresh_theme(self):
        r = RADIUS['md']
        pad_l = 14
        self.setStyleSheet(
            f"QLineEdit#mbtSearchBar{{background:{C['input']};color:{C['text']};"
            f"border:1px solid {C['border']};border-radius:{r}px;"
            f"padding:0 12px 0 {pad_l}px;font-size:14px;min-height:{TOUCH_MIN - 4}px;}}"
            f"QLineEdit#mbtSearchBar:focus{{border-color:{C['gold']};}}"
        )


# ── ProductGrid ───────────────────────────────────────────────────────────────

class ProductGrid(QWidget):
    """Responsive product card grid (capped for cashier speed)."""
    productClicked = pyqtSignal(dict)
    MAX_VISIBLE = 48  # search/filter to find more — never paint 600+ tiles

    def __init__(self, parent=None):
        super().__init__(parent)
        self._products = []
        self._currency = 'KES'
        self._is_light = False
        self._pro_density = False
        self._total_count = 0
        self._categories_by_name = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)
        self._hint = QLabel('')
        self._hint.setStyleSheet('background:transparent;')
        self._hint.hide()
        self._host = QWidget()
        self._grid = QGridLayout(self._host)
        self._grid.setSpacing(GAP)
        # Symmetric side pad so right-column cards never clip against the rail
        self._grid.setContentsMargins(PADDING - 2, PADDING - 4, PADDING - 2, PADDING - 4)
        self._grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        # Hint above grid by default; Checkout Pro moves it below via set_pro_density
        outer.addWidget(self._hint)
        outer.addWidget(self._host, 1)
        self._outer = outer
        self.setStyleSheet('background:transparent;')

    def set_currency(self, cur: str):
        self._currency = cur or 'KES'

    def set_light(self, is_light: bool):
        self._is_light = bool(is_light)

    def set_pro_density(self, enabled: bool = True):
        """Checkout Pro: compact cards, tighter gaps, pagination hint under grid."""
        self._pro_density = bool(enabled)
        gap = 14 if self._pro_density else max(GAP, 12)
        pad = 10 if self._pro_density else max(PADDING - 4, 10)
        self._grid.setSpacing(gap)
        self._grid.setContentsMargins(pad, pad, pad, pad)
        # AlignLeft pins the grid to its sizeHint, so Pro's Expanding cards could
        # never take the width they were unlocked for. Let the grid fill instead.
        try:
            self._grid.setAlignment(
                Qt.AlignTop if self._pro_density else (Qt.AlignTop | Qt.AlignLeft))
        except Exception:
            pass
        # Prevent rows from stealing vertical space from each other
        try:
            self._grid.setRowStretch(99, 1)
        except Exception:
            pass
        # Move hint under product grid for Pro footer-style "Showing X - Y of Z"
        try:
            self._outer.removeWidget(self._hint)
            if self._pro_density:
                self._outer.addWidget(self._hint)
            else:
                self._outer.insertWidget(0, self._hint)
        except Exception:
            pass

    def set_categories_map(self, mapping: dict):
        self._categories_by_name = mapping or {}

    def clear(self):
        # Cancel in-flight chunked populate
        self._populate_token = int(getattr(self, '_populate_token', 0) or 0) + 1
        self._pending_products = None
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w:
                try:
                    from desktop.utils.quiet_ui import safe_detach
                    safe_detach(w)
                except Exception:
                    try:
                        w.hide()
                        w.setParent(None)
                    except Exception:
                        pass
                try:
                    from PyQt5 import sip
                    if not sip.isdeleted(w):
                        sip.delete(w)
                except Exception:
                    try:
                        w.deleteLater()
                    except Exception:
                        pass
        self._products = []
        self._hint.hide()

    def columns_for_width(self, available: int) -> int:
        """Columns that genuinely fit ``available`` px.

        This used to floor the width at 640px and the column count at 2, so a
        ~410px Checkout Pro column still laid out two 260px cards and clipped
        the right-hand one against the cart panel. Narrow rails now drop to a
        single full-width card instead.
        """
        card_w = 248 if self._pro_density else (248 if self._is_light else 240)
        gap = self._grid.horizontalSpacing() or GAP
        avail = max(120, int(available))
        cols = max(1, int((avail + gap) // (card_w + gap)))
        # Pro cards shrink via unlock_width (~85% tile) — two fit above ~470px rail.
        if self._pro_density and cols == 1 and avail >= 470:
            cols = 2
        # Prefer readable cards over cramming 4–5 skinny tiles
        return min(2 if self._pro_density else 3, cols)

    def populate(self, products: list, columns: int = 3, *, chunked: bool = False):
        all_prods = list(products or [])
        self._total_count = len(all_prods)
        visible = all_prods[: self.MAX_VISIBLE]
        cols = max(1, int(columns))
        new_ids = [p.get('id') for p in visible]
        old_ids = [p.get('id') for p in (self._products or [])]
        if (
            new_ids
            and new_ids == old_ids
            and cols == int(getattr(self, '_last_populate_cols', -1) or -1)
            and not chunked
            and self._grid.count() > 0
        ):
            self._products = visible
            return
        self.clear()
        self._last_populate_cols = cols
        self._products = visible
        if self._total_count > 0:
            lo, hi = 1, len(visible)
            if self._pro_density:
                self._hint.setText(
                    f'Showing {lo} - {hi} of {self._total_count} products')
            elif self._total_count > self.MAX_VISIBLE:
                self._hint.setText(
                    f'Showing {len(visible)} of {self._total_count} — type to search / filter category')
            else:
                self._hint.setText('')
            if self._hint.text():
                self._hint.setStyleSheet(
                    f"color:{C['muted']}; font-size:11px; font-weight:600; "
                    f"background:transparent; padding:2px 8px;")
                self._hint.show()
        # Pro: room for icon + 2–3 line name + SKU + price + stock badge
        if self._pro_density:
            card_size = (268, 152) if self._is_light else (260, 148)
        else:
            # Taller cards so names wrap instead of "DAP Fertili…"
            card_size = (248, 178) if self._is_light else (240, 174)
        cols = max(1, int(columns))
        if self._pro_density and cols == 1:
            # One full-width card per row reads as a product list row; keeping
            # the tile height would leave a wide band of empty card.
            card_size = (card_size[0], 104)
        cmap = self._categories_by_name or {}
        # Clear stretch left by a wider column count, or a single column would
        # still be laid out inside its old half/third of the row.
        for c in range(8):
            try:
                self._grid.setColumnStretch(c, 1 if c < cols else 0)
            except Exception:
                pass
        if not visible:
            return
        if not chunked or len(visible) <= 12:
            self._add_product_cards(visible, cols, card_size, cmap, start=0)
            return
        # Chunked: first batch now, rest on subsequent event-loop ticks
        token = int(getattr(self, '_populate_token', 0) or 0)
        self._pending_products = visible
        self._pending_cols = cols
        self._pending_card_size = card_size
        self._pending_cmap = cmap
        self._pending_idx = 0
        first = 12
        self._add_product_cards(visible[:first], cols, card_size, cmap, start=0)
        self._pending_idx = first
        QTimer.singleShot(0, lambda t=token: self._populate_next_chunk(t))

    def _add_product_cards(self, batch, cols, card_size, cmap, start: int = 0):
        for i, p in enumerate(batch):
            idx = start + i
            cat = p.get('category') or 'General'
            meta = cmap.get(cat) or cmap.get(str(cat).lower()) or {}
            card = ProductCard(
                p, currency=self._currency, card_size=card_size,
                category_meta=meta, compact=self._pro_density)
            card.clicked.connect(self.productClicked.emit)
            self._grid.addWidget(card, idx // cols, idx % cols)
            if self._pro_density:
                try:
                    card.unlock_width(int(card_size[0] * 0.85))
                except Exception:
                    pass
                try:
                    self._grid.setRowMinimumHeight(idx // cols, int(card_size[1]) + 4)
                except Exception:
                    pass

    def _populate_next_chunk(self, token: int):
        if token != int(getattr(self, '_populate_token', 0) or 0):
            return
        pending = getattr(self, '_pending_products', None)
        if not pending:
            return
        idx = int(getattr(self, '_pending_idx', 0) or 0)
        if idx >= len(pending):
            self._pending_products = None
            return
        cols = int(getattr(self, '_pending_cols', 3) or 3)
        card_size = getattr(self, '_pending_card_size', (236, 164))
        cmap = getattr(self, '_pending_cmap', {}) or {}
        end = min(len(pending), idx + 12)
        self._add_product_cards(pending[idx:end], cols, card_size, cmap, start=idx)
        self._pending_idx = end
        if end < len(pending):
            QTimer.singleShot(0, lambda t=token: self._populate_next_chunk(t))
        else:
            self._pending_products = None

    def retint(self):
        for card in self.findChildren(ProductCard):
            try:
                card.refresh_theme()
            except Exception:
                pass
        if self._hint.isVisible():
            self._hint.setStyleSheet(
                f"color:{C['muted']}; font-size:12px; font-weight:600; "
                f"background:transparent; padding:4px 12px;")


# ── Theme refresh helper ──────────────────────────────────────────────────────

def refresh_pos_components(root):
    """Re-apply theme on modular POS widgets under root."""
    if root is None or not hasattr(root, 'findChildren'):
        return
    for cls in (ProductCard, CategoryIcon, StockBadge, QuantityControl,
                PaymentButton, PaymentSegment, SummaryCard, CustomerCard,
                CustomerSelector, CartLineRow, CartList, PosSearchBar):
        for w in root.findChildren(cls):
            try:
                if hasattr(w, 'refresh_theme'):
                    w.refresh_theme()
            except Exception:
                pass
    for g in root.findChildren(ProductGrid):
        try:
            g.retint()
        except Exception:
            pass
