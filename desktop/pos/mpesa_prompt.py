"""Phone-prompt controls on the existing sale screen. Manual M-Pesa stays available."""
from __future__ import annotations

import uuid

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QComboBox, QLabel, QLineEdit, QPushButton

from desktop.utils.theme import C


def wire_mpesa_prompt(tab) -> None:
    frame = getattr(tab, "_mpesa_frame", None)
    if frame is None or getattr(tab, "_mpesa_prompt_wired", False):
        return
    tab._mpesa_prompt_wired = True
    layout = frame.layout()
    tab._mpesa_profile = QComboBox()
    tab._mpesa_profile.setMinimumHeight(36)
    tab._mpesa_phone = QLineEdit()
    tab._mpesa_phone.setPlaceholderText("Customer phone for the prompt, 07…")
    tab._mpesa_phone.setMinimumHeight(40)
    tab._mpesa_prompt_status = QLabel(
        "Manual M-Pesa is still available. A phone prompt is not payment until it is verified."
    )
    tab._mpesa_prompt_status.setWordWrap(True)
    tab._mpesa_prompt_status.setStyleSheet(
        f"color:{C['text2']}; font-size:12px; background:transparent;"
    )
    send = QPushButton("Send phone prompt")
    send.setMinimumHeight(40)
    send.clicked.connect(lambda: _send(tab))
    layout.addWidget(tab._mpesa_profile)
    layout.addWidget(tab._mpesa_phone)
    layout.addWidget(send)
    layout.addWidget(tab._mpesa_prompt_status)
    tab._mpesa_payment_id = ""
    tab._mpesa_prompt_state = ""
    tab._mpesa_idempotency = ""
    tab._mpesa_timer = QTimer(tab)
    tab._mpesa_timer.setInterval(3000)
    tab._mpesa_timer.timeout.connect(lambda: _poll(tab))
    _load_profiles(tab)


def _load_profiles(tab) -> None:
    from backend.mpesa_service import MpesaSaleError, connect, list_profiles
    combo = tab._mpesa_profile
    combo.clear()
    combo.addItem("Manual only", "")
    db = connect()
    try:
        rows = list_profiles(db, getattr(tab, "user", {}) or {})
    except MpesaSaleError:
        rows = []
    finally:
        db.close()
    for row in rows:
        if row.get("status") != "active":
            continue
        label = row.get("name") or "Profile"
        if row.get("till_number"):
            label += f" · Till {row['till_number']}"
        if row.get("paybill_number"):
            label += f" · Paybill {row['paybill_number']}"
        combo.addItem(label, row.get("id"))
        if row.get("is_default"):
            combo.setCurrentIndex(combo.count() - 1)


def _amount(tab) -> float:
    if hasattr(tab, "_tender_lines") and hasattr(tab, "_using_tender_lines") and tab._using_tender_lines():
        from backend.mpesa_service import _is_mpesa
        return round(sum(
            float(row.get("amount") or 0)
            for row in tab._tender_lines.rows()
            if _is_mpesa(str(row.get("method") or ""))
        ), 2)
    method = tab._pay.currentText() if hasattr(tab, "_pay") else "M-Pesa"
    if method == "M-Pesa" and hasattr(tab, "_amount_due"):
        return float(tab._amount_due() or 0)
    if hasattr(tab, "_elec_portion"):
        return float(tab._elec_portion() or 0)
    return float(tab._paid.value() or 0) if hasattr(tab, "_paid") else 0


def _apply(tab, payment: dict) -> None:
    tab._mpesa_payment_id = payment.get("id") or ""
    tab._mpesa_prompt_state = payment.get("state") or ""
    tab._mpesa_prompt_status.setText(payment.get("customer_message") or payment.get("state") or "")
    if payment.get("state") == "verified" and payment.get("receipt_code"):
        tab._mpesa_ref.setText(payment["receipt_code"])
        tab._mpesa_timer.stop()
    elif payment.get("state") in {"failed", "cancelled", "timeout", "rejected"}:
        tab._mpesa_timer.stop()
        tab._mpesa_idempotency = ""
    elif payment.get("state") == "unknown":
        tab._mpesa_timer.stop()


def _send(tab) -> None:
    from backend.mpesa_service import MpesaSaleError, connect, start_stk
    profile_id = tab._mpesa_profile.currentData() or ""
    if not profile_id:
        tab._mpesa_prompt_status.setText("Choose an active merchant profile, or record the code manually.")
        return
    if not tab._mpesa_idempotency:
        tab._mpesa_idempotency = str(uuid.uuid4())
    db = connect()
    try:
        payment = start_stk(
            db, getattr(tab, "user", {}) or {},
            phone=tab._mpesa_phone.text(),
            amount=_amount(tab),
            profile_id=str(profile_id),
            sale_reference="",
            idempotency_key=tab._mpesa_idempotency,
        )
    except MpesaSaleError as exc:
        tab._mpesa_prompt_status.setText(str(exc))
        return
    finally:
        db.close()
    _apply(tab, payment)
    if payment.get("state") in {"prompt_sent", "sending", "waiting"}:
        tab._mpesa_timer.start()


def _poll(tab) -> None:
    from backend.mpesa_service import MpesaSaleError, connect, poll_payment
    if not tab._mpesa_payment_id:
        tab._mpesa_timer.stop()
        return
    db = connect()
    try:
        payment = poll_payment(db, getattr(tab, "user", {}) or {}, tab._mpesa_payment_id)
    except MpesaSaleError as exc:
        tab._mpesa_prompt_status.setText(str(exc))
        tab._mpesa_timer.stop()
        return
    finally:
        db.close()
    _apply(tab, payment)
