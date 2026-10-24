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
        jpg = os.path.join(tmp.name, 'shop photo.jpg')
        png = os.path.join(tmp.name, 'صورة.png')
        with open(jpg, 'wb') as handle:
            handle.write(JPEG)
        with open(png, 'wb') as handle:
            handle.write(PNG)
        api._role = 'guest'
        denied = api.save_product_image(1, jpg)
        self.assertEqual(denied.get('status'), 403)
        api._role = 'cashier'
        saved = api.save_product_image(1, jpg)
        self.assertTrue(saved.get('success'), saved)
        self.assertEqual(saved.get('image_path'), 'product-1.jpg')
        replaced = api.save_product_image(1, png)
        self.assertEqual(replaced.get('image_path'), 'product-1.png')
        folder = os.path.join(data_root, 'data', 'product-images')
        self.assertFalse(os.path.exists(os.path.join(folder, 'product-1.jpg')))
        self.assertTrue(os.path.isfile(os.path.join(folder, 'product-1.png')))
        heic = os.path.join(tmp.name, 'phone.heic')
        with open(heic, 'wb') as handle:
            handle.write(HEIC)
        blocked = api.save_product_image(1, heic)
        self.assertIn('HEIC', blocked.get('error') or '')
        self.assertTrue(os.path.isfile(os.path.join(folder, 'product-1.png')))
        cleared = api.clear_product_image(1)
        self.assertTrue(cleared.get('success'), cleared)
        self.assertFalse(os.path.exists(os.path.join(folder, 'product-1.png')))
        db = ac._db()
        path = db.execute("SELECT image_path FROM products WHERE id=1").fetchone()['image_path']
        db.close()
        self.assertFalse(path)
        ac._SCHEMA_READY = False


if __name__ == '__main__':
    unittest.main()
