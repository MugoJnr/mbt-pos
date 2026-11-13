"""Debug POS snappy cache freshness."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])
db = Path(os.environ.get("LOCALAPPDATA", "")) / "MugoByte" / "MBT POS" / "data" / "mbt_pos.db"
if not db.exists():
    db = Path(os.environ.get("LOCALAPPDATA", "")) / "MugoByte" / "MBT POS" / "mbt_pos.db"
print("db", db, "exists", db.exists())
from desktop.utils.api_client import APIClient
from desktop.tabs.sales_tab import SalesTab

api = APIClient(str(db))
prods = api.get_products() or []
print("product_count", len(prods))
tab = SalesTab(api, {"id": 1, "username": "admin", "role": "superadmin", "full_name": "T"}, str(db), lambda: {})
print("before", tab._catalog_loaded, tab._catalog_mono, tab._grid_painted, len(tab.products or []))
tab.refresh(force=True, defer_grid=False)
print(
    "after refresh",
    "loaded",
    tab._catalog_loaded,
    "fresh",
    tab._catalog_is_fresh(),
    "painted",
    tab._grid_painted,
    "n",
    len(tab.products or []),
    "ttl",
    tab._catalog_ttl_s,
)
with mock.patch.object(tab.api, "get_products") as gp:
    tab.refresh()
    print("second refresh call_count", gp.call_count)
