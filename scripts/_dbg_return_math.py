"""Debug return revenue netting."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

tmpdir = tempfile.mkdtemp()
dbp = os.path.join(tmpdir, "t.db")
with patch("mbt_paths.get_db_path", return_value=dbp), patch(
    "desktop.utils.api_client.get_db_path", return_value=dbp
):
    import desktop.utils.api_client as ac

    ac._SCHEMA_READY = False
    api = ac.APIClient()
    api._role = "superadmin"
    api._user_id = 1
    api._username = "admin"
    db = ac._db()
    db.execute(
        "INSERT INTO users (username, password_hash, role) VALUES (?,?,?)",
        ("admin", "x:y", "superadmin"),
    )
    db.execute(
        "INSERT INTO products (name, sku, price, cost_price, stock, min_stock) "
        "VALUES (?,?,?,?,?,?)",
        ("Ret Widget", "RW1", 100.0, 40.0, 50, 5),
    )
    db.commit()
    db.close()
    api._user_id = 1
    created = api.create_sale(
        {
            "items": [
                {
                    "product_id": 1,
                    "product_name": "Ret Widget",
                    "sku": "RW1",
                    "quantity": 4,
                    "unit_price": 100.0,
                    "discount": 0,
                    "total": 400.0,
                }
            ],
            "subtotal": 400,
            "total": 400,
            "payment_method": "Cash",
            "amount_paid": 400,
            "change_amount": 0,
        }
    )
    print("created", created)
    lookup = api.get_sale_for_return(created["receipt_number"])
    line_id = int(lookup["items"][0]["id"])
    ret = api.return_sale(
        created["sale_id"],
        [{"sale_item_id": line_id, "quantity": 1}],
        "mind",
        refund_method="Cash",
    )
    print("ret", ret)
    db = ac._db()
    rows = db.execute(
        "SELECT id,status,total,created_at,sale_date FROM sales"
    ).fetchall()
    for r in rows:
        print(dict(r))
    sale_day = db.execute(
        "SELECT date(created_at) AS d FROM sales WHERE id=?",
        (created["sale_id"],),
    ).fetchone()["d"]
    print("sale_day from date(created_at)", sale_day)
    print(
        "all date exprs",
        [
            dict(x)
            for x in db.execute(
                "SELECT id, date(created_at) d1, sale_date, "
                "COALESCE(NULLIF(sale_date,''), date(created_at)) d2 FROM sales"
            ).fetchall()
        ],
    )
    db.close()
    print("summary", api.get_report_summary(sale_day, sale_day))
