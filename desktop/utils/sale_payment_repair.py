"""Repair / supervised correction helpers for payment method QA defects.

- Repair completed Credit/Part Payment sales missing debt_invoices.
- Flag Mixed sales with NULL/incomplete tenders (never invent splits).
- Apply Mixed tender corrections only when an explicit supervised tender list
  is provided and validates against the sale total.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
from datetime import datetime
from typing import Any, Iterable, List, Optional, Sequence

from desktop.utils.payment_methods import (
    MIXED_CORRECTION_FLAG,
    append_mixed_correction_flag,
    clear_mixed_correction_flag,
    is_debt_payment_method,
    normalize_payment_method,
    notes_have_mixed_correction_flag,
    tender_rows_complete,
    validate_and_normalize_mixed,
)

logger = logging.getLogger('sale_payment_repair')


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _row_dict(row: Optional[sqlite3.Row]) -> Optional[dict]:
    return dict(row) if row is not None else None


def backup_database(db_path: str, suffix: str = 'pre_payment_repair') -> str:
    """Copy live DB beside itself before repair. Returns backup path."""
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup = f'{db_path}.{suffix}_{ts}.bak'
    shutil.copy2(db_path, backup)
    return backup


def _next_invoice_number(db: sqlite3.Connection) -> str:
    today = datetime.now().strftime('%Y%m%d')
    count = db.execute(
        "SELECT COUNT(*) FROM debt_invoices WHERE date(created_at)=date('now')"
    ).fetchone()[0]
    return f'INV-{today}-{count + 1:04d}'


def _next_payment_receipt(db: sqlite3.Connection) -> str:
    today = datetime.now().strftime('%Y%m%d')
    count = db.execute(
        "SELECT COUNT(*) FROM debt_payments WHERE date(created_at)=date('now')"
    ).fetchone()[0]
    return f'PAY-{today}-{count + 1:04d}'


def find_debt_sales_missing_invoices(
    db: sqlite3.Connection,
    *,
    receipt_numbers: Optional[Sequence[str]] = None,
    sale_dates: Optional[Sequence[str]] = None,
) -> List[dict]:
    """Completed credit/part-payment-like sales with no debt_invoices row."""
    rows = db.execute(
        "SELECT s.* FROM sales s "
        "LEFT JOIN debt_invoices d ON d.sale_id = s.id "
        "AND IFNULL(d.status, '') NOT IN ('cancelled') "
        "WHERE IFNULL(s.status, 'completed') = 'completed' "
        "AND d.id IS NULL "
        "ORDER BY s.id ASC"
    ).fetchall()
    out: List[dict] = []
    want_rn = {str(r).strip() for r in (receipt_numbers or []) if str(r).strip()}
    want_dates = {str(d).strip() for d in (sale_dates or []) if str(d).strip()}
    for row in rows:
        sale = dict(row)
        raw_method = sale.get('payment_method')
        try:
            canon = normalize_payment_method(raw_method, reject_unknown=False)
        except Exception:
            continue
        if not is_debt_payment_method(canon):
            # Accept bare historical "Credit" via alias; reject random methods.
            try:
                canon = normalize_payment_method(raw_method, reject_unknown=True)
            except ValueError:
                continue
            if not is_debt_payment_method(canon):
                continue
        if want_rn and str(sale.get('receipt_number') or '') not in want_rn:
            continue
        if want_dates and str(sale.get('sale_date') or '')[:10] not in want_dates:
            continue
        sale['_canonical_method'] = canon
        out.append(sale)
    return out


def repair_debt_sales_missing_invoices(
    db_path: str,
    *,
    receipt_numbers: Optional[Sequence[str]] = None,
    sale_dates: Optional[Sequence[str]] = None,
    dry_run: bool = False,
    actor: str = 'payment_repair',
) -> dict:
    """Normalize payment_method and create missing receivables for debt sales.

    Safe for completed Credit sales with amount_paid 0 (full receivable).
    Does not touch Mixed tenders or invent payment splits.
    """
    db = _connect(db_path)
    created: List[dict] = []
    normalized: List[dict] = []
    skipped: List[dict] = []
    try:
        candidates = find_debt_sales_missing_invoices(
            db, receipt_numbers=receipt_numbers, sale_dates=sale_dates,
        )
        if not dry_run:
            db.execute('BEGIN IMMEDIATE')
        for sale in candidates:
            sale_id = int(sale['id'])
            canon = sale['_canonical_method']
            customer_id = sale.get('customer_id')
            if not customer_id:
                skipped.append({
                    'sale_id': sale_id,
                    'receipt_number': sale.get('receipt_number'),
                    'reason': 'missing_customer',
                })
                continue
            cust = _row_dict(db.execute(
                "SELECT id,name,phone FROM customers WHERE id=?",
                (int(customer_id),),
            ).fetchone())
            if not cust:
                skipped.append({
                    'sale_id': sale_id,
                    'receipt_number': sale.get('receipt_number'),
                    'reason': 'customer_not_found',
                })
                continue

            raw_method = str(sale.get('payment_method') or '')
            if raw_method != canon:
                if not dry_run:
                    db.execute(
                        "UPDATE sales SET payment_method=? WHERE id=?",
                        (canon, sale_id),
                    )
                normalized.append({
                    'sale_id': sale_id,
                    'receipt_number': sale.get('receipt_number'),
                    'from': raw_method,
                    'to': canon,
                })

            total = round(float(sale.get('total') or 0), 2)
            paid = round(
                float(sale.get('amount_paid') or 0)
                + float(sale.get('credit_applied') or 0),
                2,
            )
            if total <= 0:
                skipped.append({
                    'sale_id': sale_id,
                    'receipt_number': sale.get('receipt_number'),
                    'reason': 'non_positive_total',
                })
                continue
            if paid > total + 0.009:
                skipped.append({
                    'sale_id': sale_id,
                    'receipt_number': sale.get('receipt_number'),
                    'reason': 'paid_exceeds_total',
                })
                continue
            balance = round(total - paid, 2)
            status = (
                'paid' if balance == 0
                else ('partial' if paid > 0 else 'pending')
            )
            inv_num = _next_invoice_number(db)
            if not dry_run:
                db.execute(
                    "INSERT INTO debt_invoices "
                    "(invoice_number,sale_id,receipt_number,customer_id,"
                    "customer_name,customer_phone,total_amount,amount_paid,"
                    "balance,status,cashier_id,cashier_name,notes) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        inv_num, sale_id, sale.get('receipt_number'),
                        int(customer_id), cust['name'], cust.get('phone') or '',
                        total, paid, balance, status,
                        sale.get('cashier_id'),
                        sale.get('cashier_name') or actor,
                        f'Repair from sale {canon} ({actor})',
                    ),
                )
                inv_id = int(db.execute(
                    "SELECT last_insert_rowid()").fetchone()[0])
                if paid > 0.009:
                    pay_receipt = _next_payment_receipt(db)
                    dp_cols = {
                        r[1] for r in db.execute(
                            "PRAGMA table_info(debt_payments)").fetchall()
                    }
                    if 'payment_reference' in dp_cols:
                        db.execute(
                            "INSERT INTO debt_payments "
                            "(payment_receipt,invoice_id,customer_id,amount,"
                            "payment_method,payment_reference,balance_before,"
                            "balance_after,cashier_id,cashier_name,notes) "
                            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (
                                pay_receipt, inv_id, int(customer_id), paid,
                                canon, sale.get('receipt_number'),
                                total, balance,
                                sale.get('cashier_id'),
                                sale.get('cashier_name') or actor,
                                f'Initial payment on repaired invoice {inv_num}',
                            ),
                        )
                    else:
                        db.execute(
                            "INSERT INTO debt_payments "
                            "(payment_receipt,invoice_id,customer_id,amount,"
                            "payment_method,balance_before,balance_after,"
                            "cashier_id,cashier_name,notes) "
                            "VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (
                                pay_receipt, inv_id, int(customer_id), paid,
                                canon, total, balance,
                                sale.get('cashier_id'),
                                sale.get('cashier_name') or actor,
                                f'Initial payment on repaired invoice {inv_num}',
                            ),
                        )
                db.execute(
                    "INSERT INTO audit_log "
                    "(user_id,username,action,module,details) "
                    "VALUES (?,?,?,?,?)",
                    (
                        sale.get('cashier_id'),
                        sale.get('cashier_name') or actor,
                        'REPAIR_DEBT_INVOICE',
                        'debt',
                        f'inv={inv_num} sale={sale_id} '
                        f'receipt={sale.get("receipt_number")} '
                        f'method={canon} total={total} paid={paid} '
                        f'balance={balance}',
                    ),
                )
            else:
                inv_id = None
            created.append({
                'sale_id': sale_id,
                'receipt_number': sale.get('receipt_number'),
                'invoice_number': inv_num,
                'invoice_id': inv_id,
                'payment_method': canon,
                'total': total,
                'amount_paid': paid,
                'balance': balance,
                'status': status,
            })
        if not dry_run:
            db.commit()
        return {
            'success': True,
            'dry_run': dry_run,
            'created': created,
            'normalized': normalized,
            'skipped': skipped,
            'candidate_count': len(candidates),
        }
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        logger.error('repair_debt_sales_missing_invoices failed: %s', e, exc_info=True)
        return {'success': False, 'error': str(e)}
    finally:
        db.close()


def find_mixed_missing_tenders(
    db: sqlite3.Connection,
    *,
    receipt_numbers: Optional[Sequence[str]] = None,
    sale_dates: Optional[Sequence[str]] = None,
) -> List[dict]:
    rows = db.execute(
        "SELECT * FROM sales WHERE IFNULL(status,'completed')='completed' "
        "ORDER BY id ASC"
    ).fetchall()
    want_rn = {str(r).strip() for r in (receipt_numbers or []) if str(r).strip()}
    want_dates = {str(d).strip() for d in (sale_dates or []) if str(d).strip()}
    out: List[dict] = []
    for row in rows:
        sale = dict(row)
        try:
            canon = normalize_payment_method(
                sale.get('payment_method'), reject_unknown=False,
            )
        except Exception:
            continue
        if canon != 'Mixed':
            continue
        if want_rn and str(sale.get('receipt_number') or '') not in want_rn:
            continue
        if want_dates and str(sale.get('sale_date') or '')[:10] not in want_dates:
            continue
        if tender_rows_complete(sale.get('payment_tenders')):
            continue
        # Also incomplete when columns cannot rebuild ≥2 rows
        try:
            validate_and_normalize_mixed(
                payment_tenders=sale.get('payment_tenders'),
                sale_total=float(sale.get('total') or 0),
                amount_paid=float(sale.get('amount_paid') or 0),
                cash_paid=float(sale.get('cash_paid') or 0),
                electronic_paid=float(sale.get('electronic_paid') or 0),
                electronic_method=str(sale.get('electronic_method') or ''),
                credit_applied=float(sale.get('credit_applied') or 0),
            )
            continue  # reconstructible from columns — leave alone
        except ValueError:
            pass
        sale['_canonical_method'] = canon
        out.append(sale)
    return out


def flag_mixed_sales_missing_tenders(
    db_path: str,
    *,
    receipt_numbers: Optional[Sequence[str]] = None,
    sale_dates: Optional[Sequence[str]] = None,
    dry_run: bool = False,
    actor: str = 'payment_repair',
) -> dict:
    """Flag Mixed sales that lack a valid tender breakdown. Never invents splits."""
    db = _connect(db_path)
    flagged: List[dict] = []
    already: List[dict] = []
    try:
        candidates = find_mixed_missing_tenders(
            db, receipt_numbers=receipt_numbers, sale_dates=sale_dates,
        )
        if not dry_run:
            db.execute('BEGIN IMMEDIATE')
        for sale in candidates:
            sale_id = int(sale['id'])
            notes = sale.get('notes') or ''
            if notes_have_mixed_correction_flag(notes):
                already.append({
                    'sale_id': sale_id,
                    'receipt_number': sale.get('receipt_number'),
                })
                continue
            new_notes = append_mixed_correction_flag(notes)
            raw_method = str(sale.get('payment_method') or '')
            if not dry_run:
                if raw_method != 'Mixed':
                    db.execute(
                        "UPDATE sales SET payment_method=?, notes=? WHERE id=?",
                        ('Mixed', new_notes, sale_id),
                    )
                else:
                    db.execute(
                        "UPDATE sales SET notes=? WHERE id=?",
                        (new_notes, sale_id),
                    )
                db.execute(
                    "INSERT INTO audit_log "
                    "(user_id,username,action,module,details) "
                    "VALUES (?,?,?,?,?)",
                    (
                        sale.get('cashier_id'),
                        sale.get('cashier_name') or actor,
                        'FLAG_MIXED_TENDER_CORRECTION',
                        'sales',
                        f'sale={sale_id} receipt={sale.get("receipt_number")} '
                        f'{MIXED_CORRECTION_FLAG}',
                    ),
                )
            flagged.append({
                'sale_id': sale_id,
                'receipt_number': sale.get('receipt_number'),
                'total': float(sale.get('total') or 0),
                'flag': MIXED_CORRECTION_FLAG,
            })
        if not dry_run:
            db.commit()
        return {
            'success': True,
            'dry_run': dry_run,
            'flagged': flagged,
            'already_flagged': already,
            'candidate_count': len(candidates),
        }
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        logger.error('flag_mixed_sales_missing_tenders failed: %s', e, exc_info=True)
        return {'success': False, 'error': str(e)}
    finally:
        db.close()


def apply_supervised_mixed_correction(
    db_path: str,
    *,
    sale_id: int,
    tenders: Sequence[dict],
    actor: str,
    confirm: bool,
) -> dict:
    """Apply an explicit Mixed tender breakdown after human supervision.

    Requires ``confirm=True`` and a tender list that validates against the
    sale total. Refuses to invent or guess missing amounts.
    """
    if not confirm:
        return {
            'success': False,
            'error': 'Supervised Mixed correction requires confirm=True.',
        }
    if not actor or not str(actor).strip():
        return {'success': False, 'error': 'Actor (supervisor) is required.'}
    if not tenders:
        return {
            'success': False,
            'error': 'Explicit tender rows are required; splits are not invented.',
        }

    db = _connect(db_path)
    try:
        sale = _row_dict(db.execute(
            "SELECT * FROM sales WHERE id=?", (int(sale_id),)
        ).fetchone())
        if not sale:
            return {'success': False, 'error': 'Sale not found.'}
        if (sale.get('status') or 'completed') == 'voided':
            return {'success': False, 'error': 'Cannot correct a voided sale.'}
        try:
            canon = normalize_payment_method(sale.get('payment_method'))
        except ValueError as e:
            return {'success': False, 'error': str(e)}
        if canon != 'Mixed':
            return {
                'success': False,
                'error': f'Sale payment method is {canon!r}, not Mixed.',
            }

        validated = validate_and_normalize_mixed(
            payment_tenders=list(tenders),
            sale_total=float(sale.get('total') or 0),
            amount_paid=float(sale.get('amount_paid') or 0),
            cash_paid=0.0,
            electronic_paid=0.0,
            electronic_method='',
            credit_applied=float(sale.get('credit_applied') or 0),
        )
        new_notes = clear_mixed_correction_flag(sale.get('notes'))
        db.execute('BEGIN IMMEDIATE')
        db.execute(
            "UPDATE sales SET payment_method=?, cash_paid=?, electronic_paid=?,"
            " electronic_method=?, payment_tenders=?, notes=? WHERE id=?",
            (
                'Mixed',
                validated['cash_paid'],
                validated['electronic_paid'],
                validated['electronic_method'] or None,
                validated['tenders_json'],
                new_notes or None,
                int(sale_id),
            ),
        )
        db.execute(
            "INSERT INTO audit_log "
            "(user_id,username,action,module,details) VALUES (?,?,?,?,?)",
            (
                None, str(actor).strip(),
                'SUPERVISED_MIXED_CORRECTION', 'sales',
                f'sale={sale_id} receipt={sale.get("receipt_number")} '
                f'tenders={validated["tenders_json"]}',
            ),
        )
        db.commit()
        return {
            'success': True,
            'sale_id': int(sale_id),
            'receipt_number': sale.get('receipt_number'),
            'tenders': validated['tenders'],
            'cash_paid': validated['cash_paid'],
            'electronic_paid': validated['electronic_paid'],
            'electronic_method': validated['electronic_method'],
        }
    except ValueError as e:
        try:
            db.rollback()
        except Exception:
            pass
        return {'success': False, 'error': str(e)}
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        logger.error('apply_supervised_mixed_correction failed: %s', e, exc_info=True)
        return {'success': False, 'error': str(e)}
    finally:
        db.close()


def repair_same_day_qa_sales(
    db_path: str,
    *,
    sale_date: str,
    dry_run: bool = False,
    actor: str = 'qa_payment_repair',
) -> dict:
    """Orchestrate safe same-day QA repair: debt recreate + Mixed flag only."""
    debt = repair_debt_sales_missing_invoices(
        db_path,
        sale_dates=[sale_date],
        dry_run=dry_run,
        actor=actor,
    )
    mixed = flag_mixed_sales_missing_tenders(
        db_path,
        sale_dates=[sale_date],
        dry_run=dry_run,
        actor=actor,
    )
    return {
        'success': bool(debt.get('success') and mixed.get('success')),
        'dry_run': dry_run,
        'sale_date': sale_date,
        'debt_repair': debt,
        'mixed_flags': mixed,
    }


def default_live_db_path() -> str:
    local = os.environ.get('LOCALAPPDATA') or ''
    return os.path.join(local, 'MugoByte', 'MBT POS', 'data', 'mbt_pos.db')
