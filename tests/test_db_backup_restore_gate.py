"""Local DB backup zip create + restore round-trip (critical gate C03/C04)."""
from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
import zipfile


class DbBackupRestoreGate(unittest.TestCase):
    def test_create_zip_and_restore_reads_rows(self):
        from backend.db_backup import create_db_backup_zip

        with tempfile.TemporaryDirectory() as td:
            src = os.path.join(td, 'src.db')
            conn = sqlite3.connect(src)
            conn.execute('CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)')
            conn.execute("INSERT INTO t (name) VALUES ('alpha')")
            conn.commit()
            conn.close()

            zip_path, size, digest = create_db_backup_zip(src)
            self.assertTrue(os.path.isfile(zip_path))
            self.assertGreater(size, 0)
            self.assertTrue(digest)

            restore_db = os.path.join(td, 'restored.db')
            with zipfile.ZipFile(zip_path, 'r') as zf:
                self.assertIn('mbt_pos.db', zf.namelist())
                self.assertIn('RESTORE.txt', zf.namelist())
                with zf.open('mbt_pos.db') as src_f, open(restore_db, 'wb') as dst_f:
                    dst_f.write(src_f.read())

            conn = sqlite3.connect(restore_db)
            name = conn.execute('SELECT name FROM t WHERE id=1').fetchone()[0]
            conn.close()
            self.assertEqual(name, 'alpha')

            try:
                os.remove(zip_path)
                os.rmdir(os.path.dirname(zip_path))
            except OSError:
                pass


if __name__ == '__main__':
    unittest.main()
