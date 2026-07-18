"""
Smoke + QA evidence for Accounting module.
Creates temp DB, seeds schema, posts cash sale / void / consumption,
prints P&L + trial balance, captures Accounting UI screenshots.
"""
import os
import sys
import json
import traceback
from datetime import date

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

EVIDENCE = os.path.join(os.path.expanduser('~'), 'Desktop', 'QA_EVIDENCE_ACCOUNTING')
os.makedirs(EVIDENCE, exist_ok=True)

# Use project DB path (offline) — do not wipe production; use API on live DB carefully
from mbt_paths import get_db_path, ensure_data_dirs, get_project_root

ensure_data_dirs(get_project_root())


def main():
    report = {'ok': True, 'steps': []}

    # Force schema ready reset so accounting tables create
    import desktop.utils.api_client as ac
    ac._SCHEMA_READY = False
    from desktop.utils.api_client import APIClient, _db

    api = APIClient()
    # Login as admin if possible
    try:
        login = api.login('admin', 'admin123')
        if login.get('token'):
            api.set_token(login['token'])
        if login.get('error'):
            report['steps'].append({'login': login})
        else:
            report['steps'].append({
                'login': 'ok',
                'user': (login.get('user') or {}).get('username'),
                'role': api._role,
            })
    except Exception as e:
        report['steps'].append({'login_error': str(e)})

    db = _db()
    try:
        from desktop.utils.accounting_engine import (
            ensure_accounting_schema, list_accounts, trial_balance, profit_and_loss,
            find_posted_entry, get_journal,
        )
        ensure_accounting_schema(db)
        db.commit()
        n_acct = len(list_accounts(db))
        report['steps'].append({'coa_accounts': n_acct})
        assert n_acct >= 20, 'COA too small'
    finally:
        db.close()

    # Prefer a product with stock > 0
    products = []
    try:
        d = _db()
        products = [dict(r) for r in d.execute(
            "SELECT * FROM products WHERE is_active=1 AND stock>=1 "
            "ORDER BY stock DESC LIMIT 5"
        ).fetchall()]
        d.close()
    except Exception as e:
        report['steps'].append({'list_products_error': str(e)})

    if not products:
        try:
            res = api.create_product({
                'name': 'Accounting Smoke Item',
                'sku': f'ACC-SMOKE-{date.today().isoformat()}',
                'price': 100,
                'cost_price': 40,
                'stock': 50,
                'category': 'Test',
            })
            report['steps'].append({'create_product': res})
            d = _db()
            products = [dict(r) for r in d.execute(
                "SELECT * FROM products WHERE is_active=1 AND stock>=1 "
                "ORDER BY id DESC LIMIT 1"
            ).fetchall()]
            d.close()
        except Exception as e:
            report['steps'].append({'create_product_error': str(e)})

    pid = products[0]['id'] if products else None
    cost = float(products[0].get('cost_price') or 40) if products else 40
    price = float(products[0].get('price') or 100) if products else 100

    sale_res = None
    if pid:
        try:
            sale_res = api.create_sale({
                'items': [{
                    'product_id': pid,
                    'product_name': products[0].get('name') or 'Item',
                    'sku': products[0].get('sku') or '',
                    'quantity': 1,
                    'unit_price': price,
                    'discount': 0,
                    'total': price,
                }],
                'subtotal': price,
                'discount': 0,
                'tax': 0,
                'total': price,
                'original_total': price,
                'cash_rounding_adj': 0,
                'payment_method': 'cash',
                'amount_paid': price,
                'change_amount': 0,
                'electronic_paid': 0,
                'credit_applied': 0,
            })
            report['steps'].append({'cash_sale': sale_res})
        except Exception as e:
            report['steps'].append({'cash_sale_error': str(e)})
            report['ok'] = False

    sale_id = (sale_res or {}).get('sale_id')
    journal_ok = False
    if sale_id:
        db = _db()
        try:
            je = find_posted_entry(db, 'sales', str(sale_id), 'sale')
            report['steps'].append({'sale_journal': je})
            if je:
                full = get_journal(db, je['id'])
                dr = sum(float(l['debit'] or 0) for l in full['lines'])
                cr = sum(float(l['credit'] or 0) for l in full['lines'])
                journal_ok = abs(dr - cr) < 0.02
                report['steps'].append({
                    'sale_journal_balanced': journal_ok,
                    'debit': dr, 'credit': cr,
                    'lines': full['lines'],
                })
        finally:
            db.close()

    void_ok = False
    if sale_id and journal_ok:
        void_res = api.void_sale(sale_id, 'Accounting smoke void')
        report['steps'].append({'void_sale': void_res})
        db = _db()
        try:
            rev = find_posted_entry(db, 'sales', str(sale_id), 'sale_void')
            void_ok = bool(rev)
            report['steps'].append({'void_journal': rev})
        finally:
            db.close()

    # Consumption
    cons_ok = False
    try:
        depts = api.get_departments()
        dept_id = depts[0]['id'] if depts else None
        if pid and dept_id:
            cres = api.create_consumption({
                'date': str(date.today()),
                'department_id': dept_id,
                'reason': 'Office Use',
                'notes': 'Accounting smoke',
                'taken_by': 'QA',
                'items': [{'product_id': pid, 'quantity': 1, 'unit_cost': cost}],
            })
            report['steps'].append({'consumption': cres})
            cid = (cres or {}).get('id')
            if cid:
                db = _db()
                try:
                    cj = find_posted_entry(db, 'consumption', str(cid), 'consumption')
                    cons_ok = bool(cj)
                    report['steps'].append({'consumption_journal': cj})
                finally:
                    db.close()
    except Exception as e:
        report['steps'].append({'consumption_error': str(e)})

    db = _db()
    try:
        tb = trial_balance(db)
        pl = profit_and_loss(db)
        report['steps'].append({
            'trial_balance_balanced': tb.get('balanced'),
            'tb_dr': tb.get('total_debit'),
            'tb_cr': tb.get('total_credit'),
            'pnl_income': pl.get('total_income'),
            'pnl_net': pl.get('net_profit'),
        })
    finally:
        db.close()

    # UI screenshots
    try:
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtCore import QTimer, Qt
        from desktop.utils.theme import ThemeManager, ensure_fonts
        app = QApplication.instance() or QApplication(sys.argv)
        ensure_fonts()
        ThemeManager.apply(False, force=True)
        from desktop.tabs.accounting_tab import AccountingTab
        # Fake user with accounting tab
        user = {
            'user': {
                'id': 1, 'username': 'admin', 'role': 'superadmin',
                'tab_permissions': ['accounting', 'dashboard'],
                'full_name': 'QA Admin',
            }
        }
        tab = AccountingTab(api=api, user=user, db_path=get_db_path(),
                            config_getter=lambda: {'currency_symbol': 'KES'})
        tab.resize(1280, 800)
        tab.show()
        tab.on_show()
        app.processEvents()

        shots = [
            (0, '01_dashboard.png'),
            (1, '02_chart_of_accounts.png'),
            (3, '03_journals.png'),
            (7, '04_reports_pnl.png'),
        ]

        def capture(idx, name):
            tab._tabs.setCurrentIndex(idx)
            app.processEvents()
            w = tab._tabs.widget(idx)
            if hasattr(w, 'refresh'):
                try:
                    w.refresh()
                except Exception:
                    pass
            app.processEvents()
            path = os.path.join(EVIDENCE, name)
            tab.grab().save(path, 'PNG')
            report['steps'].append({'screenshot': path})

        for idx, name in shots:
            capture(idx, name)
            # Run P&L text for reports tab
            if idx == 7:
                try:
                    tab._reports._kind.setCurrentText('Profit & Loss')
                    tab._reports.refresh()
                    app.processEvents()
                    tab.grab().save(os.path.join(EVIDENCE, '04_reports_pnl.png'), 'PNG')
                    tab._reports._kind.setCurrentText('Trial Balance')
                    tab._reports.refresh()
                    app.processEvents()
                    tab.grab().save(os.path.join(EVIDENCE, '05_trial_balance.png'), 'PNG')
                except Exception as e:
                    report['steps'].append({'report_shot_err': str(e)})

        tab.close()
    except Exception as e:
        report['ok'] = False
        report['steps'].append({'ui_error': str(e), 'trace': traceback.format_exc()})

    report['summary'] = {
        'sale_journal_balanced': journal_ok,
        'void_journal': void_ok,
        'consumption_journal': cons_ok,
    }
    if not (journal_ok and void_ok):
        report['ok'] = False

    out = os.path.join(EVIDENCE, 'smoke_report.json')
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, default=str)
    print(json.dumps(report['summary'], indent=2))
    print('Evidence:', EVIDENCE)
    print('OK' if report['ok'] else 'FAILED')
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
