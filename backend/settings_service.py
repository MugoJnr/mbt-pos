"""One transactional settings save for the till and the web dashboard.

A save is confirmed only after SQLite commits. A client that sends
config_version cannot overwrite a newer save. Passwords, PINs, and tokens
are never written into the change history.
"""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlparse

from backend.settings_catalog import (
    ACCOUNTING_METHODS,
    BOOL_KEYS,
    CHECKOUT_LAYOUTS,
    COSTING_METHODS,
    CURRENCIES,
    FORCED,
    PAYMENT_METHODS,
    ROUNDING_MODES,
    section_for,
    scope_for,
)
from backend.settings_guard import reject_privileged_settings, reject_secret_settings

_SECRET_HINTS = ('pin', 'password', 'token', 'secret', 'hash', 'credential', 'passkey')
_ACCOUNT = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,15}$')
_CONTROL_KEYS = frozenset({'config_version', 'device_id', 'source'})


def ensure_schema(db) -> None:
    db.execute(
        """CREATE TABLE IF NOT EXISTS settings_revision (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            version INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT,
            updated_by TEXT,
            source TEXT
        )"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS settings_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version INTEGER NOT NULL,
            setting_key TEXT NOT NULL,
            section TEXT,
            scope TEXT,
            old_value TEXT,
            new_value TEXT,
            username TEXT,
            role TEXT,
            device_id TEXT,
            source TEXT,
            result TEXT,
            created_at TEXT
        )"""
    )
    row = db.execute("SELECT version FROM settings_revision WHERE id=1").fetchone()
    if row is None:
        db.execute(
            "INSERT INTO settings_revision (id, version, updated_at, updated_by, source) "
            "VALUES (1, 0, '', '', '')"
        )
    try:
        db.commit()
    except Exception:
        pass


def current_version(db) -> int:
    ensure_schema(db)
    row = db.execute("SELECT version FROM settings_revision WHERE id=1").fetchone()
    if row is None:
        return 0
    try:
        return int(row['version'] if hasattr(row, 'keys') else row[0])
    except (TypeError, ValueError, KeyError, IndexError):
        return 0


def read_meta(db) -> dict:
    ensure_schema(db)
    row = db.execute(
        "SELECT version, updated_at, updated_by, source FROM settings_revision WHERE id=1"
    ).fetchone()
    version = 0
    updated_at = ''
    updated_by = ''
    source = ''
    if row is not None:
        data = dict(row) if hasattr(row, 'keys') else {
            'version': row[0], 'updated_at': row[1], 'updated_by': row[2], 'source': row[3],
        }
        version = int(data.get('version') or 0)
        updated_at = data.get('updated_at') or ''
        updated_by = data.get('updated_by') or ''
        source = data.get('source') or ''
    shop = _value(db, 'shop_name')
    warnings = []
    if not str(shop or '').strip():
        warnings.append('Shop name is not set.')
    pin = str(_value(db, 'superadmin_pin_hash') or '').strip()
    if not pin:
        warnings.append('Super-Admin PIN is not set.')
    return {
        'config_version': version,
        'updated_at': updated_at,
        'updated_by': updated_by,
        'source': source,
        'pin_configured': '1' if pin else '0',
        'shop_name': shop or '',
        'warnings': warnings,
    }


def read_history(db, limit: int = 80) -> list:
    ensure_schema(db)
    limit = max(1, min(200, int(limit or 80)))
    rows = db.execute(
        "SELECT id, version, setting_key, section, scope, old_value, new_value, "
        "username, role, device_id, source, result, created_at "
        "FROM settings_history ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    out = []
    for row in rows:
        item = dict(row) if hasattr(row, 'keys') else {
            'id': row[0], 'version': row[1], 'setting_key': row[2], 'section': row[3],
            'scope': row[4], 'old_value': row[5], 'new_value': row[6],
            'username': row[7], 'role': row[8], 'device_id': row[9],
            'source': row[10], 'result': row[11], 'created_at': row[12],
        }
        item['old_value'] = _redact(item.get('setting_key') or '', item.get('old_value'))
        item['new_value'] = _redact(item.get('setting_key') or '', item.get('new_value'))
        out.append(item)
    return out


def apply_changes(db, data: dict, *, role: str = '', username: str = '',
                  source: str = 'api', device_id: str = '') -> dict:
    """Validate, then write every accepted key in one transaction."""
    ensure_schema(db)
    try:
        incoming = reject_secret_settings(dict(data or {}))
        incoming = reject_privileged_settings(incoming, role or '')
    except ValueError as exc:
        return {'success': False, 'error': str(exc)}

    actor = (role or '').strip().lower()
    if actor and actor not in ('admin', 'superadmin'):
        return {'success': False, 'error': 'Admin only'}

    expected = incoming.pop('config_version', None)
    device = str(incoming.pop('device_id', None) or device_id or '')[:80]
    origin = str(incoming.pop('source', None) or source or 'api')[:40]
    for key in list(incoming):
        if str(key).startswith('_') or key in _CONTROL_KEYS:
            incoming.pop(key, None)

    cleaned, error = _prepare(incoming)
    if error:
        return {'success': False, 'error': error}

    version = current_version(db)
    if expected is not None and str(expected).strip() != '':
        try:
            expected_version = int(expected)
        except (TypeError, ValueError):
            return {'success': False, 'error': 'Configuration version must be a number.'}
        if expected_version != version:
            _record_conflict(db, version, username, actor, device, origin)
            return {
                'success': False,
                'conflict': True,
                'error': (
                    'These settings were saved somewhere else. '
                    'Reload them before saving again.'
                ),
                'config_version': version,
            }

    now = datetime.now().isoformat(timespec='seconds')
    changed = []
    _begin(db)
    try:
        for key, value in cleaned.items():
            previous = _value(db, key)
            if previous == value:
                continue
            db.execute(
                "INSERT OR REPLACE INTO system_settings (key, value, updated_at) VALUES (?, ?, ?)",
                (key, value, now),
            )
            changed.append((key, previous, value))
        if changed:
            version += 1
            for key, previous, value in changed:
                db.execute(
                    "INSERT INTO settings_history ("
                    "version, setting_key, section, scope, old_value, new_value, "
                    "username, role, device_id, source, result, created_at"
                    ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        version, key, section_for(key), scope_for(key),
                        _redact(key, previous), _redact(key, value),
                        username or '', actor, device, origin, 'saved', now,
                    ),
                )
            db.execute(
                "UPDATE settings_revision SET version=?, updated_at=?, updated_by=?, source=? WHERE id=1",
                (version, now, username or '', origin),
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {
        'success': True,
        'config_version': version,
        'changed': [key for key, _old, _new in changed],
    }


def _prepare(data: dict) -> tuple[dict, str]:
    cleaned = {}
    for raw_key, raw_value in data.items():
        key = str(raw_key).strip()
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', key):
            return {}, f'{raw_key} is not a valid setting name.'
        if key in FORCED:
            sent = str(raw_value).strip().lower()
            allowed = {FORCED[key].lower(), ''}
            if key == 'variance_allow_refund_after_finalize':
                allowed.update({'0', 'false', 'no', 'off'})
            if key == 'allow_reprint':
                allowed.update({'0', '1', 'false', 'true', 'no', 'yes', 'off', 'on'})
            if sent not in allowed:
                return {}, f'{key} cannot be changed from the ordinary settings save.'
            cleaned[key] = FORCED[key]
            continue
        try:
            cleaned[key] = _coerce(key, raw_value)
        except ValueError as exc:
            return {}, str(exc)
    if 'shop_name' in cleaned and not cleaned['shop_name']:
        return {}, 'Shop name is required.'
    if 'currency_code' in cleaned:
        cleaned['currency_symbol'] = cleaned['currency_code']
    elif 'currency_symbol' in cleaned:
        cleaned['currency_code'] = cleaned['currency_symbol']
    return cleaned, ''


def _coerce(key: str, value) -> str:
    if key in BOOL_KEYS:
        return '1' if _truthy(value) else '0'
    text = '' if value is None else str(value).strip()
    if key in ('currency_symbol', 'currency_code'):
        code = text.upper() or 'KES'
        if code not in CURRENCIES:
            raise ValueError('Currency must be KES, USD, EUR, GBP, TZS, UGX, or ZAR.')
        return code
    if key == 'tax_rate':
        number = _number(text or '0', 'Tax rate')
        if number < 0 or number > 100:
            raise ValueError('Tax rate must be between 0 and 100.')
        return f'{round(number, 1):.1f}'
    if key == 'shop_name':
        if len(text) > 120:
            raise ValueError('Shop name must be 120 characters or fewer.')
        return text
    if key in ('shop_address', 'shop_phone', 'shop_email', 'receipt_footer', 'mpesa_business_name'):
        if len(text) > 240:
            raise ValueError(f'{key} is too long.')
        return text
    if key == 'printer_port':
        if len(text) > 120:
            raise ValueError('Printer port is too long.')
        return text
    if key == 'document_policy':
        code = (text or 'C').strip().upper()[:1]
        if code not in 'ABCDEF':
            raise ValueError('Document policy must be A, B, C, D, E, or F.')
        return code
    if key == 'printer_connection':
        value = (text or 'USB').strip().upper()
        if value not in ('USB', 'LAN', 'WINDOWS'):
            raise ValueError('Printer connection must be USB, LAN, or Windows.')
        return 'Windows' if value == 'WINDOWS' else value
    if key == 'paper_size':
        digits = ''.join(ch for ch in (text or '80') if ch.isdigit()) or '80'
        if digits not in ('58', '80'):
            raise ValueError('Paper size must be 58mm or 80mm.')
        return digits
    if key in ('printer_name', 'printer_host'):
        if len(text) > 120 or any(ch in text for ch in '\r\n'):
            raise ValueError(f'{key} is too long.')
        return text
    if key == 'daraja_gateway_url':
        if not text:
            return ''
        parsed = urlparse(text)
        host = (parsed.hostname or '').lower()
        if parsed.scheme not in ('http', 'https') or not host or 'safaricom' in host:
            raise ValueError('Gateway URL must be an http(s) address and must not call Safaricom directly.')
        return text[:300]
    if key in ('mpesa_till', 'mpesa_paybill'):
        if text and not re.fullmatch(r'[0-9A-Za-z -]{1,20}', text):
            raise ValueError('Till and Paybill must be short numbers or codes.')
        return text
    if key == 'variance_max_cashier':
        number = _number(text or '0', 'Cashier variance limit')
        if number < 0 or number > 99999999:
            raise ValueError('Cashier variance limit is out of range.')
        return f'{number:.2f}'
    if key == 'cash_rounding_mode':
        mode = (text or 'nearest').lower()
        if mode not in ROUNDING_MODES:
            raise ValueError('Unknown cash rounding mode.')
        return mode
    if key == 'cash_rounding_value':
        number = _number(text or '5', 'Rounding value')
        whole = int(round(number))
        if whole < 1 or whole > 1000:
            raise ValueError('Rounding value must be from 1 to 1000.')
        return str(whole)
    if key == 'fiscal_year_start_month':
        month = int(_number(text or '1', 'Fiscal year start'))
        if month < 1 or month > 12:
            raise ValueError('Fiscal year start must be a month from 1 to 12.')
        return str(month)
    if key == 'accounting_method':
        method = (text or 'accrual').lower()
        if method not in ACCOUNTING_METHODS:
            raise ValueError('Accounting method must be accrual or cash.')
        return method
    if key == 'inventory_costing':
        method = (text or 'weighted_avg').lower()
        if method not in COSTING_METHODS:
            raise ValueError('Inventory costing must be weighted average or FIFO.')
        return method
    if key in ('acct_cash_code', 'acct_mpesa_code', 'acct_bank_code'):
        code = text or {'acct_cash_code': '1000', 'acct_mpesa_code': '1010', 'acct_bank_code': '1020'}[key]
        if not _ACCOUNT.fullmatch(code):
            raise ValueError(f'{key} must be an account code such as 1000.')
        return code
    if key == 'expense_category_codes':
        parts = [part.strip() for part in (text or '6000,6100,6900').split(',') if part.strip()]
        if not parts or any(not _ACCOUNT.fullmatch(part) for part in parts):
            raise ValueError('Expense categories must be account codes separated by commas.')
        return ','.join(parts)
    if key == 'opening_balances_note':
        return text[:500]
    if key == 'after_sale_default_customer':
        if (text or 'walk_in').lower() != 'walk_in':
            raise ValueError('The default customer after a sale is Walk-in.')
        return 'walk_in'
    if key == 'after_sale_default_payment':
        if text not in PAYMENT_METHODS:
            raise ValueError('Choose a payment method from the till list.')
        return text
    if key == 'pos_checkout_layout':
        layout = (text or 'product_explorer').lower()
        if layout not in CHECKOUT_LAYOUTS:
            raise ValueError('Unknown checkout layout.')
        return layout
    if len(text) > 4000:
        raise ValueError(f'{key} is too long.')
    return text


def _begin(db) -> None:
    try:
        db.execute('BEGIN IMMEDIATE')
    except Exception as exc:
        if 'transaction' not in str(exc).lower():
            raise


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


def _number(text: str, label: str) -> float:
    try:
        return float(text)
    except (TypeError, ValueError):
        raise ValueError(f'{label} must be a number.')


def _value(db, key: str):
    row = db.execute("SELECT value FROM system_settings WHERE key=?", (key,)).fetchone()
    if row is None:
        return None
    if hasattr(row, 'keys'):
        return row['value']
    return row[0]


def _redact(key: str, value) -> str:
    low = (key or '').lower()
    if any(hint in low for hint in _SECRET_HINTS):
        return '[hidden]'
    text = '' if value is None else str(value)
    return text[:500]


def _record_conflict(db, version: int, username: str, role: str, device: str, source: str) -> None:
    now = datetime.now().isoformat(timespec='seconds')
    try:
        db.execute(
            "INSERT INTO settings_history ("
            "version, setting_key, section, scope, old_value, new_value, "
            "username, role, device_id, source, result, created_at"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (version, '*', 'system', 'shop', '', '', username or '', role, device, source, 'conflict', now),
        )
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
