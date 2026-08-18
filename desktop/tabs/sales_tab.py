"""MBT POS — Point of Sale  |  MugoByte Technologies"""
from PyQt5.QtWidgets import *
from PyQt5.QtCore    import *
from PyQt5.QtGui     import *
from datetime        import datetime
import time
from desktop.utils.theme   import C, ThemeManager, qss_alpha, RADIUS, PADDING, GAP
from desktop.utils.widgets import (Card, H2, Caption, PrimaryBtn, SecondaryBtn,
                                    DangerBtn, IconBtn)
from desktop.utils.pos_components import (
    ProductCard, ProductGrid, PaymentSegment, SummaryCard,
    CustomerCard, CartList, PosSearchBar,
    safe_price as _safe_price,
    fmt_stock_short as _fmt_stock_short, round_qty, refresh_pos_components,
)
from desktop.utils.option_lists import POS_PAYMENT_METHODS
from desktop.utils.select_controls import Select
from desktop.utils.quiet_ui import info_toast, sale_complete_feedback, soft_warn


def _sfx(event: str, **kw):
    try:
        from desktop.utils.audio_manager import play
        play(event, **kw)
    except Exception:
        pass


class _KesEdit(QLineEdit):
    """KES amount field — select-all on focus so typing 60 replaces 0.00 without sip crashes."""

    def focusInEvent(self, e):
        super().focusInEvent(e)
        QTimer.singleShot(0, self.selectAll)


class SalesTab(QWidget):
    sale_completed = pyqtSignal()
    theme_changed = pyqtSignal(bool)
    focus_mode_toggled = pyqtSignal(bool)  # True = hide shell chrome for POS focus

    def __init__(self, api, user, db_path, config_getter):
        super().__init__()
        self.api = api; self.user = user
        self.db_path = db_path; self.config_getter = config_getter
        self.cart = []; self.products = []
        self._subtotal = self._discount = self._tax = self._total = 0.0
        self._original_total = 0.0
        self._rounding_adj = 0.0
        self._rounding_info = {}
        self._currency = 'KES'
        self._is_light  = bool(ThemeManager.is_light())
        self._last_sale_id = None
        self._last_receipt = ''
        self._printer_mgr = None
        self._credit_to_apply = 0.0
        self._wallet_by_customer = {}
        # Cash Paid smart auto-fill: once cashier edits, do not overwrite
        # until payment method change or sale reset.
        self._cash_paid_dirty = False
        self._paid_programmatic = False
        self._elec_paid_dirty = False
        self._elec_programmatic = False
        self._held = None  # park/resume single slot (session + durable JSON)
        self._focus_mode = False  # session-only; MainWindow hides sidebar/topbar
        self._cart_maximized = False  # hide product grid; cart fills Sales tab
        # Catalog cache — avoid full DB + grid rebuild on every tab switch
        self._catalog_loaded = False
        self._catalog_mono = 0.0
        self._catalog_ttl_s = 45.0
        self._grid_painted = False
        self._resize_filter_timer = None
        self._search_filter_timer = None
        try:
            from desktop.utils.shop_time import shop_today
            self._business_day = shop_today()
        except Exception:
            from datetime import date as _date
            self._business_day = _date.today()
        try:
            from desktop.utils.held_sale import load_held_sale
            self._held = load_held_sale()
        except Exception:
            self._held = None
        self._build()
        # Do NOT auto-refresh here — warm-tab creation would stall Dashboard.
        # First paint + catalog load happen in on_show() after the tab is visible.

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build(self):
        """Create shared panels once, then assemble via checkout layout shell."""
        from desktop.pos.panel_factory import build_shared_panels
        from desktop.pos.layout_ids import (
            CHECKOUT_LAYOUT_KEY, DEFAULT_CHECKOUT_LAYOUT, normalize_layout_id,
        )
        from desktop.pos.layouts.shells import apply_layout_shell

        root = QVBoxLayout(self)
        root.setContentsMargins(PADDING, 12, PADDING, 12)
        root.setSpacing(0)
        self._root_lay = root

        # Prevent the Sales tab itself from scrolling — panels scroll independently.
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        build_shared_panels(self)

        self._shell = QWidget()
        self._shell.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root.addWidget(self._shell, 1)

        layout_id = DEFAULT_CHECKOUT_LAYOUT
        try:
            cfg = self.api.get_settings() or {}
            layout_id = normalize_layout_id(cfg.get(CHECKOUT_LAYOUT_KEY))
        except Exception:
            layout_id = DEFAULT_CHECKOUT_LAYOUT
        self._checkout_layout = layout_id
        apply_layout_shell(self, layout_id)
        self._sync_layout_combo(layout_id)
        self._update_hold_buttons()

    def _sync_layout_combo(self, layout_id: str):
        """Keep POS Layout combo aligned without re-firing change handlers."""
        combo = getattr(self, '_layout_combo', None)
        if combo is None:
            return
        from desktop.pos.layout_ids import normalize_layout_id
        lid = normalize_layout_id(layout_id)
        try:
            combo.blockSignals(True)
            idx = combo.findData(lid)
            if idx >= 0 and combo.currentIndex() != idx:
                combo.setCurrentIndex(idx)
            combo.show()
        except Exception:
            pass
        finally:
            try:
                combo.blockSignals(False)
            except Exception:
                pass

    def _on_layout_combo_changed(self, *_args):
        """Toolbar Layout combo — persist + apply immediately."""
        combo = getattr(self, '_layout_combo', None)
        if combo is None:
            return
        lid = combo.currentData()
        if not lid:
            return
        if lid == getattr(self, '_checkout_layout', None):
            return
        self.set_checkout_layout(lid)
        try:
            from desktop.pos.layout_ids import CHECKOUT_LAYOUT_KEY
            self.api.update_settings({CHECKOUT_LAYOUT_KEY: lid})
        except Exception:
            pass
        # Keep Settings → Checkout Layout in sync when that tab is open
        try:
            w = self.window()
            tabs = getattr(w, '_tabs', None) or {}
            settings = tabs.get('settings')
            sc = getattr(settings, 'pos_checkout_layout', None) if settings else None
            if sc is not None:
                sc.blockSignals(True)
                sidx = sc.findData(lid)
                if sidx >= 0:
                    sc.setCurrentIndex(sidx)
                sc.blockSignals(False)
        except Exception:
            pass

    def set_checkout_layout(self, layout_id: str, *, animate: bool = True) -> str:
        """Switch Retail Classic / Simple Counter / Checkout Pro without restart.

        Preserves cart, customer, payment, and search state — only geometry changes.
        """
        from desktop.pos.layout_ids import normalize_layout_id
        from desktop.pos.layouts.shells import apply_layout_shell

        lid = normalize_layout_id(layout_id)
        if lid == getattr(self, '_checkout_layout', None) and getattr(self, '_shell', None):
            # Still re-apply if shell is empty (first paint edge case)
            if self._shell.layout() is not None and self._shell.layout().count() > 0:
                self._sync_layout_combo(lid)
                return lid

        # Snapshot UI values that live on widgets (already on self.cart / spins)
        search_text = ''
        try:
            search_text = self._search.text()
        except Exception:
            pass
        cat_text = ''
        try:
            cat_text = self._cat.currentText()
        except Exception:
            pass

        if animate:
            try:
                self._shell.setUpdatesEnabled(False)
            except Exception:
                pass
        try:
            apply_layout_shell(self, lid)
        finally:
            if animate:
                try:
                    self._shell.setUpdatesEnabled(True)
                    self._shell.update()
                except Exception:
                    pass

        self._sync_layout_combo(lid)

        # Restore search/category where appropriate (widgets are the same instances)
        try:
            if search_text and self._search.text() != search_text:
                self._search.setText(search_text)
            if cat_text:
                idx = self._cat.findText(cat_text)
                if idx >= 0:
                    self._cat.setCurrentIndex(idx)
        except Exception:
            pass

        try:
            self._refresh_cart()
            self._filter(defer=True)
            self._on_payment_changed(self._pay.currentText())
        except Exception:
            pass
        try:
            self._search.setFocus(Qt.OtherFocusReason)
        except Exception:
            pass
        return lid

    # ── POS focus / cart maximize (session-only) ──────────────────────────────

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_F9:
            try:
                self._process()
            except Exception:
                pass
            event.accept()
            return
        if event.key() == Qt.Key_Escape:
            if getattr(self, '_cart_maximized', False):
                self.set_cart_maximized(False)
                event.accept()
                return
            if getattr(self, '_focus_mode', False):
                self.set_focus_mode(False)
                event.accept()
                return
        super().keyPressEvent(event)

    def _toggle_focus_mode(self):
        self.set_focus_mode(not bool(getattr(self, '_focus_mode', False)))

    def set_focus_mode(self, enabled: bool):
        """Enter/exit POS focus mode. Emits focus_mode_toggled for MainWindow chrome."""
        enabled = bool(enabled)
        if bool(getattr(self, '_focus_mode', False)) == enabled:
            return
        self._focus_mode = enabled
        btn = getattr(self, '_focus_btn', None)
        if btn is not None:
            btn.setText('Restore' if enabled else 'Focus')
            btn.setToolTip(
                'Restore sidebar and top bar' if enabled else
                'Maximize Point of Sale — hide sidebar and top bar. Esc or Restore to exit.')
        self.focus_mode_toggled.emit(enabled)
        try:
            from desktop.pos.layouts.splitters import reveal_cart_stack
            QTimer.singleShot(0, lambda: reveal_cart_stack(self))
            QTimer.singleShot(120, lambda: reveal_cart_stack(self))
        except Exception:
            pass

    def _toggle_cart_maximized(self):
        self.set_cart_maximized(not bool(getattr(self, '_cart_maximized', False)))

    def set_cart_maximized(self, enabled: bool):
        """Review mode: cart fills the sales tab so long carts are easy to confirm/edit."""
        enabled = bool(enabled)
        if bool(getattr(self, '_cart_maximized', False)) == enabled:
            return
        self._cart_maximized = enabled
        left = getattr(self, '_product_panel', None) or getattr(self, '_left_panel', None)
        sale = getattr(self, '_sale_panel', None)
        actions = getattr(self, '_actions_panel', None)
        cart = getattr(self, '_right_panel', None)
        shell = getattr(self, '_shell', None)
        shell_lay = shell.layout() if shell is not None else None
        clist = getattr(self, '_cart_list', None)
        layout_id = getattr(self, '_checkout_layout', 'simple_counter')

        if left is not None:
            left.setVisible(not enabled)
        # Classic bottom payment strip — hide while reviewing cart
        pf = getattr(self, '_payment_footer_bar', None)
        if pf is not None and layout_id == 'retail_classic':
            pf.setVisible(not enabled)
        # All layouts: hide the payment/customer rail in Review so the line list
        # owns vertical space. Complete Sale stays on Classic/Explorer foot;
        # Checkout Pro cashiers Restore to pay (same as prior Pro Review).
        if actions is not None:
            actions.setVisible(not enabled)

        focus_panel = sale if layout_id == 'checkout_pro' else cart
        if focus_panel is not None:
            if enabled:
                focus_panel.setMinimumWidth(480)
                focus_panel.setMaximumWidth(16777215)
                sp = focus_panel.sizePolicy()
                sp.setHorizontalPolicy(QSizePolicy.Expanding)
                sp.setHorizontalStretch(1)
                focus_panel.setSizePolicy(sp)
                if shell_lay is not None:
                    try:
                        shell_lay.setStretchFactor(focus_panel, 1)
                        if left is not None:
                            shell_lay.setStretchFactor(left, 0)
                    except Exception:
                        pass
            else:
                # Restore layout-specific sizing via re-apply (preserves state)
                try:
                    from desktop.pos.layouts.shells import apply_layout_shell
                    apply_layout_shell(self, layout_id)
                except Exception:
                    if layout_id == 'simple_counter' and cart is not None:
                        cart.setMinimumWidth(740)
                        cart.setMaximumWidth(920)
                        cart.setFixedWidth(880)

        if clist is not None and hasattr(clist, 'set_expanded'):
            # Review expands the cart; cashier mode keeps the 5-row viewport.
            clist.set_expanded(enabled)
            if hasattr(clist, 'set_cashier_viewport'):
                try:
                    from desktop.utils.pos_components import CART_CASHIER_ROWS
                    clist.set_cashier_viewport(0 if enabled else CART_CASHIER_ROWS)
                except Exception:
                    pass

        summary = getattr(self, '_summary', None)
        if summary is not None and hasattr(summary, 'set_review_compact'):
            try:
                summary.set_review_compact(enabled)
            except Exception:
                pass

        hdr = getattr(self, '_sale_hdr', None)
        if hdr is not None:
            try:
                if enabled:
                    hdr.setText('Review Cart')
                elif layout_id == 'checkout_pro':
                    n = len(getattr(self, 'cart', []) or [])
                    hdr.setText(f'Current Sale ({n} item{"s" if n != 1 else ""})')
                else:
                    hdr.setText('Current Sale')
            except Exception:
                pass

        btn = getattr(self, '_cart_max_btn', None)
        if btn is not None:
            btn.setText('Restore' if enabled else 'Review')
            btn.setToolTip(
                'Return to product picker' if enabled else
                'Enlarge the cart to review and edit many items. Esc or Restore to add products again.')
            # Pro chrome hides Review in the header; show it while maximized so
            # cashiers can Restore without hunting the quick-actions pad.
            if layout_id == 'checkout_pro':
                try:
                    btn.setVisible(True)
                    cnt = getattr(self, '_cnt', None)
                    if cnt is not None:
                        n = len(getattr(self, 'cart', []) or [])
                        cnt.setText(f'{n} item{"s" if n != 1 else ""}')
                        cnt.setVisible(bool(enabled))
                    if not enabled:
                        btn.hide()
                        if cnt is not None:
                            cnt.hide()
                except Exception:
                    pass

        try:
            sc = getattr(self, '_cart_max_esc', None)
            if enabled:
                if sc is None:
                    sc = QShortcut(QKeySequence(Qt.Key_Escape), self)
                    sc.setContext(Qt.WidgetWithChildrenShortcut)
                    sc.activated.connect(self._exit_cart_or_focus)
                    self._cart_max_esc = sc
                sc.setEnabled(True)
            elif sc is not None:
                sc.setEnabled(False)
        except Exception:
            pass

        try:
            self.updateGeometry()
            if focus_panel is not None:
                focus_panel.updateGeometry()
        except Exception:
            pass

        # After Focus/Review/layout: cart splitter + rows must paint with height.
        # Review installs an 80–90% list bias; Restore re-applies persisted sizes.
        try:
            from desktop.pos.layouts.splitters import install_cart, reveal_cart_stack
            reveal_cart_stack(self)
            install_cart(self, layout_id)
            QTimer.singleShot(0, lambda: reveal_cart_stack(self))
            QTimer.singleShot(120, lambda: reveal_cart_stack(self))
        except Exception:
            pass

    def _exit_cart_or_focus(self):
        """Esc: restore cart first, then POS focus chrome."""
        if getattr(self, '_cart_maximized', False):
            self.set_cart_maximized(False)
            return
        if getattr(self, '_focus_mode', False):
            self.set_focus_mode(False)

    def _select_pay_method(self, method: str):
        if hasattr(self, '_pay_seg'):
            self._pay_seg.select(method, emit=False)
        for k, b in getattr(self, '_pay_btns', {}).items():
            b.setChecked(k == method)
        idx = self._pay.findText(method)
        if idx >= 0:
            self._pay.setCurrentIndex(idx)

    # ── Theme toggle ──────────────────────────────────────────────────────────

    def _on_theme_bar(self, want_light: bool):
        self.theme_changed.emit(want_light)

    def _toggle_theme(self):
        self.theme_changed.emit(not ThemeManager.is_light())

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _tot_row(self, parent_lay, label):
        row = QHBoxLayout(); row.setContentsMargins(0, 0, 0, 0)
        l = QLabel(label)
        l.setStyleSheet(f"color:{C['text2']};font-size:14px;background:transparent;")
        v = QLabel('KES 0.00')
        v.setStyleSheet(f"color:{C['text']};font-size:14px;background:transparent;")
        row.addWidget(l); row.addStretch(); row.addWidget(v)
        parent_lay.addLayout(row); return v

    def _catalog_is_fresh(self) -> bool:
        """True when a catalog load completed recently (empty shop is still fresh)."""
        if not getattr(self, '_catalog_loaded', False):
            return False
        try:
            age = time.monotonic() - float(getattr(self, '_catalog_mono', 0) or 0)
        except Exception:
            return False
        return age < float(getattr(self, '_catalog_ttl_s', 45) or 45)

    def invalidate_catalog(self):
        """Force next on_show / refresh to reload products (e.g. after inventory)."""
        self._catalog_loaded = False
        self._catalog_mono = 0.0

    def on_show(self):
        """Show path: paint first; reuse cached catalog when fresh."""
        try:
            self._ensure_business_day_current()
        except Exception:
            pass
        try:
            self._on_payment_changed(self._pay.currentText())
        except Exception:
            pass
        try:
            self._search.setFocus(Qt.OtherFocusReason)
        except Exception:
            pass
        if self._catalog_is_fresh() and getattr(self, '_grid_painted', False):
            return
        if self._catalog_is_fresh() and not getattr(self, '_grid_painted', False):
            # Data in memory (rare) but grid never painted — fill without DB round-trip
            QTimer.singleShot(0, lambda: self._filter(defer=True))
            return
        # First open or stale: load after this event so shell paints first
        QTimer.singleShot(0, lambda: self.refresh(defer_grid=True))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        try:
            sp = getattr(self, '_pos_splitter', None)
            if sp is not None and sp.count() >= 2:
                t_sp = getattr(self, '_splitter_resize_timer', None)
                if t_sp is None:
                    t_sp = QTimer(self)
                    t_sp.setSingleShot(True)
                    t_sp.setInterval(100)

                    def _rescale_columns():
                        if getattr(self, '_pos_splitter_dragging', False):
                            return
                        from desktop.pos.layout_ids import normalize_layout_id
                        from desktop.pos.layouts.splitters import apply_sizes
                        s = getattr(self, '_pos_splitter', None)
                        if s is None or s.count() < 2:
                            return
                        apply_sizes(
                            self,
                            normalize_layout_id(getattr(self, '_checkout_layout', '')),
                            s.count(),
                        )

                    t_sp.timeout.connect(_rescale_columns)
                    self._splitter_resize_timer = t_sp
                t_sp.start()
            from desktop.pos.layout_ids import LAYOUT_CHECKOUT_PRO, normalize_layout_id
            if normalize_layout_id(getattr(self, '_checkout_layout', '')) == LAYOUT_CHECKOUT_PRO:
                t_sq = getattr(self, '_pro_square_layout_timer', None)
                if t_sq is None:
                    t_sq = QTimer(self)
                    t_sq.setSingleShot(True)
                    t_sq.setInterval(120)

                    def _sync_square():
                        try:
                            from desktop.pos.checkout_pro_chrome import sync_pro_square_layout
                            sync_pro_square_layout(self)
                        except Exception:
                            pass

                    t_sq.timeout.connect(_sync_square)
                    self._pro_square_layout_timer = t_sq
                t_sq.start()
        except Exception:
            pass
        try:
            cols = self._product_columns()
            if getattr(self, '_last_cols', None) == cols:
                return
            self._last_cols = cols
            # Debounce — layout reparent / maximize fires many resizes
            t = getattr(self, '_resize_filter_timer', None)
            if t is None:
                t = QTimer(self)
                t.setSingleShot(True)
                t.setInterval(80)
                t.timeout.connect(lambda: self._filter(defer=False))
                self._resize_filter_timer = t
            t.start()
        except Exception:
            pass

    def _amount_due(self):
        """Payable after store credit and cash rounding (when active)."""
        info = self._compute_rounding()
        return round(float(info.get('amount_due', max(0.0, self._total - float(self._credit_to_apply or 0)))), 2)

    def _elec_portion(self) -> float:
        if not hasattr(self, '_elec_paid'):
            return 0.0
        return round(float(self._elec_paid.value() or 0), 2)

    def _elec_method_name(self) -> str:
        if hasattr(self, '_elec_method'):
            try:
                return (self._elec_method.currentText() or 'M-Pesa').strip()
            except Exception:
                pass
        return 'M-Pesa'

    def _is_split_method(self, method=None) -> bool:
        method = method or (self._pay.currentText() if hasattr(self, '_pay') else 'Cash')
        return method in ('Cash', 'Mixed')

    def _is_part_sale(self) -> bool:
        if getattr(self, '_pro_sale_type', '') == 'part':
            return True
        method = self._pay.currentText() if hasattr(self, '_pay') else ''
        return method == 'Part Payment'

    def _is_credit_sale(self) -> bool:
        if getattr(self, '_pro_sale_type', '') == 'credit':
            return True
        method = self._pay.currentText() if hasattr(self, '_pay') else ''
        return method in ('Credit Sale', 'Credit Account')

    def _tendered_now(self, method=None) -> tuple:
        """Cash + electronic collected at till (excludes leftover debt)."""
        method = method or (self._pay.currentText() if hasattr(self, '_pay') else 'Cash')
        cash = float(self._paid.value() or 0) if hasattr(self, '_paid') else 0.0
        elec = self._elec_portion() if self._is_split_method(method) else 0.0
        if elec < 0.009:
            return round(cash, 2), 0.0, round(cash, 2)
        return round(cash, 2), round(elec, 2), round(cash + elec, 2)

    def _prepare_part_pay_amounts(self):
        """If amounts still cover the bill, clear them so Part pay is a remainder."""
        if not self._is_part_sale():
            return
        due = self._amount_due()
        _cash, _elec, paid = self._tendered_now()
        if paid + 0.009 < due:
            return
        self._set_paid_value(0.0, mark_clean=True)
        if hasattr(self, '_elec_paid'):
            self._set_elec_value(0.0, mark_clean=True)

    def _cash_due_amount(self) -> float:
        """Cash portion due (post rounding) — used for Cash Paid autofill on split."""
        info = self._rounding_info or self._compute_rounding()
        elec = float(info.get('electronic') or 0)
        if elec > 0.009:
            return round(float(info.get('cash_rounded', 0)), 2)
        return round(float(info.get('amount_due', self._amount_due())), 2)

    def _set_elec_value(self, value: float, *, mark_clean: bool = False):
        if not hasattr(self, '_elec_paid'):
            return
        self._elec_programmatic = True
        try:
            self._elec_paid.blockSignals(True)
            self._elec_paid.setValue(round(float(value or 0), 2))
        except Exception:
            pass
        finally:
            try:
                self._elec_paid.blockSignals(False)
            except Exception:
                pass
            self._elec_programmatic = False
        if mark_clean:
            self._elec_paid_dirty = False

    def _maybe_autofill_split_remainder(self) -> bool:
        """When Mixed and cash is typed, fill electronic with the unpaid remainder."""
        if not hasattr(self, '_elec_paid'):
            return False
        method = self._pay.currentText() if hasattr(self, '_pay') else 'Cash'
        if method != 'Mixed':
            return False
        if self._is_part_sale():
            return False
        if not getattr(self, '_cash_paid_dirty', False):
            return False
        if getattr(self, '_elec_paid_dirty', False):
            return False
        raw_due = round(max(0.0, float(self._total or 0) - float(self._credit_to_apply or 0)), 2)
        cash = float(self._paid.value() or 0) if hasattr(self, '_paid') else 0.0
        from desktop.utils.payment_tenders import remainder_electronic
        rem = remainder_electronic(raw_due, cash, 0.0)
        if abs(float(self._elec_paid.value() or 0) - rem) < 0.009:
            return False
        self._set_elec_value(rem, mark_clean=True)
        return True

    def _sync_split_mpesa_ui(self):
        method = self._pay.currentText() if hasattr(self, '_pay') else 'Cash'
        if method == 'M-Pesa':
            return
        show = method == 'Mixed' and self._elec_method_name() == 'M-Pesa'
        if hasattr(self, '_mpesa_frame'):
            try:
                self._mpesa_frame.setVisible(show)
            except RuntimeError:
                pass
        if show:
            cfg = self._cfg()
            till = cfg.get('mpesa_till', '').strip()
            pb = cfg.get('mpesa_paybill', '').strip()
            biz = cfg.get('mpesa_business_name', '') or cfg.get('shop_name', 'Shop')
            parts = [biz]
            if till:
                parts.append(f'Till: {till}')
            if pb:
                parts.append(f'Paybill: {pb}')
            if not till and not pb:
                parts.append('Set Till/Paybill in Settings → M-Pesa')
            if hasattr(self, '_mpesa_info'):
                self._mpesa_info.setText(' · '.join(parts))

    def _on_elec_paid_changed(self, *_args):
        if not getattr(self, '_elec_programmatic', False):
            self._elec_paid_dirty = True
        # Split tender: remaining cash due re-fills Cash Paid when not dirty
        self._recalc()

    def _cfg(self) -> dict:
        try:
            return self.config_getter() or {}
        except Exception:
            return {}

    def _set_paid_value(self, value: float, *, mark_clean: bool = False):
        """Programmatic Cash Paid / Received update (does not set dirty)."""
        self._paid_programmatic = True
        try:
            self._paid.blockSignals(True)
            self._paid.setValue(round(float(value or 0), 2))
        except Exception:
            pass
        finally:
            try:
                self._paid.blockSignals(False)
            except Exception:
                pass
            self._paid_programmatic = False
        if mark_clean:
            self._cash_paid_dirty = False

    def _on_paid_changed(self, *_args):
        if not self._paid_programmatic:
            method = self._pay.currentText() if hasattr(self, '_pay') else 'Cash'
            # Only Cash / Mixed use the dirty flag for auto-fill
            try:
                from desktop.utils.auto_fill import AutoFillService
                if AutoFillService.is_cash_like(method):
                    self._cash_paid_dirty = True
            except Exception:
                if method in ('Cash', 'Mixed'):
                    self._cash_paid_dirty = True
            if method == 'Mixed' and self._maybe_autofill_split_remainder():
                self._compute_rounding()
                self._update_rounding_ui()
        self._calc_change()

    def _focus_cash_paid(self):
        """Auto-focus Cash Paid and select-all for quick overwrite."""
        def _do():
            try:
                self._paid.setFocus(Qt.OtherFocusReason)
                le = self._paid.lineEdit() if hasattr(self._paid, 'lineEdit') else None
                if le is not None:
                    le.selectAll()
                elif hasattr(self._paid, 'selectAll'):
                    self._paid.selectAll()
            except Exception:
                pass
        QTimer.singleShot(0, _do)

    def _set_cash_paid_ui_visible(self, visible: bool):
        if hasattr(self, '_paid'):
            self._paid.setVisible(visible)
        # Shared Amount Paid caption (all layouts) — never use legacy Cash Paid label
        cap = getattr(self, '_amount_paid_cap', None)
        if cap is not None:
            try:
                cap.setVisible(visible)
                if visible:
                    cap.setText('Amount Paid')
            except RuntimeError:
                pass
        block = getattr(self, '_amount_paid_block', None) or getattr(self, '_amount_block', None)
        if block is not None:
            try:
                block.setVisible(visible)
            except RuntimeError:
                pass
        # Legacy label stays hidden — Amount Paid cap replaces it across layouts
        if hasattr(self, '_cash_paid_lbl'):
            try:
                self._cash_paid_lbl.hide()
            except RuntimeError:
                pass
        if hasattr(self, '_chg_frame'):
            self._chg_frame.setVisible(visible)
        if hasattr(self, '_chg_lbl'):
            self._chg_lbl.setVisible(visible)
        if hasattr(self, '_chg'):
            self._chg.setVisible(visible)

    def _maybe_autofill_cash_paid(self, *, focus: bool = False):
        """Fill Cash Paid = cash due (post rounding) when allowed."""
        method = self._pay.currentText() if hasattr(self, '_pay') else 'Cash'
        cfg = self._cfg()
        try:
            from desktop.utils.auto_fill import AutoFillService
            ok = AutoFillService.should_autofill_cash_paid(
                method, dirty=bool(self._cash_paid_dirty), cfg=cfg)
        except Exception:
            ok = (
                method in ('Cash', 'Mixed')
                and not self._cash_paid_dirty
                and cfg.get('autofill_cash_paid', '1') != '0'
            )
        if not ok:
            return False
        if self._is_part_sale():
            return False
        # Split: only autofill the cash portion, not electronic + cash
        due = self._cash_due_amount()
        self._set_paid_value(due, mark_clean=True)
        if focus and due > 0.009:
            self._focus_cash_paid()
        return True

    def _compute_rounding(self) -> dict:
        """Recompute cash rounding for current cart / payment method."""
        from desktop.utils.cash_rounding_service import CashRoundingService
        cfg = {}
        try:
            cfg = self.config_getter() or {}
        except Exception:
            cfg = {}
        method = self._pay.currentText() if hasattr(self, '_pay') else 'Cash'
        credit = float(self._credit_to_apply or 0)
        # Electronic portion only on Cash / Mixed (split tender)
        elec = self._elec_portion() if self._is_split_method(method) else 0.0
        # Mixed always applies cash-portion rounding rules
        round_method = 'Cash' if method == 'Mixed' else method
        info = CashRoundingService.apply_to_total(
            self._subtotal, self._discount, self._tax, round_method, cfg,
            credit_applied=credit, electronic_portion=elec)
        self._rounding_info = info
        self._original_total = float(info.get('cart_total', self._total))
        self._rounding_adj = float(info.get('adjustment') or 0)
        return info

    def _update_rounding_ui(self):
        info = self._rounding_info or self._compute_rounding()
        method = self._pay.currentText() if hasattr(self, '_pay') else 'Cash'
        from desktop.utils.cash_rounding_service import CashRoundingService
        cfg = {}
        try:
            cfg = self.config_getter() or {}
        except Exception:
            pass
        st = CashRoundingService.settings_from_config(cfg)
        adj = float(info.get('adjustment') or 0)
        # Rounding badge/lines ONLY when Cash/Mixed + enabled + non-zero delta
        show_round = (
            self._is_split_method(method)
            and bool(st.get('enabled'))
            and CashRoundingService.should_apply('cash', st)
            and abs(adj) > 0.009
        )
        if hasattr(self, '_round_frame'):
            self._round_frame.setVisible(show_round)
            if show_round:
                cur = self._currency
                orig = float(info.get('original_due', info.get('original', 0)))
                due = float(info.get('amount_due', orig))
                cash_orig = float(info.get('cash_original') or orig)
                cash_rnd = float(info.get('cash_rounded') or due)
                elec = float(info.get('electronic') or 0)
                if elec > 0.009:
                    self._orig_due_lbl.setText(
                        f'Cash original: {cur} {cash_orig:,.2f}')
                    self._amount_due_lbl.setText(
                        f'Cash due: {cur} {cash_rnd:,.2f}')
                else:
                    self._orig_due_lbl.setText(f'Original: {cur} {orig:,.2f}')
                    self._amount_due_lbl.setText(f'Amount Due: {cur} {due:,.2f}')
                sign = '+' if adj >= 0 else ''
                self._round_adj_lbl.setText(
                    f'Cash Rounding: {sign}{cur} {adj:,.2f}')
                self._round_badge.setVisible(True)
                gold, mute, text = C['gold'], C['text2'], C['text']
                self._round_badge.setStyleSheet(
                    f"color:{gold};font-size:11px;font-weight:800;background:transparent;")
                self._orig_due_lbl.setStyleSheet(
                    f"color:{mute};font-size:12px;font-weight:600;background:transparent;")
                self._round_adj_lbl.setStyleSheet(
                    f"color:{mute};font-size:12px;font-weight:600;background:transparent;")
                self._amount_due_lbl.setStyleSheet(
                    f"color:{text};font-size:13px;font-weight:800;background:transparent;")
                self._round_frame.setStyleSheet(
                    f"QFrame#posRoundFrame{{background:{C['card2']};"
                    f"border:1px solid {C['border2']};border-radius:8px;}}")

        # Split tender panel — Mixed / Split Pay tile (all layouts)
        show_split = method == 'Mixed'
        if hasattr(self, '_split_frame'):
            self._split_frame.setVisible(show_split)
            if show_split:
                mute = C['text2']
                self._split_frame.setStyleSheet(
                    f"QFrame#posSplitFrame{{background:{C['card2']};"
                    f"border:1px solid {C['border2']};border-radius:8px;}}")
                self._elec_lbl.setStyleSheet(
                    f"color:{mute};font-size:12px;background:transparent;")
                self._split_hdr.setStyleSheet(
                    f"color:{mute};font-size:11px;font-weight:700;background:transparent;")
                elec = float(info.get('electronic') or 0)
                cash_due = float(info.get('cash_rounded') or 0)
                cash_paid = float(self._paid.value() or 0) if hasattr(self, '_paid') else cash_due
                cur = self._currency
                em = self._elec_method_name()
                if elec > 0.009:
                    total_tender = round(elec + cash_paid, 2)
                    if self._is_part_sale():
                        due_now = self._amount_due()
                        bal = max(0.0, round(due_now - total_tender, 2))
                        self._split_summary.setText(
                            f'{em} {cur} {elec:,.2f}  +  Cash {cur} {cash_paid:,.2f}'
                            f'  =  {cur} {total_tender:,.2f}'
                            f'   ·  on account {cur} {bal:,.2f}')
                        self._split_hdr.setText('Split Pay — remainder on account')
                    else:
                        self._split_summary.setText(
                            f'{em} {cur} {elec:,.2f}  +  Cash {cur} {cash_paid:,.2f}'
                            f'  =  {cur} {total_tender:,.2f}'
                            f'   (cash due {cur} {cash_due:,.2f})')
                        self._split_hdr.setText('Split Pay')
                else:
                    if self._is_part_sale():
                        self._split_summary.setText(
                            f'Type cash and {em} paid now. Anything left is customer debt.')
                        self._split_hdr.setText('Split Pay — remainder on account')
                    else:
                        self._split_summary.setText(
                            f'Type cash paid (e.g. 500). Remaining due is {em}. '
                            'Or type the electronic amount first — cash fills the rest.')
                        self._split_hdr.setText('Split Pay — cash + electronic')
                self._sync_split_mpesa_ui()


    def _is_till_method(self, method=None):
        method = method or self._pay.currentText()
        return method in ('M-Pesa',)

    def _on_customer_changed(self, *_args):
        cust_id = self._customer.selected_id() if hasattr(self, '_customer') else None
        cust = None
        if cust_id:
            try:
                for c in (self.api.get_customers() or []):
                    if c.get('id') == cust_id or c.get('id') == int(cust_id):
                        cust = c
                        break
            except Exception:
                cust = None
            if cust is not None:
                try:
                    self._wallet_by_customer[cust_id] = float(
                        cust.get('wallet_balance') or 0)
                    if hasattr(self, '_cust_card') and self._cust_card is not None:
                        self._cust_card.set_customers_cache(
                            getattr(self._cust_card, '_customers_cache', []) or [cust]
                        )
                except Exception:
                    pass
        bal = float(self._wallet_by_customer.get(cust_id) or 0) if cust_id else 0.0
        if hasattr(self, '_cust_card') and self._cust_card is not None:
            try:
                self._cust_card.set_customer(cust, walk_in=not cust_id)
            except Exception:
                pass
        # Credit customer summary tooltip (balance / limit / outstanding)
        try:
            from desktop.utils.auto_fill import AutoFillService
            cfg = self._cfg() if hasattr(self, '_cfg') else (self.config_getter() or {})
            if cust_id and AutoFillService.enabled(cfg, 'autofill_credit_customer_info'):
                summary = AutoFillService.credit_customer_summary(cust, cfg)
                hint = AutoFillService.format_credit_customer_hint(
                    summary, self._currency)
                if hasattr(self, '_customer'):
                    self._customer.setToolTip(hint or '')
                if hasattr(self, '_cust_card') and self._cust_card is not None:
                    try:
                        self._cust_card._btn.setToolTip(
                            hint or self._cust_card._btn.toolTip())
                    except Exception:
                        pass
            elif hasattr(self, '_customer'):
                self._customer.setToolTip('')
        except Exception:
            pass
        if cust_id and bal > 0.009:
            self._credit_frame.show()
            self._credit_info.setText(
                f'Store credit available: {self._currency} {bal:,.2f}')
            self._credit_spin.blockSignals(True)
            self._credit_spin.setMaximum(min(bal, self._total if self._total > 0 else bal))
            # Keep existing apply if still valid
            apply = min(float(self._credit_to_apply or 0), bal, self._total)
            self._credit_spin.setValue(apply)
            self._credit_spin.blockSignals(False)
            self._credit_to_apply = apply
        else:
            self._credit_frame.hide()
            self._credit_to_apply = 0.0
            self._credit_spin.blockSignals(True)
            self._credit_spin.setValue(0)
            self._credit_spin.blockSignals(False)
        self._calc_change()

    def _on_credit_apply_changed(self, val):
        self._credit_to_apply = round(float(val or 0), 2)
        method = self._pay.currentText()
        if self._is_till_method():
            self._set_paid_value(self._amount_due())
        elif method in ('Cash', 'Mixed') and not self._is_part_sale():
            self._maybe_autofill_cash_paid(focus=False)
        self._calc_change()

    def _apply_all_credit(self):
        cust_id = self._customer.selected_id()
        bal = float(self._wallet_by_customer.get(cust_id) or 0) if cust_id else 0.0
        self._credit_spin.setValue(min(bal, self._total))

    def _on_payment_changed(self, method: str):
        seg_keys = ('Cash', 'M-Pesa', 'Card', 'Bank Transfer', 'Mixed')
        if hasattr(self, '_pay_seg') and method in seg_keys:
            self._pay_seg.select(method, emit=False)
        if hasattr(self, '_pay_btns'):
            for k, b in self._pay_btns.items():
                if not b.isEnabled():
                    continue
                b.blockSignals(True)
                b.setChecked(k == method)
                b.blockSignals(False)
        # Credit Sale leaves tender tiles unchecked. Part pay keeps Cash/Split/etc.
        if method in ('Credit Sale', 'Credit Account'):
            if hasattr(self, '_pay_btns'):
                for b in self._pay_btns.values():
                    if not b.isEnabled():
                        continue
                    b.blockSignals(True)
                    b.setChecked(False)
                    b.blockSignals(False)
        try:
            from desktop.pos.checkout_pro_chrome import sync_sale_type_from_method
            sync_sale_type_from_method(self, method)
        except Exception:
            pass

        from desktop.utils.auto_fill import AutoFillService

        is_mpesa = method == 'M-Pesa'
        self._mpesa_frame.setVisible(is_mpesa)
        if hasattr(self, '_var_frame'):
            # Checkout Pro: never permanently show Additional Payment Handling strip
            if getattr(self, '_checkout_layout', '') == 'checkout_pro':
                self._var_frame.hide()
            else:
                self._var_frame.setVisible(is_mpesa)

        # Switching payment method resets Cash Paid dirty flag for Cash/Mixed
        if AutoFillService.is_cash_like(method):
            self._cash_paid_dirty = False
            self._elec_paid_dirty = False
        else:
            # Leaving split methods — clear electronic portion
            if hasattr(self, '_elec_paid'):
                self._elec_paid.blockSignals(True)
                self._elec_paid.setValue(0)
                self._elec_paid.blockSignals(False)
            self._elec_paid_dirty = False

        part = self._is_part_sale()
        if is_mpesa:
            cfg = self._cfg()
            till = cfg.get('mpesa_till', '').strip()
            pb   = cfg.get('mpesa_paybill', '').strip()
            biz  = cfg.get('mpesa_business_name', '') or cfg.get('shop_name', 'Shop')
            parts = [biz]
            if till:
                parts.append(f'Till: {till}')
            if pb:
                parts.append(f'Paybill: {pb}')
            if not till and not pb:
                parts.append('Set Till/Paybill in Settings → M-Pesa')
            self._mpesa_info.setText(' · '.join(parts))
            self._set_cash_paid_ui_visible(True)
            if hasattr(self, '_amount_paid_cap'):
                self._amount_paid_cap.setText('Amount Paid')
            self._paid.setEnabled(True)
            if part:
                self._paid.setToolTip('Amount paid now via Till (remainder on account)')
                self._chg_lbl.setText('Balance Due')
                if self._paid.value() + 0.009 >= self._amount_due():
                    self._set_paid_value(0.0, mark_clean=True)
            else:
                self._set_paid_value(self._amount_due())
                self._paid.setToolTip('Amount Paid — enter what customer paid via Till')
                self._chg_lbl.setText('Change')
            self._pay_lbl.setText('Method')
            if getattr(self, '_checkout_layout', '') == 'checkout_pro':
                if not part:
                    self._chg_lbl.setText('Change')
                if hasattr(self, '_cash_paid_lbl'):
                    self._cash_paid_lbl.hide()
                if hasattr(self, '_pay_lbl'):
                    self._pay_lbl.hide()
        elif method in ('Credit Sale', 'Credit Account'):
            self._set_cash_paid_ui_visible(True)
            if hasattr(self, '_amount_paid_cap'):
                self._amount_paid_cap.setText('Amount Paid')
            self._set_paid_value(0.0)
            self._paid.setEnabled(False)
            self._mpesa_ref.clear()
            self._paid.setToolTip('')
            self._chg_lbl.setText('Change')
        elif AutoFillService.hides_cash_paid_ui(method):
            if part:
                self._set_cash_paid_ui_visible(True)
                if hasattr(self, '_amount_paid_cap'):
                    self._amount_paid_cap.setText('Amount Paid')
                self._paid.setEnabled(True)
                self._mpesa_ref.clear()
                self._paid.setToolTip('Amount paid now (remainder on account)')
                self._chg_lbl.setText('Balance Due')
                if self._paid.value() + 0.009 >= self._amount_due():
                    self._set_paid_value(0.0, mark_clean=True)
            else:
                self._set_cash_paid_ui_visible(False)
                self._set_paid_value(self._amount_due())
                self._paid.setEnabled(False)
                self._mpesa_ref.clear()
                self._paid.setToolTip('')
                self._chg_lbl.setText('Change')
        elif method == 'Part Payment':
            self._set_cash_paid_ui_visible(True)
            if hasattr(self, '_amount_paid_cap'):
                self._amount_paid_cap.setText('Amount Paid')
            self._paid.setEnabled(True)
            self._mpesa_ref.clear()
            self._paid.setToolTip('Amount paid now (remainder on credit)')
            self._chg_lbl.setText('Balance Due')
            if self._paid.value() <= 0.009:
                self._set_paid_value(0.0)
        else:
            # Cash / Mixed
            self._set_cash_paid_ui_visible(True)
            if hasattr(self, '_amount_paid_cap'):
                self._amount_paid_cap.setText(
                    'Cash paid' if method == 'Mixed' else 'Amount Paid')
            self._paid.setEnabled(True)
            self._mpesa_ref.clear()
            if part:
                self._paid.setToolTip(
                    'Cash paid now. On Split, enter M-Pesa/card too; leftover is debt.'
                    if method == 'Mixed'
                    else 'Amount paid now (remainder on account)')
                self._chg_lbl.setText('Balance Due')
                if method == 'Mixed':
                    self._sync_split_mpesa_ui()
            else:
                self._paid.setToolTip(
                    'Cash tendered. On Split Pay, remaining due is the electronic method.'
                    if method == 'Mixed'
                    else 'Amount Paid — defaults to Amount Due; edit for change')
                self._chg_lbl.setText('Change')
                self._maybe_autofill_cash_paid(focus=False)
                if method == 'Mixed':
                    self._sync_split_mpesa_ui()
        self._update_rounding_ui()
        self._calc_change()

    def refresh(self, force: bool = False, defer_grid: bool = False):
        """Reload catalog from DB and repaint the product grid.

        ``defer_grid=True`` paints shell first, then fills cards in chunks
        (used on tab open). Manual refresh button uses synchronous fill.
        """
        if not force and self._catalog_is_fresh() and getattr(self, '_grid_painted', False):
            return
        try:
            self.products = self.api.get_products() or []
        except Exception:
            self.products = []
        try:
            self._currency = (self.config_getter() or {}).get('currency_symbol', 'KES') or 'KES'
        except Exception:
            pass
        try:
            self._categories_by_name = self.api.categories_by_name_map()
        except Exception:
            self._categories_by_name = {}
        try:
            customers = self.api.get_customers() or []
            self._wallet_by_customer = {
                c.get('id'): float(c.get('wallet_balance') or 0)
                for c in customers if c.get('id')
            }
            if hasattr(self, '_cust_card') and self._cust_card is not None:
                self._cust_card.set_api(self.api)
                self._cust_card.set_customers_cache(customers)
            if hasattr(self, '_customer'):
                self._customer.load_customers(customers)
                self._on_customer_changed()
        except Exception:
            pass
        cats = sorted({p.get('category') or 'General' for p in self.products})
        # Prefer managed category list when available; drop supplier-tag noise
        try:
            from desktop.utils.display_category import (
                looks_like_supplier_tag, display_category,
            )
            cleaned = set()
            for p in self.products:
                lab, _ = display_category(p.get('category') or '', p.get('name') or '')
                if lab and lab != 'Uncategorized':
                    cleaned.add(lab)
                elif p.get('category') and not looks_like_supplier_tag(p.get('category') or ''):
                    cleaned.add(p.get('category'))
            if cleaned:
                cats = sorted(cleaned)
            else:
                cats = [c for c in cats if not looks_like_supplier_tag(c)]
        except Exception:
            pass
        try:
            managed = [c.get('name') for c in (self.api.get_categories() or []) if c.get('name')]
            if managed:
                try:
                    from desktop.utils.display_category import looks_like_supplier_tag as _slt
                    managed = [c for c in managed if not _slt(c)]
                except Exception:
                    pass
                cats = sorted(set(cats) | set(managed))
        except Exception:
            pass
        self._rebuild_category_combo(cats)
        try:
            if getattr(self, '_checkout_layout', '') == 'checkout_pro':
                from desktop.pos.checkout_pro_chrome import sync_category_chips
                sync_category_chips(self)
        except Exception:
            pass
        self._catalog_loaded = True
        try:
            self._catalog_mono = time.monotonic()
        except Exception:
            self._catalog_mono = 0.0
        self._filter(defer=bool(defer_grid))

    def _on_barcode_enter(self, text: str):
        """Barcode / SKU Enter — add exact match and clear search for next scan."""
        t = getattr(self, '_search_filter_timer', None)
        if t is not None:
            t.stop()
        q = (text or '').strip()
        if not q:
            return
        from desktop.utils.pos_search import filter_pos_products, match_score
        ranked = filter_pos_products(self.products, q, limit=8)
        hit = None
        if ranked:
            top = ranked[0]
            sc = match_score(q, top)
            if sc is not None and sc <= 1:
                hit = top
            elif len(ranked) == 1:
                hit = ranked[0]
        if hit is not None:
            try:
                stock_n = float(hit.get('stock', 0) or 0)
            except (TypeError, ValueError):
                stock_n = 0
            if stock_n <= 0:
                _sfx('warning')
                soft_warn(self, f'{(hit.get("name") or "Item")} is out of stock.')
            else:
                self._add(hit, from_scan=True)
            self._search.clear()
            self._search.setFocus(Qt.OtherFocusReason)
        else:
            self._filter()

    def _rebuild_category_combo(self, cats: list):
        """Rebuild category list; defer icon pixmaps so first paint stays snappy."""
        self._cat.blockSignals(True)
        cur = self._cat.currentText()
        self._cat.clear()
        self._cat.addItem('All Categories')
        for c in cats:
            self._cat.addItem(c)
        idx = self._cat.findText(cur)
        if idx >= 0:
            self._cat.setCurrentIndex(idx)
        else:
            self._cat.setCurrentIndex(0)
        self._cat.blockSignals(False)
        # Icons after first paint — optional polish, not required for selling
        QTimer.singleShot(0, lambda names=list(cats): self._apply_category_icons(names))

    def _apply_category_icons(self, cats: list):
        try:
            from desktop.utils.category_visuals import icon_to_pixmap
        except Exception:
            return
        cmap = getattr(self, '_categories_by_name', None) or {}
        try:
            self._cat.blockSignals(True)
            for i in range(1, self._cat.count()):
                name = self._cat.itemText(i)
                if name not in cats and cats:
                    continue
                meta = cmap.get(name) or {}
                if not meta.get('icon_name'):
                    continue
                try:
                    self._cat.setItemIcon(
                        i, QIcon(icon_to_pixmap(icon_id=meta['icon_name'], size=20)))
                except Exception:
                    pass
        except Exception:
            pass
        finally:
            try:
                self._cat.blockSignals(False)
            except Exception:
                pass

    def _filter(self, defer: bool = False):
        # QLineEdit.textChanged / QComboBox.currentTextChanged pass a str.
        if isinstance(defer, str):
            t = getattr(self, '_search_filter_timer', None)
            if t is None:
                t = QTimer(self)
                t.setSingleShot(True)
                t.setInterval(120)
                t.timeout.connect(lambda: self._apply_product_filter(False))
                self._search_filter_timer = t
            t.start()
            return
        self._apply_product_filter(bool(defer))

    def _apply_product_filter(self, defer: bool = False):
        from desktop.utils.pos_search import SEARCH_LIMIT, filter_pos_products
        q = ''
        try:
            q = self._search.text()
        except Exception:
            q = ''
        cat = ''
        try:
            cat = self._cat.currentText()
        except Exception:
            cat = ''
        try:
            from desktop.utils.display_category import display_category as _dcat

            def _cat_match(p):
                if cat in ('All Categories', 'All', ''):
                    return True
                lab, _ = _dcat(p.get('category') or '', p.get('name') or '')
                raw = (p.get('category') or 'General')
                return lab == cat or raw == cat
        except Exception:
            def _cat_match(p):
                return (cat in ('All Categories', 'All', '')
                        or (p.get('category') or 'General') == cat)

        filtered = filter_pos_products(
            self.products, q, category=cat, cat_match=_cat_match,
            limit=SEARCH_LIMIT)
        show_empty = getattr(self, '_show_empty_overlay', None)
        if not filtered:
            self._prod_grid.clear()
            self._grid_painted = True
            if callable(show_empty):
                show_empty(True)
        else:
            if callable(show_empty):
                show_empty(False)
            self._prod_grid.set_currency(self._currency)
            self._prod_grid.set_light(bool(getattr(self, '_is_light', False)))
            self._prod_grid.set_categories_map(
                getattr(self, '_categories_by_name', None) or {})
            cols = self._product_columns()
            # Typing / category change: sync. Tab open: chunked for smoothness.
            use_chunk = bool(defer) and not str(q or '').strip()
            self._prod_grid.populate(filtered, columns=cols, chunked=use_chunk)
            self._grid_painted = True

    def _show_empty_overlay(self, visible: bool):
        empty = getattr(self, '_empty', None)
        panel = getattr(self, '_product_panel', None)
        if empty is None:
            return
        if visible and panel is not None:
            try:
                scroll = getattr(self, '_prod_scroll', None)
                if scroll is not None and scroll.isVisible():
                    empty.setGeometry(scroll.geometry())
                else:
                    top = 56
                    chips = getattr(self, '_cat_chips', None)
                    if chips is not None and chips.isVisible():
                        top = max(top, chips.y() + chips.height())
                    empty.setGeometry(
                        0, top, max(120, panel.width()), max(80, panel.height() - top))
                empty.raise_()
            except Exception:
                pass
            empty.show()
        else:
            empty.hide()
            try:
                empty.lower()
            except Exception:
                pass

    def _retint_prod_grid(self):
        """Update product card colors in place — no destroy/rebuild (theme switch fast path)."""
        if hasattr(self, '_prod_grid'):
            self._prod_grid.set_light(bool(getattr(self, '_is_light', False)))
            self._prod_grid.retint()
        refresh_pos_components(self)

    def _product_columns(self) -> int:
        layout_id = getattr(self, '_checkout_layout', 'simple_counter')
        if layout_id == 'checkout_pro':
            # Measured, not assumed: a hardcoded 2 clipped the right-hand card
            # whenever the Pro product column was under ~560px.
            try:
                left = getattr(self, '_product_panel', None) or self._left_panel
                available = int(left.width()) - 48
            except Exception:
                available = 380
            if hasattr(self, '_prod_grid'):
                return self._prod_grid.columns_for_width(available)
            return 1
        try:
            left = getattr(self, '_product_panel', None) or self._left_panel
            # Measured, never floored: the catalog column is drag-resizable now,
            # so a minimum of 640 would clip cards once it is narrowed.
            available = max(160, left.width() - 48)
        except Exception:
            available = 760
        if layout_id == 'retail_classic':
            # Prefer denser list feel on supermarket layout
            if hasattr(self, '_prod_grid'):
                return min(5, self._prod_grid.columns_for_width(available))
        if hasattr(self, '_prod_grid'):
            return self._prod_grid.columns_for_width(available)
        card_w = 214 if self._is_light else 206
        gap = 14
        cols = max(2, int((available + gap) // (card_w + gap)))
        return min(4, cols)

    def _prod_btn(self, p):
        """Legacy helper — ProductGrid builds ProductCard now."""
        card = ProductCard(
            p, currency=self._currency,
            card_size=(232, 156) if self._is_light else (226, 152))
        card.clicked.connect(self._add)
        return card

    def _set_card_text(self, label: QLabel, text: str, width: int, max_lines: int):
        """Clamp label text with ellipsis to keep POS cards readable."""
        safe = (text or '').strip()
        if not safe:
            label.setText('')
            return
        fm = label.fontMetrics()
        lines, current = [], ''
        for word in safe.split():
            probe = (current + ' ' + word).strip()
            if fm.horizontalAdvance(probe) <= width:
                current = probe
            else:
                if current:
                    lines.append(current)
                if len(lines) >= max_lines:
                    break
                if fm.horizontalAdvance(word) <= width:
                    current = word
                else:
                    chunk = ''
                    for ch in word:
                        test = chunk + ch
                        if fm.horizontalAdvance(test) <= width:
                            chunk = test
                        else:
                            if chunk:
                                lines.append(chunk)
                            if len(lines) >= max_lines:
                                chunk = ''
                                break
                            chunk = ch
                    current = chunk
        if current and len(lines) < max_lines:
            lines.append(current)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
        rendered = '\n'.join(lines[:max_lines])
        if rendered.replace('\n', ' ') != safe and lines:
            lines[-1] = fm.elidedText(lines[-1], Qt.ElideRight, width)
            rendered = '\n'.join(lines[:max_lines])
        label.setText(rendered)

    def _display_name(self, name: str, limit: int = 22) -> str:
        """
        Keep product names readable on buttons, even for long single words.
        Split into up to three lines and ellipsize tail.
        """
        if not name:
            return ''
        words = name.split()
        lines = []
        line = ''
        for w in words:
            if len(w) > 12:
                # Break very long words so they still wrap in button text.
                chunks = [w[i:i + 12] for i in range(0, len(w), 12)]
            else:
                chunks = [w]
            for c in chunks:
                candidate = (line + ' ' + c).strip()
                if len(candidate) <= 12:
                    line = candidate
                else:
                    if line:
                        lines.append(line)
                    line = c
                    if len(lines) >= 3:
                        break
            if len(lines) >= 3:
                break
        if line and len(lines) < 3:
            lines.append(line)
        text = '\n'.join(lines[:3])
        if len(words) > 0 and len(' '.join(words)) > len(text.replace('\n', ' ')):
            if '\n' in text:
                head, tail = text.rsplit('\n', 1)
                text = head + '\n' + (tail[:10] + '…')
            else:
                text = text[:11] + '…'
        return text

    def _line_gross(self, item):
        return round(float(item.get('quantity') or 0) * float(item.get('unit_price') or 0), 2)

    def _apply_line_total(self, item):
        """Clamp Disc (KES) to line gross and set line total after discount."""
        gross = self._line_gross(item)
        disc = max(0.0, min(float(item.get('discount') or 0), gross))
        item['discount'] = round(disc, 2)
        item['total'] = round(gross - disc, 2)
        return item['total']

    def _add(self, p, from_scan: bool = False):
        if from_scan:
            _sfx('barcode_scan')
        else:
            _sfx('product_add')
        # Low-stock cue (grouped) — never audio-only; UI already shows stock on cards
        try:
            stock_n = float(p.get('stock', 0) or 0)
            reorder = float(p.get('reorder_level') or p.get('min_stock') or 5)
            if 0 < stock_n <= reorder:
                _sfx('low_stock')
        except (TypeError, ValueError):
            pass
        for idx, item in enumerate(self.cart):
            if item['product_id'] == p['id']:
                item['quantity'] = round(item['quantity'] + 1.0, 2)
                self._apply_line_total(item)
                self._cart_select_idx = idx
                self._refresh_cart()
                return
        self.cart.append({
            'product_id':   p['id'],
            'product_name': p.get('name', ''),
            'sku':          p.get('sku', '') or '',
            'category':     p.get('category') or 'General',
            'quantity':     1.0,
            'unit_price':   p.get('price', 0),
            'discount':     0.0,
            'total':        p.get('price', 0),
        })
        self._cart_select_idx = len(self.cart) - 1
        self._refresh_cart()

    def _cart_fg(self):
        """High-contrast cart text — never inherit a stale light-mode dark fg on dark bg."""
        from desktop.utils.theme import DARK, LIGHT, ThemeManager
        light = bool(getattr(self, '_is_light', False) or ThemeManager.is_light())
        # Dark navy text on light cards; near-white on dark cards
        return '#0C1828' if light else '#F5F7FA'

    def _refresh_cart(self):
        for item in self.cart:
            self._apply_line_total(item)
        if hasattr(self, '_cart_list') and self._cart_list is not None:
            sel = getattr(self, '_cart_select_idx', None)
            if sel is None and self.cart:
                sel = len(self.cart) - 1
            elif self.cart and sel is not None:
                sel = max(0, min(int(sel), len(self.cart) - 1))
            else:
                sel = None
            self._cart_list.set_items(
                self.cart, currency=self._currency, select_index=sel)
            if sel is not None:
                self._cart_select_idx = sel
        n = len(self.cart)
        self._cnt.setText(f"{n} item{'s' if n != 1 else ''}")
        if getattr(self, '_checkout_layout', '') == 'checkout_pro':
            hdr = getattr(self, '_sale_hdr', None)
            if hdr is not None and not getattr(self, '_cart_maximized', False):
                hdr.setText(f'Current Sale ({n} item{"s" if n != 1 else ""})')
            elif getattr(self, '_cart_maximized', False):
                cnt = getattr(self, '_cnt', None)
                if cnt is not None:
                    try:
                        cnt.setText(f'{n} item{"s" if n != 1 else ""}')
                        cnt.show()
                    except Exception:
                        pass
        try:
            from desktop.pos.layouts.splitters import reveal_cart_stack
            reveal_cart_stack(self)
        except Exception:
            pass
        self._recalc()
        self._update_hold_buttons()

    def _update_hold_buttons(self):
        if hasattr(self, '_hold_btn'):
            self._hold_btn.setEnabled(bool(self.cart))
        if hasattr(self, '_resume_btn'):
            held = getattr(self, '_held', None)
            self._resume_btn.setEnabled(bool(held and held.get('cart')))
            n = len(held.get('cart') or []) if held else 0
            self._resume_btn.setToolTip(
                f'Restore held cart ({n} item{"s" if n != 1 else ""})'
                if n else 'No held sale')
        # Checkout Pro mirrors these buttons as tiles — keep both in step
        try:
            from desktop.pos.checkout_pro_chrome import sync_quick_action_state
            sync_quick_action_state(self)
        except Exception:
            pass

    def _snapshot_pos(self):
        import copy
        cust_id = None
        try:
            if hasattr(self, '_customer') and self._customer is not None:
                cust_id = self._customer.selected_id()
        except Exception:
            cust_id = None
        disc_txt = ''
        try:
            disc_txt = self._disc.text() if hasattr(self, '_disc') else ''
        except Exception:
            pass
        note = ''
        try:
            note = self._note.text() if hasattr(self, '_note') else ''
        except Exception:
            pass
        pay = 'Cash'
        try:
            pay = self._pay.currentText() if hasattr(self, '_pay') else 'Cash'
        except Exception:
            pass
        amount_paid = 0.0
        try:
            amount_paid = float(self._paid.value() or 0)
        except Exception:
            pass
        elec = 0.0
        emethod = ''
        try:
            elec = self._elec_portion() if self._is_split_method(pay) else 0.0
            emethod = self._elec_method_name() if elec > 0.009 else ''
        except Exception:
            pass
        mpesa_ref = ''
        try:
            mpesa_ref = self._mpesa_ref.text().strip() if hasattr(self, '_mpesa_ref') else ''
        except Exception:
            pass
        return {
            'cart': copy.deepcopy(self.cart),
            'customer_id': cust_id,
            'disc': disc_txt,
            'note': note,
            'payment': pay,
            'sale_type': getattr(self, '_pro_sale_type', 'cash'),
            'credit_to_apply': float(getattr(self, '_credit_to_apply', 0) or 0),
            'amount_paid': amount_paid,
            'electronic_paid': elec,
            'electronic_method': emethod,
            'mpesa_ref': mpesa_ref,
        }

    def _hold_sale(self):
        if not self.cart:
            _sfx('warning')
            soft_warn(self, 'Add items before holding a sale.')
            return
        replaced = bool(self._held and self._held.get('cart'))
        snap = self._snapshot_pos()
        self._held = snap
        try:
            from desktop.utils.held_sale import save_held_sale
            save_held_sale(snap)
        except Exception:
            pass
        self._clear()
        self._update_hold_buttons()
        _sfx('ok')
        if replaced:
            info_toast(self, 'Held sale replaced — use Resume to restore.')
        else:
            info_toast(self, 'Sale held — use Resume to restore.')

    def _suspend_sale(self):
        """Checkout Pro Suspend — same park backend as Hold (design label)."""
        if not self.cart:
            _sfx('warning')
            soft_warn(self, 'Add items before suspending a sale.')
            return
        replaced = bool(self._held and self._held.get('cart'))
        snap = self._snapshot_pos()
        self._held = snap
        try:
            from desktop.utils.held_sale import save_held_sale
            save_held_sale(snap)
        except Exception:
            pass
        self._clear()
        self._update_hold_buttons()
        _sfx('ok')
        if replaced:
            info_toast(self, 'Parked sale replaced — restore from Resume / Hold.')
        else:
            info_toast(self, 'Sale suspended — restore from Resume / Hold.')

    def _open_recent_sales(self):
        """Open business-day sales browser for the selected (or today) date."""
        self._open_business_day_sales()

    def _business_day_iso(self) -> str:
        from desktop.utils.shop_time import business_day_iso
        return business_day_iso(getattr(self, '_business_day', None))

    def _ensure_business_day_current(self):
        """Refresh QDateEdit max to shop today; unstick stale 'today' after year/clock drift."""
        from datetime import date as date_cls
        from desktop.utils.security import can_set_business_day
        from desktop.utils.shop_time import shop_today
        from desktop.utils.date_controls import apply_shop_day_edit
        today = shop_today()
        ed = getattr(self, '_biz_date', None)
        cur = getattr(self, '_business_day', today)
        if not isinstance(cur, date_cls):
            try:
                cur = date_cls(cur.year(), cur.month(), cur.day())
            except Exception:
                cur = today
        if ed is not None:
            old_max = ed.maximumDate()
            try:
                old_max_d = date_cls(old_max.year(), old_max.month(), old_max.day())
            except Exception:
                old_max_d = today
            # Max was frozen before calendar/clock moved forward → prior "today" pin
            if old_max_d < today and (not can_set_business_day(self.user) or cur >= old_max_d):
                cur = today
        if not can_set_business_day(self.user) or cur > today:
            cur = today
        self._business_day = cur
        if ed is not None:
            self._business_day = apply_shop_day_edit(ed, cur, today=today)
        self._sync_business_day_warn()

    def _sync_business_day_warn(self):
        warn = getattr(self, '_biz_warn', None)
        if warn is None:
            return
        from desktop.utils.shop_time import shop_today
        day = getattr(self, '_business_day', shop_today())
        if day != shop_today():
            warn.setText(f'Recording sales for {day.isoformat()} (not today)')
        else:
            warn.setText('')

    def _on_business_day_changed(self, qdate):
        from desktop.utils.security import can_set_business_day
        from desktop.utils.shop_time import shop_today
        from desktop.utils.date_controls import apply_shop_day_edit
        from datetime import date as date_cls
        today = shop_today()
        ed = getattr(self, '_biz_date', None)
        if not can_set_business_day(self.user):
            self._business_day = today
            if ed is not None:
                apply_shop_day_edit(ed, today, today=today)
            self._sync_business_day_warn()
            return
        try:
            new_day = date_cls(qdate.year(), qdate.month(), qdate.day())
        except Exception:
            return
        if new_day > today:
            soft_warn(self, 'Sale date cannot be in the future.')
            new_day = today
            if ed is not None:
                apply_shop_day_edit(ed, today, today=today)
        old = getattr(self, '_business_day', today)
        self._business_day = new_day
        self._sync_business_day_warn()
        if old != new_day:
            try:
                uid = (self.user.get('user') or self.user).get('id')
                uname = (self.user.get('user') or self.user).get('username') or 'staff'
                from desktop.utils.api_client import _audit
                _audit(
                    uid, uname, 'SET_BUSINESS_DAY', 'sales',
                    f"from={old.isoformat() if hasattr(old, 'isoformat') else old} "
                    f"to={new_day.isoformat()}",
                )
            except Exception:
                pass

    def _reset_business_day_today(self):
        from desktop.utils.shop_time import shop_today
        from desktop.utils.date_controls import apply_shop_day_edit
        today = shop_today()
        ed = getattr(self, '_biz_date', None)
        self._business_day = today
        if ed is not None:
            # Must raise maximumDate before setDate or Qt keeps the old year
            self._business_day = apply_shop_day_edit(ed, today, today=today)
        self._sync_business_day_warn()

    def _open_business_day_sales(self):
        from desktop.dialogs.business_day_dialog import (
            open_business_day_sales, BusinessDaySalesDialog,
        )
        mode, items, sale_id = open_business_day_sales(
            self.api, self,
            day=self._business_day_iso(),
            currency=getattr(self, '_currency', 'KES'),
            user=self.user,
        )
        if mode in (
            BusinessDaySalesDialog.RESULT_COPY,
            BusinessDaySalesDialog.RESULT_COPY_DAY,
        ) and items:
            self._apply_copied_sale_lines(
                items,
                source_sale_id=sale_id,
                copy_day=(mode == BusinessDaySalesDialog.RESULT_COPY_DAY),
            )

    def _apply_copied_sale_lines(self, items, *, source_sale_id=None, copy_day=False):
        """Load copied line items into cart; confirm if cart not empty."""
        import copy
        from PyQt5.QtWidgets import QMessageBox
        if self.cart:
            r = QMessageBox.question(
                self, 'Replace Cart?',
                'Current cart is not empty. Replace it with the copied sale lines?',
                QMessageBox.Yes | QMessageBox.No)
            if r != QMessageBox.Yes:
                return
        self.cart = copy.deepcopy(items)
        for it in self.cart:
            self._apply_line_total(it)
        note = getattr(self, '_note', None)
        if note is not None:
            tag = 'Copied day totals' if copy_day else f'Copied sale #{source_sale_id or "?"}'
            prev = (note.text() or '').strip()
            note.setText(f'{prev} | {tag}'.strip(' |') if prev else tag)
        self._refresh_cart()
        try:
            uid = (self.user.get('user') or self.user).get('id')
            uname = (self.user.get('user') or self.user).get('username') or 'staff'
            from desktop.utils.api_client import _audit
            _audit(
                uid, uname, 'COPY_SALE', 'sales',
                f"source_sale_id={source_sale_id or 'day'} "
                f"lines={len(items)} business_day={self._business_day_iso()} "
                f"copy_day={int(bool(copy_day))}",
            )
        except Exception:
            pass
        _sfx('ok')
        info_toast(
            self,
            f'{len(items)} line(s) loaded for {self._business_day_iso()} — review then Complete Sale.',
        )

    def _focus_notes(self):
        note = getattr(self, '_note', None)
        if note is None:
            return
        note.show()
        note.setFocus(Qt.OtherFocusReason)
        tip, ok = QInputDialog.getMultiLineText(
            self, 'Sale Notes', 'Notes for this sale:', note.text())
        if ok:
            note.setText(tip or '')
        if getattr(self, '_checkout_layout', '') == 'checkout_pro':
            note.hide()

    def _resume_held(self):
        held = getattr(self, '_held', None)
        if not held or not held.get('cart'):
            try:
                from desktop.utils.held_sale import load_held_sale
                held = load_held_sale()
                self._held = held
            except Exception:
                held = None
        if not held or not held.get('cart'):
            soft_warn(self, 'No parked sale to restore.')
            return
        if self.cart:
            r = QMessageBox.question(
                self, 'Replace Current Cart?',
                'Current cart will be replaced by the held sale. Continue?',
                QMessageBox.Yes | QMessageBox.No)
            if r != QMessageBox.Yes:
                return
        import copy
        self.cart = copy.deepcopy(held['cart'])
        if hasattr(self, '_disc') and held.get('disc') is not None:
            self._disc.blockSignals(True)
            self._disc.setText(str(held.get('disc') or ''))
            self._disc.blockSignals(False)
        if hasattr(self, '_note'):
            self._note.setText(str(held.get('note') or ''))
        pay = held.get('payment') or 'Cash'
        self._select_pay_method(pay)
        st = held.get('sale_type')
        if st and hasattr(self, '_sale_type') and hasattr(self._sale_type, 'set_current'):
            try:
                self._sale_type.set_current(st, emit=True)
            except Exception:
                self._pro_sale_type = st
        elif st:
            self._pro_sale_type = st
        self._credit_to_apply = float(held.get('credit_to_apply') or 0)
        cid = held.get('customer_id')
        try:
            if cid and hasattr(self, '_customer') and hasattr(self._customer, 'select_customer'):
                self._customer.select_customer(cid)
            elif hasattr(self, '_customer') and hasattr(self._customer, 'select_walk_in'):
                self._customer.select_walk_in()
            self._on_customer_changed()
        except Exception:
            pass
        # Restore tenders after sale-type chrome so Part pay does not wipe them
        try:
            em = (held.get('electronic_method') or '').strip()
            if em and hasattr(self, '_elec_method'):
                idx = self._elec_method.findText(em)
                if idx >= 0:
                    self._elec_method.setCurrentIndex(idx)
            elec = float(held.get('electronic_paid') or 0)
            paid = float(held.get('amount_paid') or 0)
            if elec > 0.009:
                self._set_elec_value(elec, mark_clean=False)
                self._elec_paid_dirty = True
            if paid > 0.009 or elec > 0.009:
                self._set_paid_value(paid, mark_clean=False)
                self._cash_paid_dirty = True
            ref = (held.get('mpesa_ref') or '').strip()
            if ref and hasattr(self, '_mpesa_ref'):
                self._mpesa_ref.setText(ref)
        except Exception:
            pass
        self._held = None
        try:
            from desktop.utils.held_sale import clear_held_sale
            clear_held_sale()
        except Exception:
            pass
        self._refresh_cart()
        _sfx('ok')

    def _parse_kes(self, text):
        """Parse typed KES amount; commas and spaces allowed."""
        s = (text or '').strip().replace(',', '').replace(' ', '')
        if not s or s in ('-', '.', '-.'):
            return 0.0
        try:
            return max(0.0, float(s))
        except ValueError:
            return None

    def _commit_line_disc_text(self, idx, ed):
        if not (0 <= idx < len(self.cart)):
            return
        parsed = self._parse_kes(ed.text())
        if parsed is None:
            ed.setText(f"{float(self.cart[idx].get('discount') or 0):.2f}")
            return
        self._set_line_disc(idx, parsed)
        # Reflect clamped value
        ed.blockSignals(True)
        ed.setText(f"{float(self.cart[idx].get('discount') or 0):.2f}")
        ed.blockSignals(False)

    def _set_line_disc(self, idx, v):
        if not (0 <= idx < len(self.cart)):
            return
        self._cart_select_idx = idx
        item = self.cart[idx]
        gross = self._line_gross(item)
        if gross <= 0:
            item['discount'] = 0.0
            item['total'] = 0.0
            if hasattr(self, '_cart_list'):
                self._cart_list.update_row(idx, item)
                self._cart_list.select_index(idx, focus_qty=False, scroll=False)
            self._recalc()
            return
        item['discount'] = float(v)
        self._apply_line_total(item)
        if hasattr(self, '_cart_list'):
            self._cart_list.update_row(idx, item)
            self._cart_list.select_index(idx, focus_qty=False, scroll=False)
        self._recalc()

    def _set_line_price(self, idx, v):
        if not (0 <= idx < len(self.cart)):
            return
        self._cart_select_idx = idx
        item = self.cart[idx]
        try:
            price = max(0.0, round(float(v), 2))
        except (TypeError, ValueError):
            price = float(item.get('unit_price') or 0)
        item['unit_price'] = price
        self._apply_line_total(item)
        if hasattr(self, '_cart_list'):
            self._cart_list.update_row(idx, item)
            self._cart_list.select_index(idx, focus_qty=False, scroll=False)
        self._recalc()

    def _bump_line_disc(self, idx, delta):
        if not (0 <= idx < len(self.cart)):
            return
        item = self.cart[idx]
        gross = self._line_gross(item)
        if gross <= 0:
            return
        new_d = max(0.0, min(gross, float(item.get('discount') or 0) + float(delta)))
        item['discount'] = round(new_d, 2)
        self._apply_line_total(item)
        if hasattr(self, '_cart_list'):
            self._cart_list.update_row(idx, item)
        self._recalc()

    def _qty(self, idx, v):
        if 0 <= idx < len(self.cart):
            self._cart_select_idx = idx
            q = round_qty(v, 0.25)
            self.cart[idx]['quantity'] = round(q, 2)
            self._apply_line_total(self.cart[idx])
            if hasattr(self, '_cart_list'):
                self._cart_list.update_row(idx, self.cart[idx])
                self._cart_list.select_index(idx, focus_qty=False, scroll=False)
            self._recalc()

    def _change_qty(self, idx, delta):
        if not (0 <= idx < len(self.cart)):
            return
        new_q = round_qty(self.cart[idx]['quantity'] + delta, 0.25)
        self.cart[idx]['quantity'] = round(new_q, 2)
        self._apply_line_total(self.cart[idx])
        self._cart_select_idx = idx
        self._refresh_cart()

    def _rm(self, idx):
        if 0 <= idx < len(self.cart):
            del self.cart[idx]
            sel = getattr(self, '_cart_select_idx', None)
            if not self.cart:
                self._cart_select_idx = None
            elif sel is None:
                self._cart_select_idx = len(self.cart) - 1
            elif idx < sel:
                self._cart_select_idx = sel - 1
            elif idx == sel:
                self._cart_select_idx = min(sel, len(self.cart) - 1)
            _sfx('product_remove')
            self._refresh_cart()

    def _cart_disc_value(self):
        """Cart-level discount only (not line discounts). Same across all layouts."""
        parsed = self._parse_kes(self._disc.text())
        return 0.0 if parsed is None else parsed

    def _commit_cart_disc(self):
        parsed = self._parse_kes(self._disc.text())
        if parsed is None:
            parsed = 0.0
        self._disc.blockSignals(True)
        self._disc.setText(f'{parsed:.2f}')
        self._disc.setReadOnly(False)
        self._disc.blockSignals(False)
        # Keep legacy Pro mirror in sync if present
        try:
            self._pro_cart_disc = float(parsed)
        except Exception:
            pass
        self._recalc()

    def _recalc(self):
        try:
            rate = float((self.config_getter() or {}).get('tax_rate', 0) or 0) / 100
            cur  = (self.config_getter() or {}).get('currency_symbol', 'KES') or 'KES'
        except Exception:
            rate = 0.0; cur = 'KES'
        self._currency = cur
        for item in self.cart:
            self._apply_line_total(item)
        # Subtotal before discount; total disc = cart KES + per-line KES
        sub = sum(self._line_gross(i) for i in self.cart)
        line_dis = round(sum(float(i.get('discount') or 0) for i in self.cart), 2)
        cart_dis = round(self._cart_disc_value(), 2)
        # Cap cart discount so total discount never exceeds subtotal
        cart_dis = min(cart_dis, max(0.0, sub - line_dis))
        if abs(cart_dis - self._cart_disc_value()) > 0.001:
            self._disc.blockSignals(True)
            self._disc.setText(f'{cart_dis:.2f}')
            self._disc.blockSignals(False)
        try:
            self._pro_cart_disc = float(cart_dis)
        except Exception:
            pass
        dis = round(line_dis + cart_dis, 2)
        tax = round(max(0, sub - dis) * rate, 2)
        tot = round(max(0, sub - dis) + tax, 2)
        self._subtotal = sub; self._discount = dis; self._tax = tax; self._total = tot
        if hasattr(self, '_summary') and hasattr(self._summary, 'set_amounts'):
            self._summary.set_amounts(cur, sub, tax, tot, discount=dis)
        else:
            self._sub_lbl.setText(f'{cur} {sub:,.2f}')
            self._tax_lbl.setText(f'{cur} {tax:,.2f}')
            self._tot_lbl.setText(f'{cur} {tot:,.2f}')
        # Cart-level Discount field stays editable on every layout (line Disc is per row)
        try:
            if hasattr(self, '_disc_lbl') and self._disc_lbl is not None:
                self._disc_lbl.setText(f'Discount ({cur})')
                tip = (
                    f'Cart-level discount in {cur}. '
                    f'Line discounts currently {line_dis:,.2f} (edit Disc on each cart row).'
                )
                self._disc_lbl.setToolTip(tip)
            if hasattr(self, '_disc') and self._disc is not None:
                self._disc.setReadOnly(False)
                self._disc.setToolTip(
                    f'Cart discount ({cur}). Type amount and press Enter. '
                    'Per-item Disc is on each cart line.')
        except Exception:
            pass
        # Cap credit apply to new total
        if self._credit_to_apply > tot:
            self._credit_to_apply = tot
            if hasattr(self, '_credit_spin'):
                self._credit_spin.blockSignals(True)
                self._credit_spin.setMaximum(tot)
                self._credit_spin.setValue(tot)
                self._credit_spin.blockSignals(False)
        elif hasattr(self, '_credit_spin') and self._credit_frame.isVisible():
            cust_id = self._customer.selected_id()
            bal = float(self._wallet_by_customer.get(cust_id) or 0) if cust_id else 0.0
            self._credit_spin.setMaximum(min(bal, tot) if tot > 0 else bal)
        # Cap electronic split to amount due before rounding
        if hasattr(self, '_elec_paid'):
            raw_due = round(max(0.0, tot - float(self._credit_to_apply or 0)), 2)
            self._elec_paid.setMaximum(raw_due if raw_due > 0 else 0)
            if self._elec_paid.value() > raw_due:
                self._elec_paid.blockSignals(True)
                self._elec_paid.setValue(raw_due)
                self._elec_paid.blockSignals(False)
        self._compute_rounding()
        self._update_rounding_ui()
        method = self._pay.currentText()
        part = self._is_part_sale()
        if method in ('Cash', 'Mixed') and not part:
            self._maybe_autofill_cash_paid(focus=False)
        elif method == 'M-Pesa' and not part:
            self._set_paid_value(self._amount_due())
        elif method in ('Card', 'Bank Transfer', 'Cheque', 'Airtel Money') and not part:
            self._set_paid_value(self._amount_due())
        self._calc_change()

    def _calc_change(self):
        due = self._amount_due()
        paid = self._paid.value()
        method = self._pay.currentText() if hasattr(self, '_pay') else 'Cash'
        from desktop.utils.pos_light_theme import L, FS
        from desktop.utils.auto_fill import AutoFillService
        ok_color = L['ok'] if self._is_light else C['ok']
        err_color = L['err'] if self._is_light else C['err']
        warn_color = (
            L.get('warn', C.get('warn', '#E8A838')) if self._is_light
            else C.get('warn', '#E8A838')
        )
        chg_sz = FS['change'] if self._is_light else '22px'

        if self._is_part_sale() or method == 'Part Payment':
            cash, elec, paid_now = self._tendered_now(method)
            rem = max(0.0, round(due - paid_now, 2))
            self._chg_lbl.setText('Balance Due')
            self._chg.setText(f'{self._currency} {rem:,.2f}')
            tone = ok_color if rem < 0.01 else warn_color
            self._chg.setStyleSheet(
                f"color:{tone};font-size:{chg_sz};font-weight:700;background:transparent;")
            if hasattr(self, '_split_frame') and self._split_frame.isVisible():
                self._update_rounding_ui()
        elif AutoFillService.is_cash_like(method) or method in ('Credit Sale', 'Credit Account'):
            elec = self._elec_portion() if self._is_split_method(method) else 0.0
            # Split: Change/Remaining is vs cash portion only
            compare_due = self._cash_due_amount() if elec > 0.009 else due
            st = AutoFillService.cash_change_state(paid, compare_due)
            if elec > 0.009 and st.get('tone') == 'err':
                # Remaining on total bill when cash short
                rem_total = max(0.0, round(due - elec - paid, 2))
                if rem_total > 0.009:
                    self._chg_lbl.setText('Remaining')
                    self._chg.setText(f'{self._currency} {rem_total:,.2f}')
                    self._chg.setStyleSheet(
                        f"color:{err_color};font-size:{chg_sz};font-weight:700;background:transparent;")
                else:
                    self._chg_lbl.setText(st['label'])
                    self._chg.setText(f"{self._currency} {st['amount']:,.2f}")
                    self._chg.setStyleSheet(
                        f"color:{err_color};font-size:{chg_sz};font-weight:700;background:transparent;")
            else:
                self._chg_lbl.setText(st['label'])
                self._chg.setText(f"{self._currency} {st['amount']:,.2f}")
                color = {'ok': ok_color, 'warn': warn_color, 'err': err_color}.get(
                    st['tone'], ok_color)
                self._chg.setStyleSheet(
                    f"color:{color};font-size:{chg_sz};font-weight:700;background:transparent;")
            # Keep split summary in sync when Cash Paid edits
            if hasattr(self, '_split_frame') and self._split_frame.isVisible():
                self._update_rounding_ui()
        else:
            # M-Pesa Difference label handled below; keep Change neutral when hidden
            chg = max(0.0, paid - due)
            self._chg.setText(f'{self._currency} {chg:,.2f}')
            self._chg.setStyleSheet(
                f"color:{ok_color if paid >= due or due == 0 else err_color};"
                f"font-size:{chg_sz};font-weight:700;background:transparent;")

        if hasattr(self, '_var_frame') and self._is_till_method():
            self._expected_lbl.setText(f'Expected Amount: {self._currency} {due:,.2f}')
            self._received_lbl.setText(f'Received Amount: {self._currency} {paid:,.2f}')
            diff = round(paid - due, 2)
            if diff > 0.009:
                self._diff_lbl.setText(
                    f'Difference: {self._currency} {diff:,.2f} excess — choose handling at checkout')
                self._diff_lbl.setStyleSheet(
                    f"color:{warn_color};font-size:12px;font-weight:700;background:transparent;")
            elif diff < -0.009:
                self._diff_lbl.setText(
                    f'Difference: {self._currency} {diff:,.2f} short')
                self._diff_lbl.setStyleSheet(
                    f"color:{err_color};font-size:12px;font-weight:700;background:transparent;")
            else:
                self._diff_lbl.setText(f'Difference: {self._currency} 0.00')
                self._diff_lbl.setStyleSheet(
                    f"color:{ok_color};font-size:12px;font-weight:600;background:transparent;")

    def _clear(self):
        """Manual Clear cart — full After Sale defaults (Walk-in, Cash, focus)."""
        from desktop.utils.state_reset import StateResetManager
        cfg = {}
        try:
            cfg = self.config_getter() or {}
        except Exception:
            pass
        StateResetManager.reset_pos(self, cfg, force_walk_in=True)

    def _process(self):
        if getattr(self, '_processing_sale', False):
            return
        if not self.cart:
            _sfx('warning')
            soft_warn(self, 'Add items before charging.')
            return
        # Quotation mode (Checkout Pro): print preview only — no stock / payment
        if getattr(self, '_pro_sale_type', 'cash') == 'quotation':
            self._preview()
            return
        self._processing_sale = True
        charge = getattr(self, '_charge_btn', None)
        if charge is not None:
            try:
                charge.setEnabled(False)
            except Exception:
                pass
        try:
            self._process_impl()
        finally:
            self._processing_sale = False
            if charge is not None:
                try:
                    charge.setEnabled(True)
                except Exception:
                    pass

    def _process_impl(self):
        pay_method = self._pay.currentText()
        is_part = self._is_part_sale()
        is_credit = self._is_credit_sale()
        is_debt = is_part or is_credit
        due = self._amount_due()
        credit_applied = round(float(self._credit_to_apply or 0), 2)
        cfg = self.config_getter() or {}
        variance_enabled = cfg.get('variance_enabled', '1') == '1'

        if pay_method in ('Cash', 'Mixed') and not is_part:
            elec = self._elec_portion()
            cash_due = self._cash_due_amount()
            cash_paid = float(self._paid.value() or 0)
            if pay_method == 'Mixed' and elec < 0.009 and cash_paid + 0.009 < due:
                from desktop.utils.payment_tenders import remainder_electronic
                rem = remainder_electronic(due, cash_paid, 0.0)
                if rem > 0.009:
                    self._set_elec_value(rem, mark_clean=True)
                    self._compute_rounding()
                    due = self._amount_due()
                    elec = self._elec_portion()
                    cash_due = self._cash_due_amount()
            if elec > 0.009:
                if cash_paid + 0.009 < cash_due:
                    em = self._elec_method_name()
                    soft_warn(
                        self,
                        f'Cash Paid is less than cash due '
                        f'({self._currency} {cash_due:,.2f}); '
                        f'{em}: {self._currency} {elec:,.2f}.')
                    return
            elif cash_paid + 0.009 < due:
                soft_warn(
                    self,
                    'Cash Paid is less than Amount Due — pay remainder, Split, or Part Payment.')
                return
        if is_part:
            _c, _e, _paid_chk = self._tendered_now(pay_method)
            if _paid_chk < 0.01:
                soft_warn(self, 'Enter the amount paid now — leftover becomes customer debt.')
                return
            if _paid_chk + 0.009 >= due:
                soft_warn(self, 'Paid covers the full total — use Paid now instead of Part pay.')
                return
        if pay_method == 'M-Pesa':
            if not cfg.get('mpesa_till', '').strip() and not cfg.get('mpesa_paybill', '').strip():
                soft_warn(
                    self,
                    'M-Pesa till/paybill not set in Settings — recording sale anyway.')
            if not is_part and self._paid.value() + 0.009 < due:
                soft_warn(
                    self,
                    f'Received Amount is less than Expected ({self._currency} {due:,.2f}).')
                return

        if is_credit:
            paid_now = 0.0
            cash_paid_now = 0.0
            elec_now = 0.0
        else:
            cash_paid_now, elec_now, paid_now = self._tendered_now(pay_method)
        elec_method_name = self._elec_method_name() if elec_now > 0.009 else ''

        cust_id = None
        if hasattr(self, '_customer'):
            cust_id = self._customer.selected_id()
        if is_debt and not cust_id:
            from desktop.dialogs.credit_customer_dialogs import ensure_credit_customer
            cust_id = ensure_credit_customer(self, self.api)
            if not cust_id:
                return
            # Reload customers and assign without leaving POS / clearing cart
            try:
                customers = self.api.get_customers() or []
                self._wallet_by_customer = {
                    c['id']: float(c.get('wallet_balance') or 0)
                    for c in customers if c.get('id')
                }
                self._customer.load_customers(customers)
                if hasattr(self._customer, 'select_customer'):
                    self._customer.select_customer(cust_id)
                else:
                    idx = self._customer.findData(cust_id)
                    if idx >= 0:
                        self._customer.setCurrentIndex(idx)
                self._on_customer_changed()
            except Exception:
                pass
        if credit_applied > 0.009 and not cust_id:
            soft_warn(self, 'Select a customer to apply store credit.')
            return

        variance_payload = None
        change_amount = 0.0
        # Till variance uses full paid vs due; cash split uses cash overpayment only
        if self._is_till_method(pay_method):
            excess = round(paid_now - due, 2) if not is_debt else 0.0
        elif self._is_split_method(pay_method) and elec_now > 0.009:
            excess = round(cash_paid_now - self._cash_due_amount(), 2) if not is_debt else 0.0
        else:
            excess = round(paid_now - due, 2) if not is_debt else 0.0

        _cash_like_excess = (
            pay_method == 'Cash'
            or (hasattr(self, '_is_split_method') and self._is_split_method(pay_method))
        )
        if variance_enabled and excess > 0.009 and (
                self._is_till_method(pay_method) or _cash_like_excess):
            from desktop.dialogs.payment_variance_dialog import PaymentVarianceDialog
            cust_name = ''
            if cust_id and hasattr(self, '_customer'):
                cust_name = self._customer.currentText().split('  ·  ')[0]
            dlg = PaymentVarianceDialog(
                self, self._currency, due, paid_now, excess,
                settings=cfg, has_customer=bool(cust_id),
                customer_name=cust_name)
            if dlg.exec_() != QDialog.Accepted or not dlg.result_data:
                return
            variance_payload = dlg.result_data
            # Manager approval when excess above threshold
            try:
                max_cash = float(cfg.get('variance_max_cashier', 1000) or 1000)
            except (TypeError, ValueError):
                max_cash = 1000.0
            if excess > max_cash + 0.009:
                from desktop.utils.security import ask_superadmin_pin, has_permission
                role_ok = has_permission(self.user, 'sales.variance_approve')
                if not role_ok:
                    if not ask_superadmin_pin(
                        self.api, self,
                        reason=f'Approve variance {self._currency} {excess:,.2f}'):
                        return
                    variance_payload['manager_approved'] = True
                    variance_payload['manager_name'] = 'superadmin-pin'
                else:
                    u = self.user.get('user', {}) if isinstance(self.user, dict) else {}
                    variance_payload['manager_approved'] = True
                    variance_payload['manager_name'] = (
                        u.get('full_name') or u.get('username') or 'manager')
            if variance_payload.get('handling') == 'return_change':
                change_amount = excess
            # No centered Confirm M-Pesa modal — cashier already chose Till / M-Pesa
            handle_label = {
                'return_change': 'Return Change',
                'additional_payment': 'Additional Customer Payment',
                'deposit': 'Customer Deposit',
                'transport': 'Transport/Delivery Fee',
                'tip': 'Tip',
                'advance': 'Advance Payment',
                'miscellaneous': 'Miscellaneous',
            }.get(variance_payload['handling'], variance_payload['handling'])
            if self._is_till_method(pay_method):
                info_toast(
                    self,
                    f'M-Pesa {self._currency} {paid_now:,.2f} · excess → {handle_label}',
                    tone='ok',
                    ms=2500,
                )
        elif pay_method == 'M-Pesa':
            # Proceed without Yes/No — Amount Paid already entered
            change_amount = max(0.0, excess)
        elif not is_debt and not variance_payload:
            if self._is_split_method(pay_method) and elec_now > 0.009:
                change_amount = max(0.0, round(cash_paid_now - self._cash_due_amount(), 2))
            else:
                change_amount = max(0.0, paid_now - due)

        try:
            info = self._compute_rounding()
            round_adj = float(info.get('adjustment') or 0)
            original_due = float(info.get('original_due', due))
            payable = float(info.get('amount_due', due))
            # Use rounded due for cash validation already done via _amount_due()
            final_total = round(float(info.get('cart_total', self._total)) + round_adj, 2)
            # When credit applied, final_total for storage = cart + adj (credit separate)
            cart_total = float(info.get('cart_total', self._total))
            sale_total = round(cart_total + round_adj, 2) if abs(round_adj) > 0.009 else cart_total
            elec = float(info.get('electronic') or elec_now or 0)
            is_split = elec > 0.009 and self._is_split_method(pay_method)
            if is_part:
                pay_label = 'part payment'
            elif is_credit:
                pay_label = 'credit sale'
            else:
                pay_label = (
                    'mixed' if is_split
                    else (pay_method.lower() if pay_method else 'cash')
                )
            from desktop.utils.payment_tenders import build_tenders, format_tenders
            tenders = []
            if is_split:
                tenders = build_tenders(
                    cash_paid=cash_paid_now,
                    electronic_paid=elec,
                    electronic_method=elec_method_name,
                    store_credit=credit_applied,
                )
            elif is_part and paid_now > 0.009:
                tenders = build_tenders(
                    cash_paid=paid_now if pay_method in ('Cash', 'Part Payment') else 0.0,
                    electronic_paid=(
                        paid_now if pay_method not in ('Cash', 'Part Payment', 'Mixed')
                        else 0.0
                    ),
                    electronic_method=(
                        pay_method if pay_method not in ('Cash', 'Part Payment', 'Mixed')
                        else ''
                    ),
                    store_credit=credit_applied,
                )
                if pay_method not in ('Cash', 'Part Payment', 'Mixed') and paid_now > 0.009:
                    elec = paid_now
                    elec_method_name = pay_method
                    cash_paid_now = 0.0
            note_bits = [self._note.text().strip()]
            if is_split:
                note_bits.append('Split: ' + format_tenders(tenders))
            notes_joined = ' | '.join(b for b in note_bits if b)
            sale_payload = {
                'items':          self.cart,
                'subtotal':       self._subtotal,
                'discount':       self._discount,
                'tax':            self._tax,
                'total':          sale_total,
                'original_total': cart_total,
                'cash_rounding_adj': round_adj,
                'electronic_paid': elec,
                'electronic_method': elec_method_name if elec > 0.009 else '',
                'cash_paid':      cash_paid_now if (is_split or elec > 0.009) else paid_now,
                'cash_original':  float(info.get('cash_original') or 0),
                'cash_rounded':   float(info.get('cash_rounded') or 0),
                'payment_method': pay_label,
                'amount_paid':    paid_now,
                'change_amount':  change_amount,
                'credit_applied': credit_applied,
                'payment_tenders': tenders,
                'notes':          notes_joined,
                'mpesa_ref': (
                    self._mpesa_ref.text().strip()
                    if (pay_method == 'M-Pesa' or (is_split and elec_method_name == 'M-Pesa'))
                    else ''
                ),
                'sale_date':      self._business_day_iso(),
            }
            if cust_id:
                sale_payload['customer_id'] = cust_id
            if variance_payload:
                sale_payload['variance'] = variance_payload
            res = self.api.create_sale(sale_payload)
            if res and res.get('success'):
                rn  = res.get('receipt_number', 'N/A')
                sid = res.get('sale_id')
                self._last_sale_id = sid
                self._last_receipt = rn
                try:
                    from desktop.utils.audio_manager import get_audio
                    get_audio().play_payment(pay_method)
                    _sfx('sale_complete')
                except Exception:
                    _sfx('sale_complete')
                # Part Payment / Credit Sale → create a debt invoice for the balance
                if is_debt:
                    self._create_debt_invoice(
                        sale_id=sid,
                        receipt_number=rn,
                        total=cart_total,
                        paid=paid_now + credit_applied,
                        method=pay_label,
                        tenders=tenders,
                    )
                else:
                    msg = (
                        f'✓  Sale recorded\n\nInvoice:  {rn}\n'
                        f'Total:    {self._currency} {sale_total:,.2f}\n'
                    )
                    sale_day = res.get('sale_date') or self._business_day_iso()
                    from desktop.utils.shop_time import shop_today
                    if sale_day and sale_day != shop_today().isoformat():
                        msg += f'Sale date: {sale_day}\n'
                    if is_split:
                        msg += (
                            f'{elec_method_name}: {self._currency} {elec:,.2f}\n'
                            f'Cash:     {self._currency} {cash_paid_now:,.2f}\n'
                        )
                    else:
                        msg += f'Received: {self._currency} {paid_now:,.2f}\n'
                    if abs(round_adj) > 0.009:
                        msg += (
                            f'Original: {self._currency} {cart_total:,.2f}\n'
                            f'Rounding: {self._currency} {round_adj:+,.2f}\n'
                        )
                    if credit_applied > 0:
                        msg += f'Credit used: {self._currency} {credit_applied:,.2f}\n'
                    if variance_payload:
                        h = variance_payload.get('handling')
                        msg += f'Excess:   {self._currency} {excess:,.2f} → {h}\n'
                        wb = res.get('wallet_balance')
                        if wb is not None:
                            msg += f'Wallet:   {self._currency} {float(wb):,.2f}\n'
                    elif change_amount > 0:
                        msg += f'Change:   {self._currency} {change_amount:,.2f}\n'
                    sale_complete_feedback(self, 'Sale Complete', msg)
                self._try_print_receipt(sid, rn)
                # Refresh stock/products first, then force After Sale defaults
                # (Walk-in must win after credit sale — do not leave John selected).
                self.refresh(force=True)
                from desktop.utils.state_reset import StateResetManager
                cfg = {}
                try:
                    cfg = self.config_getter() or {}
                except Exception:
                    pass
                StateResetManager.reset_pos(self, cfg, force_walk_in=True)
                self.sale_completed.emit()
            else:
                err = (res or {}).get('error') if isinstance(res, dict) else None
                _sfx('error')
                soft_warn(self, err or 'Failed to record sale.')
        except Exception as e:
            _sfx('error')
            soft_warn(self, f'Sale failed: {e}')

    def _get_printer(self):
        if self._printer_mgr is None:
            from printing.printer_engine import PrinterManager
            self._printer_mgr = PrinterManager(self.config_getter)
        return self._printer_mgr

    def _build_print_data(self, sale_id, receipt_number=None):
        sale = self.api.get_sale(sale_id) if sale_id else {}
        if not sale:
            return None
        elec = float(sale.get('electronic_paid') or 0)
        notes = sale.get('notes', '') or ''
        elec_method = (sale.get('electronic_method') or '').strip()
        if not elec_method and elec > 0.009 and 'Split:' in notes:
            # "Split: M-Pesa 600.00 + Cash 400.00"
            try:
                part = notes.split('Split:', 1)[1].strip()
                elec_method = part.split()[0]
            except Exception:
                elec_method = 'Electronic'
        cash_paid = float(sale.get('cash_paid') or 0)
        if cash_paid < 0.009 and elec > 0.009:
            cash_paid = max(0.0, round(float(sale.get('amount_paid') or 0) - elec, 2))
        variance = sale.get('variance') or {}
        handling = (variance.get('handling') or sale.get('variance_handling') or '').strip().lower()
        amount_paid = float(sale.get('amount_paid') or 0)
        change_amount = float(sale.get('change_amount') or 0)
        # Customer receipt: additional payment is internal-only — print as exact tender
        print_variance = variance
        if handling == 'additional_payment':
            amount_paid = float(sale.get('total') or amount_paid)
            change_amount = 0.0
            print_variance = {}
        return {
            'receipt_number': receipt_number or sale.get('receipt_number', ''),
            'created_at':     sale.get('created_at', datetime.now().isoformat()),
            'sale_date':      sale.get('sale_date') or '',
            'cashier_name':   sale.get('cashier_name', ''),
            'items':          sale.get('items', []),
            'subtotal':       float(sale.get('subtotal') or 0),
            'discount':       float(sale.get('discount') or 0),
            'tax':            float(sale.get('tax') or 0),
            'total':          float(sale.get('total') or 0),
            'original_total': float(sale.get('original_total') or 0) or None,
            'cash_rounding_adj': float(sale.get('cash_rounding_adj') or 0),
            'payment_method': sale.get('payment_method', 'cash'),
            'amount_paid':    amount_paid,
            'change_amount':  change_amount,
            'credit_applied': float(sale.get('credit_applied') or 0),
            'customer_name':  sale.get('customer_name', '') or '',
            'wallet_balance': sale.get('wallet_balance'),
            'variance':       print_variance,
            'notes':          notes,
            'electronic_paid': elec,
            'electronic_method': elec_method,
            'cash_paid': cash_paid,
            'mpesa_till':     (self.config_getter() or {}).get('mpesa_till', ''),
            'mpesa_paybill':  (self.config_getter() or {}).get('mpesa_paybill', ''),
            'mpesa_ref':      sale.get('mpesa_ref', '') or '',
            'receipt_footer': (self.config_getter() or {}).get('receipt_footer', 'Thank you!'),
        }

    def _try_print_receipt(self, sale_id, receipt_number):
        """Print receipt after sale — failures never affect the recorded sale."""
        cfg = self.config_getter() or {}
        if cfg.get('auto_print', '1') != '1':
            return
        try:
            data = self._build_print_data(sale_id, receipt_number)
            if data:
                self._get_printer().print_receipt(data)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                'Receipt print failed (sale %s kept): %s', receipt_number, e)

    def _reprint_receipt(self):
        default = self._last_receipt or ''
        receipt, ok = QInputDialog.getText(
            self, 'Reprint Receipt',
            'Receipt number to reprint:',
            text=default)
        if not ok or not receipt.strip():
            return
        receipt = receipt.strip()
        try:
            from desktop.utils.api_client import _db
            db = _db()
            row = db.execute(
                "SELECT id, status FROM sales WHERE receipt_number=?", (receipt,)
            ).fetchone()
            db.close()
            if not row:
                soft_warn(self, f'No sale found: {receipt}')
                return
            if row['status'] == 'voided':
                soft_warn(self, 'This sale was voided — receipt not reprinted.')
                return
            data = self._build_print_data(row['id'], receipt)
            if not data:
                soft_warn(self, 'Could not load sale data.')
                return
            self._get_printer().print_receipt(data)
            info_toast(self, f'Receipt {receipt} sent to printer.')
        except Exception as e:
            soft_warn(self, f'Print error: {e}')

    def _void_sale(self):
        """Void a completed sale from POS (reason dropdown + Super-Admin PIN)."""
        from desktop.utils.security import prompt_void_sale
        prefill = getattr(self, '_last_receipt', '') or ''
        if prompt_void_sale(self.api, self, receipt_prefill=prefill):
            _sfx('void')
            self.sale_completed.emit()

    def _open_return_sale(self):
        from desktop.dialogs.return_sale_dialog import prompt_return_sale
        prefill = getattr(self, '_last_receipt', '') or ''
        if prompt_return_sale(self.api, self, receipt_prefill=prefill):
            _sfx('ok')
            self.sale_completed.emit()

    def _create_debt_invoice(self, sale_id, receipt_number, total, paid, method,
                             tenders=None):
        """Auto-create debt linked to this completed sale (no orphan path)."""
        cust_id = None
        if hasattr(self, '_customer'):
            cust_id = self._customer.selected_id()
        if not cust_id or not sale_id or not receipt_number:
            soft_warn(
                self,
                'Sale recorded but debt invoice missing customer/sale/receipt — contact admin.')
            return
        try:
            from datetime import date as _date, timedelta as _td
            res = self.api.create_debt_invoice({
                'customer_id': cust_id,
                'sale_id': sale_id,
                'receipt_number': receipt_number,
                'total_amount': total,
                'amount_paid': paid,
                'payment_method': (method or 'credit sale').lower(),
                'due_date': (_date.today() + _td(days=30)).isoformat(),
                'notes': f'Auto from POS {method}',
            })
            # Idempotent: create_sale may already have created the invoice.
            if res and (res.get('success') or res.get('invoice_id')):
                bal = float(res.get('balance') or 0)
                inv = res.get('invoice_number', '')
                if not inv and res.get('invoice_id'):
                    try:
                        existing = self.api.get_debt_invoice(int(res['invoice_id']))
                        inv = (existing or {}).get('invoice_number') or inv
                        if bal <= 0 and existing:
                            bal = float(existing.get('balance') or 0)
                    except Exception:
                        pass
                msg = (
                    f'✓  Credit sale recorded\n\n'
                    f'Receipt:  {receipt_number}\n'
                    f'Debt Inv: {inv}\n'
                    f'Total:    {self._currency} {total:,.2f}\n'
                    f'Paid now: {self._currency} {paid:,.2f}\n'
                    f'Balance:  {self._currency} {bal:,.2f}\n'
                )
                try:
                    from desktop.utils.payment_tenders import format_tenders
                    tlabel = format_tenders(tenders)
                    if tlabel:
                        msg += f'Tenders:  {tlabel}\n'
                except Exception:
                    pass
                if bal <= 0.009:
                    msg += '\n✓ Fully paid'
                else:
                    msg += '\n! Outstanding balance due'
                sale_complete_feedback(self, 'Sale Complete', msg)
            else:
                err = (res or {}).get('error', 'Failed to create debt invoice.')
                soft_warn(
                    self,
                    f'Sale {receipt_number} recorded — debt create failed: {err}')
        except Exception as e:
            soft_warn(
                self,
                f'Sale {receipt_number} recorded — debt create failed: {e}')

    def _get_debt_parent(self):
        """Minimal proxy so debt dialogs get api + currency."""
        class _Proxy:
            pass
        p = _Proxy()
        p.api = self.api
        p._currency = self._currency
        return p

    def _preview(self):
        if not self.cart:
            soft_warn(self, 'Add items to preview.')
            return
        try:
            from printing.printer_engine import generate_receipt_text
            cfg  = self.config_getter() or {}
            u    = self.user.get('user', {})
            info = self._compute_rounding()
            data = {
                'receipt_number': 'PREVIEW',
                'created_at':     datetime.now().isoformat(),
                'cashier_name':   u.get('full_name') or u.get('username', 'Staff'),
                'items':          self.cart,
                'subtotal':       self._subtotal,
                'discount':       self._discount,
                'tax':            self._tax,
                'total':          float(info.get('amount_due', self._total)) + float(self._credit_to_apply or 0)
                                  if abs(float(info.get('adjustment') or 0)) > 0.009
                                  else self._total,
                'original_total': float(info.get('cart_total', self._total)),
                'cash_rounding_adj': float(info.get('adjustment') or 0),
                'payment_method': self._pay.currentText(),
                'amount_paid':    self._paid.value(),
                'change_amount':  max(0.0, self._paid.value() - self._amount_due()),
                'credit_applied': float(self._credit_to_apply or 0),
                'receipt_footer': cfg.get('receipt_footer', 'Thank you!'),
                'mpesa_till':     cfg.get('mpesa_till', ''),
                'mpesa_paybill':  cfg.get('mpesa_paybill', ''),
                'mpesa_ref':      self._mpesa_ref.text().strip(),
            }
            if hasattr(self, '_customer') and self._customer.selected_id():
                data['customer_name'] = self._customer.currentText().split('  ·  ')[0]
            txt = generate_receipt_text(data, cfg.get('shop_name', 'My Shop'), self._currency)
            dlg = QDialog(self); dlg.setWindowTitle('Invoice Preview')
            dlg.resize(480, 580); lv = QVBoxLayout(dlg)
            te = QTextEdit(); te.setReadOnly(True); te.setFont(QFont('Consolas', 11))
            te.setStyleSheet(f"background:{C['app']};color:{C['text']};border:none;")
            te.setPlainText(txt); lv.addWidget(te)
            cb = SecondaryBtn('Close'); cb.clicked.connect(dlg.close); lv.addWidget(cb)
            dlg.exec_()
        except Exception as e:
            soft_warn(self, f'Preview error: {e}')
