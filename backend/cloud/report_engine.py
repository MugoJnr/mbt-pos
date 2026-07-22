"""
MBT Cloud — Report Engine.
Automatically generates daily, weekly, and monthly reports.
Replaces Telegram report delivery with cloud-stored reports + dashboard notifications.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from datetime import date, datetime, timedelta
from typing import Any, Callable

logger = logging.getLogger('cloud.reports')

REPORT_TYPES = ('daily', 'weekly', 'monthly', 'custom')


def _period_key(report_type: str) -> str:
    """Stable per-period identifier shared by delivery tracking and scheduling."""
    today = date.today()
    if report_type == 'weekly':
        iso = today.isocalendar()
        return f'{iso[0]}-W{iso[1]:02d}'
    if report_type == 'monthly':
        return today.strftime('%Y-%m')
    return today.isoformat()


class ReportEngine:
    """Generates and schedules business reports."""

    def __init__(self, db_path: str, api_getter: Callable | None = None, config_getter: Callable[[], dict] | None = None):
        self.db_path = db_path
        self.api_getter = api_getter
        self.config_getter = config_getter or (lambda: {})
        self._scheduler: ReportScheduler | None = None

    def generate_report(self, report_type: str, start: str | None = None, end: str | None = None) -> dict:
        """Generate a report for the given period. Returns report data dict."""
        today = date.today()
        if report_type == 'daily':
            start = start or today.isoformat()
            end = end or today.isoformat()
        elif report_type == 'weekly':
            week_start = today - timedelta(days=today.weekday())
            start = start or week_start.isoformat()
            end = end or today.isoformat()
        elif report_type == 'monthly':
            month_start = today.replace(day=1)
            start = start or month_start.isoformat()
            end = end or today.isoformat()
        else:
            start = start or today.isoformat()
            end = end or today.isoformat()

        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        try:
            sales = db.execute("""
                SELECT COUNT(*) as txns,
                       COALESCE(SUM(total), 0) as revenue,
                       COALESCE(SUM(discount), 0) as discounts,
                       COALESCE(SUM(tax), 0) as tax,
                       COALESCE(SUM(subtotal), 0) as subtotal,
                       COALESCE(AVG(total), 0) as avg_ticket,
                       COALESCE(MIN(total), 0) as min_ticket,
                       COALESCE(MAX(total), 0) as max_ticket
                FROM sales
                WHERE date(created_at) BETWEEN ? AND ?
                  AND COALESCE(status, 'completed') NOT IN ('void', 'voided')
            """, (start, end)).fetchone()

            voids = db.execute("""
                SELECT COUNT(*) as txns, COALESCE(SUM(total), 0) as revenue
                FROM sales
                WHERE date(created_at) BETWEEN ? AND ?
                  AND COALESCE(status, 'completed') IN ('void', 'voided')
            """, (start, end)).fetchone()

            items = db.execute("""
                SELECT COALESCE(SUM(si.quantity), 0) as units,
                       COUNT(*) as lines
                FROM sale_items si
                JOIN sales s ON s.id = si.sale_id
                WHERE date(s.created_at) BETWEEN ? AND ?
                  AND COALESCE(s.status, 'completed') NOT IN ('void', 'voided')
            """, (start, end)).fetchone()

            # Gross profit estimate from product cost when available
            profit_row = db.execute("""
                SELECT
                    COALESCE(SUM(COALESCE(si.total, si.quantity * si.unit_price)), 0) as sold_rev,
                    COALESCE(SUM(si.quantity * COALESCE(p.cost_price, 0)), 0) as sold_cost
                FROM sale_items si
                LEFT JOIN products p ON p.id = si.product_id
                JOIN sales s ON s.id = si.sale_id
                WHERE date(s.created_at) BETWEEN ? AND ?
                  AND COALESCE(s.status, 'completed') NOT IN ('void', 'voided')
            """, (start, end)).fetchone()
            sold_rev = float(profit_row['sold_rev'] or 0) if profit_row else 0.0
            sold_cost = float(profit_row['sold_cost'] or 0) if profit_row else 0.0
            gross_profit = sold_rev - sold_cost

            top_products = db.execute("""
                SELECT COALESCE(si.product_name, p.name) as name,
                       COALESCE(p.category, '') as category,
                       SUM(si.quantity) as qty,
                       SUM(COALESCE(si.total, si.quantity * si.unit_price)) as revenue,
                       SUM(si.quantity * COALESCE(p.cost_price, 0)) as cost,
                       SUM(COALESCE(si.total, si.quantity * si.unit_price))
                         - SUM(si.quantity * COALESCE(p.cost_price, 0)) as profit
                FROM sale_items si
                LEFT JOIN products p ON p.id = si.product_id
                JOIN sales s ON s.id = si.sale_id
                WHERE date(s.created_at) BETWEEN ? AND ?
                  AND COALESCE(s.status, 'completed') NOT IN ('void', 'voided')
                GROUP BY COALESCE(si.product_name, p.name), COALESCE(p.category, '')
                ORDER BY revenue DESC LIMIT 25
            """, (start, end)).fetchall()

            by_category = db.execute("""
                SELECT COALESCE(NULLIF(TRIM(p.category), ''), 'Uncategorized') as category,
                       SUM(si.quantity) as qty,
                       SUM(COALESCE(si.total, si.quantity * si.unit_price)) as revenue
                FROM sale_items si
                LEFT JOIN products p ON p.id = si.product_id
                JOIN sales s ON s.id = si.sale_id
                WHERE date(s.created_at) BETWEEN ? AND ?
                  AND COALESCE(s.status, 'completed') NOT IN ('void', 'voided')
                GROUP BY 1
                ORDER BY revenue DESC LIMIT 20
            """, (start, end)).fetchall()

            payment_methods = db.execute("""
                SELECT COALESCE(NULLIF(TRIM(payment_method), ''), 'Unknown') as payment_method,
                       COUNT(*) as count,
                       SUM(total) as total
                FROM sales
                WHERE date(created_at) BETWEEN ? AND ?
                  AND COALESCE(status, 'completed') NOT IN ('void', 'voided')
                GROUP BY 1
                ORDER BY total DESC
            """, (start, end)).fetchall()

            low_stock = db.execute("""
                SELECT name, stock, min_stock, COALESCE(category, '') as category
                FROM products
                WHERE stock <= COALESCE(min_stock, 0) AND is_active=1
                ORDER BY stock LIMIT 20
            """).fetchall()

            staff = db.execute("""
                SELECT COALESCE(NULLIF(TRIM(cashier_name), ''), 'Unknown') as cashier_name,
                       COUNT(*) as txns,
                       SUM(total) as revenue,
                       AVG(total) as avg_ticket
                FROM sales
                WHERE date(created_at) BETWEEN ? AND ?
                  AND COALESCE(status, 'completed') NOT IN ('void', 'voided')
                GROUP BY 1 ORDER BY revenue DESC
            """, (start, end)).fetchall()

            by_hour = db.execute("""
                SELECT strftime('%H', created_at) as hour,
                       COUNT(*) as txns,
                       SUM(total) as revenue
                FROM sales
                WHERE date(created_at) BETWEEN ? AND ?
                  AND COALESCE(status, 'completed') NOT IN ('void', 'voided')
                GROUP BY 1 ORDER BY 1
            """, (start, end)).fetchall()

            by_day = db.execute("""
                SELECT date(created_at) as day,
                       COUNT(*) as txns,
                       SUM(total) as revenue,
                       SUM(discount) as discounts
                FROM sales
                WHERE date(created_at) BETWEEN ? AND ?
                  AND COALESCE(status, 'completed') NOT IN ('void', 'voided')
                GROUP BY 1 ORDER BY 1
            """, (start, end)).fetchall()

            cfg = self.config_getter() or {}
            currency = cfg.get('currency_symbol', 'KES')
            shop = cfg.get('shop_name', '')
            txns = int(sales['txns'] or 0) if sales else 0
            revenue = float(sales['revenue'] or 0) if sales else 0.0
            discounts = float(sales['discounts'] or 0) if sales else 0.0
            tax = float(sales['tax'] or 0) if sales else 0.0
            avg_ticket = float(sales['avg_ticket'] or 0) if sales else 0.0
            void_txns = int(voids['txns'] or 0) if voids else 0
            void_rev = float(voids['revenue'] or 0) if voids else 0.0
            units = float(items['units'] or 0) if items else 0.0

            report = {
                'type': report_type,
                'period_start': start,
                'period_end': end,
                'generated_at': datetime.now().isoformat(),
                'currency': currency,
                'shop_name': shop,
                'summary': {
                    'transactions': txns,
                    'revenue': revenue,
                    'discounts': discounts,
                    'tax': tax,
                    'subtotal': float(sales['subtotal'] or 0) if sales else 0.0,
                    'avg_ticket': round(avg_ticket, 2),
                    'min_ticket': float(sales['min_ticket'] or 0) if sales else 0.0,
                    'max_ticket': float(sales['max_ticket'] or 0) if sales else 0.0,
                    'items_sold': units,
                    'line_items': int(items['lines'] or 0) if items else 0,
                    'void_transactions': void_txns,
                    'void_revenue': void_rev,
                    'cost_of_goods': round(sold_cost, 2),
                    'gross_profit': round(gross_profit, 2),
                    'gross_margin_pct': round((gross_profit / sold_rev * 100.0), 2) if sold_rev else 0.0,
                },
                'top_products': [dict(r) for r in top_products],
                'by_category': [dict(r) for r in by_category],
                'payment_methods': [dict(r) for r in payment_methods],
                'low_stock': [dict(r) for r in low_stock],
                'staff_performance': [dict(r) for r in staff],
                'by_hour': [dict(r) for r in by_hour],
                'by_day': [dict(r) for r in by_day],
                'ai_summary': None,
            }
            return report
        finally:
            db.close()

    def send_report_now(self, report_type: str = 'daily') -> tuple[bool, str]:
        """Generate report, publish as notification, and store it in the cloud.

        The cloud copy is what makes reports visible on the Portal even when the
        shop PC is later powered off or offline.
        """
        try:
            report = self.generate_report(report_type)
            cfg = self.config_getter() or {}
            shop = cfg.get('shop_name', 'My Shop')
            rev = report['summary']['revenue']
            txns = report['summary']['transactions']
            currency = report['currency']

            title = f'{report_type.title()} Report — {shop}'
            body = (
                f'Period: {report["period_start"]} to {report["period_end"]}\n'
                f'Transactions: {txns}\n'
                f'Revenue: {currency} {rev:,.2f}'
            )

            from backend.cloud.notification_engine import get_notification_engine
            engine = get_notification_engine(self.db_path, self.config_getter)
            event = f'{report_type}_report'
            engine.publish(event, title, body, meta=report)

            pkey = _period_key(report_type)
            self._record_delivery(report_type, pkey, 'sent')

            cloud_ok, cloud_msg = self._push_cloud(report)
            self._set_cloud_synced(report_type, pkey, cloud_ok)
            tail = (
                ' Cloud copy saved for Portal access.'
                if cloud_ok else
                f' Cloud upload pending ({cloud_msg}); will retry automatically.'
            )
            return True, f'{report_type.title()} report generated.{tail}'
        except Exception as e:
            logger.error('send_report_now failed: %s', e, exc_info=True)
            self._record_delivery(report_type, _period_key(report_type), 'failed', str(e))
            return False, str(e)

    # ── Cloud upload (Portal report history) ────────────────────────────────────

    def _push_cloud(self, report: dict) -> tuple[bool, str]:
        """Upload a generated report to the Portal so it persists in the cloud.

        Requires an active cloud session (access token) and a linked org. Best
        effort: any failure is reported so the caller can retry later.
        """
        try:
            from backend.cloud_backup.paths import is_cloud_configured, load_identity
            if not is_cloud_configured():
                return False, 'cloud not configured'
            ident = load_identity()
            token = str(ident.get('access_token') or '').strip()
            org_id = str(ident.get('org_id') or '').strip()
            if not org_id:
                return False, 'no organization linked'
            if not token:
                return False, 'not signed in'

            cfg = self.config_getter() or {}
            body = dict(report)
            body['shop_name'] = cfg.get('shop_name', '')

            import requests
            portal = os.environ.get(
                'MBT_PORTAL_URL', 'https://portal.mugobyte.com'
            ).rstrip('/')
            url = f'{portal}/api/cloud/reports'
            payload = {'org_id': org_id, 'report': body}

            def _post(tok: str):
                return requests.post(
                    url,
                    headers={
                        'Authorization': f'Bearer {tok}',
                        'Content-Type': 'application/json',
                    },
                    json=payload,
                    timeout=30,
                )

            resp = _post(token)
            if resp.status_code in (401, 403):
                # Expired access token — refresh once and retry.
                try:
                    from backend.cloud_backup.supabase_client import get_client
                    data = get_client().refresh_session()
                    new_tok = (data.get('access_token') or '').strip()
                    if new_tok:
                        resp = _post(new_tok)
                except Exception as re:
                    return False, f'auth refresh failed: {re}'
            if resp.status_code >= 400:
                return False, f'HTTP {resp.status_code}: {resp.text[:150]}'
            return True, 'ok'
        except Exception as e:
            return False, str(e)

    @staticmethod
    def _ensure_cloud_column(db: sqlite3.Connection) -> None:
        """Idempotently add the cloud_synced tracking column to report_deliveries."""
        try:
            cols = {r[1] for r in db.execute('PRAGMA table_info(report_deliveries)').fetchall()}
            if 'cloud_synced' not in cols:
                db.execute('ALTER TABLE report_deliveries ADD COLUMN cloud_synced INTEGER NOT NULL DEFAULT 0')
                db.commit()
        except Exception:
            pass

    def _record_delivery(self, report_type: str, period_key: str, status: str, error: str = ''):
        db = sqlite3.connect(self.db_path)
        try:
            db.execute("""
                INSERT INTO report_deliveries (report_type, period_key, status, last_error, sent_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(report_type, period_key) DO UPDATE SET
                    status=excluded.status, last_error=excluded.last_error,
                    sent_at=excluded.sent_at, attempts=attempts+1
            """, (report_type, period_key, status, error, datetime.now().isoformat() if status == 'sent' else None))
            db.commit()
        except Exception:
            pass
        finally:
            db.close()

    def _set_cloud_synced(self, report_type: str, period_key: str, synced: bool) -> None:
        db = sqlite3.connect(self.db_path)
        try:
            self._ensure_cloud_column(db)
            db.execute(
                "UPDATE report_deliveries SET cloud_synced=? WHERE report_type=? AND period_key=?",
                (1 if synced else 0, report_type, period_key),
            )
            db.commit()
        except Exception:
            pass
        finally:
            db.close()

    def is_cloud_synced(self, report_type: str, period_key: str) -> bool:
        db = sqlite3.connect(self.db_path)
        try:
            self._ensure_cloud_column(db)
            row = db.execute(
                "SELECT cloud_synced FROM report_deliveries WHERE report_type=? AND period_key=?",
                (report_type, period_key),
            ).fetchone()
            return bool(row and row[0])
        except Exception:
            return False
        finally:
            db.close()

    def retry_cloud(self, report_type: str) -> tuple[bool, str]:
        """Regenerate the current period's report and re-attempt the cloud upload."""
        try:
            report = self.generate_report(report_type)
            ok, msg = self._push_cloud(report)
            self._set_cloud_synced(report_type, _period_key(report_type), ok)
            return ok, msg
        except Exception as e:
            return False, str(e)


class ReportScheduler(threading.Thread):
    """Background scheduler for automatic daily/weekly reports. Replaces telegram_reporter."""

    def __init__(self, db_path: str, config_getter: Callable[[], dict], is_online_getter: Callable[[], bool] | None = None):
        super().__init__(daemon=True, name='ReportScheduler')
        self.db_path = db_path
        self.config_getter = config_getter
        self.is_online_getter = is_online_getter or (lambda: True)
        self._stop = threading.Event()
        self._engine = ReportEngine(db_path, config_getter=config_getter)

    def stop(self):
        self._stop.set()

    def run(self):
        logger.info('Report scheduler started (cloud notification engine)')
        while not self._stop.is_set():
            try:
                cfg = self.config_getter() or {}
                interval_hrs = float(cfg.get('auto_report_interval_hours', 4))
                interval_hrs = max(1.0, min(interval_hrs, 24.0))

                if cfg.get('auto_report_daily', '1') == '1':
                    self._maybe_send('daily')
                if cfg.get('auto_report_weekly', '1') == '1':
                    self._maybe_send('weekly')
                if cfg.get('auto_report_monthly', '1') == '1':
                    self._maybe_send('monthly')

            except Exception as e:
                logger.error('Report scheduler error: %s', e)

            self._stop.wait(interval_hrs * 3600)

    def _maybe_send(self, report_type: str):
        period_key = _period_key(report_type)

        already_sent = False
        db = sqlite3.connect(self.db_path)
        try:
            row = db.execute(
                "SELECT status FROM report_deliveries WHERE report_type=? AND period_key=?",
                (report_type, period_key),
            ).fetchone()
            already_sent = bool(row and row[0] == 'sent')
        except Exception:
            pass
        finally:
            db.close()

        if already_sent:
            # Report exists locally; only ensure the cloud copy made it up so the
            # Portal keeps showing it while this PC is off/offline.
            if not self._engine.is_cloud_synced(report_type, period_key):
                ok, msg = self._engine.retry_cloud(report_type)
                logger.info('Cloud retry %s report: %s — %s', report_type, 'OK' if ok else 'PENDING', msg)
            return

        ok, msg = self._engine.send_report_now(report_type)
        logger.info('Auto %s report: %s — %s', report_type, 'OK' if ok else 'FAIL', msg)


_scheduler: ReportScheduler | None = None


def start_report_scheduler(db_path: str, config_getter, is_online_getter=None) -> ReportScheduler:
    global _scheduler
    if _scheduler is None or not _scheduler.is_alive():
        _scheduler = ReportScheduler(db_path, config_getter, is_online_getter)
        _scheduler.start()
    return _scheduler


def stop_report_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.stop()
        _scheduler = None


def validate_report_config(cfg: dict) -> list[str]:
    """Validate report configuration. Returns list of warnings."""
    warnings = []
    if cfg.get('auto_report_daily') == '1' or cfg.get('auto_report_weekly') == '1':
        pass  # cloud notification engine always available
    return warnings


def get_report_health(cfg: dict | None = None) -> dict:
    return {
        'engine': 'cloud_notification',
        'connected': True,
        'auto_daily': (cfg or {}).get('auto_report_daily', '1') == '1',
        'auto_weekly': (cfg or {}).get('auto_report_weekly', '1') == '1',
    }
