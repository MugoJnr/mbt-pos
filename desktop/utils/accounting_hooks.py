"""
MBT POS — Accounting auto-post hooks
Posts balanced journals from sales, voids, debt payments, consumption,
stock adjustments, and related flows. Never raises into POS checkout —
callers should wrap with try/except; hooks also swallow non-critical errors
when `safe=True` (default for post-commit fallbacks).

Prefer calling inside the same DB transaction (before commit) with safe=False
so failures roll back with the business txn when desired — create_sale uses
safe logging so a journal bug never blocks checkout.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

from desktop.utils.accounting_engine import (
    D, money_float, payment_method_account, post_journal, reverse_journal,
    find_posted_entry, get_account,
)

logger = logging.getLogger(__name__)


def _safe_call(fn, *args, safe=True, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        logger.error('accounting hook failed: %s', e, exc_info=True)
        if not safe:
            raise
        return {'error': str(e), 'skipped': True}


def _sale_cogs_lines(db, sale_id: int) -> tuple[list, float]:
    """COGS from the cost recorded on this sale. A missing record posts no COGS."""
    total_cost = D(0)
    try:
        row = db.execute(
            """SELECT COALESCE(SUM(quantity * unit_cost), 0)
               FROM cost_layer_uses
               WHERE sale_id=? AND COALESCE(reversed, 0)=0""",
            (sale_id,),
        ).fetchone()
        total_cost = D(row[0] if row else 0)
    except Exception:
        total_cost = D(0)
    lines = []
    if total_cost > 0:
        lines.append({
            'account_code': '5000',
            'debit': total_cost,
            'memo': f'COGS sale #{sale_id}',
        })
        lines.append({
            'account_code': '1200',
            'credit': total_cost,
            'memo': f'Inventory out sale #{sale_id}',
        })
    return lines, money_float(total_cost)


def _tender_account_debits(sale, product_tender, change_amount, receipt_number):
    """Debit each confirmed tender to its own asset account.

    Returns None when the sale has no tender list, or when the list does not
    add up to the amount kept. The older single-bucket posting then remains.
    Cash change is taken off the cash debit so the drawer is not overstated.
    """
    from desktop.utils.payment_tenders import is_credit_method, parse_tenders
    rows = parse_tenders(sale.get('payment_tenders'))
    if not rows:
        return None
    buckets = {}
    for row in rows:
        status = str(row.get('status') or 'confirmed').strip().lower()
        method = str(row.get('method') or '').strip()
        if status != 'confirmed' or not method or is_credit_method(method):
            continue
        amount = D(row.get('amount') or 0)
        if amount <= 0:
            continue
        code = payment_method_account(method)
        buckets[code] = buckets.get(code, D(0)) + amount
    if not buckets:
        return None
    if change_amount > 0 and buckets.get('1000', D(0)) > 0:
        buckets['1000'] = buckets['1000'] - change_amount
        if buckets['1000'] <= 0:
            buckets.pop('1000', None)
    posted = sum(buckets.values(), D(0))
    if abs(posted - product_tender) > D('0.02'):
        return None
    return [
        {
            'account_code': code,
            'debit': amount,
            'memo': f'Payment {code} {receipt_number}',
        }
        for code, amount in buckets.items()
        if amount > 0
    ]


def post_sale_journal(db, sale_id: int, *, user_id=None, username='',
                      safe=True) -> dict:
    """
    Auto-post revenue + tender + COGS for a completed sale.
    Handles cash/mpesa/card/bank/credit/mixed, store credit, rounding, variance.
    """
    def _run():
        sale = db.execute("SELECT * FROM sales WHERE id=?", (sale_id,)).fetchone()
        if not sale:
            return {'error': 'Sale not found'}
        sale = dict(sale)
        if (sale.get('status') or 'completed') == 'voided':
            return {'skipped': True, 'reason': 'voided'}

        existing = find_posted_entry(db, 'sales', str(sale_id), 'sale')
        if existing:
            return {'success': True, 'journal_id': existing['id'], 'idempotent': True}

        rn = sale.get('receipt_number') or str(sale_id)
        entry_date = (
            sale.get('sale_date') or sale.get('created_at') or date.today().isoformat()
        )[:10]
        method = (sale.get('payment_method') or 'cash').strip().lower()
        original_total = D(
            sale.get('original_total') if sale.get('original_total') is not None
            else sale.get('total') or 0
        )
        rounding = D(sale.get('cash_rounding_adj') or 0)
        total = D(sale.get('total') or 0)  # payable including rounding
        amount_paid = D(sale.get('amount_paid') or 0)
        change_amount = D(sale.get('change_amount') or 0)
        credit_applied = D(sale.get('credit_applied') or 0)
        electronic_paid = D(sale.get('electronic_paid') or 0)
        # Net cash/electronic received (exclude change returned)
        net_tender = amount_paid - change_amount
        if net_tender < 0:
            net_tender = D(0)

        lines = []
        # Revenue at original product total (before rounding)
        if original_total > 0:
            lines.append({
                'account_code': '4000',
                'credit': original_total,
                'memo': f'Sales {rn}',
            })

        # Store credit applied → reduce liability
        if credit_applied > 0:
            lines.append({
                'account_code': '2100',
                'debit': credit_applied,
                'memo': f'Store credit applied {rn}',
            })

        # Cash rounding
        if rounding > 0:
            lines.append({
                'account_code': '4300',
                'credit': rounding,
                'memo': f'Cash rounding income {rn}',
            })
        elif rounding < 0:
            lines.append({
                'account_code': '6500',
                'debit': abs(rounding),
                'memo': f'Cash rounding expense {rn}',
            })

        # Payment variance (tips / transport / deposit / misc / additional payment)
        var = db.execute(
            "SELECT * FROM payment_variances WHERE sale_id=? ORDER BY id DESC LIMIT 1",
            (sale_id,)
        ).fetchone()
        tip = transport = deposit = advance = misc = additional = D(0)
        if var:
            tip = D(var['tip_amount'] or 0)
            transport = D(var['transport_amount'] or 0)
            deposit = D(var['deposit_amount'] or 0)
            advance = D(var['advance_amount'] or 0)
            misc = D(var['misc_amount'] or 0)
            if (var['handling'] or '').strip().lower() == 'additional_payment':
                additional = D(var['excess_amount'] or 0)
            # change_returned is already excluded via net_tender (change_amount)

        if tip > 0:
            lines.append({'account_code': '4200', 'credit': tip, 'memo': f'Tip {rn}'})
        if transport > 0:
            t_code = '4400' if get_account(db, '4400') else '4100'
            lines.append({'account_code': t_code, 'credit': transport,
                          'memo': f'Transport collected {rn}'})
        if deposit > 0 or advance > 0:
            dep = deposit + advance
            lines.append({
                'account_code': '2100',
                'credit': dep,
                'memo': f'Customer deposit/advance {rn}',
            })
        if misc > 0:
            lines.append({
                'account_code': '4100',
                'credit': misc,
                'memo': f'Misc variance {rn}',
            })
        if additional > 0:
            # Additional customer payment → sales/other income (internal; not on receipt)
            lines.append({
                'account_code': '4100',
                'credit': additional,
                'memo': f'Additional customer payment {rn}',
            })

        # Amount still owed on credit (AR)
        # payable after credit = total - credit_applied; AR = that - net cash tendered
        # (excluding variance extras that inflate amount_paid)
        variance_extra = tip + transport + deposit + advance + misc + additional
        # amount_paid includes variance excess; net product tender:
        product_tender = net_tender - variance_extra
        if product_tender < 0:
            product_tender = D(0)

        due_after_credit = total - credit_applied
        if due_after_credit < 0:
            due_after_credit = D(0)
        ar_amount = due_after_credit - product_tender
        if ar_amount < 0:
            # Overpay without variance record — treat residual as change already handled
            ar_amount = D(0)

        # Split tender across cash / electronic accounts for mixed payments.
        # A saved tender list is posted per method. Card must not follow M-Pesa
        # into 1010, and Airtel must not be rewritten as a cash sale.
        tender_debits = _tender_account_debits(sale, product_tender, change_amount, rn)
        if tender_debits:
            lines.extend(tender_debits)
        elif product_tender > 0:
            if electronic_paid > 0 and method in ('cash', 'mixed', 'split'):
                e_amt = min(electronic_paid, product_tender)
                c_amt = product_tender - e_amt
                # Infer electronic method from notes when possible
                e_code = '1010'
                notes = (sale.get('notes') or '').lower()
                if 'card' in notes:
                    e_code = '1030'
                elif 'bank' in notes:
                    e_code = '1020'
                if e_amt > 0:
                    lines.append({
                        'account_code': e_code,
                        'debit': e_amt,
                        'memo': f'Electronic {rn}',
                    })
                if c_amt > 0:
                    lines.append({
                        'account_code': '1000',
                        'debit': c_amt,
                        'memo': f'Cash {rn}',
                    })
            elif method in ('credit',) and product_tender <= 0:
                pass  # pure credit — AR only
            else:
                pay_code = payment_method_account(
                    'cash' if method in ('credit', 'mixed') and product_tender > 0
                    else method
                )
                if method == 'credit' and product_tender > 0:
                    pay_code = '1000'  # part payment typically cash unless noted
                    pm = method
                    # Prefer declared method for part-pay
                    if sale.get('payment_method'):
                        pm = sale['payment_method']
                        if pm not in ('credit',):
                            pay_code = payment_method_account(pm)
                lines.append({
                    'account_code': pay_code,
                    'debit': product_tender,
                    'memo': f'Payment {method} {rn}',
                })

        # Variance extras also hit cash/electronic (customer paid them)
        cash_extra = tip + transport + deposit + advance + misc + additional
        if cash_extra > 0:
            # Already included in amount_paid; if product_tender split consumed
            # only product portion, add extra debit to payment account
            extra_code = payment_method_account(
                method if method not in ('credit', 'mixed') else 'cash'
            )
            lines.append({
                'account_code': extra_code,
                'debit': cash_extra,
                'memo': f'Variance tender {rn}',
            })

        if ar_amount > 0:
            lines.append({
                'account_code': '1100',
                'debit': ar_amount,
                'memo': f'Credit sale AR {rn}',
            })

        # COGS
        cogs_lines, _ = _sale_cogs_lines(db, sale_id)
        lines.extend(cogs_lines)

        # Drop zero lines & post
        lines = [ln for ln in lines
                 if D(ln.get('debit') or 0) > 0 or D(ln.get('credit') or 0) > 0]
        if not lines:
            return {'skipped': True, 'reason': 'no amounts'}

        # Balance check — if tiny float drift, adjust via rounding expense/income
        dr = sum(D(ln.get('debit') or 0) for ln in lines)
        cr = sum(D(ln.get('credit') or 0) for ln in lines)
        diff = dr - cr
        if abs(diff) > 0 and abs(diff) <= D('0.05'):
            if diff > 0:
                lines.append({
                    'account_code': '4300',
                    'credit': abs(diff),
                    'memo': 'Balance pad',
                })
            else:
                lines.append({
                    'account_code': '6500',
                    'debit': abs(diff),
                    'memo': 'Balance pad',
                })
        elif abs(diff) > D('0.05'):
            # Rebuild safer model: Dr assets = Cr revenue+liab using totals
            logger.warning(
                'Sale journal imbalance sale_id=%s diff=%s — using simplified post',
                sale_id, diff
            )
            lines = _simplified_sale_lines(
                sale, original_total, rounding, credit_applied, product_tender,
                ar_amount, tip, transport, deposit + advance, misc + additional,
                method, rn
            )
            lines.extend(cogs_lines)

        return post_journal(
            db, lines,
            description=f'Sale {rn}',
            entry_date=entry_date,
            source_module='sales',
            source_id=str(sale_id),
            entry_type='sale',
            user_id=user_id,
            username=username,
        )

    return _safe_call(_run, safe=safe)


def post_missing_sale_journals(db, *, user_id=None, username='') -> dict:
    """Post a journal for each completed sale that does not have one.

    Idempotent. Does not change the receipt total. Cost comes only from the
    cost already recorded on the sale. Each sale is its own savepoint, so one
    failure does not keep a half-written journal or undo the others.
    """
    from desktop.utils.accounting_engine import ensure_accounting_schema
    ensure_accounting_schema(db)
    rows = db.execute(
        """SELECT id FROM sales
           WHERE COALESCE(status, 'completed')='completed'
             AND NOT EXISTS (
               SELECT 1 FROM journal_entries j
               WHERE j.source_module='sales'
                 AND j.source_id=CAST(sales.id AS TEXT)
                 AND j.entry_type='sale'
                 AND j.status='posted'
                 AND j.deleted_at IS NULL
             )
           ORDER BY id"""
    ).fetchall()
    posted = 0
    failed = 0
    for row in rows:
        sale_id = row[0]
        db.execute("SAVEPOINT sale_journal")
        result = post_sale_journal(
            db, sale_id, user_id=user_id, username=username, safe=True,
        )
        if result.get('success') and not result.get('error'):
            db.execute("RELEASE sale_journal")
            if not result.get('idempotent'):
                posted += 1
        else:
            db.execute("ROLLBACK TO sale_journal")
            db.execute("RELEASE sale_journal")
            failed += 1
            logger.error(
                'sale journal missing after repair sale_id=%s result=%s',
                sale_id, result.get('error') or result.get('reason') or 'not posted',
            )
    return {'posted': posted, 'failed': failed, 'checked': len(rows)}


def _simplified_sale_lines(sale, original_total, rounding, credit_applied,
                           product_tender, ar_amount, tip, transport, deposit,
                           misc, method, rn) -> list:
    """Fallback balanced sale journal when detailed split drifts."""
    lines = []
    if original_total > 0:
        lines.append({'account_code': '4000', 'credit': original_total, 'memo': rn})
    if rounding > 0:
        lines.append({'account_code': '4300', 'credit': rounding, 'memo': rn})
    elif rounding < 0:
        lines.append({'account_code': '6500', 'debit': abs(rounding), 'memo': rn})
    if credit_applied > 0:
        lines.append({'account_code': '2100', 'debit': credit_applied, 'memo': rn})
    if tip > 0:
        lines.append({'account_code': '4200', 'credit': tip, 'memo': rn})
    if transport > 0:
        lines.append({'account_code': '4400' if True else '4100',
                      'credit': transport, 'memo': rn})
    if deposit > 0:
        lines.append({'account_code': '2100', 'credit': deposit, 'memo': rn})
    if misc > 0:
        lines.append({'account_code': '4100', 'credit': misc, 'memo': rn})

    cash_side = product_tender + tip + transport + deposit + misc
    if cash_side > 0:
        lines.append({
            'account_code': payment_method_account(
                method if method not in ('credit',) else 'cash'),
            'debit': cash_side,
            'memo': rn,
        })
    if ar_amount > 0:
        lines.append({'account_code': '1100', 'debit': ar_amount, 'memo': rn})
    return lines


def post_return_journal(db, return_sale_id: int, *, refund_total=0, cash_refund=0,
                        debt_reduced=0, cost=0, method='cash', receipt='',
                        entry_date='', user_id=None, username='', safe=True) -> dict:
    """Reduce sales, cash or debt, and COGS for a product return or a cash refund."""
    def _run():
        existing = find_posted_entry(db, 'sales', str(return_sale_id), 'sale_return')
        if existing:
            return {'success': True, 'journal_id': existing['id'], 'idempotent': True}
        refund = D(refund_total)
        cash = D(cash_refund)
        debt = D(debt_reduced)
        cogs = D(cost)
        if refund <= 0 and cogs <= 0:
            return {'skipped': True, 'reason': 'zero'}
        lines = []
        if refund > 0:
            lines.append({
                'account_code': '4000',
                'debit': refund,
                'memo': f'Return {receipt}',
            })
        if cash > 0:
            lines.append({
                'account_code': payment_method_account(method or 'cash'),
                'credit': cash,
                'memo': f'Refund {receipt}',
            })
        if debt > 0:
            lines.append({
                'account_code': '1100',
                'credit': debt,
                'memo': f'Debt reduced {receipt}',
            })
        gap = refund - cash - debt
        if gap > D('0.009'):
            lines.append({
                'account_code': payment_method_account(method or 'cash'),
                'credit': gap,
                'memo': f'Refund balance {receipt}',
            })
        elif gap < D('-0.009'):
            lines.append({
                'account_code': '4000',
                'debit': abs(gap),
                'memo': f'Return balance {receipt}',
            })
        if cogs > 0:
            lines.append({
                'account_code': '1200',
                'debit': cogs,
                'memo': f'Inventory back {receipt}',
            })
            lines.append({
                'account_code': '5000',
                'credit': cogs,
                'memo': f'COGS reversed {receipt}',
            })
        return post_journal(
            db, lines,
            description=f'Return {receipt or return_sale_id}',
            entry_date=(entry_date or date.today().isoformat())[:10],
            source_module='sales',
            source_id=str(return_sale_id),
            entry_type='sale_return',
            user_id=user_id,
            username=username,
        )
    return _safe_call(_run, safe=safe)


def post_stock_receipt_journal(db, receipt_id: int, *, user_id=None, username='',
                               safe=True) -> dict:
    """Dr Inventory, Cr Accounts Payable for one posted goods receipt.

    A later supplier payment posts its own journal. This entry is the invoice.
    """
    def _run():
        row = db.execute(
            "SELECT * FROM stock_receipts WHERE id=?", (int(receipt_id),)
        ).fetchone()
        if not row:
            return {'error': 'Receipt not found'}
        row = dict(row)
        if str(row.get('status') or 'posted').lower() == 'reversed':
            return {'skipped': True, 'reason': 'reversed'}
        existing = find_posted_entry(db, 'stock_receipts', str(receipt_id), 'receipt')
        if existing:
            return {'success': True, 'journal_id': existing['id'], 'idempotent': True}
        total = D(row.get('grand_total') or 0)
        if total <= 0:
            return {'skipped': True, 'reason': 'no amount'}
        number = row.get('receipt_number') or str(receipt_id)
        entry_date = (row.get('effective_date') or row.get('created_at') or date.today().isoformat())[:10]
        return post_journal(
            db,
            [
                {'account_code': '1200', 'debit': total, 'memo': f'Goods received {number}'},
                {'account_code': '2000', 'credit': total, 'memo': f'Supplier invoice {number}'},
            ],
            description=f'Goods receipt {number}',
            entry_date=entry_date,
            source_module='stock_receipts',
            source_id=str(receipt_id),
            entry_type='receipt',
            user_id=user_id,
            username=username,
        )

    return _safe_call(_run, safe=safe)


def post_supplier_payment_journal(db, payment_id: int, *, amount=0, method='cash',
                                  number='', entry_date='', user_id=None,
                                  username='', safe=True) -> dict:
    """Cash leaving the shop to a supplier reduces the cash account."""
    def _run():
        existing = find_posted_entry(db, 'supplier', str(payment_id), 'supplier_payment')
        if existing:
            return {'success': True, 'journal_id': existing['id'], 'idempotent': True}
        paid = D(amount)
        if paid <= 0:
            return {'skipped': True, 'reason': 'zero'}
        label = number or str(payment_id)
        return post_journal(
            db,
            [
                {'account_code': '2000', 'debit': paid, 'memo': f'Supplier payment {label}'},
                {
                    'account_code': payment_method_account(method or 'cash'),
                    'credit': paid,
                    'memo': f'Supplier payment {label}',
                },
            ],
            description=f'Supplier payment {label}',
            entry_date=(entry_date or date.today().isoformat())[:10],
            source_module='supplier',
            source_id=str(payment_id),
            entry_type='supplier_payment',
            user_id=user_id,
            username=username,
        )
    return _safe_call(_run, safe=safe)


def reverse_sale_journal(db, sale_id: int, *, reason='', user_id=None,
                         username='', safe=True) -> dict:
    def _run():
        existing = find_posted_entry(db, 'sales', str(sale_id), 'sale')
        if not existing:
            return {'skipped': True, 'reason': 'no sale journal'}
        return reverse_journal(
            db, existing['id'],
            reason=reason or 'Sale voided',
            user_id=user_id,
            username=username,
            source_module='sales',
            source_id=str(sale_id),
            entry_type='sale_void',
        )
    return _safe_call(_run, safe=safe)


def post_debt_payment_journal(db, payment_id: int = None, *,
                              invoice_id=None, amount=None,
                              payment_method='cash', payment_receipt='',
                              user_id=None, username='', entry_date=None, safe=True) -> dict:
    """Dr Cash/M-Pesa … Cr Accounts Receivable."""
    def _run():
        src_id = str(payment_id or payment_receipt or f'{invoice_id}:{amount}')
        existing = find_posted_entry(db, 'debt', src_id, 'debt_payment')
        if existing:
            return {'success': True, 'journal_id': existing['id'], 'idempotent': True}
        amt = D(amount or 0)
        if amt <= 0:
            return {'skipped': True, 'reason': 'zero'}
        pay_code = payment_method_account(payment_method)
        return post_journal(
            db,
            [
                {'account_code': pay_code, 'debit': amt,
                 'memo': f'Debt payment {payment_receipt}'},
                {'account_code': '1100', 'credit': amt,
                 'memo': f'AR collection inv={invoice_id}'},
            ],
            description=f'Debt payment {payment_receipt or src_id}',
            entry_date=(entry_date or date.today().isoformat())[:10],
            source_module='debt',
            source_id=src_id,
            entry_type='debt_payment',
            user_id=user_id,
            username=username,
        )
    return _safe_call(_run, safe=safe)


_CONSUMPTION_BOOKS = {
    '6100': 'Internal consumption',
    '6200': 'Inventory shrinkage',
    '6300': 'Inventory expiry',
    '3300': 'Owner drawings',
}


def consumption_debit_account(reason: str) -> str:
    """Staff and shop use stay an operating cost. Damage, expiry, and owner drawings do not.

    The chart's expiry account is 6300 Inventory Expiry. Wastage and damage
    stay on 6200 Inventory Shrinkage. There is no separate wastage account.
    """
    text = (reason or '').lower()
    if any(word in text for word in ('owner', 'drawing', 'personal use')):
        return '3300'
    if 'expir' in text:
        return '6300'
    if any(word in text for word in ('damage', 'wastage', 'waste', 'spoil', 'broken', 'shrink')):
        return '6200'
    return '6100'


def adjustment_debit_account(reason: str) -> str:
    """Stock-adjustment write-downs. Internal use, samples, and staff stay on 6100.

    Expiry posts to 6300 (the chart's expiry account). Wastage posts to 6200.
    Owner consumption posts to 3300. A write-down with no recognised reason
    stays on 6200 Inventory Shrinkage.
    """
    text = (reason or '').lower()
    if any(word in text for word in ('owner', 'drawing', 'personal')):
        return '3300'
    if 'expir' in text:
        return '6300'
    if any(word in text for word in ('internal', 'staff', 'sample', 'consumption')):
        return '6100'
    if any(word in text for word in ('damage', 'wastage', 'waste', 'spoil', 'broken', 'shrink')):
        return '6200'
    if any(word in text for word in ('use', 'used')):
        return '6100'
    return '6200'


def consumption_books_label(reason: str) -> str:
    code = consumption_debit_account(reason)
    return f"{code} {_CONSUMPTION_BOOKS[code]}"


def post_consumption_journal(db, consumption_id: int, *, user_id=None,
                             username='', safe=True) -> dict:
    """Dr the account that matches the reason, Cr Inventory. Not every use is an expense."""
    def _run():
        from desktop.utils.accounting_engine import seed_chart_of_accounts
        seed_chart_of_accounts(db)
        existing = find_posted_entry(db, 'consumption', str(consumption_id),
                                     'consumption')
        if existing:
            return {'success': True, 'journal_id': existing['id'], 'idempotent': True}
        cons = db.execute(
            "SELECT * FROM stock_consumptions WHERE id=?", (consumption_id,)
        ).fetchone()
        if not cons:
            return {'error': 'Consumption not found'}
        amount = D(cons['total_cost'] or 0)
        if amount <= 0:
            row = db.execute(
                "SELECT COALESCE(SUM(total_cost),0) FROM stock_consumption_items "
                "WHERE consumption_id=?", (consumption_id,)
            ).fetchone()
            amount = D(row[0] if row else 0)
        if amount <= 0:
            return {'skipped': True, 'reason': 'zero cost'}
        ref = cons['reference_no']
        reason = cons['reason'] if 'reason' in cons.keys() else ''
        account = consumption_debit_account(reason)
        return post_journal(
            db,
            [
                {'account_code': account, 'debit': amount,
                 'memo': f'Internal use {ref}'},
                {'account_code': '1200', 'credit': amount,
                 'memo': f'Inventory out {ref}'},
            ],
            description=f'Consumption {ref}',
            entry_date=(cons['date'] or date.today().isoformat())[:10],
            source_module='consumption',
            source_id=str(consumption_id),
            entry_type='consumption',
            user_id=user_id,
            username=username,
        )
    return _safe_call(_run, safe=safe)


def reverse_consumption_journal(db, consumption_id: int, *, reason='',
                                user_id=None, username='', safe=True) -> dict:
    def _run():
        existing = find_posted_entry(db, 'consumption', str(consumption_id),
                                     'consumption')
        if not existing:
            return {'skipped': True, 'reason': 'no journal'}
        return reverse_journal(
            db, existing['id'],
            reason=reason or 'Consumption voided',
            user_id=user_id,
            username=username,
            source_module='consumption',
            source_id=str(consumption_id),
            entry_type='consumption_void',
        )
    return _safe_call(_run, safe=safe)


def post_stock_adjust_journal(db, *, product_id, product_name, qty_change,
                              unit_cost, reason='', movement_id=None,
                              user_id=None, username='', safe=True) -> dict:
    """
    Damage/expire/decrease → Dr Shrinkage/Expiry, Cr Inventory.
    Increase → Dr Inventory, Cr Opening Balance Equity (or Other Income).
    """
    def _run():
        qty = D(qty_change or 0)
        cost = D(unit_cost or 0)
        amount = D(abs(qty) * cost)
        if amount <= 0:
            return {'skipped': True, 'reason': 'zero'}
        src_id = str(movement_id or f'{product_id}:{datetime.now().timestamp()}')
        existing = find_posted_entry(db, 'inventory', src_id, 'stock_adjust')
        if existing:
            return {'success': True, 'journal_id': existing['id'], 'idempotent': True}

        if qty < 0:
            exp_code = adjustment_debit_account(reason)
            lines = [
                {'account_code': exp_code, 'debit': amount,
                 'memo': f'{product_name}: {reason}'},
                {'account_code': '1200', 'credit': amount,
                 'memo': f'Inventory decrease {product_name}'},
            ]
            desc = f'Stock write-down {product_name}'
        else:
            lines = [
                {'account_code': '1200', 'debit': amount,
                 'memo': f'Inventory increase {product_name}'},
                {'account_code': '3200', 'credit': amount,
                 'memo': f'Stock adjust {reason}'},
            ]
            desc = f'Stock increase {product_name}'

        return post_journal(
            db, lines,
            description=desc,
            entry_date=date.today().isoformat(),
            source_module='inventory',
            source_id=src_id,
            entry_type='stock_adjust',
            user_id=user_id,
            username=username,
        )
    return _safe_call(_run, safe=safe)


def post_opening_inventory_journal(db, *, product_id, product_name, quantity,
                                   unit_cost, user_id=None, username='',
                                   safe=True) -> dict:
    """Dr Inventory, Cr Opening Balance Equity. Opening stock is not income."""
    def _run():
        from desktop.utils.accounting_engine import seed_chart_of_accounts
        seed_chart_of_accounts(db)
        amount = D(abs(D(quantity or 0)) * D(unit_cost or 0))
        if amount <= 0:
            return {'skipped': True, 'reason': 'zero'}
        return post_journal(
            db,
            [
                {'account_code': '1200', 'debit': amount,
                 'memo': f'Opening stock {product_name}'},
                {'account_code': '3200', 'credit': amount,
                 'memo': f'Opening balance {product_name}'},
            ],
            description=f'Opening stock {product_name}',
            entry_date=date.today().isoformat(),
            source_module='inventory',
            source_id=f'opening:{product_id}',
            entry_type='opening_stock',
            user_id=user_id,
            username=username,
        )
    return _safe_call(_run, safe=safe)


def post_stocktake_journal(db, *, product_id, product_name, qty_change, amount,
                           stocktake_id, user_id=None, username='', safe=True) -> dict:
    """Count variance. A shortage debits 6200. A gain credits 6200."""
    def _run():
        from desktop.utils.accounting_engine import seed_chart_of_accounts
        seed_chart_of_accounts(db)
        value = D(amount or 0)
        if value <= 0:
            return {'skipped': True, 'reason': 'zero'}
        src_id = f'stocktake:{stocktake_id}:{product_id}'
        if D(qty_change or 0) < 0:
            lines = [
                {'account_code': '6200', 'debit': value,
                 'memo': f'Stocktake shortage {product_name}'},
                {'account_code': '1200', 'credit': value,
                 'memo': f'Inventory count {product_name}'},
            ]
            desc = f'Stocktake shortage {product_name}'
        else:
            lines = [
                {'account_code': '1200', 'debit': value,
                 'memo': f'Stocktake gain {product_name}'},
                {'account_code': '6200', 'credit': value,
                 'memo': f'Inventory count {product_name}'},
            ]
            desc = f'Stocktake gain {product_name}'
        return post_journal(
            db, lines,
            description=desc,
            entry_date=date.today().isoformat(),
            source_module='inventory',
            source_id=src_id,
            entry_type='stocktake',
            user_id=user_id,
            username=username,
        )
    return _safe_call(_run, safe=safe)
