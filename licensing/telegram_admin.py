"""
MBT POS — Telegram License Admin
MugoByte Technologies | mugobyte.com

How targeting works:
  Every command you send includes the customer's device_id (first 12 chars is enough).
  The app only executes a command if its own device_id starts with the prefix you sent.
  This means /revoke_license abc123 only fires on the machine whose ID starts with abc123.
  All other customers' apps see the command, check the prefix, and silently ignore it.

Command format:
  /command [args] [device_prefix]
  e.g.  /revoke_license fcffbb
        /extend_subscription 30 fcffbb
        /activate_license pro 365 fcffbb
        /status            (no prefix = all devices reply with their status)
        /send_key <key>    (sends to customer's Telegram chat — no prefix needed)
"""
import json, time, hmac, hashlib, logging, threading, requests
from datetime import datetime
from typing import Optional

logger = logging.getLogger('telegram_admin')

POLL_TIMEOUT = 20
RETRY_DELAY  = 30

from licensing.license_engine import (
    _MASTER_SECRET, _verify_sig, ADMIN_TELEGRAM_IDS, PLANS,
)


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_TELEGRAM_IDS


def _parse_command(text: str) -> Optional[dict]:
    text = text.strip()
    if not text.startswith('/'):
        return None
    parts = text.split(None, 1)
    cmd   = parts[0].lower()
    args  = parts[1].strip() if len(parts) > 1 else ''
    return {'cmd': cmd, 'args': args}


def _device_matches(engine, args: str) -> tuple[bool, str]:
    """
    Check if the last token in args is a device prefix that matches this engine.
    Returns (matches, remaining_args_without_prefix).
    If no prefix given, returns (True, args) — broadcast to all.
    """
    parts = args.strip().split()
    if not parts:
        return True, args   # no prefix = broadcast

    # Last token treated as device prefix if it looks like a hex string
    last = parts[-1]
    if len(last) >= 6 and all(c in '0123456789abcdefABCDEF' for c in last):
        # It's a device prefix
        matches = engine.device_id.lower().startswith(last.lower())
        remaining = ' '.join(parts[:-1])
        return matches, remaining
    # No device prefix — broadcast
    return True, args


def _device_skip_reply(engine, args: str, shop_name: str) -> str:
    """Tell the admin when a targeted command was ignored on this machine."""
    parts = args.strip().split()
    if not parts:
        return ''
    last = parts[-1]
    if len(last) >= 6 and all(c in '0123456789abcdefABCDEF' for c in last):
        return (
            f"⏭️ <b>{shop_name}</b> — prefix <code>{last}</code> "
            f"does not match this device "
            f"(<code>{engine.device_id[:12]}…</code>)"
        )
    return ''


def _execute_command(cmd: str, args: str, engine, store,
                     reply_fn, shop_name: str = 'MBT POS',
                     config_getter=None,
                     on_state_change=None) -> str:
    """
    Execute a developer command. Returns reply string.
    on_state_change: callable() — fires immediately after state-altering commands
                     so the UI updates in real-time, not after the 5-min tick.
    """
    import json as _json

    # ── /status ───────────────────────────────────────────────────────────────
    if cmd == '/status':
        s = engine.get_status_dict()
        return (
            f"📊 <b>Status — {shop_name}</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"State:    <b>{s['state'].upper()}</b>\n"
            f"Plan:     {s['plan_name']}\n"
            f"Expires:  {s['expiry_date'] or 'N/A'}\n"
            f"Days left:{s['days_remaining']}\n"
            f"Device:   <code>{engine.device_id[:16]}…</code>\n"
            f"Shop:     {shop_name}\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"<i>MugoByte Technologies</i>"
        )

    # ── /activate_license <plan> <days> [device_prefix] ───────────────────────
    elif cmd == '/activate_license':
        matches, clean_args = _device_matches(engine, args)
        if not matches:
            return _device_skip_reply(engine, args, shop_name)

        try:
            parts   = clean_args.split()
            plan    = parts[0] if parts else 'basic'
            if plan not in PLANS:
                return f"❌ Unknown plan <code>{plan}</code>. Use: {', '.join(PLANS)}"
            days    = (
                int(parts[1]) if len(parts) > 1
                else PLANS.get(plan, {}).get('days', 365)
            )
            now     = int(time.time())
            payload = {
                'device_id':  engine.device_id,
                'plan':       plan,
                'issued_at':  now,
                'expires_at': now + days * 86400,
                'issued_by':  'MugoByte Technologies (Remote)',
                'version':    2,
            }
            raw = _json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()
            payload['sig'] = hmac.new(_MASTER_SECRET, raw, hashlib.sha256).hexdigest()
            ok, msg = engine.activate_from_remote(payload)
            store.log('REMOTE_CMD', f'/activate_license plan={plan} days={days} ok={ok}')
            if ok and on_state_change: on_state_change()
            exp = datetime.fromtimestamp(payload['expires_at']).strftime('%Y-%m-%d')
            return (
                f"{'✅' if ok else '❌'} {msg}\n"
                f"Plan: <b>{plan}</b> · {days} days · expires <b>{exp}</b>"
            )
        except Exception as e:
            return f"❌ activate error: {e}"

    # ── /extend_subscription <days> [device_prefix] ───────────────────────────
    elif cmd == '/extend_subscription':
        matches, clean_args = _device_matches(engine, args)
        if not matches:
            return _device_skip_reply(engine, args, shop_name)

        try:
            days = int(clean_args.strip())
            raw  = f"extend:{days}:{engine.device_id}".encode()
            sig  = hmac.new(_MASTER_SECRET, raw, hashlib.sha256).hexdigest()
            ok, msg = engine.extend(days, sig)
            store.log('REMOTE_CMD', f'/extend_subscription +{days}d ok={ok}')
            if ok and on_state_change: on_state_change()
            return f"{'✅' if ok else '❌'} {msg}"
        except Exception as e:
            return f"❌ extend error: {e}"

    # ── /revoke_license [device_prefix] ───────────────────────────────────────
    elif cmd == '/revoke_license':
        matches, _ = _device_matches(engine, args)
        if not matches:
            return _device_skip_reply(engine, args, shop_name)

        raw = f"revoke:{engine.device_id}".encode()
        sig = hmac.new(_MASTER_SECRET, raw, hashlib.sha256).hexdigest()
        ok, msg = engine.revoke(sig)
        store.log('REMOTE_CMD', f'/revoke_license ok={ok}')
        # Fire immediately — app must lock NOW, not after 5-min tick
        if ok and on_state_change: on_state_change()
        return f"{'✅' if ok else '❌'} {msg}"

    # ── /update_expiry <YYYY-MM-DD> [device_prefix] ───────────────────────────
    elif cmd == '/update_expiry':
        parts = args.strip().split()
        # Last token might be device prefix
        if len(parts) >= 2 and all(c in '0123456789abcdefABCDEF' for c in parts[-1]) and len(parts[-1]) >= 6:
            matches = engine.device_id.lower().startswith(parts[-1].lower())
            date_str = parts[0]
        else:
            matches  = True
            date_str = parts[0] if parts else ''
        if not matches:
            return _device_skip_reply(engine, args, shop_name)

        try:
            from datetime import datetime as _dt
            exp_dt = _dt.strptime(date_str, '%Y-%m-%d')
            extra  = int((exp_dt.timestamp() - time.time()) / 86400)
            raw    = f"extend:{extra}:{engine.device_id}".encode()
            sig    = hmac.new(_MASTER_SECRET, raw, hashlib.sha256).hexdigest()
            ok, msg = engine.extend(extra, sig)
            store.log('REMOTE_CMD', f'/update_expiry {date_str} ok={ok}')
            if ok and on_state_change: on_state_change()
            return f"{'✅' if ok else '❌'} Expiry set to {date_str}"
        except Exception as e:
            return f"❌ update_expiry error: {e}"

    # ── /device_id ────────────────────────────────────────────────────────────
    elif cmd == '/device_id':
        return (
            f"🔑 <b>Device ID — {shop_name}</b>\n"
            f"<code>{engine.device_id}</code>\n"
            f"<i>First 8 chars for targeting: <b>{engine.device_id[:8]}</b></i>"
        )

    # ── /send_key <key> ───────────────────────────────────────────────────────
    elif cmd == '/send_key':
        key_msg = args.strip()
        if not key_msg:
            return "❌ Usage: /send_key <key>"
        try:
            cfg       = (config_getter() if config_getter else {}) or {}
            token     = cfg.get('telegram_bot_token', '')
            cust_chat = cfg.get('telegram_chat_id', '').strip()
            if not token:  return "❌ Bot token not configured."
            if not cust_chat: return "❌ Customer Chat ID not set (Settings → Telegram → Connect)."
            msg = (
                f"🔑 <b>MBT POS Activation Key</b>\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"Shop: <b>{shop_name}</b>\n"
                f"<b>Your key:</b>\n"
                f"<code>{key_msg}</code>\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"<i>MBT POS → License tab → paste above → Activate</i>"
            )
            r = requests.post(
                f'https://api.telegram.org/bot{token}/sendMessage',
                json={'chat_id': cust_chat, 'text': msg, 'parse_mode': 'HTML'},
                timeout=10)
            store.log('REMOTE_CMD', f'/send_key ok={r.ok}')
            return (f"✅ Key sent to {cust_chat}." if r.ok
                    else f"❌ Send failed: {r.text[:80]}")
        except Exception as e:
            return f"❌ send_key error: {e}"

    # ── /notify_customer <msg> ────────────────────────────────────────────────
    elif cmd == '/notify_customer':
        message = args.strip()
        if not message: return "❌ Usage: /notify_customer <message>"
        try:
            cfg       = (config_getter() if config_getter else {}) or {}
            token     = cfg.get('telegram_bot_token', '')
            cust_chat = cfg.get('telegram_chat_id', '').strip()
            if not token or not cust_chat:
                return "❌ Telegram not configured on customer's device."
            msg = (
                f"📢 <b>MugoByte Technologies</b>\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"{message}\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"<i>MBT POS · {shop_name}</i>"
            )
            r = requests.post(
                f'https://api.telegram.org/bot{token}/sendMessage',
                json={'chat_id': cust_chat, 'text': msg, 'parse_mode': 'HTML'},
                timeout=10)
            store.log('REMOTE_CMD', f'/notify_customer ok={r.ok}')
            return f"{'✅' if r.ok else '❌'} {message[:60]}"
        except Exception as e:
            return f"❌ notify_customer error: {e}"

    # ── /push_config_update <json> ────────────────────────────────────────────
    elif cmd == '/push_config_update':
        try:
            cfg = json.loads(args)
            store.set('remote_config_push', cfg)
            store.log('REMOTE_CMD', f'/push_config_update keys={list(cfg.keys())}')
            return f"✅ Config push queued: {list(cfg.keys())}"
        except Exception as e:
            return f"❌ push_config_update error: {e}"

    # ── /logs ─────────────────────────────────────────────────────────────────
    elif cmd == '/logs':
        logs = store.get_logs(10)
        if not logs: return "📋 No events logged."
        lines = [f"📋 <b>License Events — {shop_name}</b>"]
        for l in logs:
            ts = datetime.fromtimestamp(l['ts']).strftime('%m/%d %H:%M')
            lines.append(f"  {ts}  {l['event']}  {l.get('detail','')[:40]}")
        return '\n'.join(lines)

    # ── /help ─────────────────────────────────────────────────────────────────
    elif cmd == '/help':
        return (
            "🔧 <b>MBT Admin Commands</b>\n\n"
            "<b>Targeting:</b> append device prefix (first 8+ hex chars) to target one machine.\n"
            "Without prefix, command goes to ALL connected devices.\n\n"
            "<b>License:</b>\n"
            "/status\n"
            "/activate_license &lt;plan&gt; [days] [device]\n"
            "  Plans: trial (30d), basic/pro (365d), lifetime\n"
            "/extend_subscription &lt;days&gt; [device]\n"
            "/revoke_license [device]\n"
            "/update_expiry YYYY-MM-DD [device]\n"
            "/device_id\n\n"
            "<b>Customer messaging:</b>\n"
            "/send_key &lt;key&gt;\n"
            "/notify_customer &lt;msg&gt;\n\n"
            "<b>System:</b>\n"
            "/push_config_update {json}\n"
            "/logs\n\n"
            "<b>Example:</b>\n"
            "<code>/revoke_license fcffbb33</code>\n"
            "<code>/extend_subscription 30 fcffbb33</code>"
        )

    return f"❓ Unknown command: {cmd}"


# ── Hub registration (no separate getUpdates poll) ────────────────────────────

class TelegramAdminListener:
    """Registers admin command handling on the shared TelegramHub."""

    def __init__(self, engine, config_getter, on_state_change=None, hub=None):
        self.engine = engine
        self.config_getter = config_getter
        self.on_state_change = on_state_change
        self._hub = hub
        if hub:
            hub.set_admin_handler(self._handle_update)
            logger.info('Telegram admin commands registered on hub')

    def stop(self):
        if self._hub:
            self._hub.set_admin_handler(None)

    def _handle_update(self, upd: dict, reply_fn):
        msg = upd.get('message', {})
        text = msg.get('text', '')
        user_id = msg.get('from', {}).get('id', 0)
        if not text:
            return

        parsed = _parse_command(text)
        if not parsed:
            return

        if not _is_admin(user_id):
            logger.warning(f'Unauthorised command user_id={user_id}')
            return

        cfg = self.config_getter() or {}
        shop_name = cfg.get('shop_name', 'MBT POS')

        reply = _execute_command(
            parsed['cmd'], parsed['args'],
            self.engine, self.engine.store,
            reply_fn,
            shop_name,
            config_getter=self.config_getter,
            on_state_change=self.on_state_change,
        )
        if reply:
            reply_fn(reply)
