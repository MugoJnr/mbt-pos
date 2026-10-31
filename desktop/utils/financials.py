"""One set of shop figures for the till and the web dashboard.

Sales are dated by sale_date, otherwise the created date.
Collections are dated by when the money was received.
Outstanding debt and inventory value are the current balances.
A repayment is not a new sale. A reversed repayment is not money collected.
Profit uses the FIFO cost recorded on the sale. Lines with no cost record
are reported as uncosted and are not given an invented profit.
"""
from __future__ import annotations

from datetime import datetime


def money(value) -> float:
    return round(float(value or 0), 2)


def sale_day_sql(alias: str = "") -> str:
    prefix = f"{alias}." if alias else ""
    return f"COALESCE(NULLIF({prefix}sale_date,''), date({prefix}created_at))"


def compute_financials(db, start: str, end: str) -> dict:
    start = str(start or "")[:10]
    end = str(end or start)[:10]
    if end < start:
        start, end = end, start
    day = sale_day_sql()
    sales = [dict(row) for row in db.execute(
        f"""SELECT id, total, amount_paid, change_amount, payment_method,
                  payment_tenders, status
           FROM sales
           WHERE {day} BETWEEN ? AND ?
             AND status IN ('completed', 'return')""",
        (start, end),
    ).fetchall()]
    from desktop.utils.payment_tenders import collected_from_sales
    tender = collected_from_sales(sales)
    total_sales = money(sum(float(row.get("total") or 0) for row in sales))
    completed_ids = [int(row["id"]) for row in sales if (row.get("status") or "") == "completed"]

    later_by_sale = {}
    later_in_period = []
    try:
        later_rows = db.execute(
            """SELECT di.sale_id, dp.amount, dp.payment_method, date(dp.created_at) AS paid_on
               FROM debt_payments dp
               JOIN debt_invoices di ON di.id = dp.invoice_id
               WHERE COALESCE(dp.reversed,0)=0
                 AND COALESCE(dp.notes,'') NOT LIKE 'Initial payment%'"""
        ).fetchall()
    except Exception:
        later_rows = []
    for row in later_rows:
        sale_id = row["sale_id"] if hasattr(row, "keys") else row[0]
        amount = float((row["amount"] if hasattr(row, "keys") else row[1]) or 0)
        method = (row["payment_method"] if hasattr(row, "keys") else row[2]) or ""
        paid_on = str((row["paid_on"] if hasattr(row, "keys") else row[3]) or "")[:10]
        if sale_id:
            later_by_sale.setdefault(int(sale_id), 0.0)
            later_by_sale[int(sale_id)] = money(later_by_sale[int(sale_id)] + amount)
        if start <= paid_on <= end:
            later_in_period.append((amount, method))

    paid_sales = 0.0
    new_credit = 0.0
    sale_paid = {}
    for row in sales:
        if (row.get("status") or "") != "completed":
            continue
        value = money(row.get("total"))
        if value <= 0:
            continue
        kept = money(collected_from_sales([row]).get("collected"))
        paid = money(min(value, kept + later_by_sale.get(int(row["id"]), 0.0)))
        sale_paid[int(row["id"])] = paid
        paid_sales = money(paid_sales + paid)
        new_credit = money(new_credit + max(0.0, value - paid))

    repayments = money(sum(amount for amount, _method in later_in_period))
    collections = money(float(tender.get("collected") or 0) + repayments)

    profit = _profit_allocation(db, start, end, sale_paid)
    expenses, expenses_known = _expenses(db, start, end)
    net = None
    if expenses_known and profit.get("uncosted_lines", 0) == 0:
        net = money(profit["gross_profit"] - expenses)
    elif expenses_known:
        net = None

    outstanding = _outstanding(db)
    inventory = _inventory(db)
    supplier = _supplier_figures(db, start, end)
    return {
        "period_start": start,
        "period_end": end,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "total_sales": total_sales,
        "paid_sales": paid_sales,
        "new_credit": new_credit,
        "total_collected": collections,
        "debt_repayments": repayments,
        "cash_collected": money(tender.get("cash_collected")),
        "mpesa_collected": money(tender.get("mpesa_collected")),
        "card_collected": money(tender.get("card_collected")),
        "bank_collected": money(tender.get("bank_collected")),
        "gross_profit": profit["gross_profit"],
        "realized_gross_profit": profit["realized_gross_profit"],
        "unrealized_gross_profit": profit["unrealized_gross_profit"],
        "cogs": profit["cogs"],
        "uncosted_sales": profit["uncosted_revenue"],
        "uncosted_lines": profit["uncosted_lines"],
        "profit_note": profit["note"],
        "expenses": expenses,
        "expenses_known": expenses_known,
        "net_operating_result": net,
        "outstanding_debt": outstanding["total"],
        "customers_with_debt": outstanding["customers"],
        "overdue_debt": outstanding["overdue"],
        "supplier_outstanding": supplier["outstanding"],
        "supplier_overdue": supplier["overdue_amount"],
        "supplier_invoiced": supplier["invoiced_period"],
        "supplier_paid": supplier["paid_period"],
        "inventory_cost_value": inventory["cost_value"],
        "inventory_retail_value": inventory["retail_value"],
        "product_count": inventory["products"],
        "stock_units": inventory["units"],
        "low_stock": inventory["low_stock"],
        "out_of_stock": inventory["out_of_stock"],
        "completed_sale_count": len(completed_ids),
        "definitions": {
            "total_sales": "Valid sales in the period, including credit. Repayments are not sales.",
            "paid_sales": "Amount paid against those sales, including later repayments of them.",
            "total_collected": "Money received in the period, including repayments of older debts.",
            "outstanding_debt": "Current unpaid balances. This is not rebuilt for a past date.",
            "gross_profit": "Net sales minus the cost recorded when the goods were sold.",
        },
    }


def management_view(role: str) -> bool:
    return (role or "").strip().lower() in ("viewer", "manager", "admin", "superadmin")


def public_financials(figures: dict, role: str) -> dict:
    """Cashiers receive the day's sales total and nothing managerial."""
    if management_view(role):
        return figures
    return {
        "period_start": figures.get("period_start"),
        "period_end": figures.get("period_end"),
        "updated_at": figures.get("updated_at"),
        "total_sales": figures.get("total_sales"),
        "total_transactions": figures.get("completed_sale_count"),
        "cashier_scope": "one_day",
    }


def _profit_allocation(db, start: str, end: str, sale_paid: dict) -> dict:
    from desktop.utils.stock_layers import ensure_cost_layers
    try:
        ensure_cost_layers(db)
    except Exception:
        return {
            "gross_profit": 0.0, "realized_gross_profit": 0.0,
            "unrealized_gross_profit": 0.0, "cogs": 0.0,
            "uncosted_revenue": 0.0, "uncosted_lines": 0,
            "note": "Cost records are not available, so profit is not shown.",
        }
    day = sale_day_sql("s")
    try:
        rows = db.execute(
            f"""SELECT s.id, s.total,
                      CASE WHEN COALESCE(si.quantity,0)=0 THEN 0
                           ELSE si.total * (COALESCE(si.quantity,0) - COALESCE(si.returned_qty,0))
                                / si.quantity END AS net_total,
                      (SELECT COUNT(*) FROM cost_layer_uses u
                       WHERE u.sale_id=si.sale_id AND u.product_id=si.product_id
                         AND COALESCE(u.reversed,0)=0) AS uses,
                      (SELECT COALESCE(SUM(u.quantity * u.unit_cost),0) FROM cost_layer_uses u
                       WHERE u.sale_id=si.sale_id AND u.product_id=si.product_id
                         AND COALESCE(u.reversed,0)=0) AS cogs
               FROM sale_items si
               JOIN sales s ON s.id=si.sale_id
               WHERE {day} BETWEEN ? AND ?
                 AND COALESCE(s.status,'completed')='completed'""",
            (start, end),
        ).fetchall()
    except Exception:
        rows = []
    by_sale = {}
    uncosted = 0.0
    uncosted_lines = 0
    for row in rows:
        sale_id = int(row[0])
        net = float(row[2] or 0)
        uses = int(row[3] or 0)
        cogs = float(row[4] or 0)
        bucket = by_sale.setdefault(sale_id, {"revenue": 0.0, "cogs": 0.0, "costed": False})
        if uses > 0:
            bucket["revenue"] += net
            bucket["cogs"] += cogs
            bucket["costed"] = True
        else:
            uncosted += net
            uncosted_lines += 1
    gross = realized = 0.0
    cogs_total = 0.0
    for sale_id, bucket in by_sale.items():
        if not bucket["costed"]:
            continue
        profit = money(bucket["revenue"] - bucket["cogs"])
        revenue = money(bucket["revenue"])
        paid = money(sale_paid.get(sale_id, 0.0))
        ratio = 0.0 if revenue <= 0 else min(1.0, paid / revenue)
        part = money(profit * ratio)
        gross = money(gross + profit)
        realized = money(realized + part)
        cogs_total = money(cogs_total + bucket["cogs"])
    unrealized = money(gross - realized)
    note = ""
    if uncosted_lines:
        note = (
            f"{uncosted_lines} sold line(s) have no recorded cost, "
            "so they are left out of profit."
        )
    return {
        "gross_profit": gross,
        "realized_gross_profit": realized,
        "unrealized_gross_profit": unrealized,
        "cogs": cogs_total,
        "uncosted_revenue": money(uncosted),
        "uncosted_lines": uncosted_lines,
        "note": note,
    }


def _expenses(db, start: str, end: str):
    try:
        row = db.execute(
            """SELECT COALESCE(SUM(amount),0)
               FROM expense_entries
               WHERE deleted_at IS NULL
                 AND date(expense_date) BETWEEN date(?) AND date(?)""",
            (start, end),
        ).fetchone()
    except Exception:
        return None, False
    return money(row[0] if row else 0), True


def _supplier_figures(db, start: str, end: str) -> dict:
    try:
        from desktop.utils.supplier_payables import shop_summary
        data = shop_summary(db, start, end)
        return {
            "outstanding": money(data.get("outstanding")),
            "overdue_amount": money(data.get("overdue_amount")),
            "invoiced_period": money(data.get("invoiced_period")),
            "paid_period": money(data.get("paid_period")),
        }
    except Exception:
        return {
            "outstanding": 0.0, "overdue_amount": 0.0,
            "invoiced_period": 0.0, "paid_period": 0.0,
        }


def _outstanding(db) -> dict:
    try:
        total = db.execute(
            """SELECT COALESCE(SUM(balance),0), COUNT(DISTINCT customer_id)
               FROM debt_invoices
               WHERE status NOT IN ('paid','cancelled','written_off')
                 AND COALESCE(balance,0) > 0.009"""
        ).fetchone()
        overdue = db.execute(
            """SELECT COALESCE(SUM(balance),0)
               FROM debt_invoices
               WHERE status NOT IN ('paid','cancelled','written_off')
                 AND due_date IS NOT NULL AND due_date < date('now')"""
        ).fetchone()
    except Exception:
        return {"total": 0.0, "customers": 0, "overdue": 0.0}
    return {
        "total": money(total[0] if total else 0),
        "customers": int(total[1] if total else 0),
        "overdue": money(overdue[0] if overdue else 0),
    }


def _inventory(db) -> dict:
    cost_value = 0.0
    try:
        from desktop.utils.stock_layers import ensure_cost_layers
        ensure_cost_layers(db)
        row = db.execute(
            "SELECT COALESCE(SUM(remaining_qty * unit_cost),0) FROM cost_layers"
        ).fetchone()
        cost_value = money(row[0] if row else 0)
    except Exception:
        cost_value = 0.0
    if cost_value <= 0:
        try:
            row = db.execute(
                """SELECT COALESCE(SUM(stock * COALESCE(cost_price,0)),0)
                   FROM products WHERE COALESCE(is_active,1)=1"""
            ).fetchone()
            cost_value = money(row[0] if row else 0)
        except Exception:
            cost_value = 0.0
    products = units = low = out = 0
    retail = 0.0
    try:
        stats = db.execute(
            """SELECT COUNT(*),
                      COALESCE(SUM(stock),0),
                      COALESCE(SUM(CASE WHEN stock <= COALESCE(min_stock,0) THEN 1 ELSE 0 END),0),
                      COALESCE(SUM(CASE WHEN stock <= 0 THEN 1 ELSE 0 END),0),
                      COALESCE(SUM(stock * COALESCE(price,0)),0)
               FROM products WHERE COALESCE(is_active,1)=1"""
        ).fetchone()
        products = int(stats[0] or 0)
        units = money(stats[1])
        low = int(stats[2] or 0)
        out = int(stats[3] or 0)
        retail = money(stats[4])
    except Exception:
        pass
    return {
        "cost_value": cost_value,
        "retail_value": retail,
        "products": products,
        "units": units,
        "low_stock": low,
        "out_of_stock": out,
    }
