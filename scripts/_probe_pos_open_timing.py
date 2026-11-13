"""Probe Point of Sale tab open cost (local DB)."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication


def main():
    app = QApplication.instance() or QApplication([])
    db = Path(os.environ.get("LOCALAPPDATA", "")) / "MugoByte" / "MBT POS" / "data" / "mbt_pos.db"
    if not db.is_file():
        db = Path(os.environ.get("LOCALAPPDATA", "")) / "MugoByte" / "MBT POS" / "mbt_pos.db"
    print("db", db, db.is_file())
    from desktop.utils.api_client import APIClient

    api = APIClient(str(db))

    def timed(label, fn):
        t0 = time.perf_counter()
        out = fn()
        ms = (time.perf_counter() - t0) * 1000
        print(f"{label}: {ms:.1f}ms")
        return out, ms

    prods, _ = timed("get_products", api.get_products)
    print("  count", len(prods or []))
    cust, _ = timed("get_customers", api.get_customers)
    print("  count", len(cust or []))
    cats, _ = timed("get_categories", api.get_categories)
    print("  count", len(cats or []))

    from desktop.tabs.sales_tab import SalesTab

    def build():
        return SalesTab(
            api,
            {"id": 1, "username": "admin", "role": "superadmin", "full_name": "T"},
            str(db),
            lambda: {},
        )

    tab, init_ms = timed("SalesTab.__init__", build)
    _, r1 = timed("refresh#1", tab.refresh)
    _, r2 = timed("refresh#2", tab.refresh)
    _, os_ms = timed("on_show", tab.on_show)
    _, lay = timed(
        "set_checkout_layout(checkout_pro)",
        lambda: tab.set_checkout_layout("checkout_pro", animate=False),
    )
    _, lay2 = timed(
        "set_checkout_layout(same)",
        lambda: tab.set_checkout_layout("checkout_pro", animate=False),
    )
    cards = len(getattr(tab._prod_grid, "_products", []) or [])
    print(
        f"SUMMARY init={init_ms:.0f} refresh={r1:.0f}/{r2:.0f} "
        f"on_show={os_ms:.0f} layout={lay:.0f}/{lay2:.0f} cards={cards}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
