"""Central ESC/POS command constants — no scattered magic bytes."""
from __future__ import annotations

ESC = b'\x1b'
GS = b'\x1d'
FS = b'\x1c'

# ESC @ — initialize printer
INIT = ESC + b'@'

# ESC a n — alignment (0 left, 1 center, 2 right)
ALIGN_LEFT = ESC + b'a\x00'
ALIGN_CENTER = ESC + b'a\x01'
ALIGN_RIGHT = ESC + b'a\x02'

# ESC E n — emphasized / bold
BOLD_ON = ESC + b'E\x01'
BOLD_OFF = ESC + b'E\x00'

# ESC - n — underline
UNDERLINE_ON = ESC + b'-\x01'
UNDERLINE_OFF = ESC + b'-\x00'

# GS ! n — character size (bit 0-3 height, 4-7 width)
# 0x00 = normal; 0x11 = double width + double height
SIZE_NORMAL = GS + b'!\x00'
SIZE_DOUBLE = GS + b'!\x11'
# Legacy ESC ! also accepted by many printers (including XP-T80A)
SIZE_DOUBLE_ESC = ESC + b'!\x11'
SIZE_NORMAL_ESC = ESC + b'!\x00'

# ESC d n — feed n lines
def FEED_LINES(n: int) -> bytes:
    return ESC + b'd' + bytes([max(0, min(255, int(n)))])


LF = b'\n'

# GS V m — cut (m=0 full, m=1 partial)
FULL_CUT = GS + b'V\x00'
PARTIAL_CUT = GS + b'V\x01'
# GS V m n — feed-and-cut (m=65/66) used by some Xprinter firmwares
PARTIAL_CUT_FEED = GS + b'V\x42\x00'  # m=66, n=0

# ESC p m t1 t2 — cash drawer pulse (m=0 pin2, m=1 pin5)
def DRAWER_PULSE(pin: int = 0, t1: int = 50, t2: int = 50) -> bytes:
    m = 0 if int(pin) == 0 else 1
    return ESC + b'p' + bytes([m, max(0, min(255, t1)), max(0, min(255, t2))])


# GS ( k — QR Code model (common ESC/POS sequence)
def qr_code_bytes(payload: str, *, module_size: int = 4, ec_level: int = 48) -> bytes:
    """Build QR ESC/POS for payload. ec_level: 48=L, 49=M, 50=Q, 51=H."""
    data = (payload or '').encode('utf-8', errors='replace')
    if not data:
        return b''
    size = max(1, min(16, int(module_size)))
    ec = max(48, min(51, int(ec_level)))
    out = bytearray()
    # Select model 2
    out.extend(GS + b'(k\x04\x00\x31\x41\x32\x00')
    # Module size
    out.extend(GS + b'(k\x03\x00\x31\x43' + bytes([size]))
    # Error correction
    out.extend(GS + b'(k\x03\x00\x31\x45' + bytes([ec]))
    # Store data
    store_len = len(data) + 3
    out.extend(GS + b'(k' + bytes([store_len & 0xFF, (store_len >> 8) & 0xFF]) + b'\x31\x50\x30' + data)
    # Print
    out.extend(GS + b'(k\x03\x00\x31\x51\x30')
    return bytes(out)


# GS k — CODE128 barcode (function B)
def barcode_code128_bytes(payload: str, *, height: int = 60, width: int = 2) -> bytes:
    data = (payload or '').encode('ascii', errors='replace')
    if not data:
        return b''
    h = max(1, min(255, int(height)))
    w = max(2, min(6, int(width)))
    out = bytearray()
    out.extend(GS + b'h' + bytes([h]))
    out.extend(GS + b'w' + bytes([w]))
    out.extend(GS + b'H\x02')  # HRI below
    # m=73 CODE128, n=length, then data
    out.extend(GS + b'k\x49' + bytes([len(data)]) + data)
    out.extend(LF)
    return bytes(out)
