"""Product photographs are checked by content and stored once per product."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from desktop.utils.product_photo import image_error, sniff_image

JPEG = b'\xff\xd8\xff\xe0' + b'\x00' * 32
PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 32
WEBP = b'RIFF' + b'\x00\x00\x00\x00' + b'WEBP' + b'\x00' * 16
HEIC = b'\x00\x00\x00\x18ftypheic' + b'\x00' * 16


class ProductPhotoTests(unittest.TestCase):
    def test_content_not_extension_decides_the_format(self):
        self.assertEqual(sniff_image(JPEG), '.jpg')
        self.assertEqual(sniff_image(PNG), '.png')
        self.assertEqual(sniff_image(WEBP), '.webp')
        self.assertIn('HEIC', image_error(HEIC))
        self.assertIn('JPEG', image_error(b'not a picture'))
        self.assertIn('Choose', image_error(b''))
        self.assertIn('8 MB', image_error(b'\xff\xd8\xff' + b'x' * (8 * 1024 * 1024)))

    def test_save_replace_and_remove_keep_one_file(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        os.environ['MBT_TEST_INSTANCE'] = '1'
        os.environ['MBT_DATA_ROOT'] = tmp.name
        os.environ['APPDATA'] = os.path.join(tmp.name, 'appdata')
        os.environ['LOCALAPPDATA'] = os.path.join(tmp.name, 'local')
        os.environ['PROGRAMDATA'] = os.path.join(tmp.name, 'programdata')
        db_path = os.path.join(tmp.name, 'shop.db')
        data_root = tmp.name
        patches = [
            patch('mbt_paths.get_db_path', return_value=db_path),
            patch('desktop.utils.api_client.get_db_path', return_value=db_path),
            patch('mbt_paths.get_data_dir', return_value=os.path.join(data_root, 'data')),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        import desktop.utils.api_client as ac
        ac._SCHEMA_READY = False
        api = ac.APIClient()
        api._role = 'cashier'
        api._user_id = 1
        api._username = 'cashier'
        db = ac._db()
        db.execute("INSERT INTO users (id,username,password_hash,role) VALUES (1,'cashier','x:y','cashier')")
        db.execute(
            "INSERT INTO products (name,sku,price,cost_price,stock,min_stock) VALUES ('Photo Oil','PHOTO-1',10,5,3,1)"
        )
        db.commit()
        db.close()
        import io
        from PIL import Image
        folder = os.path.join(data_root, 'data', 'product-images')

        def _file(kind, size, color):
            image = Image.new('RGB', size, color)
            buf = io.BytesIO()
            image.save(buf, format='JPEG' if kind == 'jpg' else 'PNG')
            path = os.path.join(tmp.name, f'shop-{kind}-{size[0]}.{kind}')
            with open(path, 'wb') as handle:
                handle.write(buf.getvalue())
            return path

        jpg = _file('jpg', (1800, 900), (180, 40, 40))
        png = _file('png', (80, 240), (20, 80, 180))
        api._role = 'guest'
        denied = api.save_product_image(1, jpg)
        self.assertEqual(denied.get('status'), 403)
        api._role = 'cashier'
        saved = api.save_product_image(1, jpg)
        self.assertTrue(saved.get('success'), saved)
        self.assertTrue(str(saved.get('image_path') or '').startswith('product-1-'))
        self.assertTrue(str(saved.get('image_path') or '').endswith('.jpg'))
        display = os.path.join(folder, saved['image_path'])
        thumb = os.path.join(folder, saved['thumb'])
        self.assertTrue(os.path.isfile(display))
        self.assertTrue(os.path.isfile(thumb))
        self.assertLessEqual(max(Image.open(display).size), 1600)
        self.assertLessEqual(max(Image.open(thumb).size), 256)
        first_name = saved['image_path']
        replaced = api.save_product_image(1, png)
        self.assertTrue(str(replaced.get('image_path') or '').endswith('.png'))
        self.assertFalse(os.path.exists(os.path.join(folder, first_name)))
        self.assertTrue(os.path.isfile(os.path.join(folder, replaced['image_path'])))
        heic = os.path.join(tmp.name, 'phone.heic')
        with open(heic, 'wb') as handle:
            handle.write(HEIC)
        blocked = api.save_product_image(1, heic)
        self.assertIn('HEIC', blocked.get('error') or '')
        self.assertTrue(os.path.isfile(os.path.join(folder, replaced['image_path'])))
        corrupt = api.save_product_image_bytes(1, b'\xff\xd8\xff\xe0' + b'\x00' * 64)
        self.assertIn('could not be shown', corrupt.get('error') or '')
        escaped = api.save_product_image_bytes(1, open(jpg, 'rb').read(), upload_name='../evil.jpg')
        self.assertEqual(escaped.get('status'), 400)
        self.assertFalse(os.path.exists(os.path.join(tmp.name, 'evil.jpg')))
        db = ac._db()
        db.execute(
            "INSERT INTO products (name,sku,price,cost_price,stock,min_stock) VALUES ('Second','PHOTO-2',10,5,3,1)"
        )
        db.commit()
        second_id = db.execute("SELECT id FROM products WHERE sku='PHOTO-2'").fetchone()['id']
        db.close()
        other = api.save_product_image(second_id, jpg)
        self.assertTrue(other.get('success'), other)
        self.assertNotEqual(other.get('image_path'), replaced.get('image_path'))
        self.assertTrue(os.path.isfile(os.path.join(folder, replaced['image_path'])))
        self.assertTrue(os.path.isfile(os.path.join(folder, other['image_path'])))
        cleared = api.clear_product_image(1)
        self.assertTrue(cleared.get('success'), cleared)
        self.assertFalse(os.path.exists(os.path.join(folder, replaced['image_path'])))
        self.assertTrue(os.path.isfile(os.path.join(folder, other['image_path'])))
        db = ac._db()
        path = db.execute("SELECT image_path FROM products WHERE id=1").fetchone()['image_path']
        other_path = db.execute("SELECT image_path FROM products WHERE id=?", (second_id,)).fetchone()['image_path']
        db.close()
        self.assertFalse(path)
        self.assertEqual(other_path, other['image_path'])
        ac._SCHEMA_READY = False


if __name__ == '__main__':
    unittest.main()
