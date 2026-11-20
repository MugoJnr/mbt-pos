"""Product photograph checks and the till's photo tile."""
from __future__ import annotations

import os
import secrets

from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtGui import QColor, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import QFileDialog, QFrame, QSizePolicy

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_EDGE = 8000
DISPLAY_EDGE = 1600
THUMB_EDGE = 256
_IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp'}


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


def unsafe_filename(name: str) -> bool:
    """True when a client file name could escape the image folder."""
    raw = str(name or '')
    if not raw or raw in ('.', '..') or '\x00' in raw or '..' in raw:
        return True
    if '/' in raw or '\\' in raw or raw.startswith('.'):
        return True
    return os.path.basename(raw) != raw


def _clean_name(path: str) -> str:
    raw = str(path or '').split('?', 1)[0].replace('\\', '/')
    return os.path.basename(raw)


def thumbnail_filename(image_path: str) -> str:
    """Card file that sits beside the stored photograph."""
    base = _clean_name(image_path)
    if not base or unsafe_filename(base):
        return ''
    root, ext = os.path.splitext(base)
    if ext.lower() not in _IMAGE_EXTS:
        return ''
    if root.endswith('.thumb'):
        return base
    suffix = '.jpg' if ext.lower() == '.jpeg' else ext.lower()
    return f'{root}.thumb{suffix}'


def display_name_for_thumb(thumb_name: str) -> str:
    base = _clean_name(thumb_name)
    if '.thumb.' not in base:
        return ''
    return base.replace('.thumb.', '.', 1)


def _encode(image, edge: int, ext: str) -> bytes:
    import io
    from PIL import Image
    copy = image.copy()
    resampling = getattr(getattr(Image, 'Resampling', Image), 'LANCZOS')
    copy.thumbnail((edge, edge), resampling)
    if ext == '.png':
        if copy.mode not in ('RGB', 'RGBA'):
            copy = copy.convert('RGBA')
        kind, params = 'PNG', {'optimize': True}
    elif ext == '.webp':
        if copy.mode not in ('RGB', 'RGBA'):
            copy = copy.convert('RGBA')
        kind, params = 'WEBP', {'quality': 80, 'method': 4}
    else:
        if copy.mode != 'RGB':
            copy = copy.convert('RGB')
        kind, params = 'JPEG', {'quality': 85, 'optimize': True}
    buf = io.BytesIO()
    copy.save(buf, format=kind, **params)
    return buf.getvalue()


def prepare_product_image(data: bytes) -> dict:
    """Check the bytes are a real picture and build a display copy plus a thumbnail.

    The caller stores those bytes under an app-chosen name. The original upload
    path is never kept, and the bytes are never executed.
    """
    error = image_error(data)
    if error:
        return {'error': error}
    ext = sniff_image(data)
    try:
        import io
        from PIL import Image
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            width, height = image.size
            if width < 1 or height < 1 or width > MAX_EDGE or height > MAX_EDGE:
                return {
                    'error': 'That photograph is an unusual size. Use a picture under 8000 pixels on each side.',
                }
            display = _encode(image, DISPLAY_EDGE, ext)
            thumb = _encode(image, THUMB_EDGE, ext)
    except Exception:
        return {'error': 'That file could not be shown. Use a real JPEG, PNG, or WebP photograph.'}
    if not display or not thumb:
        return {'error': 'That file could not be shown. Use a real JPEG, PNG, or WebP photograph.'}
    return {
        'ext': ext, 'display': display, 'thumb': thumb,
        'width': width, 'height': height,
    }


def _product_image_names(folder: str, product_id: int) -> list:
    prefix = f'product-{int(product_id)}'
    if not os.path.isdir(folder):
        return []
    found = []
    for name in os.listdir(folder):
        if name.startswith(prefix + '.') or name.startswith(prefix + '-'):
            found.append(name)
    return found


def store_image_bytes(folder: str, product_id: int, data: bytes) -> dict:
    """Write a stable display file and a thumbnail. Old files for this product are removed."""
    prepared = prepare_product_image(data)
    if prepared.get('error'):
        return prepared
    os.makedirs(folder, exist_ok=True)
    token = secrets.token_hex(4)
    filename = f'product-{int(product_id)}-{token}{prepared["ext"]}'
    thumb = thumbnail_filename(filename)
    display_path = os.path.join(folder, filename)
    thumb_path = os.path.join(folder, thumb)
    try:
        with open(display_path, 'wb') as handle:
            handle.write(prepared['display'])
        with open(thumb_path, 'wb') as handle:
            handle.write(prepared['thumb'])
    except OSError:
        for path in (display_path, thumb_path):
            try:
                os.remove(path)
            except OSError:
                pass
        return {'error': 'The photograph could not be saved.'}
    return {
        'filename': filename,
        'thumb': thumb,
        'width': prepared['width'],
        'height': prepared['height'],
    }


def remove_product_images(folder: str, product_id: int) -> None:
    for name in _product_image_names(folder, product_id):
        try:
            os.remove(os.path.join(folder, name))
        except OSError:
            pass


def ensure_thumbnail_file(folder: str, thumb_name: str) -> str:
    """Build a missing thumbnail from the stored photograph. Returns the thumb path or ''."""
    thumb_name = _clean_name(thumb_name)
    if not thumb_name or unsafe_filename(thumb_name):
        return ''
    thumb_path = os.path.join(folder, thumb_name)
    if os.path.isfile(thumb_path):
        return thumb_path
    source_name = display_name_for_thumb(thumb_name)
    source = os.path.join(folder, source_name) if source_name else ''
    if not source or not os.path.isfile(source):
        return ''
    try:
        with open(source, 'rb') as handle:
            data = handle.read(MAX_IMAGE_BYTES + 1)
        prepared = prepare_product_image(data)
    except OSError:
        return ''
    if prepared.get('error'):
        return ''
    try:
        with open(thumb_path, 'wb') as handle:
            handle.write(prepared['thumb'])
    except OSError:
        return ''
    return thumb_path if os.path.isfile(thumb_path) else ''


def resolve_product_image(path: str, prefer_thumb: bool = False) -> str:
    """Find a stored product photograph. The database keeps the file name only."""
    raw = (path or '').strip()
    if not raw:
        return ''
    base = _clean_name(raw)
    if unsafe_filename(base):
        return ''
    candidate = raw if os.path.isfile(raw) else ''
    folder = ''
    if not candidate:
        try:
            from mbt_paths import get_data_dir
            folder = os.path.join(get_data_dir(), 'product-images')
            candidate = os.path.join(folder, base)
        except Exception:
            return ''
        if not os.path.isfile(candidate):
            return ''
    else:
        folder = os.path.dirname(candidate)
    if not prefer_thumb:
        return candidate
    thumb_name = thumbnail_filename(base)
    if not thumb_name:
        return candidate
    thumb_path = os.path.join(folder, thumb_name)
    if os.path.isfile(thumb_path):
        return thumb_path
    built = ensure_thumbnail_file(folder, thumb_name)
    return built or candidate


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
        existing = resolve_product_image(image_path, prefer_thumb=self._size <= 64)
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
