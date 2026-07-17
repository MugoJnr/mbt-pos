"""
MBT POS - 80mm Thermal Invoice Printer Engine
Handles USB thermal printing with auto-cutter support.
Works offline; queues jobs when printer unavailable.
"""
import os
import sys
import time
import json
import queue
import threading
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# ESC/POS Command constants
ESC = b'\x1b'
GS  = b'\x1d'

# Initialize
INIT         = ESC + b'@'
# Alignment
ALIGN_LEFT   = ESC + b'a\x00'
ALIGN_CENTER = ESC + b'a\x01'
ALIGN_RIGHT  = ESC + b'a\x02'
# Text style
BOLD_ON      = ESC + b'E\x01'
BOLD_OFF     = ESC + b'E\x00'
DOUBLE_ON    = ESC + b'!\x11'   # double height + width
DOUBLE_OFF   = ESC + b'!\x00'
UNDERLINE_ON = ESC + b'-\x01'
UNDERLINE_OFF= ESC + b'-\x00'
# Feed & cut
LF           = b'\n'
FEED_LINES   = lambda n: ESC + b'd' + bytes([n])
FULL_CUT     = GS + b'V\x00'      # full cut (some printers)
PARTIAL_CUT  = GS + b'V\x01'      # partial cut
# Paper width (80mm ≈ 48 chars at 80col, typically 32 at 12pt)
PAPER_CHARS  = 48

# Encoding for Thai/EN — most 80mm printers use cp437 or cp850
ENCODING = 'cp437'


def center_text(text, width=PAPER_CHARS):
    return text.center(width)[:width]


def left_right(left, right, width=PAPER_CHARS):
    space = width - len(left) - len(right)
    if space < 1:
        space = 1
    return left + ' ' * space + right


def divider(char='-', width=PAPER_CHARS):
    return char * width


def format_currency(amount, symbol='KES'):
    return f"{symbol} {amount:,.2f}"


class ReceiptBuilder:
    """Builds ESC/POS byte stream for 80mm thermal printer."""

    def __init__(self, shop_name='My Shop', currency='KES'):
        self.shop_name = shop_name
        self.currency = currency
        self._buf = bytearray()

    def _write(self, data):
        if isinstance(data, str):
            self._buf.extend(data.encode(ENCODING, errors='replace'))
        else:
            self._buf.extend(data)

    def _line(self, text=''):
        self._write(text + '\n')

    def init(self):
        self._write(INIT)
        return self

    def align(self, a='left'):
        self._write({'left': ALIGN_LEFT, 'center': ALIGN_CENTER, 'right': ALIGN_RIGHT}.get(a, ALIGN_LEFT))
        return self

    def bold(self, on=True):
        self._write(BOLD_ON if on else BOLD_OFF)
        return self

    def double(self, on=True):
        self._write(DOUBLE_ON if on else DOUBLE_OFF)
        return self

    def text(self, text):
        self._line(text)
        return self

    def divider(self, char='─'):
        self._line(divider(char))
        return self

    def feed(self, n=2):
        self._write(FEED_LINES(n))
        return self

    def cut(self, partial=True):
        self._write(PARTIAL_CUT if partial else FULL_CUT)
        return self

    def header(self, invoice_number, date_str, cashier):
        self.init()
        self.align('center')
        self.double(True)
        self.bold(True)
        self._line(self.shop_name[:PAPER_CHARS])
        self.double(False)
        self.bold(False)
        self._line('INVOICE')
        self.divider('=')
        self.align('left')
        self._line(f"Invoice #: {invoice_number}")
        self._line(f"Date:      {date_str}")
        self._line(f"Cashier:   {cashier}")
        self.divider()
        return self

    def items(self, items):
        # Column widths for 80mm paper: item(20), qty(6), price(9), total(9)
        # Kept plain and high-contrast for white paper output.
        header = f"{'ITEM':<20} {'QTY':>6} {'PRICE':>9} {'TOTAL':>9}"
        self._line(header)
        self.divider()
        for item in items:
            raw_name = str(item.get('product_name', '') or '')
            qty_val  = float(item.get('quantity', 1) or 1)
            qty = f"{qty_val:g}" if qty_val % 1 else f"{int(qty_val)}"
            price = f"{float(item.get('unit_price', 0) or 0):,.2f}"
            total = f"{float(item.get('total', 0) or 0):,.2f}"

            # Wrap long names to avoid truncating critical words on white paper slips.
            chunks = [raw_name[i:i+20] for i in range(0, len(raw_name), 20)] or ['']
            first = chunks[0]
            row = f"{first:<20} {qty:>6} {price:>9} {total:>9}"
            self._line(row[:PAPER_CHARS])
            for cont in chunks[1:3]:
                self._line(f"{cont:<20}")
            disc = float(item.get('discount') or 0)
            if disc > 0:
                self._line(f"  Disc: -{disc:,.2f}")
        self.divider()
        return self

    def totals(self, subtotal, discount, tax, total, payment_method, amount_paid, change,
               credit_applied=0, variance=None, wallet_balance=None,
               original_total=None, cash_rounding_adj=0):
        sym = self.currency
        if discount > 0:
            self._line(left_right(f"Subtotal:", format_currency(subtotal, sym)))
            self._line(left_right(f"Discount:", f"-{format_currency(discount, sym)}"))
        if tax > 0:
            self._line(left_right(f"Tax:", format_currency(tax, sym)))
        adj = float(cash_rounding_adj or 0)
        orig = original_total
        if orig is None and abs(adj) > 0.009:
            orig = float(total) - adj
        pm = str(payment_method or '').lower()
        is_electronic = any(x in pm for x in ('mpesa', 'm-pesa', 'card', 'bank', 'cheque', 'eft'))
        # Show cash rounding only when applied and not pure electronic receipt
        if abs(adj) > 0.009 and not is_electronic:
            if orig is not None:
                self._line(left_right("Original Total:", format_currency(orig, sym)))
            sign = '+' if adj >= 0 else ''
            self._line(left_right("Cash Rounding:", f"{sign}{format_currency(abs(adj), sym)}"))
        self.bold(True)
        self._line(left_right(f"TOTAL:", format_currency(total, sym)))
        self.bold(False)
        if credit_applied and float(credit_applied) > 0:
            self._line(left_right("Store Credit:", f"-{format_currency(credit_applied, sym)}"))
        self._line(left_right(f"Payment ({payment_method}):", format_currency(amount_paid, sym)))
        if change > 0:
            self._line(left_right(f"Change Returned:", format_currency(change, sym)))
        var = variance or {}
        if var and float(var.get('excess_amount') or 0) > 0:
            self.divider()
            if float(var.get('tip_amount') or 0) > 0:
                self._line(left_right("Tip:", format_currency(var.get('tip_amount'), sym)))
            if float(var.get('transport_amount') or 0) > 0:
                self._line(left_right("Transport:", format_currency(var.get('transport_amount'), sym)))
            if float(var.get('deposit_amount') or 0) > 0:
                self._line(left_right("Deposit:", format_currency(var.get('deposit_amount'), sym)))
            if float(var.get('advance_amount') or 0) > 0:
                self._line(left_right("Advance:", format_currency(var.get('advance_amount'), sym)))
            if float(var.get('misc_amount') or 0) > 0:
                cat = var.get('misc_category') or 'Misc'
                self._line(left_right(f"Misc ({cat}):", format_currency(var.get('misc_amount'), sym)))
            if wallet_balance is not None and float(var.get('deposit_amount') or 0) + float(var.get('advance_amount') or 0) > 0:
                self._line(left_right("Credit Bal:", format_currency(wallet_balance, sym)))
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
        return bytes(self._buf)


def build_receipt(sale_data, shop_name='My Shop', currency='KES',
                  footer='Thank you for shopping with us!'):
    """
    sale_data: dict with keys:
        receipt_number, created_at, cashier_name,
        subtotal, discount, tax, total,
        payment_method, amount_paid, change_amount,
        items: list of {product_name, quantity, unit_price, total}
    Returns: bytes (ESC/POS stream)
    """
    date_str = sale_data.get('created_at', datetime.now().isoformat())[:19]
    cashier  = sale_data.get('cashier_name', 'Staff')
    invoice  = sale_data.get('receipt_number', 'N/A')

    b = ReceiptBuilder(shop_name=shop_name, currency=currency)
    b.header(invoice, date_str, cashier)
    b.items(sale_data.get('items', []))
    b.totals(
        sale_data.get('subtotal', sale_data.get('total', 0)),
        sale_data.get('discount', 0),
        sale_data.get('tax', 0),
        sale_data.get('total', 0),
        sale_data.get('payment_method', 'cash'),
        sale_data.get('amount_paid', sale_data.get('total', 0)),
        sale_data.get('change_amount', 0),
        credit_applied=sale_data.get('credit_applied', 0),
        variance=sale_data.get('variance'),
        wallet_balance=sale_data.get('wallet_balance'),
        original_total=sale_data.get('original_total'),
        cash_rounding_adj=sale_data.get('cash_rounding_adj', 0),
    )
    b.footer(footer)
    return b.build()


class PrintQueue(threading.Thread):
    """
    Background thread that processes the print queue.
    If printer not available, jobs are held and retried.
    """

    def __init__(self, printer_getter):
        super().__init__(daemon=True, name="PrintQueue")
        self._q = queue.Queue()
        self.printer_getter = printer_getter  # callable → printer object or None
        self.status = "idle"  # idle / printing / error
        self._stop = threading.Event()

    def enqueue(self, data: bytes, label='receipt'):
        self._q.put({'data': data, 'label': label, 'queued_at': datetime.now()})
        logger.info(f"Print job queued: {label}")

    def stop(self):
        self._stop.set()

    def run(self):
        while not self._stop.is_set():
            try:
                job = self._q.get(timeout=2)
            except queue.Empty:
                continue

            for attempt in range(5):
                printer = self.printer_getter()
                if printer is None:
                    logger.warning(f"Printer unavailable, retry {attempt+1}/5 in 3s")
                    self.status = "error"
                    time.sleep(3)
                    continue
                try:
                    self.status = "printing"
                    printer.write(job['data'])
                    printer.flush()
                    self.status = "idle"
                    logger.info(f"Printed: {job['label']}")
                    break
                except Exception as e:
                    logger.error(f"Print error: {e}")
                    self.status = "error"
                    time.sleep(2)
            else:
                logger.error(f"Print job failed after 5 attempts: {job['label']}")
                self.status = "error"

            self._q.task_done()


def get_usb_printer(vendor_id=None, product_id=None, port=None):
    """
    Returns a file-like printer object.
    Tries: USB raw device (Linux /dev/usb/lp*), then serial port.
    """
    # Linux: /dev/usb/lp0, /dev/usb/lp1, ...
    if sys.platform.startswith('linux'):
        for lp in ['/dev/usb/lp0', '/dev/usb/lp1', '/dev/usb/lp2']:
            if os.path.exists(lp):
                try:
                    return open(lp, 'wb')
                except Exception:
                    pass

    # Windows: try to open LPT or COM port
    if sys.platform == 'win32':
        if port:
            try:
                import serial
                return serial.Serial(port, 9600, timeout=1)
            except Exception:
                pass
        # Direct LPT write
        try:
            return open('LPT1', 'wb')
        except Exception:
            pass

    # Try usb.core
    try:
        import usb.core
        kwargs = {}
        if vendor_id:
            kwargs['idVendor'] = int(vendor_id, 16) if isinstance(vendor_id, str) else vendor_id
        if product_id:
            kwargs['idProduct'] = int(product_id, 16) if isinstance(product_id, str) else product_id
        dev = usb.core.find(**kwargs) if kwargs else usb.core.find(find_all=True)
        if dev:
            if isinstance(dev, list):
                dev = next(iter(dev), None)
            if dev:
                dev.reset()
                dev.set_configuration()
                cfg = dev.get_active_configuration()
                intf = cfg[(0, 0)]
                ep = next(
                    (e for e in intf if usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT),
                    None
                )
                if ep:
                    class UsbPrinterWrapper:
                        def write(self, data):
                            ep.write(data)
                        def flush(self):
                            pass
                    return UsbPrinterWrapper()
    except Exception:
        pass

    return None


class PrinterManager:
    """
    High-level printer manager.
    Maintains PrintQueue and provides print_receipt().
    """

    def __init__(self, config_getter):
        self.config_getter = config_getter
        self._queue = PrintQueue(self._get_printer)
        self._queue.start()
        self._printer = None
        self._printer_lock = threading.Lock()

    def _get_printer(self):
        cfg = self.config_getter()
        port = cfg.get('printer_port', '')
        vendor = cfg.get('printer_vendor_id', None)
        product = cfg.get('printer_product_id', None)
        return get_usb_printer(vendor, product, port)

    def print_receipt(self, sale_data):
        cfg = self.config_getter()
        shop  = cfg.get('shop_name', 'My Shop')
        cur   = cfg.get('currency_symbol', 'KES')
        foot  = cfg.get('receipt_footer', 'Thank you for shopping with us!')
        data  = build_receipt(sale_data, shop_name=shop, currency=cur, footer=foot)
        self._queue.enqueue(data, label=sale_data.get('receipt_number', 'receipt'))

    def print_raw(self, data: bytes, label='raw'):
        self._queue.enqueue(data, label)

    def test_print(self):
        cfg = self.config_getter()
        shop = cfg.get('shop_name', 'My Shop')
        b = ReceiptBuilder(shop_name=shop)
        b.init()
        b.align('center')
        b.bold(True)
        b.text('TEST PRINT')
        b.bold(False)
        b.text('MugoByte Technologies')
        b.text('mugobyte.com')
        b.divider()
        b.text(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        b.feed(3)
        b.cut()
        self._queue.enqueue(b.build(), 'test')

    @property
    def queue_size(self):
        return self._queue._q.qsize()

    @property
    def status(self):
        return self._queue.status

    def is_printer_available(self):
        p = self._get_printer()
        if p:
            try:
                p.close()
            except Exception:
                pass
            return True
        return False


def generate_receipt_text(sale_data, shop_name='My Shop', currency='KES'):
    """Plain-text fallback invoice (for preview / non-printer output)."""
    lines = []
    W = PAPER_CHARS
    lines.append('=' * W)
    lines.append(center_text(shop_name))
    lines.append(center_text('MugoByte Technologies'))
    lines.append(center_text('mugobyte.com'))
    lines.append('=' * W)
    lines.append(f"Invoice #: {sale_data.get('receipt_number','N/A')}")
    lines.append(f"Date:      {sale_data.get('created_at','')[:19]}")
    lines.append(f"Cashier:   {sale_data.get('cashier_name','Staff')}")
    lines.append('-' * W)
    header = f"{'ITEM':<20} {'QTY':>6} {'PRICE':>9} {'TOTAL':>9}"
    lines.append(header)
    lines.append('-' * W)
    for item in sale_data.get('items', []):
        raw_name = str(item.get('product_name','') or '')
        qty_val = float(item.get('quantity', 1) or 1)
        qty = f"{qty_val:g}" if qty_val % 1 else f"{int(qty_val)}"
        price = f"{float(item.get('unit_price',0) or 0):>9.2f}"
        total = f"{float(item.get('total',0) or 0):>9.2f}"
        chunks = [raw_name[i:i+20] for i in range(0, len(raw_name), 20)] or ['']
        lines.append(f"{chunks[0]:<20} {qty:>6} {price} {total}")
        for cont in chunks[1:3]:
            lines.append(f"{cont:<20}")
    lines.append('-' * W)
    if sale_data.get('discount', 0) > 0:
        lines.append(left_right('Subtotal:', f"{sale_data.get('subtotal',0):.2f}"))
        lines.append(left_right('Discount:', f"-{sale_data.get('discount',0):.2f}"))
    if sale_data.get('tax', 0) > 0:
        lines.append(left_right('Tax:', f"{sale_data.get('tax',0):.2f}"))
    adj = float(sale_data.get('cash_rounding_adj') or 0)
    orig = sale_data.get('original_total')
    if orig is None and abs(adj) > 0.009:
        orig = float(sale_data.get('total') or 0) - adj
    pm_check = str(sale_data.get('payment_method', 'cash')).lower()
    is_electronic = any(x in pm_check for x in ('mpesa', 'm-pesa', 'card', 'bank', 'cheque', 'eft'))
    if abs(adj) > 0.009 and not is_electronic:
        if orig is not None:
            lines.append(left_right('Original Total:', f"{float(orig):,.2f}"))
        sign = '+' if adj >= 0 else '-'
        lines.append(left_right('Cash Rounding:', f"{sign}{abs(adj):,.2f}"))
    lines.append(left_right('TOTAL:', f"{currency} {sale_data.get('total',0):,.2f}"))
    credit_applied = float(sale_data.get('credit_applied') or 0)
    if credit_applied > 0:
        lines.append(left_right('Store Credit Applied:', f"-{credit_applied:,.2f}"))
    pm = str(sale_data.get('payment_method', 'cash'))
    if 'mpesa' in pm.lower() or pm.lower() == 'm-pesa':
        till = sale_data.get('mpesa_till', '')
        pb   = sale_data.get('mpesa_paybill', '')
        if till:
            lines.append(left_right('M-Pesa Till:', till))
        if pb:
            lines.append(left_right('Paybill:', pb))
        ref = sale_data.get('mpesa_ref', '')
        if ref:
            lines.append(left_right('M-Pesa Ref:', ref))
    lines.append(left_right(f"Paid ({pm}):",
                             f"{sale_data.get('amount_paid',0):,.2f}"))
    if sale_data.get('change_amount', 0) > 0:
        lines.append(left_right('Change Returned:', f"{sale_data.get('change_amount',0):,.2f}"))
    # Payment variance split (excess Till / M-Pesa)
    var = sale_data.get('variance') or {}
    if var and float(var.get('excess_amount') or 0) > 0:
        lines.append('-' * W)
        lines.append(center_text('*** PAYMENT VARIANCE ***'))
        excess = float(var.get('excess_amount') or 0)
        handling = (var.get('handling') or '').lower()
        if float(var.get('tip_amount') or 0) > 0:
            lines.append(left_right('Tip:', f"{var.get('tip_amount'):,.2f}"))
        if float(var.get('transport_amount') or 0) > 0:
            lines.append(left_right('Transport/Delivery:', f"{var.get('transport_amount'):,.2f}"))
        if float(var.get('deposit_amount') or 0) > 0:
            lines.append(left_right('Customer Deposit:', f"{var.get('deposit_amount'):,.2f}"))
        if float(var.get('advance_amount') or 0) > 0:
            lines.append(left_right('Advance Payment:', f"{var.get('advance_amount'):,.2f}"))
        if float(var.get('misc_amount') or 0) > 0:
            cat = var.get('misc_category') or 'Misc'
            lines.append(left_right(f'Misc ({cat}):', f"{var.get('misc_amount'):,.2f}"))
        if float(var.get('change_returned') or 0) > 0 and not sale_data.get('change_amount'):
            lines.append(left_right('Change Returned:', f"{var.get('change_returned'):,.2f}"))
        if handling in ('deposit', 'advance') and sale_data.get('wallet_balance') is not None:
            lines.append(left_right('Credit Balance:',
                                    f"{currency} {float(sale_data.get('wallet_balance')):,.2f}"))
        if var.get('reason'):
            lines.append(left_right('Note:', str(var.get('reason'))[:28]))
    # ── Part payment / credit sale (debt) block ──────────────────────────────
    pm_low = pm.lower()
    if pm_low in ('part payment', 'credit sale', 'credit'):
        balance = round(float(sale_data.get('total', 0) or 0)
                        - float(sale_data.get('amount_paid', 0) or 0)
                        - credit_applied, 2)
        if balance > 0:
            lines.append('-' * W)
            lines.append(center_text('*** CREDIT SALE ***' if pm_low != 'part payment'
                                     else '*** PART PAYMENT ***'))
            if sale_data.get('customer_name'):
                lines.append(left_right('Customer:', str(sale_data.get('customer_name'))))
            if sale_data.get('debt_invoice_number'):
                lines.append(left_right('Debt Invoice:', str(sale_data.get('debt_invoice_number'))))
            if sale_data.get('due_date'):
                lines.append(left_right('Due Date:', str(sale_data.get('due_date'))))
            lines.append(left_right('Outstanding Balance:', f"{currency} {balance:,.2f}"))
    lines.append('=' * W)
    lines.append(center_text(sale_data.get('receipt_footer', 'Thank you!')))
    lines.append(center_text('Powered by MugoByte Technologies'))
    lines.append(center_text('mugobyte.com'))
    lines.append('=' * W)
    return '\n'.join(lines)
