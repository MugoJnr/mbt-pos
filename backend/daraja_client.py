"""Safaricom Daraja Lipa na M-Pesa Online.

Checked against the public Daraja contract on 2026-11-13:
sandbox https://sandbox.safaricom.co.ke
production https://api.safaricom.co.ke
OAuth GET /oauth/v1/generate?grant_type=client_credentials
STK POST /mpesa/stkpush/v1/processrequest
Query POST /mpesa/stkpushquery/v1/query

ResponseCode 0 means Safaricom accepted the prompt request. It is not payment.
The portal pages are https://developer.safaricom.co.ke/ and /apis.
"""
from __future__ import annotations

import base64
import hashlib
import json
import time
from datetime import datetime
from typing import Callable
from urllib import error as urlerror
from urllib import request as urlrequest
from zoneinfo import ZoneInfo

from backend.mpesa_daraja import callback_metadata, normalise_stk_query

NAIROBI = ZoneInfo("Africa/Nairobi")
SANDBOX_BASE = "https://sandbox.safaricom.co.ke"
PRODUCTION_BASE = "https://api.safaricom.co.ke"
_TOKEN_CACHE: dict[str, tuple[str, float]] = {}


class DarajaError(ValueError):
    """Safaricom was not treated as paid."""


def base_url(environment: str) -> str:
    name = (environment or "").strip().lower()
    if name == "sandbox":
        return SANDBOX_BASE
    if name == "production":
        return PRODUCTION_BASE
    raise DarajaError("Choose sandbox or production.")


def stk_timestamp(moment: datetime | None = None) -> str:
    current = moment or datetime.now(NAIROBI)
    if current.tzinfo is None:
        current = current.replace(tzinfo=NAIROBI)
    return current.astimezone(NAIROBI).strftime("%Y%m%d%H%M%S")


def stk_password(shortcode: str, passkey: str, stamp: str) -> str:
    raw = f"{shortcode}{passkey}{stamp}".encode()
    return base64.b64encode(raw).decode("ascii")


def transaction_type(merchant_type: str) -> str:
    kind = (merchant_type or "").strip().lower()
    if kind == "till":
        return "CustomerBuyGoodsOnline"
    if kind == "paybill":
        return "CustomerPayBillOnline"
    raise DarajaError("Choose Buy Goods Till or Paybill.")


def _cache_key(environment: str, consumer_key: str, consumer_secret: str) -> str:
    material = f"{environment}:{consumer_key}:{consumer_secret}".encode()
    return hashlib.sha256(material).hexdigest()


def reconcile_stk(*, query: dict, callback: dict | None, intended_shillings: int, checkout_id: str) -> dict:
    """Query plus callback. Disagreement is reconciliation, not a sale."""
    query = query if isinstance(query, dict) else {}
    qcode = "" if query.get("ResultCode") is None else str(query.get("ResultCode"))
    if callback:
        meta = callback_metadata(callback)
        ccode = str(meta.get("_result_code") or "")
        success = {"0", "00"}
        if qcode and ccode and ((qcode in success) != (ccode in success)):
            return {
                "state": "unknown",
                "verification": "unverified",
                "receipt": "",
                "detail": "The callback and the status query do not agree. The sale was not completed.",
                "evidence": {"query_result_code": qcode, "callback_result_code": ccode},
            }
    body = {
        "queried": True,
        "provider": "daraja",
        "ResultCode": qcode,
        "ResultDesc": query.get("ResultDesc") or query.get("ResponseDescription") or "",
        "CheckoutRequestID": query.get("CheckoutRequestID") or checkout_id,
    }
    if callback:
        body["callback_payload"] = callback
    return normalise_stk_query(
        body, intended_shillings=int(intended_shillings), checkout_id=checkout_id,
    )


class DarajaClient:
    """One short code. The access token is cached in this process only."""

    def __init__(
        self,
        *,
        environment: str,
        consumer_key: str,
        consumer_secret: str,
        shortcode: str,
        passkey: str,
        merchant_type: str,
        party_b: str,
        callback_url: str,
        opener: Callable | None = None,
        timeout: int = 20,
    ):
        self.environment = (environment or "").strip().lower()
        self.base = base_url(self.environment)
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.shortcode = re_digits(shortcode)
        self.passkey = passkey
        self.merchant_type = (merchant_type or "").strip().lower()
        self.party_b = re_digits(party_b or shortcode)
        self.callback_url = (callback_url or "").strip()
        self.timeout = timeout
        self._open = opener or urlrequest.urlopen

    def access_token(self) -> str:
        key = _cache_key(self.environment, self.consumer_key, self.consumer_secret)
        cached = _TOKEN_CACHE.get(key)
        now = time.time()
        if cached and cached[1] > now + 30:
            return cached[0]
        basic = base64.b64encode(f"{self.consumer_key}:{self.consumer_secret}".encode()).decode("ascii")
        url = self.base + "/oauth/v1/generate?grant_type=client_credentials"
        request = urlrequest.Request(url, headers={"Authorization": "Basic " + basic})
        body = _read_json(self._open, request, self.timeout)
        token = str(body.get("access_token") or "")
        if not token:
            raise DarajaError("Safaricom did not return an access token. No prompt was sent.")
        try:
            expires = int(body.get("expires_in") or 3600)
        except (TypeError, ValueError):
            expires = 3600
        _TOKEN_CACHE[key] = (token, now + max(60, expires))
        return token

    def stk_push(self, *, phone: str, amount: int, account_reference: str, description: str) -> dict:
        if not self.callback_url.lower().startswith("https://"):
            raise DarajaError("Safaricom needs a public HTTPS callback. No prompt was sent.")
        stamp = stk_timestamp()
        payload = {
            "BusinessShortCode": self.shortcode,
            "Password": stk_password(self.shortcode, self.passkey, stamp),
            "Timestamp": stamp,
            "TransactionType": transaction_type(self.merchant_type),
            "Amount": int(amount),
            "PartyA": phone,
            "PartyB": self.party_b,
            "PhoneNumber": phone,
            "CallBackURL": self.callback_url,
            "AccountReference": (account_reference or "MBT")[:12],
            "TransactionDesc": (description or "Payment")[:13],
        }
        body = self._post("/mpesa/stkpush/v1/processrequest", payload)
        return {
            "merchant_request_id": str(body.get("MerchantRequestID") or ""),
            "checkout_request_id": str(body.get("CheckoutRequestID") or ""),
            "response_code": str(body.get("ResponseCode") or ""),
            "response_description": str(body.get("ResponseDescription") or ""),
            "customer_message": str(body.get("CustomerMessage") or ""),
            "provider": "daraja",
        }

    def stk_query(self, checkout_request_id: str) -> dict:
        stamp = stk_timestamp()
        payload = {
            "BusinessShortCode": self.shortcode,
            "Password": stk_password(self.shortcode, self.passkey, stamp),
            "Timestamp": stamp,
            "CheckoutRequestID": checkout_request_id,
        }
        body = self._post("/mpesa/stkpushquery/v1/query", payload)
        body["provider"] = "daraja"
        return body

    def _post(self, path: str, payload: dict) -> dict:
        token = self.access_token()
        data = json.dumps(payload).encode()
        request = urlrequest.Request(
            self.base + path,
            data=data,
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        return _read_json(self._open, request, self.timeout)


def re_digits(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _read_json(opener, request, timeout: int) -> dict:
    try:
        with opener(request, timeout=timeout) as response:
            raw = response.read().decode() or "{}"
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise DarajaError("Safaricom returned an unexpected response. No payment was recorded.")
            return parsed
    except DarajaError:
        raise
    except urlerror.HTTPError as exc:
        raise DarajaError(f"Safaricom returned HTTP {exc.code}. No payment was recorded.") from exc
    except (urlerror.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise DarajaError("Safaricom did not answer. No second prompt was sent.") from exc


def clear_token_cache() -> None:
    _TOKEN_CACHE.clear()
