"""MBT POS - Inventory | MugoByte Technologies"""
import logging

from PyQt5.QtWidgets import *
from PyQt5.QtCore    import *
from PyQt5.QtGui     import *

_log = logging.getLogger('inventory')
from desktop.utils.theme   import C, qss_alpha
from desktop.utils.widgets import (Card, H2, Caption, PrimaryBtn, SecondaryBtn,
                                    DangerBtn, GhostBtn, SearchBar, make_table, tbl_item,
                                    tbl_right, tbl_center, page_layout, IconBtn)
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
    """Display stock — show decimals when needed (e.g. 89.75 after quarter sales)."""
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

        # ── Toolbar (Lovable: search + primary + secondary + ghost) ───────────
        tb = QHBoxLayout(); tb.setSpacing(8)
        self._search = SearchBar('Search by name or SKU…')
        self._search.textChanged.connect(self._filter)
        tb.addWidget(self._search, 1)

        if has_permission(self.user, 'inventory.create'):
            add = PrimaryBtn('+ Add Product', 40)
            add.clicked.connect(self._add)
            tb.addWidget(add)

        if self._role() == ROLE_SUPERADMIN:
            adj = SecondaryBtn('⚖  Adjust Stock', 40)
            adj.clicked.connect(self._adjust_stock_dialog)
            tb.addWidget(adj)

        ref = GhostBtn('↺  Refresh', 40)
        ref.clicked.connect(self.refresh)
        tb.addWidget(ref)
        lay.addLayout(tb)

        # ── Table in card ─────────────────────────────────────────────────────
        wrap = Card()
        wl = wrap.layout_v(margins=(0, 0, 0, 0), spacing=0)
        self._tbl = make_table(
            ['Name', 'SKU', 'Category', 'Price', 'Cost', 'Stock', 'Unit', 'Actions'],
            stretch_col=0, row_height=52)
        for col, w in [(1,90),(2,120),(3,110),(4,100),(5,80),(6,70),(7,120)]:
            self._tbl.horizontalHeader().setSectionResizeMode(col, QHeaderView.Fixed)
            self._tbl.setColumnWidth(col, w)
        wl.addWidget(self._tbl)
        lay.addWidget(wrap, 1)
        self._stats = Caption('')
        lay.addWidget(self._stats)

    def on_show(self): self.refresh()

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
                self._tbl.setItem(i, 5, tbl_center('—', C['warn']))

        tot = sum(_safe_float(p.get('price')) * _safe_float(p.get('stock')) for p in prods)
        self._stats.setText(
            f"  {len(prods)} products  ·  {low} low stock  ·  "
            f"Stock value: {cur} {tot:,.2f}")

    def _populate_row(self, i, p, cur, can_edit, can_delete):
        self._tbl.insertRow(i)
        stock = _safe_float(p.get('stock'), 0)
        mins = _safe_int(p.get('min_stock'), 5)
        is_low = stock <= mins
        is_zero = stock <= 0

        self._tbl.setItem(i, 0, tbl_item(p.get('name', '') or ''))
        self._tbl.setItem(i, 1, tbl_item(p.get('sku', '') or ''))
        self._tbl.setItem(i, 2, tbl_item(p.get('category', '') or ''))
        self._tbl.setItem(i, 3, tbl_right(f"{cur} {_safe_float(p.get('price')):,.2f}", C['gold']))
        self._tbl.setItem(i, 4, tbl_right(f"{cur} {_safe_float(p.get('cost_price')):,.2f}"))

        stk_color = C['err'] if is_zero else (C['warn'] if is_low else C['text2'])
        stk_item  = tbl_center(_fmt_stock(stock), stk_color)
        if is_low:
            f = stk_item.font(); f.setBold(True); stk_item.setFont(f)
        self._tbl.setItem(i, 5, stk_item)
        self._tbl.setItem(i, 6, tbl_center(p.get('unit', 'pcs')))

        cell = QWidget()
        cell.setStyleSheet('background: transparent;')
        cl   = QHBoxLayout(cell)
        cl.setContentsMargins(6, 4, 6, 4)
        cl.setSpacing(4)

        if can_edit:
            eb = IconBtn('✏', 28, 28)
            eb.setToolTip('Edit')
            eb.clicked.connect(lambda _, pid=p['id']: self._edit(pid))
            cl.addWidget(eb)

        if can_delete:
            db_b = IconBtn('🗑', 28, 28)
            db_b.setToolTip('Delete')
            db_b.setStyleSheet(
                f"QPushButton {{ background:{C['card2']}; color:{C['text2']}; "
                f"border:1px solid {C['border']}; border-radius:8px; font-size:12px; }}"
                f"QPushButton:hover {{ color:{C['err']}; border-color:{qss_alpha(C['err'], 0.40)}; "
                f"background:{qss_alpha(C['err'], 0.10)}; }}")
            db_b.clicked.connect(lambda _, pid=p['id']: self._delete(pid))
            cl.addWidget(db_b)

        if not can_edit and not can_delete:
            lbl = QLabel('View only')
            lbl.setStyleSheet(f"color:{C['muted']}; font-size:12px;")
            cl.addWidget(lbl)

        cl.addStretch()
        self._tbl.setCellWidget(i, 7, cell)

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
                'Reason for stock adjustment (required — this is logged):')
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
                QMessageBox.information(self, 'Stock Adjusted ✓',
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


# ── Product Dialog ─────────────────────────────────────────────────────────────

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

        # Stock field — only when adding a NEW product
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
                f"(Use the ⚖ Adjust Stock button to change stock quantity)</span>")
            stk_info.setTextFormat(Qt.RichText)
            stk_info.setStyleSheet(f"color:{C['text']}; font-size:14px; background:transparent;")
            lay.addRow(lbl('Current Stock'), stk_info)

        # Separator
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{C['border2']};")
        lay.addRow(sep)

        # Buttons (wrap layout in QWidget — raw QHBoxLayout in QFormLayout can crash on Windows)
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
