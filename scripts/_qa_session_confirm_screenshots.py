"""Session QA — capture screenshot evidence for 3.0.57 fixes.

Usage:  python scripts/_qa_session_confirm_screenshots.py
Out:    QA_SCREENSHOTS_CONFIRM/  (workspace sibling of extracted/)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = Path(__file__).resolve().parents[3] / "QA_SCREENSHOTS_CONFIRM"
OUT.mkdir(parents=True, exist_ok=True)

PRODUCTS = [
    {"id": i, "name": n, "sku": s, "category": c, "price": p,
     "selling_price": p, "stock": st, "unit": "pcs"}
    for i, (n, s, c, p, st) in enumerate([
        ("DAP Fertilizer 50kg", "F-0532", "Fertilizers", 1070, 12),
        ("NPK 17:17:17 50kg", "F-0110", "Fertilizers", 1250, 8),
        ("Urea Nitrogen 50kg Bag", "F-0201", "Fertilizers", 980, 15),
        ("Maize Seed H614 2kg", "S-1001", "Seeds", 450, 40),
        ("Glyphosate Herbicide 1L", "P-2001", "Pesticides", 890, 25),
        ("Hand Hoe Heavy Duty", "T-3001", "Tools", 750, 12),
    ], start=1)
]


def _cart_seed():
    seed = []
    for i, p in enumerate(PRODUCTS[:4]):
        qty = float(i + 1)
        disc = 50.0 if i == 0 else 0.0
        seed.append({
            "product_id": p["id"],
            "product_name": p["name"],
            "sku": p.get("sku") or "",
            "category": p["category"],
            "quantity": qty,
            "unit_price": float(p["price"]),
            "discount": disc,
            "total": float(p["price"]) * qty - disc,
        })
    return seed


def _save(pix_or_widget, name: str, report: list) -> Path:
    path = OUT / name
    if hasattr(pix_or_widget, "grab"):
        ok = bool(pix_or_widget.grab().save(str(path), "PNG"))
        w, h = pix_or_widget.width(), pix_or_widget.height()
    else:
        ok = bool(pix_or_widget.save(str(path), "PNG"))
        w, h = pix_or_widget.width(), pix_or_widget.height()
    size = path.stat().st_size if path.exists() else 0
    status = "OK" if ok and size > 500 else "FAIL"
    report.append({"file": name, "status": status, "size": size, "dims": f"{w}x{h}"})
    print(f"  {status} {name} ({size}B, {w}x{h})", flush=True)
    return path


def capture_biz_day(report: list) -> None:
    from PyQt5.QtCore import QDate, Qt, QTimer
    from PyQt5.QtWidgets import QApplication, QDateEdit, QVBoxLayout, QWidget, QLabel

    from desktop.utils.theme import ThemeManager
    from desktop.pos.panel_factory import BusinessDayBar
    from desktop.utils.widgets import SecondaryBtn

    app = QApplication.instance() or QApplication(sys.argv)
    ThemeManager.apply(False, app)

    shells: list = []

    def _bar(width: int) -> tuple[QWidget, BusinessDayBar]:
        shell = QWidget()
        shells.append(shell)
        shell.setObjectName("posProductPanel")
        shell.setAttribute(Qt.WA_StyledBackground, True)
        shell.setFixedWidth(width)
        shell.setStyleSheet("QWidget#posProductPanel{background:#16213A;}")
        lay = QVBoxLayout(shell)
        bar = BusinessDayBar(shell)
        de = QDateEdit()
        de.setCalendarPopup(True)
        de.setDisplayFormat("yyyy-MM-dd")
        de.setDate(QDate(2026, 8, 16))
        de.setMinimumHeight(34)
        today = SecondaryBtn("Today", 32)
        view = SecondaryBtn("View day", 32)
        copy = SecondaryBtn("Copy sale…", 32)
        warn = QLabel("")
        warn.setObjectName("posBizDayWarn")
        bar.setup(None, de, (
            (today, "Today", "Today"),
            (view, "View", "View day"),
            (copy, "Copy", "Copy sale…"),
        ), warn)
        lay.addWidget(bar)
        shell.show()
        for _ in range(20):
            app.processEvents()
        return shell, bar

    # Wide: bordered clickable button
    shell_wide, bar_wide = _bar(720)
    _save(bar_wide, "biz_day_button_3057.png", report)

    # Stacked two-row layout (narrow catalog column)
    shell_stack, bar_stack = _bar(420)
    _save(bar_stack, "biz_day_stacked_narrow.png", report)

    # Calendar dialog (same widget pick_shop_day_dialog opens on click)
    from PyQt5.QtWidgets import QDialog, QCalendarWidget, QDialogButtonBox

    cal_dlg = QDialog(shell_wide.window())
    cal_dlg.setWindowTitle("Select business day")
    cal_dlg.setMinimumWidth(340)
    dlg_lay = QVBoxLayout(cal_dlg)
    dlg_lay.setContentsMargins(12, 12, 12, 12)
    cal = QCalendarWidget(cal_dlg)
    cal.setSelectedDate(QDate(2026, 8, 16))
    cal.setMinimumDate(QDate(2000, 1, 1))
    cal.setMaximumDate(QDate(2026, 8, 17))
    bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    dlg_lay.addWidget(cal)
    dlg_lay.addWidget(bb)
    cal_dlg.show()
    for _ in range(30):
        app.processEvents()
    _save(cal_dlg, "biz_day_calendar_open_3057.png", report)
    cal_dlg.close()


def capture_checkout_pro(app, report: list) -> None:
    from PyQt5.QtWidgets import QFrame, QPushButton, QWidget
    from PyQt5.QtCore import Qt

    from desktop.utils.api_client import APIClient
    from desktop.tabs.sales_tab import SalesTab
    from desktop.pos.layout_ids import LAYOUT_CHECKOUT_PRO
    from desktop.pos.layouts import splitters
    from desktop.pos.checkout_pro_chrome import (
        apply_checkout_pro_chrome, sync_pro_square_layout, sync_category_chips,
    )
    from desktop.utils.no_wheel_spinbox import install_no_wheel_spinboxes
    from desktop.utils.no_wheel_small_scroll import install_no_wheel_small_scroll

    install_no_wheel_spinboxes(app)
    install_no_wheel_small_scroll(app)

    db = ROOT / "data" / "mbt_pos.db"
    api = APIClient(str(db))
    user = {"id": 1, "username": "admin", "role": "superadmin", "full_name": "QA"}

    def _find_frame(tab, obj: str):
        for fr in tab.findChildren(QFrame):
            if fr.objectName() == obj and fr.isVisible():
                return fr
        return None

    def _seed_tab(tab):
        tab.products = [dict(p) for p in PRODUCTS]
        try:
            tab._cat.blockSignals(True)
            tab._cat.clear()
            tab._cat.addItem("All Categories")
            for c in ("Fertilizers", "Seeds", "Pesticides", "Tools"):
                tab._cat.addItem(c)
            tab._cat.setCurrentIndex(0)
        finally:
            try:
                tab._cat.blockSignals(False)
            except Exception:
                pass
        tab.set_checkout_layout(LAYOUT_CHECKOUT_PRO, animate=False)
        for _ in range(30):
            app.processEvents()
        apply_checkout_pro_chrome(tab)
        sync_pro_square_layout(tab)
        try:
            sync_category_chips(tab)
        except Exception:
            pass
        try:
            tab._show_empty_overlay(False)
        except Exception:
            pass
        grid = getattr(tab, "_prod_grid", None)
        if grid is not None and hasattr(grid, "populate"):
            grid.set_currency("KES")
            if hasattr(grid, "set_pro_density"):
                grid.set_pro_density(True)
            grid.populate(tab.products, columns=2)
        tab.cart = _cart_seed()
        tab._cart_select_idx = 0
        tab._refresh_cart()
        tab._recalc()
        try:
            tab._paid.setValue(float(tab._total))
            tab._calc_change()
        except Exception:
            pass
        for _ in range(40):
            app.processEvents()

    for wh, tag in ((1024, "1024"), (1280, "1280")):
        tab = SalesTab(api, user, str(db), lambda: {})
        # Mimic shell: sidebar ~132px, tab chrome ~60px
        tab.resize(wh - 132, wh - 60)
        tab.setWindowTitle(f"MBT POS QA Checkout Pro {wh}²")
        tab.show()
        for _ in range(30):
            app.processEvents()
        _seed_tab(tab)
        sync_pro_square_layout(tab)
        for _ in range(20):
            app.processEvents()

        _save(tab, f"checkout_pro_{tag}.png", report)

        actions = _find_frame(tab, "posActionsPanel")
        if actions is not None:
            _save(actions, f"pos_buttons_rail_{tag}.png", report)

        # Complete Sale visibility probe
        complete = None
        for btn in tab.findChildren(QPushButton):
            txt = (btn.text() or "").strip().lower()
            if "complete sale" in txt or "complete" in txt:
                complete = btn
                break
        if complete is not None:
            vis = complete.isVisible() and complete.width() > 0 and complete.height() > 0
            report.append({
                "probe": f"complete_sale_{tag}",
                "visible": vis,
                "geom": f"{complete.width()}x{complete.height()}",
            })
            print(f"  Complete Sale @ {tag}: visible={vis} {complete.width()}x{complete.height()}", flush=True)

        tab.close()
        for _ in range(10):
            app.processEvents()

    # Cart splitter narrow — one tab at 1280
    tab = SalesTab(api, user, str(db), lambda: {})
    tab.resize(1280 - 132, 1280 - 60)
    tab.show()
    for _ in range(30):
        app.processEvents()
    _seed_tab(tab)

    sp = tab._pos_splitter
    cs = tab._cart_splitter
    if sp and sp.count() >= 2:
        moved = list(sp.sizes())
        delta = min(100, moved[0] - sp.widget(0).minimumWidth())
        if delta > 0:
            moved[0] -= delta
            moved[1] += delta
            sp.setSizes(moved)
            splitters._on_moved(tab)
            for _ in range(15):
                app.processEvents()
    if cs and cs.count() == 2:
        moved = list(cs.sizes())
        delta = min(80, moved[0] - cs.widget(0).minimumHeight())
        if delta > 0:
            moved[0] -= delta
            moved[1] += delta
            cs.setSizes(moved)
            splitters._on_cart_moved(tab)
            for _ in range(15):
                app.processEvents()

    _save(tab, "cart_narrow_splitter.png", report)
    sale = _find_frame(tab, "posSalePanel")
    if sale is not None:
        _save(sale, "cart_narrow_sale_stack.png", report)

    # Clip probe on payment rail
    rail = tab._right_panel
    clipped = []
    if rail is not None:
        for ch in rail.findChildren(QWidget):
            if not ch.isVisible():
                continue
            demand = max(ch.minimumSizeHint().width(), ch.minimumWidth())
            if demand > rail.width() - 8:
                clipped.append(type(ch).__name__)
    report.append({"probe": "rail_clip", "clipped": clipped or "none"})
    print(f"  rail clip probe: {clipped or 'none'}", flush=True)

    tab.close()


def main() -> int:
    # Prefer native Windows for accurate grabs
    os.environ.setdefault("QT_QPA_PLATFORM", "windows")

    from PyQt5.QtWidgets import QApplication, QWidget
    from PyQt5.QtCore import Qt

    app = QApplication(sys.argv)
    app.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    report: list = []
    print(f"Capturing -> {OUT}", flush=True)

    try:
        capture_biz_day(report)
    except Exception as exc:
        report.append({"error": "biz_day", "msg": str(exc)})
        print(f"  FAIL biz_day: {exc}", flush=True)

    try:
        capture_checkout_pro(app, report)
    except Exception as exc:
        report.append({"error": "checkout_pro", "msg": str(exc)})
        print(f"  FAIL checkout_pro: {exc}", flush=True)

    meta = {
        "version": "3.0.57",
        "out_dir": str(OUT),
        "platform": os.environ.get("QT_QPA_PLATFORM"),
        "captures": report,
    }
    (OUT / "report.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"DONE -> {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
