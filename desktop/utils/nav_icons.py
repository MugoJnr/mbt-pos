"""Painted nav / section icons — no emoji, no ASCII glyph fallbacks."""
from __future__ import annotations

from PyQt5.QtCore import Qt, QRectF, QPointF
from PyQt5.QtGui import QIcon, QPixmap, QPainter, QColor, QPen, QBrush, QPainterPath
from PyQt5.QtWidgets import QApplication

from desktop.utils.theme import C


def _color(hex_color: str, alpha: int = 255) -> QColor:
    c = QColor(hex_color or '#FBBF24')
    c.setAlpha(int(alpha))
    return c


def _paint_pixmap(size: int, draw_fn, accent: str | None = None) -> QPixmap:
    dpr = 1.0
    try:
        app = QApplication.instance()
        if app is not None:
            dpr = float(app.devicePixelRatio() or 1.0)
    except Exception:
        dpr = 1.0
    px = int(size * max(1.0, dpr))
    pm = QPixmap(px, px)
    pm.fill(Qt.transparent)
    pm.setDevicePixelRatio(max(1.0, dpr))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    gold = _color(accent or C.get('gold', '#FBBF24'))
    muted = _color(C.get('text2', '#B4C2D6'))
    draw_fn(p, float(size), gold, muted)
    p.end()
    return pm


def _paint_base(size: int, draw_fn, accent: str | None = None) -> QIcon:
    return QIcon(_paint_pixmap(size, draw_fn, accent=accent))


def icon_dashboard(size=18) -> QIcon:
    def draw(p, s, gold, muted):
        m = s * 0.18
        gap = s * 0.08
        cell = (s - 2 * m - gap) / 2
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(gold))
        p.drawRoundedRect(QRectF(m, m, cell, cell), 2, 2)
        p.setBrush(QBrush(muted))
        p.drawRoundedRect(QRectF(m + cell + gap, m, cell, cell), 2, 2)
        p.drawRoundedRect(QRectF(m, m + cell + gap, cell, cell), 2, 2)
        p.setBrush(QBrush(gold))
        p.drawRoundedRect(QRectF(m + cell + gap, m + cell + gap, cell, cell), 2, 2)
    return _paint_base(size, draw)


def icon_sales(size=18) -> QIcon:
    def draw(p, s, gold, muted):
        p.setPen(QPen(gold, max(1.4, s * 0.1), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        # cart basket
        path = QPainterPath()
        path.moveTo(s * 0.22, s * 0.35)
        path.lineTo(s * 0.32, s * 0.35)
        path.lineTo(s * 0.40, s * 0.72)
        path.lineTo(s * 0.78, s * 0.72)
        path.lineTo(s * 0.86, s * 0.42)
        path.lineTo(s * 0.36, s * 0.42)
        p.drawPath(path)
        p.setBrush(QBrush(gold))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(s * 0.46, s * 0.82), s * 0.07, s * 0.07)
        p.drawEllipse(QPointF(s * 0.70, s * 0.82), s * 0.07, s * 0.07)
    return _paint_base(size, draw)


def icon_inventory(size=18) -> QIcon:
    def draw(p, s, gold, muted):
        p.setPen(QPen(gold, max(1.3, s * 0.09), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(s * 0.22, s * 0.28, s * 0.56, s * 0.48), 2.5, 2.5)
        p.drawLine(QPointF(s * 0.22, s * 0.44), QPointF(s * 0.78, s * 0.44))
        p.drawLine(QPointF(s * 0.50, s * 0.28), QPointF(s * 0.50, s * 0.76))
    return _paint_base(size, draw)


def icon_consumption(size=18) -> QIcon:
    def draw(p, s, gold, muted):
        p.setPen(QPen(gold, max(1.3, s * 0.09), Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(s * 0.22, s * 0.22, s * 0.56, s * 0.56))
        p.drawLine(QPointF(s * 0.50, s * 0.34), QPointF(s * 0.50, s * 0.54))
        p.drawLine(QPointF(s * 0.50, s * 0.54), QPointF(s * 0.62, s * 0.62))
    return _paint_base(size, draw)


def icon_debt(size=18) -> QIcon:
    def draw(p, s, gold, muted):
        p.setPen(QPen(gold, max(1.3, s * 0.09), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(s * 0.24, s * 0.30, s * 0.52, s * 0.42), 3, 3)
        p.drawArc(QRectF(s * 0.36, s * 0.20, s * 0.28, s * 0.22), 0 * 16, 180 * 16)
    return _paint_base(size, draw)


def icon_finance(size=18) -> QIcon:
    def draw(p, s, gold, muted):
        p.setPen(QPen(gold, max(1.4, s * 0.1), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        pts = [
            QPointF(s * 0.22, s * 0.68),
            QPointF(s * 0.38, s * 0.50),
            QPointF(s * 0.52, s * 0.58),
            QPointF(s * 0.78, s * 0.28),
        ]
        for i in range(1, len(pts)):
            p.drawLine(pts[i - 1], pts[i])
        p.setBrush(QBrush(gold))
        p.setPen(Qt.NoPen)
        for pt in pts:
            p.drawEllipse(pt, s * 0.055, s * 0.055)
    return _paint_base(size, draw)


def icon_reports(size=18) -> QIcon:
    def draw(p, s, gold, muted):
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(muted))
        p.drawRoundedRect(QRectF(s * 0.24, s * 0.52, s * 0.14, s * 0.24), 1.5, 1.5)
        p.setBrush(QBrush(gold))
        p.drawRoundedRect(QRectF(s * 0.43, s * 0.36, s * 0.14, s * 0.40), 1.5, 1.5)
        p.setBrush(QBrush(muted))
        p.drawRoundedRect(QRectF(s * 0.62, s * 0.28, s * 0.14, s * 0.48), 1.5, 1.5)
    return _paint_base(size, draw)


def icon_notes(size=18) -> QIcon:
    def draw(p, s, gold, muted):
        p.setPen(QPen(gold, max(1.3, s * 0.09), Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(s * 0.28, s * 0.20, s * 0.44, s * 0.60), 2.5, 2.5)
        p.drawLine(QPointF(s * 0.36, s * 0.38), QPointF(s * 0.64, s * 0.38))
        p.drawLine(QPointF(s * 0.36, s * 0.50), QPointF(s * 0.64, s * 0.50))
        p.drawLine(QPointF(s * 0.36, s * 0.62), QPointF(s * 0.56, s * 0.62))
    return _paint_base(size, draw)


def icon_ai(size=18) -> QIcon:
    def draw(p, s, gold, muted):
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(gold))
        # four-point sparkle
        cx, cy = s * 0.50, s * 0.50
        path = QPainterPath()
        path.moveTo(cx, cy - s * 0.34)
        path.quadTo(cx + s * 0.04, cy - s * 0.04, cx + s * 0.34, cy)
        path.quadTo(cx + s * 0.04, cy + s * 0.04, cx, cy + s * 0.34)
        path.quadTo(cx - s * 0.04, cy + s * 0.04, cx - s * 0.34, cy)
        path.quadTo(cx - s * 0.04, cy - s * 0.04, cx, cy - s * 0.34)
        p.drawPath(path)
    return _paint_base(size, draw)


def icon_users(size=18) -> QIcon:
    def draw(p, s, gold, muted):
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(gold))
        p.drawEllipse(QPointF(s * 0.50, s * 0.34), s * 0.14, s * 0.14)
        path = QPainterPath()
        path.addEllipse(QRectF(s * 0.26, s * 0.52, s * 0.48, s * 0.30))
        p.drawPath(path)
    return _paint_base(size, draw)


def icon_settings(size=18) -> QIcon:
    def draw(p, s, gold, muted):
        p.setPen(QPen(gold, max(1.3, s * 0.09), Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(s * 0.30, s * 0.30, s * 0.40, s * 0.40))
        p.drawEllipse(QRectF(s * 0.42, s * 0.42, s * 0.16, s * 0.16))
        for ang in range(0, 360, 45):
            from math import cos, sin, radians
            r0, r1 = s * 0.28, s * 0.42
            a = radians(ang)
            p.drawLine(
                QPointF(s * 0.50 + r0 * cos(a), s * 0.50 + r0 * sin(a)),
                QPointF(s * 0.50 + r1 * cos(a), s * 0.50 + r1 * sin(a)),
            )
    return _paint_base(size, draw)


def icon_security(size=18) -> QIcon:
    def draw(p, s, gold, muted):
        p.setPen(QPen(gold, max(1.3, s * 0.09), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        path = QPainterPath()
        path.moveTo(s * 0.50, s * 0.18)
        path.lineTo(s * 0.78, s * 0.30)
        path.lineTo(s * 0.78, s * 0.52)
        path.quadTo(s * 0.78, s * 0.72, s * 0.50, s * 0.84)
        path.quadTo(s * 0.22, s * 0.72, s * 0.22, s * 0.52)
        path.lineTo(s * 0.22, s * 0.30)
        path.closeSubpath()
        p.drawPath(path)
    return _paint_base(size, draw)


def icon_license(size=18) -> QIcon:
    def draw(p, s, gold, muted):
        p.setPen(QPen(gold, max(1.3, s * 0.09), Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(s * 0.28, s * 0.24, s * 0.44, s * 0.52), 2.5, 2.5)
        p.setBrush(QBrush(gold))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(s * 0.50, s * 0.44), s * 0.08, s * 0.08)
        p.drawRoundedRect(QRectF(s * 0.42, s * 0.52, s * 0.16, s * 0.12), 1, 1)
    return _paint_base(size, draw)


def icon_diagnostics(size=18) -> QIcon:
    def draw(p, s, gold, muted):
        p.setPen(QPen(gold, max(1.3, s * 0.09), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(s * 0.22, s * 0.22, s * 0.56, s * 0.56))
        p.drawLine(QPointF(s * 0.50, s * 0.34), QPointF(s * 0.50, s * 0.52))
        p.setBrush(QBrush(gold))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(s * 0.50, s * 0.62), s * 0.05, s * 0.05)
    return _paint_base(size, draw)


NAV_ICON_BUILDERS = {
    'dashboard': icon_dashboard,
    'sales': icon_sales,
    'inventory': icon_inventory,
    'consumption': icon_consumption,
    'debt': icon_debt,
    'accounting': icon_finance,
    'reports': icon_reports,
    'notes': icon_notes,
    'ai_ops': icon_ai,
    'admin': icon_users,
    'settings': icon_settings,
    'security': icon_security,
    'license': icon_license,
    'diagnostics': icon_diagnostics,
}


def nav_icon(tid: str, size: int = 18) -> QIcon:
    builder = NAV_ICON_BUILDERS.get(tid) or icon_dashboard
    return builder(size)


def section_icon_for_title(title: str, size: int = 18) -> QIcon:
    t = (title or '').lower()
    if 'receipt' in t or 'print' in t:
        return icon_notes(size)
    if 'shop' in t or 'business' in t:
        return icon_sales(size)
    if 'm-pesa' in t or 'payment' in t:
        return icon_debt(size)
    if 'sync' in t or 'cloud' in t or 'tunnel' in t or 'cloudflare' in t:
        return icon_diagnostics(size)
    if 'workflow' in t or 'checkout' in t or 'after sale' in t:
        return icon_sales(size)
    if 'visual' in t or 'categor' in t:
        return icon_inventory(size)
    if 'security' in t or 'pin' in t:
        return icon_security(size)
    if 'audio' in t:
        return icon_notes(size)
    if 'telegram' in t or 'notify' in t:
        return icon_ai(size)
    if 'void' in t or 'edit' in t:
        return icon_diagnostics(size)
    return icon_settings(size)


# ── Action / chrome icons (header buttons, toolbars) ──────────────────────────

def icon_refresh(size=16, accent=None) -> QIcon:
    def draw(p, s, gold, muted):
        pen = QPen(gold, max(1.4, s * 0.11), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawArc(QRectF(s * 0.18, s * 0.18, s * 0.64, s * 0.64), 40 * 16, 280 * 16)
        # arrow head
        p.setBrush(QBrush(gold))
        p.setPen(Qt.NoPen)
        tip = QPointF(s * 0.72, s * 0.22)
        path = QPainterPath()
        path.moveTo(tip)
        path.lineTo(tip + QPointF(-s * 0.16, s * 0.04))
        path.lineTo(tip + QPointF(-s * 0.02, s * 0.18))
        path.closeSubpath()
        p.drawPath(path)
    return _paint_base(size, draw, accent=accent)


def icon_sun(size=16, accent=None) -> QIcon:
    def draw(p, s, gold, muted):
        p.setPen(QPen(gold, max(1.2, s * 0.09), Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(s * 0.34, s * 0.34, s * 0.32, s * 0.32))
        from math import cos, sin, radians
        for ang in range(0, 360, 45):
            a = radians(ang)
            p.drawLine(
                QPointF(s * 0.50 + s * 0.22 * cos(a), s * 0.50 + s * 0.22 * sin(a)),
                QPointF(s * 0.50 + s * 0.36 * cos(a), s * 0.50 + s * 0.36 * sin(a)),
            )
    return _paint_base(size, draw, accent=accent)


def icon_moon(size=16, accent=None) -> QIcon:
    def draw(p, s, gold, muted):
        outer = QPainterPath()
        outer.addEllipse(QPointF(s * 0.50, s * 0.50), s * 0.30, s * 0.30)
        cut = QPainterPath()
        cut.addEllipse(QPointF(s * 0.64, s * 0.40), s * 0.24, s * 0.24)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(gold))
        p.drawPath(outer.subtracted(cut))
    return _paint_base(size, draw, accent=accent)


def icon_online(size=12, accent=None) -> QIcon:
    def draw(p, s, gold, muted):
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(gold))
        p.drawEllipse(QPointF(s * 0.50, s * 0.50), s * 0.28, s * 0.28)
    return _paint_base(size, draw, accent=accent or C.get('ok', '#22C55E'))


def icon_save(size=16, accent=None) -> QIcon:
    def draw(p, s, gold, muted):
        p.setPen(QPen(gold, max(1.3, s * 0.09), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        path = QPainterPath()
        path.moveTo(s * 0.22, s * 0.22)
        path.lineTo(s * 0.62, s * 0.22)
        path.lineTo(s * 0.78, s * 0.38)
        path.lineTo(s * 0.78, s * 0.78)
        path.lineTo(s * 0.22, s * 0.78)
        path.closeSubpath()
        p.drawPath(path)
        p.drawRect(QRectF(s * 0.34, s * 0.22, s * 0.28, s * 0.18))
        p.drawRoundedRect(QRectF(s * 0.34, s * 0.52, s * 0.32, s * 0.26), 1.5, 1.5)
    return _paint_base(size, draw, accent=accent)


def icon_export(size=16, accent=None) -> QIcon:
    def draw(p, s, gold, muted):
        p.setPen(QPen(gold, max(1.3, s * 0.09), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        p.drawLine(QPointF(s * 0.50, s * 0.18), QPointF(s * 0.50, s * 0.58))
        p.drawLine(QPointF(s * 0.50, s * 0.18), QPointF(s * 0.36, s * 0.34))
        p.drawLine(QPointF(s * 0.50, s * 0.18), QPointF(s * 0.64, s * 0.34))
        path = QPainterPath()
        path.moveTo(s * 0.24, s * 0.52)
        path.lineTo(s * 0.24, s * 0.78)
        path.lineTo(s * 0.76, s * 0.78)
        path.lineTo(s * 0.76, s * 0.52)
        p.drawPath(path)
    return _paint_base(size, draw, accent=accent)


def icon_email(size=16, accent=None) -> QIcon:
    def draw(p, s, gold, muted):
        p.setPen(QPen(gold, max(1.3, s * 0.09), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(s * 0.18, s * 0.28, s * 0.64, s * 0.46), 2, 2)
        p.drawLine(QPointF(s * 0.18, s * 0.34), QPointF(s * 0.50, s * 0.54))
        p.drawLine(QPointF(s * 0.82, s * 0.34), QPointF(s * 0.50, s * 0.54))
    return _paint_base(size, draw, accent=accent)


def icon_live(size=16, accent=None) -> QIcon:
    def draw(p, s, gold, muted):
        p.setPen(QPen(gold, max(1.3, s * 0.09), Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(s * 0.22, s * 0.28, s * 0.56, s * 0.40), 2, 2)
        p.drawLine(QPointF(s * 0.38, s * 0.72), QPointF(s * 0.62, s * 0.72))
        p.setBrush(QBrush(gold))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(s * 0.50, s * 0.48), s * 0.08, s * 0.08)
    return _paint_base(size, draw, accent=accent)


def icon_gear(size=16, accent=None) -> QIcon:
    def draw(p, s, gold, muted):
        p.setPen(QPen(gold, max(1.3, s * 0.09), Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(s * 0.30, s * 0.30, s * 0.40, s * 0.40))
        p.drawEllipse(QRectF(s * 0.42, s * 0.42, s * 0.16, s * 0.16))
        from math import cos, sin, radians
        for ang in range(0, 360, 45):
            r0, r1 = s * 0.28, s * 0.42
            a = radians(ang)
            p.drawLine(
                QPointF(s * 0.50 + r0 * cos(a), s * 0.50 + r0 * sin(a)),
                QPointF(s * 0.50 + r1 * cos(a), s * 0.50 + r1 * sin(a)),
            )
    return _paint_base(size, draw, accent=accent)


def icon_plus(size=16, accent=None) -> QIcon:
    def draw(p, s, gold, muted):
        p.setPen(QPen(gold, max(1.6, s * 0.12), Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(s * 0.50, s * 0.24), QPointF(s * 0.50, s * 0.76))
        p.drawLine(QPointF(s * 0.24, s * 0.50), QPointF(s * 0.76, s * 0.50))
    return _paint_base(size, draw, accent=accent)


def icon_warning(size=16, accent=None) -> QIcon:
    def draw(p, s, gold, muted):
        p.setPen(QPen(gold, max(1.3, s * 0.09), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        path = QPainterPath()
        path.moveTo(s * 0.50, s * 0.16)
        path.lineTo(s * 0.84, s * 0.78)
        path.lineTo(s * 0.16, s * 0.78)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(s * 0.50, s * 0.36), QPointF(s * 0.50, s * 0.56))
        p.setBrush(QBrush(gold))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(s * 0.50, s * 0.66), s * 0.045, s * 0.045)
    return _paint_base(size, draw, accent=accent)


def icon_money(size=16, accent=None) -> QIcon:
    def draw(p, s, gold, muted):
        p.setPen(QPen(gold, max(1.3, s * 0.09), Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(s * 0.18, s * 0.18, s * 0.64, s * 0.64))
        p.setFont(p.font())
        # KES-style mark via strokes
        p.drawLine(QPointF(s * 0.50, s * 0.32), QPointF(s * 0.50, s * 0.68))
        p.drawLine(QPointF(s * 0.36, s * 0.40), QPointF(s * 0.64, s * 0.40))
        p.drawLine(QPointF(s * 0.36, s * 0.60), QPointF(s * 0.64, s * 0.60))
    return _paint_base(size, draw, accent=accent)


def icon_trend_up(size=16, accent=None) -> QIcon:
    def draw(p, s, gold, muted):
        p.setPen(QPen(gold, max(1.4, s * 0.1), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        p.drawLine(QPointF(s * 0.22, s * 0.68), QPointF(s * 0.42, s * 0.48))
        p.drawLine(QPointF(s * 0.42, s * 0.48), QPointF(s * 0.54, s * 0.56))
        p.drawLine(QPointF(s * 0.54, s * 0.56), QPointF(s * 0.78, s * 0.28))
        p.drawLine(QPointF(s * 0.62, s * 0.28), QPointF(s * 0.78, s * 0.28))
        p.drawLine(QPointF(s * 0.78, s * 0.28), QPointF(s * 0.78, s * 0.44))
    return _paint_base(size, draw, accent=accent)


def icon_receipt(size=16, accent=None) -> QIcon:
    def draw(p, s, gold, muted):
        p.setPen(QPen(gold, max(1.3, s * 0.09), Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        path = QPainterPath()
        path.moveTo(s * 0.30, s * 0.16)
        path.lineTo(s * 0.70, s * 0.16)
        path.lineTo(s * 0.70, s * 0.84)
        path.lineTo(s * 0.62, s * 0.76)
        path.lineTo(s * 0.54, s * 0.84)
        path.lineTo(s * 0.46, s * 0.76)
        path.lineTo(s * 0.38, s * 0.84)
        path.lineTo(s * 0.30, s * 0.76)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(s * 0.38, s * 0.34), QPointF(s * 0.62, s * 0.34))
        p.drawLine(QPointF(s * 0.38, s * 0.46), QPointF(s * 0.62, s * 0.46))
        p.drawLine(QPointF(s * 0.38, s * 0.58), QPointF(s * 0.54, s * 0.58))
    return _paint_base(size, draw, accent=accent)


def icon_box(size=16, accent=None) -> QIcon:
    def draw(p, s, gold, muted):
        p.setPen(QPen(gold, max(1.3, s * 0.09), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(s * 0.22, s * 0.28, s * 0.56, s * 0.48), 2.5, 2.5)
        p.drawLine(QPointF(s * 0.22, s * 0.44), QPointF(s * 0.78, s * 0.44))
        p.drawLine(QPointF(s * 0.50, s * 0.28), QPointF(s * 0.50, s * 0.76))
    return _paint_base(size, draw, accent=accent)


def icon_wallet(size=16, accent=None) -> QIcon:
    def draw(p, s, gold, muted):
        p.setPen(QPen(gold, max(1.3, s * 0.09), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(s * 0.18, s * 0.30, s * 0.64, s * 0.44), 3, 3)
        p.drawLine(QPointF(s * 0.18, s * 0.42), QPointF(s * 0.82, s * 0.42))
        p.setBrush(QBrush(gold))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(s * 0.66, s * 0.56), s * 0.07, s * 0.07)
    return _paint_base(size, draw, accent=accent)


def icon_users_kpi(size=16, accent=None) -> QIcon:
    def draw(p, s, gold, muted):
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(gold))
        p.drawEllipse(QPointF(s * 0.38, s * 0.34), s * 0.12, s * 0.12)
        p.drawEllipse(QPointF(s * 0.62, s * 0.34), s * 0.10, s * 0.10)
        path = QPainterPath()
        path.addEllipse(QRectF(s * 0.18, s * 0.52, s * 0.40, s * 0.28))
        p.drawPath(path)
        p.setBrush(QBrush(muted))
        path2 = QPainterPath()
        path2.addEllipse(QRectF(s * 0.48, s * 0.54, s * 0.34, s * 0.24))
        p.drawPath(path2)
    return _paint_base(size, draw, accent=accent)


# Legacy ASCII glyph → semantic key (screenshots previously showed # * ^ ! = @ +)
_GLYPH_TO_KPI = {
    '#': 'count',
    '*': 'money',
    '^': 'avg',
    '!': 'alert',
    '=': 'debt',
    '+': 'plus',
    '@': 'users',
}

KPI_ICON_BUILDERS = {
    'count': icon_receipt,
    'sales': icon_receipt,
    'money': icon_money,
    'revenue': icon_money,
    'avg': icon_trend_up,
    'alert': icon_warning,
    'low_stock': icon_warning,
    'debt': icon_wallet,
    'plus': icon_plus,
    'collected': icon_plus,
    'users': icon_users_kpi,
    'customers': icon_users_kpi,
    'box': icon_box,
    'stock': icon_box,
    'consumption': icon_consumption,
    'reports': icon_reports,
    'finance': icon_finance,
}


def resolve_kpi_key(icon: str) -> str:
    raw = (icon or '').strip()
    if raw in _GLYPH_TO_KPI:
        return _GLYPH_TO_KPI[raw]
    key = raw.lower().replace(' ', '_')
    if key in KPI_ICON_BUILDERS:
        return key
    return 'count'


def kpi_icon(icon_or_key: str, size: int = 22, accent: str | None = None) -> QIcon:
    key = resolve_kpi_key(icon_or_key)
    builder = KPI_ICON_BUILDERS.get(key) or icon_receipt
    return builder(size, accent=accent)


def kpi_pixmap(icon_or_key: str, size: int = 22, accent: str | None = None) -> QPixmap:
    return kpi_icon(icon_or_key, size=size, accent=accent).pixmap(size, size)


ACTION_ICON_BUILDERS = {
    'refresh': icon_refresh,
    'sun': icon_sun,
    'moon': icon_moon,
    'online': icon_online,
    'save': icon_save,
    'export': icon_export,
    'email': icon_email,
    'live': icon_live,
    'settings': icon_settings,
    'gear': icon_settings,
    'plus': icon_plus,
    'warning': icon_warning,
    'ai': icon_ai,
    'sparkle': icon_ai,
}


def action_icon(name: str, size: int = 16, accent: str | None = None) -> QIcon:
    key = (name or '').strip().lower()
    builder = ACTION_ICON_BUILDERS.get(key) or icon_settings
    try:
        return builder(size, accent=accent)
    except TypeError:
        return builder(size)


def apply_button_icon(btn, name: str, size: int = 16, accent: str | None = None):
    """Attach a painted action icon — never rely on emoji / tofu glyphs in the label."""
    from PyQt5.QtCore import QSize
    btn.setIcon(action_icon(name, size=size, accent=accent))
    btn.setIconSize(QSize(size, size))
    return btn
