"""Category visuals and till print requests. Disposable files only."""
import os
import sqlite3
import tempfile
import unittest


class CategoryVisualStoreTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='mbt-visuals-')
        os.environ['MBT_DATA_ROOT'] = self.root
        os.environ['APPDATA'] = self.root
        os.environ['LOCALAPPDATA'] = self.root
        os.environ['PROGRAMDATA'] = self.root

    def test_defaults_and_bounds(self):
        from backend.category_visual_store import load_prefs, save_prefs
        prefs = load_prefs()
        self.assertEqual(prefs['tile_size'], 48)
        saved = save_prefs({'tile_size': 64, 'image_fit': 'contain', 'compact_mode': True})
        self.assertEqual(saved['tile_size'], 64)
        self.assertEqual(saved['image_fit'], 'contain')
        self.assertTrue(saved['compact_mode'])
        again = load_prefs()
        self.assertEqual(again['tile_size'], 64)
        with self.assertRaises(ValueError):
            save_prefs({'tile_size': 16})
        self.assertEqual(load_prefs()['tile_size'], 64)
        with self.assertRaises(ValueError):
            save_prefs({'default_placeholder': '../secret'})

    def test_print_request_stays_pending_until_the_till_finishes(self):
        from backend.device_commands import claim_next_print_test, enqueue, finish, get_command
        db = sqlite3.connect(':memory:')
        db.row_factory = sqlite3.Row
        job = enqueue(db, 'print_test', 'admin')
        self.assertEqual(job['status'], 'pending')
        self.assertNotEqual(job['result'], 'queued')
        with self.assertRaises(ValueError):
            enqueue(db, 'revoke_license', 'admin')
        claimed = claim_next_print_test(db, 'till')
        self.assertEqual(claimed['status'], 'running')
        self.assertIsNone(claim_next_print_test(db, 'till'))
        done = finish(db, claimed['id'], 'queued', 'Test page was queued. The printer has not confirmed paper.')
        self.assertEqual(done['result'], 'queued')
        self.assertIn('not confirmed', done['detail'])
        self.assertEqual(get_command(db, job['id'])['status'], 'completed')


if __name__ == '__main__':
    unittest.main()
