"""Send receipt bytes to a configured printer.

Windows named printers use the spooler. Network printers and the test
emulator use TCP port 9100. A file sink is only for tests.

QZ Tray is not used. Silent printing with QZ Tray needs a paid certificate,
and every shop would have to install a second program.
"""
from __future__ import annotations

import os
import socket


class FilePrinter:
    def __init__(self, path: str):
        self._fh = open(path, "ab")

    def write(self, data: bytes):
        self._fh.write(data or b"")
        return len(data or b"")

    def flush(self):
        self._fh.flush()

    def close(self):
        self._fh.close()


class TcpPrinter:
    def __init__(self, host: str, port: int, timeout: float = 3):
        self._sock = socket.create_connection((host, int(port)), timeout)
        self._sock.settimeout(timeout)

    def write(self, data: bytes):
        self._sock.sendall(data or b"")
        return len(data or b"")

    def flush(self):
        return None

    def close(self):
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        self._sock.close()


class Win32RawPrinter:
    """RAW spooler job. The Windows print dialog is not opened."""

    def __init__(self, name: str):
        import win32print
        self._api = win32print
        self._handle = win32print.OpenPrinter(name)
        self._open = True
        try:
            win32print.StartDocPrinter(self._handle, 1, ("MBT POS", None, "RAW"))
            win32print.StartPagePrinter(self._handle)
        except Exception:
            win32print.ClosePrinter(self._handle)
            self._open = False
            raise

    def write(self, data: bytes):
        if not data:
            return 0
        self._api.WritePrinter(self._handle, data)
        return len(data)

    def flush(self):
        return None

    def close(self):
        if not self._open:
            return
        self._open = False
        try:
            self._api.EndPagePrinter(self._handle)
            self._api.EndDocPrinter(self._handle)
        finally:
            self._api.ClosePrinter(self._handle)


def printer_language(cfg: dict) -> str:
    chosen = str((cfg or {}).get("printer_language") or "").strip().lower()
    if chosen in ("escpos", "raw"):
        return "escpos"
    if chosen in ("driver", "gdi", "windows"):
        return "driver"
    connection = str((cfg or {}).get("printer_connection") or "").strip().upper()
    return "driver" if connection == "WINDOWS" else "escpos"


def _endpoint(cfg: dict) -> tuple[str, int]:
    target = str((cfg or {}).get("printer_host") or (cfg or {}).get("printer_port") or "").strip()
    if ":" in target and not target.upper().startswith("COM"):
        host, _, port_text = target.rpartition(":")
        try:
            return host or "127.0.0.1", int(port_text)
        except ValueError:
            return target, 9100
    return target, 9100


def open_printer(cfg: dict):
    """Open the configured transport. None means there is nothing to write to."""
    sink = os.environ.get("MBT_PRINTER_SINK", "").strip()
    if sink:
        return FilePrinter(sink)
    cfg = cfg or {}
    connection = str(cfg.get("printer_connection") or "").strip().upper()
    name = str(cfg.get("printer_name") or "").strip()
    port = str(cfg.get("printer_port") or "").strip()
    if connection == "LAN":
        host, number = _endpoint(cfg)
        if not host or host.upper() in ("USB", "LAN", "WINDOWS", "NONE"):
            return None
        return TcpPrinter(host, number)
    if connection == "WINDOWS" or name:
        if printer_language(cfg) == "driver" and connection == "WINDOWS" and not sink:
            return None
        if name:
            return Win32RawPrinter(name)
    from printing.printer_engine import get_usb_printer
    serial_port = port if port.upper() not in ("", "USB", "WINDOWS", "LAN", "NONE") else None
    return get_usb_printer(port=serial_port)


def print_driver_text(printer_name: str, text: str) -> None:
    """Print formatted text through the named Windows driver, with no dialog."""
    from PyQt5.QtGui import QFont, QTextDocument
    from PyQt5.QtPrintSupport import QPrinter

    printer = QPrinter(QPrinter.ScreenResolution)
    printer.setPrinterName(printer_name)
    document = QTextDocument()
    document.setDefaultFont(QFont("Consolas", 9))
    document.setPlainText(text or "")
    document.print_(printer)
