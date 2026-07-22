"""S04 Super-Admin PIN + S05 sale edit audit log — existing helpers/API gates."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class SuperadminPinAndSaleEditAuditGate(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, 'test.db')
        self._patches = [
            patch('mbt_paths.get_db_path', return_value=self._db_path),
            patch('desktop.utils.api_client.get_db_path', return_value=self._db_path),
        ]
        for p in self._patches:
            p.start()
        import desktop.utils.api_client as ac
        ac._SCHEMA_READY = False
        self.ac = ac
        self.api = ac.APIClient()
        self.api._role = 'superadmin'
        self.api._user_id = 1
        self.api._username = 'admin'
        db = ac._db()
        existing = db.execute(
            "SELECT id FROM users WHERE username=?", ('admin',)
        ).fetchone()
        if existing:
            self.api._user_id = int(existing['id'])
        else:
            db.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?,?,?)",
                ('admin', 'x:y', 'superadmin'),
            )
            self.api._user_id = int(
                db.execute("SELECT last_insert_rowid()").fetchone()[0]
            )
        db.execute(
            "UPDATE users SET role='superadmin' WHERE id=?",
            (self.api._user_id,),
        )
        db.execute(
            "INSERT INTO products (name, sku, price, cost_price, stock, min_stock) "
            "VALUES (?,?,?,?,?,?)",
            ('PIN Widget', 'PW1', 50.0, 20.0, 20, 2),
        )
        db.commit()
        db.close()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def test_s04_superadmin_pin_set_and_verify(self):
        from desktop.utils.security import set_superadmin_pin, _pin_hash

        self.assertTrue(set_superadmin_pin('998877', self.api))
        cfg = self.api.get_settings() or {}
        stored = cfg.get('superadmin_pin_hash') or ''
        self.assertTrue(stored)
        self.assertEqual(stored, _pin_hash('998877'))
        self.assertNotEqual(stored, _pin_hash('000000'))
        self.assertNotEqual(stored, '998877')

        # UI callers: edit_sale dialog + security helpers wire ask_superadmin_pin
        edit_path = os.path.join(ROOT, 'desktop', 'dialogs', 'edit_sale_dialog.py')
        with open(edit_path, encoding='utf-8') as f:
            self.assertIn('ask_superadmin_pin', f.read())
        sec_path = os.path.join(ROOT, 'desktop', 'utils', 'security.py')
        with open(sec_path, encoding='utf-8') as f:
            sec_src = f.read()
        self.assertIn('def verify_superadmin_pin', sec_src)
        self.assertIn('def ask_superadmin_pin', sec_src)
        self.assertIn('MBT_AUTO_SUPERADMIN_PIN', sec_src)

    def test_s05_sale_edits_audit_log(self):
        created = self.api.create_sale({
            'items': [{
                'product_id': 1,
                'product_name': 'PIN Widget',
                'sku': 'PW1',
                'quantity': 2,
                'unit_price': 50.0,
                'discount': 0,
                'total': 100.0,
            }],
            'subtotal': 100.0,
            'discount': 0,
            'tax': 0,
            'total': 100.0,
            'payment_method': 'Cash',
            'amount_paid': 100.0,
            'change_amount': 0,
        })
        self.assertTrue(created.get('success'), created)
        sale_id = int(created.get('sale_id') or created.get('id'))

        before = self.api.get_sale_edits(sale_id) or []
        res = self.api.edit_sale(sale_id, {
            'reason': 'S05 audit gate',
            'items': [{
                'product_id': 1,
                'product_name': 'PIN Widget',
                'sku': 'PW1',
                'quantity': 1.0,
                'unit_price': 50.0,
                'discount': 0,
                'total': 50.0,
            }],
            'payment_method': 'Cash',
            'discount': 0,
            'amount_paid': 50.0,
        })
        self.assertTrue(res.get('success'), res)
        after = self.api.get_sale_edits(sale_id) or []
        self.assertGreater(len(after), len(before))
        # Security tab surfaces get_sale_edits
        sec_path = os.path.join(ROOT, 'desktop', 'tabs', 'security_tab.py')
        with open(sec_path, encoding='utf-8') as f:
            sec = f.read()
        self.assertIn('get_sale_edits', sec)


if __name__ == '__main__':
    unittest.main()
