"""MBT POS - Inventory | MugoByte Technologies"""
import logging

from PyQt5.QtWidgets import *
from PyQt5.QtCore    import *
from PyQt5.QtGui     import *

_log = logging.getLogger('inventory')
from desktop.utils.theme   import C, qss_alpha
from desktop.utils.widgets import (Card, H2, Caption, PrimaryBtn, SecondaryBtn,
                                    DangerBtn, GhostBtn, SearchBar, make_table, tbl_item,
                                    tbl_right, tbl_center, page_layout, retint_table_items,
                                    apply_table_row_backgrounds, table_row_bg_hex)
from desktop.utils.security import (has_permission, require_permission,
                                     ask_superadmin_pin, ROLE_SUPERADMIN)


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
        lay, _ = page_layout(self, margins=(24, 24, 24, 24), spacing=16)

        # â”€â”€ Toolbar (Lovable: search + primary + secondary + ghost) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        tb = QHBoxLayout(); tb.setSpacing(8)
        self._search = SearchBar('Search by name or SKU\u2026')
        self._search.textChanged.connect(self._filter)
        tb.addWidget(self._search, 1)

        if has_permission(self.user, 'inventory.create'):
            add = PrimaryBtn('+ Add Product', 40)
            add.clicked.connect(self._add)
            tb.addWidget(add)

        if self._role() == ROLE_SUPERADMIN:
            adj = SecondaryBtn('\u2699  Adjust Stock', 40)
            adj.clicked.connect(self._adjust_stock_dialog)
            tb.addWidget(adj)

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
            self._populate(self.products)
        except Exception as e:
            self.products = []
            self._tbl.setRowCount(0)
            self._stats.setText(f"  Could not load inventory: {e}")

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
    def _adjust_stock_dialog(self):
        """Superadmin: adjust stock with PIN and reason. Never crashes the app."""
        if self._role() != ROLE_SUPERADMIN:
            QMessageBox.warning(self, 'Access Denied',
                'Only Super-Admin can adjust stock.'); return

        if not self.products:
            QMessageBox.information(self, 'No Products',
                'Add products first.'); return

        try:
            names = [f"{p['name']}  (current stock: {_fmt_stock(p.get('stock'))})"
                     for p in self.products]
            name, ok = QInputDialog.getItem(
                self, 'Adjust Stock', 'Select product:', names, 0, False)
            if not ok:
                return
            prod = self.products[names.index(name)]

            cur_stock = _safe_float(prod.get('stock'), 0)
            new_qty, ok = QInputDialog.getDouble(
                self, 'New Stock Quantity',
                f"New quantity for '{prod['name']}':\n"
                f"Current stock: {_fmt_stock(cur_stock)}",
                cur_stock, 0, 999999, 4)
            if not ok:
                return
            new_qty = round(float(new_qty), 4)

            reason, ok = QInputDialog.getText(
                self, 'Reason Required',
                'Reason for stock adjustment (required â€” this is logged):')
            if not ok or not reason.strip():
                QMessageBox.warning(self, 'Required',
                    'A reason is required for all stock adjustments.')
                return

            if not ask_superadmin_pin(self.api, self,
                    reason=f"Adjust '{prod['name']}' stock"):
                return

            res = self.api.adjust_stock(prod['id'], new_qty, reason.strip())
            if res and res.get('success'):
                old_s = _safe_float(res.get('old_stock'))
                new_s = _safe_float(res.get('new_stock'))
                chg   = round(new_s - old_s, 4)
                QMessageBox.information(self, 'Stock Adjusted âœ“',
                    f"'{prod['name']}'\n"
                    f"  Before: {_fmt_stock(old_s)}\n"
                    f"  After:  {_fmt_stock(new_s)}\n"
                    f"  Change: {chg:+g}")
                self.refresh()
            else:
                QMessageBox.critical(self, 'Error',
                    (res or {}).get('error', 'Adjustment failed.'))
        except Exception as e:
            _log.exception('Adjust stock dialog error')
            QMessageBox.critical(
                self, 'Adjust Stock',
                f'Could not complete stock adjustment:\n\n{e}\n\n'
                f'You can still add or edit products.')

    def _add(self):
        if not require_permission(self.user, 'inventory.create', self):
            return
        try:
            dlg = _ProdDlg(self, role=self._role())
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
    def __init__(self, parent, prod=None, role='cashier'):
        super().__init__(parent)
        self.setWindowTitle('Add New Product' if not prod else 'Edit Product')
        self.setMinimumWidth(500)
        from desktop.utils.theme import MBT_STYLESHEET
        self.setStyleSheet(MBT_STYLESHEET)

        self._is_new = prod is None
        self._role   = role

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
        self.price = QDoubleSpinBox(); self.price.setRange(0, 9999999); self.price.setDecimals(2); self.price.setMinimumHeight(42)
        self.cost  = QDoubleSpinBox(); self.cost.setRange(0, 9999999);  self.cost.setDecimals(2); self.cost.setMinimumHeight(42)
        self.mins  = QSpinBox();       self.mins.setRange(0, 999999);   self.mins.setValue(5);    self.mins.setMinimumHeight(42)
        self.unit  = QLineEdit();      self.unit.setMinimumHeight(42);  self.unit.setText('pcs')

        if prod:
            self.name.setText(prod.get('name') or '')
            self.sku.setText(prod.get('sku') or '')
            self.cat.setText(prod.get('category') or '')
            self.price.setValue(_safe_float(prod.get('price')))
            self.cost.setValue(_safe_float(prod.get('cost_price')))
            self.mins.setValue(_safe_int(prod.get('min_stock'), 5))
            self.unit.setText(prod.get('unit') or 'pcs')

        lay.addRow(lbl('Name *'),           self.name)
        lay.addRow(lbl('SKU / Code'),        self.sku)
        lay.addRow(lbl('Category'),          self.cat)
        lay.addRow(lbl('Selling Price'),     self.price)
        lay.addRow(lbl('Cost Price'),        self.cost)
        lay.addRow(lbl('Min Stock Alert'),   self.mins)
        lay.addRow(lbl('Unit'),              self.unit)

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
                f"(Use the âš- Adjust Stock button to change stock quantity)</span>")
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

    def _val(self):
        if not self.name.text().strip():
            QMessageBox.warning(self, 'Required', 'Product name is required.')
            return
        self.accept()

    def data(self):
        d = {
            'name':       self.name.text().strip(),
            'sku':        self.sku.text().strip() or None,
            'category':   self.cat.text().strip() or None,
            'price':      self.price.value(),
            'cost_price': self.cost.value(),
            'min_stock':  self.mins.value(),
            'unit':       self.unit.text().strip() or 'pcs',
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
        from desktop.utils.theme import MBT_STYLESHEET
        self.setStyleSheet(MBT_STYLESHEET)

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
        for i, m in enumerate(moves):
            self._stock_tbl.insertRow(i)
            self._stock_tbl.setItem(i, 0, tbl_item(_fmt_dt(m.get('created_at'))))
            mtype = str(m.get('movement_type') or '')
            self._stock_tbl.setItem(i, 1, tbl_center(mtype))
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
