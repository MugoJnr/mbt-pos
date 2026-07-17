"""
Per-deployment defaults for MBT POS (multi-shop).
Set MBT_BOT_TOKEN env var or config/deploy.local.json before building the installer.
"""
import json
import os

_DIR = os.path.dirname(os.path.abspath(__file__))
_LOCAL = os.path.join(_DIR, 'deploy.local.json')


def _appdata_deploy_local() -> str:
    """Installed .exe: optional overrides in %LOCALAPPDATA%\\MugoByte\\MBT POS\\config\\."""
    try:
        from mbt_paths import get_project_root
        return os.path.join(get_project_root(), 'config', 'deploy.local.json')
    except Exception:
        return ''


def _load_deploy_local_files() -> dict:
    merged = {}
    # AppData overrides bundled file so live shops can fix tokens without rebuild
    for path in (_LOCAL, _appdata_deploy_local()):
        if path and os.path.isfile(path):
            try:
                with open(path, encoding='utf-8-sig') as f:
                    data = json.load(f)
                # Skip misfiled connector tokens in cloudflare_api_token
                api = (data.get('cloudflare_api_token') or '').strip()
                if api.lower().startswith('cfut_') or api.startswith('eyJ'):
                    data = dict(data)
                    if not (data.get('cloudflare_tunnel_token') or '').strip():
                        data['cloudflare_tunnel_token'] = api
                    data['cloudflare_api_token'] = ''
                merged.update(data)
            except Exception:
                pass
    return merged

# Shop-facing Telegram bot (@mbt_admin1_bot) — override per build via deploy.local.json
_DEFAULT_BOT = '8342651179:AAE_JPNBUxWz9dkz49Ldr9sySwsabpx1IwQ'
_DEFAULT_DEVELOPER_CHAT = '8293620725'


def load_deploy_config() -> dict:
    """Build-time + install defaults. Shipped inside every MBT_POS_Setup.exe."""
    cfg = {
        'telegram_bot_token': os.environ.get('MBT_BOT_TOKEN', '').strip() or _DEFAULT_BOT,
        'telegram_bot_username': 'mbt_admin1_bot',
        'developer_chat_id': os.environ.get('MBT_DEVELOPER_CHAT_ID', '').strip()
            or _DEFAULT_DEVELOPER_CHAT,
        'cloudflare_api_token': os.environ.get('CLOUDFLARE_API_TOKEN', '').strip(),
    }
    cfg.update(_load_deploy_local_files())
    return cfg


def verify_installer_bundle() -> tuple[bool, str]:
    """Called from BUILD.bat — fail the build if Telegram bot is not embedded."""
    try:
        c = load_deploy_config()
        token = (c.get('telegram_bot_token') or '').strip()
        user = (c.get('telegram_bot_username') or 'mbt_admin1_bot').lstrip('@')
        if not token:
            return False, 'telegram_bot_token is empty in config/deploy.py'
        if not os.path.isfile(os.path.join(_DIR, 'deploy.py')):
            return False, 'config/deploy.py missing from project'
        return True, f'@{user}'
    except Exception as e:
        return False, str(e)


def verify_cloudflare_token() -> tuple[bool, str]:
    """BUILD.bat — auto Cloudflare needs a real management API token (not cfut_/JWT)."""
    tok = (load_deploy_config().get('cloudflare_api_token') or '').strip()
    if not tok:
        return False, (
            'cloudflare_api_token missing — remote dashboard will NOT auto-setup on shop PCs.\n'
            '  Create config/deploy.local.json with your Cloudflare management API token, or set\n'
            '  CLOUDFLARE_API_TOKEN before running BUILD.bat\n'
            '  Permissions: Account → Cloudflare Tunnel → Edit; Zone → DNS → Edit (mugobyte.com)')
    low = tok.lower()
    if low.startswith('cfut_') or tok.startswith('eyJ'):
        return False, (
            'cloudflare_api_token is a tunnel connector token (cfut_/JWT) — wrong type.\n'
            '  Use a management API token (often cfat_…) with Tunnel Edit + DNS Edit.\n'
            '  Put connector tokens in cloudflare_tunnel_token only if HQ pre-issues them.')
    if len(tok) < 20:
        return False, 'cloudflare_api_token looks too short'
    return True, 'Management API token present in deploy config'


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
        'auto_db_backup': '1',
        'auto_db_backup_interval_hours': '24',
        # M-Pesa (manual — each shop enters Till/Paybill; no buyer accounts)
        'mpesa_mode': 'manual',
        'mpesa_till': '',
        'mpesa_paybill': '',
        'mpesa_business_name': '',
    }
