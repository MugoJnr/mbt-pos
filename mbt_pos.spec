# -*- mode: python ; coding: utf-8 -*-
# MBT POS - PyInstaller Spec (onedir — reliable updates, no python DLL extract errors)
# MugoByte Technologies | mugobyte.com
# Build with: python -m PyInstaller mbt_pos.spec

import json
import os
HERE = os.path.abspath(SPECPATH)

try:
    from PyInstaller.utils.hooks import collect_data_files
    _tzdata_datas = collect_data_files('tzdata')
except Exception:
    _tzdata_datas = []

_cf_bin = os.path.join(HERE, 'tools', 'cloudflared.exe')
_extra_binaries = [(_cf_bin, '.')] if os.path.isfile(_cf_bin) else []


def _runtime_version_manifest():
    """Create the packaged manifest without a self-referential installer hash."""
    source = os.path.join(HERE, 'version.json')
    with open(source, encoding='utf-8-sig') as f:
        payload = json.load(f)
    payload['checksum_sha256'] = ''
    target = os.path.join(HERE, 'build', '_release_manifest', 'version.json')
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(payload, f, indent=4)
        f.write('\n')
    return target

def _web_runtime_datas():
    """Ship only what Flask actually serves at runtime.

    web_routes serves the built SPA (<app>/dist) plus web/templates. Walking
    all of web/ additionally swept in the front-end toolchain — lockfiles,
    tsconfig/eslint/vite configs, READMEs, developer scratch scripts, and a
    second copy of every icon under public/ — none of which a shop PC can use.
    """
    web_root = os.path.join(HERE, 'web')
    out = []

    for name in sorted(os.listdir(web_root)):
        src = os.path.join(web_root, name)
        if os.path.isfile(src) and name.endswith('.py'):
            out.append((src, 'web'))

    shipped_trees = [os.path.join(web_root, 'templates')]
    for entry in sorted(os.listdir(web_root)):
        dist = os.path.join(web_root, entry, 'dist')
        if os.path.isdir(dist):
            shipped_trees.append(dist)

    for tree in shipped_trees:
        if not os.path.isdir(tree):
            continue
        for root, dirs, files in os.walk(tree):
            dirs[:] = [d for d in dirs if d not in ('__pycache__', '.git')]
            rel_root = os.path.relpath(root, HERE)
            for f in files:
                if f.endswith('.map'):
                    continue
                out.append((os.path.join(root, f), rel_root))
    return out


def _safe_config_datas():
    """Bundle config code and public templates only.

    Runtime vendor credentials belong in the per-machine AppData configuration
    or a server-side proxy. A local deploy file must never enter an installer.
    """
    config_root = os.path.join(HERE, 'config')
    allowed_files = {
        '__init__.py',
        'deploy.py',
        'cloud_config.example.json',
        'deploy.local.json.example',
        'web_config.json',
    }
    return [
        (os.path.join(config_root, name), 'config')
        for name in sorted(allowed_files)
        if os.path.isfile(os.path.join(config_root, name))
    ]

a = Analysis(
    [os.path.join(HERE, 'launcher.py')],
    pathex=[HERE],
    binaries=_extra_binaries,
    datas=[
        (os.path.join(HERE, 'assets'),      'assets'),
        (os.path.join(HERE, 'printing'),    'printing'),
        (os.path.join(HERE, 'diagnostics'), 'diagnostics'),
        (_runtime_version_manifest(), '.'),
    ] + _safe_config_datas() + _web_runtime_datas() + _tzdata_datas + (
        [(os.path.join(HERE, 'web_launcher.py'), '.')]
        if os.path.exists(os.path.join(HERE, 'web_launcher.py')) else []
    ),
    hiddenimports=[
        'PyQt5', 'PyQt5.QtWidgets', 'PyQt5.QtCore', 'PyQt5.QtGui', 'PyQt5.sip',
        'PyQt5.QtSvg',
        'jwt', 'jwt.algorithms',
        'bcrypt', 'cffi', '_cffi_backend',
        'requests', 'urllib3', 'charset_normalizer', 'certifi', 'idna',
        'openpyxl', 'openpyxl.styles', 'openpyxl.utils',
        'openpyxl.chart', 'openpyxl.chart.bar_chart', 'et_xmlfile',
        'flask', 'flask_cors', 'werkzeug', 'werkzeug.utils',
        'werkzeug.routing', 'werkzeug.exceptions', 'werkzeug.serving',
        'click',
        'serial', 'serial.tools', 'serial.tools.list_ports',
        'sqlite3', '_sqlite3',
        'hashlib', 'hmac', 'base64', 'json', 'threading',
        'logging', 'logging.handlers',
        'email', 'email.mime', 'email.mime.text',
        'mbt_paths',
        'roles',
        'licensing.activation_ui',
        'licensing.license_engine',
        'licensing.license_service',
        'licensing.license_service',
        'backend.cloud.notification_engine',
        'backend.cloud.report_engine',
        'backend.cloud.device_service',
        'backend.cloud.command_center',
        'backend.export_engine',
        'backend.internet_monitor',
        'diagnostics.diagnostic_engine',
        'printing.printer_engine',
        'printing.escpos_commands',
        'printing.profiles',
        'printing.transports',
        'printing.receipt_formatter',
        'printing.print_job',
        'win32print', 'win32api', 'pywintypes',
        'desktop.wizard.setup_wizard',
        'desktop.utils.theme',
        # Imported lazily inside MainWindow._build_ui, so pin them explicitly —
        # a missed collapsible-sidebar module ships a POS with no left rail.
        'desktop.utils.sidebar_prefs',
        'desktop.utils.shell_splitter',
        'desktop.utils.widgets',
        'desktop.utils.api_client',
        'desktop.utils.log_config',
        # Lazily imported from reports/inventory/finance/export paths — pin so
        # Super-Admin PIN spreadsheet gates ship in the frozen tree.
        'desktop.utils.export_security',
        'desktop.tabs.debt_tab',
        'desktop.payments',
        'desktop.payments.service',
        'desktop.payments.provider',
        'desktop.payments.cloud_client',
        'desktop.payments.matching',
        'desktop.payments.repository',
        'desktop.payments.schema',
        'desktop.payments.models',
        'desktop.payments.security',
        'desktop.dialogs.mpesa_checkout_dialog',
        'desktop.dialogs.payment_inbox_dialog',
        'desktop.pos',
        'desktop.pos.layout_ids',
        'desktop.pos.panel_factory',
        'desktop.pos.layouts',
        'desktop.pos.layouts.shells',
        'backend.app',
        'backend.app_version',
        'backend.web_service',
        'backend.cloudflare_setup',
        'backend.updater',
        'config.deploy',
        'backend.db_backup',
        'tzdata',
        'zoneinfo',
        'desktop.utils.shop_time',
        'web', 'web.web_routes',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'matplotlib', 'numpy', 'pandas',
        'scipy', 'PIL', 'cv2', 'tensorflow',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MBT_POS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    manifest=os.path.join(HERE, 'mbt_pos.manifest'),
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(HERE, 'assets', 'mbt_icon.ico')
         if os.path.exists(os.path.join(HERE, 'assets', 'mbt_icon.ico'))
         else None,
    version=os.path.join(HERE, 'file_version_info.txt')
         if os.path.exists(os.path.join(HERE, 'file_version_info.txt'))
         else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='MBT_POS',
)
