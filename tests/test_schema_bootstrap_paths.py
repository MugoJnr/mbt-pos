import os
import tempfile
import unittest
from unittest.mock import patch


class SchemaBootstrapPathTests(unittest.TestCase):
    def test_each_database_path_is_bootstrapped_in_the_same_process(self):
        from desktop.utils import api_client

        old_ready = api_client._SCHEMA_READY
        old_path = api_client._SCHEMA_READY_PATH
        try:
            api_client._SCHEMA_READY = False
            api_client._SCHEMA_READY_PATH = None
            with tempfile.TemporaryDirectory() as temp:
                first = os.path.join(temp, 'first.db')
                second = os.path.join(temp, 'second.db')
                for path in (first, second):
                    with patch.object(api_client, 'get_db_path', return_value=path):
                        db = api_client._db()
                        try:
                            table = db.execute(
                                "SELECT name FROM sqlite_master "
                                "WHERE type='table' AND name='users'"
                            ).fetchone()
                            self.assertIsNotNone(table)
                        finally:
                            db.close()
        finally:
            api_client._SCHEMA_READY = old_ready
            api_client._SCHEMA_READY_PATH = old_path


if __name__ == '__main__':
    unittest.main()
