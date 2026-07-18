"""
MBT POS — Centralized Smart Auto-Fill Service
MugoByte Technologies

Fills safe defaults across modules. Never auto-fills:
  payment amounts (except POS Cash Paid rules), void/adj/consumption reasons,
  notes, or discretionary discounts.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# Settings keys
AUTOFILL_CASH_PAID = 'autofill_cash_paid'
AUTOFILL_PRODUCT_DEFAULTS = 'autofill_product_defaults'
AUTOFILL_REPORTS_TODAY = 'autofill_reports_today'
AUTOFILL_CLEAR_SEARCH_ON_LEAVE = 'autofill_clear_search_on_leave'
AUTOFILL_SUPPLIER_DETAILS = 'autofill_supplier_details'
AUTOFILL_CREDIT_CUSTOMER_INFO = 'autofill_credit_customer_info'
AUTOFILL_DEFAULT_PAYMENT = 'autofill_default_payment'
AUTOFILL_DEFAULT_UNIT = 'autofill_default_unit'
AUTOFILL_DEFAULT_MIN_STOCK = 'autofill_default_min_stock'

_DEFAULTS = {
    AUTOFILL_CASH_PAID: '1',
    AUTOFILL_PRODUCT_DEFAULTS: '1',
    AUTOFILL_REPORTS_TODAY: '1',
    AUTOFILL_CLEAR_SEARCH_ON_LEAVE: '1',
    AUTOFILL_SUPPLIER_DETAILS: '1',
    AUTOFILL_CREDIT_CUSTOMER_INFO: '1',
    AUTOFILL_DEFAULT_PAYMENT: 'Cash',
    AUTOFILL_DEFAULT_UNIT: 'pcs',
    AUTOFILL_DEFAULT_MIN_STOCK: '5',
}

# Methods that use Cash Paid spin + Change / Remaining Balance
CASH_LIKE_METHODS = frozenset({'cash', 'mixed'})

# Electronic: hide Cash Paid / Change; amount due recorded silently
ELECTRONIC_HIDE_CASH_UI = frozenset({
    'card', 'bank transfer', 'cheque', 'check', 'airtel money',
})

# Never auto-fill these field categories (documentation / guards)
NEVER_AUTOFILL = frozenset({
    'payment_amount', 'void_reason', 'adjustment_reason',
    'consumption_reason', 'notes', 'discretionary_discount',
})


def autofill_defaults() -> dict:
    return dict(_DEFAULTS)


def autofill_settings(cfg: Optional[dict] = None) -> dict:
    cfg = cfg or {}
    out = {}
    for key, default in _DEFAULTS.items():
        val = cfg.get(key, default)
        if val is None or val == '':
            val = default
        out[key] = str(val)
    return out


def _flag(cfg: Optional[dict], key: str, default: str = '1') -> bool:
    st = autofill_settings(cfg)
    return str(st.get(key, default)).strip() in ('1', 'true', 'True', 'yes')


def _norm_phone(phone: str) -> str:
    digits = re.sub(r'\D+', '', phone or '')
    if len(digits) >= 9 and digits.startswith('254'):
        digits = '0' + digits[3:]
    if len(digits) == 9 and digits[0] == '7':
        digits = '0' + digits
    return digits


def phone_format_ok(phone: str) -> bool:
    """True when phone is empty (optional) or has a plausible digit length."""
    raw = (phone or '').strip()
    if not raw:
        return True
    digits = re.sub(r'\D+', '', raw)
    return 9 <= len(digits) <= 15


class SearchMemory:
    """Per-module search text; cleared on leave unless pinned."""

    def __init__(self):
        self._values: Dict[str, str] = {}
        self._pinned: Dict[str, bool] = {}

    def get(self, module: str) -> str:
        return self._values.get(module, '')

    def set(self, module: str, text: str) -> None:
        self._values[module] = text or ''

    def pin(self, module: str, pinned: bool = True) -> None:
        self._pinned[module] = bool(pinned)

    def is_pinned(self, module: str) -> bool:
        return bool(self._pinned.get(module))

    def clear_on_leave(self, module: str, *, force: bool = False) -> None:
        if force or not self.is_pinned(module):
            self._values.pop(module, None)


_SEARCH_MEMORY = SearchMemory()


class AutoFillService:
    """Reusable auto-fill helpers for desktop POS modules."""

    search_memory = _SEARCH_MEMORY

    # ── Settings helpers ──────────────────────────────────────────────────────

    @staticmethod
    def enabled(cfg: Optional[dict], key: str) -> bool:
        return _flag(cfg, key)

    @staticmethod
    def cash_paid_enabled(cfg: Optional[dict] = None) -> bool:
        return _flag(cfg, AUTOFILL_CASH_PAID)

    @staticmethod
    def default_payment(cfg: Optional[dict] = None) -> str:
        st = autofill_settings(cfg)
        # Prefer State Reset After Sale default when present
        try:
            from desktop.utils.state_reset import (
                AFTER_SALE_DEFAULT_PAYMENT, workflow_settings,
            )
            wf = workflow_settings(cfg)
            pay = (wf.get(AFTER_SALE_DEFAULT_PAYMENT) or '').strip()
            if pay:
                return pay
        except Exception:
            pass
        return (st.get(AUTOFILL_DEFAULT_PAYMENT) or 'Cash').strip() or 'Cash'

    # ── New sale ──────────────────────────────────────────────────────────────

    @staticmethod
    def new_sale_defaults(cfg: Optional[dict] = None,
                          user: Optional[dict] = None) -> dict:
        """Walk-in, default payment, today, logged-in cashier — no payment amounts."""
        pay = AutoFillService.default_payment(cfg)
        cashier = ''
        if user:
            cashier = (
                user.get('full_name')
                or user.get('username')
                or user.get('name')
                or ''
            )
        return {
            'customer': 'walk_in',
            'payment_method': pay,
            'sale_date': date.today().isoformat(),
            'cashier': cashier,
            # Explicit: never invent cash/card amounts here
            'amount_paid': None,
            'discount': None,
            'notes': None,
        }

    @staticmethod
    def apply_new_sale_shell(tab, cfg: Optional[dict] = None) -> None:
        """
        Light defaults for a fresh POS shell (customer + payment).
        Prefer StateResetManager.reset_pos after a completed sale.
        """
        if tab is None:
            return
        try:
            from desktop.utils.state_reset import StateResetManager
            StateResetManager.reset_pos(tab, cfg, force_walk_in=True)
        except Exception as e:
            log.debug('apply_new_sale_shell via StateReset failed: %s', e)

    # ── Cash Paid (POS) ───────────────────────────────────────────────────────

    @staticmethod
    def is_cash_like(method: Optional[str]) -> bool:
        m = (method or '').strip().lower()
        return m in CASH_LIKE_METHODS

    @staticmethod
    def hides_cash_paid_ui(method: Optional[str]) -> bool:
        m = (method or '').strip().lower()
        return m in ELECTRONIC_HIDE_CASH_UI

    @staticmethod
    def should_autofill_cash_paid(
            method: Optional[str],
            *,
            dirty: bool,
            cfg: Optional[dict] = None) -> bool:
        if dirty:
            return False
        if not AutoFillService.cash_paid_enabled(cfg):
            return False
        return AutoFillService.is_cash_like(method)

    @staticmethod
    def cash_change_state(paid: float, due: float) -> dict:
        """
        Live Change / Remaining Balance styling.
        Returns label, amount, tone in {ok, warn, err}.
        """
        paid = round(float(paid or 0), 2)
        due = round(float(due or 0), 2)
        diff = round(paid - due, 2)
        if paid < 0:
            return {
                'label': 'Invalid',
                'amount': abs(paid),
                'tone': 'err',
                'diff': diff,
            }
        if diff > 0.009:
            return {
                'label': 'Change',
                'amount': diff,
                'tone': 'ok',
                'diff': diff,
            }
        if diff < -0.009:
            return {
                'label': 'Remaining Balance',
                'amount': abs(diff),
                'tone': 'warn',
                'diff': diff,
            }
        return {
            'label': 'Change',
            'amount': 0.0,
            'tone': 'ok',
            'diff': 0.0,
        }

    # ── Product create ────────────────────────────────────────────────────────

    @staticmethod
    def product_create_defaults(cfg: Optional[dict] = None) -> dict:
        if not _flag(cfg, AUTOFILL_PRODUCT_DEFAULTS):
            return {}
        st = autofill_settings(cfg)
        try:
            min_stock = int(float(st.get(AUTOFILL_DEFAULT_MIN_STOCK) or 5))
        except (TypeError, ValueError):
            min_stock = 5
        currency = 'KES'
        tax_rate = 0.0
        if cfg:
            currency = cfg.get('currency_symbol') or cfg.get('currency') or 'KES'
            try:
                tax_rate = float(cfg.get('tax_rate') or 0)
            except (TypeError, ValueError):
                tax_rate = 0.0
        return {
            'unit': (st.get(AUTOFILL_DEFAULT_UNIT) or 'pcs').strip() or 'pcs',
            'min_stock': min_stock,
            'status': 'Active',
            'currency': currency,
            'tax_rate': tax_rate,
            'stock': 0.0,
            'price': 0.0,
            'cost_price': 0.0,
        }

    @staticmethod
    def apply_product_create_defaults(dlg, cfg: Optional[dict] = None) -> None:
        if dlg is None or not getattr(dlg, '_is_new', False):
            return
        defaults = AutoFillService.product_create_defaults(cfg)
        if not defaults:
            return
        try:
            if hasattr(dlg, 'unit') and dlg.unit and not (dlg.unit.text() or '').strip():
                dlg.unit.setText(defaults['unit'])
            if hasattr(dlg, 'mins') and dlg.mins is not None:
                dlg.mins.setValue(int(defaults['min_stock']))
            if hasattr(dlg, 'stock') and dlg.stock is not None:
                dlg.stock.setValue(float(defaults.get('stock') or 0))
        except Exception as e:
            log.debug('product defaults apply failed: %s', e)

    # ── Supplier ──────────────────────────────────────────────────────────────

    @staticmethod
    def supplier_fill_fields(supplier: Optional[dict],
                             cfg: Optional[dict] = None) -> dict:
        """Map supplier record → address/phone/email/terms/currency fields."""
        if not supplier or not _flag(cfg, AUTOFILL_SUPPLIER_DETAILS):
            return {}
        currency = (cfg or {}).get('currency_symbol') or 'KES'
        return {
            'address': supplier.get('address') or '',
            'phone': supplier.get('phone') or '',
            'email': supplier.get('email') or '',
            'terms': supplier.get('payment_terms') or supplier.get('terms') or '',
            'currency': supplier.get('currency') or currency,
            'name': supplier.get('name') or '',
        }

    # ── Credit customer ───────────────────────────────────────────────────────

    @staticmethod
    def credit_customer_summary(customer: Optional[dict],
                                cfg: Optional[dict] = None) -> dict:
        if not customer or not _flag(cfg, AUTOFILL_CREDIT_CUSTOMER_INFO):
            return {}
        return {
            'balance': float(customer.get('wallet_balance') or 0),
            'credit_limit': float(customer.get('credit_limit') or 0),
            'outstanding': float(customer.get('total_outstanding') or 0),
            'last_purchase': (
                customer.get('last_purchase')
                or customer.get('last_sale_at')
                or customer.get('updated_at')
                or ''
            ),
            'name': customer.get('name') or '',
            'phone': customer.get('phone') or '',
        }

    @staticmethod
    def format_credit_customer_hint(summary: dict, currency: str = 'KES') -> str:
        if not summary:
            return ''
        parts = []
        out = float(summary.get('outstanding') or 0)
        lim = float(summary.get('credit_limit') or 0)
        bal = float(summary.get('balance') or 0)
        if out > 0.009:
            parts.append(f'Owing {currency} {out:,.2f}')
        if lim > 0.009:
            parts.append(f'Limit {currency} {lim:,.2f}')
        if bal > 0.009:
            parts.append(f'Credit {currency} {bal:,.2f}')
        last = (summary.get('last_purchase') or '')[:10]
        if last:
            parts.append(f'Last {last}')
        return ' · '.join(parts)

    # ── Debt ──────────────────────────────────────────────────────────────────

    @staticmethod
    def debt_open_defaults(customer: Optional[dict] = None,
                           invoice: Optional[dict] = None) -> dict:
        outstanding = 0.0
        if invoice:
            outstanding = float(
                invoice.get('balance')
                or invoice.get('outstanding')
                or 0)
        elif customer:
            outstanding = float(customer.get('total_outstanding') or 0)
        return {
            'customer_id': (customer or {}).get('id'),
            'invoice_id': (invoice or {}).get('id'),
            'invoice_number': (invoice or {}).get('invoice_number') or '',
            'outstanding': outstanding,
            'payment_date': date.today().isoformat(),
            # Never invent payment amount — caller may copy outstanding if desired
            'amount': None,
            'notes': None,
            'reason': None,
        }

    # ── Stock / consumption product select ────────────────────────────────────

    @staticmethod
    def product_stock_fields(product: Optional[dict]) -> dict:
        if not product:
            return {}
        return {
            'product_id': product.get('id'),
            'name': product.get('name') or '',
            'sku': product.get('sku') or '',
            'barcode': product.get('barcode') or '',
            'stock': float(product.get('stock') or 0),
            'unit': product.get('unit') or 'pcs',
            'cost_price': float(product.get('cost_price') or 0),
            'price': float(product.get('price') or 0),
            'min_stock': float(product.get('min_stock') or 0),
            # Never fill reason
            'reason': None,
            'notes': None,
        }

    @staticmethod
    def barcode_product_fill(product: Optional[dict],
                             *, qty: float = 1.0) -> dict:
        fields = AutoFillService.product_stock_fields(product)
        if not fields:
            return {}
        fields['quantity'] = float(qty)  # editable by cashier
        return fields

    # ── Duplicate phone ───────────────────────────────────────────────────────

    @staticmethod
    def find_customers_by_phone(api, phone: str) -> List[dict]:
        phone_n = _norm_phone(phone)
        if not phone_n or not api:
            return []
        try:
            customers = api.get_customers() or []
        except Exception:
            return []
        hits = []
        for c in customers:
            if _norm_phone(c.get('phone') or '') == phone_n:
                hits.append(c)
        return hits

    @staticmethod
    def prompt_use_existing_customer(parent, api, phone: str) -> Optional[int]:
        """
        If phone already exists, ask Use Existing / Create New.
        Returns existing customer_id, None to continue create, or -1 to cancel.
        Skips entirely when phone is empty (phone is optional).
        """
        if not (phone or '').strip():
            return None
        hits = AutoFillService.find_customers_by_phone(api, phone)
        if not hits:
            return None
        try:
            from PyQt5.QtWidgets import QMessageBox
        except Exception:
            return None
        c = hits[0]
        name = c.get('name') or 'Existing customer'
        ph = c.get('phone') or phone
        msg = (
            f'A customer with phone {ph} already exists:\n\n'
            f'  {name}\n\n'
            f'Use the existing customer instead of creating a duplicate?'
        )
        box = QMessageBox(parent)
        box.setWindowTitle('Duplicate Phone')
        box.setIcon(QMessageBox.Question)
        box.setText(msg)
        use_btn = box.addButton('Use Existing', QMessageBox.AcceptRole)
        box.addButton('Create New Anyway', QMessageBox.DestructiveRole)
        cancel_btn = box.addButton(QMessageBox.Cancel)
        box.exec_()
        clicked = box.clickedButton()
        if clicked == cancel_btn:
            return -1
        if clicked == use_btn:
            try:
                return int(c['id'])
            except (TypeError, ValueError, KeyError):
                return -1
        return None  # create new anyway

    # ── Reports ───────────────────────────────────────────────────────────────

    @staticmethod
    def reports_default_preset(cfg: Optional[dict] = None) -> str:
        if _flag(cfg, AUTOFILL_REPORTS_TODAY):
            return 'today'
        return 'today'

    @staticmethod
    def apply_reports_default_dates(tab, cfg: Optional[dict] = None) -> None:
        if tab is None or not _flag(cfg, AUTOFILL_REPORTS_TODAY):
            return
        try:
            if hasattr(tab, '_on_preset'):
                tab._on_preset('today')
            elif hasattr(tab, '_preset') and hasattr(tab._preset, 'set_value'):
                tab._preset.set_value('today')
        except Exception as e:
            log.debug('reports today default failed: %s', e)

    # ── Module search memory ──────────────────────────────────────────────────

    @staticmethod
    def remember_search(module: str, text: str) -> None:
        AutoFillService.search_memory.set(module, text)

    @staticmethod
    def pin_search(module: str, pinned: bool = True) -> None:
        AutoFillService.search_memory.pin(module, pinned)

    @staticmethod
    def on_module_leave(module: str, widget=None,
                        cfg: Optional[dict] = None) -> None:
        """Clear module search unless pinned (or setting disabled)."""
        if not _flag(cfg, AUTOFILL_CLEAR_SEARCH_ON_LEAVE):
            return
        mem = AutoFillService.search_memory
        if mem.is_pinned(module):
            return
        mem.clear_on_leave(module)
        if widget is None:
            return
        for attr in ('_search', 'search', '_filter_edit'):
            w = getattr(widget, attr, None)
            if w is None:
                continue
            try:
                if hasattr(w, 'blockSignals'):
                    w.blockSignals(True)
                if hasattr(w, 'clear'):
                    w.clear()
                elif hasattr(w, 'setText'):
                    w.setText('')
            except Exception:
                pass
            finally:
                try:
                    if hasattr(w, 'blockSignals'):
                        w.blockSignals(False)
                except Exception:
                    pass

    @staticmethod
    def guards_never_autofill(field_kind: str) -> bool:
        return (field_kind or '').strip().lower() in NEVER_AUTOFILL
