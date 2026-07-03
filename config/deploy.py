"""
Per-deployment defaults for MBT POS (multi-shop).
Set MBT_BOT_TOKEN env var or config/deploy.local.json before building the installer.
"""
import json
import os

_DIR = os.path.dirname(os.path.abspath(__file__))
_LOCAL = os.path.join(_DIR, 'deploy.local.json')

# Shop-facing Telegram bot (@mbt_admin1_bot) — override per build via deploy.local.json
_DEFAULT_BOT = '8342651179:AAE_JPNBUxWz9dkz49Ldr9sySwsabpx1IwQ'
_DEFAULT_DEVELOPER_CHAT = '8293620725'


def load_deploy_config() -> dict:
    cfg = {
        'telegram_bot_token': os.environ.get('MBT_BOT_TOKEN', '').strip() or _DEFAULT_BOT,
        'telegram_bot_username': 'mbt_admin1_bot',
        'developer_chat_id': os.environ.get('MBT_DEVELOPER_CHAT_ID', '').strip()
            or _DEFAULT_DEVELOPER_CHAT,
        'cloudflare_api_token': os.environ.get('CLOUDFLARE_API_TOKEN', '').strip(),
    }
    if os.path.isfile(_LOCAL):
        try:
            with open(_LOCAL, encoding='utf-8') as f:
                cfg.update(json.load(f))
        except Exception:
            pass
    return cfg


def shop_settings_defaults() -> dict:
    """Inserted into system_settings for new installs (INSERT OR IGNORE)."""
    d = load_deploy_config()
    token = (d.get('telegram_bot_token') or '').strip()
    dev_id = (d.get('developer_chat_id') or '').strip()
    return {
        'shop_name': 'My Shop',
        'shop_address': '',
        'shop_phone': '',
        'shop_email': '',
        'telegram_bot_token': token,
        'telegram_chat_id': '',
        'developer_chat_id': dev_id,
        'currency_symbol': 'KES',
        'tax_rate': '0',
        'receipt_footer': 'Thank you for shopping with us!',
        'theme': 'dark',
        'sync_interval': '30',
        'printer_name': '',
        'printer_port': 'USB',
        'auto_print': '1',
        # Automatic Telegram reports (daily Excel to shop owner)
        'auto_report_daily': '1',
        'auto_report_weekly': '0',
        'auto_report_interval_hours': '4',
        'auto_report_weekday': '0',
        # M-Pesa (manual — each shop enters Till/Paybill; no buyer accounts)
        'mpesa_mode': 'manual',
        'mpesa_till': '',
        'mpesa_paybill': '',
        'mpesa_business_name': '',
    }
