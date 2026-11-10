"""Normalise Daraja STK query and callback evidence before any sale is settled.

Shapes follow the documented Lipa na M-Pesa Online query and STK callback.
Fixtures built from that documentation are not captured live responses.
"""
from __future__ import annotations

import json
import re
from typing import Any


def _items(metadata: Any) -> list[dict]:
    if isinstance(metadata, dict):
        raw = metadata.get("Item") or metadata.get("item") or []
    elif isinstance(metadata, list):
        raw = metadata
    else:
        raw = []
    return [row for row in raw if isinstance(row, dict)]


def callback_metadata(payload: Any) -> dict[str, Any]:
    """Read CallbackMetadata. Duplicate names with different values are ambiguous."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return {"_ambiguous": True}
    body = payload if isinstance(payload, dict) else {}
    callback = body.get("Body", body).get("stkCallback", body) if isinstance(body, dict) else {}
    if not isinstance(callback, dict):
        return {"_ambiguous": True}
    found: dict[str, Any] = {}
    ambiguous = False
    for item in _items(callback.get("CallbackMetadata")):
        name = str(item.get("Name") or item.get("name") or "")
        if not name or "Value" not in item and "value" not in item:
            continue
        value = item.get("Value", item.get("value"))
        if name in found and found[name] != value:
            ambiguous = True
        found[name] = value
    if ambiguous:
        found["_ambiguous"] = True
    found["_checkout_request_id"] = str(
        callback.get("CheckoutRequestID") or callback.get("checkout_request_id") or ""
    )
    code = callback.get("ResultCode", callback.get("result_code"))
    found["_result_code"] = "" if code is None else str(code)
    found["_result_desc"] = str(callback.get("ResultDesc") or callback.get("result_desc") or "")
    return found


def _whole(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if abs(number - round(number)) > 0.001:
        return None
    return int(round(number))


def _receipt(value: Any) -> str:
    text = re.sub(r"\s+", "", str(value or "")).upper()
    if not re.fullmatch(r"[A-Z0-9]{6,12}", text):
        return ""
    return text


def normalise_stk_query(body: dict, *, intended_shillings: int, checkout_id: str) -> dict:
    """Decide the till state from one status-query body. Never treats an acknowledgement as payment."""
    evidence = {
        "queried": bool(body.get("queried")),
        "provider": body.get("provider") or "",
        "query_result_code": "",
        "callback_amount": None,
        "callback_receipt": "",
    }
    if not body.get("queried"):
        return _decision("unresolved", "unverified", "", "The service did not confirm this was a status query.", evidence)
    code = body.get("ResultCode", body.get("result_code"))
    if code is None or str(code) == "":
        return _decision("unresolved", "unverified", "", "The status query has no result code.", evidence)
    code_text = str(code)
    evidence["query_result_code"] = code_text
    detail = str(body.get("ResultDesc") or body.get("result_desc") or "")
    if code_text == "1032":
        return _decision("cancelled", "unverified", "", detail or "Customer cancelled the prompt.", evidence)
    if code_text == "1037":
        return _decision("timeout", "unverified", "", detail or "The prompt timed out.", evidence)
    if code_text not in {"0", "00"}:
        return _decision("failed", "unverified", "", detail or f"The prompt failed ({code_text}).", evidence)

    provider = str(body.get("provider") or "")
    amount = None
    receipt = ""
    identity = str(body.get("CheckoutRequestID") or body.get("checkout_request_id") or checkout_id or "")
    callback = callback_metadata(body.get("callback_payload"))
    if callback.get("_ambiguous"):
        return _decision("unresolved", "unverified", "", "The callback evidence is ambiguous.", evidence)
    if callback.get("Amount") is not None or callback.get("MpesaReceiptNumber"):
        if callback.get("_checkout_request_id") and checkout_id and callback["_checkout_request_id"] != checkout_id:
            return _decision("rejected", "unverified", "", "The callback is for a different prompt.", evidence)
        if callback.get("_result_code") not in {"", "0", "00"}:
            return _decision(
                "unresolved", "unverified", "",
                "The status query and the callback do not agree.",
                evidence,
            )
        amount = _whole(callback.get("Amount"))
        receipt = _receipt(callback.get("MpesaReceiptNumber"))
        evidence["callback_amount"] = amount
        evidence["callback_receipt"] = receipt
    elif provider == "mock":
        amount = _whole(body.get("Amount", body.get("amount")))
        receipt = _receipt(body.get("MpesaReceiptNumber") or body.get("mpesa_receipt_number"))
        evidence["callback_amount"] = amount
        evidence["callback_receipt"] = receipt
    if amount is None or not receipt:
        return _decision(
            "unresolved", "unverified", "",
            "The prompt succeeded at Safaricom, but the amount and receipt are not in yet. This is not payment.",
            evidence,
        )
    if identity and checkout_id and identity != checkout_id and provider != "mock":
        return _decision("rejected", "unverified", "", "The status query is for a different prompt.", evidence)
    if amount != int(intended_shillings):
        return _decision("rejected", "unverified", "", "The confirmed amount does not match this prompt.", evidence)
    verification = "verified_mock" if provider == "mock" else "verified_daraja"
    message = (
        "Simulated sandbox result. Safaricom was not contacted."
        if provider == "mock"
        else "Verified by a status query and the Safaricom receipt."
    )
    return _decision("verified", verification, receipt, message, evidence)


def _decision(state: str, verification: str, receipt: str, detail: str, evidence: dict) -> dict:
    return {
        "state": state,
        "verification": verification,
        "receipt": receipt,
        "detail": detail,
        "evidence": evidence,
    }
