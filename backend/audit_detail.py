"""Read-only presentation of one audit_log row.

Historical values come only from the text stored on the event.
The current product or receipt, when linked, is labelled as current.
"""
from __future__ import annotations

import re

_SECRET = re.compile(
    r"(?i)\b(password|passkey|pin_hash|token|secret|jwt|authorization)\b\s*[:=]\s*\S+"
)
_CHANGE = re.compile(r"([A-Za-z_]+)\s+([^,]*?)->([^,\n]*)")
_PID = re.compile(r"\bpid=(\d+)\b")
_RCP = re.compile(r"\b(RCP-\d{8}-\d+)\b")


def redact(text: str) -> str:
    return _SECRET.sub(lambda match: f"{match.group(1)}=[masked]", str(text or ""))


def parse_changes(details: str) -> list[dict]:
    changes = []
    for match in _CHANGE.finditer(redact(details or "")):
        before = match.group(2).strip()
        after = match.group(3).strip()
        changes.append({
            "field": match.group(1),
            "before": before or "Not recorded",
            "after": after or "Not recorded",
        })
    return changes


def outcome_label(action: str) -> str:
    name = (action or "").upper()
    if any(word in name for word in ("FAIL", "DENIED", "BLOCKED")):
        return "Denied or failed"
    return "Recorded"


def describe_event(row: dict, related: list | None = None, linked: dict | None = None) -> dict:
    """Fields the audit row actually contains, plus parsed before/after text."""
    details = redact(row.get("details") or "")
    recorded = row.get("created_at") or "Not recorded"
    return {
        "id": row.get("id"),
        "action": row.get("action") or "Not recorded",
        "module": row.get("module") or "Not recorded",
        "username": row.get("username") or "Not recorded",
        "user_id": row.get("user_id"),
        "role_at_event": "Not recorded",
        "created_at": recorded,
        "recorded_at": recorded,
        "occurred_at": "Not recorded separately from the log time",
        "synced_at": "Not recorded",
        "ip_address": row.get("ip_address") or "Not recorded",
        "source": "Not recorded",
        "outcome": outcome_label(row.get("action") or ""),
        "details": details or "Not recorded",
        "changes": parse_changes(details),
        "related": related or [],
        "linked": linked,
    }


def entity_needles(details: str) -> list[str]:
    text = details or ""
    needles = [f"pid={match.group(1)}" for match in _PID.finditer(text)]
    needles.extend(match.group(1) for match in _RCP.finditer(text))
    return needles


def product_id_from(details: str):
    match = _PID.search(details or "")
    return int(match.group(1)) if match else None


def receipt_from(details: str):
    match = _RCP.search(details or "")
    return match.group(1) if match else None
