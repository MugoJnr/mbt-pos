import sys
"""
MBT POS - Spreadsheet Export Engine v2
MugoByte Technologies | mugobyte.com
Generates comprehensive multi-sheet Excel reports with full product detail.
"""
import os
from datetime import datetime, date
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.chart import BarChart, Reference

# ── Palette ────────────────────────────────────────────────────────────────────
D = "0D1B2A"; M = "1A3C5E"; G = "F4A825"; W = "FFFFFF"
ALT = "EEF3F8"; TOT_BG = "FFF3CC"; TOT_FG = "0D1B2A"; BDR = "B0BEC5"
GRN = "43A047"; RED = "E53935"; BLU = "1565C0"

def _s(style='thin', color=BDR): return Side(style=style, color=color)
def _border(c=BDR): s=_s(color=c); return Border(left=s,right=s,top=s,bottom=s)
def _fill(h): return PatternFill("solid", fgColor=h)
def _font(size=10,bold=False,color='000000',italic=False,name='Calibri'):
    return Font(name=name,size=size,bold=bold,color=color,italic=italic)
def _align(h='left',v='center',wrap=False):
    return Alignment(horizontal=h,vertical=v,wrap_text=wrap)

def _hdr_cell(ws, row, col, value, width=None, col_letter=None):
    c = ws.cell(row=row, column=col, value=value)
    c.font      = _font(11, bold=True, color=W)
    c.fill      = _fill(M)
    c.alignment = _align('center')
    c.border    = _border(BDR)
    if width and col_letter:
        ws.column_dimensions[col_letter].width = width
    return c

def _brand_header(ws, shop, title, date_range=None, ncols=12):
    end = get_column_letter(ncols)
    ws.merge_cells(f'A1:{end}1')
    c = ws['A1']
    c.value     = f"  {shop}  |  {title}"
    c.font      = _font(16, bold=True, color=W)
    c.fill      = _fill(D)
    c.alignment = _align('center','center')
    ws.row_dimensions[1].height = 34

    ws.merge_cells(f'A2:{end}2')
    c2 = ws['A2']
    sub = "MugoByte Technologies  |  mugobyte.com"
    if date_range: sub += f"  |  Period: {date_range}"
    c2.value     = sub
    c2.font      = _font(10, italic=True, color=G)
    c2.fill      = _fill(M)
    c2.alignment = _align('center','center')
    ws.row_dimensions[2].height = 18

def _kpi_block(ws, kpis, start_row=4, currency='KES'):
    ws.cell(start_row-1,1).value = "KEY PERFORMANCE INDICATORS"
    ws.cell(start_row-1,1).font  = _font(12, bold=True, color=M)
    ws.row_dimensions[start_row-1].height = 22
    for i,(lbl,val,fmt) in enumerate(kpis):
        r = start_row + i
        lc = ws.cell(r,1,lbl); lc.font=_font(10,bold=True); lc.fill=_fill(ALT)
        lc.border=_border(); lc.alignment=_align()
        vc = ws.cell(r,2,val); vc.border=_border(); vc.alignment=_align('right')
        vc.font=_font(10,bold=True,color=BLU)
        if fmt=='currency': vc.number_format='#,##0.00'
    ws.column_dimensions['A'].width=30; ws.column_dimensions['B'].width=20


def export_sales_report(sales_data, items_by_sale, shop_name='My Shop',
                        start_date=None, end_date=None, output_path=None,
                        currency='KES', products_data=None,
                        debt_summary=None, aging_report=None,
                        debt_invoices=None, debt_payments=None):
    """
    Multi-sheet Excel report.
    Sheet 1 – Sales Summary    (transaction-level)
    Sheet 2 – Line Items       (product name, qty, unit price, total, date, cashier)
    Sheet 3 – Top Products     (aggregated + bar chart)
    Sheet 4 – Payment Methods
    Sheet 5 – Stock / Inventory (current stock, cost, value, low-stock flag)
    Sheet 6 – Debt Management (summary, aging, invoices, payments)
    """
    wb = Workbook()
    dr = f"{start_date or '—'} to {end_date or str(date.today())}"

    # ── Pre-compute totals ─────────────────────────────────────────────────────
    total_rev   = sum(s.get('total', 0) for s in sales_data)
    total_count = len(sales_data)
    avg_sale    = total_rev / total_count if total_count else 0
    total_disc  = sum(s.get('discount', 0) for s in sales_data)
    total_tax   = sum(s.get('tax', 0) for s in sales_data)

    # Build flat line-items list eagerly (used by sheets 2+3)
    line_items = []
    for sale in sales_data:
        sid = sale.get('id') or sale.get('sale_id')
        items = items_by_sale.get(sid, [])
        if not items and 'items' in sale:
            items = sale['items']
        for item in items:
            line_items.append({
                'receipt':      sale.get('receipt_number', ''),
                'date':         (sale.get('created_at', '') or '')[:19],
                'cashier':      sale.get('cashier_name', ''),
                'product_name': item.get('product_name', ''),
                'sku':          item.get('sku', '') or '',
                'quantity':     float(item.get('quantity', 0)),
                'unit_price':   float(item.get('unit_price', 0)),
                'discount':     float(item.get('discount', 0)),
                'total':        float(item.get('total', 0)),
                'payment':      sale.get('payment_method', '').upper(),
            })

    # ══════════════════════════════════════════════════════════════════════════
    # SHEET 1 – Sales Summary
    # ══════════════════════════════════════════════════════════════════════════
    ws1 = wb.active; ws1.title = "Sales Summary"
    ws1.sheet_view.showGridLines = False
    ws1.freeze_panes = 'A4'
    _brand_header(ws1, shop_name, "Sales Report", dr, ncols=12)

    _kpi_block(ws1, [
        ('Total Transactions', total_count, ''),
        (f'Total Revenue ({currency})', total_rev, 'currency'),
        (f'Average Sale ({currency})', avg_sale, 'currency'),
        (f'Total Discounts ({currency})', total_disc, 'currency'),
        (f'Total Tax ({currency})', total_tax, 'currency'),
    ], start_row=4, currency=currency)

    SR = 11
    ws1.cell(SR-1, 1).value = "TRANSACTION DETAILS"
    ws1.cell(SR-1, 1).font  = _font(12, bold=True, color=M)

    hdrs1 = ['#','Receipt No.','Date & Time','Cashier','Items',
             f'Subtotal ({currency})', f'Discount ({currency})',
             f'Tax ({currency})', f'Original ({currency})',
             f'Rounding ({currency})', f'Final ({currency})','Payment']
    wds1  = [5, 18, 20, 16, 6, 16, 14, 12, 14, 12, 16, 12]
    for col,(h,w) in enumerate(zip(hdrs1, wds1), 1):
        _hdr_cell(ws1, SR, col, h, w, get_column_letter(col))

    for idx, sale in enumerate(sales_data):
        r = SR+1+idx; alt = idx%2==1
        sid  = sale.get('id') or sale.get('sale_id')
        n_items = len(items_by_sale.get(sid, sale.get('items', [])))
        adj = float(sale.get('cash_rounding_adj') or 0)
        tot = float(sale.get('total',0))
        orig = float(sale.get('original_total') or 0)
        if orig <= 0:
            orig = tot - adj
        vals = [idx+1, sale.get('receipt_number',''), (sale.get('created_at','') or '')[:19],
                sale.get('cashier_name',''), n_items or sale.get('item_count',''),
                float(sale.get('subtotal', sale.get('total',0))),
                float(sale.get('discount',0)), float(sale.get('tax',0)),
                orig, adj, tot, sale.get('payment_method','').upper()]
        for col, val in enumerate(vals, 1):
            c = ws1.cell(r, col, val)
            c.border    = _border()
            c.alignment = _align('right' if isinstance(val,(int,float)) else 'left')
            if alt: c.fill = _fill(ALT)
            if col in (6,7,8,9,10,11): c.number_format = f'"{currency} "#,##0.00'

    # Totals row
    TR1 = SR+1+len(sales_data)
    ws1.cell(TR1,1).value = 'TOTAL'
    for col in range(1,13):
        c = ws1.cell(TR1, col)
        c.fill = _fill(TOT_BG); c.font = _font(10,bold=True,color=TOT_FG); c.border = _border()
    if total_count:
        for col, col_letter in [(6,'F'),(7,'G'),(8,'H'),(9,'I'),(10,'J'),(11,'K')]:
            cell = ws1.cell(TR1, col)
            cell.value          = f'=SUM({col_letter}{SR+1}:{col_letter}{SR+total_count})'
            cell.number_format  = f'"{currency} "#,##0.00'
            cell.alignment      = _align('right')

    _footer(ws1, TR1+2, 10)

    # ══════════════════════════════════════════════════════════════════════════
    # SHEET 2 – Line Items (THE MISSING SHEET — product name, qty, price, etc.)
    # ══════════════════════════════════════════════════════════════════════════
    ws2 = wb.create_sheet("Line Items")
    ws2.sheet_view.showGridLines = False
    ws2.freeze_panes = 'A4'
    _brand_header(ws2, shop_name, "Sales Line Items — Full Detail", dr, ncols=10)

    ws2.cell(3,1).value = "Every individual product sold in the selected period"
    ws2.cell(3,1).font  = _font(10, italic=True, color=G)

    hdrs2 = ['Receipt No.','Date & Time','Cashier','Product Name','SKU',
             'Qty', f'Unit Price ({currency})', f'Discount ({currency})', f'Total ({currency})','Payment']
    wds2  = [18, 20, 16, 30, 14, 8, 18, 14, 18, 12]
    for col,(h,w) in enumerate(zip(hdrs2,wds2), 1):
        _hdr_cell(ws2, 4, col, h, w, get_column_letter(col))

    for idx, li in enumerate(line_items):
        r = 5+idx; alt = idx%2==1
        vals = [li['receipt'], li['date'], li['cashier'], li['product_name'], li['sku'],
                li['quantity'], li['unit_price'], li['discount'], li['total'], li['payment']]
        for col, val in enumerate(vals, 1):
            c = ws2.cell(r, col, val)
            c.border    = _border()
            c.alignment = _align('right' if isinstance(val,(int,float)) and col>5 else
                                 'center' if col==6 else 'left')
            if alt: c.fill = _fill(ALT)
            if col in (7,8,9): c.number_format = f'"{currency} "#,##0.00'
            if col==6:         c.number_format  = '#,##0.##'

    # Totals
    TR2 = 5+len(line_items)
    ws2.cell(TR2,1).value='TOTAL'
    for col in range(1,11):
        c=ws2.cell(TR2,col); c.fill=_fill(TOT_BG); c.font=_font(10,bold=True); c.border=_border()
    if line_items:
        n = len(line_items)
        for col,cl in [(6,'F'),(7,'G'),(8,'H'),(9,'I')]:
            cell=ws2.cell(TR2,col)
            cell.value         = f'=SUM({cl}5:{cl}{4+n})'
            cell.number_format = '#,##0.00' if col==6 else f'"{currency} "#,##0.00'
            cell.alignment     = _align('right')

    _footer(ws2, TR2+2, 10)

    # ══════════════════════════════════════════════════════════════════════════
    # SHEET 3 – Top Products (aggregated)
    # ══════════════════════════════════════════════════════════════════════════
    ws3 = wb.create_sheet("Top Products")
    ws3.sheet_view.showGridLines = False
    _brand_header(ws3, shop_name, "Product Performance", dr, ncols=8)

    prod_stats = {}
    for li in line_items:
        name = li['product_name'] or 'Unknown'
        prod_stats.setdefault(name, {'qty':0,'revenue':0,'transactions':0})
        prod_stats[name]['qty']          += li['quantity']
        prod_stats[name]['revenue']      += li['total']
        prod_stats[name]['transactions'] += 1

    sorted_prods = sorted(prod_stats.items(), key=lambda x: x[1]['revenue'], reverse=True)

    hdrs3 = ['Rank','Product Name','Units Sold','Transactions',
             f'Revenue ({currency})','% of Total','Avg Unit Price']
    wds3  = [6, 32, 14, 14, 18, 14, 18]
    for col,(h,w) in enumerate(zip(hdrs3,wds3),1):
        _hdr_cell(ws3, 4, col, h, w, get_column_letter(col))

    grand_rev = sum(v['revenue'] for v in prod_stats.values()) or 1
    for rank,(name,st) in enumerate(sorted_prods,1):
        r=4+rank; alt=rank%2==0
        avg_up = st['revenue']/st['qty'] if st['qty'] else 0
        vals=[rank, name, st['qty'], st['transactions'],
              st['revenue'], st['revenue']/grand_rev, avg_up]
        for col,val in enumerate(vals,1):
            c=ws3.cell(r,col,val); c.border=_border()
            if alt: c.fill=_fill(ALT)
            c.alignment=_align('right' if col not in(1,2) else
                               'center' if col==1 else 'left')
            if col==5: c.number_format=f'"{currency} "#,##0.00'
            if col==6: c.number_format='0.0%'
            if col==7: c.number_format=f'"{currency} "#,##0.00'

    # Totals row
    TR3=4+len(sorted_prods)+1
    ws3.cell(TR3,2).value='GRAND TOTAL'; ws3.cell(TR3,2).font=_font(10,bold=True)
    ws3.cell(TR3,5).value=grand_rev; ws3.cell(TR3,5).number_format=f'"{currency} "#,##0.00'
    ws3.cell(TR3,5).font=_font(10,bold=True,color=GRN)
    for col in range(1,8):
        ws3.cell(TR3,col).fill=_fill(TOT_BG); ws3.cell(TR3,col).border=_border()

    # Bar chart
    if sorted_prods:
        chart=BarChart(); chart.type="bar"
        chart.title="Revenue by Product"; chart.y_axis.title=f"Revenue ({currency})"
        top_n=min(10,len(sorted_prods))
        data_ref=Reference(ws3,min_col=5,min_row=4,max_row=4+top_n)
        cats_ref=Reference(ws3,min_col=2,min_row=5,max_row=4+top_n)
        chart.add_data(data_ref,titles_from_data=True); chart.set_categories(cats_ref)
        chart.height=14; chart.width=24; ws3.add_chart(chart,"I5")

    _footer(ws3, TR3+2, 8)

    # ══════════════════════════════════════════════════════════════════════════
    # SHEET 4 – Payment Methods
    # ══════════════════════════════════════════════════════════════════════════
    ws4 = wb.create_sheet("Payment Methods")
    ws4.sheet_view.showGridLines = False
    _brand_header(ws4, shop_name, "Payment Method Breakdown", dr, ncols=5)

    pay_stats = {}
    for sale in sales_data:
        pm = (sale.get('payment_method') or 'cash').upper()
        pay_stats.setdefault(pm, {'count':0,'total':0})
        pay_stats[pm]['count'] += 1
        pay_stats[pm]['total'] += float(sale.get('total',0))

    hdrs4=['Payment Method','Transactions','% Transactions',f'Revenue ({currency})','% Revenue']
    wds4 =[22, 16, 18, 22, 16]
    for col,(h,w) in enumerate(zip(hdrs4,wds4),1):
        _hdr_cell(ws4, 4, col, h, w, get_column_letter(col))

    grand_count=sum(v['count'] for v in pay_stats.values()) or 1
    grand_pay  =sum(v['total'] for v in pay_stats.values()) or 1
    for idx,(pm,st) in enumerate(sorted(pay_stats.items(),key=lambda x:x[1]['total'],reverse=True)):
        r=5+idx; alt=idx%2==1
        vals=[pm, st['count'], st['count']/grand_count,
              st['total'], st['total']/grand_pay]
        for col,val in enumerate(vals,1):
            c=ws4.cell(r,col,val); c.border=_border()
            if alt: c.fill=_fill(ALT)
            c.alignment=_align('right' if col>1 else 'left')
            if col in(3,5): c.number_format='0.0%'
            if col==4:      c.number_format=f'"{currency} "#,##0.00'

    _footer(ws4, 6+len(pay_stats), 5)

    # ══════════════════════════════════════════════════════════════════════════
    # SHEET 5 – Stock / Inventory Snapshot
    # ══════════════════════════════════════════════════════════════════════════
    ws5 = wb.create_sheet("Stock & Inventory")
    ws5.sheet_view.showGridLines = False
    ws5.freeze_panes = 'A5'
    _brand_header(ws5, shop_name, "Stock & Inventory Snapshot",
                  f"As at {datetime.now().strftime('%Y-%m-%d %H:%M')}", ncols=10)

    ws5.cell(3, 1).value = (
        "Current stock levels at time of export  —  "
        "RED = below minimum stock threshold (reorder needed)"
    )
    ws5.cell(3, 1).font      = _font(10, italic=True, color=G)
    ws5.cell(3, 1).alignment = _align('left')

    hdrs5 = ['#', 'Product Name', 'SKU', 'Category',
             f'Selling Price ({currency})', f'Cost Price ({currency})',
             'Current Stock', 'Min Stock',
             f'Stock Value ({currency})', 'Status']
    wds5  = [5, 30, 14, 16, 18, 16, 14, 12, 18, 14]
    for col, (h, w) in enumerate(zip(hdrs5, wds5), 1):
        _hdr_cell(ws5, 4, col, h, w, get_column_letter(col))

    # Colours for status column
    LOW_FILL  = _fill('FFEBEE')   # light red  — below minimum
    LOW_FONT  = _font(10, bold=True, color=RED)
    OK_FILL   = _fill('E8F5E9')   # light green — healthy stock
    OK_FONT   = _font(10, bold=True, color=GRN)
    ZERO_FILL = _fill('FFF3E0')   # amber — out of stock
    ZERO_FONT = _font(10, bold=True, color='E65100')

    products = products_data or []
    # Sort: out-of-stock first, then low-stock, then alphabetical
    def _sort_key(p):
        stk = int(p.get('stock', 0) or 0)
        mn  = int(p.get('min_stock', 5) or 5)
        if stk == 0:   return (0, p.get('name', ''))
        if stk <= mn:  return (1, p.get('name', ''))
        return              (2, p.get('name', ''))

    products_sorted = sorted(products, key=_sort_key)

    total_stock_value = 0.0
    low_count  = 0
    zero_count = 0

    for idx, prod in enumerate(products_sorted):
        r   = 5 + idx
        alt = idx % 2 == 1

        name      = prod.get('name', '')
        sku       = prod.get('sku', '') or ''
        category  = prod.get('category', '') or ''
        price     = float(prod.get('price', 0) or 0)
        cost      = float(prod.get('cost_price', 0) or 0)
        stock     = int(prod.get('stock', 0) or 0)
        min_stock = int(prod.get('min_stock', 5) or 5)
        stk_value = cost * stock if cost else price * stock * 0.6
        total_stock_value += stk_value

        if stock == 0:
            status     = 'OUT OF STOCK'
            row_fill   = ZERO_FILL
            stat_font  = ZERO_FONT
            zero_count += 1
        elif stock <= min_stock:
            status     = 'LOW STOCK'
            row_fill   = LOW_FILL
            stat_font  = LOW_FONT
            low_count  += 1
        else:
            status     = 'OK'
            row_fill   = OK_FILL if not alt else _fill(ALT)
            stat_font  = OK_FONT

        vals = [idx + 1, name, sku, category, price, cost,
                stock, min_stock, stk_value, status]

        for col, val in enumerate(vals, 1):
            c = ws5.cell(r, col, val)
            c.border    = _border()
            c.alignment = _align(
                'right' if col in (5, 6, 7, 8, 9) else
                'center' if col in (1,) else 'left')
            # Row background
            if stock == 0:
                c.fill = ZERO_FILL
            elif stock <= min_stock:
                c.fill = LOW_FILL
            elif alt:
                c.fill = _fill(ALT)
            # Number formats
            if col in (5, 6):   c.number_format = f'"{currency} "#,##0.00'
            if col == 9:        c.number_format = f'"{currency} "#,##0.00'
            if col in (7, 8):   c.number_format = '#,##0'
            # Status column special font
            if col == 10:       c.font = stat_font

    # ── Summary / totals row ──────────────────────────────────────────────────
    n_prods = len(products_sorted)
    TR5     = 5 + n_prods

    ws5.cell(TR5, 1).value = 'TOTALS'
    ws5.cell(TR5, 2).value = f'{n_prods} products'
    ws5.cell(TR5, 9).value = total_stock_value
    ws5.cell(TR5, 9).number_format = f'"{currency} "#,##0.00'
    ws5.cell(TR5, 10).value = (
        f'{zero_count} out-of-stock  ·  {low_count} low stock'
    )
    for col in range(1, 11):
        c = ws5.cell(TR5, col)
        c.fill   = _fill(TOT_BG)
        c.font   = _font(10, bold=True, color=TOT_FG)
        c.border = _border()

    # ── KPI summary block above table ─────────────────────────────────────────
    # Insert 2 rows of KPI summary at the bottom for quick reading
    KPI_ROW = TR5 + 2
    ws5.cell(KPI_ROW,     1).value = 'INVENTORY SUMMARY'
    ws5.cell(KPI_ROW,     1).font  = _font(12, bold=True, color=M)
    kpis = [
        ('Total Products',        n_prods,            ''),
        ('Out of Stock',          zero_count,         ''),
        ('Low Stock (need reorder)', low_count,        ''),
        (f'Total Stock Value ({currency})', total_stock_value, 'currency'),
    ]
    for i, (lbl, val, fmt) in enumerate(kpis):
        r = KPI_ROW + 1 + i
        lc = ws5.cell(r, 1, lbl)
        lc.font   = _font(10, bold=True); lc.fill = _fill(ALT)
        lc.border = _border(); lc.alignment = _align()
        vc = ws5.cell(r, 2, val)
        vc.border = _border(); vc.alignment = _align('right')
        vc.font   = _font(10, bold=True, color=RED if (lbl.startswith('Out') and val > 0)
                           else GRN if lbl.startswith('Total Prod') else BLU)
        if fmt == 'currency': vc.number_format = f'"{currency} "#,##0.00'

    _footer(ws5, KPI_ROW + len(kpis) + 2, 10)

    # ══════════════════════════════════════════════════════════════════════════
    # SHEET 6 – Debt Management
    # ══════════════════════════════════════════════════════════════════════════
    ws6 = wb.create_sheet("Debt Management")
    ws6.sheet_view.showGridLines = False
    ws6.freeze_panes = 'A13'
    _brand_header(ws6, shop_name, "Debt Management Report", dr, ncols=9)

    debt_summary = debt_summary or {}
    aging_report = aging_report or {}
    debt_invoices = debt_invoices or []
    debt_payments = debt_payments or []

    outstanding = float((debt_summary.get('outstanding') or {}).get('total', 0) or 0)
    overdue = float((debt_summary.get('overdue') or {}).get('total', 0) or 0)
    collected = float((debt_summary.get('today_collected') or {}).get('total', 0) or 0)
    customers_with_debt = int(debt_summary.get('customers_with_debt') or 0)

    _kpi_block(ws6, [
        (f'Outstanding Debt ({currency})', outstanding, 'currency'),
        (f'Overdue Debt ({currency})', overdue, 'currency'),
        (f'Collected Today ({currency})', collected, 'currency'),
        ('Customers with Debt', customers_with_debt, ''),
        ('Open Invoices', len([i for i in debt_invoices if i.get('status') not in ('paid', 'cancelled')]), ''),
    ], start_row=4, currency=currency)

    ws6.cell(4, 4).value = "AGING BREAKDOWN"
    ws6.cell(4, 4).font = _font(12, bold=True, color=M)
    aging_rows = [
        ('Current', aging_report.get('current', {})),
        ('1-30 Days', aging_report.get('1_30', {})),
        ('31-60 Days', aging_report.get('31_60', {})),
        ('61-90 Days', aging_report.get('61_90', {})),
        ('90+ Days', aging_report.get('over_90', {})),
    ]
    _hdr_cell(ws6, 5, 4, "Bucket", 14, 'D')
    _hdr_cell(ws6, 5, 5, "Invoices", 10, 'E')
    _hdr_cell(ws6, 5, 6, f"Amount ({currency})", 16, 'F')
    for i, (label, data) in enumerate(aging_rows):
        r = 6 + i
        cnt = int((data or {}).get('count', 0) or 0)
        total = float((data or {}).get('total', 0) or 0)
        vals = (label, cnt, total)
        for cidx, val in enumerate(vals, 4):
            c = ws6.cell(r, cidx, val)
            c.border = _border()
            c.alignment = _align('right' if cidx in (5, 6) else 'left')
            if i % 2 == 1:
                c.fill = _fill(ALT)
            if cidx == 6:
                c.number_format = f'"{currency} "#,##0.00'

    ws6.cell(11, 1).value = "OPEN / RECENT DEBT INVOICES"
    ws6.cell(11, 1).font = _font(12, bold=True, color=M)
    hdrs6 = ['Invoice No.', 'Customer', f'Outstanding ({currency})', 'Status', 'Due Date', 'Created']
    wds6 = [18, 24, 18, 12, 14, 20]
    for col, (h, w) in enumerate(zip(hdrs6, wds6), 1):
        _hdr_cell(ws6, 12, col, h, w, get_column_letter(col))

    inv_rows = sorted(
        debt_invoices,
        key=lambda x: x.get('created_at', ''),
        reverse=True
    )[:30]
    for i, inv in enumerate(inv_rows):
        r = 13 + i
        vals = [
            inv.get('invoice_number', ''),
            inv.get('customer_name', ''),
            float(inv.get('balance', 0) or 0),
            (inv.get('status', '') or '').upper(),
            inv.get('due_date') or '',
            (inv.get('created_at', '') or '')[:19],
        ]
        for col, val in enumerate(vals, 1):
            c = ws6.cell(r, col, val)
            c.border = _border()
            c.alignment = _align('right' if col == 3 else 'left')
            if i % 2 == 1:
                c.fill = _fill(ALT)
            if col == 3:
                c.number_format = f'"{currency} "#,##0.00'

    pay_start = 15 + len(inv_rows)
    ws6.cell(pay_start, 1).value = "RECENT DEBT PAYMENTS"
    ws6.cell(pay_start, 1).font = _font(12, bold=True, color=M)
    pay_hdrs = ['Receipt', 'Customer', f'Amount ({currency})', 'Method', 'Date']
    pay_wds = [18, 24, 18, 14, 20]
    for col, (h, w) in enumerate(zip(pay_hdrs, pay_wds), 1):
        _hdr_cell(ws6, pay_start + 1, col, h, w, get_column_letter(col))

    pay_rows = sorted(
        debt_payments,
        key=lambda x: x.get('created_at', ''),
        reverse=True
    )[:30]
    for i, pay in enumerate(pay_rows):
        r = pay_start + 2 + i
        vals = [
            pay.get('payment_receipt', ''),
            pay.get('customer_name', ''),
            float(pay.get('amount', 0) or 0),
            (pay.get('payment_method', '') or '').upper(),
            (pay.get('created_at', '') or '')[:19],
        ]
        for col, val in enumerate(vals, 1):
            c = ws6.cell(r, col, val)
            c.border = _border()
            c.alignment = _align('right' if col == 3 else 'left')
            if i % 2 == 1:
                c.fill = _fill(ALT)
            if col == 3:
                c.number_format = f'"{currency} "#,##0.00'

    _footer(ws6, pay_start + 3 + len(pay_rows), 9)

    # ── Save ──────────────────────────────────────────────────────────────────
    if output_path is None:
        output_path = os.path.join(
            (os.path.dirname(sys.executable) if getattr(sys, 'frozen', False)
             else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            'exports',
            f"sales_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        )
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    wb.save(output_path)
    return output_path


def _footer(ws, row, ncols):
    end = get_column_letter(ncols)
    ws.merge_cells(f'A{row}:{end}{row}')
    c = ws[f'A{row}']
    c.value     = f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}  |  Powered by MugoByte Technologies  |  mugobyte.com"
    c.font      = _font(9, italic=True, color=G)
    c.alignment = _align('center')
