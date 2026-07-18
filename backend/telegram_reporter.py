"""
MBT POS – Telegram Reporter
MugoByte Technologies | mugobyte.com

Handles:
  • Manual (on-demand) report delivery with success/failure feedback
  • Queued automatic daily/weekly reports (idempotent per business+date)
  • Offline persistence: PENDING → SENDING → SENT | FAILED | RETRYING
  • Singleton scheduler with catch-up on startup
  • Retry logic with exponential back-off
  • Token-safe structured logging
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from datetime import date, datetime, timedelta
from typing import Callable, Optional

logger = logging.getLogger('telegram_reporter')

from mbt_paths import get_project_root

_PROJECT_ROOT = get_project_root()

# ── Singleton scheduler ───────────────────────────────────────────────────────
_scheduler_lock = threading.Lock()
_scheduler_instance: Optional['ReportScheduler'] = None


def get_report_scheduler() -> Optional['ReportScheduler']:
    return _scheduler_instance


def start_report_scheduler(api, config_getter, is_online_getter=None) -> 'ReportScheduler':
    """Start at most one ReportScheduler for the process."""
    global _scheduler_instance
    with _scheduler_lock:
        if _scheduler_instance is not None and _scheduler_instance.is_alive():
            logger.warning(
                'ReportScheduler already RUNNING — refusing duplicate start '
                '(idempotent singleton)'
            )
            _scheduler_instance.api = api
            _scheduler_instance.config_getter = config_getter
            if is_online_getter is not None:
                _scheduler_instance.is_online_getter = is_online_getter
            return _scheduler_instance
        _scheduler_instance = ReportScheduler(api, config_getter, is_online_getter)
        _scheduler_instance.start()
        return _scheduler_instance


def stop_report_scheduler():
    global _scheduler_instance
    with _scheduler_lock:
        if _scheduler_instance:
            _scheduler_instance.stop()
            _scheduler_instance = None


def _redact(text: object) -> str:
    try:
        from backend.telegram_hub import _redact_telegram_url
        return _redact_telegram_url(text)
    except Exception:
        return str(text)


# ── Low-level send helpers ─────────────────────────────────────────────────────

def _telegram_preflight(token: str, chat_id: str) -> tuple[bool, str]:
    """Validate bot token and chat access. Returns (ok, error_msg)."""
    import requests
    api = f'https://api.telegram.org/bot{token}'
    try:
        r = requests.get(f'{api}/getMe', timeout=10)
        if not r.ok:
            return False, 'Invalid Telegram bot token.'
    except Exception as e:
        return False, f'No internet or Telegram unreachable ({_redact(e)}).'

    try:
        r = requests.get(f'{api}/getChat', params={'chat_id': chat_id}, timeout=10)
        if not r.ok:
            try:
                msg = r.json().get('description', '')
            except Exception:
                msg = ''
            low = (msg or '').lower()
            if 'chat not found' in low or 'forbidden' in low:
                return (
                    False,
                    'Chat ID is not linked to this bot (blocked or never started). '
                    'Open the bot and send any message, then reconnect.',
                )
            return False, f'Telegram chat check failed: {msg or f"HTTP {r.status_code}"}'
    except Exception as e:
        return False, f'Internet unstable while checking Telegram chat ({_redact(e)}).'

    return True, ''


def _send_message(token: str, chat_id: str, text: str,
                  parse_mode='HTML', retries=3) -> tuple[bool, str]:
    """Send a text message. Returns (ok, error_msg)."""
    import requests
    last_err = ''
    for attempt in range(1, retries + 1):
        try:
            r = requests.post(
                f'https://api.telegram.org/bot{token}/sendMessage',
                json={'chat_id': chat_id, 'text': text, 'parse_mode': parse_mode},
                timeout=12,
            )
            if r.ok:
                logger.info('Telegram message sent ok (attempt %s)', attempt)
                return True, ''
            try:
                err = r.json().get('description', r.text[:120])
            except Exception:
                err = r.text[:120] or f'HTTP {r.status_code}'
            last_err = err
            logger.warning(
                'Telegram sendMessage attempt %s failed: %s',
                attempt, _redact(err),
            )
            if attempt < retries:
                time.sleep(2 ** attempt)
        except Exception as e:
            last_err = _redact(e)
            logger.warning(
                'Telegram sendMessage attempt %s exception: %s',
                attempt, last_err,
            )
            if attempt < retries:
                time.sleep(2 ** attempt)
    return False, (last_err or f'Failed after {retries} attempts')


def _send_document(token: str, chat_id: str, file_path: str,
                   caption='', retries=3) -> tuple[bool, str]:
    """Send a file. Returns (ok, error_msg)."""
    import requests
    if not os.path.exists(file_path):
        return False, f'File not found: {file_path}'
    last_err = ''
    for attempt in range(1, retries + 1):
        try:
            with open(file_path, 'rb') as f:
                r = requests.post(
                    f'https://api.telegram.org/bot{token}/sendDocument',
                    data={
                        'chat_id': chat_id,
                        'caption': caption,
                        'parse_mode': 'HTML',
                    },
                    files={'document': (os.path.basename(file_path), f)},
                    timeout=60,
                )
            if r.ok:
                logger.info(
                    'Telegram document sent ok: %s',
                    os.path.basename(file_path),
                )
                return True, ''
            try:
                err = r.json().get('description', r.text[:120])
            except Exception:
                err = r.text[:120] or f'HTTP {r.status_code}'
            last_err = err
            logger.warning(
                'Telegram sendDocument attempt %s failed: %s',
                attempt, _redact(err),
            )
            if 'blocked' in (err or '').lower() or 'forbidden' in (err or '').lower():
                return False, err  # no point retrying blocked bot
            if attempt < retries:
                time.sleep(2 ** attempt)
        except Exception as e:
            last_err = _redact(e)
            logger.warning(
                'Telegram sendDocument attempt %s exception: %s',
                attempt, last_err,
            )
            if attempt < retries:
                time.sleep(2 ** attempt)
    return False, (last_err or f'Failed after {retries} attempts')


# ── Report builder ─────────────────────────────────────────────────────────────

def _build_report_file(api, start: str, end: str,
                       shop_name: str, currency: str) -> str:
    """Export Excel report, return path. Works for empty days (0 sales)."""
    sys.path.insert(0, _PROJECT_ROOT)
    from backend.export_engine import export_sales_report
    from desktop.utils.api_client import _get_export_dir

    sales = [
        s for s in (api.get_sales(start, end) or [])
        if (s.get('status') or 'completed') != 'voided'
    ]
    items_by_sale = {}
    try:
        flat = api.get_sale_items_for_range(start, end) or []
        for item in flat:
            sid = item.get('sale_id')
            if sid is not None:
                items_by_sale.setdefault(sid, []).append(item)
        for sale in sales:
            sid = sale.get('id') or sale.get('sale_id')
            sale['item_count'] = len(items_by_sale.get(sid, []))
    except Exception:
        for sale in sales:
            sid = sale.get('id') or sale.get('sale_id')
            d = api.get_sale(sid)
            if d:
                items_by_sale[sid] = d.get('items', [])
                sale['item_count'] = len(items_by_sale[sid])

    try:
        products = api.get_products() or []
    except Exception:
        products = []

    try:
        export_dir = _get_export_dir()
    except Exception:
        export_dir = os.path.join(_PROJECT_ROOT, 'exports')
    os.makedirs(export_dir, exist_ok=True)

    fname = f"MBT_Sales_{start}_to_{end}_{datetime.now().strftime('%H%M%S')}.xlsx"
    out = os.path.join(export_dir, fname)

    try:
        debt_summary = api.get_debt_summary() or {}
    except Exception:
        debt_summary = {}
    try:
        aging_report = api.get_aging_report() or {}
    except Exception:
        aging_report = {}
    try:
        debt_invoices = api.get_debt_invoices(start=start, end=end) or []
    except Exception:
        debt_invoices = []
    try:
        debt_payments = api.get_debt_payments(start=start, end=end) or []
    except Exception:
        debt_payments = []
    try:
        vdata = api.get_payment_variance_report(start, end) or {}
        variance_rows = vdata.get('rows') or []
        variance_summary = vdata.get('summary') or {}
    except Exception:
        variance_rows, variance_summary = [], {}

    path = export_sales_report(
        sales, items_by_sale,
        shop_name=shop_name, start_date=start, end_date=end,
        output_path=out, currency=currency,
        products_data=products,
        debt_summary=debt_summary,
        aging_report=aging_report,
        debt_invoices=debt_invoices,
        debt_payments=debt_payments,
        variance_rows=variance_rows,
        variance_summary=variance_summary,
        generated_by='Telegram Auto-Report',
        filters=f'Date {start} → {end} · completed sales only',
    )
    logger.info(
        'Built report %s→%s (%s sales, empty=%s): %s',
        start, end, len(sales), len(sales) == 0, os.path.basename(path),
    )
    return path


def _report_caption(shop_name: str, start: str, end: str, n_sales: int) -> str:
    empty_note = '\n<i>No sales on this day (empty report).</i>' if n_sales == 0 else ''
    return (
        f'📊 <b>Sales Report — {shop_name}</b>\n'
        f'Period: {start} → {end}\n'
        f'Transactions: <b>{n_sales}</b>{empty_note}\n'
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f'<i>MugoByte Technologies  ·  mugobyte.com</i>'
    )


def validate_telegram_config(cfg: dict | None = None) -> list[str]:
    """Return human-readable config warnings (empty list = OK)."""
    from backend.telegram_hub import resolve_bot_token, resolve_bot_username
    cfg = cfg or {}
    warnings: list[str] = []
    token = resolve_bot_token(cfg)
    chat = (cfg.get('telegram_chat_id') or '').strip()
    bot = resolve_bot_username(cfg)
    if not token:
        warnings.append('Telegram bot token missing — reports cannot send.')
    if not chat:
        warnings.append(
            f'Telegram chat ID not connected — open @{bot} and Connect in Settings.'
        )
    if cfg.get('auto_report_daily', '1') == '1' and (not token or not chat):
        warnings.append(
            'Automatic daily reports are ON but Telegram is incomplete — '
            'fixing is silent until Connect is finished.'
        )
    return warnings


def get_report_health(config_getter=None) -> dict:
    """Settings / diagnostics snapshot — never includes bot token."""
    from backend.daily_report_queue import business_key_from_cfg, get_health
    from backend.telegram_hub import get_hub, resolve_bot_token

    cfg = {}
    if config_getter:
        try:
            cfg = config_getter() or {}
        except Exception:
            cfg = {}
    bkey = business_key_from_cfg(cfg)
    q = get_health(bkey)
    sched = get_report_scheduler()
    hub = get_hub()
    hub_st = hub.get_status() if hub else {'state': 'stopped', 'detail': ''}
    token_ok = bool(resolve_bot_token(cfg))
    chat_ok = bool((cfg.get('telegram_chat_id') or '').strip())
    warnings = validate_telegram_config(cfg)
    last = q.get('last_sent') or {}
    last_any = q.get('last_any') or {}
    return {
        'scheduler': 'RUNNING' if (sched and sched.is_alive()) else 'STOPPED',
        'scheduler_detail': (sched.status_detail() if sched else 'not started'),
        'telegram_connected': chat_ok and token_ok,
        'hub_state': hub_st.get('state', 'unknown'),
        'hub_detail': hub_st.get('detail', ''),
        'config_ok': len(warnings) == 0,
        'config_warnings': warnings,
        'last_report_date': last.get('report_date') or last_any.get('report_date') or '',
        'last_report_status': last.get('status') or last_any.get('status') or 'none',
        'last_sent_at': last.get('sent_at') or '',
        'delivery_pending': q.get('pending', 0),
        'delivery_failed': q.get('failed', 0),
        'failed_attempts': q.get('failed_attempts', 0),
        'counts': q.get('counts') or {},
        'business_key': bkey,
    }


# ── Public send API ────────────────────────────────────────────────────────────

def _deliver_range(api, cfg: dict, start: str, end: str,
                   on_progress=None) -> tuple[bool, str, str]:
    """
    Build + send Excel for [start, end].
    Returns (ok, message, file_path).
    """
    from backend.telegram_hub import resolve_bot_token, resolve_bot_username
    token = resolve_bot_token(cfg)
    chat_id = (cfg.get('telegram_chat_id') or '').strip()
    shop = cfg.get('shop_name', 'My Shop')
    currency = cfg.get('currency_symbol', 'KES')
    bot_user = resolve_bot_username(cfg)

    if not token:
        return False, 'Bot token not configured. Check Settings → Telegram.', ''
    if not chat_id:
        return (
            False,
            f'Your Telegram Chat ID is not set. Go to Settings → Telegram, '
            f'message @{bot_user}, and click Connect.',
            '',
        )

    if on_progress:
        on_progress('Checking Telegram connection…')
    ok, pre_err = _telegram_preflight(token, chat_id)
    if not ok:
        return False, pre_err, ''

    if on_progress:
        on_progress('Building report…')
    path = _build_report_file(api, start, end, shop, currency)

    if on_progress:
        on_progress('Sending to Telegram…')
    sales = [
        s for s in (api.get_sales(start, end) or [])
        if (s.get('status') or 'completed') != 'voided'
    ]
    caption = _report_caption(shop, start, end, len(sales))
    ok, err = _send_document(token, chat_id, path, caption)
    if ok:
        return True, f'✓ Report sent to Telegram\nSaved: {path}', path
    return False, f'Failed to send: {err}\nFile saved locally: {path}', path


def send_report_now(api, config_getter,
                    on_progress=None, on_done=None,
                    *, force: bool = True) -> None:
    """
    Export + send today's report in a background thread.
    Manual sends use force=True (re-queue even if already SENT).
    """
    def _run():
        from backend.daily_report_queue import (
            TYPE_DAILY, begin_send, business_key_from_cfg, mark_failed,
            mark_sent, reset_for_manual_resend,
        )
        cfg = config_getter() or {}
        today = str(date.today())
        bkey = business_key_from_cfg(cfg)
        row = None
        try:
            logger.info(
                'send_report_now start date=%s force=%s biz=%s',
                today, force, bkey,
            )
            if force:
                row = reset_for_manual_resend(bkey, today, TYPE_DAILY)
            else:
                from backend.daily_report_queue import enqueue, is_sent
                if is_sent(bkey, today, TYPE_DAILY):
                    if on_done:
                        on_done(True, f'Today\'s report already SENT for {today}.')
                    return
                row = enqueue(bkey, today, TYPE_DAILY, reason='manual')
            if row:
                row = begin_send(row['id']) or row

            ok, msg, path = _deliver_range(api, cfg, today, today, on_progress)
            if row:
                if ok:
                    mark_sent(row['id'], path)
                else:
                    mark_failed(row['id'], msg, retry=False)
            if on_done:
                on_done(ok, msg)
        except Exception as e:
            logger.error('send_report_now error: %s', _redact(e), exc_info=True)
            if row:
                try:
                    mark_failed(row['id'], str(e), retry=False)
                except Exception:
                    pass
            if on_done:
                on_done(False, f'Error: {_redact(e)}')

    threading.Thread(target=_run, daemon=True, name='SendReportNow').start()


def send_report_for_range(api, config_getter, start: str, end: str,
                          on_progress=None, on_done=None) -> None:
    """Send report for a custom date range (manual / weekly)."""
    def _run():
        cfg = config_getter() or {}
        try:
            logger.info('send_report_for_range %s→%s', start, end)
            ok, msg, _path = _deliver_range(api, cfg, start, end, on_progress)
            if on_done:
                on_done(ok, msg)
        except Exception as e:
            logger.error('send_report_for_range error: %s', _redact(e), exc_info=True)
            if on_done:
                on_done(False, f'Error: {_redact(e)}')

    threading.Thread(target=_run, daemon=True, name='SendReportRange').start()


# ── Scheduler ─────────────────────────────────────────────────────────────────

RECONNECT_GRACE_SEC = 60
DEFAULT_ONLINE_INTERVAL_HRS = 4
PROCESS_TICK_SEC = 30


def _probe_internet() -> bool:
    import socket
    for host, port in (('8.8.8.8', 53), ('1.1.1.1', 53), ('8.8.4.4', 53)):
        try:
            s = socket.create_connection((host, port), timeout=3)
            s.close()
            return True
        except OSError:
            continue
    return False


class ReportScheduler:
    """
    Queues daily reports (one per business+date) and delivers when online.

    Triggers to enqueue:
      • Startup catch-up (last 7 days not SENT)
      • Internet reconnect (after grace)
      • Periodic tick while online (ensures today is queued)

    Delivery is idempotent: SENT rows are never re-sent by the scheduler.
    """

    def __init__(self, api, config_getter, is_online_getter=None):
        self.api = api
        self.config_getter = config_getter
        self.is_online_getter = is_online_getter
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name='ReportScheduler',
        )
        self._was_online = False
        self._online_since: Optional[datetime] = None
        self._reconnect_pending = False
        self._last_db_backup_at = None
        self._sending = False
        self._send_lock = threading.Lock()
        self._config_warned = False
        self._started_at: Optional[datetime] = None
        self._last_tick_at: Optional[datetime] = None
        self._last_enqueue_reason = ''
        self._catchup_done = False

    def start(self):
        self._started_at = datetime.now()
        self._thread.start()
        warnings = validate_telegram_config(self.config_getter() or {})
        if warnings:
            for w in warnings:
                logger.warning('ReportScheduler config: %s', w)
            self._config_warned = True
        else:
            logger.info('ReportScheduler config OK (token + chat present)')
        logger.info(
            'ReportScheduler started (queue+idempotent daily, reconnect + '
            'catch-up, process every %ss)',
            PROCESS_TICK_SEC,
        )

    def stop(self):
        self._stop.set()

    def is_alive(self) -> bool:
        return self._thread.is_alive() and not self._stop.is_set()

    def status_detail(self) -> str:
        if not self.is_alive():
            return 'stopped'
        parts = ['running']
        if self._sending:
            parts.append('sending')
        if self._reconnect_pending:
            parts.append('reconnect_queued')
        if self._last_tick_at:
            parts.append(f"last_tick={self._last_tick_at.strftime('%H:%M:%S')}")
        return ', '.join(parts)

    def _is_online(self) -> bool:
        if self.is_online_getter:
            try:
                return bool(self.is_online_getter())
            except Exception:
                pass
        return _probe_internet()

    @staticmethod
    def _telegram_ready(cfg: dict) -> bool:
        from backend.telegram_hub import resolve_bot_token
        return bool(
            resolve_bot_token(cfg)
            and (cfg.get('telegram_chat_id') or '').strip()
        )

    def _interval_seconds(self, cfg: dict) -> int:
        """How often to attempt queue processing / ensure today is enqueued."""
        try:
            hrs = float(cfg.get('auto_report_interval_hours', DEFAULT_ONLINE_INTERVAL_HRS))
            hrs = max(0.25, min(hrs, 24.0))
        except (TypeError, ValueError):
            hrs = DEFAULT_ONLINE_INTERVAL_HRS
        return int(hrs * 3600)

    def _loop(self):
        from backend.daily_report_queue import init_db, release_stale_sending
        try:
            init_db()
            release_stale_sending()
        except Exception as e:
            logger.error('ReportScheduler queue init: %s', e)

        # Startup catch-up once online path runs
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:
                logger.error('Scheduler tick error: %s', _redact(e), exc_info=True)
            self._stop.wait(PROCESS_TICK_SEC)

    def _tick(self):
        from backend.daily_report_queue import (
            TYPE_DAILY, TYPE_WEEKLY, business_key_from_cfg, enqueue,
            enqueue_catchup,
        )
        self._last_tick_at = datetime.now()
        cfg = self.config_getter() or {}
        bkey = business_key_from_cfg(cfg)

        if not self._telegram_ready(cfg):
            if not self._config_warned:
                for w in validate_telegram_config(cfg):
                    logger.warning('ReportScheduler: %s', w)
                self._config_warned = True
            self._was_online = self._is_online()
            return

        online = self._is_online()
        now = datetime.now()

        if online and not self._was_online:
            self._online_since = now
            self._reconnect_pending = True
            logger.info(
                'ReportScheduler: internet connected — queue catch-up + daily'
            )

        if not online:
            # Still enqueue locally so catch-up exists when back online
            if cfg.get('auto_report_daily', '0') == '1' and not self._catchup_done:
                enqueue_catchup(bkey, include_today=True, reason='offline_buffer')
                self._catchup_done = True
            self._was_online = False
            self._reconnect_pending = False
            self._online_since = None
            return

        self._was_online = True

        # Enqueue catch-up + today
        if cfg.get('auto_report_daily', '0') == '1':
            if not self._catchup_done or self._reconnect_pending:
                enqueue_catchup(
                    bkey, include_today=True,
                    reason='startup_catchup' if not self._catchup_done else 'reconnect',
                )
                self._catchup_done = True
                self._last_enqueue_reason = 'catchup'
            else:
                enqueue(bkey, str(date.today()), TYPE_DAILY, reason='daily_ensure')

        if self._reconnect_pending and self._online_since:
            if (now - self._online_since).total_seconds() >= RECONNECT_GRACE_SEC:
                self._reconnect_pending = False
                logger.info('ReportScheduler: reconnect grace elapsed — processing queue')
                self._process_queue(cfg, bkey)
                self._maybe_enqueue_weekly(cfg, bkey, now)
                self._maybe_send_db_backup(cfg, 'internet_reconnect')
                return

        # Process pending while online (idempotent — SENT skipped)
        self._process_queue(cfg, bkey)
        self._maybe_enqueue_weekly(cfg, bkey, now)
        self._maybe_send_db_backup(cfg, 'online_interval')

    def _maybe_enqueue_weekly(self, cfg: dict, bkey: str, now: datetime):
        from backend.daily_report_queue import (
            TYPE_WEEKLY, enqueue, is_sent,
        )
        if cfg.get('auto_report_weekly', '0') != '1':
            return
        weekday = int(cfg.get('auto_report_weekday', '0'))
        if now.weekday() != weekday:
            return
        # Use ISO week Monday date as the idempotency key date
        week_key_date = str(now.date() - timedelta(days=now.weekday()))
        if is_sent(bkey, week_key_date, TYPE_WEEKLY):
            return
        enqueue(bkey, week_key_date, TYPE_WEEKLY, reason='weekly')

    def _process_queue(self, cfg: dict, bkey: str):
        """Claim and send at most one queued report per tick."""
        from backend.daily_report_queue import (
            TYPE_DAILY, TYPE_WEEKLY, claim_next, mark_failed, mark_sent,
        )
        if cfg.get('auto_report_daily', '0') != '1' and cfg.get('auto_report_weekly', '0') != '1':
            return

        with self._send_lock:
            if self._sending:
                return
            self._sending = True

        row = None
        try:
            # Prefer daily catch-up; weekly processed if no daily pending
            if cfg.get('auto_report_daily', '0') == '1':
                row = claim_next(bkey, TYPE_DAILY)
            if row is None and cfg.get('auto_report_weekly', '0') == '1':
                row = claim_next(bkey, TYPE_WEEKLY)
            if row is None:
                return

            rtype = row['report_type']
            rdate = row['report_date']
            if rtype == TYPE_WEEKLY:
                start = rdate
                end = str(
                    datetime.strptime(rdate, '%Y-%m-%d').date() + timedelta(days=6)
                )
            else:
                start = end = rdate

            logger.info(
                'ReportScheduler: sending %s %s→%s (id=%s attempt=%s reason=%s)',
                rtype, start, end, row['id'], row.get('attempts'),
                row.get('reason') or '',
            )
            ok, msg, path = _deliver_range(self.api, cfg, start, end)
            if ok:
                mark_sent(row['id'], path)
                logger.info(
                    'Auto %s report SENT date=%s: %s',
                    rtype, rdate, str(msg)[:80],
                )
            else:
                mark_failed(row['id'], msg, retry=True)
                logger.warning(
                    'Auto %s report failed date=%s: %s',
                    rtype, rdate, _redact(msg)[:120],
                )
        except Exception as e:
            logger.error('Queue process error: %s', _redact(e), exc_info=True)
            if row:
                try:
                    mark_failed(row['id'], str(e), retry=True)
                except Exception:
                    pass
        finally:
            with self._send_lock:
                self._sending = False

    def _maybe_send_db_backup(self, cfg: dict, reason: str):
        from backend.db_backup import (
            parse_last_backup_at, send_db_backup_now, should_send_scheduled_backup,
        )
        if not should_send_scheduled_backup(cfg, self._last_db_backup_at):
            return
        if self._last_db_backup_at is None:
            self._last_db_backup_at = parse_last_backup_at(cfg)
        if not should_send_scheduled_backup(cfg, self._last_db_backup_at):
            return
        with self._send_lock:
            if self._sending:
                return
            self._sending = True

        logger.info('ReportScheduler: sending database backup (%s)', reason)

        def on_done(ok, msg):
            with self._send_lock:
                self._sending = False
            if ok:
                self._last_db_backup_at = datetime.now()
            logger.info(
                'Auto DB backup (%s): ok=%s %s',
                reason, ok, _redact(msg)[:80],
            )

        send_db_backup_now(
            self.config_getter, api=self.api, on_done=on_done, reason=reason,
        )
