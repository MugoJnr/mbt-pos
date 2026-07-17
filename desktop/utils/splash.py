"""
MBT POS — Modern Splash Screen
MugoByte Technologies | mugobyte.com
"""
from PyQt5.QtWidgets import QWidget, QApplication
from PyQt5.QtCore    import Qt, QTimer, QPropertyAnimation, QEasingCurve, QRect, QRectF
from PyQt5.QtGui     import (QPainter, QColor, QFont, QLinearGradient,
                              QRadialGradient, QPen, QBrush, QPainterPath)


def _app_version():
    try:
        from desktop.main import APP_VERSION
        return APP_VERSION
    except Exception:
        return '2.3'


class SplashScreen(QWidget):
    def __init__(self):
        super().__init__()
        self._progress = 0
        self._status   = 'Starting'
        self._dots     = 0
        self._pulse    = 0
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.SplashScreen)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(520, 340)
        self._center()

        self._fade = QPropertyAnimation(self, b'windowOpacity')
        self._fade.setDuration(420)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        self._fade.start()

        self._dot_t = QTimer(self)
        self._dot_t.timeout.connect(self._tick)
        self._dot_t.start(80)

    def _center(self):
        s = QApplication.primaryScreen().geometry()
        self.move(s.center().x() - self.width() // 2,
                  s.center().y() - self.height() // 2)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        w, h = self.width(), self.height()
        card = QRectF(0, 0, w, h)

        # Soft outer glow
        glow = QRadialGradient(w / 2, h / 2, w * 0.55)
        glow.setColorAt(0.0, QColor(240, 165, 0, 28))
        glow.setColorAt(0.55, QColor(88, 56, 200, 14))
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(glow))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(card.adjusted(-6, -6, 6, 6), 22, 22)

        # Card background — deep navy with slight color shift
        bg = QLinearGradient(0, 0, w * 0.2, h)
        bg.setColorAt(0.0, QColor('#0B1220'))
        bg.setColorAt(0.45, QColor('#121C30'))
        bg.setColorAt(1.0, QColor('#0A101A'))
        path = QPainterPath()
        path.addRoundedRect(card, 18, 18)
        p.fillPath(path, QBrush(bg))

        # Accent corner wash
        wash = QLinearGradient(0, 0, w, h * 0.55)
        wash.setColorAt(0.0, QColor(240, 165, 0, 22))
        wash.setColorAt(0.35, QColor(99, 102, 241, 10))
        wash.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillPath(path, QBrush(wash))

        # Border
        p.setPen(QPen(QColor('#2A3F5F'), 1.2))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(card.adjusted(0.5, 0.5, -0.5, -0.5), 18, 18)

        # Top gold hairline
        top = QLinearGradient(40, 0, w - 40, 0)
        top.setColorAt(0.0, QColor(0, 0, 0, 0))
        top.setColorAt(0.2, QColor('#F0A500'))
        top.setColorAt(0.8, QColor('#FFC857'))
        top.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(top))
        p.drawRoundedRect(QRectF(0, 0, w, 3.5), 2, 2)

        # Pulsing badge behind logo
        pulse_a = 18 + int(10 * abs((self._pulse % 40) - 20) / 20)
        badge = QRadialGradient(w / 2, 78, 70)
        badge.setColorAt(0.0, QColor(240, 165, 0, pulse_a))
        badge.setColorAt(1.0, QColor(240, 165, 0, 0))
        p.setBrush(QBrush(badge))
        p.drawEllipse(QRectF(w / 2 - 70, 20, 140, 120))

        # Brand mark
        lf = QFont('Segoe UI', 52, QFont.Black)
        lf.setLetterSpacing(QFont.AbsoluteSpacing, 6)
        p.setFont(lf)
        p.setPen(QColor(0, 0, 0, 70))
        p.drawText(QRect(2, 36, w, 72), Qt.AlignHCenter | Qt.AlignVCenter, 'MBT')
        p.setPen(QColor('#FFB830'))
        p.drawText(QRect(0, 34, w, 72), Qt.AlignHCenter | Qt.AlignVCenter, 'MBT')

        tf = QFont('Segoe UI', 10, QFont.DemiBold)
        tf.setLetterSpacing(QFont.AbsoluteSpacing, 4)
        p.setFont(tf)
        p.setPen(QColor('#8FA8C4'))
        p.drawText(QRect(0, 108, w, 22), Qt.AlignHCenter, 'POINT OF SALE')

        bf = QFont('Segoe UI', 11, QFont.Bold)
        p.setFont(bf)
        p.setPen(QColor('#F0A500'))
        p.drawText(QRect(0, 142, w, 22), Qt.AlignHCenter, 'MugoByte Technologies')
        wf = QFont('Segoe UI', 9)
        p.setFont(wf)
        p.setPen(QColor('#5A738E'))
        p.drawText(QRect(0, 164, w, 18), Qt.AlignHCenter, 'mugobyte.com')

        # Progress track
        bx, by, bw, bh = 56, 230, w - 112, 8
        p.setBrush(QColor('#1A2A40'))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(bx, by, bw, bh), 4, 4)
        fw = int(bw * min(self._progress, 100) / 100)
        if fw > 0:
            fg = QLinearGradient(bx, 0, bx + fw, 0)
            fg.setColorAt(0, QColor('#E89500'))
            fg.setColorAt(0.5, QColor('#FFB830'))
            fg.setColorAt(1, QColor('#FFE08A'))
            p.setBrush(QBrush(fg))
            p.drawRoundedRect(QRectF(bx, by, max(fw, 10), bh), 4, 4)

        # Status
        sf = QFont('Segoe UI', 10, QFont.Medium)
        p.setFont(sf)
        p.setPen(QColor('#A8C0D8'))
        dots = '.' * (self._dots % 4)
        status = (self._status or 'Starting').rstrip('.')
        p.drawText(QRect(0, by + 16, w, 22), Qt.AlignHCenter, f'{status}{dots}')

        # Version footer — live app version
        vf = QFont('Segoe UI', 8)
        p.setFont(vf)
        p.setPen(QColor('#3D5168'))
        p.drawText(QRect(0, h - 30, w, 20), Qt.AlignHCenter,
                   f'v{_app_version()}  \u00b7  \u00a9 2026 MugoByte Technologies')
        p.end()

    def set_status(self, msg, progress=None):
        self._status = msg or 'Starting'
        if progress is not None:
            self._progress = progress
        self.update()
        QApplication.processEvents()

    def set_progress(self, v):
        self._progress = v
        self.update()
        QApplication.processEvents()

    def _tick(self):
        self._pulse += 1
        if self._pulse % 5 == 0:
            self._dots += 1
        self.update()

    def finish_and_close(self, delay=400):
        self._dot_t.stop()
        self._progress = 100
        self._status = 'Ready'
        self.update()
        QApplication.processEvents()
        fade = QPropertyAnimation(self, b'windowOpacity')
        fade.setDuration(420)
        fade.setStartValue(1.0)
        fade.setEndValue(0.0)
        fade.setEasingCurve(QEasingCurve.InCubic)
        fade.finished.connect(self.close)
        QTimer.singleShot(delay, fade.start)
        self._fade_out = fade
