"""Print job result objects — separate PRINT STATE from SALE STATE."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
import uuid


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PrintJobResult:
    success: bool
    job_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    receipt_number: str = ''
    printer: str = ''
    transport: str = ''
    started_at: str = field(default_factory=_utc_now)
    completed_at: str = ''
    bytes_sent: int = 0
    error_type: str = ''
    error_message: str = ''
    retryable: bool = False
    label: str = ''
    is_reprint: bool = False
    drawer_pulsed: bool = False
    cut_issued: bool = False

    def finish(self, *, success: bool, bytes_sent: int = 0,
               error_type: str = '', error_message: str = '',
               retryable: bool = False) -> 'PrintJobResult':
        self.success = success
        self.bytes_sent = int(bytes_sent or 0)
        self.error_type = error_type or ''
        self.error_message = (error_message or '')[:500]
        self.retryable = bool(retryable)
        self.completed_at = _utc_now()
        return self

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def cashier_message(self) -> str:
        if self.success:
            return 'Receipt printed.'
        rn = self.receipt_number or 'this sale'
        return (
            f'Sale completed successfully. Receipt could not be printed '
            f'({rn}).'
        )


# Stable error type codes for UI / logs
ERR_NOT_CONFIGURED = 'printer_not_configured'
ERR_WINDOWS_NOT_FOUND = 'windows_printer_not_found'
ERR_LAN_UNREACHABLE = 'lan_unreachable'
ERR_CONNECTION_REFUSED = 'connection_refused'
ERR_TIMEOUT = 'connection_timeout'
ERR_ACCESS_DENIED = 'access_denied'
ERR_INVALID_IP = 'invalid_ip'
ERR_INVALID_PORT = 'invalid_port'
ERR_WRITE_FAILED = 'write_failure'
ERR_SPOOLER = 'windows_spooler_unavailable'
ERR_UNSUPPORTED = 'unsupported_command'
ERR_LOGO = 'logo_failure'
ERR_UNEXPECTED = 'unexpected_exception'
ERR_USB_REMOVED = 'usb_printer_removed'
