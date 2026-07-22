"""U01: every SettingsTab `_common_payload` key is accounted for.

Each saved key must have a known runtime reader outside SettingsTab, OR be
explicitly allowlisted as intentionally unused (forced default / deferred
feature) with a comment. Does not claim live UI toggle UAT for every control.
"""
from __future__ import annotations

import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Settings keys expected to be read by runtime code (not only SettingsTab save/load).
WIRED_SETTINGS_MATRIX = {
    'shop_name': [
        'desktop/tabs/sales_tab.py',
        'desktop/tabs/debt_tab.py',
        'printing/printer_engine.py',
    ],
    'shop_address': ['printing/printer_engine.py'],
    'shop_phone': ['printing/printer_engine.py'],
    'currency_symbol': [
        'desktop/tabs/sales_tab.py',
        'desktop/tabs/reports_tab.py',
        'desktop/tabs/debt_tab.py',
    ],
    'tax_rate': ['desktop/tabs/sales_tab.py'],
    'receipt_footer': ['desktop/tabs/sales_tab.py'],
    'auto_print': ['desktop/tabs/sales_tab.py'],
    'printer_port': ['printing/printer_engine.py'],
    'mpesa_till': ['desktop/tabs/sales_tab.py'],
    'mpesa_paybill': ['desktop/tabs/sales_tab.py'],
    'mpesa_business_name': ['desktop/tabs/sales_tab.py'],
    'auto_report_daily': [
        'desktop/tabs/reports_tab.py',
        'backend/cloud/report_engine.py',
    ],
    'auto_report_weekly': [
        'desktop/tabs/reports_tab.py',
        'backend/cloud/report_engine.py',
    ],
    'auto_report_interval_hours': ['backend/cloud/report_engine.py'],
    'auto_db_backup': ['backend/db_backup.py'],
    'auto_db_backup_interval_hours': ['backend/db_backup.py'],
    'variance_enabled': ['desktop/tabs/sales_tab.py'],
    'variance_enable_deposits': ['desktop/dialogs/payment_variance_dialog.py'],
    'variance_enable_tips': ['desktop/dialogs/payment_variance_dialog.py'],
    'variance_enable_transport': ['desktop/dialogs/payment_variance_dialog.py'],
    'variance_require_customer_deposit': [
        'desktop/dialogs/payment_variance_dialog.py',
    ],
    'variance_max_cashier': ['desktop/tabs/sales_tab.py'],
    'cash_rounding_enabled': ['desktop/utils/cash_rounding_service.py'],
    'cash_rounding_apply_cash': ['desktop/utils/cash_rounding_service.py'],
    'cash_rounding_apply_mpesa': ['desktop/utils/cash_rounding_service.py'],
    'cash_rounding_apply_card': ['desktop/utils/cash_rounding_service.py'],
    'cash_rounding_apply_bank': ['desktop/utils/cash_rounding_service.py'],
    'cash_rounding_mode': ['desktop/utils/cash_rounding_service.py'],
    'cash_rounding_value': ['desktop/utils/cash_rounding_service.py'],
    'after_sale_default_customer': ['desktop/utils/state_reset.py'],
    'after_sale_default_payment': ['desktop/utils/state_reset.py'],
    'after_sale_focus_barcode': ['desktop/utils/state_reset.py'],
    'after_sale_auto_clear_cart': ['desktop/utils/state_reset.py'],
    'after_sale_reset_discounts': ['desktop/utils/state_reset.py'],
    'after_sale_reset_notes': ['desktop/utils/state_reset.py'],
    'autofill_cash_paid': ['desktop/tabs/sales_tab.py'],
    'autofill_product_defaults': ['desktop/utils/auto_fill.py'],
    'autofill_reports_today': ['desktop/utils/auto_fill.py'],
    'autofill_clear_search_on_leave': ['desktop/utils/auto_fill.py'],
    'autofill_credit_customer_info': [
        'desktop/utils/auto_fill.py',
        'desktop/tabs/sales_tab.py',
    ],
    # Theme aliases live on MainWindow / api settings (not in _common_payload).
    'theme': ['desktop/main.py'],
    'ui_theme': ['desktop/main.py'],
}

# Keys persisted by `_common_payload` that are intentionally not runtime-driven.
# Values are forced defaults or deferred features — see comments.
INTENTIONALLY_UNUSED = {
    # Hidden sync interval spin; always persist 30 — no scheduler reader yet.
    'sync_interval': 'forced default 30; sync interval UI not wired',
    # STK Push deferred (V05); mode combo hidden and forced to manual.
    'mpesa_mode': 'forced manual; STK/Paybill push not implemented',
    # Post-finalize refund checkbox hidden; always persist 0 (P11 returns).
    'variance_allow_refund_after_finalize': (
        'forced 0; post-finalize refund deferred with P11'
    ),
}

_PAYLOAD_KEY_RE = re.compile(r"['\"]([a-z_][a-z0-9_]*)['\"]\s*:")


def _common_payload_keys() -> list[str]:
    path = os.path.join(ROOT, 'desktop', 'tabs', 'settings_tab.py')
    text = open(path, encoding='utf-8', errors='replace').read()
    m = re.search(
        r'def _common_payload\(self\):(.*?)(?=\n    def )',
        text,
        re.S,
    )
    if not m:
        raise AssertionError('_common_payload not found in settings_tab.py')
    return _PAYLOAD_KEY_RE.findall(m.group(1))


def _key_mentioned(text: str, key: str) -> bool:
    pat = re.compile(
        rf"""(?:cfg|settings|config|_cfg\(\)|get_settings\(\))\s*\.?\s*get\s*\(\s*['\"]{re.escape(key)}['\"]"""
        rf"""|['\"]{re.escape(key)}['\"]\s*:"""
        rf"""|\.get\(\s*['\"]{re.escape(key)}['\"]"""
    )
    return bool(
        pat.search(text)
        or f"'{key}'" in text
        or f'"{key}"' in text
    )


class SettingsKeysWiredMatrix(unittest.TestCase):
    def test_key_settings_read_outside_settings_tab(self):
        missing = []
        for key, rel_paths in WIRED_SETTINGS_MATRIX.items():
            found = False
            for rel in rel_paths:
                path = os.path.join(ROOT, *rel.split('/'))
                self.assertTrue(os.path.isfile(path), f'missing file {rel}')
                text = open(path, encoding='utf-8', errors='replace').read()
                if key in text and _key_mentioned(text, key):
                    found = True
                    break
            if not found:
                missing.append(f'{key} not found in {rel_paths}')
        self.assertEqual(missing, [], '; '.join(missing))

    def test_settings_tab_persists_matrix_keys(self):
        """Keys in matrix (except theme aliases) appear in SettingsTab payload or load."""
        settings_path = os.path.join(ROOT, 'desktop', 'tabs', 'settings_tab.py')
        text = open(settings_path, encoding='utf-8', errors='replace').read()
        skip = {'theme', 'ui_theme'}  # theme lives on MainWindow / api settings
        for key in WIRED_SETTINGS_MATRIX:
            if key in skip:
                continue
            self.assertIn(
                key,
                text,
                f'{key} not present in settings_tab.py (save/load surface)',
            )

    def test_common_payload_keys_fully_accounted(self):
        """U01 gate: every `_common_payload` key has a reader or unused allowlist."""
        payload_keys = _common_payload_keys()
        self.assertGreaterEqual(len(payload_keys), 40, payload_keys)

        wired_payload = {
            k for k in WIRED_SETTINGS_MATRIX if k not in ('theme', 'ui_theme')
        }
        unused = set(INTENTIONALLY_UNUSED)

        overlap = wired_payload & unused
        self.assertEqual(
            overlap,
            set(),
            f'keys listed as both wired and unused: {sorted(overlap)}',
        )

        accounted = wired_payload | unused
        gaps = sorted(set(payload_keys) - accounted)
        extras = sorted(accounted - set(payload_keys))
        self.assertEqual(
            gaps,
            [],
            'unaccounted _common_payload keys (add reader matrix or INTENTIONALLY_UNUSED): '
            + ', '.join(gaps),
        )
        self.assertEqual(
            extras,
            [],
            'matrix/allowlist keys missing from _common_payload: ' + ', '.join(extras),
        )

        # Allowlist reasons must be non-empty documentation.
        for key, reason in INTENTIONALLY_UNUSED.items():
            self.assertTrue(
                isinstance(reason, str) and len(reason.strip()) >= 8,
                f'unused allowlist reason too short for {key}',
            )


if __name__ == '__main__':
    unittest.main()
