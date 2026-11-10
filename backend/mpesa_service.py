"""Shop M-Pesa ledger.

The till and the web dashboard both use this module. Daraja credentials stay
on the separate payment service. A prompt acknowledgement is not a payment.
A sale is marked verified only after a status query returns the same amount.
"""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from urllib import error as urlerror
from urllib import request as urlrequest

from mbt_paths import get_data_dir, get_db_path


class MpesaSaleError(ValueError):
    """The sale must not be saved with this M-Pesa claim."""


OPEN_STATES = {"preparing", "sending", "prompt_sent", "waiting", "unknown"}
TERMINAL_STATES = {"verified", "failed", "cancelled", "timeout", "rejected"}
_CODE = re.compile(r"^[A-Z0-9]{6,12}$")
_PHONE_DIGITS = re.compile(r"\D+")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _is_mpesa(name: str) -> bool:
    key = str(name or "").lower().replace("-", "").replace(" ", "")
    return "mpesa" in key


def _role(actor) -> str:
    if isinstance(actor, dict):
        return str(actor.get("role") or "").lower()
    return str(actor or "").lower()


def _actor_name(actor) -> str:
    if isinstance(actor, dict):
        return str(actor.get("username") or actor.get("full_name") or "staff")
    return "staff"


def can_configure(actor) -> bool:
    return _role(actor) in {"admin", "superadmin"}


def can_view(actor) -> bool:
    return _role(actor) in {"manager", "admin", "superadmin"}


def can_operate(actor) -> bool:
    return _role(actor) in {"cashier", "manager", "admin", "superadmin"}


def can_override(actor) -> bool:
    return _role(actor) in {"manager", "admin", "superadmin"}


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(get_db_path(), timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_tables(db: sqlite3.Connection) -> None:
    db.execute(
        """CREATE TABLE IF NOT EXISTS mpesa_profiles (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            merchant_type TEXT NOT NULL,
            till_number TEXT,
            paybill_number TEXT,
            shortcode TEXT,
            business_name TEXT,
            account_reference_label TEXT,
            callback_url TEXT,
            branch_id INTEGER,
            environment TEXT NOT NULL DEFAULT 'sandbox',
            status TEXT NOT NULL DEFAULT 'draft',
            is_default INTEGER NOT NULL DEFAULT 0,
            credentials_stored INTEGER NOT NULL DEFAULT 0,
            created_at TEXT,
            updated_at TEXT
        )"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS mpesa_payments (
            id TEXT PRIMARY KEY,
            idempotency_key TEXT UNIQUE,
            profile_id TEXT,
            branch_id INTEGER,
            kind TEXT NOT NULL,
            state TEXT NOT NULL,
            amount_shillings INTEGER,
            amount_text TEXT,
            phone TEXT,
            phone_masked TEXT,
            sale_reference TEXT,
            checkout_request_id TEXT,
            merchant_request_id TEXT,
            receipt_code TEXT,
            verification TEXT NOT NULL DEFAULT 'unverified',
            provider TEXT,
            result_code TEXT,
            result_detail TEXT,
            sale_id INTEGER,
            released INTEGER NOT NULL DEFAULT 0,
            created_at TEXT,
            updated_at TEXT
        )"""
    )
    db.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS mpesa_receipt_code_unique
           ON mpesa_payments(receipt_code)
           WHERE receipt_code IS NOT NULL AND receipt_code != ''"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS mpesa_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payment_id TEXT,
            actor TEXT,
            action TEXT,
            detail TEXT,
            created_at TEXT
        )"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS mpesa_incoming (
            id TEXT PRIMARY KEY,
            provider_ref TEXT UNIQUE,
            profile_id TEXT,
            amount_shillings INTEGER,
            phone_masked TEXT,
            account_reference TEXT,
            state TEXT NOT NULL,
            sale_id INTEGER,
            detail TEXT,
            created_at TEXT,
            updated_at TEXT
        )"""
    )
    cols = {row[1] for row in db.execute("PRAGMA table_info(sales)").fetchall()}
    if "mpesa_verification" not in cols:
        db.execute("ALTER TABLE sales ADD COLUMN mpesa_verification TEXT")
    payment_cols = {row[1] for row in db.execute("PRAGMA table_info(mpesa_payments)").fetchall()}
    if "evidence_json" not in payment_cols:
        db.execute("ALTER TABLE mpesa_payments ADD COLUMN evidence_json TEXT")
    db.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS mpesa_sale_reference_unique
           ON mpesa_payments(sale_reference)
           WHERE sale_reference IS NOT NULL AND sale_reference != ''"""
    )


def normalize_phone(raw: str) -> str:
    digits = _PHONE_DIGITS.sub("", raw or "")
    if digits.startswith("254") and len(digits) == 12:
        phone = digits
    elif digits.startswith("0") and len(digits) == 10:
        phone = "254" + digits[1:]
    elif len(digits) == 9:
        phone = "254" + digits
    else:
        raise MpesaSaleError("Enter the customer phone as 07… or 2547….")
    if not phone.startswith("254") or len(phone) != 12 or phone[3] not in "17":
        raise MpesaSaleError("Enter a Kenyan mobile number.")
    return phone


def mask_phone(phone: str) -> str:
    if len(phone) < 7:
        return "hidden"
    return phone[:4] + "***" + phone[-3:]


def normalize_code(raw: str) -> str:
    code = re.sub(r"\s+", "", (raw or "")).upper()
    if not code:
        return ""
    if not _CODE.fullmatch(code):
        raise MpesaSaleError("The M-Pesa code must be 6 to 12 letters or numbers.")
    return code


def whole_shillings(amount) -> int:
    try:
        number = round(float(amount), 2)
    except (TypeError, ValueError):
        raise MpesaSaleError("Enter the amount to request.")
    if number <= 0:
        raise MpesaSaleError("The M-Pesa amount must be more than zero.")
    if abs(number - round(number)) > 0.001:
        raise MpesaSaleError(
            "A phone prompt can request whole shillings only. Record the cents as a manual payment."
        )
    return int(round(number))


def _setting(db, key: str, default: str = "") -> str:
    try:
        row = db.execute("SELECT value FROM system_settings WHERE key=?", (key,)).fetchone()
    except sqlite3.Error:
        return default
    if not row or row[0] is None:
        return default
    return str(row[0])


def _set_setting(db, key: str, value: str) -> None:
    db.execute(
        "INSERT INTO system_settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def shop_tenant(db) -> str:
    current = _setting(db, "mpesa_tenant_id")
    if current:
        return current
    tenant = "shop-" + uuid.uuid4().hex
    _set_setting(db, "mpesa_tenant_id", tenant)
    return tenant


def _gateway_file() -> str:
    import os
    return os.path.join(get_data_dir(), "mpesa_service.json")


def gateway_config(db) -> dict:
    url = _setting(db, "daraja_gateway_url").strip().rstrip("/")
    token = ""
    try:
        with open(_gateway_file(), encoding="utf-8") as handle:
            loaded = json.load(handle)
        token = str(loaded.get("service_token") or "")
    except (OSError, json.JSONDecodeError):
        token = ""
    return {"url": url, "token_configured": bool(token), "_token": token}


def save_service_token(token: str) -> None:
    import os
    path = _gateway_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"service_token": token.strip()}, handle)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _audit(db, payment_id: str, actor, action: str, detail: str) -> None:
    db.execute(
        "INSERT INTO mpesa_audit (payment_id, actor, action, detail, created_at) VALUES (?,?,?,?,?)",
        (payment_id, _actor_name(actor), action, detail[:300], _now()),
    )


def _public_payment(row) -> dict:
    data = dict(row)
    data.pop("phone", None)
    data.pop("idempotency_key", None)
    data["simulated"] = data.get("provider") == "mock"
    data["safaricom_confirmed"] = data.get("verification") == "verified_daraja"
    if data.get("state") == "verified" and data.get("simulated"):
        data["customer_message"] = "Simulated sandbox result. Safaricom was not contacted."
    elif data.get("state") == "verified":
        data["customer_message"] = "Payment verified by a status query."
    elif data.get("state") == "unknown":
        data["customer_message"] = "The result is unknown. Another prompt will not be sent."
    elif data.get("state") == "prompt_sent":
        data["customer_message"] = "Prompt sent. Waiting for the customer. This is not payment."
    elif data.get("state") == "waiting":
        data["customer_message"] = data.get("result_detail") or "Waiting for the amount and receipt. This is not payment."
    else:
        data["customer_message"] = data.get("result_detail") or data.get("state") or ""
    return data


def _public_profile(row) -> dict:
    data = dict(row)
    data["credentials_stored"] = bool(data.get("credentials_stored"))
    data["is_default"] = bool(data.get("is_default"))
    data["secrets_visible"] = False
    return data


def current_branch_id(db):
    try:
        row = db.execute("SELECT id FROM cc_branches WHERE is_current=1 LIMIT 1").fetchone()
    except sqlite3.Error:
        return None
    return int(row[0]) if row else None


def list_profiles(db, actor) -> list:
    if not can_operate(actor):
        raise MpesaSaleError("You cannot view M-Pesa profiles.")
    ensure_tables(db)
    rows = db.execute("SELECT * FROM mpesa_profiles ORDER BY is_default DESC, name").fetchall()
    branch = current_branch_id(db)
    visible = []
    for row in rows:
        if _role(actor) == "cashier" and row["branch_id"] and branch and int(row["branch_id"]) != branch:
            continue
        if _role(actor) == "cashier" and row["status"] != "active":
            continue
        visible.append(_public_profile(row))
    return visible


def _lab(db, method: str, path: str, body: dict | None = None, timeout: int = 20):
    cfg = gateway_config(db)
    if not cfg["url"]:
        raise MpesaSaleError("Set the payment service address in M-Pesa settings. Checkout was not sent.")
    url = cfg["url"] + path
    payload = None if body is None else json.dumps(body).encode()
    headers = {
        "Content-Type": "application/json",
        "X-Tenant-ID": shop_tenant(db),
        "Accept": "application/json",
    }
    if cfg["_token"]:
        headers["Authorization"] = "Bearer " + cfg["_token"]
    req = urlrequest.Request(url, data=payload, headers=headers, method=method)
    try:
        with urlrequest.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode() or "{}"
            parsed = json.loads(raw)
            return response.status, parsed if isinstance(parsed, dict) else {"raw": parsed}
    except urlerror.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:240]
        try:
            parsed = json.loads(detail)
            detail = str(parsed.get("detail") or parsed.get("error") or detail)
        except json.JSONDecodeError:
            pass
        raise MpesaSaleError(f"Payment service returned HTTP {exc.code}. {detail}") from exc
    except (urlerror.URLError, TimeoutError, OSError) as exc:
        raise MpesaSaleError("Payment service did not answer. No second prompt was sent.") from exc


def create_profile(db, actor, fields: dict) -> dict:
    if not can_configure(actor):
        raise MpesaSaleError("Only an admin can save a merchant profile.")
    ensure_tables(db)
    environment = str(fields.get("environment") or "sandbox").lower()
    if environment != "sandbox":
        raise MpesaSaleError("Production is not enabled.")
    merchant_type = str(fields.get("merchant_type") or "").lower()
    if merchant_type not in {"till", "paybill"}:
        raise MpesaSaleError("Choose Buy Goods Till or Paybill.")
    name = str(fields.get("name") or "").strip()[:80]
    shortcode = re.sub(r"\s+", "", str(fields.get("shortcode") or ""))
    till_number = re.sub(r"\s+", "", str(fields.get("till_number") or ""))
    paybill_number = re.sub(r"\s+", "", str(fields.get("paybill_number") or ""))
    if not name or not shortcode:
        raise MpesaSaleError("Enter a profile name and the business shortcode.")
    if merchant_type == "till" and not till_number:
        till_number = shortcode
    if merchant_type == "paybill" and not paybill_number:
        paybill_number = shortcode
    callback = str(fields.get("callback_url") or "").strip()
    if not callback:
        callback = gateway_config(db)["url"] + "/api/v1/webhooks/stk-callback"
    key = str(fields.get("consumer_key") or "")
    secret = str(fields.get("consumer_secret") or "")
    passkey = str(fields.get("passkey") or "")
    if not key or not secret or not passkey:
        raise MpesaSaleError("Enter the consumer key, consumer secret, and passkey once. They are not shown again.")
    body = {
        "name": name,
        "display_name": str(fields.get("business_name") or name)[:120],
        "merchant_type": merchant_type,
        "shortcode": shortcode,
        "paybill_number": paybill_number or None,
        "callback_url": callback,
        "business_name": str(fields.get("business_name") or name)[:120],
        "account_reference_label": str(fields.get("account_reference_label") or "Invoice")[:40],
        "consumer_key": key,
        "consumer_secret": secret,
        "passkey": passkey,
        "environment": "sandbox",
    }
    _status, created = _lab(db, "POST", "/api/v1/profiles", body)
    profile_id = str(created.get("id") or "")
    if not profile_id:
        raise MpesaSaleError("The payment service did not save the profile. Nothing was stored on this till.")
    now = _now()
    branch = fields.get("branch_id")
    db.execute(
        """INSERT INTO mpesa_profiles
           (id, name, merchant_type, till_number, paybill_number, shortcode, business_name,
            account_reference_label, callback_url, branch_id, environment, status,
            is_default, credentials_stored, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?, 'sandbox', 'draft', 0, 1, ?, ?)""",
        (
            profile_id, name, merchant_type, till_number, paybill_number, shortcode,
            body["business_name"], body["account_reference_label"], body["callback_url"],
            int(branch) if branch else None, now, now,
        ),
    )
    _audit(db, profile_id, actor, "profile_created", "Credentials stored on the payment service only.")
    row = db.execute("SELECT * FROM mpesa_profiles WHERE id=?", (profile_id,)).fetchone()
    return _public_profile(row)


def set_profile_status(db, actor, profile_id: str, active: bool, make_default: bool = False) -> dict:
    if not can_configure(actor):
        raise MpesaSaleError("Only an admin can change a merchant profile.")
    ensure_tables(db)
    row = db.execute("SELECT * FROM mpesa_profiles WHERE id=?", (profile_id,)).fetchone()
    if not row:
        raise MpesaSaleError("That merchant profile is not on this shop.")
    action = "activate" if active else "deactivate"
    _lab(db, "POST", f"/api/v1/profiles/{profile_id}/{action}", {})
    status = "active" if active else "inactive"
    if make_default and active:
        db.execute("UPDATE mpesa_profiles SET is_default=0")
    db.execute(
        "UPDATE mpesa_profiles SET status=?, is_default=?, updated_at=? WHERE id=?",
        (status, 1 if make_default and active else row["is_default"], _now(), profile_id),
    )
    if make_default and active:
        _set_setting(db, "mpesa_till", row["till_number"] or "")
        _set_setting(db, "mpesa_paybill", row["paybill_number"] or "")
        _set_setting(db, "mpesa_business_name", row["business_name"] or "")
        _set_setting(db, "mpesa_mode", "manual")
        _set_setting(db, "daraja_environment", "sandbox")
    _audit(db, profile_id, actor, "profile_" + action, "Default receipt numbers updated." if make_default else "")
    fresh = db.execute("SELECT * FROM mpesa_profiles WHERE id=?", (profile_id,)).fetchone()
    return _public_profile(fresh)


def authenticate_profile(db, actor, profile_id: str) -> dict:
    if not can_view(actor):
        raise MpesaSaleError("You cannot test this profile.")
    ensure_tables(db)
    _status, body = _lab(db, "POST", f"/api/v1/profiles/{profile_id}/authenticate", {})
    return {
        "success": bool(body.get("success")),
        "message": body.get("message") or "Authentication finished.",
        "provider": body.get("provider") or "",
        "payment_created": False,
        "sale_created": False,
    }


def diagnostics(db, actor) -> dict:
    if not can_view(actor) and not can_operate(actor):
        raise MpesaSaleError("You cannot view M-Pesa diagnostics.")
    ensure_tables(db)
    cfg = gateway_config(db)
    reachable = False
    health_status = ""
    if cfg["url"]:
        try:
            status, body = _lab(db, "GET", "/api/v1/health", None, timeout=5)
            reachable = status == 200
            health_status = str(body.get("status") or status)
        except MpesaSaleError as exc:
            health_status = str(exc)
    active = db.execute(
        "SELECT COUNT(*) FROM mpesa_profiles WHERE status='active'"
    ).fetchone()[0]
    return {
        "service_address_set": bool(cfg["url"]),
        "service_reachable": reachable,
        "service_health": health_status,
        "service_authentication": "configured" if cfg["token_configured"] else "not configured",
        "active_profiles": int(active),
        "production_authorized": False,
        "callback_verified": False,
        "stk_available": bool(reachable and active),
        "manual_checkout": True,
        "payment_confirmed": False,
        "message": (
            "A health check does not take a payment. "
            "Callback reachability is not verified. Production is off."
        ),
    }


def _insert_payment(db, **fields) -> str:
    payment_id = fields.pop("id", None) or str(uuid.uuid4())
    now = _now()
    fields.setdefault("created_at", now)
    fields.setdefault("updated_at", now)
    fields["id"] = payment_id
    columns = list(fields)
    db.execute(
        f"INSERT INTO mpesa_payments ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
        [fields[column] for column in columns],
    )
    return payment_id


def _payment(db, payment_id: str):
    return db.execute("SELECT * FROM mpesa_payments WHERE id=?", (payment_id,)).fetchone()


def _new_reference(db) -> str:
    for _ in range(5):
        reference = "MP" + uuid.uuid4().hex[:10].upper()
        taken = db.execute(
            "SELECT 1 FROM mpesa_payments WHERE sale_reference=?", (reference,)
        ).fetchone()
        if not taken:
            return reference
    raise MpesaSaleError("A payment reference could not be reserved.")


def start_stk(db, actor, *, phone: str, amount, profile_id: str, sale_reference: str,
              idempotency_key: str, new_attempt_of: str = "") -> dict:
    if not can_operate(actor):
        raise MpesaSaleError("You cannot send a phone prompt.")
    ensure_tables(db)
    profile = db.execute("SELECT * FROM mpesa_profiles WHERE id=?", (profile_id,)).fetchone()
    if not profile or profile["status"] != "active":
        raise MpesaSaleError("Choose an active merchant profile.")
    branch = current_branch_id(db)
    if _role(actor) == "cashier" and profile["branch_id"] and branch and int(profile["branch_id"]) != branch:
        raise MpesaSaleError("This profile is for another branch.")
    normalized = normalize_phone(phone)
    shillings = whole_shillings(amount)
    key = (idempotency_key or "").strip()
    if not key:
        raise MpesaSaleError("The prompt needs an idempotency key.")
    existing = db.execute(
        "SELECT * FROM mpesa_payments WHERE idempotency_key=?", (key,)
    ).fetchone()
    if existing:
        return _public_payment(existing)
    if new_attempt_of:
        prior = _payment(db, new_attempt_of)
        if not prior or not prior["released"]:
            raise MpesaSaleError("A manager must release the unknown payment before a new prompt.")
    reference = _new_reference(db)
    payment_id = _insert_payment(
        db,
        idempotency_key=key,
        profile_id=profile_id,
        branch_id=branch,
        kind="stk",
        state="sending",
        amount_shillings=shillings,
        amount_text=f"{shillings:.2f}",
        phone=normalized,
        phone_masked=mask_phone(normalized),
        sale_reference=reference,
        verification="unverified",
        provider="",
        result_detail="Sending request. Not a payment.",
    )
    _audit(db, payment_id, actor, "stk_send", f"amount={shillings}")
    db.commit()
    try:
        _status, body = _lab(db, "POST", "/api/v1/transactions/stk-push", {
            "phone": normalized,
            "amount": shillings,
            "account_reference": reference,
            "transaction_desc": "Payment",
            "idempotency_key": key,
            "profile_id": profile_id,
            "callback_url": profile["callback_url"],
        })
    except MpesaSaleError as exc:
        db.execute(
            """UPDATE mpesa_payments
               SET state='unknown', result_detail=?, updated_at=?
               WHERE id=? AND state='sending'""",
            (str(exc), _now(), payment_id),
        )
        _audit(db, payment_id, actor, "stk_unknown", "No checkout id. Prompt was not repeated.")
        db.commit()
        return _public_payment(_payment(db, payment_id))
    checkout = str(body.get("checkout_request_id") or "")
    provider = "mock" if body.get("provider") == "mock" else "daraja"
    if not checkout or str(body.get("response_code") or "") not in {"0", "00"}:
        db.execute(
            """UPDATE mpesa_payments
               SET state='unknown', provider=?, result_code=?, result_detail=?, updated_at=?
               WHERE id=?""",
            (provider, str(body.get("response_code") or ""), "Request was not accepted. Not a payment.", _now(), payment_id),
        )
    else:
        db.execute(
            """UPDATE mpesa_payments
               SET state='prompt_sent', provider=?, checkout_request_id=?, merchant_request_id=?,
                   result_code=?, result_detail=?, verification='unverified', updated_at=?
               WHERE id=?""",
            (
                provider, checkout, str(body.get("merchant_request_id") or ""),
                str(body.get("response_code") or ""),
                "Prompt sent. Waiting for a status query. Not a payment.",
                _now(), payment_id,
            ),
        )
    _audit(db, payment_id, actor, "stk_accepted" if checkout else "stk_not_accepted", checkout or "no checkout id")
    db.commit()
    return _public_payment(_payment(db, payment_id))


def poll_payment(db, actor, payment_id: str) -> dict:
    if not can_operate(actor):
        raise MpesaSaleError("You cannot check this payment.")
    ensure_tables(db)
    row = _payment(db, payment_id)
    if not row:
        raise MpesaSaleError("Payment not found.")
    if row["state"] in TERMINAL_STATES or row["kind"] != "stk":
        return _public_payment(row)
    if not row["checkout_request_id"]:
        if row["state"] != "unknown":
            db.execute(
                "UPDATE mpesa_payments SET state='unknown', updated_at=? WHERE id=?",
                (_now(), payment_id),
            )
            db.commit()
        return _public_payment(_payment(db, payment_id))
    try:
        _status, body = _lab(db, "POST", "/api/v1/transactions/stk-query", {
            "checkout_request_id": row["checkout_request_id"],
            "profile_id": row["profile_id"],
        })
    except MpesaSaleError as exc:
        db.execute(
            """UPDATE mpesa_payments
               SET state='unknown', result_detail=?, updated_at=? WHERE id=?""",
            (str(exc), _now(), payment_id),
        )
        _audit(db, payment_id, actor, "query_unknown", "Status query did not answer.")
        db.commit()
        return _public_payment(_payment(db, payment_id))
    from backend.mpesa_daraja import normalise_stk_query
    decision = normalise_stk_query(
        body if isinstance(body, dict) else {},
        intended_shillings=int(row["amount_shillings"]),
        checkout_id=row["checkout_request_id"] or "",
    )
    provider = "mock" if body.get("provider") == "mock" else (row["provider"] or "daraja")
    state = "waiting" if decision["state"] == "unresolved" else decision["state"]
    verification = decision["verification"]
    receipt = decision["receipt"]
    detail = decision["detail"]
    code = str((decision.get("evidence") or {}).get("query_result_code") or "")
    evidence = json.dumps(decision.get("evidence") or {}, default=str)[:2000]
    try:
        db.execute(
            """UPDATE mpesa_payments
               SET state=?, provider=?, receipt_code=?, verification=?, result_code=?,
                   result_detail=?, evidence_json=?, updated_at=?
               WHERE id=? AND state NOT IN ('verified')""",
            (state, provider, receipt or None, verification, code, detail, evidence, _now(), payment_id),
        )
    except sqlite3.IntegrityError as exc:
        db.rollback()
        raise MpesaSaleError("That M-Pesa code is already recorded.") from exc
    _audit(db, payment_id, actor, "query_" + state, detail)
    db.commit()
    return _public_payment(_payment(db, payment_id))


def release_unknown(db, actor, payment_id: str, reason: str) -> dict:
    if not can_override(actor):
        raise MpesaSaleError("A manager must release an unknown payment.")
    if len((reason or "").strip()) < 3:
        raise MpesaSaleError("Enter a reason.")
    ensure_tables(db)
    row = _payment(db, payment_id)
    if not row:
        raise MpesaSaleError("Payment not found.")
    if row["state"] != "unknown":
        raise MpesaSaleError("Only an unknown payment can be released for a new prompt.")
    if row["sale_id"]:
        raise MpesaSaleError("This payment is already attached to a sale.")
    db.execute(
        "UPDATE mpesa_payments SET released=1, updated_at=? WHERE id=?",
        (_now(), payment_id),
    )
    _audit(db, payment_id, actor, "release_unknown", reason.strip())
    db.commit()
    return _public_payment(_payment(db, payment_id))


def _code_taken(db, code: str) -> bool:
    if not code:
        return False
    row = db.execute(
        "SELECT id FROM mpesa_payments WHERE receipt_code=?", (code,)
    ).fetchone()
    if row:
        return True
    try:
        sale = db.execute(
            "SELECT id FROM sales WHERE upper(trim(mpesa_ref))=?", (code,)
        ).fetchone()
    except sqlite3.Error:
        sale = None
    return sale is not None


def prepare_sale_mpesa(db, data: dict, method: str, electronic_paid: float) -> dict:
    """Reserve a manual code, or require a verified payment. Does not commit."""
    method_name = (method or "").lower()
    electronic_method = str(data.get("electronic_method") or "")
    tenders = data.get("payment_tenders") or []
    mpesa_tenders = [row for row in tenders if _is_mpesa(str(row.get("method") or ""))]
    touches = (
        _is_mpesa(method_name)
        or _is_mpesa(electronic_method)
        or bool(mpesa_tenders)
        or bool(str(data.get("mpesa_payment_id") or "").strip())
        or bool(str(data.get("mpesa_ref") or "").strip())
    )
    if not touches:
        return {}
    ensure_tables(db)
    if mpesa_tenders:
        component = round(sum(float(row.get("amount") or 0) for row in mpesa_tenders), 2)
    elif _is_mpesa(electronic_method):
        component = round(float(electronic_paid or 0), 2)
    elif _is_mpesa(method_name):
        component = round(float(data.get("amount_paid") or data.get("total") or 0), 2)
    else:
        component = 0.0
    payment_id = str(data.get("mpesa_payment_id") or "").strip()
    if payment_id:
        row = _payment(db, payment_id)
        if not row or row["state"] != "verified":
            raise MpesaSaleError("This M-Pesa payment is not verified. The sale was not completed.")
        if row["sale_id"]:
            raise MpesaSaleError("This M-Pesa payment is already attached to a sale.")
        if abs(float(row["amount_shillings"]) - component) > 0.001:
            raise MpesaSaleError("The verified amount does not match the M-Pesa portion of this sale.")
        note = row["result_detail"] or "Verified by status query."
        return {
            "payment_id": payment_id,
            "mpesa_ref": row["receipt_code"] or "",
            "verification": row["verification"],
            "note": note,
        }
    code = normalize_code(str(data.get("mpesa_ref") or ""))
    if code and _code_taken(db, code):
        raise MpesaSaleError("That M-Pesa code is already recorded.")
    if code:
        _insert_payment(
            db,
            kind="manual",
            state="recorded",
            amount_shillings=None,
            amount_text=f"{component:.2f}",
            receipt_code=code,
            verification="manual",
            provider="manual",
            result_detail="Manually recorded. Not verified with Safaricom.",
            sale_reference=(data.get("client_token") or "")[:12],
        )
    note = "Manually recorded. Not verified with Safaricom."
    if not code and (_is_mpesa(method_name) or mpesa_tenders or _is_mpesa(electronic_method)):
        note = "Manually recorded. No transaction code. Not verified with Safaricom."
    return {"payment_id": "", "mpesa_ref": code, "verification": "manual", "note": note}


def attach_sale_mpesa(db, sale_id: int, prepared: dict) -> None:
    if not prepared:
        return
    verification = prepared.get("verification") or ""
    if verification:
        db.execute(
            "UPDATE sales SET mpesa_verification=? WHERE id=?",
            (verification, sale_id),
        )
    payment_id = prepared.get("payment_id") or ""
    if payment_id:
        db.execute(
            "UPDATE mpesa_payments SET sale_id=?, updated_at=? WHERE id=? AND sale_id IS NULL",
            (sale_id, _now(), payment_id),
        )
    elif prepared.get("mpesa_ref"):
        db.execute(
            """UPDATE mpesa_payments SET sale_id=?, updated_at=?
               WHERE receipt_code=? AND sale_id IS NULL""",
            (sale_id, _now(), prepared["mpesa_ref"]),
        )


def list_payments(db, actor, **filters) -> list:
    if not can_operate(actor):
        raise MpesaSaleError("You cannot view M-Pesa payments.")
    ensure_tables(db)
    sql = "SELECT * FROM mpesa_payments WHERE 1=1"
    args = []
    for column in ("state", "verification", "profile_id", "kind"):
        value = filters.get(column)
        if value:
            sql += f" AND {column}=?"
            args.append(value)
    if _role(actor) == "cashier":
        branch = current_branch_id(db)
        if branch:
            sql += " AND (branch_id IS NULL OR branch_id=?)"
            args.append(branch)
    sql += " ORDER BY created_at DESC LIMIT 200"
    return [_public_payment(row) for row in db.execute(sql, args).fetchall()]


def summary(db, actor) -> dict:
    if not can_view(actor):
        raise MpesaSaleError("You cannot view M-Pesa totals.")
    ensure_tables(db)
    def _sum(where: str) -> dict:
        row = db.execute(
            f"SELECT COUNT(*), COALESCE(SUM(amount_shillings),0) FROM mpesa_payments WHERE {where}"
        ).fetchone()
        return {"count": int(row[0]), "shillings": int(row[1] or 0)}
    incoming = db.execute(
        "SELECT state, COUNT(*) FROM mpesa_incoming GROUP BY state"
    ).fetchall()
    return {
        "verified_daraja": _sum("verification='verified_daraja'"),
        "simulated": _sum("verification='verified_mock'"),
        "manual": _sum("verification='manual'"),
        "pending": _sum("state IN ('prompt_sent','waiting','sending','preparing')"),
        "unknown": _sum("state='unknown' AND released=0"),
        "failed": _sum("state IN ('failed','timeout','cancelled','rejected')"),
        "incoming": {row[0]: int(row[1]) for row in incoming},
    }


def record_incoming(db, actor, fields: dict) -> dict:
    if not can_override(actor):
        raise MpesaSaleError("A manager records an incoming payment.")
    ensure_tables(db)
    provider_ref = normalize_code(str(fields.get("provider_ref") or ""))
    if not provider_ref:
        raise MpesaSaleError("Enter the M-Pesa code.")
    if _code_taken(db, provider_ref):
        state = "duplicate"
    else:
        state = "unmatched"
    shillings = whole_shillings(fields.get("amount"))
    phone = ""
    if fields.get("phone"):
        phone = mask_phone(normalize_phone(str(fields.get("phone"))))
    incoming_id = str(uuid.uuid4())
    try:
        db.execute(
            """INSERT INTO mpesa_incoming
               (id, provider_ref, profile_id, amount_shillings, phone_masked, account_reference,
                state, detail, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                incoming_id, provider_ref, fields.get("profile_id") or None, shillings, phone,
                str(fields.get("account_reference") or "")[:20], state,
                "Incoming payment stored. Not attached to a sale.", _now(), _now(),
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise MpesaSaleError("That incoming code is already in the inbox.") from exc
    _audit(db, incoming_id, actor, "incoming_" + state, provider_ref)
    row = db.execute("SELECT * FROM mpesa_incoming WHERE id=?", (incoming_id,)).fetchone()
    return dict(row)


def list_incoming(db, actor) -> list:
    if not can_view(actor):
        raise MpesaSaleError("You cannot view incoming payments.")
    ensure_tables(db)
    return [dict(row) for row in db.execute(
        "SELECT * FROM mpesa_incoming ORDER BY created_at DESC LIMIT 200"
    ).fetchall()]


def sale_mpesa_due(sale) -> float | None:
    """Outstanding M-Pesa amount on a sale. None when the sale has no M-Pesa component."""
    raw = sale["payment_tenders"] if "payment_tenders" in sale.keys() else None
    tenders = []
    if raw:
        try:
            tenders = json.loads(raw) if isinstance(raw, str) else list(raw)
        except (TypeError, json.JSONDecodeError):
            tenders = []
    mpesa_lines = [row for row in tenders if _is_mpesa(str(row.get("method") or ""))]
    if mpesa_lines:
        return round(sum(float(row.get("amount") or 0) for row in mpesa_lines), 2)
    method = str(sale["payment_method"] if "payment_method" in sale.keys() else "")
    electronic = str(sale["electronic_method"] if "electronic_method" in sale.keys() else "")
    if _is_mpesa(electronic):
        paid = sale["electronic_paid"] if "electronic_paid" in sale.keys() else 0
        return round(float(paid or 0), 2)
    if _is_mpesa(method):
        paid = sale["amount_paid"] if "amount_paid" in sale.keys() else sale["total"]
        return round(float(paid or 0), 2)
    return None


def match_incoming(db, actor, incoming_id: str, sale_id: int, reason: str) -> dict:
    if not can_override(actor):
        raise MpesaSaleError("A manager matches an incoming payment.")
    if len((reason or "").strip()) < 3:
        raise MpesaSaleError("Enter a reason.")
    ensure_tables(db)
    row = db.execute("SELECT * FROM mpesa_incoming WHERE id=?", (incoming_id,)).fetchone()
    if not row:
        raise MpesaSaleError("Incoming payment not found.")
    if row["state"] == "matched":
        raise MpesaSaleError("This payment is already matched.")
    if row["state"] == "duplicate":
        raise MpesaSaleError("This code is a duplicate and cannot be matched.")
    sale = db.execute("SELECT * FROM sales WHERE id=?", (sale_id,)).fetchone()
    if not sale:
        raise MpesaSaleError("Sale not found.")
    due = sale_mpesa_due(sale)
    if due is None:
        raise MpesaSaleError("That sale has no M-Pesa amount to match.")
    if abs(float(due) - float(row["amount_shillings"])) > 0.001:
        db.execute(
            "UPDATE mpesa_incoming SET state='mismatch', updated_at=? WHERE id=?",
            (_now(), incoming_id),
        )
        _audit(db, incoming_id, actor, "incoming_mismatch", reason.strip())
        raise MpesaSaleError("The incoming amount does not match that sale. It was marked as a mismatch.")
    if sale["mpesa_ref"] and normalize_code(sale["mpesa_ref"]) != row["provider_ref"]:
        raise MpesaSaleError("That sale already has a different M-Pesa code.")
    db.execute(
        "UPDATE mpesa_incoming SET state='matched', sale_id=?, updated_at=? WHERE id=?",
        (sale_id, _now(), incoming_id),
    )
    if not sale["mpesa_ref"]:
        db.execute(
            """UPDATE sales SET mpesa_ref=?, mpesa_verification='manual',
               notes=TRIM(COALESCE(notes,'') || ' | Incoming payment matched. Not a phone-prompt verification.')
               WHERE id=?""",
            (row["provider_ref"], sale_id),
        )
    _audit(db, incoming_id, actor, "incoming_matched", f"sale={sale_id}. {reason.strip()}")
    fresh = db.execute("SELECT * FROM mpesa_incoming WHERE id=?", (incoming_id,)).fetchone()
    return dict(fresh)
