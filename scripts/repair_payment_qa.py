"""CLI: repair Credit→debt orphans and flag Mixed missing tenders (supervised).

Default target is an isolated copy unless --live is passed. Live mode always
backs up the DB first and never invents Mixed tender splits.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main() -> int:
    ap = argparse.ArgumentParser(description='MBT POS payment repair utility')
    ap.add_argument('--db', default='', help='SQLite path (default: live AppData)')
    ap.add_argument('--live', action='store_true',
                    help='Allow writing the live AppData database (backs up first)')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--sale-date', default='',
                    help='Limit to sale_date YYYY-MM-DD')
    ap.add_argument('--receipt', action='append', default=[],
                    help='Limit to receipt number (repeatable)')
    ap.add_argument('--actor', default='payment_repair')
    args = ap.parse_args()

    from desktop.utils.sale_payment_repair import (
        backup_database,
        default_live_db_path,
        flag_mixed_sales_missing_tenders,
        repair_debt_sales_missing_invoices,
        repair_same_day_qa_sales,
    )

    db_path = args.db or default_live_db_path()
    if not os.path.isfile(db_path):
        print(json.dumps({'success': False, 'error': f'DB not found: {db_path}'}))
        return 2

    live_default = os.path.normcase(os.path.abspath(default_live_db_path()))
    target = os.path.normcase(os.path.abspath(db_path))
    if target == live_default and not args.live and not args.dry_run:
        print(json.dumps({
            'success': False,
            'error': 'Refusing live DB write without --live (or use --dry-run).',
            'db': db_path,
        }))
        return 3

    backup = None
    if target == live_default and args.live and not args.dry_run:
        backup = backup_database(db_path)

    sale_dates = [args.sale_date] if args.sale_date else None
    receipts = args.receipt or None

    if args.sale_date and not receipts:
        result = repair_same_day_qa_sales(
            db_path,
            sale_date=args.sale_date,
            dry_run=args.dry_run,
            actor=args.actor,
        )
    else:
        debt = repair_debt_sales_missing_invoices(
            db_path,
            receipt_numbers=receipts,
            sale_dates=sale_dates,
            dry_run=args.dry_run,
            actor=args.actor,
        )
        mixed = flag_mixed_sales_missing_tenders(
            db_path,
            receipt_numbers=receipts,
            sale_dates=sale_dates,
            dry_run=args.dry_run,
            actor=args.actor,
        )
        result = {
            'success': bool(debt.get('success') and mixed.get('success')),
            'dry_run': args.dry_run,
            'debt_repair': debt,
            'mixed_flags': mixed,
        }
    if backup:
        result['backup'] = backup
    result['db'] = db_path
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get('success') else 1


if __name__ == '__main__':
    raise SystemExit(main())
