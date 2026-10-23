"""Device move rules shared by the portal admin and the license server.

A transfer issues revoke_license once. Repeating the same move must not
queue another revoke — a stale revoke command is what kept re-locking tills.
"""
from __future__ import annotations


def classify_seat_validation(
    device_id: str,
    seats: list[dict] | None,
    activations: dict[str, list[dict]] | None = None,
    aliases: list[str] | None = None,
) -> tuple[str, str]:
    """Decide what this computer should hear on /licenses/validate.

    Returns (outcome, message). Outcomes the client may keep using are
    ``ok``, ``free``, and ``reserved``. ``moved``, ``suspended``, and
    ``revoked`` must lock the computer that no longer holds the seat.
    """
    devices = set()
    for raw in (device_id, *(aliases or [])):
        did = str(raw or "").strip()
        if did:
            devices.add(did)
    active_map = activations or {}
    relevant = [seat for seat in (seats or []) if isinstance(seat, dict)]
    if not relevant:
        return "free", "No paid seat for this product"

    def seat_id(seat: dict) -> str:
        return str(seat.get("id") or "")

    def active_ids(seat: dict) -> set[str]:
        rows = active_map.get(seat_id(seat)) or []
        found = set()
        for row in rows:
            if row.get("is_active") is False:
                continue
            did = str(row.get("device_id") or "").strip()
            if did:
                found.add(did)
        return found

    def status(seat: dict) -> str:
        return str(seat.get("status") or "active").strip().lower()

    for seat in relevant:
        if status(seat) != "active":
            continue
        if devices and devices & active_ids(seat):
            return "ok", "Valid"

    for seat in relevant:
        if status(seat) != "active":
            continue
        reserved = str(seat.get("reserved_device_id") or "").strip()
        holding = active_ids(seat)
        if holding and not (devices & holding):
            return "moved", "License transferred to another device"
        if reserved and devices and reserved not in devices and not holding:
            return "moved", "License transferred to another device"
        if not holding and (not reserved or reserved in devices):
            return "reserved", "Seat reserved for this device"

    if any(status(seat) == "suspended" for seat in relevant):
        return "suspended", "License suspended"
    if any(status(seat) == "revoked" for seat in relevant):
        return "revoked", "License revoked"
    return "free", "No paid seat for this product"


def validation_http(outcome: str, message: str) -> tuple[int, dict]:
    if outcome in ("ok", "free", "reserved"):
        return 200, {
            "ok": True,
            "outcome": outcome,
            "message": message,
            "license_type": "free" if outcome == "free" else "paid",
        }
    return 403, {"error": message, "outcome": outcome}


def classify_device_transfer(
    old_device_id: str,
    new_device_id: str,
    active_device_ids: set[str] | None = None,
) -> tuple[bool, str, bool]:
    """Return (ok, message, issue_revoke_once)."""
    old = (old_device_id or "").strip()
    new = (new_device_id or "").strip()
    active = {str(item).strip() for item in (active_device_ids or set()) if str(item).strip()}
    if not old or not new:
        return False, "old_device_id and new_device_id required", False
    if old == new or active == {new}:
        return True, "Already on this device", False
    return True, "Device transferred", True
