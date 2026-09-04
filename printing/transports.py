"""Printer transports — deliver raw ESC/POS bytes without graphics reinterpretation."""
from __future__ import annotations

import logging
import socket
import sys
from abc import ABC, abstractmethod
from typing import Optional, Tuple

from printing.print_job import (
    ERR_ACCESS_DENIED, ERR_CONNECTION_REFUSED, ERR_INVALID_IP,
    ERR_INVALID_PORT, ERR_LAN_UNREACHABLE, ERR_NOT_CONFIGURED,
    ERR_SPOOLER, ERR_TIMEOUT, ERR_UNEXPECTED, ERR_USB_REMOVED,
    ERR_WINDOWS_NOT_FOUND, ERR_WRITE_FAILED,
)

logger = logging.getLogger('printing.transport')


class TransportError(Exception):
    def __init__(self, error_type: str, message: str, retryable: bool = True):
        super().__init__(message)
        self.error_type = error_type
        self.retryable = retryable


class PrinterTransport(ABC):
    name: str = 'base'

    @abstractmethod
    def write(self, data: bytes) -> int:
        """Send raw bytes. Return bytes written. Raise TransportError on failure."""

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class WindowsRawTransport(PrinterTransport):
    """Send RAW ESC/POS via the Windows spooler (preferred for USB installs)."""

    name = 'windows_raw'

    def __init__(self, printer_name: str):
        self.printer_name = (printer_name or '').strip()
        if not self.printer_name:
            raise TransportError(ERR_NOT_CONFIGURED, 'Windows printer name is empty', False)
        try:
            import win32print  # type: ignore
        except ImportError as e:
            raise TransportError(
                ERR_SPOOLER,
                'win32print is not available in this build',
                False,
            ) from e
        self._win32print = win32print
        names = [p[2] for p in win32print.EnumPrinters(2)]
        if self.printer_name not in names:
            # Case-insensitive match
            match = next((n for n in names if n.lower() == self.printer_name.lower()), None)
            if not match:
                raise TransportError(
                    ERR_WINDOWS_NOT_FOUND,
                    f'Windows printer not found: {self.printer_name}',
                    False,
                )
            self.printer_name = match

    def write(self, data: bytes) -> int:
        if not data:
            return 0
        hprinter = None
        try:
            hprinter = self._win32print.OpenPrinter(self.printer_name)
            job = ('MBT POS Receipt', None, 'RAW')
            self._win32print.StartDocPrinter(hprinter, 1, job)
            try:
                self._win32print.StartPagePrinter(hprinter)
                written = self._win32print.WritePrinter(hprinter, data)
                self._win32print.EndPagePrinter(hprinter)
            finally:
                self._win32print.EndDocPrinter(hprinter)
            return int(written or 0)
        except Exception as e:
            msg = str(e)
            low = msg.lower()
            if 'access' in low or 'denied' in low:
                raise TransportError(ERR_ACCESS_DENIED, msg, True) from e
            if 'not found' in low or 'unknown' in low:
                raise TransportError(ERR_WINDOWS_NOT_FOUND, msg, False) from e
            raise TransportError(ERR_WRITE_FAILED, msg, True) from e
        finally:
            if hprinter is not None:
                try:
                    self._win32print.ClosePrinter(hprinter)
                except Exception:
                    pass


class LanEscposTransport(PrinterTransport):
    """Direct TCP raw print (typical port 9100). Works fully offline on LAN."""

    name = 'lan_tcp'

    def __init__(self, host: str, port: int = 9100, timeout: float = 5.0):
        self.host = (host or '').strip()
        self.port = int(port or 9100)
        self.timeout = float(timeout or 5.0)
        if not self.host:
            raise TransportError(ERR_INVALID_IP, 'Printer IP is empty', False)
        if self.port < 1 or self.port > 65535:
            raise TransportError(ERR_INVALID_PORT, f'Invalid port: {self.port}', False)
        self._sock: Optional[socket.socket] = None

    def _connect(self) -> socket.socket:
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
            sock.settimeout(self.timeout)
            return sock
        except socket.timeout as e:
            raise TransportError(ERR_TIMEOUT, f'Timeout connecting to {self.host}:{self.port}', True) from e
        except ConnectionRefusedError as e:
            raise TransportError(
                ERR_CONNECTION_REFUSED,
                f'Connection refused {self.host}:{self.port}',
                True,
            ) from e
        except OSError as e:
            raise TransportError(
                ERR_LAN_UNREACHABLE,
                f'LAN printer unreachable {self.host}:{self.port}: {e}',
                True,
            ) from e

    def write(self, data: bytes) -> int:
        if not data:
            return 0
        sock = self._connect()
        try:
            sock.sendall(data)
            return len(data)
        except socket.timeout as e:
            raise TransportError(ERR_TIMEOUT, 'Write timed out', True) from e
        except OSError as e:
            raise TransportError(ERR_WRITE_FAILED, str(e), True) from e
        finally:
            try:
                sock.close()
            except Exception:
                pass


class FileLikeTransport(PrinterTransport):
    """Wrap legacy serial / LPT / USB file-like objects."""

    name = 'legacy_file'

    def __init__(self, handle, label: str = 'legacy'):
        self._handle = handle
        self.name = label

    def write(self, data: bytes) -> int:
        if not data:
            return 0
        try:
            n = self._handle.write(data)
            if hasattr(self._handle, 'flush'):
                self._handle.flush()
            return int(n if n is not None else len(data))
        except Exception as e:
            low = str(e).lower()
            if 'timeout' in low:
                raise TransportError(ERR_TIMEOUT, str(e), True) from e
            if 'access' in low or 'denied' in low:
                raise TransportError(ERR_ACCESS_DENIED, str(e), True) from e
            if 'no such' in low or 'removed' in low or 'disconnected' in low:
                raise TransportError(ERR_USB_REMOVED, str(e), True) from e
            raise TransportError(ERR_WRITE_FAILED, str(e), True) from e

    def close(self) -> None:
        try:
            self._handle.close()
        except Exception:
            pass


def open_legacy_device(port: str = '', vendor_id=None, product_id=None) -> Optional[FileLikeTransport]:
    """Preserve existing serial/LPT/pyusb paths behind the transport abstraction."""
    import os

    port = (port or '').strip()
    # Treat placeholder "USB" as "no real serial port"
    if port.upper() == 'USB':
        port = ''

    if sys.platform.startswith('linux'):
        for lp in ('/dev/usb/lp0', '/dev/usb/lp1', '/dev/usb/lp2'):
            if os.path.exists(lp):
                try:
                    return FileLikeTransport(open(lp, 'wb'), 'linux_usb_lp')
                except Exception:
                    pass

    if sys.platform == 'win32':
        if port:
            try:
                import serial
                return FileLikeTransport(
                    serial.Serial(port, 9600, timeout=1),
                    f'serial:{port}',
                )
            except Exception:
                pass
        try:
            return FileLikeTransport(open('LPT1', 'wb'), 'lpt1')
        except Exception:
            pass

    try:
        import usb.core
        import usb.util
        kwargs = {}
        if vendor_id:
            kwargs['idVendor'] = int(vendor_id, 16) if isinstance(vendor_id, str) else vendor_id
        if product_id:
            kwargs['idProduct'] = int(product_id, 16) if isinstance(product_id, str) else product_id
        dev = usb.core.find(**kwargs) if kwargs else None
        if not kwargs:
            # Do not grab arbitrary USB devices without VID/PID
            return None
        if not dev:
            return None
        try:
            if hasattr(dev, 'is_kernel_driver_active') and dev.is_kernel_driver_active(0):
                try:
                    dev.detach_kernel_driver(0)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            dev.set_configuration()
        except Exception:
            pass
        cfg = dev.get_active_configuration()
        intf = cfg[(0, 0)]
        ep = next(
            (e for e in intf
             if usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT),
            None,
        )
        if not ep:
            return None

        class _Usb:
            def write(self, data):
                return ep.write(data)

            def flush(self):
                return None

            def close(self):
                try:
                    usb.util.dispose_resources(dev)
                except Exception:
                    pass

        return FileLikeTransport(_Usb(), 'pyusb')
    except Exception:
        return None


def resolve_transport(cfg: dict) -> Tuple[PrinterTransport, str]:
    """
    Pick transport from settings.

    Priority:
      1. printer_connection=lan + printer_ip
      2. printer_name (Windows RAW) when set
      3. Legacy serial/LPT/USB
    """
    cfg = cfg or {}
    conn = str(cfg.get('printer_connection') or '').strip().lower()
    host = (cfg.get('printer_ip') or cfg.get('printer_host') or '').strip()
    name = (cfg.get('printer_name') or '').strip()
    port = (cfg.get('printer_port') or '').strip()

    if conn == 'lan' or (host and conn != 'windows'):
        try:
            lan_port = int(cfg.get('printer_lan_port') or cfg.get('printer_tcp_port') or 9100)
        except (TypeError, ValueError):
            raise TransportError(ERR_INVALID_PORT, 'Invalid LAN port', False)
        try:
            timeout = float(cfg.get('printer_timeout') or 5)
        except (TypeError, ValueError):
            timeout = 5.0
        if not host:
            raise TransportError(ERR_INVALID_IP, 'LAN printer IP not configured', False)
        return LanEscposTransport(host, lan_port, timeout), f'{host}:{lan_port}'

    if name and sys.platform == 'win32':
        return WindowsRawTransport(name), name

    # Auto: Windows name if present even without connection mode
    if name and sys.platform == 'win32' and conn in ('', 'auto', 'windows', 'usb'):
        return WindowsRawTransport(name), name

    legacy = open_legacy_device(
        port=port,
        vendor_id=cfg.get('printer_vendor_id'),
        product_id=cfg.get('printer_product_id'),
    )
    if legacy is not None:
        return legacy, legacy.name

    raise TransportError(
        ERR_NOT_CONFIGURED,
        'No printer configured. Set a Windows printer name or LAN IP in Settings.',
        False,
    )


def list_windows_printers() -> list:
    if sys.platform != 'win32':
        return []
    try:
        import win32print
        return [p[2] for p in win32print.EnumPrinters(2)]
    except Exception as e:
        logger.warning('EnumPrinters failed: %s', e)
        return []


def probe_lan(host: str, port: int = 9100, timeout: float = 3.0) -> Tuple[bool, str]:
    host = (host or '').strip()
    if not host:
        return False, 'IP required'
    try:
        with socket.create_connection((host, int(port)), timeout=float(timeout)):
            return True, f'Reachable {host}:{port}'
    except Exception as e:
        return False, str(e)
