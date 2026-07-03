"""Quick smoke test for MBT POS critical flows."""
import sys
import uuid

def main():
    lines = []
    errors = []

    def ok(msg):
        lines.append(f"OK  {msg}")

    def fail(msg, exc=None):
        lines.append(f"FAIL {msg}: {exc}")
        errors.append(msg)

    try:
        from mbt_paths import get_project_root, get_db_path, ensure_data_dirs
        root = ensure_data_dirs(get_project_root())
        ok(f"project_root={root}")
        ok(f"database={get_db_path()}")
    except Exception as e:
        fail("mbt_paths", e)
        root = None

    try:
        from licensing.license_engine import LicenseEngine, resolve_device_id
        did = resolve_device_id()
        ok(f"device_id={did[:12]}...")
        eng = LicenseEngine(root)
        ok(f"license state={eng.state} valid={eng.is_valid}")
    except Exception as e:
        fail("license_engine", e)
        eng = None
        did = "0" * 40

    try:
        from desktop.utils.api_client import APIClient
        api = APIClient()
        api._user_id = 1
        api._username = "admin"
        api._role = "admin"
        sku = "FLOW-" + uuid.uuid4().hex[:8]
        d = {
            "name": "Flow Test Product",
            "sku": sku,
            "price": 99.0,
            "cost_price": 50.0,
            "min_stock": 2,
            "unit": "pcs",
            "stock": 1,
        }
        r1 = api.create_product(d)
        r2 = api.create_product(d)
        if r1.get("success"):
            ok(f"create_product id={r1.get('id')}")
        else:
            fail("create_product", r1)
        if r2.get("error"):
            ok("duplicate SKU returns error (no crash)")
        else:
            fail("duplicate SKU should return error", r2)
    except Exception as e:
        fail("api create_product", e)

    try:
        from PyQt5.QtWidgets import QApplication
        from licensing.activation_ui import ActivationDialog

        app = QApplication.instance() or QApplication(sys.argv)
        dlg = ActivationDialog(did, eng)
        ok(
            f"activation dialog {dlg.minimumSize().width()}x"
            f"{dlg.minimumSize().height()} "
            f"buttons: act={dlg._act_btn.isVisible()} "
            f"tg={dlg._tg_btn.isVisible()}"
        )
    except Exception as e:
        fail("activation_ui", e)

    try:
        import launcher
        ok("launcher module loads")
    except Exception as e:
        fail("launcher", e)

    report = "\n".join(lines)
    print(report)
    with open("flow_check_result.txt", "w", encoding="utf-8") as f:
        f.write(report + "\n")
        f.write(f"errors={len(errors)}\n")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
