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
    try:
        return f'{float(v):,.2f}'
    except (TypeError, ValueError):
        return '0.00'


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
        super().__init__(parent)
        self._stock = stock
        self._unit = unit or 'pcs'
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(22)
        self.refresh_from(stock, unit)

    def refresh_from(self, stock, unit='pcs'):
        self._stock = stock
        self._unit = unit or 'pcs'
        try:
            n = float(stock)
        except (TypeError, ValueError):
            n = 0.0
        if n <= 0:
            tone, text = 'err', 'Out'
        elif n < 10:
            tone, text = 'warn', f'Low {fmt_stock_short(n)}'
        else:
            tone, text = 'ok', f'{fmt_stock_short(n)} {self._unit}'[:14]
        color = C.get(tone, C['text2']) if tone != 'ok' else C['text2']
        if tone == 'ok':
            color = C['text2']
        elif tone == 'warn':
            color = C['warn']
        else:
            color = C['err']
        self.setText(text)
        self.setProperty('mbtBadgeTone', 'err' if n <= 0 else ('warn' if n < 10 else 'muted'))
        self.setToolTip(
            'Out of stock' if n <= 0 else (
                f'Low stock: {n:g} {self._unit}' if n < 10 else f'{n:g} {self._unit}'))
        self.setStyleSheet(
            f"QLabel {{ color:{color}; font-size:11px; font-weight:700; "
            f"background:{qss_alpha(color, 0.12)}; border:1px solid {qss_alpha(color, 0.28)}; "
            f"border-radius:{RADIUS['md']}px; padding:2px 8px; }}")


# ── ProductCard ───────────────────────────────────────────────────────────────

class ProductCard(QFrame):
    """
    Clickable product tile. Category emoji in colored circle when no image.
    Never shows broken/empty image placeholders.
    """
    clicked = pyqtSignal(dict)

    def __init__(self, product: dict, currency='KES', card_size=(214, 148),
                 parent=None, category_meta=None):
        super().__init__(parent)
        self._product = product or {}
        self._currency = currency
        self._active = True
        self._category_meta = category_meta or {}
        self.setObjectName('posProdCard')
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        w, h = card_size
        self.setFixedSize(int(w), int(h))
        self.setMinimumHeight(TOUCH_MIN * 2)

        name = (self._product.get('name') or '').strip()
        sku = (self._product.get('sku') or '').strip()
        cat = self._product.get('category') or 'General'
        price = self._product.get('price', 0)
        stock = self._product.get('stock', 0) or 0
        unit = self._product.get('unit', 'pcs') or 'pcs'
        try:
            stock_n = float(stock)
        except (TypeError, ValueError):
            stock_n = 0.0
        self._oos = stock_n <= 0

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(10)
        self._icon = CategoryIcon(cat, size=44, category_meta=self._category_meta)
        top.addWidget(self._icon)

        tcol = QVBoxLayout()
        tcol.setSpacing(2)
        tcol.setContentsMargins(0, 0, 0, 0)
        self._name = QLabel()
        self._name.setObjectName('posProdName')
        self._name.setWordWrap(True)
        self._name.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._set_elided(self._name, name, w - 80, 2)
        tcol.addWidget(self._name)
        if sku:
            self._sku = QLabel(sku)
            self._sku.setObjectName('posProdSku')
            self._set_elided(self._sku, sku, w - 80, 1)
            tcol.addWidget(self._sku)
        else:
            self._sku = None
        top.addLayout(tcol, 1)
        lay.addLayout(top)

        lay.addStretch(1)

        bot = QHBoxLayout()
        bot.setSpacing(8)
        self._price = QLabel(f'{self._currency} {safe_price(price)}')
        self._price.setObjectName('posProdPrice')
        self._price.setToolTip(self._price.text())
        bot.addWidget(self._price, 1)
        self._badge = StockBadge(stock_n, unit)
        bot.addWidget(self._badge, 0, Qt.AlignRight | Qt.AlignVCenter)
        lay.addLayout(bot)

        self.set_card_active(not self._oos)
        self.setToolTip(
            'Out of stock' if self._oos else f"{name}\nStock: {stock} {unit}")
        self.refresh_theme()

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
        r = RADIUS['xl']
        if self._oos:
            self.setStyleSheet(
                f"QFrame#posProdCard{{background:{C['panel']};border:1px solid {C['border']};"
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
        self._name.setStyleSheet(
            f"QLabel#posProdName{{color:{C['text']}; font-size:14px; font-weight:700; "
            f"line-height:1.25; background:transparent; border:none;}}")
        if self._sku is not None:
            self._sku.setStyleSheet(
                f"QLabel#posProdSku{{color:{C['muted']}; font-size:10px; font-weight:700; "
                f"letter-spacing:0.6px; background:transparent; border:none;}}")
        self._price.setStyleSheet(
            f"QLabel#posProdPrice{{color:{C['gold']}; font-size:15px; font-weight:900; "
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
    ):
        super().__init__(parent)
        self._step = float(step) if step else 0.25
        self._snap = bool(snap)
        self._minimum = float(self._step if minimum is None else minimum)
        self._maximum = float(maximum)
        self._touch = bool(touch)
        shell_h = TOUCH_MIN if self._touch else 36
        btn_w = 40 if self._touch else 30
        btn_h = shell_h - 4
        spin_h = shell_h - 4
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
        btn_min = 38 if getattr(self, '_touch', False) else 30
        font_sz = 20 if getattr(self, '_touch', False) else 18
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


# ── Cart line (shopping-cart row — not spreadsheet) ───────────────────────────

class CartLineRow(QFrame):
    """Modern cart row: thumb, name/SKU, ± qty, discount, unit price, line total, remove."""
    qtyChanged = pyqtSignal(float)
    discChanged = pyqtSignal(float)
    removeClicked = pyqtSignal()

    def __init__(self, item: dict, currency='KES', parent=None):
        super().__init__(parent)
        self._item = item or {}
        self._currency = currency or 'KES'
        self.setObjectName('posCartLine')
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setMinimumHeight(118)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(12)

        cat = self._item.get('category') or 'General'
        self._thumb = CategoryIcon(cat, size=48)
        top.addWidget(self._thumb, 0, Qt.AlignTop)

        info = QVBoxLayout()
        info.setSpacing(2)
        info.setContentsMargins(0, 0, 0, 0)
        self._name = QLabel((self._item.get('product_name') or '').strip() or 'Item')
        self._name.setObjectName('posCartName')
        self._name.setWordWrap(True)
        info.addWidget(self._name)
        sku = (self._item.get('sku') or '').strip()
        self._sku = QLabel(sku if sku else f"#{self._item.get('product_id', '')}")
        self._sku.setObjectName('posCartSku')
        info.addWidget(self._sku)
        self._unit_lbl = QLabel()
        self._unit_lbl.setObjectName('posCartUnit')
        info.addWidget(self._unit_lbl)
        info.addStretch(1)
        top.addLayout(info, 1)

        totals = QVBoxLayout()
        totals.setSpacing(4)
        totals.setContentsMargins(0, 0, 0, 0)
        self._line_total = QLabel()
        self._line_total.setObjectName('posCartLineTot')
        self._line_total.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        totals.addWidget(self._line_total)
        self._save_lbl = QLabel('')
        self._save_lbl.setObjectName('posCartSave')
        self._save_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._save_lbl.hide()
        totals.addWidget(self._save_lbl)
        totals.addStretch(1)
        top.addLayout(totals)

        self._rm = QPushButton('Remove')
        self._rm.setObjectName('posCartRemove')
        self._rm.setMinimumHeight(TOUCH_MIN)
        self._rm.setMinimumWidth(84)
        self._rm.setCursor(Qt.PointingHandCursor)
        self._rm.setToolTip('Remove line')
        self._rm.clicked.connect(self.removeClicked.emit)
        top.addWidget(self._rm, 0, Qt.AlignTop)
        root.addLayout(top)

        # Qty + Discount on one clear action strip (touch-friendly, high contrast)
        actions = QHBoxLayout()
        actions.setSpacing(10)

        qty_box = QFrame()
        qty_box.setObjectName('posCartQtyBox')
        ql = QHBoxLayout(qty_box)
        ql.setContentsMargins(10, 8, 10, 8)
        ql.setSpacing(8)
        qty_cap = QLabel('Qty')
        qty_cap.setObjectName('posCartCap')
        self._qty = QuantityControl(
            value=float(self._item.get('quantity') or 1),
            step=0.25, minimum=0.25, width=148, touch=True)
        self._qty.valueChanged.connect(self.qtyChanged.emit)
        ql.addWidget(qty_cap)
        ql.addWidget(self._qty, 1)
        actions.addWidget(qty_box, 1)

        disc_box = QFrame()
        disc_box.setObjectName('posCartDiscBox')
        dl = QHBoxLayout(disc_box)
        dl.setContentsMargins(10, 8, 10, 8)
        dl.setSpacing(8)
        disc_cap = QLabel('Discount (KES)')
        disc_cap.setObjectName('posCartDiscCap')
        self._disc = QuantityControl(
            value=float(self._item.get('discount') or 0),
            step=10.0, minimum=0.0, maximum=999999.0,
            snap=False, width=148, touch=True)
        self._disc.valueChanged.connect(self.discChanged.emit)
        dl.addWidget(disc_cap)
        dl.addWidget(self._disc, 1)
        actions.addWidget(disc_box, 1)

        root.addLayout(actions)

        self._sync_labels()
        self.refresh_theme()

    def _sync_labels(self):
        cur = self._currency
        up = float(self._item.get('unit_price') or 0)
        tot = float(self._item.get('total') or 0)
        disc = float(self._item.get('discount') or 0)
        self._unit_lbl.setText(f'{cur} {up:,.2f} each')
        self._line_total.setText(f'{cur} {tot:,.2f}')
        if disc > 0.009:
            self._save_lbl.setText(f'Save {cur} {disc:,.2f}')
            self._save_lbl.show()
        else:
            self._save_lbl.hide()

    def update_item(self, item: dict):
        self._item = item or {}
        self._qty.blockSignals(True)
        self._disc.blockSignals(True)
        try:
            self._qty.setValue(float(self._item.get('quantity') or 1))
            self._disc.setValue(float(self._item.get('discount') or 0))
        finally:
            self._qty.blockSignals(False)
            self._disc.blockSignals(False)
        name = (self._item.get('product_name') or '').strip() or 'Item'
        self._name.setText(name)
        sku = (self._item.get('sku') or '').strip()
        self._sku.setText(sku if sku else f"#{self._item.get('product_id', '')}")
        self._sync_labels()

    def refresh_theme(self):
        self.setStyleSheet(
            f"QFrame#posCartLine{{background:{C['card2']};border:1px solid {C['border']};"
            f"border-radius:{RADIUS['lg']}px;}}"
            f"QFrame#posCartLine:hover{{border-color:{qss_alpha(C['gold'], 0.45)};"
            f"background:{C['hover']};}}"
            f"QFrame#posCartQtyBox{{background:{C['input']};border:1px solid {C['border']};"
            f"border-radius:10px;}}"
            f"QFrame#posCartDiscBox{{background:{qss_alpha(C['gold'], 0.10)};"
            f"border:1px solid {qss_alpha(C['gold'], 0.55)};border-radius:10px;}}"
            f"QLabel#posCartName{{color:{C['text']};font-size:14px;font-weight:700;"
            f"background:transparent;}}"
            f"QLabel#posCartSku{{color:{C['muted']};font-size:11px;font-weight:600;"
            f"background:transparent;}}"
            f"QLabel#posCartUnit{{color:{C['text2']};font-size:12px;font-weight:600;"
            f"background:transparent;}}"
            f"QLabel#posCartCap{{color:{C['muted']};font-size:11px;font-weight:800;"
            f"background:transparent;min-width:28px;}}"
            f"QLabel#posCartDiscCap{{color:{C['gold']};font-size:11px;font-weight:800;"
            f"background:transparent;}}"
            f"QLabel#posCartLineTot{{color:{C['text']};font-size:16px;font-weight:800;"
            f"background:transparent;min-width:96px;}}"
            f"QLabel#posCartSave{{color:{C['ok']};font-size:11px;font-weight:800;"
            f"background:transparent;}}"
            f"QPushButton#posCartRemove{{background:{C['err_dim']};color:{C['err']};"
            f"border:1px solid {qss_alpha(C['err'], 0.45)};border-radius:10px;"
            f"font-weight:800;font-size:12px;padding:0 10px;}}"
            f"QPushButton#posCartRemove:hover{{background:{C['err']};color:#FFFFFF;}}"
        )
        for qc in (self._qty, self._disc):
            qc.refresh_theme()
        self._thumb.refresh_theme()


class CartList(QWidget):
    """Scrollable stack of CartLineRow — replaces spreadsheet cart table."""
    qtyChanged = pyqtSignal(int, float)
    discChanged = pyqtSignal(int, float)
    removeClicked = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('posCartList')
        self._rows = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setMinimumHeight(280)
        self._scroll.setMaximumHeight(520)
        self._scroll.setStyleSheet('QScrollArea{border:none;background:transparent;}')

        self._body = QWidget()
        self._body.setObjectName('posCartListBody')
        self._lay = QVBoxLayout(self._body)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(8)
        self._empty = QLabel('Cart is empty\nTap a product to add it.')
        self._empty.setAlignment(Qt.AlignCenter)
        self._empty.setObjectName('posCartEmpty')
        self._lay.addWidget(self._empty)
        self._lay.addStretch(1)
        self._scroll.setWidget(self._body)
        outer.addWidget(self._scroll)
        self.refresh_theme()

    def clear_rows(self):
        while self._rows:
            w = self._rows.pop()
            self._lay.removeWidget(w)
            w.deleteLater()
        self._empty.show()

    def set_items(self, items: list, currency='KES'):
        self.clear_rows()
        items = items or []
        if not items:
            self._empty.show()
            return
        self._empty.hide()
        # Insert above stretch (last item)
        stretch_idx = self._lay.count() - 1
        for i, item in enumerate(items):
            row = CartLineRow(item, currency=currency)
            row.qtyChanged.connect(lambda v, idx=i: self.qtyChanged.emit(idx, v))
            row.discChanged.connect(lambda v, idx=i: self.discChanged.emit(idx, v))
            row.removeClicked.connect(lambda idx=i: self.removeClicked.emit(idx))
            self._lay.insertWidget(stretch_idx + i, row)
            self._rows.append(row)

    def update_row(self, idx: int, item: dict):
        if 0 <= idx < len(self._rows):
            self._rows[idx].update_item(item)

    def refresh_theme(self):
        self.setStyleSheet(
            f"QWidget#posCartList,QWidget#posCartListBody{{background:transparent;}}"
            f"QLabel#posCartEmpty{{color:{C['muted']};font-size:13px;font-weight:600;"
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
        self.setObjectName('posPayToggle')
        self.setCheckable(True)
        self.setEnabled(bool(enabled))
        self.setCursor(Qt.PointingHandCursor if enabled else Qt.ForbiddenCursor)
        self.setMinimumHeight(56)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        if not enabled:
            tip = 'Gift Card / Store Credit — coming soon'
            self.setToolTip(tip)
        self.refresh_theme()

    def refresh_theme(self):
        muted = C['muted']
        if not self.isEnabled() or self._secondary:
            self.setStyleSheet(
                f"QPushButton#posPayToggle{{background:{C['panel']};color:{muted};"
                f"border:1px dashed {C['border2']};border-radius:{RADIUS['md']}px;"
                f"font-size:11px;font-weight:700;min-height:56px;padding:8px 4px;}}"
                f"QPushButton#posPayToggle:disabled{{color:{muted};}}")
            return
        self.setStyleSheet(
            f"QPushButton#posPayToggle{{background:{C['card2']};color:{C['text2']};"
            f"border:1.5px solid {C['border']};border-radius:{RADIUS['md']}px;"
            f"font-size:12px;font-weight:700;min-height:56px;padding:8px 4px;}}"
            f"QPushButton#posPayToggle:checked{{background:{qss_alpha(C['gold'], 0.16)};"
            f"color:{C['gold']};border-color:{C['gold']};font-weight:800;}}"
            f"QPushButton#posPayToggle:hover:!checked{{background:{C['hover']};"
            f"color:{C['text']};border-color:{qss_alpha(C['gold'], 0.35)};}}"
            f"QPushButton#posPayToggle:pressed{{background:{qss_alpha(C['gold'], 0.10)};}}"
        )


class PaymentSegment(QWidget):
    """Cash | M-Pesa | Card | Bank | Split tiles + future-ready Gift Card stub."""
    methodChanged = pyqtSignal(str)

    # Display key → payment combo text (POS_PAYMENT_METHODS)
    TILES = (
        ('Cash', 'Cash\nCash', True),
        ('M-Pesa', 'M-Pesa\nTill', True),
        ('Card', 'Card\nCard', True),
        ('Bank Transfer', 'Bank\nTransfer', True),
        ('Mixed', 'Split\nPay', True),
        ('Gift Card', 'Gift\nSoon', False),  # future-ready stub
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
                'Gift Card': 'Gift*',
            }.get(key, label)
            b = PaymentButton(key, pretty, enabled=enabled, secondary=not enabled)
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
            'Gift': 'Gift Card',
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
        self.refresh_theme()

    def _row(self, label: str) -> QLabel:
        row = QHBoxLayout()
        l = QLabel(label)
        l.setObjectName('posTotMute')
        v = QLabel('KES 0.00')
        v.setObjectName('posTotVal')
        row.addWidget(l)
        row.addStretch()
        row.addWidget(v)
        self._body.addLayout(row)
        return v

    def set_amounts(self, currency, sub, tax, total, discount=0.0):
        cur = currency or 'KES'
        self._sub_lbl.setText(f'{cur} {sub:,.2f}')
        self._tax_lbl.setText(f'{cur} {tax:,.2f}')
        text = f'{cur} {total:,.2f}'
        self._tot_lbl.setText(text)
        try:
            sav = float(discount or 0)
        except (TypeError, ValueError):
            sav = 0.0
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
            base = (
                f"color:{gold};font-size:30px;font-weight:900;background:transparent;")
            flash = (
                f"color:{C.get('gold_lt', gold)};font-size:32px;font-weight:900;"
                f"background:transparent;")
            self._tot_lbl.setStyleSheet(flash)
            QTimer.singleShot(160, lambda: self._tot_lbl.setStyleSheet(base))
        except Exception:
            pass

    def refresh_theme(self):
        self.setStyleSheet(
            f"QFrame#posTotFrame{{background:{C['panel']};border:1px solid {C['border']};"
            f"border-radius:{RADIUS['lg']}px;}}")
        self._sep.setStyleSheet(f"background:{C['border']};border:none;")
        self._section.setStyleSheet(
            f"color:{C['muted']};font-size:11px;font-weight:800;letter-spacing:0.8px;"
            f"text-transform:uppercase;background:transparent;")
        self._total_hdr.setStyleSheet(
            f"color:{C['text']};font-size:15px;font-weight:800;background:transparent;")
        self._tot_lbl.setStyleSheet(
            f"color:{C['gold']};font-size:30px;font-weight:900;background:transparent;")
        for w in self.findChildren(QLabel):
            if w.objectName() == 'posTotMute':
                w.setStyleSheet(
                    f"color:{C['text2']};font-size:14px;font-weight:600;background:transparent;")
            elif w.objectName() == 'posTotVal':
                w.setStyleSheet(
                    f"color:{C['text']};font-size:14px;background:transparent;")
            elif w.objectName() == 'posTotSave':
                w.setStyleSheet(
                    f"color:{C['ok']};font-size:14px;font-weight:700;background:transparent;")
        self.disc_label.setStyleSheet(
            f"color:{C['text2']};font-size:14px;font-weight:600;background:transparent;")


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
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, 'Customers', 'Customer list is not available yet.')
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
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, 'Customers', 'Cannot add customer — API unavailable.')
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
        if q and matched > 1 and not self.view().isVisible():
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
    """Search / barcode field — Enter submits scan. ASCII placeholder (no emoji)."""
    submitted = pyqtSignal(str)

    def __init__(self, placeholder='Search or scan barcode...', parent=None):
        super().__init__(parent)
        self.setObjectName('mbtSearchBar')
        self.setPlaceholderText(placeholder)
        self.setMinimumHeight(TOUCH_MIN - 2)
        self.setClearButtonEnabled(True)
        self.refresh_theme()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.submitted.emit(self.text().strip())
            event.accept()
            return
        super().keyPressEvent(event)

    def refresh_theme(self):
        r = RADIUS['md']
        self.setStyleSheet(
            f"QLineEdit#mbtSearchBar{{background:{C['input']};color:{C['text']};"
            f"border:1px solid {C['border']};border-radius:{r}px;"
            f"padding:0 12px 0 14px;font-size:14px;min-height:{TOUCH_MIN - 4}px;}}"
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
        self._total_count = 0
        self._categories_by_name = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)
        self._hint = QLabel('')
        self._hint.setStyleSheet('background:transparent;')
        self._hint.hide()
        outer.addWidget(self._hint)
        self._host = QWidget()
        self._grid = QGridLayout(self._host)
        self._grid.setSpacing(GAP)
        self._grid.setContentsMargins(PADDING - 4, PADDING - 4, PADDING - 4, PADDING - 4)
        self._grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        outer.addWidget(self._host, 1)
        self.setStyleSheet('background:transparent;')

    def set_currency(self, cur: str):
        self._currency = cur or 'KES'

    def set_light(self, is_light: bool):
        self._is_light = bool(is_light)

    def set_categories_map(self, mapping: dict):
        self._categories_by_name = mapping or {}

    def clear(self):
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._hint.hide()

    def columns_for_width(self, available: int) -> int:
        card_w = 220 if self._is_light else 214
        gap = self._grid.horizontalSpacing() or GAP
        cols = max(2, int((max(640, available) + gap) // (card_w + gap)))
        return min(4, cols)

    def populate(self, products: list, columns: int = 3):
        self.clear()
        all_prods = list(products or [])
        self._total_count = len(all_prods)
        visible = all_prods[: self.MAX_VISIBLE]
        self._products = visible
        if self._total_count > self.MAX_VISIBLE:
            self._hint.setText(
                f'Showing {len(visible)} of {self._total_count} — type to search / filter category')
            self._hint.setStyleSheet(
                f"color:{C['muted']}; font-size:12px; font-weight:600; "
                f"background:transparent; padding:4px 12px;")
            self._hint.show()
        card_size = (220, 150) if self._is_light else (214, 148)
        cols = max(1, int(columns))
        cmap = self._categories_by_name or {}
        for i, p in enumerate(visible):
            cat = p.get('category') or 'General'
            meta = cmap.get(cat) or cmap.get(str(cat).lower()) or {}
            card = ProductCard(
                p, currency=self._currency, card_size=card_size,
                category_meta=meta)
            card.clicked.connect(self.productClicked.emit)
            self._grid.addWidget(card, i // cols, i % cols)

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
