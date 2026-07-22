"""
MBT POS — Double-Entry Accounting Engine
MugoByte Technologies | mugobyte.com

Offline-first SQLite journals. Posted entries are immutable;
corrections use reversing journals. Amounts stored as REAL (2dp).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Any, Iterable, Optional, Sequence, Union

logger = logging.getLogger(__name__)

Money = Union[Decimal, float, int, str]

# ── Chart of Accounts (seed) ───────────────────────────────────────────────────
# code, name, type, subtype, normal_balance, is_system, description
DEFAULT_COA = [
    # Assets
    ('1000', 'Cash on Hand', 'asset', 'cash', 'debit', 1, 'Till / petty cash'),
    ('1010', 'M-Pesa / Mobile Money', 'asset', 'cash', 'debit', 1, 'Mobile money float'),
    ('1020', 'Bank Account', 'asset', 'bank', 'debit', 1, 'Primary bank account'),
    ('1030', 'Card Clearing', 'asset', 'cash', 'debit', 1, 'Card settlement clearing'),
    ('1100', 'Accounts Receivable', 'asset', 'receivable', 'debit', 1, 'Customer credit sales'),
    ('1200', 'Inventory Asset', 'asset', 'inventory', 'debit', 1, 'Stock at cost'),
    ('1900', 'Other Current Assets', 'asset', 'other', 'debit', 0, 'Miscellaneous assets'),
    # Liabilities
    ('2000', 'Accounts Payable', 'liability', 'payable', 'credit', 1, 'Supplier payables'),
    ('2100', 'Customer Store Credit', 'liability', 'unearned', 'credit', 1, 'Wallet / deposits'),
    ('2200', 'Tax Payable', 'liability', 'tax', 'credit', 0, 'VAT / sales tax'),
    ('2900', 'Other Liabilities', 'liability', 'other', 'credit', 0, 'Miscellaneous liabilities'),
    # Equity
    ('3000', "Owner's Equity", 'equity', 'equity', 'credit', 1, 'Opening capital'),
    ('3100', 'Retained Earnings', 'equity', 'equity', 'credit', 1, 'Accumulated earnings'),
    ('3200', 'Opening Balance Equity', 'equity', 'equity', 'credit', 1, 'System opening balances'),
    # Income
    ('4000', 'Sales Revenue', 'income', 'revenue', 'credit', 1, 'Product sales'),
    ('4100', 'Other Income', 'income', 'other', 'credit', 0, 'Non-operating income'),
    ('4200', 'Tip Income', 'income', 'other', 'credit', 1, 'Payment variance tips'),
    ('4300', 'Cash Rounding Income', 'income', 'other', 'credit', 1, 'Positive cash rounding'),
    ('4400', 'Transport Income', 'income', 'other', 'credit', 0, 'Transport surcharge collected'),
    # COGS
    ('5000', 'Cost of Goods Sold', 'cogs', 'cogs', 'debit', 1, 'Inventory cost of sales'),
    # Expenses
    ('6000', 'Operating Expenses', 'expense', 'opex', 'debit', 0, 'General expenses'),
    ('6100', 'Internal Consumption', 'expense', 'opex', 'debit', 1, 'Staff / office stock use'),
    ('6200', 'Inventory Shrinkage', 'expense', 'cogs', 'debit', 1, 'Damage / loss adjustments'),
    ('6300', 'Inventory Expiry', 'expense', 'cogs', 'debit', 1, 'Expired stock write-off'),
    ('6400', 'Transport Expense', 'expense', 'opex', 'debit', 1, 'Transport variance'),
    ('6500', 'Cash Rounding Expense', 'expense', 'opex', 'debit', 1, 'Negative cash rounding'),
    ('6600', 'Miscellaneous Expense', 'expense', 'opex', 'debit', 1, 'Misc payment variance'),
    ('6900', 'Other Expenses', 'expense', 'opex', 'debit', 0, 'Uncategorized expenses'),
]

ACCOUNT_TYPE_ORDER = ('asset', 'liability', 'equity', 'income', 'cogs', 'expense')

PAYMENT_ACCOUNT = {
    'cash': '1000',
    'mpesa': '1010',
    'm-pesa': '1010',
    'mobile': '1010',
    'card': '1030',
    'bank': '1020',
    'transfer': '1020',
    'credit': '1100',
}


def D(value: Money) -> Decimal:
    """Money as Decimal quantized to 2dp."""
    try:
        if isinstance(value, Decimal):
            d = value
        else:
            d = Decimal(str(value if value is not None else 0))
    except (InvalidOperation, ValueError, TypeError):
        d = Decimal('0')
    return d.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def money_float(value: Money) -> float:
    return float(D(value))


def get_currency_code(conn) -> str:
    row = conn.execute(
        "SELECT value FROM system_settings WHERE key IN ('currency_code','currency_symbol') "
        "ORDER BY CASE key WHEN 'currency_code' THEN 0 ELSE 1 END LIMIT 1"
    ).fetchone()
    if not row:
        return 'KES'
    val = (row[0] if not hasattr(row, 'keys') else row['value']) or 'KES'
    return str(val).strip() or 'KES'


# ── Schema ─────────────────────────────────────────────────────────────────────

ACCOUNTING_DDL = """
CREATE TABLE IF NOT EXISTS chart_of_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    account_type TEXT NOT NULL,
    subtype TEXT,
    normal_balance TEXT NOT NULL DEFAULT 'debit',
    parent_code TEXT,
    is_system INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    description TEXT,
    currency_code TEXT DEFAULT 'KES',
    branch_id INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS accounting_periods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    closed_at TEXT,
    closed_by INTEGER,
    closed_by_name TEXT,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(start_date, end_date)
);

CREATE TABLE IF NOT EXISTS journal_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_number TEXT UNIQUE NOT NULL,
    entry_date TEXT NOT NULL,
    description TEXT,
    source_module TEXT,
    source_id TEXT,
    entry_type TEXT DEFAULT 'manual',
    status TEXT NOT NULL DEFAULT 'posted',
    currency_code TEXT DEFAULT 'KES',
    branch_id INTEGER,
    period_id INTEGER,
    total_debit REAL NOT NULL DEFAULT 0,
    total_credit REAL NOT NULL DEFAULT 0,
    reversed_by_id INTEGER,
    reverses_id INTEGER,
    posted_by INTEGER,
    posted_by_name TEXT,
    posted_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    deleted_at TEXT,
    FOREIGN KEY(period_id) REFERENCES accounting_periods(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_journal_idempotent
    ON journal_entries(source_module, source_id, entry_type)
    WHERE source_module IS NOT NULL AND source_id IS NOT NULL
      AND deleted_at IS NULL AND status='posted';

CREATE TABLE IF NOT EXISTS journal_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    journal_id INTEGER NOT NULL,
    account_id INTEGER NOT NULL,
    account_code TEXT NOT NULL,
    account_name TEXT,
    debit REAL NOT NULL DEFAULT 0,
    credit REAL NOT NULL DEFAULT 0,
    memo TEXT,
    line_no INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(journal_id) REFERENCES journal_entries(id),
    FOREIGN KEY(account_id) REFERENCES chart_of_accounts(id)
);

CREATE TABLE IF NOT EXISTS account_balances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    period_id INTEGER,
    as_of_date TEXT NOT NULL,
    debit_total REAL NOT NULL DEFAULT 0,
    credit_total REAL NOT NULL DEFAULT 0,
    balance REAL NOT NULL DEFAULT 0,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(account_id, as_of_date, period_id),
    FOREIGN KEY(account_id) REFERENCES chart_of_accounts(id)
);

CREATE TABLE IF NOT EXISTS cash_bank_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    account_code TEXT NOT NULL,
    account_type TEXT NOT NULL DEFAULT 'cash',
    opening_balance REAL DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    branch_id INTEGER,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    deleted_at TEXT,
    UNIQUE(account_code)
);

CREATE TABLE IF NOT EXISTS expense_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    expense_number TEXT UNIQUE NOT NULL,
    expense_date TEXT NOT NULL,
    account_code TEXT NOT NULL,
    pay_from_code TEXT NOT NULL,
    amount REAL NOT NULL,
    description TEXT,
    vendor_name TEXT,
    status TEXT NOT NULL DEFAULT 'approved',
    approved_by INTEGER,
    approved_by_name TEXT,
    attachment_path TEXT,
    journal_id INTEGER,
    currency_code TEXT DEFAULT 'KES',
    branch_id INTEGER,
    created_by INTEGER,
    created_by_name TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS period_closes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    period_id INTEGER NOT NULL,
    closed_at TEXT NOT NULL,
    closed_by INTEGER,
    closed_by_name TEXT,
    trial_balance_json TEXT,
    notes TEXT,
    FOREIGN KEY(period_id) REFERENCES accounting_periods(id)
);

CREATE TABLE IF NOT EXISTS accounting_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    username TEXT,
    action TEXT NOT NULL,
    entity_type TEXT,
    entity_id TEXT,
    details TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS accounting_transfers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transfer_number TEXT UNIQUE NOT NULL,
    transfer_date TEXT NOT NULL,
    from_code TEXT NOT NULL,
    to_code TEXT NOT NULL,
    amount REAL NOT NULL,
    description TEXT,
    journal_id INTEGER,
    created_by INTEGER,
    created_by_name TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    deleted_at TEXT
);
"""


def ensure_accounting_schema(conn) -> None:
    """Create accounting tables + seed COA / cash links / open period."""
    conn.executescript(ACCOUNTING_DDL)
    # currency_code setting (prefer code over symbol-only)
    cur = conn.execute(
        "SELECT value FROM system_settings WHERE key='currency_code'"
    ).fetchone()
    if not cur:
        sym = conn.execute(
            "SELECT value FROM system_settings WHERE key='currency_symbol'"
        ).fetchone()
        code = (sym[0] if sym else None) or 'KES'
        conn.execute(
            "INSERT OR IGNORE INTO system_settings (key, value) VALUES (?,?)",
            ('currency_code', str(code).strip() or 'KES')
        )
    seed_chart_of_accounts(conn)
    _seed_cash_bank_links(conn)
    _ensure_open_period(conn)
    # Multi-currency / FX stub setting
    conn.execute(
        "INSERT OR IGNORE INTO system_settings (key, value) VALUES (?,?)",
        ('accounting_fx_enabled', '0')
    )
    conn.execute(
        "INSERT OR IGNORE INTO system_settings (key, value) VALUES (?,?)",
        ('accounting_multi_branch', '0')
    )


def seed_chart_of_accounts(conn) -> int:
    """Insert default COA rows if missing. Returns count inserted."""
    currency = get_currency_code(conn)
    now = datetime.now().isoformat()
    inserted = 0
    for code, name, atype, subtype, nb, is_sys, desc in DEFAULT_COA:
        exists = conn.execute(
            "SELECT id FROM chart_of_accounts WHERE code=?", (code,)
        ).fetchone()
        if exists:
            continue
        conn.execute(
            "INSERT INTO chart_of_accounts "
            "(code,name,account_type,subtype,normal_balance,is_system,is_active,"
            "description,currency_code,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,1,?,?,?,?)",
            (code, name, atype, subtype, nb, is_sys, desc, currency, now, now)
        )
        inserted += 1
    return inserted


def _seed_cash_bank_links(conn) -> None:
    links = [
        ('Cash on Hand', '1000', 'cash'),
        ('M-Pesa', '1010', 'mobile'),
        ('Bank Account', '1020', 'bank'),
        ('Card Clearing', '1030', 'card'),
    ]
    for name, code, atype in links:
        conn.execute(
            "INSERT OR IGNORE INTO cash_bank_accounts "
            "(name, account_code, account_type, is_active) VALUES (?,?,?,1)",
            (name, code, atype)
        )


def _ensure_open_period(conn) -> None:
    year = date.today().year
    start = f'{year}-01-01'
    end = f'{year}-12-31'
    row = conn.execute(
        "SELECT id FROM accounting_periods WHERE start_date=? AND end_date=?",
        (start, end)
    ).fetchone()
    if not row:
        conn.execute(
            "INSERT INTO accounting_periods (name, start_date, end_date, status) "
            "VALUES (?,?,?,'open')",
            (f'FY {year}', start, end)
        )


def accounting_audit(conn, user_id, username, action, entity_type='',
                     entity_id='', details='') -> None:
    conn.execute(
        "INSERT INTO accounting_audit "
        "(user_id,username,action,entity_type,entity_id,details) "
        "VALUES (?,?,?,?,?,?)",
        (user_id, username or '', action, entity_type, str(entity_id or ''),
         details or '')
    )


# ── Account helpers ────────────────────────────────────────────────────────────

def get_account(conn, code: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM chart_of_accounts WHERE code=? AND deleted_at IS NULL",
        (code,)
    ).fetchone()
    return dict(row) if row else None


def require_account(conn, code: str) -> dict:
    acc = get_account(conn, code)
    if not acc or not int(acc.get('is_active') or 0):
        raise ValueError(f'Account {code} not found or inactive')
    return acc


def payment_method_account(method: str) -> str:
    m = (method or 'cash').strip().lower()
    return PAYMENT_ACCOUNT.get(m, '1000')


def list_accounts(conn, active_only=True, account_type=None) -> list:
    clauses = ["deleted_at IS NULL"]
    params: list = []
    if active_only:
        clauses.append("is_active=1")
    if account_type:
        clauses.append("account_type=?")
        params.append(account_type)
    where = " WHERE " + " AND ".join(clauses)
    rows = conn.execute(
        f"SELECT * FROM chart_of_accounts{where} ORDER BY code", params
    ).fetchall()
    return [dict(r) for r in rows]


def upsert_account(conn, data: dict, *, user_id=None, username='') -> dict:
    code = (data.get('code') or '').strip()
    name = (data.get('name') or '').strip()
    atype = (data.get('account_type') or '').strip().lower()
    if not code or not name or atype not in ACCOUNT_TYPE_ORDER:
        return {'error': 'code, name, and valid account_type are required'}
    nb = data.get('normal_balance') or (
        'debit' if atype in ('asset', 'expense', 'cogs') else 'credit'
    )
    now = datetime.now().isoformat()
    existing = get_account(conn, code)
    if existing:
        if int(existing.get('is_system') or 0) and data.get('force') is not True:
            # Allow rename/description only on system accounts
            conn.execute(
                "UPDATE chart_of_accounts SET name=?, description=?, updated_at=? WHERE code=?",
                (name, data.get('description') or existing.get('description'), now, code)
            )
        else:
            conn.execute(
                "UPDATE chart_of_accounts SET name=?, account_type=?, subtype=?,"
                " normal_balance=?, description=?, is_active=?, updated_at=? WHERE code=?",
                (name, atype, data.get('subtype'), nb,
                 data.get('description'), int(data.get('is_active', 1)), now, code)
            )
        accounting_audit(conn, user_id, username, 'UPDATE_ACCOUNT', 'account', code, name)
        return {'success': True, 'code': code, 'updated': True}
    conn.execute(
        "INSERT INTO chart_of_accounts "
        "(code,name,account_type,subtype,normal_balance,is_system,is_active,"
        "description,currency_code,created_at,updated_at) VALUES (?,?,?,?,?,0,?,?,?,?,?)",
        (code, name, atype, data.get('subtype'), nb,
         int(data.get('is_active', 1)), data.get('description'),
         get_currency_code(conn), now, now)
    )
    accounting_audit(conn, user_id, username, 'CREATE_ACCOUNT', 'account', code, name)
    return {'success': True, 'code': code, 'created': True}


def soft_delete_account(conn, code: str, *, user_id=None, username='') -> dict:
    acc = get_account(conn, code)
    if not acc:
        return {'error': 'Account not found'}
    if int(acc.get('is_system') or 0):
        return {'error': 'System accounts cannot be deleted'}
    used = conn.execute(
        "SELECT COUNT(*) FROM journal_lines WHERE account_code=?", (code,)
    ).fetchone()[0]
    if used:
        conn.execute(
            "UPDATE chart_of_accounts SET is_active=0, updated_at=? WHERE code=?",
            (datetime.now().isoformat(), code)
        )
        accounting_audit(conn, user_id, username, 'DEACTIVATE_ACCOUNT', 'account', code, '')
        return {'success': True, 'deactivated': True}
    conn.execute(
        "UPDATE chart_of_accounts SET deleted_at=?, is_active=0, updated_at=? WHERE code=?",
        (datetime.now().isoformat(), datetime.now().isoformat(), code)
    )
    accounting_audit(conn, user_id, username, 'DELETE_ACCOUNT', 'account', code, '')
    return {'success': True, 'deleted': True}


# ── Journal engine ─────────────────────────────────────────────────────────────

class UnbalancedJournalError(ValueError):
    pass


class PeriodClosedError(ValueError):
    pass


def _next_entry_number(conn) -> str:
    year = date.today().year
    prefix = f'JE-{year}-'
    row = conn.execute(
        "SELECT entry_number FROM journal_entries "
        "WHERE entry_number LIKE ? ORDER BY id DESC LIMIT 1",
        (prefix + '%',)
    ).fetchone()
    n = 0
    if row and row[0]:
        try:
            n = int(str(row[0]).rsplit('-', 1)[-1])
        except ValueError:
            n = 0
    return f'{prefix}{n + 1:06d}'


def find_posted_entry(conn, source_module: str, source_id: str,
                      entry_type: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM journal_entries WHERE source_module=? AND source_id=? "
        "AND entry_type=? AND status='posted' AND deleted_at IS NULL",
        (source_module, str(source_id), entry_type)
    ).fetchone()
    return dict(row) if row else None


def period_for_date(conn, entry_date: str) -> Optional[dict]:
    d = (entry_date or '')[:10]
    row = conn.execute(
        "SELECT * FROM accounting_periods WHERE date(?) BETWEEN date(start_date) "
        "AND date(end_date) ORDER BY id DESC LIMIT 1",
        (d,)
    ).fetchone()
    return dict(row) if row else None


def assert_period_open(conn, entry_date: str) -> Optional[dict]:
    period = period_for_date(conn, entry_date)
    if period and (period.get('status') or '') == 'closed':
        raise PeriodClosedError(
            f"Accounting period '{period.get('name')}' is closed — cannot post.")
    return period


def post_journal(
    conn,
    lines: Sequence[dict],
    *,
    description: str = '',
    entry_date: Optional[str] = None,
    source_module: Optional[str] = None,
    source_id: Optional[str] = None,
    entry_type: str = 'manual',
    user_id=None,
    username: str = '',
    branch_id=None,
    currency_code: Optional[str] = None,
    allow_empty: bool = False,
) -> dict:
    """
    Post a balanced journal. Each line: {account_code, debit?, credit?, memo?}
    Rejects unbalanced entries. Idempotent when source_module+source_id+entry_type set.
    """
    if source_module and source_id is not None:
        existing = find_posted_entry(conn, source_module, str(source_id), entry_type)
        if existing:
            return {'success': True, 'journal_id': existing['id'],
                    'entry_number': existing['entry_number'], 'idempotent': True}

    entry_date = (entry_date or date.today().isoformat())[:10]
    period = assert_period_open(conn, entry_date)
    currency_code = currency_code or get_currency_code(conn)

    prepared = []
    total_dr = Decimal('0')
    total_cr = Decimal('0')
    for i, raw in enumerate(lines or []):
        code = (raw.get('account_code') or raw.get('code') or '').strip()
        if not code:
            continue
        dr = D(raw.get('debit') or 0)
        cr = D(raw.get('credit') or 0)
        if dr < 0 or cr < 0:
            raise ValueError('Debit/credit amounts cannot be negative')
        if dr > 0 and cr > 0:
            raise ValueError(f'Line {code}: cannot have both debit and credit')
        if dr == 0 and cr == 0:
            continue
        acc = require_account(conn, code)
        prepared.append({
            'account_id': acc['id'],
            'account_code': code,
            'account_name': acc['name'],
            'debit': dr,
            'credit': cr,
            'memo': (raw.get('memo') or '')[:500],
            'line_no': i + 1,
        })
        total_dr += dr
        total_cr += cr

    if not prepared:
        if allow_empty:
            return {'success': True, 'skipped': True, 'reason': 'empty'}
        raise ValueError('Journal has no lines')

    if total_dr != total_cr:
        raise UnbalancedJournalError(
            f'Journal unbalanced: debit={total_dr} credit={total_cr} '
            f'diff={total_dr - total_cr}'
        )

    now = datetime.now().isoformat()
    entry_number = _next_entry_number(conn)
    conn.execute(
        "INSERT INTO journal_entries "
        "(entry_number,entry_date,description,source_module,source_id,entry_type,"
        "status,currency_code,branch_id,period_id,total_debit,total_credit,"
        "posted_by,posted_by_name,posted_at,created_at) "
        "VALUES (?,?,?,?,?,?,'posted',?,?,?,?,?,?,?,?,?)",
        (entry_number, entry_date, description or '',
         source_module, str(source_id) if source_id is not None else None,
         entry_type, currency_code, branch_id,
         period['id'] if period else None,
         money_float(total_dr), money_float(total_cr),
         user_id, username or '', now, now)
    )
    jid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    for ln in prepared:
        conn.execute(
            "INSERT INTO journal_lines "
            "(journal_id,account_id,account_code,account_name,debit,credit,memo,line_no) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (jid, ln['account_id'], ln['account_code'], ln['account_name'],
             money_float(ln['debit']), money_float(ln['credit']),
             ln['memo'], ln['line_no'])
        )

    accounting_audit(
        conn, user_id, username, 'POST_JOURNAL', 'journal', jid,
        f"{entry_number} {description} dr={total_dr} cr={total_cr} "
        f"src={source_module}:{source_id}:{entry_type}"
    )
    return {
        'success': True,
        'journal_id': jid,
        'entry_number': entry_number,
        'total_debit': money_float(total_dr),
        'total_credit': money_float(total_cr),
    }


def reverse_journal(
    conn,
    journal_id: int,
    *,
    reason: str = '',
    user_id=None,
    username: str = '',
    entry_date: Optional[str] = None,
    source_module: Optional[str] = None,
    source_id: Optional[str] = None,
    entry_type: str = 'reversal',
) -> dict:
    """Create a reversing journal (swap debits/credits). Original stays posted."""
    orig = conn.execute(
        "SELECT * FROM journal_entries WHERE id=? AND deleted_at IS NULL",
        (journal_id,)
    ).fetchone()
    if not orig:
        return {'error': 'Journal not found'}
    orig = dict(orig)
    if orig.get('reversed_by_id'):
        return {'error': 'Journal already reversed',
                'reversed_by_id': orig['reversed_by_id']}
    if (orig.get('status') or '') != 'posted':
        return {'error': 'Only posted journals can be reversed'}

    if source_module and source_id is not None:
        existing = find_posted_entry(conn, source_module, str(source_id), entry_type)
        if existing:
            return {'success': True, 'journal_id': existing['id'],
                    'entry_number': existing['entry_number'], 'idempotent': True}

    lines = conn.execute(
        "SELECT * FROM journal_lines WHERE journal_id=? ORDER BY line_no, id",
        (journal_id,)
    ).fetchall()
    rev_lines = []
    for ln in lines:
        rev_lines.append({
            'account_code': ln['account_code'],
            'debit': float(ln['credit'] or 0),
            'credit': float(ln['debit'] or 0),
            'memo': f"Reversal: {ln['memo'] or ''}".strip(),
        })
    desc = f"REVERSAL of {orig['entry_number']}"
    if reason:
        desc += f" — {reason}"
    result = post_journal(
        conn, rev_lines,
        description=desc,
        entry_date=entry_date or date.today().isoformat(),
        source_module=source_module or orig.get('source_module'),
        source_id=source_id if source_id is not None else (
            f"rev:{orig.get('source_id')}" if orig.get('source_id') else None
        ),
        entry_type=entry_type,
        user_id=user_id,
        username=username,
        branch_id=orig.get('branch_id'),
        currency_code=orig.get('currency_code'),
    )
    if result.get('journal_id'):
        conn.execute(
            "UPDATE journal_entries SET reversed_by_id=? WHERE id=?",
            (result['journal_id'], journal_id)
        )
        conn.execute(
            "UPDATE journal_entries SET reverses_id=? WHERE id=?",
            (journal_id, result['journal_id'])
        )
        accounting_audit(
            conn, user_id, username, 'REVERSE_JOURNAL', 'journal', journal_id,
            f"→ {result.get('entry_number')} reason={reason}"
        )
    return result


def get_journal(conn, journal_id: int) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM journal_entries WHERE id=?", (journal_id,)
    ).fetchone()
    if not row:
        return None
    entry = dict(row)
    entry['lines'] = [dict(r) for r in conn.execute(
        "SELECT * FROM journal_lines WHERE journal_id=? ORDER BY line_no, id",
        (journal_id,)
    ).fetchall()]
    return entry


def list_journals(conn, start=None, end=None, source_module=None,
                  limit=500) -> list:
    clauses = ["deleted_at IS NULL"]
    params: list = []
    if start:
        clauses.append("date(entry_date)>=date(?)")
        params.append(start)
    if end:
        clauses.append("date(entry_date)<=date(?)")
        params.append(end)
    if source_module:
        clauses.append("source_module=?")
        params.append(source_module)
    where = " WHERE " + " AND ".join(clauses)
    params.append(int(limit))
    rows = conn.execute(
        f"SELECT * FROM journal_entries{where} ORDER BY entry_date DESC, id DESC "
        f"LIMIT ?", params
    ).fetchall()
    return [dict(r) for r in rows]


# ── Balances & reports ─────────────────────────────────────────────────────────

def account_activity(conn, account_code: str, start=None, end=None) -> dict:
    clauses = [
        "jl.account_code=?",
        "je.status='posted'",
        "je.deleted_at IS NULL",
    ]
    params: list = [account_code]
    if start:
        clauses.append("date(je.entry_date)>=date(?)")
        params.append(start)
    if end:
        clauses.append("date(je.entry_date)<=date(?)")
        params.append(end)
    where = " AND ".join(clauses)
    rows = [dict(r) for r in conn.execute(
        f"SELECT je.entry_number, je.entry_date, je.description, je.source_module,"
        f" je.source_id, jl.debit, jl.credit, jl.memo "
        f"FROM journal_lines jl "
        f"JOIN journal_entries je ON je.id=jl.journal_id "
        f"WHERE {where} ORDER BY je.entry_date, je.id, jl.line_no",
        params
    ).fetchall()]
    dr = sum(D(r['debit']) for r in rows)
    cr = sum(D(r['credit']) for r in rows)
    acc = get_account(conn, account_code) or {}
    nb = acc.get('normal_balance') or 'debit'
    bal = dr - cr if nb == 'debit' else cr - dr
    return {
        'account': acc,
        'lines': rows,
        'total_debit': money_float(dr),
        'total_credit': money_float(cr),
        'balance': money_float(bal),
    }


def trial_balance(conn, as_of=None, start=None) -> dict:
    """Trial balance: all accounts with activity (or all active)."""
    as_of = (as_of or date.today().isoformat())[:10]
    clauses = [
        "je.status='posted'",
        "je.deleted_at IS NULL",
        "date(je.entry_date)<=date(?)",
    ]
    params: list = [as_of]
    if start:
        clauses.append("date(je.entry_date)>=date(?)")
        params.append(start)
    where = " AND ".join(clauses)
    rows = conn.execute(
        f"SELECT coa.code, coa.name, coa.account_type, coa.normal_balance,"
        f" COALESCE(SUM(jl.debit),0) as debit_total,"
        f" COALESCE(SUM(jl.credit),0) as credit_total "
        f"FROM chart_of_accounts coa "
        f"LEFT JOIN journal_lines jl ON jl.account_code=coa.code "
        f"LEFT JOIN journal_entries je ON je.id=jl.journal_id AND {where} "
        f"WHERE coa.deleted_at IS NULL AND coa.is_active=1 "
        f"GROUP BY coa.code ORDER BY coa.code",
        params
    ).fetchall()
    accounts = []
    tot_dr = Decimal('0')
    tot_cr = Decimal('0')
    for r in rows:
        dr = D(r['debit_total'])
        cr = D(r['credit_total'])
        if dr == 0 and cr == 0:
            continue
        nb = r['normal_balance'] or 'debit'
        bal_dr = max(dr - cr, Decimal('0')) if nb == 'debit' else max(cr - dr, Decimal('0'))
        bal_cr = max(cr - dr, Decimal('0')) if nb == 'debit' else max(dr - cr, Decimal('0'))
        # Present as TB columns: debit balance / credit balance
        if nb == 'debit':
            tb_dr = dr - cr
            tb_cr = Decimal('0')
            if tb_dr < 0:
                tb_cr = -tb_dr
                tb_dr = Decimal('0')
        else:
            tb_cr = cr - dr
            tb_dr = Decimal('0')
            if tb_cr < 0:
                tb_dr = -tb_cr
                tb_cr = Decimal('0')
        accounts.append({
            'code': r['code'],
            'name': r['name'],
            'account_type': r['account_type'],
            'debit': money_float(tb_dr),
            'credit': money_float(tb_cr),
            'raw_debit': money_float(dr),
            'raw_credit': money_float(cr),
        })
        tot_dr += tb_dr
        tot_cr += tb_cr
    return {
        'as_of': as_of,
        'start': start,
        'accounts': accounts,
        'total_debit': money_float(tot_dr),
        'total_credit': money_float(tot_cr),
        'balanced': tot_dr == tot_cr,
        'currency_code': get_currency_code(conn),
    }


def profit_and_loss(conn, start=None, end=None) -> dict:
    start = (start or f'{date.today().year}-01-01')[:10]
    end = (end or date.today().isoformat())[:10]
    rows = conn.execute(
        """
        SELECT coa.code, coa.name, coa.account_type, coa.normal_balance,
               COALESCE(SUM(jl.debit),0) as debit_total,
               COALESCE(SUM(jl.credit),0) as credit_total
        FROM chart_of_accounts coa
        LEFT JOIN journal_lines jl ON jl.account_code=coa.code
        LEFT JOIN journal_entries je ON je.id=jl.journal_id
            AND je.status='posted' AND je.deleted_at IS NULL
            AND date(je.entry_date) BETWEEN date(?) AND date(?)
        WHERE coa.deleted_at IS NULL AND coa.is_active=1
          AND coa.account_type IN ('income','cogs','expense')
        GROUP BY coa.code
        ORDER BY coa.account_type, coa.code
        """,
        (start, end)
    ).fetchall()
    income, cogs, expenses = [], [], []
    inc_tot = cogs_tot = exp_tot = Decimal('0')
    for r in rows:
        dr, cr = D(r['debit_total']), D(r['credit_total'])
        atype = r['account_type']
        if atype == 'income':
            amt = cr - dr
            if amt == 0:
                continue
            income.append({'code': r['code'], 'name': r['name'], 'amount': money_float(amt)})
            inc_tot += amt
        elif atype == 'cogs':
            amt = dr - cr
            if amt == 0:
                continue
            cogs.append({'code': r['code'], 'name': r['name'], 'amount': money_float(amt)})
            cogs_tot += amt
        else:
            amt = dr - cr
            if amt == 0:
                continue
            expenses.append({'code': r['code'], 'name': r['name'], 'amount': money_float(amt)})
            exp_tot += amt
    gross = inc_tot - cogs_tot
    net = gross - exp_tot
    return {
        'start': start, 'end': end,
        'income': income, 'cogs': cogs, 'expenses': expenses,
        'total_income': money_float(inc_tot),
        'total_cogs': money_float(cogs_tot),
        'gross_profit': money_float(gross),
        'total_expenses': money_float(exp_tot),
        'net_profit': money_float(net),
        'currency_code': get_currency_code(conn),
    }


def balance_sheet(conn, as_of=None) -> dict:
    as_of = (as_of or date.today().isoformat())[:10]
    # Assets / liabilities / equity from inception to as_of
    rows = conn.execute(
        """
        SELECT coa.code, coa.name, coa.account_type, coa.normal_balance,
               COALESCE(SUM(jl.debit),0) as debit_total,
               COALESCE(SUM(jl.credit),0) as credit_total
        FROM chart_of_accounts coa
        LEFT JOIN journal_lines jl ON jl.account_code=coa.code
        LEFT JOIN journal_entries je ON je.id=jl.journal_id
            AND je.status='posted' AND je.deleted_at IS NULL
            AND date(je.entry_date)<=date(?)
        WHERE coa.deleted_at IS NULL AND coa.is_active=1
          AND coa.account_type IN ('asset','liability','equity')
        GROUP BY coa.code
        ORDER BY coa.code
        """,
        (as_of,)
    ).fetchall()
    # Current year P&L rolls into equity
    pl = profit_and_loss(conn, f'{as_of[:4]}-01-01', as_of)
    assets, liabilities, equity = [], [], []
    a_tot = l_tot = e_tot = Decimal('0')
    for r in rows:
        dr, cr = D(r['debit_total']), D(r['credit_total'])
        atype = r['account_type']
        if atype == 'asset':
            amt = dr - cr
            if abs(amt) < Decimal('0.005'):
                continue
            assets.append({'code': r['code'], 'name': r['name'], 'amount': money_float(amt)})
            a_tot += amt
        elif atype == 'liability':
            amt = cr - dr
            if abs(amt) < Decimal('0.005'):
                continue
            liabilities.append({'code': r['code'], 'name': r['name'], 'amount': money_float(amt)})
            l_tot += amt
        else:
            amt = cr - dr
            if abs(amt) < Decimal('0.005'):
                continue
            equity.append({'code': r['code'], 'name': r['name'], 'amount': money_float(amt)})
            e_tot += amt
    net = D(pl['net_profit'])
    if abs(net) >= Decimal('0.005'):
        equity.append({
            'code': 'PL',
            'name': f"Current Year Earnings ({as_of[:4]})",
            'amount': money_float(net),
        })
        e_tot += net
    return {
        'as_of': as_of,
        'assets': assets, 'liabilities': liabilities, 'equity': equity,
        'total_assets': money_float(a_tot),
        'total_liabilities': money_float(l_tot),
        'total_equity': money_float(e_tot),
        'total_liabilities_equity': money_float(l_tot + e_tot),
        'balanced': abs(a_tot - (l_tot + e_tot)) < Decimal('0.02'),
        'currency_code': get_currency_code(conn),
    }


def cash_book(conn, account_code='1000', start=None, end=None) -> dict:
    return account_activity(conn, account_code, start, end)


def dashboard_kpis(conn) -> dict:
    today = date.today().isoformat()
    month_start = date.today().replace(day=1).isoformat()
    pl = profit_and_loss(conn, month_start, today)
    tb = trial_balance(conn, today)
    cash = account_activity(conn, '1000', None, today)
    bank = account_activity(conn, '1020', None, today)
    mpesa = account_activity(conn, '1010', None, today)
    ar = account_activity(conn, '1100', None, today)
    je_count = conn.execute(
        "SELECT COUNT(*) FROM journal_entries WHERE status='posted' "
        "AND deleted_at IS NULL AND date(entry_date)=date('now')"
    ).fetchone()[0]
    return {
        'month_revenue': pl['total_income'],
        'month_expenses': pl['total_expenses'],
        'month_net': pl['net_profit'],
        'cash_balance': cash['balance'],
        'bank_balance': bank['balance'],
        'mpesa_balance': mpesa['balance'],
        'ar_balance': ar['balance'],
        'journals_today': je_count,
        'trial_balanced': tb['balanced'],
        'currency_code': get_currency_code(conn),
    }


# ── Expenses & transfers ───────────────────────────────────────────────────────

def _next_doc(conn, table: str, col: str, prefix: str) -> str:
    row = conn.execute(
        f"SELECT {col} FROM {table} WHERE {col} LIKE ? ORDER BY id DESC LIMIT 1",
        (prefix + '%',)
    ).fetchone()
    n = 0
    if row and row[0]:
        try:
            n = int(str(row[0]).rsplit('-', 1)[-1])
        except ValueError:
            n = 0
    return f'{prefix}{n + 1:06d}'


def create_expense(conn, data: dict, *, user_id=None, username='') -> dict:
    amount = D(data.get('amount') or 0)
    if amount <= 0:
        return {'error': 'Amount must be greater than zero'}
    exp_code = (data.get('account_code') or '6000').strip()
    pay_code = (data.get('pay_from_code') or '1000').strip()
    require_account(conn, exp_code)
    require_account(conn, pay_code)
    exp_date = (data.get('expense_date') or date.today().isoformat())[:10]
    num = _next_doc(conn, 'expense_entries', 'expense_number', 'EXP-')
    desc = (data.get('description') or 'Expense').strip()
    result = post_journal(
        conn,
        [
            {'account_code': exp_code, 'debit': amount, 'memo': desc},
            {'account_code': pay_code, 'credit': amount, 'memo': desc},
        ],
        description=f'Expense {num}: {desc}',
        entry_date=exp_date,
        source_module='expense',
        source_id=num,
        entry_type='expense',
        user_id=user_id,
        username=username,
    )
    if not result.get('success'):
        return result
    conn.execute(
        "INSERT INTO expense_entries "
        "(expense_number,expense_date,account_code,pay_from_code,amount,description,"
        "vendor_name,status,approved_by,approved_by_name,attachment_path,journal_id,"
        "currency_code,created_by,created_by_name) "
        "VALUES (?,?,?,?,?,?,?,'approved',?,?,?,?,?,?,?)",
        (num, exp_date, exp_code, pay_code, money_float(amount), desc,
         data.get('vendor_name') or '', user_id, username or '',
         data.get('attachment_path'), result.get('journal_id'),
         get_currency_code(conn), user_id, username or '')
    )
    eid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    return {'success': True, 'id': eid, 'expense_number': num,
            'journal_id': result.get('journal_id')}


def create_transfer(conn, data: dict, *, user_id=None, username='') -> dict:
    amount = D(data.get('amount') or 0)
    if amount <= 0:
        return {'error': 'Amount must be greater than zero'}
    from_code = (data.get('from_code') or '').strip()
    to_code = (data.get('to_code') or '').strip()
    if not from_code or not to_code or from_code == to_code:
        return {'error': 'Distinct from/to accounts required'}
    require_account(conn, from_code)
    require_account(conn, to_code)
    tdate = (data.get('transfer_date') or date.today().isoformat())[:10]
    num = _next_doc(conn, 'accounting_transfers', 'transfer_number', 'TRF-')
    desc = (data.get('description') or f'Transfer {from_code}→{to_code}').strip()
    result = post_journal(
        conn,
        [
            {'account_code': to_code, 'debit': amount, 'memo': desc},
            {'account_code': from_code, 'credit': amount, 'memo': desc},
        ],
        description=f'Transfer {num}: {desc}',
        entry_date=tdate,
        source_module='transfer',
        source_id=num,
        entry_type='transfer',
        user_id=user_id,
        username=username,
    )
    if not result.get('success'):
        return result
    conn.execute(
        "INSERT INTO accounting_transfers "
        "(transfer_number,transfer_date,from_code,to_code,amount,description,"
        "journal_id,created_by,created_by_name) VALUES (?,?,?,?,?,?,?,?,?)",
        (num, tdate, from_code, to_code, money_float(amount), desc,
         result.get('journal_id'), user_id, username or '')
    )
    tid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    return {'success': True, 'id': tid, 'transfer_number': num,
            'journal_id': result.get('journal_id')}


def close_period(conn, period_id: int, *, user_id=None, username='',
                 notes='') -> dict:
    period = conn.execute(
        "SELECT * FROM accounting_periods WHERE id=?", (period_id,)
    ).fetchone()
    if not period:
        return {'error': 'Period not found'}
    period = dict(period)
    if period.get('status') == 'closed':
        return {'error': 'Period already closed'}
    tb = trial_balance(conn, period['end_date'], period['start_date'])
    if not tb.get('balanced'):
        return {
            'error': 'Trial balance does not balance — cannot close period',
            'trial_balance': tb,
        }
    now = datetime.now().isoformat()
    conn.execute(
        "UPDATE accounting_periods SET status='closed', closed_at=?, "
        "closed_by=?, closed_by_name=?, notes=? WHERE id=?",
        (now, user_id, username or '', notes or '', period_id)
    )
    conn.execute(
        "INSERT INTO period_closes "
        "(period_id,closed_at,closed_by,closed_by_name,trial_balance_json,notes) "
        "VALUES (?,?,?,?,?,?)",
        (period_id, now, user_id, username or '',
         json.dumps(tb), notes or '')
    )
    accounting_audit(conn, user_id, username, 'CLOSE_PERIOD', 'period',
                     period_id, period.get('name'))
    return {'success': True, 'period_id': period_id, 'trial_balance': tb}


def reopen_period(conn, period_id: int, *, user_id=None, username='') -> dict:
    conn.execute(
        "UPDATE accounting_periods SET status='open', closed_at=NULL, "
        "closed_by=NULL, closed_by_name=NULL WHERE id=?",
        (period_id,)
    )
    accounting_audit(conn, user_id, username, 'REOPEN_PERIOD', 'period',
                     period_id, '')
    return {'success': True}


def list_periods(conn) -> list:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM accounting_periods ORDER BY start_date DESC"
    ).fetchall()]


def list_expenses(conn, start=None, end=None) -> list:
    clauses = ["deleted_at IS NULL"]
    params: list = []
    if start:
        clauses.append("date(expense_date)>=date(?)")
        params.append(start)
    if end:
        clauses.append("date(expense_date)<=date(?)")
        params.append(end)
    where = " WHERE " + " AND ".join(clauses)
    return [dict(r) for r in conn.execute(
        f"SELECT * FROM expense_entries{where} ORDER BY expense_date DESC, id DESC",
        params
    ).fetchall()]


def get_expense(conn, expense_id: int) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM expense_entries WHERE id=? AND deleted_at IS NULL",
        (expense_id,),
    ).fetchone()
    return dict(row) if row else None


def delete_expense(
    conn, expense_id: int, *, reason: str = '', user_id=None, username='',
) -> dict:
    """Soft-delete expense and reverse its journal (posted entries stay immutable)."""
    exp = get_expense(conn, expense_id)
    if not exp:
        return {'error': 'Expense not found'}
    jid = exp.get('journal_id')
    if jid:
        rev = reverse_journal(
            conn, int(jid),
            reason=reason or f"Delete expense {exp.get('expense_number')}",
            user_id=user_id,
            username=username or '',
            source_module='expense',
            source_id=f"del:{exp.get('expense_number')}",
            entry_type='reversal',
        )
        if rev.get('error') and 'already reversed' not in str(rev.get('error') or '').lower():
            return rev
    now = datetime.now().isoformat()
    conn.execute(
        "UPDATE expense_entries SET deleted_at=?, status='voided' WHERE id=?",
        (now, expense_id),
    )
    accounting_audit(
        conn, user_id, username, 'DELETE_EXPENSE', 'expense', expense_id,
        f"{exp.get('expense_number')} reason={reason}",
    )
    return {'success': True, 'id': expense_id, 'expense_number': exp.get('expense_number')}


def update_expense(
    conn, expense_id: int, data: dict, *, user_id=None, username='',
) -> dict:
    """
    Update expense. Description/vendor-only changes patch the row.
    Amount/account/date changes reverse the old journal and post a replacement.
    """
    exp = get_expense(conn, expense_id)
    if not exp:
        return {'error': 'Expense not found'}

    new_desc = data.get('description')
    if new_desc is None:
        new_desc = exp.get('description') or ''
    new_desc = str(new_desc).strip() or (exp.get('description') or 'Expense')
    new_vendor = data.get('vendor_name')
    if new_vendor is None:
        new_vendor = exp.get('vendor_name') or ''
    new_vendor = str(new_vendor)

    amount = D(data['amount']) if 'amount' in data and data['amount'] is not None else D(exp.get('amount') or 0)
    if amount <= 0:
        return {'error': 'Amount must be greater than zero'}
    exp_code = (data.get('account_code') or exp.get('account_code') or '6000').strip()
    pay_code = (data.get('pay_from_code') or exp.get('pay_from_code') or '1000').strip()
    exp_date = (data.get('expense_date') or exp.get('expense_date') or date.today().isoformat())[:10]
    require_account(conn, exp_code)
    require_account(conn, pay_code)

    money_changed = (
        abs(amount - D(exp.get('amount') or 0)) >= Decimal('0.005')
        or exp_code != (exp.get('account_code') or '')
        or pay_code != (exp.get('pay_from_code') or '')
        or exp_date != (exp.get('expense_date') or '')[:10]
    )

    new_journal_id = exp.get('journal_id')
    if money_changed:
        jid = exp.get('journal_id')
        if jid:
            rev = reverse_journal(
                conn, int(jid),
                reason=f"Update expense {exp.get('expense_number')}",
                user_id=user_id,
                username=username or '',
                source_module='expense',
                source_id=f"upd:{exp.get('expense_number')}",
                entry_type='reversal',
            )
            if rev.get('error') and 'already reversed' not in str(rev.get('error') or '').lower():
                return rev
        result = post_journal(
            conn,
            [
                {'account_code': exp_code, 'debit': amount, 'memo': new_desc},
                {'account_code': pay_code, 'credit': amount, 'memo': new_desc},
            ],
            description=f"Expense {exp.get('expense_number')}: {new_desc}",
            entry_date=exp_date,
            source_module='expense',
            source_id=f"{exp.get('expense_number')}:v2",
            entry_type='expense',
            user_id=user_id,
            username=username or '',
        )
        if not result.get('success'):
            return result
        new_journal_id = result.get('journal_id')

    conn.execute(
        "UPDATE expense_entries SET expense_date=?, account_code=?, pay_from_code=?, "
        "amount=?, description=?, vendor_name=?, journal_id=?, "
        "attachment_path=COALESCE(?, attachment_path) WHERE id=?",
        (
            exp_date, exp_code, pay_code, money_float(amount), new_desc, new_vendor,
            new_journal_id,
            data.get('attachment_path'),
            expense_id,
        ),
    )
    accounting_audit(
        conn, user_id, username, 'UPDATE_EXPENSE', 'expense', expense_id,
        f"{exp.get('expense_number')} amt={money_float(amount)}",
    )
    return {
        'success': True,
        'id': expense_id,
        'expense_number': exp.get('expense_number'),
        'journal_id': new_journal_id,
    }


def ar_aging_from_debts(conn) -> dict:
    """AR aging reads debt_invoices — single source of truth with Debt module."""
    rows = [dict(r) for r in conn.execute(
        """
        SELECT di.*, c.phone,
               COALESCE(di.due_date, date(di.created_at, '+30 days')) as due_calc
        FROM debt_invoices di
        LEFT JOIN customers c ON c.id=di.customer_id
        WHERE di.status NOT IN ('paid','cancelled') AND di.balance > 0.009
        ORDER BY di.customer_name, di.created_at
        """
    ).fetchall()]
    buckets = {'current': 0.0, '1_30': 0.0, '31_60': 0.0, '61_90': 0.0, '90_plus': 0.0}
    by_customer: dict = {}
    today = date.today()
    for inv in rows:
        bal = float(inv.get('balance') or 0)
        due_s = (inv.get('due_calc') or inv.get('created_at') or '')[:10]
        try:
            due = date.fromisoformat(due_s)
            days = (today - due).days
        except Exception:
            days = 0
        if days <= 0:
            key = 'current'
        elif days <= 30:
            key = '1_30'
        elif days <= 60:
            key = '31_60'
        elif days <= 90:
            key = '61_90'
        else:
            key = '90_plus'
        buckets[key] = round(buckets[key] + bal, 2)
        cid = inv.get('customer_id')
        if cid not in by_customer:
            by_customer[cid] = {
                'customer_id': cid,
                'customer_name': inv.get('customer_name'),
                'phone': inv.get('phone') or inv.get('customer_phone'),
                'balance': 0.0,
                'invoices': 0,
            }
        by_customer[cid]['balance'] = round(by_customer[cid]['balance'] + bal, 2)
        by_customer[cid]['invoices'] += 1
    gl_ar = account_activity(conn, '1100')
    return {
        'buckets': buckets,
        'total': round(sum(buckets.values()), 2),
        'customers': sorted(by_customer.values(), key=lambda x: -x['balance']),
        'gl_ar_balance': gl_ar['balance'],
        'note': 'Aging from debt_invoices; GL AR from journals (should reconcile).',
        'currency_code': get_currency_code(conn),
    }


def ap_aging_stub(conn) -> dict:
    """AP stub — purchases module not fully present; schema-ready."""
    gl_ap = account_activity(conn, '2000')
    return {
        'buckets': {'current': 0.0, '1_30': 0.0, '31_60': 0.0, '61_90': 0.0, '90_plus': 0.0},
        'total': 0.0,
        'vendors': [],
        'gl_ap_balance': gl_ap['balance'],
        'note': 'AP aging awaits purchases module; GL AP account is ready.',
        'currency_code': get_currency_code(conn),
    }
