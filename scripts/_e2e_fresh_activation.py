"""E2E Phase 5: Fresh install cloud sign-in activation via ActivationDialog UI."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
os.chdir(ROOT)

STATE = json.loads((ROOT / "logs" / "_e2e_fresh_user_state.json").read_text(encoding="utf-8"))
EMAIL = STATE["email"]
PASSWORD = STATE["password"]
LICENSE_KEY = (STATE.get("license") or {}).get("license_key", "")

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication

from desktop.utils.theme import ensure_fonts
from licensing.license_engine import LicenseEngine
from licensing.activation_ui import ActivationDialog

ensure_fonts()
app = QApplication.instance() or QApplication(sys.argv)
engine = LicenseEngine(str(ROOT))
print("DEVICE", engine.device_id[:16], "STATE", engine.state)
dlg = ActivationDialog(engine.device_id, engine)
dlg.show()

result = {"ok": False}


def drive():
    dlg._cloud_email.setText(EMAIL)
    dlg._cloud_pw.setText(PASSWORD)
    dlg._cloud_signin_activate()
    QTimer.singleShot(8000, check)


def check():
    st = engine.state
    lic = engine.load_license_info() if hasattr(engine, "load_license_info") else {}
    print("POST_SIGNIN state=", st, "lic=", bool(getattr(engine, "license_key", None)))
    if engine.is_licensed():
        result.update({"ok": True, "method": "cloud_signin", "state": st})
        app.quit()
        return
    if LICENSE_KEY:
        dlg._key_input.setText(LICENSE_KEY)
        dlg._activate()
        QTimer.singleShot(6000, check_key)


def check_key():
    print("POST_KEY state=", engine.state, "licensed=", engine.is_licensed())
    if engine.is_licensed():
        result.update({"ok": True, "method": "license_key", "state": engine.state})
    else:
        msg = dlg._result_lbl.text() if hasattr(dlg, "_result_lbl") else ""
        result.update({"ok": False, "error": msg or "activation failed", "state": engine.state})
    app.quit()


QTimer.singleShot(1500, drive)
app.exec_()

# persistence check
engine2 = LicenseEngine(str(ROOT))
out = {
    "activation": result,
    "licensed_after": engine2.is_licensed(),
    "state_after": engine2.state,
    "device_id": engine2.device_id,
}
print("RESULT", json.dumps(out, indent=2))
STATE["activation"] = out
STATE["completed_phases"] = list(set(STATE.get("completed_phases", []) + ["4", "5"]))
STATE["failed"] = not out.get("licensed_after")
(ROOT / "logs" / "_e2e_fresh_user_state.json").write_text(json.dumps(STATE, indent=2), encoding="utf-8")
raise SystemExit(0 if out.get("licensed_after") else 1)
