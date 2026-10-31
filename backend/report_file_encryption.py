"""File-level encryption for sensitive report downloads.

PDF uses PDF standard AES-256 (pypdf).
Excel uses ECMA-376 agile encryption (msoffcrypto), which Excel opens with a password.
CSV has no file password of its own, so the CSV is stored inside an AES-256 ZIP.

Worksheet protection is not used here. A lost password cannot be recovered.
"""
from __future__ import annotations

import os
import re
import secrets
from io import BytesIO

MIN_EXPORT_PASSWORD = 10
MAX_EXPORT_PASSWORD = 128

_OLE_MAGIC = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'


class ExportPasswordError(ValueError):
    """The user still needs to choose a usable export password."""


def check_export_password(password: str, confirm: str | None = None) -> str:
    """Return the password when it is long enough and the confirmation matches.

    The value is not written anywhere by this function.
    """
    pw = '' if password is None else str(password)
    if confirm is not None and pw != ('' if confirm is None else str(confirm)):
        raise ExportPasswordError('The passwords do not match.')
    if not pw or not pw.strip():
        raise ExportPasswordError('Enter a password. An empty password is not accepted.')
    if pw != pw.strip():
        raise ExportPasswordError('Do not start or end the password with a space.')
    if len(pw) < MIN_EXPORT_PASSWORD:
        raise ExportPasswordError(
            f'Use at least {MIN_EXPORT_PASSWORD} characters. A short PIN is not enough.'
        )
    if len(pw) > MAX_EXPORT_PASSWORD:
        raise ExportPasswordError(
            f'Use at most {MAX_EXPORT_PASSWORD} characters.'
        )
    return pw


def generate_export_password() -> str:
    """A passphrase the user can read and copy. It is not derived from a login."""
    return secrets.token_urlsafe(12)


def safe_download_name(name: str, fallback: str) -> str:
    """A single file name. Rejects folders and parent-directory tricks."""
    base = os.path.basename(str(name or '')).strip()
    base = base.replace('\x00', '')
    if not base or base in ('.', '..') or not re.fullmatch(r'[A-Za-z0-9._ -]+', base):
        return fallback
    return base


def export_audit_text(*, report: str, fmt: str, period: str, ok: bool,
                      sha256: str = '') -> str:
    """Audit text. Callers must not pass a password into any argument."""
    digest = (sha256 or '')[:64]
    if len(digest) > 16 and not re.fullmatch(r'[0-9a-fA-F]+', digest):
        digest = ''
    return (
        f'report={report} format={fmt} period={period} '
        f'encrypted=aes-256 ok={1 if ok else 0} sha256={digest}'
    )


def seal_pdf(pdf_bytes: bytes, password: str) -> bytes:
    """Encrypt a PDF so a reader must supply the password. AES-256."""
    check_export_password(password, password)
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(BytesIO(pdf_bytes))
    if reader.is_encrypted:
        raise RuntimeError('The PDF was already encrypted.')
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.encrypt(password, algorithm='AES-256')
    out = BytesIO()
    writer.write(out)
    data = out.getvalue()
    if b'/Encrypt' not in data:
        raise RuntimeError('PDF encryption was not written into the file.')
    check = PdfReader(BytesIO(data))
    if not check.is_encrypted:
        raise RuntimeError('The PDF reader does not see this file as encrypted.')
    return data


def seal_xlsx_file(path: str, password: str) -> bytes:
    """Encrypt an OOXML workbook. The result is not a zip Excel can open without a password."""
    check_export_password(password, password)
    from msoffcrypto.format.ooxml import OOXMLFile

    with open(path, 'rb') as handle:
        office = OOXMLFile(handle)
        if office.is_encrypted():
            raise RuntimeError('The workbook was already encrypted.')
        buf = BytesIO()
        office.encrypt(password, buf)
    data = buf.getvalue()
    if not data.startswith(_OLE_MAGIC):
        raise RuntimeError('Workbook encryption did not produce an Office encrypted file.')
    return data


def seal_csv(csv_bytes: bytes, inner_name: str, password: str) -> bytes:
    """Put a CSV inside an AES-256 ZIP. The ZIP bytes are the download."""
    check_export_password(password, password)
    import pyzipper

    name = safe_download_name(inner_name, 'report.csv')
    if not name.lower().endswith('.csv'):
        name += '.csv'
    buf = BytesIO()
    with pyzipper.AESZipFile(
        buf, 'w', compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES,
    ) as archive:
        archive.setpassword(password.encode('utf-8'))
        archive.writestr(name, csv_bytes)
    data = buf.getvalue()
    if not data.startswith(b'PK'):
        raise RuntimeError('The encrypted CSV archive was not written.')
    return data


def pdf_opens(data: bytes, password: str) -> str:
    """Return the first page text when the password is correct. Raises otherwise."""
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(data))
    if not reader.is_encrypted:
        raise RuntimeError('PDF is not encrypted')
    result = reader.decrypt(password or '')
    if not result:
        raise RuntimeError('PDF password was rejected')
    return reader.pages[0].extract_text() or ''


def xlsx_opens(data: bytes, password: str) -> bytes:
    """Return the decrypted xlsx bytes, or raise when the password is wrong."""
    import msoffcrypto

    office = msoffcrypto.OfficeFile(BytesIO(data))
    if not office.is_encrypted():
        raise RuntimeError('Workbook is not encrypted')
    office.load_key(password=password)
    out = BytesIO()
    office.decrypt(out)
    return out.getvalue()


def csv_opens(data: bytes, password: str) -> bytes:
    """Return the first file inside an AES ZIP."""
    import pyzipper

    with pyzipper.AESZipFile(BytesIO(data)) as archive:
        archive.setpassword((password or '').encode('utf-8'))
        names = archive.namelist()
        if not names:
            raise RuntimeError('Archive is empty')
        return archive.read(names[0])
