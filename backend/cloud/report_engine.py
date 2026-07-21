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
                       COALESCE(SUM(tax), 0) as tax
                FROM sales
                WHERE date(created_at) BETWEEN ? AND ?
                  AND COALESCE(status, 'completed') != 'void'
            """, (start, end)).fetchone()

            top_products = db.execute("""
                SELECT p.name, SUM(si.qty) as qty, SUM(si.qty * si.price) as revenue
                FROM sale_items si
                JOIN products p ON p.id = si.product_id
                JOIN sales s ON s.id = si.sale_id
                WHERE date(s.created_at) BETWEEN ? AND ?
                  AND COALESCE(s.status, 'completed') != 'void'
                GROUP BY p.id
                ORDER BY revenue DESC LIMIT 10
            """, (start, end)).fetchall()

            payment_methods = db.execute("""
                SELECT payment_method, COUNT(*) as count, SUM(total) as total
                FROM sales
                WHERE date(created_at) BETWEEN ? AND ?
                  AND COALESCE(status, 'completed') != 'void'
                GROUP BY payment_method
            """, (start, end)).fetchall()

            low_stock = db.execute("""
                SELECT name, stock, min_stock FROM products
                WHERE stock <= COALESCE(min_stock, 0) AND is_active=1
                ORDER BY stock LIMIT 20
            """).fetchall()

            staff = db.execute("""
                SELECT cashier_name, COUNT(*) as txns, SUM(total) as revenue
                FROM sales
                WHERE date(created_at) BETWEEN ? AND ?
                  AND COALESCE(status, 'completed') != 'void'
                GROUP BY cashier_name ORDER BY revenue DESC
            """, (start, end)).fetchall()

            cfg = self.config_getter() or {}
            currency = cfg.get('currency_symbol', 'KES')

            report = {
                'type': report_type,
                'period_start': start,
                'period_end': end,
                'generated_at': datetime.now().isoformat(),
                'currency': currency,
                'summary': {
                    'transactions': sales['txns'] if sales else 0,
                    'revenue': sales['revenue'] if sales else 0,
                    'discounts': sales['discounts'] if sales else 0,
                    'tax': sales['tax'] if sales else 0,
                },
                'top_products': [dict(r) for r in top_products],
                'payment_methods': [dict(r) for r in payment_methods],
                'low_stock': [dict(r) for r in low_stock],
                'staff_performance': [dict(r) for r in staff],
                'ai_summary': None,  # placeholder for future AI summary
            }
            return report
        finally:
            db.close()

    def send_report_now(self, report_type: str = 'daily') -> tuple[bool, str]:
        """Generate report and publish as notification."""
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

            self._record_delivery(report_type, report['period_start'], 'sent')
            return True, f'{report_type.title()} report generated and delivered to notification center.'
        except Exception as e:
            logger.error('send_report_now failed: %s', e, exc_info=True)
            self._record_delivery(report_type, date.today().isoformat(), 'failed', str(e))
            return False, str(e)

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

            except Exception as e:
                logger.error('Report scheduler error: %s', e)

            self._stop.wait(interval_hrs * 3600)

    def _maybe_send(self, report_type: str):
        today = date.today()
        period_key = today.isoformat() if report_type == 'daily' else f'{today.isocalendar()[0]}-W{today.isocalendar()[1]:02d}'

        db = sqlite3.connect(self.db_path)
        try:
            row = db.execute(
                "SELECT status FROM report_deliveries WHERE report_type=? AND period_key=?",
                (report_type, period_key),
            ).fetchone()
            if row and row[0] == 'sent':
                return
        except Exception:
            pass
        finally:
            db.close()

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
