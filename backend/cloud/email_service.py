"""
MugoByte Platform — Email Service.
Resend HTTP API for verification, password reset, and notification delivery.
"""
from __future__ import annotations

import hashlib
import logging
import os
import secrets
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger('cloud.email')

FROM = os.environ.get('EMAIL_FROM', 'MugoByte Platform <noreply@mugobyte.com>')
SITE_URL = os.environ.get('SITE_URL', 'https://portal.mugobyte.com')
SITE_NAME = os.environ.get('SITE_NAME', 'MugoByte Platform')
COMPANY = 'MugoByte Technologies'


def _resend_api_key() -> str:
    key = os.environ.get('RESEND_API_KEY', '').strip()
    if key:
        return key
    try:
        from backend.cloud_backup.paths import load_cloud_config
        cfg = load_cloud_config() or {}
        return (cfg.get('resend_api_key') or cfg.get('RESEND_API_KEY') or '').strip()
    except Exception:
        return ''


def _email_from() -> str:
    try:
        from backend.cloud_backup.paths import load_cloud_config
        cfg = load_cloud_config() or {}
        return (cfg.get('email_from') or os.environ.get('EMAIL_FROM') or FROM).strip()
    except Exception:
        return FROM


def _site_name() -> str:
    return (os.environ.get('SITE_NAME') or SITE_NAME).strip() or 'MugoByte Platform'


def _branded_shell(title: str, body_html: str) -> str:
    name = _site_name()
    year = datetime.utcnow().year
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{title}</title></head>
<body style="margin:0;padding:0;background:#0b1220;font-family:Segoe UI,Helvetica,Arial,sans-serif;color:#e2e8f0;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#0b1220;padding:32px 16px;">
    <tr><td align="center">
      <table role="presentation" width="560" cellspacing="0" cellpadding="0" style="max-width:560px;background:#111827;border-radius:12px;overflow:hidden;border:1px solid #1f2937;">
        <tr><td style="padding:28px 32px 12px;background:linear-gradient(135deg,#1a1f3a,#0b1220);">
          <div style="font-size:20px;font-weight:700;color:#fff;letter-spacing:0.02em;">{COMPANY}</div>
          <div style="font-size:13px;color:#94a3b8;margin-top:4px;">{name}</div>
        </td></tr>
        <tr><td style="padding:8px 32px 28px;">
          <h1 style="margin:16px 0 12px;font-size:20px;color:#f8fafc;">{title}</h1>
          <div style="font-size:15px;line-height:1.6;color:#cbd5e1;">{body_html}</div>
        </td></tr>
        <tr><td style="padding:20px 32px;border-top:1px solid #1f2937;font-size:12px;color:#64748b;line-height:1.6;">
          <a href="{SITE_URL}" style="color:#60a5fa;text-decoration:none;">Open Workspace</a>
          &nbsp;·&nbsp;<a href="{SITE_URL}/support" style="color:#60a5fa;text-decoration:none;">Support</a>
          &nbsp;·&nbsp;<a href="https://mugobyte.com/privacy" style="color:#60a5fa;text-decoration:none;">Privacy</a>
          &nbsp;·&nbsp;<a href="https://mugobyte.com/terms" style="color:#60a5fa;text-decoration:none;">Terms</a>
          <div style="margin-top:10px;">© {year} {COMPANY} · portal.mugobyte.com</div>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


def _ensure_token_table(db: sqlite3.Connection):
    db.execute("""
        CREATE TABLE IF NOT EXISTS email_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            token_hash TEXT NOT NULL,
            token_type TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    db.commit()


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _create_token(db_path: str, email: str, token_type: str, ttl_hours: int = 24) -> str:
    raw = secrets.token_urlsafe(32)
    expires = (datetime.utcnow() + timedelta(hours=ttl_hours)).isoformat()
    db = sqlite3.connect(db_path)
    try:
        _ensure_token_table(db)
        db.execute(
            'INSERT INTO email_tokens (email, token_hash, token_type, expires_at) VALUES (?,?,?,?)',
            (email.lower().strip(), _hash_token(raw), token_type, expires),
        )
        db.commit()
    finally:
        db.close()
    return raw


def _verify_token(db_path: str, raw_token: str, token_type: str) -> Optional[str]:
    db = sqlite3.connect(db_path)
    try:
        _ensure_token_table(db)
        row = db.execute(
            """SELECT id, email, expires_at, used_at FROM email_tokens
               WHERE token_hash=? AND token_type=? ORDER BY id DESC LIMIT 1""",
            (_hash_token(raw_token), token_type),
        ).fetchone()
        if not row:
            return None
        tid, email, expires_at, used_at = row
        if used_at:
            return None
        if datetime.fromisoformat(expires_at) < datetime.utcnow():
            return None
        db.execute('UPDATE email_tokens SET used_at=datetime(\'now\') WHERE id=?', (tid,))
        db.commit()
        return email
    finally:
        db.close()


async def send_transactional_email(to: str, subject: str, html: str) -> bool:
    """Send email via Resend HTTP API."""
    api_key = _resend_api_key()
    if not api_key:
        logger.info('[email] RESEND_API_KEY not set — would send to %s: %s', to, subject)
        return False
    try:
        import requests
        r = requests.post(
            'https://api.resend.com/emails',
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json={'from': _email_from(), 'to': [to], 'subject': subject, 'html': html},
            timeout=15,
        )
        if not r.ok:
            logger.error('[email] Resend failed: %s %s', r.status_code, r.text[:200])
            return False
        return True
    except Exception as e:
        logger.error('[email] send failed: %s', e)
        return False


def send_password_reset_email(db_path: str, email: str) -> bool:
    name = _site_name()
    raw = _create_token(db_path, email, 'password_reset', ttl_hours=1)
    reset_url = f'{SITE_URL}/reset-password?token={raw}'
    body = f"""
    <p>Hello,</p>
    <p>We received a request to reset your {name} password.</p>
    <p><a href="{reset_url}" style="display:inline-block;margin:12px 0;padding:10px 18px;background:#3b82f6;color:#fff;border-radius:8px;text-decoration:none;">Reset password</a></p>
    <p>This link expires in 1 hour. If you did not request this, ignore this email.</p>
    """
    html = _branded_shell(f'Reset your {name} password', body)
    return _sync_send(email, f'Reset your {name} password', html)


def send_verification_email(db_path: str, email: str) -> bool:
    name = _site_name()
    raw = _create_token(db_path, email, 'email_verification', ttl_hours=24)
    verify_url = f'{SITE_URL}/verify-email?token={raw}'
    return send_confirm_link_email(email, verify_url)


def send_confirm_link_email(email: str, confirm_url: str, *, subject: str = '', title: str = '') -> bool:
    """Send a branded email with an absolute Auth action link."""
    name = _site_name()
    title = title or f'Verify your {name} email'
    subject = subject or title
    body = f"""
    <p>Hello,</p>
    <p>Thanks for joining {name}. Confirm your email to access MugoByte Workspace.</p>
    <p><a href="{confirm_url}" style="display:inline-block;margin:12px 0;padding:10px 18px;background:#3b82f6;color:#fff;border-radius:8px;text-decoration:none;">Continue</a></p>
    <p>If the button does not work, copy this link into your browser:</p>
    <p style="word-break:break-all;font-size:12px;color:#94a3b8;">{confirm_url}</p>
    <p>This link expires in 24 hours.</p>
    """
    if 'reset' in subject.lower() or 'password' in subject.lower():
        body = f"""
        <p>Hello,</p>
        <p>We received a request to reset your {name} password.</p>
        <p><a href="{confirm_url}" style="display:inline-block;margin:12px 0;padding:10px 18px;background:#3b82f6;color:#fff;border-radius:8px;text-decoration:none;">Reset password</a></p>
        <p style="word-break:break-all;font-size:12px;color:#94a3b8;">{confirm_url}</p>
        <p>This link expires in 1 hour. If you did not request this, ignore this email.</p>
        """
        title = subject
    html = _branded_shell(title, body)
    return _sync_send(email, subject, html)


def send_notification_email(to: str, title: str, body: str) -> bool:
    html = _branded_shell(title, f'<p>{body}</p>')
    return _sync_send(to, title, html)


def verify_email_token(db_path: str, raw_token: str) -> str | None:
    return _verify_token(db_path, raw_token, 'email_verification')


def verify_reset_token(db_path: str, raw_token: str) -> str | None:
    return _verify_token(db_path, raw_token, 'password_reset')


def _sync_send(to: str, subject: str, html: str) -> bool:
    api_key = _resend_api_key()
    if not api_key:
        logger.info('[email] RESEND_API_KEY not set — would send to %s: %s', to, subject)
        return False
    try:
        import requests
        r = requests.post(
            'https://api.resend.com/emails',
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json={'from': _email_from(), 'to': [to], 'subject': subject, 'html': html},
            timeout=15,
        )
        return r.ok
    except Exception as e:
        logger.error('[email] send failed: %s', e)
        return False
