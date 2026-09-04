"""Regression: notes and customer records must respect role + ownership.

A viewer could previously create, edit and delete notes, and create customers,
because these API methods had no authorization at all. Notes were also returned
to every role regardless of `notes.own` vs `notes.view_all`.
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

ROLES = ('superadmin', 'admin', 'manager', 'cashier', 'viewer')


class NotesCustomerScopeGates(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, 'scope.db')
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
        db = ac._db()
        for role in ROLES:
            db.execute(
                "INSERT INTO users (username,password_hash,role) VALUES (?,?,?)",
                (role, 'x:y', role))
        db.commit()
        self.uids = {
            r['role']: int(r['id'])
            for r in db.execute("SELECT id, role FROM users").fetchall()
        }
        db.close()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def _as(self, role):
        self.api._role = role
        self.api._user_id = self.uids[role]
        self.api._username = role
        return self.api

    # ── notes ────────────────────────────────────────────────────────────────
    def test_viewer_cannot_create_note(self):
        res = self._as('viewer').create_note({'title': 'x', 'content': 'y'})
        self.assertNotIn('success', res)
        self.assertIn('permission', res.get('error', '').lower())

    def test_viewer_cannot_edit_or_delete_note(self):
        note = self._as('cashier').create_note({'title': 'mine', 'content': 'c'})
        nid = note['id']
        v = self._as('viewer')
        self.assertIn('error', v.update_note(nid, {'title': 'hacked'}))
        self.assertIn('error', v.delete_note(nid))
        rows = [n for n in self._as('cashier').get_notes() if n['id'] == nid]
        self.assertEqual(rows[0]['title'], 'mine')

    def test_cashier_sees_only_own_notes(self):
        self._as('manager').create_note({'title': 'manager note', 'content': 'm'})
        self._as('cashier').create_note({'title': 'cashier note', 'content': 'c'})
        titles = {n['title'] for n in self._as('cashier').get_notes()}
        self.assertEqual(titles, {'cashier note'})

    def test_view_all_role_sees_every_note(self):
        self._as('manager').create_note({'title': 'manager note', 'content': 'm'})
        self._as('cashier').create_note({'title': 'cashier note', 'content': 'c'})
        titles = {n['title'] for n in self._as('admin').get_notes()}
        self.assertEqual(titles, {'manager note', 'cashier note'})

    def test_cashier_cannot_touch_another_users_note(self):
        note = self._as('manager').create_note({'title': 'private', 'content': 'm'})
        nid = note['id']
        c = self._as('cashier')
        self.assertIn('error', c.update_note(nid, {'title': 'tampered'}))
        self.assertIn('error', c.delete_note(nid))
        rows = [n for n in self._as('manager').get_notes() if n['id'] == nid]
        self.assertEqual(rows[0]['title'], 'private')

    def test_owner_can_edit_and_delete_own_note(self):
        for role in ('superadmin', 'admin', 'manager', 'cashier'):
            api = self._as(role)
            nid = api.create_note({'title': role, 'content': 'x'})['id']
            self.assertTrue(api.update_note(nid, {'title': 'edited'}).get('success'))
            self.assertTrue(api.delete_note(nid).get('success'))

    # ── customers ────────────────────────────────────────────────────────────
    def test_viewer_cannot_create_customer(self):
        res = self._as('viewer').create_customer(
            {'name': 'Walk In', 'phone': '0712345678'})
        self.assertNotIn('success', res)
        self.assertEqual(self._as('viewer').get_customers(), [])

    def test_cashier_can_register_customer_for_credit_sale(self):
        res = self._as('cashier').create_customer(
            {'name': 'Credit Buyer', 'phone': '0712345678'})
        self.assertTrue(res.get('success'))

    def test_cashier_cannot_edit_customer_record(self):
        cid = self._as('manager').create_customer(
            {'name': 'Original', 'phone': '0712345678'})['customer_id']
        res = self._as('cashier').update_customer(cid, {'name': 'Changed'})
        self.assertIn('error', res)
        names = {c['name'] for c in self._as('manager').get_customers()}
        self.assertIn('Original', names)
        self.assertNotIn('Changed', names)

    def test_viewer_cannot_edit_customer_record(self):
        cid = self._as('manager').create_customer(
            {'name': 'Original', 'phone': '0712345678'})['customer_id']
        self.assertIn('error', self._as('viewer').update_customer(cid, {'name': 'X'}))

    def test_manage_roles_can_edit_customer(self):
        for role in ('superadmin', 'admin', 'manager'):
            api = self._as(role)
            cid = api.create_customer(
                {'name': f'{role} cust', 'phone': '0712345678'})['customer_id']
            self.assertTrue(
                api.update_customer(cid, {'name': f'{role} edited'}).get('success'))


if __name__ == '__main__':
    unittest.main()
