"""
MBT POS — Lightweight modern chart widgets (Lovable-style)
No matplotlib / PyQtChart — pure Qt paint for small installer footprint.
"""
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy, QFrame
from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtGui import QPainter, QColor, QLinearGradient, QPen, QFont, QPainterPath
from desktop.utils.theme import C, RADIUS


def _qcolor(hex_color, alpha=255):
    c = QColor(hex_color or '#F2A800')
    c.setAlpha(int(alpha))
    return c


class GoldBarChart(QWidget):
    """
    Vertical bar chart — Sales last N days (Lovable MiniBar).
    values: list of float; labels: list of str (same length)
    """
    def __init__(self, parent=None, height=140):
        super().__init__(parent)
        self._values = []
        self._labels = []
        self.setMinimumHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setAttribute(Qt.WA_StyledBackground, True)

    def set_data(self, values, labels=None):
        self._values = [max(0.0, float(v or 0)) for v in (values or [])]
        self._labels = list(labels or [])
        while len(self._labels) < len(self._values):
            self._labels.append('')
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        if w < 20 or h < 20:
            return

        label_h = 18
        top_pad, bot_pad, side = 8, label_h + 6, 6
        chart_h = h - top_pad - bot_pad
        chart_w = w - side * 2
        n = len(self._values)
        if n == 0:
            p.setPen(_qcolor(C['muted']))
            p.setFont(QFont('Manrope', 11))
            p.drawText(self.rect(), Qt.AlignCenter, 'No sales data yet')
            return

        peak = max(self._values) or 1.0
        gap = max(4, chart_w // (n * 6))
        bar_w = max(8, (chart_w - gap * (n - 1)) / n)
        x = side

        gold = C['gold']
        gold_lt = C.get('gold_lt', gold)
        track = _qcolor(C['border'], 120)

        for i, val in enumerate(self._values):
            bh = (val / peak) * (chart_h - 4)
            bx = x + i * (bar_w + gap)
            by = top_pad + chart_h - bh

            # subtle track
            p.setPen(Qt.NoPen)
            p.setBrush(track)
            p.drawRoundedRect(QRectF(bx, top_pad, bar_w, chart_h), 4, 4)

            if bh > 1:
                grad = QLinearGradient(bx, by + bh, bx, by)
                grad.setColorAt(0, _qcolor(gold, 110))
                grad.setColorAt(1, _qcolor(gold_lt, 255))
                p.setBrush(grad)
                p.drawRoundedRect(QRectF(bx, by, bar_w, bh), 5, 5)

            # label
            lab = self._labels[i] if i < len(self._labels) else ''
            if lab:
                p.setPen(_qcolor(C['text2']))
                f = QFont('Manrope', 9)
                f.setWeight(QFont.DemiBold)
                p.setFont(f)
                p.drawText(QRectF(bx - 4, h - label_h, bar_w + 8, label_h),
                           Qt.AlignHCenter | Qt.AlignVCenter, lab)


class PaymentBars(QWidget):
    """Horizontal % bars for Cash / M-Pesa / Card (Lovable By Payment)."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []  # [{label, pct, color_key}]
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.setAttribute(Qt.WA_StyledBackground, True)

    def set_data(self, rows):
        """rows: list of dicts with label, value (amount), optional color"""
        total = sum(float(r.get('value') or r.get('total') or 0) for r in (rows or []))
        out = []
        palette = [C['gold'], C['ok'], C['info'], C['warn'], C['err']]
        for i, r in enumerate(rows or []):
            val = float(r.get('value') or r.get('total') or 0)
            pct = (val / total * 100.0) if total > 0 else 0.0
            out.append({
                'label': r.get('label') or r.get('payment_method') or 'Other',
                'pct': pct,
                'value': val,
                'color': r.get('color') or palette[i % len(palette)],
            })
        self._rows = out
        self.update()
        self.setMinimumHeight(max(100, 28 + len(out) * 36))

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        y = 4
        if not self._rows:
            p.setPen(_qcolor(C['muted']))
            p.setFont(QFont('Manrope', 11))
            p.drawText(self.rect(), Qt.AlignCenter, 'No payment data')
            return

        for row in self._rows:
            # label + pct
            p.setPen(_qcolor(C['text2']))
            f = QFont('Manrope', 11)
            p.setFont(f)
            p.drawText(QRectF(0, y, w * 0.55, 18), Qt.AlignLeft | Qt.AlignVCenter, str(row['label']))
            p.setPen(_qcolor(C['text']))
            f.setWeight(QFont.DemiBold)
            p.setFont(f)
            p.drawText(QRectF(w * 0.55, y, w * 0.45, 18),
                       Qt.AlignRight | Qt.AlignVCenter, f"{row['pct']:.0f}%")
            y += 20

            track = QRectF(0, y, w, 10)
            p.setPen(Qt.NoPen)
            p.setBrush(_qcolor(C.get('panel', C['card2']), 255))
            p.drawRoundedRect(track, 5, 5)
            fill_w = max(0.0, min(w, w * row['pct'] / 100.0))
            if fill_w > 1:
                grad = QLinearGradient(0, y, fill_w, y)
                grad.setColorAt(0, _qcolor(row['color'], 200))
                grad.setColorAt(1, _qcolor(row['color'], 255))
                p.setBrush(grad)
                p.drawRoundedRect(QRectF(0, y, fill_w, 10), 5, 5)
            y += 16


class ChartCard(QFrame):
    """Card shell with title + chart body."""
    def __init__(self, title, chart_widget, parent=None):
        super().__init__(parent)
        self.setObjectName('mbtChartCard')
        self._title = QLabel(title)
        self._chart = chart_widget
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(12)
        self._title.setStyleSheet(
            f"color:{C['text']}; font-size:15px; font-weight:700; background:transparent;")
        lay.addWidget(self._title)
        lay.addWidget(self._chart)
        self.refresh_theme()

    def refresh_theme(self):
        r = RADIUS['xl']
        self.setStyleSheet(
            f"QFrame#mbtChartCard {{ background:{C['card']}; border:1px solid {C['border']}; "
            f"border-radius:{r}px; }}")
        self._title.setStyleSheet(
            f"color:{C['text']}; font-size:15px; font-weight:700; background:transparent;")
        self._chart.update()

    def set_title(self, title):
        self._title.setText(title)
