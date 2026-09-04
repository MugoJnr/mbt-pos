"""
MBT POS — production ESC/POS receipt engine (Phase 1).

Architecture:
  receipt_formatter  → sale dict → ReceiptDocument (no hardware)
  EscPosBuilder      → ReceiptDocument → raw ESC/POS bytes
  transports         → Windows RAW / LAN TCP / legacy file
  PrinterManager     → queue + PrintJobResult + drawer/cut policy

Printing never creates or mutates sales. Callers must print from saved sales only.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from datetime import datetime
from typing import Callable, Optional

from printing.escpos_commands import (
    ALIGN_CENTER, ALIGN_LEFT, ALIGN_RIGHT, BOLD_OFF, BOLD_ON,
    DRAWER_PULSE, FEED_LINES, FULL_CUT, INIT, PARTIAL_CUT, PARTIAL_CUT_FEED,
    SIZE_DOUBLE_ESC, SIZE_NORMAL_ESC, UNDERLINE_OFF, UNDERLINE_ON,
    barcode_code128_bytes, qr_code_bytes,
)
from printing.print_job import (
    ERR_LOGO, ERR_NOT_CONFIGURED, ERR_UNEXPECTED, PrintJobResult,
)
from printing.profiles import PrinterProfile, get_profile
from printing.receipt_formatter import (
    ReceiptDocument, build_receipt_document, document_to_plain_text,
    format_money, left_right, wrap_text,
)
from printing.transports import (
    TransportError, list_windows_printers, probe_lan, resolve_transport,
)

logger = logging.getLogger('printing')

# Re-export legacy names used by older imports/tests
PAPER_CHARS = 48
ENCODING = 'cp437'

# Keep command aliases for tests that import from printer_engine
ESC = b'\x1b'
GS = b'\x1d'
DOUBLE_ON = SIZE_DOUBLE_ESC
DOUBLE_OFF = SIZE_NORMAL_ESC


class EscPosBuilder:
    """Low-level ESC/POS byte builder (profile-aware)."""

    def __init__(self, profile: Optional[PrinterProfile] = None):
        self.profile = profile or get_profile()
        self.encoding = self.profile.encoding or ENCODING
        self.width = int(self.profile.chars_normal or PAPER_CHARS)
        self._buf = bytearray()
        self._cut_issued = False
        self._drawer_pulsed = False

    def raw(self, data: bytes) -> 'EscPosBuilder':
        if data:
            self._buf.extend(data)
        return self

    def _write_text(self, text: str) -> None:
        self._buf.extend(str(text or '').encode(self.encoding, errors='replace'))

    def init(self) -> 'EscPosBuilder':
        return self.raw(INIT)

    def align(self, a: str = 'left') -> 'EscPosBuilder':
        return self.raw({
            'left': ALIGN_LEFT, 'center': ALIGN_CENTER, 'right': ALIGN_RIGHT,
        }.get(a, ALIGN_LEFT))

    def bold(self, on: bool = True) -> 'EscPosBuilder':
        return self.raw(BOLD_ON if on else BOLD_OFF)

    def underline(self, on: bool = True) -> 'EscPosBuilder':
        return self.raw(UNDERLINE_ON if on else UNDERLINE_OFF)

    def double(self, on: bool = True) -> 'EscPosBuilder':
        return self.raw(SIZE_DOUBLE_ESC if on else SIZE_NORMAL_ESC)

    def text(self, text: str = '') -> 'EscPosBuilder':
        self._write_text(str(text or '') + '\n')
        return self

    def feed(self, n: int = 2) -> 'EscPosBuilder':
        return self.raw(FEED_LINES(n))

    def cut(self, mode: str | None = None) -> 'EscPosBuilder':
        mode = (mode or self.profile.cut_mode or 'partial').lower()
        if mode in ('none', 'off', '0'):
            return self
        if mode in ('full',):
            self.raw(FULL_CUT)
        elif mode in ('partial_feed', 'feed'):
            self.raw(PARTIAL_CUT_FEED)
        else:
            self.raw(PARTIAL_CUT)
        self._cut_issued = True
        return self

    def drawer(self, pin: int | None = None, t1: int = 50, t2: int = 50) -> 'EscPosBuilder':
        pin = self.profile.drawer_pin_default if pin is None else pin
        self.raw(DRAWER_PULSE(pin, t1, t2))
        self._drawer_pulsed = True
        return self

    def qr(self, payload: str) -> 'EscPosBuilder':
        if not self.profile.supports_qr:
            return self
        return self.raw(qr_code_bytes(payload))

    def barcode(self, payload: str) -> 'EscPosBuilder':
        if not self.profile.supports_barcode:
            return self
        return self.raw(barcode_code128_bytes(payload))

    def raster_logo(self, png_path: str, max_width_px: int = 384) -> 'EscPosBuilder':
        """Best-effort monochrome raster. Failures are silent (never block print)."""
        if not self.profile.supports_raster_logo:
            return self
        try:
            data = _png_to_raster_escpos(png_path, max_width_px=max_width_px)
            if data:
                self.align('center')
                self.raw(data)
                self.text('')
        except Exception as e:
            logger.warning('Logo raster skipped: %s', e)
        return self

    def from_document(self, doc: ReceiptDocument) -> 'EscPosBuilder':
        self.init()
        for line in doc.lines:
            if line.kind == 'blank':
                self.text('')
                continue
            if line.kind == 'sep':
                self.align('left')
                self.bold(False)
                self.double(False)
                self.text((line.text or '-')[: self.width])
                continue
            self.align(line.align or 'left')
            self.bold(bool(line.bold))
            self.double(bool(line.double))
            self.text(line.text or '')
        self.bold(False)
        self.double(False)
        self.align('left')
        if doc.barcode_payload:
            try:
                self.align('center')
                self.barcode(doc.barcode_payload)
                self.align('left')
            except Exception:
                pass
        if doc.qr_payload:
            try:
                self.align('center')
                self.qr(doc.qr_payload)
                self.align('left')
            except Exception:
                pass
        feed = int(doc.feed_before_cut or self.profile.feed_before_cut or 3)
        self.feed(feed)
        if doc.cut:
            self.cut()
        return self

    def build(self) -> bytes:
        return bytes(self._buf)


def _png_to_raster_escpos(path: str, max_width_px: int = 384) -> bytes:
    """Convert PNG/JPEG to GS v 0 raster. Requires Pillow when available."""
    import os
    if not path or not os.path.isfile(path):
        return b''
    try:
        from PIL import Image
    except ImportError:
        return b''
    img = Image.open(path)
    if img.mode != 'L':
        img = img.convert('L')
    # Resize to receipt-safe width (203dpi ≈ 72mm ≈ 576 dots; keep modest)
    max_w = max(64, min(576, int(max_width_px or 384)))
    if img.width > max_w:
        ratio = max_w / float(img.width)
        img = img.resize((max_w, max(1, int(img.height * ratio))))
    # Threshold to 1-bit
    bw = img.point(lambda x: 0 if x < 160 else 255, mode='1')
    width = bw.width
    height = bw.height
    row_bytes = (width + 7) // 8
    pixels = bw.load()
    data = bytearray()
    for y in range(height):
        for byte_i in range(row_bytes):
            bval = 0
            for bit in range(8):
                x = byte_i * 8 + bit
                if x < width and pixels[x, y] == 0:
                    bval |= 0x80 >> bit
            data.append(bval)
    # GS v 0 m xL xH yL yH d1...dk
    header = GS + b'v0\x00' + bytes([
        row_bytes & 0xFF, (row_bytes >> 8) & 0xFF,
        height & 0xFF, (height >> 8) & 0xFF,
    ])
    return header + bytes(data)


class ReceiptBuilder:
    """
    Backward-compatible fluent builder used by older tests/callers.
    Internally accumulates ESC/POS using EscPosBuilder.
    """

    def __init__(self, shop_name='My Shop', currency='KES',
                 shop_address='', shop_phone='', profile=None):
        self.shop_name = shop_name
        self.currency = currency
        self.shop_address = (shop_address or '').strip()
        self.shop_phone = (shop_phone or '').strip()
        self._esc = EscPosBuilder(profile or get_profile())
        self._buf = self._esc._buf  # shared for .build() parity

    def _write(self, data):
        if isinstance(data, str):
            self._esc._write_text(data)
        else:
            self._esc.raw(data)
        return self

    def _line(self, text=''):
        self._esc.text(text)
        return self

    def init(self):
        self._esc.init()
        return self

    def align(self, a='left'):
        self._esc.align(a)
        return self

    def bold(self, on=True):
        self._esc.bold(on)
        return self

    def double(self, on=True):
        self._esc.double(on)
        return self

    def text(self, text):
        self._esc.text(text)
        return self

    def divider(self, char='-'):
        self._esc.text(char * self._esc.width)
        return self

    def feed(self, n=2):
        self._esc.feed(n)
        return self

    def cut(self, partial=True):
        self._esc.cut('partial' if partial else 'full')
        return self

    def header(self, invoice_number, date_str, cashier):
        self.init()
        self.align('center')
        self.double(True)
        self.bold(True)
        self._line(self.shop_name[:self._esc.width])
        self.double(False)
        self.bold(False)
        if self.shop_address:
            self._line(self.shop_address[:self._esc.width])
        if self.shop_phone:
            self._line(self.shop_phone[:self._esc.width])
        self._line('INVOICE')
        self.divider('=')
        self.align('left')
        self._line(f'Invoice #: {invoice_number}')
        self._line(f'Date:      {date_str}')
        self._line(f'Cashier:   {cashier}')
        self.divider()
        return self

    def items(self, items):
        W = self._esc.width
        for item in items or []:
            raw_name = str(item.get('product_name', '') or '')
            for chunk in wrap_text(raw_name, W, 3):
                self._line(chunk)
            qty_val = float(item.get('quantity', 1) or 1)
            qty = f'{qty_val:g}' if qty_val % 1 else f'{int(qty_val)}'
            price = float(item.get('unit_price', 0) or 0)
            total = float(item.get('total', 0) or 0)
            self._line(left_right(f'{qty} x {price:,.2f}', f'{total:,.2f}', W))
            disc = float(item.get('discount') or 0)
            if disc > 0:
                self._line(left_right('  Disc:', f'-{disc:,.2f}', W))
        self.divider()
        return self

    def totals(self, subtotal, discount, tax, total, payment_method, amount_paid, change,
               credit_applied=0, variance=None, wallet_balance=None,
               original_total=None, cash_rounding_adj=0,
               electronic_paid=0, electronic_method='', cash_paid=0):
        W = self._esc.width
        sym = self.currency
        if float(discount or 0) > 0:
            self._line(left_right('Subtotal:', format_money(subtotal, sym), W))
            self._line(left_right('Discount:', f'-{format_money(discount, sym)}', W))
        if float(tax or 0) > 0:
            self._line(left_right('Tax:', format_money(tax, sym), W))
        adj = float(cash_rounding_adj or 0)
        pm = str(payment_method or '').lower()
        is_electronic = any(x in pm for x in ('mpesa', 'm-pesa', 'card', 'bank', 'cheque', 'eft'))
        is_mixed = 'mixed' in pm or float(electronic_paid or 0) > 0.009
        if abs(adj) > 0.009 and (not is_electronic or is_mixed):
            if original_total is not None:
                self._line(left_right('Original Total:', format_money(original_total, sym), W))
            sign = '+' if adj >= 0 else ''
            self._line(left_right('Cash Rounding:', f'{sign}{format_money(abs(adj), sym)}', W))
        self.bold(True)
        self._line(left_right('TOTAL:', format_money(total, sym), W))
        self.bold(False)
        if credit_applied and float(credit_applied) > 0:
            self._line(left_right('Store Credit:', f'-{format_money(credit_applied, sym)}', W))
        elec = float(electronic_paid or 0)
        if elec > 0.009:
            em = (electronic_method or 'Electronic').strip() or 'Electronic'
            cash_amt = float(cash_paid or 0)
            if cash_amt < 0.009:
                cash_amt = max(0.0, round(float(amount_paid or 0) - elec, 2))
            self._line(left_right(f'{em}:', format_money(elec, sym), W))
            self._line(left_right('Cash:', format_money(cash_amt, sym), W))
        else:
            self._line(left_right(f'Payment ({payment_method}):', format_money(amount_paid, sym), W))
        if float(change or 0) > 0:
            self._line(left_right('Change Returned:', format_money(change, sym), W))
        var = variance or {}
        handling = (var.get('handling') or '').strip().lower()
        if handling == 'additional_payment':
            return self
        if var and float(var.get('excess_amount') or 0) > 0:
            self.divider()
            if float(var.get('tip_amount') or 0) > 0:
                self._line(left_right('Tip:', format_money(var.get('tip_amount'), sym), W))
            if float(var.get('transport_amount') or 0) > 0:
                self._line(left_right('Transport:', format_money(var.get('transport_amount'), sym), W))
            if float(var.get('deposit_amount') or 0) > 0:
                self._line(left_right('Deposit:', format_money(var.get('deposit_amount'), sym), W))
            if float(var.get('advance_amount') or 0) > 0:
                self._line(left_right('Advance:', format_money(var.get('advance_amount'), sym), W))
            if float(var.get('misc_amount') or 0) > 0:
                cat = var.get('misc_category') or 'Misc'
                self._line(left_right(f'Misc ({cat}):', format_money(var.get('misc_amount'), sym), W))
            if wallet_balance is not None and float(var.get('deposit_amount') or 0) + float(var.get('advance_amount') or 0) > 0:
                self._line(left_right('Credit Bal:', format_money(wallet_balance, sym), W))
        return self

    def footer(self, custom_footer='Thank you for shopping with us!'):
        self.divider()
        self.align('center')
        self._line(custom_footer)
        self._line('')
        self._line('Powered by MugoByte Technologies')
        self.divider('=')
        self.feed(3)
        self.cut(partial=True)
        return self

    def build(self):
        return self._esc.build()


def build_receipt(sale_data, shop_name='My Shop', currency='KES',
                  footer='Thank you for shopping with us!',
                  shop_address='', shop_phone='',
                  is_reprint=False, profile=None, logo_path='',
                  qr_enabled=False) -> bytes:
    """Build ESC/POS bytes from a saved sale dict."""
    profile = profile or get_profile()
    doc = build_receipt_document(
        sale_data,
        shop_name=shop_name,
        currency=currency,
        footer=footer,
        shop_address=shop_address,
        shop_phone=shop_phone,
        width=profile.chars_normal,
        is_reprint=is_reprint,
        qr_enabled=qr_enabled,
    )
    esc = EscPosBuilder(profile)
    if logo_path:
        try:
            esc.raster_logo(logo_path)
        except Exception as e:
            logger.warning('%s: %s', ERR_LOGO, e)
    esc.from_document(doc)
    return esc.build()


def generate_receipt_text(sale_data, shop_name='My Shop', currency='KES',
                          shop_address='', shop_phone='', is_reprint=False) -> str:
    """Plain-text preview — same document model as thermal."""
    doc = build_receipt_document(
        sale_data,
        shop_name=shop_name,
        currency=currency,
        footer=sale_data.get('receipt_footer', 'Thank you!') if sale_data else 'Thank you!',
        shop_address=shop_address,
        shop_phone=shop_phone,
        width=PAPER_CHARS,
        is_reprint=is_reprint,
    )
    return document_to_plain_text(doc, PAPER_CHARS)


def should_open_drawer(sale_data: dict, cfg: dict) -> bool:
    """Drawer policy: cash (and cash portion of mixed/part) when enabled."""
    cfg = cfg or {}
    if str(cfg.get('open_drawer_on_cash', '1')) != '1':
        return False
    pm = str((sale_data or {}).get('payment_method') or '').lower()
    if pm in ('cash',):
        return True
    if 'mixed' in pm:
        try:
            return float((sale_data or {}).get('cash_paid') or 0) > 0.009
        except (TypeError, ValueError):
            return False
    if pm in ('part payment',):
        # Only if cash was actually received
        try:
            cash = float((sale_data or {}).get('cash_paid') or 0)
            if cash > 0.009:
                return True
            # fallback: amount_paid with cash-like method and no electronic
            elec = float((sale_data or {}).get('electronic_paid') or 0)
            paid = float((sale_data or {}).get('amount_paid') or 0)
            return elec < 0.009 and paid > 0.009 and str(
                cfg.get('open_drawer_on_part_cash', '1')) == '1'
        except (TypeError, ValueError):
            return False
    return False


class PrintQueue(threading.Thread):
    """Background queue — never blocks the cashier UI."""

    def __init__(self, send_fn: Callable[[bytes], int]):
        super().__init__(daemon=True, name='MBT-PrintQueue')
        self._q: queue.Queue = queue.Queue()
        self._send_fn = send_fn
        self.status = 'idle'
        self._stop = threading.Event()
        self.last_result: Optional[PrintJobResult] = None
        self._callbacks: list = []
        self._cb_lock = threading.Lock()

    def on_complete(self, cb: Callable[[PrintJobResult], None]):
        with self._cb_lock:
            self._callbacks.append(cb)

    def enqueue(self, data: bytes, job: PrintJobResult,
                on_complete: Callable[[PrintJobResult], None] = None):
        self._q.put({'data': data, 'job': job, 'on_complete': on_complete})
        logger.info(
            'Print job queued id=%s receipt=%s bytes=%s',
            job.job_id, job.receipt_number, len(data or b''),
        )

    def stop(self):
        self._stop.set()

    def run(self):
        while not self._stop.is_set():
            try:
                item = self._q.get(timeout=2)
            except queue.Empty:
                continue
            job: PrintJobResult = item['job']
            data: bytes = item['data']
            last_err = None
            for attempt in range(5):
                try:
                    self.status = 'printing'
                    written = self._send_fn(data)
                    job.finish(success=True, bytes_sent=written)
                    self.status = 'idle'
                    self.last_result = job
                    logger.info(
                        'Printed ok id=%s receipt=%s transport=%s bytes=%s',
                        job.job_id, job.receipt_number, job.transport, written,
                    )
                    break
                except TransportError as e:
                    last_err = e
                    self.status = 'error'
                    logger.warning(
                        'Print attempt %s/5 id=%s type=%s: %s',
                        attempt + 1, job.job_id, e.error_type, e,
                    )
                    time.sleep(2 if e.retryable else 0.5)
                    if not e.retryable:
                        break
                except Exception as e:
                    last_err = e
                    self.status = 'error'
                    logger.exception('Print unexpected error id=%s', job.job_id)
                    time.sleep(2)
            else:
                # exhausted
                pass
            if not job.success:
                if isinstance(last_err, TransportError):
                    job.finish(
                        success=False, error_type=last_err.error_type,
                        error_message=str(last_err), retryable=last_err.retryable,
                    )
                else:
                    job.finish(
                        success=False, error_type=ERR_UNEXPECTED,
                        error_message=str(last_err or 'print failed'),
                        retryable=True,
                    )
                self.last_result = job
                logger.error(
                    'Print failed id=%s receipt=%s type=%s msg=%s',
                    job.job_id, job.receipt_number, job.error_type, job.error_message,
                )
            # Per-job callback first (preferred); then any registered listeners.
            job_cb = item.get('on_complete')
            with self._cb_lock:
                cbs = list(self._callbacks)
            for cb in ([job_cb] if job_cb else []) + cbs:
                try:
                    cb(job)
                except Exception:
                    pass
            self._q.task_done()


# Legacy helper kept for older call sites / tests
def get_usb_printer(vendor_id=None, product_id=None, port=None):
    from printing.transports import open_legacy_device
    t = open_legacy_device(port=port or '', vendor_id=vendor_id, product_id=product_id)
    return t._handle if t else None


class PrinterManager:
    """
    High-level manager. Prefer print_saved_receipt / print_sale_data.
    Fire-and-forget queue preserves UI responsiveness.
    """

    _instance = None
    _instance_lock = threading.Lock()

    def __init__(self, config_getter):
        self.config_getter = config_getter
        self._queue = PrintQueue(self._send_bytes)
        self._queue.start()
        self._last_job: Optional[PrintJobResult] = None
        self._result_event = threading.Event()

    @classmethod
    def shared(cls, config_getter) -> 'PrinterManager':
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls(config_getter)
            else:
                cls._instance.config_getter = config_getter
            return cls._instance

    def _cfg(self) -> dict:
        try:
            return self.config_getter() or {}
        except Exception:
            return {}

    def _profile(self) -> PrinterProfile:
        return get_profile(self._cfg().get('printer_profile'))

    def _send_bytes(self, data: bytes) -> int:
        transport, label = resolve_transport(self._cfg())
        try:
            return transport.write(data)
        finally:
            try:
                transport.close()
            except Exception:
                pass

    def _compose_bytes(self, sale_data: dict, *, is_reprint: bool = False) -> tuple[bytes, PrintJobResult]:
        cfg = self._cfg()
        profile = self._profile()
        job = PrintJobResult(
            success=False,
            receipt_number=str((sale_data or {}).get('receipt_number') or ''),
            is_reprint=is_reprint,
            label='reprint' if is_reprint else 'receipt',
        )
        shop = cfg.get('shop_name', 'My Shop')
        cur = cfg.get('currency_symbol', 'KES')
        foot = cfg.get('receipt_footer', 'Thank you for shopping with us!')
        logo = ''
        if str(cfg.get('print_logo', '1')) == '1':
            logo = (cfg.get('receipt_logo_path') or cfg.get('shop_logo_path') or '').strip()
        qr_on = str(cfg.get('print_qr', '0')) == '1'
        data = build_receipt(
            sale_data,
            shop_name=shop,
            currency=cur,
            footer=foot,
            shop_address=cfg.get('shop_address', ''),
            shop_phone=cfg.get('shop_phone', ''),
            is_reprint=is_reprint,
            profile=profile,
            logo_path=logo,
            qr_enabled=qr_on,
        )
        # Drawer pulse appended AFTER receipt content (cash policy)
        if should_open_drawer(sale_data, cfg) and not is_reprint:
            esc = EscPosBuilder(profile)
            esc.drawer()
            data = data + esc.build()
            job.drawer_pulsed = True
        job.cut_issued = True
        try:
            transport, label = resolve_transport(cfg)
            job.transport = transport.name
            job.printer = label
            try:
                transport.close()
            except Exception:
                pass
        except TransportError as e:
            job.transport = ''
            job.printer = ''
            # Still queue — send will fail with same error (keeps async path)
            job.error_type = e.error_type
            job.error_message = str(e)
            job.retryable = e.retryable
        return data, job

    def print_sale_data(self, sale_data: dict, *, is_reprint: bool = False,
                        wait: bool = False, timeout: float = 20.0,
                        on_complete: Callable[[PrintJobResult], None] = None,
                        ) -> PrintJobResult:
        """Print from an already-built sale dict (must be from saved sale)."""
        data, job = self._compose_bytes(sale_data, is_reprint=is_reprint)
        self._result_event.clear()

        def _done(res: PrintJobResult):
            self._last_job = res
            self._result_event.set()
            if on_complete:
                try:
                    on_complete(res)
                except Exception:
                    pass

        self._queue.enqueue(data, job, on_complete=_done)
        if wait:
            self._result_event.wait(timeout=timeout)
            return self._last_job or job
        return job

    def print_receipt(self, sale_data):
        """Legacy fire-and-forget API used by sales_tab auto-print."""
        return self.print_sale_data(sale_data, is_reprint=False, wait=False)

    def print_raw(self, data: bytes, label='raw') -> PrintJobResult:
        job = PrintJobResult(success=False, label=label)
        try:
            transport, name = resolve_transport(self._cfg())
            job.transport = transport.name
            job.printer = name
            try:
                transport.close()
            except Exception:
                pass
        except TransportError as e:
            job.finish(False, error_type=e.error_type, error_message=str(e),
                       retryable=e.retryable)
            return job
        self._queue.enqueue(data or b'', job)
        return job

    def open_cash_drawer(self) -> PrintJobResult:
        """Explicit drawer test/pulse — separate from receipt print."""
        esc = EscPosBuilder(self._profile())
        esc.init()
        esc.drawer()
        return self.print_raw(esc.build(), label='drawer_pulse')

    def test_print(self) -> PrintJobResult:
        cfg = self._cfg()
        profile = self._profile()
        esc = EscPosBuilder(profile)
        esc.init()
        esc.align('center')
        esc.bold(True)
        esc.double(True)
        esc.text('TEST PRINT')
        esc.double(False)
        esc.bold(False)
        esc.text(cfg.get('shop_name', 'My Shop'))
        addr = (cfg.get('shop_address') or '').strip()
        phone = (cfg.get('shop_phone') or '').strip()
        if addr:
            esc.text(addr[:profile.chars_normal])
        if phone:
            esc.text(phone[:profile.chars_normal])
        esc.text('-' * profile.chars_normal)
        esc.align('left')
        esc.text('Normal text ABCDEFG 0123456789')
        esc.bold(True)
        esc.text('BOLD text')
        esc.bold(False)
        esc.align('center')
        esc.text('Centered line')
        esc.align('left')
        esc.double(True)
        esc.text('DOUBLE')
        esc.double(False)
        esc.text(left_right('Left', 'Right', profile.chars_normal))
        esc.text(format_money(1250, cfg.get('currency_symbol', 'KES')))
        long_name = 'Very Long Product Name That Must Wrap Cleanly On Eighty Millimetre Paper'
        for chunk in wrap_text(long_name, profile.chars_normal, 3):
            esc.text(chunk)
        esc.text(left_right('2 x 150.00', '300.00', profile.chars_normal))
        esc.text('-' * profile.chars_normal)
        esc.text(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        if profile.supports_barcode:
            esc.align('center')
            esc.barcode('MBT-TEST-001')
            esc.align('left')
        if profile.supports_qr and str(cfg.get('print_qr', '0')) == '1':
            esc.align('center')
            esc.qr('MBT-POS-TEST')
            esc.align('left')
        esc.feed(profile.feed_before_cut)
        esc.cut()
        # Drawer NOT pulsed here — separate button
        return self.print_raw(esc.build(), label='test')

    def is_printer_available(self) -> bool:
        try:
            transport, _ = resolve_transport(self._cfg())
            try:
                transport.close()
            except Exception:
                pass
            return True
        except TransportError:
            return False

    @property
    def queue_size(self):
        return self._queue._q.qsize()

    @property
    def status(self):
        return self._queue.status

    @property
    def last_result(self) -> Optional[PrintJobResult]:
        return self._last_job or self._queue.last_result


def print_saved_receipt(
    api,
    config_getter,
    *,
    receipt_number: str = '',
    sale_id=None,
    is_reprint: bool = False,
    wait: bool = False,
    on_complete=None,
) -> PrintJobResult:
    """
    Canonical reprint/retry entry — loads committed sale only.
    NEVER calls create_sale().
    """
    cfg = {}
    try:
        cfg = config_getter() or {}
    except Exception:
        pass
    mgr = PrinterManager.shared(config_getter)

    sale = None
    if sale_id:
        try:
            sale = api.get_sale(int(sale_id))
        except Exception as e:
            return PrintJobResult(False, receipt_number=receipt_number).finish(
                False, error_type=ERR_UNEXPECTED,
                error_message=f'Could not load sale: {e}', retryable=True,
            )
        if sale and str(sale.get('status') or '').lower() == 'voided':
            return PrintJobResult(False, receipt_number=receipt_number).finish(
                False, error_type='sale_voided',
                error_message='This sale was voided — receipt not printed.',
                retryable=False,
            )
    if not sale and receipt_number:
        try:
            from desktop.utils.api_client import _db
            db = _db()
            row = db.execute(
                "SELECT id, status FROM sales WHERE receipt_number=?",
                (receipt_number.strip(),),
            ).fetchone()
            db.close()
            if not row:
                return PrintJobResult(False, receipt_number=receipt_number).finish(
                    False, error_type='sale_not_found',
                    error_message=f'No sale found: {receipt_number}',
                    retryable=False,
                )
            if str(row['status'] or '').lower() == 'voided':
                return PrintJobResult(False, receipt_number=receipt_number).finish(
                    False, error_type='sale_voided',
                    error_message='This sale was voided — receipt not printed.',
                    retryable=False,
                )
            sale = api.get_sale(int(row['id']))
        except Exception as e:
            return PrintJobResult(False, receipt_number=receipt_number).finish(
                False, error_type=ERR_UNEXPECTED,
                error_message=str(e), retryable=True,
            )
    if not sale:
        return PrintJobResult(False, receipt_number=receipt_number).finish(
            False, error_type='sale_not_found',
            error_message='Sale not found', retryable=False,
        )

    # Enrich print payload (same fields sales_tab used)
    data = dict(sale)
    data['mpesa_till'] = cfg.get('mpesa_till', '')
    data['mpesa_paybill'] = cfg.get('mpesa_paybill', '')
    data['receipt_footer'] = cfg.get('receipt_footer', 'Thank you!')
    # Pull debt invoice fields when present on get_sale
    if sale.get('debt_invoice_number'):
        data['debt_invoice_number'] = sale.get('debt_invoice_number')
    if sale.get('due_date'):
        data['due_date'] = sale.get('due_date')
    if sale.get('outstanding_balance') is not None:
        data['outstanding_balance'] = sale.get('outstanding_balance')

    # Audit reprint when possible
    if is_reprint:
        try:
            from desktop.utils.api_client import _audit
            _audit(
                getattr(api, '_user_id', None),
                getattr(api, '_username', '') or 'cashier',
                'RECEIPT_REPRINT',
                'sales',
                f"receipt={data.get('receipt_number')}",
            )
        except Exception:
            pass

    return mgr.print_sale_data(
        data, is_reprint=is_reprint, wait=wait, on_complete=on_complete,
    )


# Module-level helpers for settings UI
def windows_printers():
    return list_windows_printers()


def test_lan_printer(host: str, port: int = 9100, timeout: float = 3.0):
    return probe_lan(host, port, timeout)


center_text = lambda text, width=PAPER_CHARS: str(text).center(width)[:width]
divider = lambda char='-', width=PAPER_CHARS: char * width
format_currency = format_money
