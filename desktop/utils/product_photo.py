"""Product photograph checks and the till's photo tile."""
from __future__ import annotations

import os

from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtGui import QColor, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import QFileDialog, QFrame, QSizePolicy

MAX_IMAGE_BYTES = 8 * 1024 * 1024


def sniff_image(data: bytes) -> str:
    """Return '.jpg', '.png', '.webp', '.heic', or '' from the file contents."""
    if not data:
        return ''
    if data.startswith(b'\xff\xd8\xff'):
        return '.jpg'
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return '.png'
    if len(data) >= 12 and data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return '.webp'
    if len(data) >= 12 and data[4:8] == b'ftyp':
        brand = data[8:12]
        if brand in (b'heic', b'heix', b'hevc', b'mif1'):
            return '.heic'
    return ''


def image_error(data: bytes) -> str:
    if not data:
        return 'Choose a photograph.'
    if len(data) > MAX_IMAGE_BYTES:
        return 'That photograph is larger than 8 MB. Use a smaller file.'
    kind = sniff_image(data)
    if kind == '.heic':
        return 'HEIC photographs are not supported. Save the picture as JPEG, PNG, or WebP.'
    if not kind:
        return 'Use a JPEG, PNG, or WebP photograph.'
    return ''


def resolve_product_image(path: str) -> str:
    """Find a stored product photograph. The database keeps the file name only."""
    raw = (path or '').strip()
    if not raw:
        return ''
    if os.path.isfile(raw):
        return raw
    try:
        from mbt_paths import get_data_dir
        candidate = os.path.join(get_data_dir(), 'product-images', os.path.basename(raw))
    except Exception:
        return ''
    return candidate if os.path.isfile(candidate) else ''


class ProductPhotoTile(QFrame):
    """Clickable photograph. Empty tiles show a camera so the action is obvious."""

    def __init__(self, image_path: str = '', size: int = 88, parent=None):
        super().__init__(parent)
        self._size = int(size)
        self.setFixedSize(self._size, self._size)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._source = ''
        self._cleared = False
        self._pix = QPixmap()
        existing = resolve_product_image(image_path)
        if existing:
            self._pix = QPixmap(existing)
        self._refresh_tip()

    def photo_source(self) -> str:
        return self._source

    def photo_cleared(self) -> bool:
        return self._cleared and not self._source

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.isEnabled():
            self.choose()
        else:
            super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space) and self.isEnabled():
            self.choose()
            return
        super().keyPressEvent(event)

    def choose(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Product photograph', '',
            'Photographs (*.png *.jpg *.jpeg *.webp *.heic)',
        )
        if not path:
            return
        try:
            with open(path, 'rb') as handle:
                data = handle.read(MAX_IMAGE_BYTES + 1)
        except OSError:
            self._reject('That photograph could not be read.')
            return
        error = image_error(data)
        if error:
            self._reject(error)
            return
        pix = QPixmap(path)
        if pix.isNull():
            self._reject('That file could not be shown.')
            return
        self._source = path
        self._cleared = False
        self._pix = pix
        self._refresh_tip()
        self.update()

    def clear_photo(self):
        self._source = ''
        self._cleared = True
        self._pix = QPixmap()
        self._refresh_tip()
        self.update()

    def _reject(self, message: str):
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.warning(self, 'Photograph', message)

    def _refresh_tip(self):
        if self._pix.isNull():
            tip = 'Add photograph'
        else:
            tip = 'Change photograph'
        self.setToolTip(tip)
        self.setAccessibleName(tip)

    def paintEvent(self, _event):
        from desktop.utils.theme import C
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(1, 1, self.width() - 2, self.height() - 2)
        painter.setPen(QPen(QColor(C.get('gold', '#d4a017')), 1.5))
        painter.setBrush(QColor(C.get('card2', '#152033')))
        painter.drawRoundedRect(rect, 12, 12)
        if not self._pix.isNull():
            fitted = self._pix.scaled(
                int(rect.width()) - 8, int(rect.height()) - 8,
                Qt.KeepAspectRatio, Qt.SmoothTransformation,
            )
            painter.drawPixmap(
                int((self.width() - fitted.width()) / 2),
                int((self.height() - fitted.height()) / 2),
                fitted,
            )
            return
        self._paint_camera(painter, rect)

    def _paint_camera(self, painter: QPainter, rect: QRectF):
        from desktop.utils.theme import C
        gold = QColor(C.get('gold', '#d4a017'))
        painter.setPen(QPen(gold, 1.6))
        painter.setBrush(Qt.NoBrush)
        body = QRectF(rect.center().x() - 16, rect.center().y() - 8, 32, 22)
        painter.drawRoundedRect(body, 4, 4)
        painter.drawRoundedRect(QRectF(body.x() + 8, body.y() - 5, 10, 5), 1, 1)
        painter.drawEllipse(QRectF(body.center().x() - 5, body.center().y() - 5, 10, 10))
        painter.drawLine(
            int(body.right() + 4), int(body.center().y()),
            int(body.right() + 12), int(body.center().y()),
        )
        painter.drawLine(
            int(body.right() + 8), int(body.center().y() - 4),
            int(body.right() + 8), int(body.center().y() + 4),
        )
