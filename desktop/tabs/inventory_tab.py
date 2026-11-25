"""MBT POS - Inventory | MugoByte Technologies"""
import logging
import os

from PyQt5.QtWidgets import *
from PyQt5.QtCore    import *
from PyQt5.QtGui     import *

_log = logging.getLogger('inventory')
from desktop.utils.theme   import C, qss_alpha, apply_themed_dialog
from desktop.utils.widgets import (Card, H2, Caption, PrimaryBtn, SecondaryBtn,
                                    DangerBtn, GhostBtn, SearchBar, make_table, tbl_item,
                                    tbl_right, tbl_center, page_layout, PageChrome,
                                    retint_table_items,
                                    apply_table_row_backgrounds, table_row_bg_hex,
                                    align_header_right)
from desktop.utils.security import (has_permission, require_permission,
                                     ask_superadmin_pin, collect_superadmin_pin,
                                     ROLE_SUPERADMIN)
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


def _issue_since_label(raw):
    """Show a full minute, not an elided year-month stub."""
    text = str(raw or '').strip().replace('T', ' ')
    if len(text) >= 16 and text[4:5] == '-' and text[7:8] == '-':
        return text[:16]
    return text


def _fmt_stock(v, unit=None):
    """Display stock to the stored precision, without trailing zeros."""
    text = f"{_safe_float(v, 0):.4f}".rstrip('0').rstrip('.')
    return text or '0'


def _stock_item(label, tone, tooltip=''):
    """Stock cell drawn as text so a refresh does not build a widget per row."""
    tone_key = {'err': 'err', 'warn': 'warn', 'ok': 'ok'}.get(tone, 'text')
    item = tbl_right(label, tone=tone_key)
    if tooltip:
        item.setToolTip(tooltip)
    if tone == 'err':
        item.setData(Qt.UserRole + 40, 'out_of_stock')
    return item


class _ElideLabel(QLabel):
    """Single-line label. The full text stays in the tooltip.

    ``cap`` limits how much width a warning badge may claim so the product
    name keeps the cell. A cap of 0 means the label prefers its own text.
    """

    def __init__(self, text, parent=None, cap=0):
        super().__init__(parent)
        self._full = text or ''
        self._cap = int(cap or 0)
        self.setToolTip(self._full)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.setText(self._full)

    def _height(self):
        return max(18, self.fontMetrics().height())

    def _text_width(self):
        return self.fontMetrics().horizontalAdvance(self._full) + 4

    def minimumSizeHint(self):
        if self._cap:
            return QSize(min(56, self._text_width()), self._height())
        return QSize(min(96, self._text_width()), self._height())

    def sizeHint(self):
        width = self._text_width()
        if self._cap:
            width = min(width, self._cap)
        return QSize(width, self._height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        width = max(0, self.contentsRect().width())
        elided = self.fontMetrics().elidedText(self._full, Qt.ElideRight, width)
        if self.text() != elided:
            self.setText(elided)


class _FlowLayout(QLayout):
    """Wrap toolbar buttons so they cannot force the inventory page wider than the window."""

    def __init__(self, parent=None, spacing=10):
        super().__init__(parent)
        self._items = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect, test_only):
        x = rect.x()
        y = rect.y()
        line_height = 0
        spacing = self.spacing()
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + spacing
            if next_x - spacing > rect.right() and line_height > 0:
                x = rect.x()
                y = y + line_height + spacing
                next_x = x + hint.width() + spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y()


# Floors stay readable. Caps stop one long SKU or category from pushing Actions off-screen.
_COL_FLOOR = {0: 168, 1: 96, 2: 112, 3: 156, 4: 156, 5: 76, 6: 64, 7: 204}
_COL_CAP = {1: 168, 2: 188, 3: 220, 4: 220, 5: 120, 6: 96, 7: 220}


class InventoryTab(QWidget):
    def __init__(self, api, user, db_path, config_getter):
        super().__init__()
        self.api = api; self.user = user
        self.db_path = db_path; self.config_getter = config_getter
        self._adjust_stock_active = False
        self.products = []; self._build()

    def _role(self):
        return (self.user.get('user') or self.user).get('role', 'cashier')

    def _build(self):
        lay, self._page_scroll = page_layout(self)  # 20/18 rhythm
        page = self._page_scroll.widget()
        if page is not None:
            page.setMinimumWidth(0)

        chrome, _ = PageChrome(
            'Inventory',
            'Products, stock levels, and category visuals.')
        lay.addWidget(chrome)

        # Toolbar: search + primary + secondary + ghost
        tb = QHBoxLayout(); tb.setSpacing(10)
        self._search = SearchBar('Search name, SKU, or barcode\u2026')
        self._search.setAccessibleName('Search products')
        self._search.textChanged.connect(self._filter)
        tb.addWidget(self._search, 1)
        self._cost_filter = QComboBox()
        self._cost_filter.setMinimumHeight(40)
        self._cost_filter.setMinimumWidth(220)
        for label, code in (
            ('All costing', ''),
            ('Missing buying price', 'missing_price'),
            ('Zero or invalid cost', 'zero_or_invalid'),
            ('Missing FIFO layer', 'missing_fifo'),
            ('Stock without cost', 'stock_without_cost'),
            ('Costing needs review', 'inconsistent'),
            ('Costing complete', 'complete'),
        ):
            self._cost_filter.addItem(label, code)
        self._cost_filter.currentIndexChanged.connect(self._filter)
        tb.addWidget(self._cost_filter)
        lay.addLayout(tb)

        filt = QHBoxLayout()
        filt.setSpacing(10)
        self._status_filter = QComboBox()
        self._status_filter.setMinimumHeight(40)
        self._status_filter.setAccessibleName('Product status')
        for label, code in (
            ('All products', 'all'),
            ('In stock', 'in'),
            ('Low stock', 'low'),
            ('Out of stock', 'out'),
        ):
            self._status_filter.addItem(label, code)
        self._status_filter.currentIndexChanged.connect(self._filter)
        filt.addWidget(self._status_filter)

        self._category_filter = QComboBox()
        self._category_filter.setMinimumHeight(40)
        self._category_filter.setMinimumWidth(180)
        self._category_filter.setAccessibleName('Product category')
        self._category_filter.addItem('All categories', 'all')
        self._category_filter.addItem('Uncategorised', '__uncategorised__')
        self._category_filter.currentIndexChanged.connect(self._filter)
        filt.addWidget(self._category_filter, 1)

        self._sort_filter = QComboBox()
        self._sort_filter.setMinimumHeight(40)
        self._sort_filter.setAccessibleName('Sort products')
        for label, code in (
            ('Name A\u2013Z', 'name_asc'),
            ('Name Z\u2013A', 'name_desc'),
            ('Lowest stock first', 'stock_asc'),
            ('Highest stock first', 'stock_desc'),
            ('Recently added', 'created'),
            ('Recently updated', 'updated'),
        ):
            self._sort_filter.addItem(label, code)
        self._sort_filter.currentIndexChanged.connect(self._filter)
        filt.addWidget(self._sort_filter)

        self._shown = Caption('0 products')
        self._shown.setAccessibleName('Matching products')
        filt.addWidget(self._shown)
        clear = GhostBtn('Clear filters', 40)
        clear.setAccessibleName('Clear filters')
        clear.setToolTip('Show every product, sorted by name')
        clear.clicked.connect(self._clear_filters)
        filt.addWidget(clear)
        lay.addLayout(filt)

        # Buttons wrap onto extra rows. A single non-wrapping bar was wider than
        # the till and pushed the product table, including Actions, past the window.
        tools = _FlowLayout(spacing=10)
        self._tool_flow = tools

        if has_permission(self.user, 'inventory.create'):
            add = PrimaryBtn('+ Add Product', 40)
            add.clicked.connect(self._add)
            tools.addWidget(add)

        if has_permission(self.user, 'categories.manage'):
            cats_btn = SecondaryBtn('Shop categories', 40)
            cats_btn.setToolTip('Add, rename, or remove categories for this shop')
            cats_btn.clicked.connect(self._manage_categories)
            tools.addWidget(cats_btn)

        if has_permission(self.user, 'inventory.receive'):
            recv = SecondaryBtn('Receive Stock', 40)
            recv.setToolTip('Receive a supplier delivery. No extra PIN.')
            recv.clicked.connect(self._receive_stock_dialog)
            tools.addWidget(recv)
        if has_permission(self.user, 'inventory.view'):
            from desktop.dialogs.restock_dialog import can_open_restock
            if can_open_restock(self.user):
                restock_btn = SecondaryBtn('Restock Lists', 40)
                restock_btn.setToolTip('Lists of products to buy. This does not change stock or the open sale.')
                restock_btn.clicked.connect(self._open_restock)
                tools.addWidget(restock_btn)
            issues_btn = SecondaryBtn('Issues', 40)
            issues_btn.setToolTip('Business issues for stock and products. A sale is not blocked.')
            issues_btn.clicked.connect(self._open_issues)
            batches_btn = SecondaryBtn('Batches', 40)
            batches_btn.setToolTip('Every delivery batch, including finished batches')
            batches_btn.clicked.connect(self._open_batches)
            tools.addWidget(batches_btn)
            tools.addWidget(issues_btn)
            count_btn = SecondaryBtn('Stocktake', 40)
            count_btn.setToolTip('Count stock. Applying the count is Super-Admin only.')
            count_btn.clicked.connect(self._open_stocktake)
            tools.addWidget(count_btn)

        if has_permission(self.user, 'inventory.receive') and self._role() != ROLE_SUPERADMIN:
            ask = SecondaryBtn('Request Adjustment', 40)
            ask.setToolTip('Ask a Super-Admin to change stock. This does not change stock.')
            ask.clicked.connect(self._request_adjustment_dialog)
            tools.addWidget(ask)
        if self._role() == ROLE_SUPERADMIN:
            adj = SecondaryBtn('Adjust Stock', 40)
            try:
                from desktop.utils.nav_icons import apply_button_icon
                apply_button_icon(adj, 'gear', 15)
            except Exception:
                pass
            adj.clicked.connect(self._adjust_stock_dialog)
            tools.addWidget(adj)
            pending = SecondaryBtn('Adjustment Requests', 40)
            pending.setToolTip('Approve or reject cashier stock-adjustment requests')
            pending.clicked.connect(self._review_adjustment_requests)
            tools.addWidget(pending)
            sups = SecondaryBtn('Suppliers', 40)
            sups.clicked.connect(self._suppliers_dialog)
            tools.addWidget(sups)

        exp = SecondaryBtn('Export Excel', 40)
        exp.setToolTip('Export inventory snapshot and stock movements to Excel')
        exp.clicked.connect(self._export_inventory)
        tools.addWidget(exp)

        ref = GhostBtn('Refresh', 40)
        try:
            from desktop.utils.nav_icons import apply_button_icon
            apply_button_icon(ref, 'refresh', 15)
        except Exception:
            pass
        ref.clicked.connect(self.refresh)
        tools.addWidget(ref)
        tool_host = QWidget()
        tool_host.setLayout(tools)
        tool_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        lay.addWidget(tool_host)

        # â”€â”€ Table in card â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        wrap = Card()
        wl = wrap.layout_v(margins=(0, 0, 0, 0), spacing=0)
        self._tbl = make_table(
            ['Name', 'SKU', 'Category', 'Price', 'Cost', 'Stock', 'Unit', 'Actions'],
            stretch_col=0, row_height=56)
        self._tbl.cellClicked.connect(self._on_cell_clicked)
        self._tbl.setAlternatingRowColors(False)  # zebra via BackgroundRole only
        hdr = self._tbl.horizontalHeader()
        hdr.setSectionsClickable(True)
        hdr.setHighlightSections(False)
        hdr.setFixedHeight(40)
        hdr.setStyleSheet(
            f"QHeaderView::section {{ background:{C['card2']}; color:{C['text2']}; "
            f"font-size:11px; font-weight:700; letter-spacing:0.6px; "
            f"padding:10px 12px; border:none; border-bottom:2px solid {C['border2']}; }}")
        # Category shows retail category (not supplier tags); tooltips carry source.
        # Widths are applied in _fit_columns so Actions stays inside a 1920 till
        # and the horizontal bar only appears when the window is too narrow.
        hdr.setMinimumSectionSize(56)
        if not has_permission(self.user, 'inventory.view_cost'):
            self._tbl.setColumnHidden(4, True)
        hdr.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        actions_head = self._tbl.horizontalHeaderItem(7)
        if actions_head is not None:
            actions_head.setTextAlignment(Qt.AlignCenter)
        align_header_right(self._tbl, 3, 4, 5)
        self._tbl.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self._tbl.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._tbl.setWordWrap(False)
        self._tbl.setTextElideMode(Qt.ElideRight)
        self._tbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self._tbl.setMinimumWidth(0)
        # Keep Actions header fully painted (avoid right-edge clip into scrollbar)
        self._tbl.horizontalHeader().setStretchLastSection(False)
        self._tbl.setStyleSheet(
            "QScrollBar:horizontal{height:14px;background:#142033;margin:0;}"
            f"QScrollBar::handle:horizontal{{background:{C['gold']};"
            "min-width:72px;border-radius:5px;}"
            "QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal{width:0;height:0;}"
            "QScrollBar::add-page:horizontal,QScrollBar::sub-page:horizontal{background:#142033;}"
        )
        wl.addWidget(self._tbl)
        lay.addWidget(wrap, 1)
        # Sticky-style footer card — clear gap so last table row never looks overlapped
        self._stats_footer = QFrame()
        self._stats_footer.setObjectName('invStatsFooter')
        fl = QHBoxLayout(self._stats_footer)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(0)
        self._stats = Caption('')
        self._stats.setObjectName('invStatsCaption')
        fl.addWidget(self._stats)
        self._apply_stats_style()
        lay.addSpacing(10)
        lay.addWidget(self._stats_footer)
        lay.addSpacing(10)

    def _apply_stats_style(self):
        self._stats_footer.setStyleSheet(
            f"QFrame#invStatsFooter {{ background:transparent; border:none; "
            f"margin:0; padding:0; }}")
        self._stats.setStyleSheet(
            f"QLabel#invStatsCaption {{ color:{C['text2']}; font-size:13px; font-weight:600; "
            f"background:{C['card']}; border:1px solid {C['border']}; border-radius:10px; "
            f"padding:12px 16px; min-height:22px; }}")

    def on_show(self): self.refresh()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._fit_columns)

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
            if self.products:
                self._filter()
            else:
                retint_table_items(self._tbl)
        except Exception as e:
            _log.warning('Inventory apply_theme: %s', e)

    def refresh(self):
        try:
            self.products = self.api.get_products() or []
        except Exception as e:
            self._stats.setText(f"  Inventory is busy. Showing the last list. ({e})")
            return
        try:
            self._categories_by_name = self.api.categories_by_name_map()
        except Exception:
            self._categories_by_name = {}
        try:
            self._reload_category_choices()
            self._filter()
        except Exception as e:
            self.products = []
            self._tbl.setRowCount(0)
            self._stats.setText(f"  Could not load inventory: {e}")
        self._fit_columns()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._fit_columns)

    def _lock_page_width(self):
        """Keep the inventory page inside the window.

        A wide size hint used to stretch the page past the till. The window then
        clipped Actions, and the page scrollbar is intentionally off, so the row
        buttons could not be reached. The table's own bar is what scrolls them.
        """
        scroll = getattr(self, '_page_scroll', None)
        if scroll is None or scroll.viewport() is None:
            return 0
        inner = scroll.widget()
        visible = scroll.viewport().width()
        if inner is None or visible < 80:
            return 0
        inner.setMinimumWidth(0)
        if inner.maximumWidth() != visible:
            inner.setMaximumWidth(visible)
        if inner.width() != visible:
            inner.resize(visible, max(inner.height(), scroll.viewport().height()))
        return visible

    def _visible_width(self):
        """Width the cashier can actually see, not the table's inflated size hint."""
        table = self._tbl
        width = table.viewport().width()
        scroll = getattr(self, '_page_scroll', None)
        if scroll is not None and scroll.viewport() is not None:
            page = scroll.viewport().width() - 40
            if page > 80 and (width < 80 or width > page + 24):
                width = page
        return width

    def _column_pref(self, col):
        floor = _COL_FLOOR[col]
        cap = _COL_CAP.get(col, floor)
        if col == 0:
            return floor
        if col == 7:
            width = floor
            for row in range(min(self._tbl.rowCount(), 40)):
                widget = self._tbl.cellWidget(row, 7)
                if widget is not None:
                    width = max(width, widget.sizeHint().width() + 12)
            return min(cap, max(floor, width))
        fm = self._tbl.fontMetrics()
        width = floor
        header = self._tbl.horizontalHeaderItem(col)
        if header is not None:
            width = max(width, fm.horizontalAdvance(header.text()) + 36)
        for row in range(self._tbl.rowCount()):
            item = self._tbl.item(row, col)
            if item is None:
                continue
            width = max(width, fm.horizontalAdvance(item.text()) + 36)
            if width >= cap:
                return cap
        return min(cap, width)

    def _fit_columns(self):
        """Put Name, price, stock, SKU and the row buttons in the visible window.

        A narrow window keeps the horizontal scrollbar so the buttons can still
        be reached. Names ellipsize; the cell tooltip keeps the full name.
        """
        table = getattr(self, '_tbl', None)
        if table is None or table.columnCount() < 8 or getattr(self, '_fitting', False):
            return
        visible_page = self._lock_page_width()
        viewport = self._visible_width()
        if visible_page and abs(table.viewport().width() - (visible_page - 40)) > 48:
            tries = getattr(self, '_fit_tries', 0)
            if tries < 4:
                self._fit_tries = tries + 1
                QTimer.singleShot(0, self._fit_columns)
                return
        self._fit_tries = 0
        if viewport < 240:
            return
        cols = [col for col in range(table.columnCount()) if not table.isColumnHidden(col)]
        if 0 not in cols or 7 not in cols:
            return
        floors = {col: _COL_FLOOR[col] for col in cols}
        prefs = {col: max(floors[col], self._column_pref(col)) for col in cols}
        prefs[0] = floors[0]
        floor_sum = sum(floors.values())
        pref_sum = sum(prefs.values())
        if viewport >= pref_sum:
            widths = dict(prefs)
            widths[0] = floors[0] + (viewport - pref_sum)
        elif viewport >= floor_sum:
            extra = viewport - floor_sum
            grow = [col for col in cols if col != 0 and prefs[col] > floors[col]]
            room = sum(prefs[col] - floors[col] for col in grow)
            widths = dict(floors)
            given = 0
            if room:
                for col in grow:
                    share = int(extra * (prefs[col] - floors[col]) / room)
                    widths[col] = floors[col] + share
                    given += share
            widths[0] = floors[0] + (extra - given)
        else:
            widths = dict(floors)
        planned = {col: int(widths[col]) for col in cols}
        if (
            all(table.columnWidth(col) == planned[col] for col in cols)
            and table.horizontalScrollBarPolicy() == Qt.ScrollBarAsNeeded
        ):
            if sum(planned.values()) <= viewport + 4:
                table.horizontalScrollBar().setValue(0)
            return
        self._fitting = True
        try:
            header = table.horizontalHeader()
            header.setStretchLastSection(False)
            header.setMinimumSectionSize(56)
            for col, width in planned.items():
                header.setSectionResizeMode(col, QHeaderView.Fixed)
                table.setColumnWidth(col, width)
            table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            if sum(planned.values()) <= viewport + 4:
                table.horizontalScrollBar().setValue(0)
        finally:
            self._fitting = False

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

    def _cost_codes(self, product):
        health = product.get('cost_health') or {}
        return [item.get('code') for item in (health.get('badges') or [])]

    def _matches_cost_filter(self, product, code):
        if not code:
            return True
        codes = set(self._cost_codes(product))
        if code == 'zero_or_invalid':
            return bool(codes & {'explicit_zero', 'invalid_price', 'zero_review'})
        if code == 'inconsistent':
            return bool(codes & {'inconsistent', 'zero_review', 'stock_without_cost'})
        return code in codes

    def _choice(self, box, default):
        if not hasattr(self, box):
            return default
        value = getattr(self, box).currentData()
        return default if value is None else value

    def _reload_category_choices(self):
        from desktop.utils.inventory_filters import assigned_category
        box = self._category_filter
        current = box.currentData()
        names = []
        seen = set()
        try:
            for row in self.api.get_categories() or []:
                label = assigned_category({'category': row.get('name') or ''})
                key = label.casefold()
                if label and key not in seen:
                    seen.add(key)
                    names.append(label)
        except Exception:
            _log.exception('Could not load shop categories')
        for product in self.products or []:
            label = assigned_category(product)
            key = label.casefold()
            if label and key not in seen:
                seen.add(key)
                names.append(label)
        names.sort(key=str.casefold)
        box.blockSignals(True)
        box.clear()
        box.addItem('All categories', 'all')
        for label in names:
            box.addItem(label, label)
        box.addItem('Uncategorised', '__uncategorised__')
        index = box.findData(current if current is not None else 'all')
        box.setCurrentIndex(index if index >= 0 else 0)
        box.blockSignals(False)

    def _clear_filters(self):
        self._search.blockSignals(True)
        self._search.clear()
        self._search.blockSignals(False)
        for box_name, data in (
            ('_status_filter', 'all'),
            ('_category_filter', 'all'),
            ('_sort_filter', 'name_asc'),
            ('_cost_filter', ''),
        ):
            box = getattr(self, box_name)
            box.blockSignals(True)
            index = box.findData(data)
            box.setCurrentIndex(index if index >= 0 else 0)
            box.blockSignals(False)
        self._filter()

    def _filter(self):
        from desktop.utils.inventory_filters import filter_inventory, sort_inventory
        q = self._search.text()
        code = self._choice('_cost_filter', '')
        try:
            matched = filter_inventory(
                self.products,
                query=q,
                status=self._choice('_status_filter', 'all'),
                category=self._choice('_category_filter', 'all'),
            )
            matched = [p for p in matched if self._matches_cost_filter(p, code)]
            matched = sort_inventory(matched, self._choice('_sort_filter', 'name_asc'))
            self._populate(matched)
            shown = f"{len(matched)} product" if len(matched) == 1 else f"{len(matched)} products"
            if hasattr(self, '_shown'):
                self._shown.setText(shown)
            if not matched and self.products:
                self._stats.setText('  No products match these filters.')
        except Exception as e:
            _log.exception('Inventory filter error')
            self._stats.setText(f"  Could not filter inventory: {e}")

    def _populate(self, prods):
        self._tbl.setUpdatesEnabled(False)
        try:
            self._populate_rows(prods)
        finally:
            self._tbl.setUpdatesEnabled(True)

    def _populate_rows(self, prods):
        self._tbl.setRowCount(0)
        cfg  = self.config_getter() or {}
        cur  = cfg.get('currency_symbol', 'KES')
        low  = 0
        can_edit   = has_permission(self.user, 'inventory.edit_info')
        can_delete = has_permission(self.user, 'inventory.delete')

        for i, p in enumerate(prods):
            try:
                self._populate_row(i, p, cur, can_edit, can_delete)
                from desktop.utils.inventory_filters import stock_band
                if stock_band(p) == 'low':
                    low += 1
            except Exception as e:
                _log.warning(f"Skipping product row {p.get('id')}: {e}")
                self._tbl.insertRow(i)
                self._tbl.setItem(i, 0, tbl_item(p.get('name', '?') or '?'))
                self._tbl.setItem(i, 5, tbl_center('\u2014', C['warn']))

        stats = f"  {len(prods)} products  \u00b7  {low} low stock"
        review = 0
        for product in (self.products or prods):
            if any(code != 'complete' for code in self._cost_codes(product)):
                review += 1
        if review:
            stats += f"  \u00b7  {review} costing warnings \u00b7 valuation incomplete where a buying price or FIFO layer is missing"
        if has_permission(self.user, 'inventory.view_cost'):
            try:
                value = float((self.api.inventory_value() or {}).get('value') or 0)
            except Exception:
                value = 0
            stats += f"  \u00b7  FIFO value: {cur} {value:,.2f}"
        self._stats.setText(stats)
        # Final pass — guarantee every visible row has theme-matched zebra roles
        apply_table_row_backgrounds(self._tbl)
        # Zero-stock tint must win over zebra (scan aid vs low-stock red text alone)
        for i, p in enumerate(prods):
            if _safe_float(p.get('stock'), 0) <= 0:
                self._apply_zero_stock_row(i)

    def _populate_row(self, i, p, cur, can_edit, can_delete):
        self._tbl.insertRow(i)
        from desktop.utils.inventory_filters import stock_band
        stock = _safe_float(p.get('stock'), 0)
        band = stock_band(p)
        is_low = band == 'low'
        is_zero = band == 'out'

        from desktop.utils.display_category import display_category, normalize_product_name
        from desktop.utils.inventory_filters import assigned_category
        raw_name = p.get('name', '') or ''
        name = normalize_product_name(raw_name)
        sku = p.get('sku', '') or ''
        raw_cat = assigned_category(p)
        known = getattr(self, '_categories_by_name', {}) or {}
        if raw_cat and raw_cat.casefold() in known:
            cat_label, cat_tip = raw_cat, raw_cat
        else:
            cat_label, cat_tip = display_category(p.get('category', '') or '', raw_name)
        unit = p.get('unit', 'pcs') or 'pcs'
        price_s = f"{cur} {_safe_float(p.get('price')):,.2f}"
        cost_s = f"{cur} {_safe_float(p.get('cost_price')):,.2f}"

        name_item = tbl_item(name, tone='text')
        name_item.setToolTip(raw_name if raw_name != name else name)
        self._tbl.setItem(i, 0, name_item)
        try:
            from desktop.utils.product_photo import ProductPhotoTile
            tile = ProductPhotoTile(p.get('image_path') or '', size=36)
            tile.setEnabled(bool(can_edit))
            tile.choose = lambda pid=p.get('id'): self._edit(pid) if can_edit else None
            name_wrap = QWidget()
            name_wrap.setStyleSheet('background:transparent;')
            name_wrap.setMinimumWidth(0)
            name_wrap.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
            name_wrap.setToolTip(raw_name if raw_name else name)
            name_lay = QHBoxLayout(name_wrap)
            name_lay.setContentsMargins(4, 0, 8, 0)
            name_lay.setSpacing(8)
            name_lay.addWidget(tile)
            name_label = _ElideLabel(name)
            name_label.setStyleSheet(f"color:{C['text']}; background:transparent; font-size:13px;")
            name_lay.addWidget(name_label, 1)
            badge_codes = [code for code in self._cost_codes(p) if code != 'complete']
            if badge_codes:
                health = p.get('cost_health') or {}
                label = ''
                tone = 'warn'
                for item in health.get('badges') or []:
                    if item.get('code') == badge_codes[0]:
                        label = item.get('label') or badge_codes[0]
                        tone = item.get('tone') or 'warn'
                        break
                colour = {'err': C.get('err', '#b42318'), 'ok': C.get('ok', '#067647')}.get(
                    tone, C.get('warn', '#b54708'),
                )
                badge = _ElideLabel(label, cap=220)
                badge.setStyleSheet(
                    f"color:{colour}; background:transparent; font-size:11px; font-weight:700;"
                )
                name_lay.addWidget(badge)
                name_item.setToolTip(label)
            self._tbl.setCellWidget(i, 0, name_wrap)
        except Exception:
            _log.exception('Product photo tile failed')

        sku_item = tbl_item(sku if sku else '—', tone='text2' if not sku else 'text')
        sku_item.setToolTip(sku or 'No SKU')
        self._tbl.setItem(i, 1, sku_item)

        cat_tone = 'text2' if cat_label == 'Uncategorised' else 'text'
        cat_item = tbl_item(cat_label, tone=cat_tone)
        cat_item.setToolTip(cat_tip or cat_label)
        self._tbl.setItem(i, 2, cat_item)

        if _safe_float(p.get('price')) <= 0.009:
            price_item = tbl_right('—', tone='muted')
            price_item.setToolTip('No sell price set')
        else:
            price_item = tbl_right(price_s, tone='gold')
            price_item.setToolTip(price_s)
        self._tbl.setItem(i, 3, price_item)

        see_cost = has_permission(self.user, 'inventory.view_cost')
        if not see_cost:
            cost_item = tbl_right('—', tone='muted')
            cost_item.setToolTip('Cost is visible to a manager or administrator')
        elif _safe_float(p.get('cost_price')) <= 0.009:
            cost_item = tbl_right('—', tone='muted')
            cost_item.setToolTip('No cost set')
        else:
            cost_item = tbl_right(cost_s, tone='text')
            cost_item.setToolTip(cost_s)
        self._tbl.setItem(i, 4, cost_item)

        stk_s = _fmt_stock(stock, unit)
        if is_zero:
            tip = f'Out of stock · {stk_s} {unit}'
            stk_item = _stock_item('OUT', 'err', tip)
        elif is_low:
            tip = f'{stk_s} {unit} · low stock'
            stk_item = _stock_item(stk_s, 'warn', tip)
        else:
            tip = f'{stk_s} {unit}'
            stk_item = _stock_item(stk_s, 'ok', tip)
        self._tbl.setItem(i, 5, stk_item)

        unit_item = tbl_center(unit, tone='text2')
        unit_item.setToolTip(unit)
        self._tbl.setItem(i, 6, unit_item)

        action = tbl_center('', tone='text')
        action.setData(Qt.UserRole, p.get('id'))
        action.setData(Qt.UserRole + 1, bool(can_edit))
        action.setData(Qt.UserRole + 2, bool(can_delete))
        self._tbl.setItem(i, 7, action)
        actions = QWidget()
        actions.setStyleSheet('background:transparent;')
        actions.setMinimumWidth(0)
        actions.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        actions_row = QHBoxLayout(actions)
        actions_row.setContentsMargins(6, 0, 6, 0)
        actions_row.setSpacing(8)
        actions_row.setAlignment(Qt.AlignCenter)
        pair = (
            f"min-width:92px;max-width:92px;min-height:34px;max-height:34px;"
            f"padding:0;font-size:13px;font-weight:700;border-radius:8px;"
        )
        if can_delete:
            delete = DangerBtn('Remove', 34)
            delete.setFixedSize(92, 34)
            delete.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            delete.setToolTip('Remove this product')
            delete.setStyleSheet(
                f"QPushButton{{background:{C['err']};color:#ffffff;border:none;{pair}}}"
                f"QPushButton:hover{{background:{C['err']};}}"
            )
            delete.clicked.connect(lambda _=False, pid=p.get('id'): self._delete(pid))
            actions_row.addWidget(delete, 0, Qt.AlignCenter)
        more = QPushButton('More')
        more.setCursor(Qt.PointingHandCursor)
        more.setFixedSize(92, 34)
        more.setAccessibleName('More')
        more.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        more.setToolTip('Edit product and history')
        more.setStyleSheet(
            f"QPushButton{{background:transparent;color:{C['text']};"
            f"border:1px solid {C['border2']};{pair}}}"
            f"QPushButton:hover{{background:{C['hover']};border-color:{C['gold']};}}"
        )
        more.clicked.connect(
            lambda _=False, pid=p.get('id'), ce=bool(can_edit), cd=bool(can_delete), anchor=more:
            self._open_row_menu(pid, ce, cd, anchor)
        )
        actions_row.addWidget(more, 0, Qt.AlignCenter)
        self._tbl.setCellWidget(i, 7, actions)
        apply_table_row_backgrounds(self._tbl, row=i)
        if is_zero:
            self._apply_zero_stock_row(i)

    def _open_row_menu(self, pid, can_edit, can_delete, anchor):
        if not pid:
            return
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background:{C['card']}; color:{C['text']}; "
            f"border:1px solid {C['border']}; padding:4px; }}"
            f"QMenu::item {{ padding:8px 18px; border-radius:6px; }}"
            f"QMenu::item:selected {{ background:{C['hover']}; color:{C['gold']}; }}"
        )
        if can_edit:
            menu.addAction('Edit product', lambda pid=pid: self._edit(pid))
        menu.addAction('History', lambda pid=pid: self._show_history(pid))
        from desktop.dialogs.restock_dialog import can_open_restock
        if can_open_restock(self.user):
            menu.addAction('Add to Restock List', lambda pid=pid: self._add_to_restock(pid))
        if can_delete:
            menu.addSeparator()
            menu.addAction('Remove', lambda pid=pid: self._delete(pid))
        menu.exec_(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def _on_cell_clicked(self, row: int, col: int):
        if col != 7 or self._tbl.cellWidget(row, col) is not None:
            return
        item = self._tbl.item(row, col)
        if item is None:
            return
        self._open_row_menu(
            item.data(Qt.UserRole),
            bool(item.data(Qt.UserRole + 1)),
            bool(item.data(Qt.UserRole + 2)),
            self._tbl.viewport(),
        )

    def _apply_zero_stock_row(self, row: int):
        """OUT is badge-only — keep zebra row background (no maroon full-row tint)."""
        return
    def _request_adjustment_dialog(self):
        if self._role() == ROLE_SUPERADMIN or not has_permission(self.user, 'inventory.receive'):
            QMessageBox.warning(self, 'Access Denied',
                'Use Adjust Stock if you are the Super-Admin.'); return
        dlg = QDialog(self)
        dlg.setWindowTitle('Request a stock adjustment')
        dlg.setMinimumWidth(460)
        form = QFormLayout(dlg)
        prod = QComboBox()
        for p in (self.products or []):
            prod.addItem(f"{p.get('name')}  (stock {p.get('stock')})", p.get('id'))
        qty = QDoubleSpinBox()
        qty.setRange(0, 999999)
        qty.setDecimals(3)
        qty.setSingleStep(0.01)
        reason = QLineEdit()
        reason.setPlaceholderText('Why should stock change?')
        form.addRow('Product', prod)
        form.addRow('Target quantity', qty)
        form.addRow('Reason', reason)
        buttons = QHBoxLayout()
        cancel = SecondaryBtn('Cancel', 36)
        cancel.clicked.connect(dlg.reject)
        go = PrimaryBtn('Send request', 36)
        buttons.addWidget(cancel)
        buttons.addWidget(go)
        form.addRow(buttons)

        def send():
            if not reason.text().strip():
                QMessageBox.warning(dlg, 'Required', 'Enter a reason.'); return
            result = self.api.request_stock_adjustment(
                prod.currentData(), qty.value(), reason.text().strip(),
            )
            if result.get('error'):
                QMessageBox.warning(dlg, 'Not sent', result['error']); return
            QMessageBox.information(
                dlg, 'Request sent',
                f"{result.get('request_number')} is waiting for a Super-Admin. Stock was not changed.",
            )
            dlg.accept()

        go.clicked.connect(send)
        dlg.exec_()

    def _review_adjustment_requests(self):
        if self._role() != ROLE_SUPERADMIN:
            QMessageBox.warning(self, 'Access Denied',
                'Only Super-Admin can decide stock adjustments.'); return
        rows = self.api.list_stock_adjustment_requests('pending') or []
        if not rows:
            QMessageBox.information(self, 'Adjustment requests', 'No pending requests.'); return
        dlg = QDialog(self)
        dlg.setWindowTitle('Pending stock adjustments')
        dlg.resize(640, 360)
        lay = QVBoxLayout(dlg)
        table = QTableWidget(len(rows), 5)
        table.setHorizontalHeaderLabels(['Request', 'Product', 'Now', 'Target', 'Reason'])
        for i, row in enumerate(rows):
            table.setItem(i, 0, QTableWidgetItem(str(row.get('request_number') or '')))
            table.setItem(i, 1, QTableWidgetItem(str(row.get('product_name') or '')))
            table.setItem(i, 2, QTableWidgetItem(str(row.get('current_stock') or 0)))
            table.setItem(i, 3, QTableWidgetItem(str(row.get('requested_qty') or 0)))
            table.setItem(i, 4, QTableWidgetItem(str(row.get('reason') or '')))
        table.resizeColumnsToContents()
        lay.addWidget(table)
        buttons = QHBoxLayout()
        reject = SecondaryBtn('Reject selected', 36)
        approve = PrimaryBtn('Approve selected', 36)
        buttons.addStretch(1)
        buttons.addWidget(reject)
        buttons.addWidget(approve)
        lay.addLayout(buttons)

        def decide(decision):
            idx = table.currentRow()
            if idx < 0:
                QMessageBox.warning(dlg, 'Select one', 'Select a request first.'); return
            result = self.api.review_stock_adjustment(rows[idx]['id'], decision)
            if result.get('error'):
                QMessageBox.warning(dlg, 'Not applied', result['error']); return
            QMessageBox.information(dlg, 'Saved', f"Request {result.get('status')}.")
            dlg.accept()
            self.refresh()

        reject.clicked.connect(lambda: decide('rejected'))
        approve.clicked.connect(lambda: decide('approved'))
        dlg.exec_()

    def _open_stocktake(self):
        from desktop.utils.security import has_permission
        dlg = QDialog(self)
        dlg.setWindowTitle('Stocktake')
        dlg.setMinimumWidth(420)
        apply_themed_dialog(dlg)
        lay = QVBoxLayout(dlg)
        name = QLineEdit()
        name.setPlaceholderText('Count name, for example Monday morning')
        product = QComboBox()
        for prod in self.products or []:
            product.addItem(prod.get('name') or '', prod.get('id'))
        qty = QDoubleSpinBox()
        qty.setRange(0, 1000000)
        qty.setDecimals(2)
        qty.setSingleStep(0.01)
        status = QLabel('A count does not change stock until it is applied.')
        status.setWordWrap(True)
        history = QListWidget()
        history.setMinimumHeight(120)
        lay.addWidget(QLabel('Name'))
        lay.addWidget(name)
        lay.addWidget(QLabel('Product'))
        lay.addWidget(product)
        lay.addWidget(QLabel('Counted quantity'))
        lay.addWidget(qty)
        lay.addWidget(QLabel('Recent counts'))
        lay.addWidget(history)
        lay.addWidget(status)

        def show_history():
            history.clear()
            listed = self.api.list_stocktakes()
            for row in listed.get('stocktakes') or []:
                item = QListWidgetItem(f"{row.get('name') or 'Count'} · {row.get('status') or ''}")
                item.setData(Qt.UserRole, row.get('id'))
                history.addItem(item)

        def open_saved():
            item = history.currentItem()
            if item is None:
                return
            detail = self.api.get_stocktake(item.data(Qt.UserRole))
            if detail.get('error'):
                status.setText(detail['error'])
                return
            holder['id'] = detail.get('id')
            name.setText(detail.get('name') or '')
            lines = detail.get('lines') or []
            if lines:
                status.setText(
                    f"{detail.get('name')} is {detail.get('status')}. "
                    f"{lines[0].get('name')}: counted {lines[0].get('counted_qty')}, "
                    f"snapshot {lines[0].get('snapshot_qty')}."
                )
            else:
                status.setText(f"{detail.get('name')} is {detail.get('status')}. No lines yet.")

        show_history()
        history.itemClicked.connect(lambda _item: open_saved())
        buttons = QHBoxLayout()
        start = PrimaryBtn('Start and save count', 36)
        apply_btn = SecondaryBtn('Apply count', 36)
        apply_btn.setEnabled(has_permission(self.user, 'inventory.adjust_stock'))
        close = GhostBtn('Close', 36)
        buttons.addWidget(start)
        buttons.addWidget(apply_btn)
        buttons.addWidget(close)
        lay.addLayout(buttons)
        holder = {'id': None}

        def save():
            if holder['id'] is None:
                opened = self.api.start_stocktake(name.text())
                if not opened.get('success'):
                    status.setText(opened.get('error') or 'Could not start the count')
                    return
                holder['id'] = opened.get('id')
            pid = product.currentData()
            from desktop.utils.quantities import QuantityError, parse_quantity
            chosen = next((item for item in (self.products or []) if item.get('id') == pid), {})
            try:
                counted = parse_quantity(
                    qty.value(), chosen.get('unit'), allow_zero=True,
                    decimal_qty=chosen.get('allow_decimal_qty'),
                )
            except QuantityError as exc:
                message = str(exc)
                if 'whole units' in message:
                    message = f"'{chosen.get('name') or 'This product'}' is sold in whole units."
                status.setText(message)
                return
            saved = self.api.record_stocktake_count(holder['id'], pid, counted)
            status.setText(
                'Count saved. Stock is unchanged.' if saved.get('success')
                else (saved.get('error') or 'Could not save the count')
            )
            if saved.get('success'):
                show_history()

        def apply_count():
            if holder['id'] is None:
                status.setText('Save a count first.')
                return
            result = self.api.apply_stocktake(holder['id'])
            if result.get('success'):
                status.setText('Count applied. Stock now includes sales made during the count.')
                show_history()
                self.refresh()
            else:
                status.setText(result.get('error') or 'Could not apply the count')

        start.clicked.connect(save)
        apply_btn.clicked.connect(apply_count)
        close.clicked.connect(dlg.reject)
        dlg.exec_()

    def _open_restock(self):
        from desktop.dialogs.restock_dialog import open_restock_dialog
        open_restock_dialog(self, self.api, self.user)

    def _add_to_restock(self, product_id):
        from desktop.dialogs.restock_dialog import RestockDialog, _run
        from backend import restock_requests as restock
        dialog = RestockDialog(self.api, self.user, self)
        lists = _run(dialog.actor, restock.list_requests, {})
        drafts = [row for row in (lists.get('requests') or []) if row.get('status') == 'draft']
        if not drafts:
            created = _run(dialog.actor, restock.create_request, {'name': 'Shop restock'})
            if created.get('error'):
                QMessageBox.warning(self, 'Restock list', created['error'])
                return
            target = created['request']
        else:
            target = drafts[0]
            full = _run(dialog.actor, restock.get_request, target['id'])
            target = full.get('request') or target
        added = _run(dialog.actor, restock.add_line, target['id'], {
            'version': target['version'], 'product_id': product_id, 'quantity': 1, 'merge': True,
        })
        if added.get('error'):
            QMessageBox.warning(self, 'Restock list', added['error'])
            return
        QMessageBox.information(
            self, 'Restock list',
            f"Added to {added['request']['name']}. The open sale was not changed.",
        )

    def _receive_stock_dialog(self):
        if not has_permission(self.user, 'inventory.receive'):
            QMessageBox.warning(self, 'Access Denied',
                'Your role cannot receive supplier stock.'); return
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
        if self._adjust_stock_active:
            _log.warning('Ignored duplicate Adjust Stock invocation')
            return

        try:
            fresh_products = self.api.get_products() or []
            self.products = fresh_products
        except Exception as e:
            QMessageBox.critical(
                self, 'Adjust Stock', f'Could not refresh inventory:\n\n{e}')
            return

        if not self.products:
            QMessageBox.information(self, 'No Products',
                'Add products first.'); return

        self._adjust_stock_active = True
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
            qty.setSingleStep(0.01)
            qty.setMinimumHeight(40)
            qty.setEnabled(False)
            selected = {'pid': None, 'stock': None}

            def _on_prod(_=None):
                pid = prod_sel.current_value()
                prod = next((x for x in self.products if x['id'] == pid), None)
                if prod:
                    selected['pid'] = pid
                    selected['stock'] = _safe_float(prod.get('stock'), 0)
                    qty.setEnabled(True)
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
                else:
                    selected['pid'] = None
                    selected['stock'] = None
                    qty.setEnabled(False)
                    qty.setValue(0)
                    qty.setToolTip('Select a product first')

            prod_sel.currentIndexChanged.connect(_on_prod)
            prod_sel.cleared.connect(_on_prod)
            prod_sel.clear_selection()
            _on_prod()
            reason = ReasonSelect(reasons=STOCK_ADJUSTMENT_REASONS, height=40)
            form.addRow('Product', prod_sel)
            form.addRow('New quantity', qty)
            form.addRow('Reason', reason)
            buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)

            def _validate_and_accept():
                pid = prod_sel.current_value()
                prod = next((x for x in self.products if x['id'] == pid), None)
                if not prod:
                    QMessageBox.warning(self, 'Required', 'Select a product.')
                    prod_sel.setFocus()
                    return
                if not reason.is_valid():
                    QMessageBox.warning(self, 'Required', reason.validation_error())
                    reason.setFocus()
                    return
                try:
                    latest_products = self.api.get_products() or []
                    latest = next((x for x in latest_products if x['id'] == pid), None)
                    if latest is None:
                        QMessageBox.warning(
                            self, 'Product Changed',
                            'This product no longer exists. Refresh and try again.')
                        return
                    latest_stock = _safe_float(latest.get('stock'), 0)
                    if latest_stock != selected['stock']:
                        self.products = latest_products
                        selected['stock'] = latest_stock
                        qty.setValue(latest_stock)
                        QMessageBox.warning(
                            self, 'Stock Changed',
                            'Stock changed while this form was open. The latest '
                            'quantity is now shown; review it and submit again.')
                        return
                except Exception as e:
                    QMessageBox.critical(
                        self, 'Adjust Stock',
                        f'Could not verify the latest stock quantity:\n\n{e}')
                    return
                dlg.accept()

            buttons.accepted.connect(_validate_and_accept)
            buttons.rejected.connect(dlg.reject)
            form.addRow(buttons)

            if dlg.exec_() != QDialog.Accepted:
                return
            pid = prod_sel.current_value()
            prod = next((x for x in self.products if x['id'] == pid), None)
            if not prod or not reason.is_valid():
                return
            new_qty = round(float(qty.value()), 4)

            pin = collect_superadmin_pin(
                self.api, self, reason="Adjust '%s' stock" % prod['name'])
            if not pin:
                return

            res = self.api.adjust_stock(
                prod['id'], new_qty, reason.value(),
                expected_stock=selected['stock'],
                pin=pin,
            )
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
        finally:
            self._adjust_stock_active = False

    def _add(self):
        if not require_permission(self.user, 'inventory.create', self):
            return
        try:
            dlg = _ProdDlg(self, role=self._role(), user=self.user, config_getter=self.config_getter)
            if dlg.exec_() != QDialog.Accepted:
                return
            res = self.api.create_product(dlg.data())
            if res and res.get('success'):
                if res.get('pending_approval'):
                    QMessageBox.information(
                        self, 'Waiting for approval',
                        res.get('message') or 'The product was not published.')
                elif dlg.photo_source() and res.get('id'):
                    saved = self.api.save_product_image(res['id'], dlg.photo_source())
                    if saved.get('error'):
                        QMessageBox.warning(
                            self, 'Photograph',
                            saved['error'])
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

    def _open_issues(self):
        from desktop.utils.api_client import _db
        from desktop.utils.business_issues import list_issues, scan, summary
        db = _db()
        try:
            scan(db, str(self.user.get('username') or 'till'))
            items = list_issues(db, self.user, 'open')
            counts = summary(db, self.user)
        finally:
            db.close()
        dlg = QDialog(self)
        dlg.setWindowTitle('Business issues')
        dlg.setMinimumSize(1040, 480)
        dlg.resize(1120, 520)
        apply_themed_dialog(dlg)
        lay = QVBoxLayout(dlg)
        lay.addWidget(Caption(
            f"Open {counts['open']}  ·  Important {counts['important']}  ·  "
            f"Attention {counts['attention']}  ·  Critical {counts['critical']}"
        ))
        lay.addWidget(Caption('Opening a row does not resolve it. Saving the real correction does.'))
        table = make_table(['Severity', 'Issue', 'Since'], stretch_col=1)
        header = table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        table.setColumnWidth(2, 188)
        table.setTextElideMode(Qt.ElideRight)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        table.setRowCount(len(items))
        for i, item in enumerate(items):
            title = item.get('title') or ''
            since_raw = item.get('first_detected') or ''
            since = _issue_since_label(since_raw)
            issue_item = tbl_item(title)
            tip = title
            explanation = (item.get('explanation') or '').strip()
            if explanation and explanation not in title:
                tip = f"{title}\n{explanation}"
            issue_item.setToolTip(tip)
            since_item = tbl_item(since)
            since_item.setToolTip(since_raw or since)
            table.setItem(i, 0, tbl_item(item['severity'].title()))
            table.setItem(i, 1, issue_item)
            table.setItem(i, 2, since_item)
            table.item(i, 0).setData(Qt.UserRole, item)
        lay.addWidget(table, 1)
        buttons = QHBoxLayout()
        open_btn = PrimaryBtn('Open record', 40)
        close_btn = GhostBtn('Close', 40)

        def _open():
            row = table.currentRow()
            if row < 0:
                return
            item = table.item(row, 0).data(Qt.UserRole) or {}
            dest = item.get('destination') or {}
            product_id = dest.get('product_id')
            dlg.accept()
            if product_id:
                self.refresh()
                self._edit(int(product_id))
                self._open_issues()

        open_btn.clicked.connect(_open)
        close_btn.clicked.connect(dlg.reject)
        buttons.addWidget(open_btn)
        buttons.addStretch(1)
        buttons.addWidget(close_btn)
        lay.addLayout(buttons)
        dlg.exec_()

    def _edit(self, pid):
        if not require_permission(self.user, 'inventory.edit_info', self):
            return
        p = next((x for x in self.products if x['id'] == pid), None)
        if not p:
            return
        try:
            dlg = _ProdDlg(self, p, role=self._role(), user=self.user)
            if dlg.exec_() != QDialog.Accepted:
                return
            res = self.api.update_product(pid, dlg.data(), pin_verified=False)
            if res and res.get('success'):
                if res.get('pending_approval'):
                    QMessageBox.information(
                        self, 'Waiting for approval',
                        res.get('message') or 'The live product was not changed.')
                    self.refresh()
                    return
                if dlg.photo_source():
                    saved = self.api.save_product_image(pid, dlg.photo_source())
                    if saved.get('error'):
                        QMessageBox.warning(self, 'Photograph', saved['error'])
                elif dlg.photo_cleared():
                    saved = self.api.clear_product_image(pid)
                    if saved.get('error'):
                        QMessageBox.warning(self, 'Photograph', saved['error'])
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
        if not require_permission(self.user, 'inventory.delete', self): return
        p = next((x for x in self.products if x['id'] == pid), None)
        name = p.get('name', '') if p else ''
        if QMessageBox.question(self, 'Remove product',
                f"Remove '{name}'?\n\nIf it has stock, a receipt, or a stock movement, it leaves the selling list and old receipts keep it. If it has no history, it is deleted.",
                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            removed = self.api.delete_product(pid)
            if removed and removed.get('success'):
                self.refresh()
            else:
                QMessageBox.warning(
                    self, 'Could Not Delete Product',
                    (removed or {}).get('error', 'This product was not removed.'))

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

    def _open_batches(self):
        dlg = QDialog(self)
        dlg.setWindowTitle('Batches')
        dlg.resize(980, 640)
        apply_themed_dialog(dlg)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(16, 16, 16, 16)
        search = QLineEdit()
        search.setPlaceholderText('Search product, batch, or supplier')
        search.setMinimumHeight(40)
        table = make_table(
            ['Batch', 'Product', 'Supplier', 'Received', 'Reference', 'In', 'Left', 'Selling', 'Price', 'Status'],
            stretch_col=1, row_height=36,
        )
        lay.addWidget(search)
        lay.addWidget(table, 1)

        def load():
            data = self.api.list_batches(search.text()) or {}
            rows = data.get('batches') or []
            table.setRowCount(0)
            for i, batch in enumerate(rows):
                table.insertRow(i)
                table.setItem(i, 0, tbl_item(str(batch.get('batch_ref') or '')))
                table.setItem(i, 1, tbl_item(str(batch.get('product_name') or '')))
                table.setItem(i, 2, tbl_item(str(batch.get('supplier_name') or '')))
                table.setItem(i, 3, tbl_item(str(batch.get('created_at') or '')))
                table.setItem(i, 4, tbl_item(str(batch.get('reference_note') or '')))
                table.setItem(i, 5, tbl_center(str(batch.get('original_qty') or 0)))
                table.setItem(i, 6, tbl_center(str(batch.get('remaining_qty') or 0)))
                table.setItem(i, 7, tbl_right(f"{float(batch.get('effective_sell_price') or 0):,.2f}"))
                table.setItem(i, 8, tbl_item('Custom' if batch.get('price_mode') == 'custom' else 'Normal'))
                table.setItem(i, 9, tbl_item(str(batch.get('status') or '')))

        search.textChanged.connect(lambda _text: load())
        load()
        dlg.exec_()


# â”€â”€ Product Dialog â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class _ProdDlg(QDialog):
    def __init__(self, parent, prod=None, role='cashier', config_getter=None, user=None):
        super().__init__(parent)
        self.setWindowTitle('Add New Product' if not prod else 'Edit Product')
        self.setMinimumWidth(500)
        apply_themed_dialog(self)

        self._is_new = prod is None
        self._pid = None if not prod else prod.get('id')
        self._role   = role
        self._config_getter = config_getter
        from desktop.utils.security import has_permission
        actor = user or {'role': role}
        self._can_remove = has_permission(actor, 'inventory.delete')
        self._see_cost = has_permission(actor, 'inventory.view_cost')

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
        self.barcode = QLineEdit(); self.barcode.setMinimumHeight(42); self.barcode.setPlaceholderText('Scan or type the barcode')
        self.cat = QComboBox()
        self.cat.setMinimumHeight(42)
        self.cat.setAccessibleName('Category')
        self._fill_categories((prod or {}).get('category') or '')
        self.cat.currentIndexChanged.connect(lambda _i: self._on_cat_preview())
        self.price = QDoubleSpinBox(); self.price.setRange(0, 9999999); self.price.setDecimals(2); self.price.setMinimumHeight(42)
        self.cost  = QDoubleSpinBox(); self.cost.setRange(0, 9999999);  self.cost.setDecimals(2); self.cost.setMinimumHeight(42)
        self.mins  = QSpinBox();       self.mins.setRange(0, 999999);   self.mins.setValue(5);    self.mins.setMinimumHeight(42)
        self.unit  = QLineEdit();      self.unit.setMinimumHeight(42);  self.unit.setText('pcs')
        self.decimals = QComboBox(); self.decimals.setMinimumHeight(42)
        self.decimals.addItem('Follow the unit', None)
        self.decimals.addItem('Allow decimal quantities', 1)
        self.decimals.addItem('Whole quantities only', 0)
        self.status = Select(items=list(PRODUCT_STATUSES))
        self.status.setMinimumHeight(42)

        if prod:
            self.name.setText(prod.get('name') or '')
            self.sku.setText(prod.get('sku') or '')
            self.barcode.setText(prod.get('barcode') or '')
            self.price.setValue(_safe_float(prod.get('price')))
            self.cost.setValue(_safe_float(prod.get('cost_price')))
            self.mins.setValue(_safe_int(prod.get('min_stock'), 5))
            self.unit.setText(prod.get('unit') or 'pcs')
            flag = prod.get('allow_decimal_qty')
            flag_index = {None: 0, '': 0, 1: 1, '1': 1, True: 1, 0: 2, '0': 2, False: 2}.get(flag, 0)
            self.decimals.setCurrentIndex(flag_index)
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
        lay.addRow(lbl('Barcode'),           self.barcode)
        # Category + live visual preview (icon from offline library)
        cat_wrap = QWidget()
        cat_hl = QHBoxLayout(cat_wrap)
        cat_hl.setContentsMargins(0, 0, 0, 0)
        cat_hl.setSpacing(8)
        cat_hl.addWidget(self.cat, 1)
        self._add_cat_btn = SecondaryBtn('Add new category', 42)
        self._add_cat_btn.setToolTip('Create a category and select it without leaving this product')
        self._add_cat_btn.clicked.connect(self._add_category)
        if not has_permission(actor, 'categories.create'):
            self._add_cat_btn.setVisible(False)
        cat_hl.addWidget(self._add_cat_btn)
        try:
            from desktop.utils.category_visuals import CategoryVisual
            self._cat_vis = CategoryVisual(size=40, show_label=False)
            cat_hl.addWidget(self._cat_vis)
        except Exception:
            self._cat_vis = None
        lay.addRow(lbl('Category'),          cat_wrap)
        self._on_cat_preview()
        lay.addRow(lbl('Selling Price'),     self.price)
        self._enter_cost = self._see_cost or prod is None
        if self._enter_cost:
            lay.addRow(lbl('Cost Price' if self._see_cost else 'Buying price'), self.cost)
        lay.addRow(lbl('Min Stock Alert'),   self.mins)
        lay.addRow(lbl('Unit'),              self.unit)
        lay.addRow(lbl('Decimal quantities'), self.decimals)
        if self._can_remove:
            lay.addRow(lbl('Status'),        self.status)

        from desktop.utils.product_photo import ProductPhotoTile
        self._photo = ProductPhotoTile((prod or {}).get('image_path') or '', size=88)
        photo_side = QVBoxLayout()
        photo_side.setContentsMargins(0, 0, 0, 0)
        photo_side.setSpacing(6)
        photo_hint = QLabel('Click the camera to add or change the photograph.')
        photo_hint.setWordWrap(True)
        photo_hint.setStyleSheet(f"color:{C['muted']}; font-size:12px; background:transparent;")
        photo_clear = GhostBtn('Remove photograph', 32)
        photo_clear.setToolTip('Remove the photograph and show the empty camera tile')
        photo_clear.clicked.connect(self._photo.clear_photo)
        photo_side.addWidget(photo_hint)
        photo_side.addWidget(photo_clear, 0, Qt.AlignLeft)
        photo_side.addStretch()
        photo_wrap = QWidget()
        photo_lay = QHBoxLayout(photo_wrap)
        photo_lay.setContentsMargins(0, 0, 0, 0)
        photo_lay.setSpacing(10)
        photo_lay.addWidget(self._photo)
        photo_lay.addLayout(photo_side, 1)
        lay.addRow(lbl('Photograph'), photo_wrap)

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
            stk_info.setWordWrap(True)
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
        if (not self._is_new) and self._can_remove and self._pid:
            delete = DangerBtn('Remove product', 44)
            delete.clicked.connect(self._request_delete)
            btn_row.addWidget(delete, 1)
        btn_row.addWidget(save, 1)
        btn_wrap = QWidget()
        btn_wrap.setLayout(btn_row)
        lay.addRow(btn_wrap)
        from desktop.utils.dialog_keys import wire_dialog_keys
        wire_dialog_keys(self, primary=save, cancel=cancel)

        from desktop.utils.state_reset import StateResetManager
        if self._is_new:
            StateResetManager.clear_modal_on_close(
                self, wipe=lambda: StateResetManager.reset_product_form(self))
        else:
            StateResetManager.clear_modal_on_close(self)

    def _category_value(self) -> str:
        data = self.cat.currentData()
        if data is None:
            return (self.cat.currentText() or '').strip()
        return str(data or '').strip()

    def _fill_categories(self, current: str = ''):
        current = (current or '').strip()
        self.cat.blockSignals(True)
        self.cat.clear()
        self.cat.addItem('Uncategorised', '')
        names = []
        try:
            parent = self.parent()
            api = getattr(parent, 'api', None)
            for row in (api.get_categories() if api else []) or []:
                name = (row.get('name') or '').strip()
                if name:
                    names.append(name)
        except Exception:
            names = []
        seen = set()
        for name in names:
            key = name.casefold()
            if key in seen:
                continue
            seen.add(key)
            self.cat.addItem(name, name)
        if current and current.casefold() not in seen:
            self.cat.addItem(current, current)
        index = 0
        for i in range(self.cat.count()):
            if str(self.cat.itemData(i) or '').casefold() == current.casefold():
                index = i
                break
        self.cat.setCurrentIndex(index)
        self.cat.blockSignals(False)

    def _add_category(self):
        dlg = QDialog(self)
        dlg.setWindowTitle('New Category')
        dlg.setMinimumWidth(420)
        form = QFormLayout(dlg)
        form.setContentsMargins(16, 16, 16, 16)
        name = QLineEdit()
        name.setMinimumHeight(40)
        name.setAccessibleName('New category name')
        name.setPlaceholderText('Category name')
        desc = QLineEdit()
        desc.setMinimumHeight(40)
        desc.setAccessibleName('New category description')
        desc.setPlaceholderText('Optional description')
        form.addRow('Name', name)
        form.addRow('Description', desc)
        buttons = QHBoxLayout()
        cancel = SecondaryBtn('Cancel', 40)
        create = PrimaryBtn('Create category', 40)
        cancel.clicked.connect(dlg.reject)
        buttons.addWidget(cancel)
        buttons.addWidget(create)
        wrap = QWidget()
        wrap.setLayout(buttons)
        form.addRow(wrap)

        def _save():
            parent = self.parent()
            api = getattr(parent, 'api', None)
            if api is None:
                QMessageBox.warning(dlg, 'Category', 'Categories are not available.')
                return
            result = api.create_category({
                'name': name.text(),
                'description': desc.text(),
            })
            if result.get('error'):
                existing = api.get_category_by_name(name.text()) if 'already exists' in (result.get('error') or '').lower() else {}
                if existing.get('name'):
                    self._fill_categories(existing['name'])
                    self._on_cat_preview()
                    dlg.accept()
                    return
                QMessageBox.warning(dlg, 'Category', result.get('error') or 'The category was not created.')
                return
            self._fill_categories(result.get('name') or name.text())
            self._on_cat_preview()
            dlg.accept()

        create.clicked.connect(_save)
        dlg.exec_()

    def _on_cat_preview(self, text=''):
        if not getattr(self, '_cat_vis', None):
            return
        name = (text or self._category_value() or '').strip()
        if not name:
            try:
                self._cat_vis.set_category({'name': 'Uncategorised', 'visual_type': 'icon'})
            except Exception:
                pass
            return
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

    def photo_source(self) -> str:
        tile = getattr(self, '_photo', None)
        return tile.photo_source() if tile else ''

    def photo_cleared(self) -> bool:
        tile = getattr(self, '_photo', None)
        return bool(tile and tile.photo_cleared())

    def _request_delete(self):
        pid = self._pid
        parent = self.parent()
        self.reject()
        if parent is not None and hasattr(parent, '_delete'):
            parent._delete(pid)

    def _val(self):
        if not self.name.text().strip():
            QMessageBox.warning(self, 'Required', 'Product name is required.')
            return
        self.accept()

    def data(self):
        d = {
            'name':       self.name.text().strip(),
            'sku':        self.sku.text().strip() or None,
            'barcode':    self.barcode.text().strip() or None,
            'category':   self._category_value(),
            'price':      self.price.value(),
            'min_stock':  self.mins.value(),
            'unit':       self.unit.text().strip() or 'pcs',
            'allow_decimal_qty': self.decimals.currentData(),
        }
        if self._enter_cost:
            d['cost_price'] = self.cost.value()
        if self._can_remove:
            status = self.status.current_label() or 'Active'
            d['is_active'] = 1 if status == 'Active' else 0
            d['product_status'] = status
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

        batches_w = QWidget()
        bw = QVBoxLayout(batches_w)
        bw.setContentsMargins(0, 8, 0, 0)
        self._batch_meta = Caption('')
        self._batch_meta.setWordWrap(True)
        bw.addWidget(self._batch_meta)
        self._batch_tbl = make_table(
            ['Batch', 'Supplier', 'Received', 'Reference', 'In', 'Used', 'Left',
             'Buy', 'Extra', 'Landed', 'Left value', 'Selling', 'Price', 'Status'],
            stretch_col=1, row_height=40)
        bw.addWidget(self._batch_tbl)
        self._price_btn = SecondaryBtn('Set batch selling price', 36)
        self._price_btn.clicked.connect(self._set_selling_price)
        self._price_btn.setVisible(False)
        bw.addWidget(self._price_btn)
        tabs.addTab(batches_w, 'Batches')

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
        self._product_price = price
        self._price_btn.setVisible(bool(data.get('can_set_batch_price')))
        self._meta.setText(
            f"Entered inventory: {entered}  ·  SKU: {sku}  ·  Category: {cat}\n"
            f"Current stock: {stock} {unit}  ·  Price: {cur} {price:,.2f}"
        )

        batches = data.get('batches') or []
        self._batches = batches
        summary = data.get('batch_summary') or {}
        see_cost = bool(data.get('see_cost'))
        bits = [
            f"Batches on hand: {summary.get('active_batches') or 0}",
            f"Oldest batch: {summary.get('oldest_batch_id') or '-'}",
        ]
        if see_cost:
            bits.append(f"Stock value: {cur} {_safe_float(summary.get('inventory_value')):,.2f}")
            bits.append(f"Average cost: {cur} {_safe_float(summary.get('average_cost')):,.2f}")
            latest = summary.get('latest_purchase_price')
            bits.append(
                f"Latest buy: {cur} {_safe_float(latest):,.2f}" if latest is not None else 'Latest buy: -'
            )
        self._batch_meta.setText('  ·  '.join(bits))
        self._batch_tbl.setRowCount(0)
        for i, batch in enumerate(batches):
            self._batch_tbl.insertRow(i)
            self._batch_tbl.setItem(i, 0, tbl_item(str(batch.get('batch_ref') or batch.get('id') or '')))
            supplier = batch.get('supplier_name') or ('Opening stock' if batch.get('legacy') else '-')
            self._batch_tbl.setItem(i, 1, tbl_item(str(supplier)))
            self._batch_tbl.setItem(i, 2, tbl_item(_fmt_dt(batch.get('created_at'))))
            self._batch_tbl.setItem(i, 3, tbl_item(str(batch.get('reference_note') or batch.get('source_id') or '')))
            self._batch_tbl.setItem(i, 4, tbl_center(_fmt_stock(batch.get('original_qty'))))
            self._batch_tbl.setItem(i, 5, tbl_center(_fmt_stock(batch.get('consumed_qty'))))
            self._batch_tbl.setItem(i, 6, tbl_center(_fmt_stock(batch.get('remaining_qty'))))
            if see_cost:
                self._batch_tbl.setItem(i, 7, tbl_right(f"{_safe_float(batch.get('purchase_unit_cost')):,.2f}"))
                self._batch_tbl.setItem(i, 8, tbl_right(f"{_safe_float(batch.get('extra_unit_cost')):,.2f}"))
                self._batch_tbl.setItem(i, 9, tbl_right(f"{_safe_float(batch.get('unit_cost')):,.2f}"))
                self._batch_tbl.setItem(i, 10, tbl_right(f"{_safe_float(batch.get('remaining_value')):,.2f}", C['gold']))
            else:
                for col in (7, 8, 9, 10):
                    self._batch_tbl.setItem(i, col, tbl_right('—', C['muted']))
            selling = batch.get('effective_sell_price')
            self._batch_tbl.setItem(
                i, 11,
                tbl_right('—' if selling is None else f"{_safe_float(selling):,.2f}"),
            )
            self._batch_tbl.setItem(i, 12, tbl_center('Custom' if batch.get('price_mode') == 'custom' else 'Normal'))
            origin = 'inherited' if batch.get('cost_origin') == 'inherited' else ''
            status = str(batch.get('status') or '')
            if origin:
                status = f"{status} · {origin}"
            self._batch_tbl.setItem(i, 13, tbl_center(status))

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

    def _set_selling_price(self):
        batches = getattr(self, '_batches', []) or []
        row = self._batch_tbl.currentRow()
        if row < 0 or row >= len(batches):
            QMessageBox.information(self, 'Batch price', 'Select a batch first.')
            return
        batch = batches[row]
        if batch.get('status') == 'exhausted' or float(batch.get('remaining_qty') or 0) <= 0:
            QMessageBox.information(
                self, 'Batch price',
                'That batch is finished. Its history stays, and it cannot be sold.',
            )
            return
        current = batch.get('sell_price')
        text, ok = QInputDialog.getText(
            self, 'Batch selling price',
            'Selling price for this batch. Leave blank to use the normal product price.',
            text='' if current in (None, '') else str(current),
        )
        if not ok:
            return
        raw = str(text).strip()
        price = None if raw == '' else raw
        if price is not None:
            try:
                number = round(float(price), 4)
            except ValueError:
                QMessageBox.warning(self, 'Batch price', 'Enter a valid selling price.')
                return
            if number < 0:
                QMessageBox.warning(self, 'Batch price', 'Selling price cannot be negative.')
                return
            normal = float(getattr(self, '_product_price', 0) or 0)
            if number > normal + 0.001:
                answer = QMessageBox.question(
                    self, 'Above the normal price',
                    f'This batch price is above the normal product price of {normal:,.2f}. Save it?',
                )
                if answer != QMessageBox.Yes:
                    return
            price = number
        result = self.api.set_batch_selling_price(batch.get('id'), price) or {}
        if result.get('error'):
            QMessageBox.warning(self, 'Batch price', result['error'])
            return
        if result.get('warning'):
            QMessageBox.information(self, 'Batch price', result['warning'])
        self._load()
