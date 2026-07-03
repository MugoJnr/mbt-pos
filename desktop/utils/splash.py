"""
MBT POS — Premium Splash Screen
MugoByte Technologies | mugobyte.com
"""
import os
from PyQt5.QtWidgets import QWidget, QApplication
from PyQt5.QtCore    import Qt, QTimer, QPropertyAnimation, QEasingCurve, QRect
from PyQt5.QtGui     import (QPainter, QColor, QFont, QLinearGradient,
                              QRadialGradient, QPen, QBrush)


class SplashScreen(QWidget):
    def __init__(self):
        super().__init__()
        self._progress = 0
        self._status   = 'Starting…'
        self._dots     = 0
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.SplashScreen)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(500, 320)
        self._center()

        # Fade in
        self._fade = QPropertyAnimation(self, b'windowOpacity')
        self._fade.setDuration(500)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        self._fade.start()

        self._dot_t = QTimer(self)
        self._dot_t.timeout.connect(self._tick)
        self._dot_t.start(450)

    def _center(self):
        s = QApplication.primaryScreen().geometry()
        self.move(s.center().x() - self.width()//2,
                  s.center().y() - self.height()//2)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # Background card
        bg = QLinearGradient(0, 0, 0, h)
        bg.setColorAt(0,   QColor('#0C1422'))
        bg.setColorAt(0.5, QColor('#111C2E'))
        bg.setColorAt(1,   QColor('#0A1219'))
        p.setBrush(QBrush(bg))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRect(0, 0, w, h), 16, 16)

        # Border
        p.setPen(QPen(QColor('#1F3352'), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRect(1, 1, w-2, h-2), 15, 15)

        # Gold top accent line
        grd = QLinearGradient(0, 0, w, 0)
        grd.setColorAt(0,   QColor(0, 0, 0, 0))
        grd.setColorAt(0.3, QColor('#F0A500'))
        grd.setColorAt(0.7, QColor('#FFB830'))
        grd.setColorAt(1,   QColor(0, 0, 0, 0))
        p.setBrush(QBrush(grd)); p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRect(0, 0, w, 3), 2, 2)

        # Subtle glow
        glow = QRadialGradient(w//2, h//2 - 20, 200)
        glow.setColorAt(0.0, QColor(240, 165, 0, 18))
        glow.setColorAt(1.0, QColor(240, 165, 0,  0))
        p.setBrush(QBrush(glow)); p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRect(0, 0, w, h), 16, 16)

        # Logo "MBT"
        lf = QFont('Segoe UI', 54, QFont.Black)
        lf.setLetterSpacing(QFont.AbsoluteSpacing, 10)
        p.setFont(lf)
        # Shadow
        p.setPen(QColor(0, 0, 0, 60))
        p.drawText(QRect(2, 42, w, 80), Qt.AlignHCenter, 'MBT')
        # Gold
        p.setPen(QColor('#F0A500'))
        p.drawText(QRect(0, 40, w, 80), Qt.AlignHCenter, 'MBT')

        # Tagline
        tf = QFont('Segoe UI', 11); tf.setLetterSpacing(QFont.AbsoluteSpacing, 5)
        p.setFont(tf); p.setPen(QColor('#3E5C78'))
        p.drawText(QRect(0, 122, w, 22), Qt.AlignHCenter, 'POINT  OF  SALE')

        # Brand
        bf = QFont('Segoe UI', 10, QFont.Bold)
        p.setFont(bf); p.setPen(QColor('#F0A500CC'))
        p.drawText(QRect(0, 152, w, 20), Qt.AlignHCenter, 'MugoByte Technologies')
        wf = QFont('Segoe UI', 9)
        p.setFont(wf); p.setPen(QColor('#3E5C78'))
        p.drawText(QRect(0, 172, w, 18), Qt.AlignHCenter, 'mugobyte.com')

        # Progress track
        bx, by, bw, bh2 = 50, 234, w - 100, 5
        p.setBrush(QColor('#1F3352')); p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRect(bx, by, bw, bh2), 3, 3)
        fw = int(bw * min(self._progress, 100) / 100)
        if fw > 0:
            fg = QLinearGradient(bx, 0, bx + fw, 0)
            fg.setColorAt(0, QColor('#F0A500'))
            fg.setColorAt(1, QColor('#FFB830'))
            p.setBrush(QBrush(fg))
            p.drawRoundedRect(QRect(bx, by, fw, bh2), 3, 3)

        # Status
        sf = QFont('Segoe UI', 10)
        p.setFont(sf); p.setPen(QColor('#7A9AB8'))
        dots = '.' * (self._dots % 4)
        p.drawText(QRect(0, by + 14, w, 20), Qt.AlignHCenter,
                   self._status.rstrip('.') + dots)

        # Version
        vf = QFont('Segoe UI', 8)
        p.setFont(vf); p.setPen(QColor('#263647'))
        p.drawText(QRect(0, h - 28, w, 20), Qt.AlignHCenter,
                   'v2.0  ·  © 2025 MugoByte Technologies')
        p.end()

    def set_status(self, msg, progress=None):
        self._status = msg
        if progress is not None:
            self._progress = progress
        self.update(); QApplication.processEvents()

    def set_progress(self, v):
        self._progress = v; self.update(); QApplication.processEvents()

    def _tick(self):
        self._dots += 1; self.update()

    def finish_and_close(self, delay=400):
        self._dot_t.stop()
        self._progress = 100; self._status = 'Ready'
        self.update(); QApplication.processEvents()
        fade = QPropertyAnimation(self, b'windowOpacity')
        fade.setDuration(480)
        fade.setStartValue(1.0); fade.setEndValue(0.0)
        fade.setEasingCurve(QEasingCurve.InCubic)
        fade.finished.connect(self.close)
        QTimer.singleShot(delay, fade.start)
        self._fade_out = fade
