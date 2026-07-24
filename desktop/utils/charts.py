"""
MBT POS — Lightweight modern chart widgets
No matplotlib / PyQtChart — pure Qt paint for small installer footprint.
"""
import os
from PyQt5.QtWidgets import (
    QWidget, QLabel, QSizePolicy, QFrame, QVBoxLayout, QHBoxLayout,
    QPushButton, QStyle, QDialog, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView,
)
from PyQt5.QtCore import Qt, QRectF, QTimer, QPointF, QSize, pyqtSignal
from PyQt5.QtGui import (
    QPainter, QColor, QLinearGradient, QPen, QFont, QFontMetrics, QPainterPath,
    QBrush, QPolygonF,
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
        # Extra top pad so peak value labels never flush against the chart edge
        top_pad, bot_pad, side = 22, label_h + 6, 6
        chart_h = h - top_pad - bot_pad
        chart_w = w - side * 2
        n = len(self._values)
        if n == 0:
            p.setPen(_qcolor(C['muted']))
            p.setFont(QFont('Segoe UI', 11))
            p.drawText(self.rect(), Qt.AlignCenter, 'No sales data yet')
            return
        # Sparse week caption (same language as GoldLineChart)
        nonzero = [(i, v) for i, v in enumerate(self._values) if v > 0.009]
        sparse_note = ''
        if len(self._values) >= 5 and len(nonzero) <= 2:
            if not nonzero:
                sparse_note = 'No sales in this period'
            else:
                peak_i = max(nonzero, key=lambda t: t[1])[0]
                lab = self._labels[peak_i] if peak_i < len(self._labels) else ''
                sparse_note = f'Quiet week · peak {lab}' if lab else 'Quiet week · sparse sales'
        top_extra = 18 if sparse_note else 0
        if sparse_note:
            p.setPen(_qcolor(C['text2']))
            f = QFont('Segoe UI', 10)
            f.setWeight(QFont.DemiBold)
            p.setFont(f)
            p.drawText(QRectF(side, 2, max(40, chart_w), 16),
                       Qt.AlignLeft | Qt.AlignVCenter, sparse_note)
        peak = max(self._values) or 1.0
        gap = max(4, chart_w // (n * 6))
        bar_w = max(8, (chart_w - gap * (n - 1)) / n)
        # Left gutter for Y-axis scale (matches GoldLineChart polish)
        y_gutter = 36
        x = side + y_gutter
        usable_w = chart_w - y_gutter
        bar_w = max(8, (usable_w - gap * (n - 1)) / n)
        gold = C['gold']
        gold_lt = C.get('gold_lt', gold)
        track = _qcolor(C['border'], 120)
        usable_h = chart_h - top_extra
        # Leave ~12% headroom above the tallest bar for value labels
        label_headroom = max(14, int(usable_h * 0.12))
        bar_h_max = max(20.0, usable_h - label_headroom)
        # Horizontal grid + Y labels
        p.setPen(QPen(_qcolor(C['border'], 90), 1, Qt.DotLine))
        for g in (1, 2, 3):
            gy = int(top_pad + top_extra + usable_h * g / 4)
            p.drawLine(int(side + y_gutter), gy, int(side + chart_w), gy)
        p.setPen(_qcolor(C['muted']))
        yf = QFont('Segoe UI', 8)
        p.setFont(yf)
        for frac, label_v in ((0.0, peak), (0.5, peak / 2), (1.0, 0.0)):
            gy = int(top_pad + top_extra + usable_h * frac)
            p.drawText(
                QRectF(2, gy - 8, y_gutter - 2, 16),
                Qt.AlignRight | Qt.AlignVCenter, f"{label_v:,.0f}")
        for i, val in enumerate(self._values):
            # Floor nonzero bars so quiet days stay visible (not near-invisible stubs)
            raw_bh = (val / peak) * (bar_h_max - 4)
            if val > 0.009:
                bh = max(10.0, raw_bh)
            else:
                bh = 0.0
            bx = x + i * (bar_w + gap)
            by = top_pad + top_extra + usable_h - bh
            p.setPen(Qt.NoPen)
            p.setBrush(track)
            p.drawRoundedRect(QRectF(bx, top_pad + top_extra, bar_w, usable_h), 4, 4)
            if bh > 1:
                grad = QLinearGradient(bx, by + bh, bx, by)
                grad.setColorAt(0, _qcolor(gold, 110))
                grad.setColorAt(1, _qcolor(gold_lt, 255))
                p.setBrush(grad)
                p.drawRoundedRect(QRectF(bx, by, bar_w, bh), 5, 5)
            # Value label on peak bars so quiet weeks still read as intentional
            if val > 0.009 and (val / peak) >= 0.25:
                p.setPen(_qcolor(C['text2']))
                f = QFont('Segoe UI', 8)
                f.setWeight(QFont.DemiBold)
                p.setFont(f)
                try:
                    lab_v = f'{val:,.0f}'
                except Exception:
                    lab_v = str(int(val))
                p.drawText(QRectF(bx - 2, by - 14, bar_w + 4, 14),
                           Qt.AlignHCenter | Qt.AlignBottom, lab_v)
            lab = self._labels[i] if i < len(self._labels) else ''
            if lab:
                p.setPen(_qcolor(C['text2']))
                f = QFont('Segoe UI', 9)
                f.setWeight(QFont.DemiBold)
                p.setFont(f)
                p.drawText(QRectF(bx - 4, h - label_h, bar_w + 8, label_h),
                           Qt.AlignHCenter | Qt.AlignVCenter, lab)
        # Center watermark when week is sparse — charts don't look "broken"
        if sparse_note and len(nonzero) <= 2:
            p.setPen(_qcolor(C['muted'], 140))
            f = QFont('Segoe UI', 12)
            f.setWeight(QFont.DemiBold)
            p.setFont(f)
            p.drawText(QRectF(side, top_pad + top_extra, chart_w, usable_h),
                       Qt.AlignCenter, sparse_note)


class GoldLineChart(QWidget):
    """Line + gradient area with reveal animation and hover tooltip."""

    activated = pyqtSignal()

    def __init__(self, parent=None, height=160):
        super().__init__(parent)
        self._values = []
        self._labels = []
        self._progress = 1.0
        self._hover_i = -1
        self.setMinimumHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName('Sales trend chart')
        self.setAccessibleDescription('Click or press Enter to open chart details')
        self.setToolTip('Open sales trend details')
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
        # Sparse week: ≤2 active days — show caption so empty valleys read intentional
        nonzero = [(i, v) for i, v in enumerate(self._values) if v > 0.009]
        self._sparse = bool(self._values) and len(nonzero) <= 2 and len(self._values) >= 5
        self._sparse_note = ''
        if self._sparse and nonzero:
            peak_i = max(nonzero, key=lambda t: t[1])[0]
            lab = self._labels[peak_i] if peak_i < len(self._labels) else ''
            self._sparse_note = (
                f'Quiet week · peak {lab}' if lab else 'Quiet week · sparse sales'
            )
        elif self._values and not nonzero:
            self._sparse_note = 'No sales in this period'
            self._sparse = True
        # Offscreen / QA captures: paint fully revealed (timers may not tick)
        skip_anim = (os.environ.get('QT_QPA_PLATFORM') or '').lower() == 'offscreen'
        if skip_anim:
            self._progress = 1.0
            self._anim.stop()
            self.update()
        else:
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
            return [], 14, 26, 48, 10, max(10, h - 40)
        # Extra top pad when sparse caption is shown
        top_pad = 28 if getattr(self, '_sparse_note', '') else 18
        bot_pad = 26
        left_pad, right_pad = 48, 10  # left room for Y-axis values
        chart_h = max(10, h - top_pad - bot_pad)
        chart_w = max(10, w - left_pad - right_pad)
        peak = max(self._values) or 1.0
        # ~10% headroom so the peak point never kisses the top edge
        headroom = max(8.0, chart_h * 0.10)
        out = []
        for i, val in enumerate(self._values):
            x = left_pad + chart_w / 2.0 if n == 1 else left_pad + chart_w * i / (n - 1)
            y = top_pad + headroom + (chart_h - headroom) - (val / peak) * (chart_h - headroom - 4)
            out.append(QPointF(x, y))
        return out, top_pad, bot_pad, left_pad, right_pad, chart_h

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

        pts, top_pad, bot_pad, left_pad, right_pad, chart_h = self._pts(w, h)
        n = len(pts)
        gold = C['gold']
        gold_lt = C.get('gold_lt', gold)
        base_y = float(top_pad + chart_h)

        note = getattr(self, '_sparse_note', '') or ''
        if note:
            painter.setPen(_qcolor(C['text2']))
            f = QFont('Segoe UI', 10)
            f.setWeight(QFont.DemiBold)
            painter.setFont(f)
            painter.drawText(
                QRectF(left_pad, 2, max(40, w - left_pad - right_pad), 20),
                Qt.AlignLeft | Qt.AlignVCenter, note)

        painter.setPen(QPen(_qcolor(C['border'], 90), 1, Qt.DotLine))
        peak = max(self._values) or 1.0
        for g in (1, 2, 3):
            gy = int(top_pad + chart_h * g / 4)
            painter.drawLine(left_pad, gy, w - right_pad, gy)
        # Y-axis value labels on the LEFT so they don't collide with the line
        painter.setPen(_qcolor(C['muted']))
        yf = QFont('Segoe UI', 8)
        painter.setFont(yf)
        for frac, label_v in ((0.0, peak), (0.5, peak / 2), (1.0, 0.0)):
            gy = int(top_pad + chart_h * frac)
            txt = f"{label_v:,.0f}"
            painter.drawText(
                QRectF(2, gy - 8, left_pad - 4, 16),
                Qt.AlignRight | Qt.AlignVCenter, txt)

        clip_w = int(left_pad + (w - left_pad - right_pad) * self._progress)
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

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.activated.emit()
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.activated.emit()
            e.accept()
            return
        super().keyPressEvent(e)

    def data_rows(self):
        return [
            {'label': self._labels[i] if i < len(self._labels) else '', 'value': value}
            for i, value in enumerate(self._values)
        ]


class PaymentBars(QWidget):
    """Horizontal animated % bars for Cash / M-Pesa / Card."""

    activated = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []
        self._anim_pct = []
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName('Payment mix chart')
        self.setAccessibleDescription('Click or press Enter to open payment details')
        self.setToolTip('Open payment mix details')
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)

    def set_data(self, rows):
        # Percent of active (non-zero) mix only — avoids "Mixed 20%" with one bar
        active = []
        for r in (rows or []):
            val = float(r.get('value') or r.get('total') or 0)
            if val <= 0.009:
                continue
            active.append({
                'label': r.get('label') or r.get('payment_method') or 'Other',
                'value': val,
                'color': r.get('color'),
            })
        # Fit chart card: keep top 3 by value, roll rest into Other (≤4 rows, no clip)
        active.sort(key=lambda x: x['value'], reverse=True)
        if len(active) > 3:
            head, tail = active[:3], active[3:]
            other_val = sum(x['value'] for x in tail)
            if other_val > 0.009:
                head.append({'label': 'Other', 'value': other_val, 'color': None})
            active = head
        total = sum(x['value'] for x in active) or 0.0
        out = []
        palette = [C['gold'], C['ok'], C['info'], C['warn'], C['err']]
        for i, r in enumerate(active):
            val = float(r['value'])
            pct = (val / total * 100.0) if total > 0 else 0.0
            out.append({
                'label': r['label'],
                'pct': pct,
                'value': val,
                'color': r.get('color') or palette[i % len(palette)],
            })
        self._rows = out
        # Offscreen / QA captures: skip animation so % always sum to 100 in screenshots
        skip_anim = (os.environ.get('QT_QPA_PLATFORM') or '').lower() == 'offscreen'
        self._anim_pct = [float(r['pct']) for r in out] if skip_anim else [0.0] * len(out)
        # Compact row rhythm so ≤4 bars fit ChartCard without internal scroll
        row_h = 32
        h = max(96, 8 + max(1, len(out) or 1) * row_h)
        self.setMinimumHeight(h)
        self.setMaximumHeight(h)
        if skip_anim:
            self._timer.stop()
            self.update()
        else:
            self._timer.start()
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.activated.emit()
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.activated.emit()
            e.accept()
            return
        super().keyPressEvent(e)

    def data_rows(self):
        return [dict(row) for row in self._rows]

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
        p.setClipRect(self.rect())
        # Inset so long labels / %·amount never paint past the ChartCard edge
        pad = 2.0
        w = max(1.0, float(self.width()) - pad * 2)
        x0 = pad
        y = 4.0
        if not self._rows:
            p.setPen(_qcolor(C['muted']))
            p.setFont(QFont('Segoe UI', 11))
            p.drawText(self.rect(), Qt.AlignCenter, 'No payment data')
            return

        for i, row in enumerate(self._rows):
            pct = self._anim_pct[i] if i < len(self._anim_pct) else row['pct']
            f = QFont('Segoe UI', 11)
            p.setFont(f)
            fm = QFontMetrics(f)
            label_w = w * 0.40
            value_w = w * 0.58
            gap = w * 0.02
            label = fm.elidedText(str(row['label']), Qt.ElideRight, int(label_w))
            p.setPen(_qcolor(C['text2']))
            p.drawText(QRectF(x0, y, label_w, 16), Qt.AlignLeft | Qt.AlignVCenter, label)
            f.setWeight(QFont.DemiBold)
            p.setFont(f)
            fm_b = QFontMetrics(f)
            amt = float(row.get('value') or 0)
            if amt >= 1_000_000:
                amt_s = f"{amt / 1_000_000:.1f}M"
            elif amt >= 10_000:
                amt_s = f"{amt / 1_000:.1f}K"
            elif amt >= 1:
                amt_s = f"{amt:,.0f}"
            else:
                amt_s = ''
            right = f"{pct:.0f}% · {amt_s}" if amt_s else f"{pct:.0f}%"
            right = fm_b.elidedText(right, Qt.ElideLeft, int(value_w))
            p.setPen(_qcolor(C['text']))
            p.drawText(QRectF(x0 + label_w + gap, y, value_w, 16),
                       Qt.AlignRight | Qt.AlignVCenter, right)
            y += 18

            track = QRectF(x0, y, w, 8)
            p.setPen(Qt.NoPen)
            p.setBrush(_qcolor(C.get('panel', C['card2']), 255))
            p.drawRoundedRect(track, 4, 4)
            fill_w = max(0.0, min(float(w), w * pct / 100.0))
            if fill_w > 1:
                grad = QLinearGradient(x0, y, x0 + fill_w, y)
                grad.setColorAt(0, _qcolor(row['color'], 180))
                grad.setColorAt(1, _qcolor(row['color'], 255))
                p.setBrush(grad)
                p.drawRoundedRect(QRectF(x0, y, fill_w, 8), 4, 4)
            y += 14


class ChartCard(QFrame):
    """Card shell with title + chart body."""

    activated = pyqtSignal()

    def __init__(self, title, chart_widget, parent=None, expandable=False):
        super().__init__(parent)
        self.setObjectName('mbtChartCard')
        self._title = QLabel(title)
        self._chart = chart_widget
        self._expandable = bool(expandable)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)
        header = QHBoxLayout()
        header.setSpacing(10)
        self._title.setStyleSheet(
            f"color:{C['text']}; font-size:15px; font-weight:700; background:transparent;")
        header.addWidget(self._title, 1)
        self._expand_btn = None
        if self._expandable:
            btn = QPushButton('Expand')
            btn.setObjectName('mbtChartExpandBtn')
            btn.setIcon(self.style().standardIcon(QStyle.SP_TitleBarMaxButton))
            btn.setIconSize(QSize(16, 16))
            btn.setMinimumSize(88, 38)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip('Open full chart and data table')
            btn.setAccessibleName('Expand chart')
            btn.clicked.connect(self.activated.emit)
            header.addWidget(btn)
            self._expand_btn = btn
            if hasattr(self._chart, 'activated'):
                self._chart.activated.connect(self.activated.emit)
        lay.addLayout(header)
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
        if self._expand_btn is not None:
            self._expand_btn.setStyleSheet(
                f"QPushButton#mbtChartExpandBtn {{ background:{C['card2']}; color:{C['text2']}; "
                f"border:1px solid {C['border']}; border-radius:9px; padding:0 10px; "
                f"font-size:12px; font-weight:700; }}"
                f"QPushButton#mbtChartExpandBtn:hover {{ color:{C['gold']}; "
                f"border-color:{C['gold']}; background:{C['hover']}; }}"
                f"QPushButton#mbtChartExpandBtn:focus {{ border:2px solid {C['focus']}; }}"
            )
        self._chart.update()

    def set_title(self, title):
        self._title.setText(title)


class ChartDetailsDialog(QDialog):
    """Responsive native detail view for a dashboard chart and exact values."""

    def __init__(self, kind, title, rows, currency='KES', parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(820, 620)
        self.setMinimumSize(620, 480)
        self.setAccessibleName(f'{title} details')

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(14)

        heading = QLabel(title)
        heading.setStyleSheet(
            f"color:{C['text']};font-size:20px;font-weight:800;background:transparent;")
        description = QLabel(
            'Exact values for the selected period. Use Tab to reach the table and Close button.')
        description.setWordWrap(True)
        description.setStyleSheet(
            f"color:{C['text2']};font-size:12px;background:transparent;")
        root.addWidget(heading)
        root.addWidget(description)

        if kind == 'trend':
            chart = GoldLineChart(height=280)
            chart.setCursor(Qt.ArrowCursor)
            chart.setFocusPolicy(Qt.NoFocus)
            chart.setToolTip('')
            chart.set_data(
                [r.get('value', 0) for r in rows],
                [r.get('label', '') for r in rows],
            )
            headers = ['Day', 'Gross sales']
            table_rows = [
                [str(r.get('label') or '—'), f"{currency} {float(r.get('value') or 0):,.2f}"]
                for r in rows
            ]
        else:
            chart = PaymentBars()
            chart.setCursor(Qt.ArrowCursor)
            chart.setFocusPolicy(Qt.NoFocus)
            chart.setToolTip('')
            chart.set_data(rows)
            headers = ['Payment method', 'Collected', 'Share']
            clean_rows = chart.data_rows()
            table_rows = [
                [
                    str(r.get('label') or 'Other'),
                    f"{currency} {float(r.get('value') or 0):,.2f}",
                    f"{float(r.get('pct') or 0):.1f}%",
                ]
                for r in clean_rows
            ]

        chart.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root.addWidget(chart, 2)

        table = QTableWidget(len(table_rows), len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setAlternatingRowColors(False)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for col in range(1, len(headers)):
            table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeToContents)
        for row_idx, row in enumerate(table_rows):
            for col_idx, text in enumerate(row):
                item = QTableWidgetItem(text)
                if col_idx:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(row_idx, col_idx, item)
        table.setAccessibleName(f'{title} exact values')
        table.setStyleSheet(
            f"QTableWidget {{ background:{C['card']};color:{C['text']};"
            f"border:1px solid {C['border']};border-radius:10px;gridline-color:{C['border']}; }}"
            f"QHeaderView::section {{ background:{C['card2']};color:{C['text2']};"
            f"padding:8px;border:none;border-bottom:1px solid {C['border']}; }}"
            f"QTableWidget::item:selected {{ background:{C['selected']};color:{C['text']}; }}"
        )
        root.addWidget(table, 1)

        close_row = QHBoxLayout()
        close_row.addStretch()
        close = QPushButton('Close')
        close.setMinimumSize(100, 42)
        close.setCursor(Qt.PointingHandCursor)
        close.setDefault(True)
        close.clicked.connect(self.accept)
        close.setStyleSheet(
            f"QPushButton {{ background:{C['gold']};color:{C.get('gold_fg', '#0B1220')};"
            f"border:none;border-radius:9px;font-weight:800;padding:0 18px; }}"
            f"QPushButton:hover {{ background:{C['gold_lt']}; }}"
            f"QPushButton:focus {{ border:2px solid {C['text']}; }}"
        )
        close_row.addWidget(close)
        root.addLayout(close_row)

        self.setStyleSheet(f"QDialog {{ background:{C['surface']}; }}")
