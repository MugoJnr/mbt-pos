"""MBT POS - Inventory | MugoByte Technologies"""
import logging

from PyQt5.QtWidgets import *
from PyQt5.QtCore    import *
from PyQt5.QtGui     import *

_log = logging.getLogger('inventory')
from desktop.utils.theme   import C, qss_alpha, apply_themed_dialog
from desktop.utils.widgets import (Card, H2, Caption, PrimaryBtn, SecondaryBtn,
                                    DangerBtn, GhostBtn, SearchBar, make_table, tbl_item,
                                    tbl_right, tbl_center, page_layout, PageChrome,
                                    retint_table_items,
                                    apply_table_row_backgrounds, table_row_bg_hex)
from desktop.utils.security import (has_permission, require_permission,
                                     ask_superadmin_pin, ROLE_SUPERADMIN)
from desktop.utils.option_lists import STOCK_ADJUSTMENT_REASONS, PRODUCT_STATUSES
from desktop.utils.select_controls import (
    SearchableSelect, ReasonSelect, Select, ReasonDialog,
)


def _safe_int(v, default=0):
    if v is None:
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _safe_float(v, default=0.0):
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _fmt_stock(v):
    """Display stock â€” show decimals when needed (e.g. 89.75 after quarter sales)."""
    f = _safe_float(v, 0)
    if abs(f - round(f)) < 1e-9:
        return str(int(round(f)))
    return f"{f:g}"


class InventoryTab(QWidget):
    def __init__(self, api, user, db_path, config_getter):
        super().__init__()
        self.api = api; self.user = user
        self.db_path = db_path; self.config_getter = config_getter
        self.products = []; self._build()

    def _role(self):
        return (self.user.get('user') or self.user).get('role', 'cashier')

    def _build(self):
        lay, _ = page_layout(self)  # 20/18 rhythm

        chrome, _ = PageChrome(
            'Inventory',
            'Products, stock levels, and category visuals.')
        lay.addWidget(chrome)

        # Toolbar: search + primary + secondary + ghost
        tb = QHBoxLayout(); tb.setSpacing(10)
        self._search = SearchBar('Search by name or SKU\u2026')
        self._search.textChanged.connect(self._filter)
        tb.addWidget(self._search, 1)

        if has_permission(self.user, 'inventory.create'):
            add = PrimaryBtn('+ Add Product', 40)
            add.clicked.connect(self._add)
            tb.addWidget(add)

        cats_btn = SecondaryBtn('Category Visuals', 40)
        cats_btn.setToolTip('Assign offline icons or images to product categories')
        cats_btn.clicked.connect(self._manage_categories)
        tb.addWidget(cats_btn)

        if self._role() == ROLE_SUPERADMIN:
            adj = SecondaryBtn('\u2699  Adjust Stock', 40)
            adj.clicked.connect(self._adjust_stock_dialog)
            tb.addWidget(adj)
            recv = SecondaryBtn('Receive Stock', 40)
            recv.setToolTip('Receive delivery from a supplier (increases stock)')
            recv.clicked.connect(self._receive_stock_dialog)
            tb.addWidget(recv)
            sups = SecondaryBtn('Suppliers', 40)
            sups.clicked.connect(self._suppliers_dialog)
            tb.addWidget(sups)

        exp = SecondaryBtn('Export Excel', 40)
        exp.setToolTip('Export inventory snapshot and stock movements to Excel')
        exp.clicked.connect(self._export_inventory)
        tb.addWidget(exp)

        ref = GhostBtn('\u21bb  Refresh', 40)
        ref.clicked.connect(self.refresh)
        tb.addWidget(ref)
        lay.addLayout(tb)

        # â”€â”€ Table in card â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        wrap = Card()
        wl = wrap.layout_v(margins=(0, 0, 0, 0), spacing=0)
        self._tbl = make_table(
            ['Name', 'SKU', 'Category', 'Price', 'Cost', 'Stock', 'Unit', 'Actions'],
            stretch_col=0, row_height=56)
        self._tbl.setAlternatingRowColors(False)  # zebra via BackgroundRole only
        hdr = self._tbl.horizontalHeader()
        # Wider fixed columns so Cost/Category/Unit aren't clipped to "KES â€¦"
        widths = {
            1: 100,   # SKU
            2: 160,   # Category
            3: 130,   # Price
            4: 130,   # Cost
            5: 80,    # Stock
            6: 90,    # Unit
            7: 230,   # Actions (History + Edit + Delete)
        }
        for col, w in widths.items():
            hdr.setSectionResizeMode(col, QHeaderView.Fixed)
            self._tbl.setColumnWidth(col, w)
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        hdr.setMinimumSectionSize(70)
        self._tbl.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self._tbl.setWordWrap(False)
        self._tbl.setTextElideMode(Qt.ElideRight)
        wl.addWidget(self._tbl)
        lay.addWidget(wrap, 1)
        self._stats = Caption('')
        self._stats.setObjectName('invStatsCaption')
        self._apply_stats_style()
        lay.addWidget(self._stats)

    def _apply_stats_style(self):
        self._stats.setStyleSheet(
            f"color:{C['text2']}; font-size:13px; font-weight:600; "
            f"background:transparent; padding:4px 2px;")

    def on_show(self): self.refresh()

    def apply_theme(self, is_light=None):
        """Retint chrome + table after ThemeManager.apply (no DB reload).

        SearchBar / mbtPageInner / PrimaryBtn bake inline QSS at build time —
        must refresh them here so Light never keeps a dark toolbar/footer strip
        around an already-light table.
        """
        try:
            from desktop.utils.widgets import refresh_themed_widgets
            refresh_themed_widgets(self)
            self._apply_stats_style()
            # Rebuild visible rows from cached products so accents + buttons use live C
            q = (self._search.text() or '').lower() if hasattr(self, '_search') else ''
            if q:
                prods = [p for p in (self.products or [])
                         if q in (p.get('name') or '').lower()
                         or q in (p.get('sku') or '').lower()
                         or q in (p.get('category') or '').lower()]
            else:
                prods = list(self.products or [])
            if prods:
                self._populate(prods)
            else:
                retint_table_items(self._tbl)
        except Exception as e:
            _log.warning('Inventory apply_theme: %s', e)

    def refresh(self):
        try:
            self.products = self.api.get_products() or []
        except Exception:
            self.products = []
        try:
            self._categories_by_name = self.api.categories_by_name_map()
        except Exception:
            self._categories_by_name = {}
        try:
            self._populate(self.products)
        except Exception as e:
            self.products = []
            self._tbl.setRowCount(0)
            self._stats.setText(f"  Could not load inventory: {e}")

    def _manage_categories(self):
        from desktop.dialogs.category_manager import CategoryManagerDialog
        dlg = CategoryManagerDialog(self.api, self)
        dlg.exec_()
        try:
            self._categories_by_name = self.api.categories_by_name_map()
        except Exception:
            pass
        self.refresh()

    def _export_inventory(self):
        """Export inventory snapshot + recent stock movements (shared formatter)."""
        try:
            from backend.report_export_service import export_inventory_full
            cfg = self.config_getter() or {}
            shop = cfg.get('shop_name', 'My Shop')
            cur = cfg.get('currency_symbol', 'KES') or 'KES'
            user = self.user.get('user') or self.user
            who = user.get('full_name') or user.get('username') or 'admin'
            products = self.products or self.api.get_products() or []
            moves = self.api.get_stock_movements(limit=5000) or []
            path = export_inventory_full(
                products, moves,
                shop_name=shop, currency=cur, generated_by=who,
            )
            QMessageBox.information(
                self, 'Exported',
                f'Inventory report saved:\n{path}\n\n'
                f'Sheets: Inventory · Stock Movements')
            try:
                import os
                os.startfile(path)
            except Exception:
                pass
        except Exception as e:
            _log.exception('Inventory export failed')
            QMessageBox.critical(self, 'Export Failed', str(e))

    def _filter(self):
        q = self._search.text().lower()
        try:
            self._populate([p for p in self.products
                            if q in p.get('name','').lower()
                            or q in (p.get('sku') or '').lower()
                            or q in (p.get('category') or '').lower()])
        except Exception as e:
            _log.exception('Inventory filter error')
            self._stats.setText(f"  Could not filter inventory: {e}")

    def _populate(self, prods):
        self._tbl.setRowCount(0)
        cfg  = self.config_getter() or {}
        cur  = cfg.get('currency_symbol', 'KES')
        low  = 0
        can_edit   = has_permission(self.user, 'inventory.edit_info')
        can_delete = has_permission(self.user, 'inventory.create')

        for i, p in enumerate(prods):
            try:
                self._populate_row(i, p, cur, can_edit, can_delete)
                stock = _safe_float(p.get('stock'), 0)
                mins = _safe_int(p.get('min_stock'), 5)
                if stock <= mins:
                    low += 1
            except Exception as e:
                _log.warning(f"Skipping product row {p.get('id')}: {e}")
                self._tbl.insertRow(i)
                self._tbl.setItem(i, 0, tbl_item(p.get('name', '?') or '?'))
                self._tbl.setItem(i, 5, tbl_center('\u2014', C['warn']))

        tot = sum(_safe_float(p.get('price')) * _safe_float(p.get('stock')) for p in prods)
        self._stats.setText(
            f"  {len(prods)} products  \u00b7  {low} low stock  \u00b7  "
            f"Stock value: {cur} {tot:,.2f}")
        # Final pass — guarantee every visible row has theme-matched zebra roles
        apply_table_row_backgrounds(self._tbl)

    def _populate_row(self, i, p, cur, can_edit, can_delete):
        self._tbl.insertRow(i)
        stock = _safe_float(p.get('stock'), 0)
        mins = _safe_int(p.get('min_stock'), 5)
        is_low = stock <= mins
        is_zero = stock <= 0

        name = p.get('name', '') or ''
        sku = p.get('sku', '') or ''
        cat = p.get('category', '') or ''
        unit = p.get('unit', 'pcs') or 'pcs'
        price_s = f"{cur} {_safe_float(p.get('price')):,.2f}"
        cost_s = f"{cur} {_safe_float(p.get('cost_price')):,.2f}"

        name_item = tbl_item(name, tone='text')
        name_item.setToolTip(name)
        self._tbl.setItem(i, 0, name_item)

        sku_item = tbl_item(sku, tone='text')
        sku_item.setToolTip(sku)
        self._tbl.setItem(i, 1, sku_item)

        cat_item = tbl_item(cat, tone='text')
        cat_item.setToolTip(cat)
        self._tbl.setItem(i, 2, cat_item)

        price_item = tbl_right(price_s, tone='gold')
        price_item.setToolTip(price_s)
        self._tbl.setItem(i, 3, price_item)

        cost_item = tbl_right(cost_s, tone='text')
        cost_item.setToolTip(cost_s)
        self._tbl.setItem(i, 4, cost_item)

        stk_tone = 'err' if is_zero else ('warn' if is_low else 'text2')
        stk_item  = tbl_center(_fmt_stock(stock), tone=stk_tone)
        if is_low:
            f = stk_item.font(); f.setBold(True); stk_item.setFont(f)
        self._tbl.setItem(i, 5, stk_item)

        unit_item = tbl_center(unit, tone='text2')
        unit_item.setToolTip(unit)
        self._tbl.setItem(i, 6, unit_item)

        row_bg = table_row_bg_hex(i)
        cell = QWidget()
        cell.setAutoFillBackground(True)
        cell.setStyleSheet(f'background: {row_bg}; border: none;')
        cl   = QHBoxLayout(cell)
        cl.setContentsMargins(8, 6, 8, 6)
        cl.setSpacing(6)

        # input/hover contrast on both even (card) and odd (card2) zebra rows
        btn_bg = C['input']
        if can_edit:
            eb = QPushButton('Edit')
            eb.setCursor(Qt.PointingHandCursor)
            eb.setFixedHeight(32)
            eb.setMinimumWidth(54)
            eb.setToolTip('Edit product')
            eb.setStyleSheet(
                f"QPushButton {{ background:{btn_bg}; color:{C['text']}; "
                f"border:1px solid {C['border2']}; border-radius:8px; "
                f"font-size:12px; font-weight:700; padding:4px 10px; }}"
                f"QPushButton:hover {{ color:{C['gold']}; border-color:{C['gold']}; "
                f"background:{C['hover']}; }}")
            eb.clicked.connect(lambda _, pid=p['id']: self._edit(pid))
            cl.addWidget(eb)

        # History is available to anyone who can see inventory
        hb = QPushButton('History')
        hb.setCursor(Qt.PointingHandCursor)
        hb.setFixedHeight(32)
        hb.setMinimumWidth(68)
        hb.setToolTip('Stock adjustments and sales since this product was added')
        hb.setStyleSheet(
            f"QPushButton {{ background:{btn_bg}; color:{C['text']}; "
            f"border:1px solid {C['border2']}; border-radius:8px; "
            f"font-size:12px; font-weight:700; padding:4px 10px; }}"
            f"QPushButton:hover {{ color:{C['gold']}; border-color:{C['gold']}; "
            f"background:{C['hover']}; }}")
        hb.clicked.connect(lambda _, pid=p['id']: self._show_history(pid))
        cl.addWidget(hb)

        if can_delete:
            db_b = QPushButton('Delete')
            db_b.setCursor(Qt.PointingHandCursor)
            db_b.setFixedHeight(32)
            db_b.setMinimumWidth(62)
            db_b.setToolTip('Delete product')
            db_b.setStyleSheet(
                f"QPushButton {{ background:{C['err']}; color:#FFFFFF; "
                f"border:none; border-radius:8px; "
                f"font-size:12px; font-weight:700; padding:4px 10px; }}"
                f"QPushButton:hover {{ background:{C['err']}; color:#FFFFFF; "
                f"border:1px solid {C['text']}; }}")
            db_b.clicked.connect(lambda _, pid=p['id']: self._delete(pid))
            cl.addWidget(db_b)

        if not can_edit and not can_delete:
            # History still shown above; only add View only if somehow no History
            pass

        cl.addStretch()
        self._tbl.setCellWidget(i, 7, cell)
        apply_table_row_backgrounds(self._tbl, row=i)
    def _receive_stock_dialog(self):
        if self._role() != ROLE_SUPERADMIN:
            QMessageBox.warning(self, 'Access Denied',
                'Only Super-Admin can receive stock.'); return
        from desktop.dialogs.receive_stock_dialog import ReceiveStockDialog
        dlg = ReceiveStockDialog(self.api, self, products=self.products)
        if dlg.exec_():
            self.refresh()

    def _suppliers_dialog(self):
        from desktop.dialogs.receive_stock_dialog import SuppliersDialog
        SuppliersDialog(self.api, self).exec_()

    def _adjust_stock_dialog(self):
        """Superadmin: adjust stock with PIN and reason. Never crashes the app."""
        if self._role() != ROLE_SUPERADMIN:
            QMessageBox.warning(self, 'Access Denied',
                'Only Super-Admin can adjust stock.'); return

        if not self.products:
            QMessageBox.information(self, 'No Products',
                'Add products first.'); return


        try:
            dlg = QDialog(self)
            dlg.setWindowTitle('Adjust Stock')
            dlg.setMinimumWidth(460)
            from desktop.utils.theme import apply_themed_dialog
            apply_themed_dialog(dlg)
            form = QFormLayout(dlg)
            form.setContentsMargins(24, 20, 24, 20)
            form.setSpacing(12)

            prod_sel = SearchableSelect(placeholder='Search product…')
            prod_sel.set_items([
                ("%s  (stock: %s)" % (pr['name'], _fmt_stock(pr.get('stock'))), pr['id'])
                for pr in self.products
            ])
            qty = QDoubleSpinBox()
            qty.setRange(0, 999999)
            qty.setDecimals(4)
            qty.setMinimumHeight(40)
            if self.products:
                qty.setValue(_safe_float(self.products[0].get('stock'), 0))

            def _on_prod(_=None):
                pid = prod_sel.current_value()
                prod = next((x for x in self.products if x['id'] == pid), None)
                if prod:
                    try:
                        from desktop.utils.auto_fill import AutoFillService
                        fields = AutoFillService.product_stock_fields(prod)
                        qty.setValue(float(fields.get('stock') or 0))
                        unit = fields.get('unit') or 'pcs'
                        cost = float(fields.get('cost_price') or 0)
                        qty.setToolTip(
                            f"Current stock: {fields.get('stock')} {unit}  ·  "
                            f"Cost: {cost:,.2f}  ·  (reason never auto-filled)")
                    except Exception:
                        qty.setValue(_safe_float(prod.get('stock'), 0))

            prod_sel.currentIndexChanged.connect(_on_prod)
            reason = ReasonSelect(reasons=STOCK_ADJUSTMENT_REASONS, height=40)
            form.addRow('Product', prod_sel)
            form.addRow('New quantity', qty)
            form.addRow('Reason', reason)
            buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            buttons.accepted.connect(dlg.accept)
            buttons.rejected.connect(dlg.reject)
            form.addRow(buttons)

            if dlg.exec_() != QDialog.Accepted:
                return
            pid = prod_sel.current_value()
            prod = next((x for x in self.products if x['id'] == pid), None)
            if not prod:
                QMessageBox.warning(self, 'Required', 'Select a product.')
                return
            if not reason.is_valid():
                QMessageBox.warning(self, 'Required', reason.validation_error())
                return
            new_qty = round(float(qty.value()), 4)

            if not ask_superadmin_pin(self.api, self,
                    reason="Adjust '%s' stock" % prod['name']):
                return

            res = self.api.adjust_stock(prod['id'], new_qty, reason.value())
            if res and res.get('success'):
                old_s = _safe_float(res.get('old_stock'))
                new_s = _safe_float(res.get('new_stock'))
                chg   = round(new_s - old_s, 4)
                try:
                    from desktop.utils.audio_manager import play as _audio_play
                    _audio_play('save')
                except Exception:
                    pass
                QMessageBox.information(self, 'Stock Adjusted',
                    "'%s'\n  Before: %s\n  After:  %s\n  Change: %+g" % (
                        prod['name'], _fmt_stock(old_s), _fmt_stock(new_s), chg))
                self.refresh()
            else:
                try:
                    from desktop.utils.audio_manager import play as _audio_play
                    _audio_play('error')
                except Exception:
                    pass
                QMessageBox.critical(self, 'Error',
                    (res or {}).get('error', 'Adjustment failed.'))
        except Exception as e:
            _log.exception('Adjust stock dialog error')
            QMessageBox.critical(
                self, 'Adjust Stock',
                'Could not complete stock adjustment:\n\n%s\n\n'
                'You can still add or edit products.' % e)

    def _add(self):
        if not require_permission(self.user, 'inventory.create', self):
            return
        try:
            dlg = _ProdDlg(self, role=self._role(), config_getter=self.config_getter)
            if dlg.exec_() != QDialog.Accepted:
                return
            res = self.api.create_product(dlg.data())
            if res and res.get('success'):
                self.refresh()
            else:
                QMessageBox.critical(
                    self, 'Could Not Add Product',
                    (res or {}).get('error', 'Failed to add product.'))
        except Exception as e:
            _log.exception('Add product UI error')
            QMessageBox.critical(
                self, 'Error',
                f'Could not add product:\n\n{e}')

    def _edit(self, pid):
        if not require_permission(self.user, 'inventory.edit_info', self):
            return
        p = next((x for x in self.products if x['id'] == pid), None)
        if not p:
            return
        try:
            dlg = _ProdDlg(self, p, role=self._role())
            if dlg.exec_() != QDialog.Accepted:
                return
            res = self.api.update_product(pid, dlg.data(), pin_verified=False)
            if res and res.get('success'):
                self.refresh()
            else:
                QMessageBox.critical(
                    self, 'Could Not Update Product',
                    (res or {}).get('error', 'Failed to update product.'))
        except Exception as e:
            _log.exception('Edit product UI error')
            QMessageBox.critical(
                self, 'Error',
                f'Could not update product:\n\n{e}')

    def _delete(self, pid):
        if not require_permission(self.user, 'inventory.create', self): return
        p = next((x for x in self.products if x['id'] == pid), None)
        name = p.get('name', '') if p else ''
        if QMessageBox.question(self, 'Confirm Delete',
                f"Delete '{name}'?\n\nThis cannot be undone.",
                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            if self.api.delete_product(pid):
                self.refresh()

    def _show_history(self, pid):
        p = next((x for x in self.products if x['id'] == pid), None)
        if not p:
            return
        try:
            dlg = _ProductHistoryDlg(self, self.api, pid, self.config_getter)
            dlg.exec_()
        except Exception as e:
            _log.exception('Product history dialog error')
            QMessageBox.critical(
                self, 'Product History',
                f'Could not open history:\n\n{e}')


# â”€â”€ Product Dialog â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class _ProdDlg(QDialog):
    def __init__(self, parent, prod=None, role='cashier', config_getter=None):
        super().__init__(parent)
        self.setWindowTitle('Add New Product' if not prod else 'Edit Product')
        self.setMinimumWidth(500)
        apply_themed_dialog(self)

        self._is_new = prod is None
        self._role   = role
        self._config_getter = config_getter

        lay = QFormLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(16)
        lay.setLabelAlignment(Qt.AlignRight)

        def lbl(text):
            l = QLabel(text)
            l.setStyleSheet(f"color:{C['text']}; font-size:14px; font-weight:600;")
            return l

        self.name  = QLineEdit(); self.name.setMinimumHeight(42); self.name.setPlaceholderText('Product name *')
        self.sku   = QLineEdit(); self.sku.setMinimumHeight(42);  self.sku.setPlaceholderText('e.g. UNG-2KG')
        self.cat   = QLineEdit(); self.cat.setMinimumHeight(42);  self.cat.setPlaceholderText('e.g. Flour, Dairy')
        self.cat.textChanged.connect(self._on_cat_preview)
        self.price = QDoubleSpinBox(); self.price.setRange(0, 9999999); self.price.setDecimals(2); self.price.setMinimumHeight(42)
        self.cost  = QDoubleSpinBox(); self.cost.setRange(0, 9999999);  self.cost.setDecimals(2); self.cost.setMinimumHeight(42)
        self.mins  = QSpinBox();       self.mins.setRange(0, 999999);   self.mins.setValue(5);    self.mins.setMinimumHeight(42)
        self.unit  = QLineEdit();      self.unit.setMinimumHeight(42);  self.unit.setText('pcs')
        self.status = Select(items=list(PRODUCT_STATUSES))
        self.status.setMinimumHeight(42)

        if prod:
            self.name.setText(prod.get('name') or '')
            self.sku.setText(prod.get('sku') or '')
            self.cat.setText(prod.get('category') or '')
            self.price.setValue(_safe_float(prod.get('price')))
            self.cost.setValue(_safe_float(prod.get('cost_price')))
            self.mins.setValue(_safe_int(prod.get('min_stock'), 5))
            self.unit.setText(prod.get('unit') or 'pcs')
            st = prod.get('product_status') or (
                'Active' if int(prod.get('is_active', 1) or 0) == 1 else 'Inactive')
            self.status.set_value(st)
        elif self._is_new:
            try:
                from desktop.utils.auto_fill import AutoFillService
                cfg = {}
                if callable(self._config_getter):
                    cfg = self._config_getter() or {}
                elif parent is not None and hasattr(parent, 'config_getter'):
                    cfg = parent.config_getter() or {}
                AutoFillService.apply_product_create_defaults(self, cfg)
                defaults = AutoFillService.product_create_defaults(cfg)
                if defaults.get('status') and hasattr(self, 'status'):
                    self.status.set_value(defaults['status'])
            except Exception:
                pass

        lay.addRow(lbl('Name *'),           self.name)
        lay.addRow(lbl('SKU / Code'),        self.sku)
        # Category + live visual preview (icon from offline library)
        cat_wrap = QWidget()
        cat_hl = QHBoxLayout(cat_wrap)
        cat_hl.setContentsMargins(0, 0, 0, 0)
        cat_hl.setSpacing(8)
        cat_hl.addWidget(self.cat, 1)
        try:
            from desktop.utils.category_visuals import CategoryVisual
            self._cat_vis = CategoryVisual(size=40, show_label=False)
            cat_hl.addWidget(self._cat_vis)
        except Exception:
            self._cat_vis = None
        lay.addRow(lbl('Category'),          cat_wrap)
        self._on_cat_preview(self.cat.text())
        lay.addRow(lbl('Selling Price'),     self.price)
        lay.addRow(lbl('Cost Price'),        self.cost)
        lay.addRow(lbl('Min Stock Alert'),   self.mins)
        lay.addRow(lbl('Unit'),              self.unit)
        lay.addRow(lbl('Status'),            self.status)

        # Stock field â€” only when adding a NEW product
        if self._is_new:
            self.stock = QDoubleSpinBox()
            self.stock.setRange(0, 999999)
            self.stock.setDecimals(4)
            self.stock.setMinimumHeight(42)
            lay.addRow(lbl('Opening Stock'), self.stock)
        else:
            stk_val  = _fmt_stock(prod.get('stock'))
            stk_info = QLabel(
                f"<b>{stk_val}</b>  "
                f"<span style='color:{C['muted']};font-size:12px;'>"
                f"(Use the Adjust Stock button to change stock quantity)</span>")
            stk_info.setTextFormat(Qt.RichText)
            stk_info.setStyleSheet(f"color:{C['text']}; font-size:14px; background:transparent;")
            lay.addRow(lbl('Current Stock'), stk_info)

        # Separator
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{C['border2']};")
        lay.addRow(sep)

        # Buttons (wrap layout in QWidget â€” raw QHBoxLayout in QFormLayout can crash on Windows)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        cancel = SecondaryBtn('Cancel', 44)
        cancel.clicked.connect(self.reject)
        save = PrimaryBtn('Save Product', 44)
        save.clicked.connect(self._val)
        btn_row.addWidget(cancel, 1)
        btn_row.addWidget(save, 1)
        btn_wrap = QWidget()
        btn_wrap.setLayout(btn_row)
        lay.addRow(btn_wrap)

        from desktop.utils.state_reset import StateResetManager
        if self._is_new:
            StateResetManager.clear_modal_on_close(
                self, wipe=lambda: StateResetManager.reset_product_form(self))
        else:
            StateResetManager.clear_modal_on_close(self)

    def _on_cat_preview(self, text=''):
        if not getattr(self, '_cat_vis', None):
            return
        name = (text or self.cat.text() or '').strip() or 'General'
        meta = {}
        try:
            parent = self.parent()
            cmap = getattr(parent, '_categories_by_name', None) or {}
            meta = cmap.get(name) or cmap.get(name.lower()) or {}
            if not meta and parent is not None and hasattr(parent, 'api'):
                meta = parent.api.get_category_by_name(name) or {}
        except Exception:
            meta = {}
        if meta:
            self._cat_vis.set_category(meta)
        else:
            from desktop.utils.category_visuals import suggest_visual_for_category_name
            sug = suggest_visual_for_category_name(name)
            self._cat_vis.set_visual(
                visual_type='icon',
                icon_name=sug.get('icon_name'),
                accent_color=sug.get('accent_color'),
                name=name,
            )

    def _val(self):
        if not self.name.text().strip():
            QMessageBox.warning(self, 'Required', 'Product name is required.')
            return
        self.accept()

    def data(self):
        status = self.status.current_label() or 'Active'
        d = {
            'name':       self.name.text().strip(),
            'sku':        self.sku.text().strip() or None,
            'category':   self.cat.text().strip() or None,
            'price':      self.price.value(),
            'cost_price': self.cost.value(),
            'min_stock':  self.mins.value(),
            'unit':       self.unit.text().strip() or 'pcs',
            'is_active':  1 if status == 'Active' else 0,
            'product_status': status,
        }
        if self._is_new:
            d['stock'] = self.stock.value()
        return d

# -- Product History Dialog -----------------------------------------------------

def _fmt_dt(v):
    """Show date/time from ISO-ish DB strings."""
    if not v:
        return '-'
    s = str(v).replace('T', ' ')
    return s[:19] if len(s) >= 19 else s


class _ProductHistoryDlg(QDialog):
    """Timeline for one product: profile, stock adjustments, and sales."""

    def __init__(self, parent, api, product_id, config_getter):
        super().__init__(parent)
        self.api = api
        self._pid = product_id
        self.config_getter = config_getter
        self.setWindowTitle('Product History')
        self.setMinimumSize(820, 560)
        self.resize(900, 620)
        apply_themed_dialog(self)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        self._hdr = H2('Product History')
        root.addWidget(self._hdr)
        self._meta = Caption('')
        self._meta.setWordWrap(True)
        root.addWidget(self._meta)

        tabs = QTabWidget()
        root.addWidget(tabs, 1)

        # Sales tab
        sales_w = QWidget()
        sw = QVBoxLayout(sales_w)
        sw.setContentsMargins(0, 8, 0, 0)
        self._sales_tbl = make_table(
            ['Date', 'Receipt', 'Qty', 'Price', 'Disc', 'Line Total', 'Cashier', 'Pay', 'Status'],
            stretch_col=1, row_height=40)
        for col, w in [(0, 140), (2, 60), (3, 80), (4, 70), (5, 90), (6, 100), (7, 80), (8, 70)]:
            self._sales_tbl.setColumnWidth(col, w)
        sw.addWidget(self._sales_tbl)
        self._sales_empty = Caption('No sales recorded for this product yet.')
        self._sales_empty.setVisible(False)
        sw.addWidget(self._sales_empty)
        tabs.addTab(sales_w, 'Sales')

        # Stock tab
        stock_w = QWidget()
        sk = QVBoxLayout(stock_w)
        sk.setContentsMargins(0, 8, 0, 0)
        self._stock_tbl = make_table(
            ['Date', 'Type', 'Before', 'Change', 'After', 'Reason / Ref', 'By'],
            stretch_col=5, row_height=40)
        for col, w in [(0, 140), (1, 90), (2, 70), (3, 70), (4, 70), (6, 100)]:
            self._stock_tbl.setColumnWidth(col, w)
        sk.addWidget(self._stock_tbl)
        self._stock_empty = Caption('No stock movements logged for this product yet.')
        self._stock_empty.setVisible(False)
        sk.addWidget(self._stock_empty)
        tabs.addTab(stock_w, 'Stock Adjustments')

        close_btn = PrimaryBtn('Close', 40)
        close_btn.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(close_btn)
        root.addLayout(row)

        self._load()

    def _currency(self):
        try:
            return (self.config_getter() or {}).get('currency_symbol', 'KES') or 'KES'
        except Exception:
            return 'KES'

    def _load(self):
        try:
            data = self.api.get_product_history(self._pid) or {}
        except Exception as e:
            QMessageBox.critical(self, 'Product History', str(e))
            return

        prod = data.get('product') or {}
        if not prod:
            self._meta.setText('Product not found.')
            return

        cur = self._currency()
        name = prod.get('name') or 'Product'
        self.setWindowTitle(f'History - {name}')
        self._hdr.setText(name)
        entered = _fmt_dt(prod.get('created_at'))
        sku = prod.get('sku') or '-'
        cat = prod.get('category') or '-'
        stock = _fmt_stock(prod.get('stock'))
        unit = prod.get('unit') or 'pcs'
        price = _safe_float(prod.get('price'))
        self._meta.setText(
            f"Entered inventory: {entered}  ·  SKU: {sku}  ·  Category: {cat}\n"
            f"Current stock: {stock} {unit}  ·  Price: {cur} {price:,.2f}"
        )

        sales = data.get('sales') or []
        self._sales_tbl.setRowCount(0)
        self._sales_empty.setVisible(not sales)
        for i, s in enumerate(sales):
            self._sales_tbl.insertRow(i)
            self._sales_tbl.setItem(i, 0, tbl_item(_fmt_dt(s.get('created_at'))))
            self._sales_tbl.setItem(i, 1, tbl_item(str(s.get('receipt_number') or '')))
            self._sales_tbl.setItem(i, 2, tbl_center(_fmt_stock(s.get('quantity'))))
            self._sales_tbl.setItem(i, 3, tbl_right(f"{_safe_float(s.get('unit_price')):,.2f}"))
            disc = _safe_float(s.get('discount'))
            self._sales_tbl.setItem(i, 4, tbl_right(f"{disc:,.2f}" if disc else '-'))
            self._sales_tbl.setItem(i, 5, tbl_right(f"{_safe_float(s.get('total')):,.2f}", C['gold']))
            self._sales_tbl.setItem(i, 6, tbl_item(str(s.get('cashier_name') or '')))
            self._sales_tbl.setItem(i, 7, tbl_center(str(s.get('payment_method') or '')))
            self._sales_tbl.setItem(i, 8, tbl_center(str(s.get('status') or 'ok')))

        moves = data.get('movements') or []
        self._stock_tbl.setRowCount(0)
        self._stock_empty.setVisible(not moves)
        _type_labels = {
            'INTERNAL_USE': 'Internal Use',
            'INTERNAL_USE_VOID': 'Use Void',
            'SALE': 'Sale',
            'VOID_RESTORE': 'Void Restore',
            'SUPERADMIN_ADJUST': 'Adjust',
            'MANUAL_ADJUST': 'Adjust',
            'PURCHASE': 'Purchase',
            'TRANSFER': 'Transfer',
            'ADJUSTMENT': 'Adjustment',
        }
        for i, m in enumerate(moves):
            self._stock_tbl.insertRow(i)
            self._stock_tbl.setItem(i, 0, tbl_item(_fmt_dt(m.get('created_at'))))
            mtype = str(m.get('movement_type') or '')
            label = _type_labels.get(mtype, mtype)
            self._stock_tbl.setItem(i, 1, tbl_center(label))
            self._stock_tbl.setItem(i, 2, tbl_center(_fmt_stock(m.get('qty_before'))))
            chg = _safe_float(m.get('qty_change'))
            chg_s = f"+{_fmt_stock(chg)}" if chg > 0 else _fmt_stock(chg)
            chg_color = C['ok'] if chg > 0 else (C['err'] if chg < 0 else C['text2'])
            self._stock_tbl.setItem(i, 3, tbl_center(chg_s, chg_color))
            self._stock_tbl.setItem(i, 4, tbl_center(_fmt_stock(m.get('qty_after'))))
            reason = (m.get('reason') or '') or (m.get('reference') or '')
            reason_item = tbl_item(str(reason))
            reason_item.setToolTip(str(reason))
            self._stock_tbl.setItem(i, 5, reason_item)
            self._stock_tbl.setItem(i, 6, tbl_item(str(m.get('username') or '-')))
