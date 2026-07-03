"""
MBT POS – Telegram Reporter
MugoByte Technologies | mugobyte.com

Handles:
  • Manual (on-demand) report delivery with success/failure feedback
  • Scheduled automatic daily/weekly reports
  • Retry logic with exponential back-off (3 attempts)
  • Structured error logging
"""
import os, sys, time, json, logging, threading
from datetime import datetime, date, timedelta

logger = logging.getLogger('telegram_reporter')

from mbt_paths import get_project_root

_PROJECT_ROOT = get_project_root()


def _telegram_preflight(token: str, chat_id: str) -> tuple[bool, str]:
    """
    Validate bot token and chat access up front.
    Returns (ok, error_msg).
    """
    import requests
    api = f'https://api.telegram.org/bot{token}'
    try:
        r = requests.get(f'{api}/getMe', timeout=10)
        if not r.ok:
            return False, "Invalid Telegram bot token."
    except Exception:
        return False, "No internet or Telegram server unreachable."

    try:
        r = requests.get(f'{api}/getChat', params={'chat_id': chat_id}, timeout=10)
        if not r.ok:
            try:
                msg = r.json().get('description', '')
            except Exception:
                msg = ''
            if 'chat not found' in msg.lower() or 'forbidden' in msg.lower():
                return False, "Chat ID is not linked to this bot. Open @mbt_admin1_bot and send any message, then reconnect."
            return False, f"Telegram chat check failed: {msg or f'HTTP {r.status_code}'}"
    except Exception:
        return False, "Internet is unstable while checking Telegram chat."

    return True, ''


# ── Low-level send helpers ─────────────────────────────────────────────────────

def _send_message(token: str, chat_id: str, text: str,
                  parse_mode='HTML', retries=3) -> tuple[bool, str]:
    """Send a text message. Returns (ok, error_msg)."""
    import requests
    last_err = ''
    for attempt in range(1, retries+1):
        try:
            r = requests.post(
                f'https://api.telegram.org/bot{token}/sendMessage',
                json={'chat_id': chat_id, 'text': text, 'parse_mode': parse_mode},
                timeout=12,
            )
            if r.ok:
                logger.info(f"Telegram message sent ok (attempt {attempt})")
                return True, ''
            try:
                err = r.json().get('description', r.text[:120])
            except Exception:
                err = r.text[:120] or f'HTTP {r.status_code}'
            last_err = err
            logger.warning(f"Telegram sendMessage attempt {attempt} failed: {err}")
            if attempt < retries:
                time.sleep(2 ** attempt)
        except Exception as e:
            last_err = str(e)
            logger.warning(f"Telegram sendMessage attempt {attempt} exception: {e}")
            if attempt < retries:
                time.sleep(2 ** attempt)
    return False, (last_err or f"Failed after {retries} attempts")


def _send_document(token: str, chat_id: str, file_path: str,
                   caption='', retries=3) -> tuple[bool, str]:
    """Send a file. Returns (ok, error_msg)."""
    import requests
    if not os.path.exists(file_path):
        return False, f"File not found: {file_path}"
    last_err = ''
    for attempt in range(1, retries+1):
        try:
            with open(file_path, 'rb') as f:
                r = requests.post(
                    f'https://api.telegram.org/bot{token}/sendDocument',
                    data={'chat_id': chat_id, 'caption': caption, 'parse_mode': 'HTML'},
                    files={'document': (os.path.basename(file_path), f)},
                    timeout=60,
                )
            if r.ok:
                logger.info(f"Telegram document sent ok: {os.path.basename(file_path)}")
                return True, ''
            try:
                err = r.json().get('description', r.text[:120])
            except Exception:
                err = r.text[:120] or f'HTTP {r.status_code}'
            last_err = err
            logger.warning(f"Telegram sendDocument attempt {attempt} failed: {err}")
            if attempt < retries:
                time.sleep(2 ** attempt)
        except Exception as e:
            last_err = str(e)
            logger.warning(f"Telegram sendDocument attempt {attempt} exception: {e}")
            if attempt < retries:
                time.sleep(2 ** attempt)
    return False, (last_err or f"Failed after {retries} attempts")


# ── Report builder ─────────────────────────────────────────────────────────────

def _build_report_file(api, start: str, end: str,
                        shop_name: str, currency: str) -> str:
    """Export Excel report, return path."""
    sys.path.insert(0, _PROJECT_ROOT)
    from backend.export_engine import export_sales_report
    from desktop.utils.api_client import _get_export_dir

    sales = [s for s in (api.get_sales(start, end) or [])
             if (s.get('status') or 'completed') != 'voided']
    items_by_sale = {}
    for sale in sales:
        sid = sale.get('id') or sale.get('sale_id')
        d   = api.get_sale(sid)
        if d:
            items_by_sale[sid] = d.get('items', [])
            sale['item_count'] = len(items_by_sale[sid])

    # Current inventory for Stock sheet
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
    out   = os.path.join(export_dir, fname)
    # Debt sheet payload (best effort, do not block report send if debt query fails)
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

    path  = export_sales_report(
        sales, items_by_sale,
        shop_name=shop_name, start_date=start, end_date=end,
        output_path=out, currency=currency,
        products_data=products,
        debt_summary=debt_summary,
        aging_report=aging_report,
        debt_invoices=debt_invoices,
        debt_payments=debt_payments,
    )
    return path


def _report_caption(shop_name: str, start: str, end: str, n_sales: int) -> str:
    return (
        f"📊 <b>Sales Report — {shop_name}</b>\n"
        f"Period: {start} → {end}\n"
        f"Transactions: <b>{n_sales}</b>\n"
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"<i>MugoByte Technologies  ·  mugobyte.com</i>"
    )


# ── Public API ─────────────────────────────────────────────────────────────────

def send_report_now(api, config_getter,
                    on_progress=None, on_done=None) -> None:
    """
    Export + send report immediately in a background thread.
    on_progress(msg: str) — called with status text (main-thread safe via QTimer)
    on_done(ok: bool, message: str) — called when finished
    """
    def _run():
        from backend.telegram_hub import resolve_bot_token, resolve_bot_username
        cfg       = config_getter() or {}
        token     = resolve_bot_token(cfg)
        chat_id   = cfg.get('telegram_chat_id', '').strip()
        shop      = cfg.get('shop_name', 'My Shop')
        currency  = cfg.get('currency_symbol', 'KES')
        today     = str(date.today())
        bot_user  = resolve_bot_username(cfg)

        if not token:
            if on_done: on_done(False, "Bot token not configured. Check Settings → Telegram.")
            return
        if not chat_id:
            if on_done: on_done(False, f"Your Telegram Chat ID is not set. Go to Settings → Telegram, message @{bot_user}, and click Connect.")
            return

        try:
            if on_progress: on_progress("Checking Telegram connection…")
            ok, pre_err = _telegram_preflight(token, chat_id)
            if not ok:
                if on_done: on_done(False, pre_err)
                return

            if on_progress: on_progress("Building report…")
            path = _build_report_file(api, today, today, shop, currency)

            if on_progress: on_progress("Sending to Telegram…")
            sales = [s for s in (api.get_sales(today, today) or [])
                     if (s.get('status') or 'completed') != 'voided']
            caption = _report_caption(shop, today, today, len(sales))
            ok, err = _send_document(token, chat_id, path, caption)

            if ok:
                logger.info(f"Manual report sent ok: {path}")
                if on_done: on_done(True, f"✓ Report sent to Telegram\nSaved: {path}")
            else:
                logger.error(f"Manual report send failed: {err}")
                if on_done: on_done(False, f"Failed to send: {err}\nFile saved locally: {path}")
        except Exception as e:
            logger.error(f"send_report_now error: {e}", exc_info=True)
            if on_done: on_done(False, f"Error: {e}")

    threading.Thread(target=_run, daemon=True).start()


def send_report_for_range(api, config_getter, start: str, end: str,
                           on_progress=None, on_done=None) -> None:
    """Send report for a custom date range."""
    def _run():
        from backend.telegram_hub import resolve_bot_token
        cfg      = config_getter() or {}
        token    = resolve_bot_token(cfg)
        chat_id  = cfg.get('telegram_chat_id', '').strip()
        shop     = cfg.get('shop_name', 'My Shop')
        currency = cfg.get('currency_symbol', 'KES')

        if not token or not chat_id:
            if on_done: on_done(False, "Telegram not configured. Check Settings.")
            return
        try:
            if on_progress: on_progress("Checking Telegram connection…")
            ok, pre_err = _telegram_preflight(token, chat_id)
            if not ok:
                if on_done: on_done(False, pre_err)
                return

            if on_progress: on_progress("Building report…")
            path = _build_report_file(api, start, end, shop, currency)

            if on_progress: on_progress("Sending to Telegram…")
            sales = [s for s in (api.get_sales(start, end) or [])
                     if (s.get('status') or 'completed') != 'voided']
            caption = _report_caption(shop, start, end, len(sales))
            ok, err = _send_document(token, chat_id, path, caption)

            if ok:
                if on_done: on_done(True, f"✓ Report sent\nSaved: {path}")
            else:
                if on_done: on_done(False, f"Send failed: {err}\nFile saved: {path}")
        except Exception as e:
            logger.error(f"send_report_for_range error: {e}", exc_info=True)
            if on_done: on_done(False, f"Error: {e}")

    threading.Thread(target=_run, daemon=True).start()


# ── Scheduler ─────────────────────────────────────────────────────────────────

RECONNECT_GRACE_SEC = 60          # wait after internet returns before sending
DEFAULT_ONLINE_INTERVAL_HRS = 4   # while continuously online


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
    Sends daily/weekly Excel reports when:
      • Internet comes back (after ~1 min grace), or
      • The PC stays online for 4 hours since the last auto report.

    Settings: auto_report_daily, auto_report_weekly, auto_report_weekday,
              auto_report_interval_hours (default 4).
    """

    def __init__(self, api, config_getter, is_online_getter=None):
        self.api               = api
        self.config_getter     = config_getter
        self.is_online_getter = is_online_getter
        self._stop             = threading.Event()
        self._thread           = threading.Thread(
            target=self._loop, daemon=True, name='ReportScheduler')
        self._was_online       = False
        self._online_since     = None
        self._reconnect_pending = False
        self._last_sent_at     = None
        self._last_weekly      = None
        self._sending          = False
        self._send_lock        = threading.Lock()

    def start(self):
        self._thread.start()
        logger.info(
            "ReportScheduler started (on reconnect + every %sh while online)",
            DEFAULT_ONLINE_INTERVAL_HRS,
        )

    def stop(self):
        self._stop.set()

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
        try:
            hrs = float(cfg.get('auto_report_interval_hours', DEFAULT_ONLINE_INTERVAL_HRS))
            hrs = max(1.0, min(hrs, 24.0))
        except (TypeError, ValueError):
            hrs = DEFAULT_ONLINE_INTERVAL_HRS
        return int(hrs * 3600)

    def _loop(self):
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:
                logger.error(f"Scheduler tick error: {e}")
            self._stop.wait(30)

    def _tick(self):
        cfg = self.config_getter() or {}
        if not self._telegram_ready(cfg):
            self._was_online = self._is_online()
            return

        online = self._is_online()
        now = datetime.now()

        if online and not self._was_online:
            self._online_since = now
            self._reconnect_pending = True
            logger.info("ReportScheduler: internet connected — daily report queued")

        if not online:
            self._was_online = False
            self._reconnect_pending = False
            self._online_since = None
            return

        self._was_online = True
        interval = self._interval_seconds(cfg)

        if self._reconnect_pending and self._online_since:
            if (now - self._online_since).total_seconds() >= RECONNECT_GRACE_SEC:
                self._reconnect_pending = False
                self._send_daily(cfg, 'internet_reconnect')
                self._maybe_send_weekly(cfg, now)
                return

        if self._last_sent_at is None:
            if self._online_since and (now - self._online_since).total_seconds() >= interval:
                self._send_daily(cfg, 'online_interval')
                self._maybe_send_weekly(cfg, now)
        elif (now - self._last_sent_at).total_seconds() >= interval:
            self._send_daily(cfg, 'online_interval')
            self._maybe_send_weekly(cfg, now)

    def _send_daily(self, cfg: dict, reason: str):
        if cfg.get('auto_report_daily', '0') != '1':
            return
        with self._send_lock:
            if self._sending:
                return
            self._sending = True

        logger.info(f"ReportScheduler: sending daily report ({reason})")

        def on_done(ok, msg):
            with self._send_lock:
                self._sending = False
            if ok:
                self._last_sent_at = datetime.now()
            logger.info(f"Auto daily report ({reason}): ok={ok} {str(msg)[:80]}")

        send_report_now(self.api, self.config_getter, on_done=on_done)

    def _maybe_send_weekly(self, cfg: dict, now: datetime):
        if cfg.get('auto_report_weekly', '0') != '1':
            return
        weekday = int(cfg.get('auto_report_weekday', '0'))
        if now.weekday() != weekday:
            return
        week_key = f"{now.isocalendar()[0]}-W{now.isocalendar()[1]}"
        if self._last_weekly == week_key:
            return
        with self._send_lock:
            if self._sending:
                return
            self._sending = True

        today_str = str(now.date())
        start = str(now.date() - timedelta(days=6))
        self._last_weekly = week_key
        logger.info(f"ReportScheduler: sending weekly report {start}→{today_str}")

        def on_done(ok, msg):
            with self._send_lock:
                self._sending = False
            logger.info(f"Auto weekly report: ok={ok} {str(msg)[:80]}")

        send_report_for_range(
            self.api, self.config_getter, start, today_str, on_done=on_done)
