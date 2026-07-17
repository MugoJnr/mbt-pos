"""
MBT POS — Centralized State Reset Manager
MugoByte Technologies

Completed workflows leave clean defaults. POS credit sales must return to
Walk-in customer (never leave the previous credit customer selected).

Smart exceptions (do NOT call reset prematurely):
  stock count sessions, bulk import, batch price changes,
  report filters, Settings edits in progress, setup wizards.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from PyQt5.QtCore import QDate, Qt, QTimer
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QDoubleSpinBox, QLineEdit,
    QPlainTextEdit, QSpinBox, QTextEdit, QWidget,
)

log = logging.getLogger(__name__)

# Settings keys (Settings → Workflow / After Sale)
AFTER_SALE_DEFAULT_CUSTOMER = 'after_sale_default_customer'
AFTER_SALE_DEFAULT_PAYMENT = 'after_sale_default_payment'
AFTER_SALE_FOCUS_BARCODE = 'after_sale_focus_barcode'
AFTER_SALE_AUTO_CLEAR_CART = 'after_sale_auto_clear_cart'
AFTER_SALE_RESET_DISCOUNTS = 'after_sale_reset_discounts'
AFTER_SALE_RESET_NOTES = 'after_sale_reset_notes'

_DEFAULTS = {
    AFTER_SALE_DEFAULT_CUSTOMER: 'walk_in',
    AFTER_SALE_DEFAULT_PAYMENT: 'Cash',
    AFTER_SALE_FOCUS_BARCODE: '1',
    AFTER_SALE_AUTO_CLEAR_CART: '1',
    AFTER_SALE_RESET_DISCOUNTS: '1',
    AFTER_SALE_RESET_NOTES: '1',
}


def workflow_defaults() -> dict:
    return dict(_DEFAULTS)


def workflow_settings(cfg: Optional[dict] = None) -> dict:
    """Resolved After Sale workflow flags from settings dict."""
    cfg = cfg or {}
    out = {}
    for key, default in _DEFAULTS.items():
        val = cfg.get(key, default)
        if val is None or val == '':
            val = default
        out[key] = str(val)
    return out


def _safe_clear_text(w) -> None:
    if w is None:
        return
    try:
        if hasattr(w, 'blockSignals'):
            w.blockSignals(True)
        if hasattr(w, 'clear'):
            w.clear()
        elif hasattr(w, 'setText'):
            w.setText('')
        elif hasattr(w, 'setPlainText'):
            w.setPlainText('')
    except Exception:
        pass
    finally:
        try:
            if hasattr(w, 'blockSignals'):
                w.blockSignals(False)
        except Exception:
            pass


def _safe_set_spin(w, value: float = 0.0) -> None:
    if w is None:
        return
    try:
        w.blockSignals(True)
        w.setValue(value)
    except Exception:
        pass
    finally:
        try:
            w.blockSignals(False)
        except Exception:
            pass


def _focus_widget(w) -> None:
    if w is None:
        return

    def _do():
        try:
            w.setFocus(Qt.OtherFocusReason)
            if hasattr(w, 'selectAll'):
                w.selectAll()
        except Exception:
            try:
                w.setFocus()
            except Exception:
                pass

    QTimer.singleShot(0, _do)


class StateResetManager:
    """Central helpers to restore module defaults after successful workflows."""

    # ── POS ───────────────────────────────────────────────────────────────────

    @staticmethod
    def reset_pos(tab, settings: Optional[dict] = None, *,
                  force_walk_in: bool = True) -> None:
        """
        After a successful sale (cash / M-Pesa / credit / split) or Clear cart.

        Always restores customer to Walk-in when force_walk_in=True (critical
        credit-sale fix). Other behaviours follow Settings → Workflow.
        """
        if tab is None:
            return
        try:
            cfg = settings
            if cfg is None and hasattr(tab, 'config_getter'):
                cfg = tab.config_getter() or {}
            wf = workflow_settings(cfg)
        except Exception:
            wf = workflow_settings({})

        # Cart
        if wf.get(AFTER_SALE_AUTO_CLEAR_CART, '1') == '1':
            try:
                if hasattr(tab, 'cart') and isinstance(tab.cart, list):
                    tab.cart.clear()
            except Exception:
                pass

        # Discounts
        if wf.get(AFTER_SALE_RESET_DISCOUNTS, '1') == '1':
            disc = getattr(tab, '_disc', None)
            if disc is not None:
                try:
                    disc.blockSignals(True)
                    disc.setText('0.00')
                except Exception:
                    pass
                finally:
                    try:
                        disc.blockSignals(False)
                    except Exception:
                        pass

        # Paid / change / rounding / store-credit / split tender
        try:
            # Allow Cash Paid smart auto-fill on the next sale
            tab._cash_paid_dirty = False
            tab._paid_programmatic = False
        except Exception:
            pass
        _safe_set_spin(getattr(tab, '_paid', None), 0)
        _safe_set_spin(getattr(tab, '_elec_paid', None), 0)
        _safe_set_spin(getattr(tab, '_credit_spin', None), 0)
        try:
            tab._credit_to_apply = 0.0
        except Exception:
            pass
        try:
            tab._rounding_adj = 0.0
            tab._rounding_info = {}
        except Exception:
            pass

        # Notes + M-Pesa ref + temp refs
        if wf.get(AFTER_SALE_RESET_NOTES, '1') == '1':
            _safe_clear_text(getattr(tab, '_note', None))
        _safe_clear_text(getattr(tab, '_mpesa_ref', None))

        # Optional future fields (salesperson / delivery / split refs)
        for attr in (
            '_salesperson', '_sales_person', '_delivery', '_delivery_note',
            '_split_ref', '_temp_ref', '_order_ref',
        ):
            _safe_clear_text(getattr(tab, attr, None))
            w = getattr(tab, attr, None)
            if w is not None and hasattr(w, 'setCurrentIndex'):
                try:
                    w.blockSignals(True)
                    w.setCurrentIndex(0)
                except Exception:
                    pass
                finally:
                    try:
                        w.blockSignals(False)
                    except Exception:
                        pass

        # Customer → Walk-in (critical)
        if force_walk_in or wf.get(AFTER_SALE_DEFAULT_CUSTOMER, 'walk_in') == 'walk_in':
            StateResetManager._select_walk_in(getattr(tab, '_customer', None))
            try:
                if hasattr(tab, '_on_customer_changed'):
                    tab._on_customer_changed()
            except Exception:
                pass

        # Payment → default (Cash from settings)
        pay_name = wf.get(AFTER_SALE_DEFAULT_PAYMENT, 'Cash') or 'Cash'
        StateResetManager._select_payment(tab, pay_name)

        # Barcode / product search
        search = getattr(tab, '_search', None)
        _safe_clear_text(search)
        try:
            if hasattr(tab, '_filter'):
                tab._filter()
        except Exception:
            pass

        # Refresh cart totals / UI
        try:
            if hasattr(tab, '_refresh_cart'):
                tab._refresh_cart()
        except Exception:
            pass

        if wf.get(AFTER_SALE_FOCUS_BARCODE, '1') == '1':
            _focus_widget(search)

    @staticmethod
    def _select_walk_in(customer_widget) -> None:
        if customer_widget is None:
            return
        try:
            if hasattr(customer_widget, 'select_walk_in'):
                customer_widget.select_walk_in()
                return
        except Exception:
            pass
        try:
            customer_widget.blockSignals(True)
            # Prefer item with data None (Walk-in)
            idx = -1
            if hasattr(customer_widget, 'findData'):
                idx = customer_widget.findData(None)
            if idx < 0:
                for i in range(customer_widget.count()):
                    txt = (customer_widget.itemText(i) or '').lower()
                    if 'walk-in' in txt or 'walk in' in txt:
                        idx = i
                        break
            customer_widget.setCurrentIndex(idx if idx >= 0 else 0)
        except Exception as e:
            log.debug('select_walk_in failed: %s', e)
        finally:
            try:
                customer_widget.blockSignals(False)
            except Exception:
                pass

    @staticmethod
    def _select_payment(tab, method: str) -> None:
        method = (method or 'Cash').strip()
        try:
            if hasattr(tab, '_select_pay_method'):
                tab._select_pay_method(method)
                return
        except Exception:
            pass
        pay = getattr(tab, '_pay', None)
        if pay is None:
            return
        try:
            if hasattr(pay, 'set_value') and pay.set_value(method):
                return
        except Exception:
            pass
        try:
            idx = pay.findText(method)
            if idx >= 0:
                pay.setCurrentIndex(idx)
            elif pay.count() > 0:
                pay.setCurrentIndex(0)
        except Exception:
            pass
        seg = getattr(tab, '_pay_seg', None)
        if seg is not None and hasattr(seg, 'select'):
            try:
                seg.select(method, emit=False)
            except Exception:
                pass

    # ── Product / purchase / stock ────────────────────────────────────────────

    @staticmethod
    def reset_product_form(dlg) -> None:
        """Clear add-product dialog fields to blank defaults."""
        if dlg is None:
            return
        for attr, default in (
            ('name', ''), ('sku', ''), ('cat', ''), ('unit', 'pcs'),
        ):
            w = getattr(dlg, attr, None)
            if w is None:
                continue
            try:
                if default:
                    w.setText(default)
                else:
                    w.clear()
            except Exception:
                pass
        for attr in ('price', 'cost', 'stock'):
            _safe_set_spin(getattr(dlg, attr, None), 0)
        mins = getattr(dlg, 'mins', None)
        if mins is not None:
            _safe_set_spin(mins, 5)

    @staticmethod
    def reset_purchase_form(form) -> None:
        """Clear purchase / goods-received entry form if present."""
        if form is None:
            return
        StateResetManager.wipe_transient_fields(form, keep_dates=False)
        for attr in (
            '_supplier', 'supplier', '_items', 'items', '_lines', 'lines',
            '_ref', 'ref', '_invoice', 'invoice', '_notes', 'notes',
        ):
            w = getattr(form, attr, None)
            if isinstance(w, list):
                try:
                    w.clear()
                except Exception:
                    pass
            else:
                _safe_clear_text(w)
                if w is not None and hasattr(w, 'setCurrentIndex'):
                    try:
                        w.setCurrentIndex(0)
                    except Exception:
                        pass
        if hasattr(form, '_rebuild_table'):
            try:
                form._rebuild_table()
            except Exception:
                pass

    @staticmethod
    def reset_stock_adjustment(form=None) -> None:
        """
        Stock adjustment uses one-shot dialogs (QInputDialog) — nothing sticky.
        Provided for API completeness / future form-based adjust UI.
        """
        if form is None:
            return
        StateResetManager.wipe_transient_fields(form)
        for attr in ('_reason', 'reason', '_qty', 'qty', '_product', 'product'):
            w = getattr(form, attr, None)
            _safe_clear_text(w)
            _safe_set_spin(w, 0)
            if w is not None and hasattr(w, 'setCurrentIndex'):
                try:
                    w.setCurrentIndex(0)
                except Exception:
                    pass

    # ── Customer ──────────────────────────────────────────────────────────────

    @staticmethod
    def reset_customer_form(dlg) -> None:
        if dlg is None:
            return
        for attr in ('name', 'phone', 'email', 'addr', 'nid', 'notes'):
            w = getattr(dlg, attr, None)
            if w is None:
                continue
            try:
                if hasattr(w, 'setPlainText'):
                    w.setPlainText('')
                elif hasattr(w, 'clear'):
                    w.clear()
                elif hasattr(w, 'setText'):
                    w.setText('')
            except Exception:
                pass
        lim = getattr(dlg, 'limit', None)
        if lim is not None:
            _safe_set_spin(lim, 0)
        ct = getattr(dlg, 'cust_type', None)
        if ct is not None and hasattr(ct, 'setCurrentIndex'):
            try:
                ct.setCurrentIndex(0)
            except Exception:
                pass

    # ── Consumption ───────────────────────────────────────────────────────────

    @staticmethod
    def reset_consumption(pane) -> None:
        """After successful internal consumption — new AUTO ref, clear lines."""
        if pane is None:
            return
        try:
            if hasattr(pane, '_lines') and isinstance(pane._lines, list):
                pane._lines.clear()
        except Exception:
            pass
        _safe_clear_text(getattr(pane, '_notes', None))
        _safe_clear_text(getattr(pane, '_taken', None))
        _safe_clear_text(getattr(pane, '_search', None))
        reason = getattr(pane, '_reason', None)
        if reason is not None:
            try:
                if hasattr(reason, 'clear_selection'):
                    reason.clear_selection()
                elif hasattr(reason, 'setCurrentIndex'):
                    reason.setCurrentIndex(0)
            except Exception:
                pass
        date_w = getattr(pane, '_date', None)
        if date_w is not None and hasattr(date_w, 'setDate'):
            try:
                date_w.setDate(QDate.currentDate())
            except Exception:
                pass
        try:
            if hasattr(pane, 'refresh'):
                pane.refresh()  # peeks next AUTO-###### ref
            elif hasattr(pane, '_rebuild_table'):
                pane._rebuild_table()
        except Exception:
            pass

    # ── Debt payment ──────────────────────────────────────────────────────────

    @staticmethod
    def reset_debt_payment(dlg) -> None:
        """Clear payment amount / notes / method after successful collect."""
        if dlg is None:
            return
        _safe_clear_text(getattr(dlg, 'notes', None))
        amt = getattr(dlg, 'amount', None)
        if amt is not None:
            _safe_set_spin(amt, 0)
        method = getattr(dlg, 'method', None)
        if method is not None and hasattr(method, 'setCurrentIndex'):
            try:
                method.setCurrentIndex(0)  # Cash
            except Exception:
                pass

    @staticmethod
    def after_debt_payment(debt_tab) -> None:
        """Return focus to debt list and clear transient invoice searches."""
        if debt_tab is None:
            return
        try:
            tabs = getattr(debt_tab, '_tabs', None)
            inv = getattr(debt_tab, '_invoices_tab', None)
            if tabs is not None and inv is not None:
                idx = tabs.indexOf(inv)
                if idx >= 0:
                    tabs.setCurrentIndex(idx)
        except Exception:
            pass
        for sub in (
            getattr(debt_tab, '_invoices_tab', None),
            getattr(debt_tab, '_customers_tab', None),
            getattr(debt_tab, '_payments_tab', None),
        ):
            if sub is None:
                continue
            _safe_clear_text(getattr(sub, '_search', None))
            try:
                if hasattr(sub, 'refresh'):
                    sub.refresh()
            except Exception:
                pass
        try:
            ov = getattr(debt_tab, '_overview_tab', None)
            if ov is not None and hasattr(ov, 'refresh'):
                ov.refresh()
        except Exception:
            pass

    # ── Modal helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def wipe_transient_fields(root: Optional[QWidget], *,
                              keep_dates: bool = True) -> None:
        """Clear line edits / spins / plain texts under a widget tree."""
        if root is None:
            return
        try:
            widgets = root.findChildren(QWidget)
        except Exception:
            return
        for w in widgets:
            try:
                name = (w.objectName() or '')
                # Never wipe report filters / settings / wizard marked widgets
                if name.startswith('keep_') or name.startswith('report_'):
                    continue
                if isinstance(w, (QLineEdit, QPlainTextEdit, QTextEdit)):
                    _safe_clear_text(w)
                elif isinstance(w, (QDoubleSpinBox, QSpinBox)):
                    _safe_set_spin(w, 0)
                elif isinstance(w, QCheckBox):
                    w.blockSignals(True)
                    w.setChecked(False)
                    w.blockSignals(False)
                elif isinstance(w, QDateEdit) and not keep_dates:
                    w.setDate(QDate.currentDate())
                elif isinstance(w, QComboBox) and not name.startswith('persist_'):
                    # Only reset if empty-data placeholder style; skip otherwise
                    pass
            except Exception:
                continue

    @staticmethod
    def clear_modal_on_close(dialog, wipe: Optional[Callable] = None) -> None:
        """
        On reject / close without accept → wipe temp form / validation / search.
        Call once after building the dialog.
        """
        if dialog is None:
            return
        if getattr(dialog, '_mbt_reset_hooked', False):
            return
        dialog._mbt_reset_hooked = True

        def _on_finished(result: int) -> None:
            # QDialog.Accepted == 1 — keep values only on accept (dialog closes)
            try:
                from PyQt5.QtWidgets import QDialog
                if int(result) == int(QDialog.Accepted):
                    return
            except Exception:
                if int(result) == 1:
                    return
            try:
                if wipe:
                    wipe()
                else:
                    StateResetManager.wipe_transient_fields(dialog)
            except Exception as e:
                log.debug('modal wipe failed: %s', e)

        try:
            dialog.finished.connect(_on_finished)
        except Exception:
            pass

    @staticmethod
    def clear_search(*widgets) -> None:
        for w in widgets:
            _safe_clear_text(w)
