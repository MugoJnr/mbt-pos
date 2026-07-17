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


def round_qty(v, step=0.25) -> float:
    try:
        q = float(v)
    except (TypeError, ValueError):
        return step
    return max(step, round(round(q / step) * step, 2))


# ── CategoryIcon ──────────────────────────────────────────────────────────────

class CategoryIcon(QLabel):
    """Colored circle with category emoji — used when product has no image."""

    def __init__(self, category='General', size=48, parent=None):
        super().__init__(parent)
        self._category = category or 'General'
        self._size = int(size)
        self.setFixedSize(self._size, self._size)
        self.setAlignment(Qt.AlignCenter)
        self.refresh_theme()

    def set_category(self, category: str):
        self._category = category or 'General'
        self.refresh_theme()

    def refresh_theme(self):
        emoji, accent = category_visual(self._category)
        self.setText(emoji)
        r = self._size // 2
        self.setStyleSheet(
            f"QLabel {{ background:{qss_alpha(accent, 0.18)}; color:{accent}; "
            f"border-radius:{r}px; font-size:{max(16, self._size // 2)}px; "
            f"border:none; }}")


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

    def __init__(self, product: dict, currency='KES', card_size=(214, 148), parent=None):
        super().__init__(parent)
        self._product = product or {}
        self._currency = currency
        self._active = True
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
        self._icon = CategoryIcon(cat, size=44)
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
    """Segmented − | qty | + control. Qty rounded to 2 decimals; step 0.25."""
    valueChanged = pyqtSignal(float)

    def __init__(self, value=1.0, step=0.25, parent=None):
        super().__init__(parent)
        self._step = float(step)
        self.setObjectName('qtyControl')
        self.setFixedHeight(TOUCH_MIN - 6)
        self.setFixedWidth(118)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._minus = QPushButton('−')
        self._plus = QPushButton('+')
        for b, seg in ((self._minus, 'left'), (self._plus, 'right')):
            b.setObjectName('qtyBtn')
            b.setProperty('seg', seg)
            b.setFixedSize(32, TOUCH_MIN - 6)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)

        self._spin = QDoubleSpinBox()
        self._spin.setObjectName('qtyInput')
        self._spin.setRange(self._step, 9999.0)
        self._spin.setDecimals(2)
        self._spin.setSingleStep(self._step)
        self._spin.setValue(round_qty(value, self._step))
        self._spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self._spin.setAlignment(Qt.AlignCenter)
        self._spin.setFixedHeight(TOUCH_MIN - 6)
        le = self._spin.lineEdit()
        if le:
            le.setAlignment(Qt.AlignCenter)

        self._spin.valueChanged.connect(self._on_spin)
        self._minus.clicked.connect(lambda: self._bump(-self._step))
        self._plus.clicked.connect(lambda: self._bump(self._step))
        lay.addWidget(self._minus)
        lay.addWidget(self._spin, 1)
        lay.addWidget(self._plus)
        self.refresh_theme()

    def value(self) -> float:
        return float(self._spin.value())

    def setValue(self, v):
        self._spin.blockSignals(True)
        self._spin.setValue(round_qty(v, self._step))
        self._spin.blockSignals(False)

    def _bump(self, delta):
        self.setValue(self.value() + delta)
        self.valueChanged.emit(self.value())

    def _on_spin(self, v):
        q = round_qty(v, self._step)
        if abs(q - float(v)) > 1e-9:
            self._spin.blockSignals(True)
            self._spin.setValue(q)
            self._spin.blockSignals(False)
        self.valueChanged.emit(q)

    def refresh_theme(self):
        q_bg, q_card = C['input'], C['card2']
        q_fg, q_bd, q_bd1 = C['text'], C['border2'], C['border']
        q_hover, q_gold, q_sel = C['hover'], C['gold'], C['selected']
        q_spin = C['card']
        r = 12
        self.setStyleSheet(
            f"QWidget#qtyControl{{background:{q_bg};border:1px solid {q_bd};"
            f"border-radius:{r}px;}}"
            f"QPushButton#qtyBtn{{background:{q_card};color:{q_fg};border:none;"
            f"font-size:16px;font-weight:700;padding:0;min-height:{TOUCH_MIN - 6}px;}}"
            f"QPushButton#qtyBtn:hover{{background:{q_hover};color:{q_gold};}}"
            f"QPushButton#qtyBtn[seg=\"left\"]{{border-top-left-radius:{r}px;"
            f"border-bottom-left-radius:{r}px;border-right:1px solid {q_bd1};}}"
            f"QPushButton#qtyBtn[seg=\"right\"]{{border-top-right-radius:{r}px;"
            f"border-bottom-right-radius:{r}px;border-left:1px solid {q_bd1};}}"
            f"QDoubleSpinBox#qtyInput{{background:{q_spin};color:{q_fg};border:none;"
            f"padding:0;font-size:14px;font-weight:700;}}"
            f"QDoubleSpinBox#qtyInput:focus{{background:{q_hover};}}"
        )


# ── PaymentButton / PaymentSegment ────────────────────────────────────────────

class PaymentButton(QPushButton):
    """Single checkable payment method chip."""

    def __init__(self, key: str, label: str, parent=None):
        super().__init__(label, parent)
        self.method_key = key
        self.setObjectName('posPayToggle')
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(TOUCH_MIN - 2)
        self.refresh_theme()

    def refresh_theme(self):
        self.setStyleSheet(
            f"QPushButton#posPayToggle{{background:{C['card2']};color:{C['text2']};"
            f"border:1px solid {C['border']};border-radius:{RADIUS['md']}px;"
            f"font-size:13px;font-weight:700;min-height:{TOUCH_MIN - 2}px;padding:6px 10px;}}"
            f"QPushButton#posPayToggle:checked{{background:{qss_alpha(C['gold'], 0.14)};"
            f"color:{C['gold']};border-color:{C['gold']};font-weight:800;}}"
            f"QPushButton#posPayToggle:hover:!checked{{background:{C['hover']};color:{C['text']};}}"
        )


class PaymentSegment(QWidget):
    """Cash | M-Pesa | Card segmented row."""
    methodChanged = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self._btns = {}
        for key, label in (('Cash', '💵 Cash'), ('M-Pesa', '📱 M-Pesa'), ('Card', '💳 Card')):
            b = PaymentButton(key, label)
            b.clicked.connect(lambda _=False, k=key: self.select(k, emit=True))
            lay.addWidget(b)
            self._btns[key] = b
        self.select('Cash', emit=False)

    def select(self, method: str, emit=True):
        for k, b in self._btns.items():
            b.blockSignals(True)
            b.setChecked(k == method)
            b.blockSignals(False)
        if emit:
            self.methodChanged.emit(method)

    def current(self) -> str:
        for k, b in self._btns.items():
            if b.isChecked():
                return k
        return 'Cash'

    def refresh_theme(self):
        for b in self._btns.values():
            b.refresh_theme()


# ── SummaryCard ───────────────────────────────────────────────────────────────

class SummaryCard(QFrame):
    """Checkout totals panel with gold TOTAL."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('posTotFrame')
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)
        self._body = lay
        self._sub_lbl = self._row('Subtotal')
        self.disc_label = QLabel('Discount (KES)')
        self.disc_edit = None  # set by host (KES QLineEdit)
        self._tax_lbl = self._row('Tax')
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setObjectName('posTotSep')
        lay.addWidget(sep)
        self._sep = sep
        tot = QHBoxLayout()
        self._total_hdr = QLabel('TOTAL')
        self._tot_lbl = QLabel('KES 0.00')
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

    def set_amounts(self, currency, sub, tax, total):
        cur = currency or 'KES'
        self._sub_lbl.setText(f'{cur} {sub:,.2f}')
        self._tax_lbl.setText(f'{cur} {tax:,.2f}')
        self._tot_lbl.setText(f'{cur} {total:,.2f}')

    def refresh_theme(self):
        self.setStyleSheet(
            f"QFrame#posTotFrame{{background:{C['panel']};border:1px solid {C['border']};"
            f"border-radius:{RADIUS['lg']}px;}}")
        self._sep.setStyleSheet(f"background:{C['border']};border:none;")
        self._total_hdr.setStyleSheet(
            f"color:{C['text']};font-size:14px;font-weight:700;background:transparent;")
        self._tot_lbl.setStyleSheet(
            f"color:{C['gold']};font-size:28px;font-weight:900;background:transparent;")
        for w in self.findChildren(QLabel):
            if w.objectName() == 'posTotMute':
                w.setStyleSheet(
                    f"color:{C['text2']};font-size:14px;font-weight:600;background:transparent;")
            elif w.objectName() == 'posTotVal':
                w.setStyleSheet(
                    f"color:{C['text']};font-size:14px;background:transparent;")
        self.disc_label.setStyleSheet(
            f"color:{C['text2']};font-size:14px;font-weight:600;background:transparent;")


# ── CustomerSelector ──────────────────────────────────────────────────────────

class CustomerSelector(QComboBox):
    """Walk-in + named customers for credit / debt / notes."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('posCustomer')
        self.setMinimumHeight(TOUCH_MIN - 2)
        self.setEditable(False)
        self.addItem('Walk-in Customer', None)
        self.refresh_theme()

    def load_customers(self, customers: list):
        cur = self.currentData()
        self.blockSignals(True)
        self.clear()
        self.addItem('Walk-in Customer', None)
        for c in customers or []:
            name = (c.get('name') or 'Customer').strip()
            phone = (c.get('phone') or '').strip()
            label = f'{name}  ·  {phone}' if phone else name
            self.addItem(label, c.get('id'))
        idx = self.findData(cur)
        self.setCurrentIndex(idx if idx >= 0 else 0)
        self.blockSignals(False)

    def selected_id(self):
        return self.currentData()

    def refresh_theme(self):
        self.setStyleSheet(
            f"QComboBox#posCustomer{{background:{C['input']};color:{C['text']};"
            f"border:1px solid {C['border2']};border-radius:{RADIUS['md']}px;"
            f"padding:6px 10px;font-size:13px;min-height:{TOUCH_MIN - 4}px;}}"
            f"QComboBox#posCustomer:focus{{border-color:{C['gold']};}}"
            f"QComboBox#posCustomer QAbstractItemView{{background:{C['card']};"
            f"color:{C['text']};selection-background-color:{C['hover']};}}"
        )


# ── PosSearchBar ──────────────────────────────────────────────────────────────

class PosSearchBar(QLineEdit):
    """Search / barcode field — 🔍 placeholder, Enter submits scan."""
    submitted = pyqtSignal(str)

    def __init__(self, placeholder='🔍  Search or scan barcode…', parent=None):
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
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)
        self._hint = QLabel('')
        self._hint.setStyleSheet('background:transparent;')
        self._hint.hide()
        outer.addWidget(self._hint)
        self._host = QWidget()
        self._grid = QGridLayout(self._host)
        self._grid.setSpacing(GAP - 4)
        self._grid.setContentsMargins(PADDING - 4, PADDING - 4, PADDING - 4, PADDING - 4)
        self._grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        outer.addWidget(self._host, 1)
        self.setStyleSheet('background:transparent;')

    def set_currency(self, cur: str):
        self._currency = cur or 'KES'

    def set_light(self, is_light: bool):
        self._is_light = bool(is_light)

    def clear(self):
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._hint.hide()

    def columns_for_width(self, available: int) -> int:
        card_w = 220 if self._is_light else 214
        gap = self._grid.horizontalSpacing() or (GAP - 4)
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
        for i, p in enumerate(visible):
            card = ProductCard(p, currency=self._currency, card_size=card_size)
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
                PaymentButton, PaymentSegment, SummaryCard, CustomerSelector,
                PosSearchBar):
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
