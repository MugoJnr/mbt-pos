"""
MBT POS — Lightweight modern chart widgets
No matplotlib / PyQtChart — pure Qt paint for small installer footprint.
"""
from PyQt5.QtWidgets import QWidget, QLabel, QSizePolicy, QFrame, QVBoxLayout
from PyQt5.QtCore import Qt, QRectF, QTimer, QPointF
from PyQt5.QtGui import (
    QPainter, QColor, QLinearGradient, QPen, QFont, QPainterPath, QBrush, QPolygonF,
)
from desktop.utils.theme import C, RADIUS


def _qcolor(hex_color, alpha=255):
    c = QColor(hex_color or '#F5B301')
    c.setAlpha(int(alpha))
    return c


class GoldBarChart(QWidget):
    """Vertical bar chart — kept for compatibility."""

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
            p.setFont(QFont('Segoe UI', 11))
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
            p.setPen(Qt.NoPen)
            p.setBrush(track)
            p.drawRoundedRect(QRectF(bx, top_pad, bar_w, chart_h), 4, 4)
            if bh > 1:
                grad = QLinearGradient(bx, by + bh, bx, by)
                grad.setColorAt(0, _qcolor(gold, 110))
                grad.setColorAt(1, _qcolor(gold_lt, 255))
                p.setBrush(grad)
                p.drawRoundedRect(QRectF(bx, by, bar_w, bh), 5, 5)
            lab = self._labels[i] if i < len(self._labels) else ''
            if lab:
                p.setPen(_qcolor(C['text2']))
                f = QFont('Segoe UI', 9)
                f.setWeight(QFont.DemiBold)
                p.setFont(f)
                p.drawText(QRectF(bx - 4, h - label_h, bar_w + 8, label_h),
                           Qt.AlignHCenter | Qt.AlignVCenter, lab)


class GoldLineChart(QWidget):
    """Line + gradient area with reveal animation and hover tooltip."""

    def __init__(self, parent=None, height=160):
        super().__init__(parent)
        self._values = []
        self._labels = []
        self._progress = 1.0
        self._hover_i = -1
        self.setMinimumHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)
        self._anim = QTimer(self)
        self._anim.setInterval(33)
        self._anim.timeout.connect(self._tick)

    def set_data(self, values, labels=None):
        self._values = [max(0.0, float(v or 0)) for v in (values or [])]
        self._labels = list(labels or [])
        while len(self._labels) < len(self._values):
            self._labels.append('')
        self._progress = 0.0
        self._hover_i = -1
        self._anim.start()
        self.update()

    def _tick(self):
        self._progress = min(1.0, self._progress + 0.1)
        self.update()
        if self._progress >= 1.0:
            self._anim.stop()

    def _pts(self, w, h):
        n = len(self._values)
        if n == 0:
            return [], 14, 26, 10, max(10, h - 40)
        top_pad, bot_pad, side = 14, 26, 10
        chart_h = max(10, h - top_pad - bot_pad)
        chart_w = max(10, w - side * 2)
        peak = max(self._values) or 1.0
        out = []
        for i, val in enumerate(self._values):
            x = side + chart_w / 2.0 if n == 1 else side + chart_w * i / (n - 1)
            y = top_pad + chart_h - (val / peak) * (chart_h - 4)
            out.append(QPointF(x, y))
        return out, top_pad, bot_pad, side, chart_h

    def paintEvent(self, _event):
        painter = QPainter(self)
        if not painter.isActive():
            return
        painter.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        if w < 40 or h < 40:
            return
        if not self._values:
            painter.setPen(_qcolor(C['muted']))
            painter.setFont(QFont('Segoe UI', 11))
            painter.drawText(self.rect(), Qt.AlignCenter, 'No sales data yet')
            return

        pts, top_pad, bot_pad, side, chart_h = self._pts(w, h)
        n = len(pts)
        gold = C['gold']
        gold_lt = C.get('gold_lt', gold)
        base_y = float(top_pad + chart_h)

        painter.setPen(QPen(_qcolor(C['border'], 90), 1, Qt.DotLine))
        for g in (1, 2, 3):
            gy = int(top_pad + chart_h * g / 4)
            painter.drawLine(side, gy, w - side, gy)

        clip_w = int(side + (w - 2 * side) * self._progress)
        painter.setClipRect(0, 0, max(1, clip_w), h)

        if n >= 2:
            poly = QPolygonF()
            poly.append(QPointF(pts[0].x(), base_y))
            for pt in pts:
                poly.append(pt)
            poly.append(QPointF(pts[-1].x(), base_y))
            grad = QLinearGradient(0, float(top_pad), 0, base_y)
            grad.setColorAt(0.0, _qcolor(gold, 100))
            grad.setColorAt(1.0, _qcolor(gold, 10))
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(grad))
            painter.drawPolygon(poly)

            painter.setBrush(Qt.NoBrush)
            pen = QPen(_qcolor(gold_lt, 255), 2)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            for i in range(1, n):
                painter.drawLine(pts[i - 1], pts[i])

        for i, pt in enumerate(pts):
            r = 4 if i == self._hover_i else 3
            painter.setPen(Qt.NoPen)
            painter.setBrush(_qcolor(gold, 255))
            painter.drawEllipse(QRectF(pt.x() - r, pt.y() - r, r * 2, r * 2))

        painter.setClipping(False)

        painter.setPen(_qcolor(C['text2']))
        font = QFont('Segoe UI', 9)
        font.setWeight(QFont.DemiBold)
        painter.setFont(font)
        for i, pt in enumerate(pts):
            lab = self._labels[i] if i < len(self._labels) else ''
            if lab:
                painter.drawText(
                    QRectF(pt.x() - 18, h - bot_pad, 36, bot_pad - 2),
                    Qt.AlignCenter, lab)

        if 0 <= self._hover_i < n:
            val = self._values[self._hover_i]
            lab = self._labels[self._hover_i] if self._hover_i < len(self._labels) else ''
            tip = f"{lab}: {val:,.0f}" if lab else f"{val:,.0f}"
            pt = pts[self._hover_i]
            painter.setFont(QFont('Segoe UI', 10, QFont.Bold))
            br = painter.fontMetrics().boundingRect(tip)
            tw, th = br.width() + 14, br.height() + 8
            tx = max(4, min(int(pt.x() - tw / 2), w - tw - 4))
            ty = max(4, int(pt.y() - th - 8))
            painter.setPen(Qt.NoPen)
            painter.setBrush(_qcolor(C['card2'], 240))
            painter.drawRoundedRect(QRectF(tx, ty, tw, th), 6, 6)
            painter.setPen(_qcolor(C['text']))
            painter.drawText(QRectF(tx, ty, tw, th), Qt.AlignCenter, tip)

    def mouseMoveEvent(self, e):
        pts, *_ = self._pts(self.width(), self.height())
        best, dist = -1, 1e9
        for i, pt in enumerate(pts):
            d = abs(pt.x() - e.x())
            if d < dist:
                dist, best = d, i
        ni = best if dist < 36 else -1
        if ni != self._hover_i:
            self._hover_i = ni
            self.update()

    def leaveEvent(self, e):
        self._hover_i = -1
        self.update()
        super().leaveEvent(e)


class PaymentBars(QWidget):
    """Horizontal animated % bars for Cash / M-Pesa / Card."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []
        self._anim_pct = []
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)

    def set_data(self, rows):
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
        self._anim_pct = [0.0] * len(out)
        self.setMinimumHeight(max(100, 28 + len(out) * 40))
        self._timer.start()
        self.update()

    def _tick(self):
        done = True
        for i, row in enumerate(self._rows):
            target = row['pct']
            cur = self._anim_pct[i]
            if abs(target - cur) < 0.5:
                self._anim_pct[i] = target
            else:
                self._anim_pct[i] = cur + (target - cur) * 0.2
                done = False
        self.update()
        if done:
            self._timer.stop()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        y = 4
        if not self._rows:
            p.setPen(_qcolor(C['muted']))
            p.setFont(QFont('Segoe UI', 11))
            p.drawText(self.rect(), Qt.AlignCenter, 'No payment data')
            return

        for i, row in enumerate(self._rows):
            pct = self._anim_pct[i] if i < len(self._anim_pct) else row['pct']
            p.setPen(_qcolor(C['text2']))
            f = QFont('Segoe UI', 12)
            p.setFont(f)
            p.drawText(QRectF(0, y, w * 0.55, 18), Qt.AlignLeft | Qt.AlignVCenter, str(row['label']))
            p.setPen(_qcolor(C['text']))
            f.setWeight(QFont.DemiBold)
            p.setFont(f)
            p.drawText(QRectF(w * 0.55, y, w * 0.45, 18),
                       Qt.AlignRight | Qt.AlignVCenter, f"{pct:.0f}%")
            y += 22

            track = QRectF(0, y, w, 10)
            p.setPen(Qt.NoPen)
            p.setBrush(_qcolor(C.get('panel', C['card2']), 255))
            p.drawRoundedRect(track, 5, 5)
            fill_w = max(0.0, min(float(w), w * pct / 100.0))
            if fill_w > 1:
                grad = QLinearGradient(0, y, fill_w, y)
                grad.setColorAt(0, _qcolor(row['color'], 180))
                grad.setColorAt(1, _qcolor(row['color'], 255))
                p.setBrush(grad)
                p.drawRoundedRect(QRectF(0, y, fill_w, 10), 5, 5)
            y += 18


class ChartCard(QFrame):
    """Card shell with title + chart body."""

    def __init__(self, title, chart_widget, parent=None):
        super().__init__(parent)
        self.setObjectName('mbtChartCard')
        self._title = QLabel(title)
        self._chart = chart_widget
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
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
            f"border-radius:{r}px; }}"
        )
        self._title.setStyleSheet(
            f"color:{C['text']}; font-size:15px; font-weight:700; background:transparent;")
        self._chart.update()

    def set_title(self, title):
        self._title.setText(title)
