# -*- mode: python ; coding: utf-8 -*-
# MBT POS - PyInstaller Spec (onedir — reliable updates, no python DLL extract errors)
# MugoByte Technologies | mugobyte.com
# Build with: python -m PyInstaller mbt_pos.spec

import os
HERE = os.path.abspath(SPECPATH)

_cf_bin = os.path.join(HERE, 'tools', 'cloudflared.exe')
_extra_binaries = [(_cf_bin, '.')] if os.path.isfile(_cf_bin) else []

a = Analysis(
    [os.path.join(HERE, 'launcher.py')],
    pathex=[HERE],
    binaries=_extra_binaries,
    datas=[
        (os.path.join(HERE, 'assets'),      'assets'),
        (os.path.join(HERE, 'backend'),     'backend'),
        (os.path.join(HERE, 'desktop'),     'desktop'),
        (os.path.join(HERE, 'licensing'),   'licensing'),
        (os.path.join(HERE, 'printing'),    'printing'),
        (os.path.join(HERE, 'diagnostics'), 'diagnostics'),
        (os.path.join(HERE, 'web'),         'web'),
        (os.path.join(HERE, 'version.json'), '.'),
        (os.path.join(HERE, 'config'),       'config'),
    ] + ([(os.path.join(HERE, 'web_launcher.py'), '.')]
         if os.path.exists(os.path.join(HERE, 'web_launcher.py')) else []),
    hiddenimports=[
        'PyQt5', 'PyQt5.QtWidgets', 'PyQt5.QtCore', 'PyQt5.QtGui', 'PyQt5.sip',
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
        'licensing.telegram_admin',
        'backend.export_engine',
        'backend.telegram_reporter',
        'backend.internet_monitor',
        'diagnostics.diagnostic_engine',
        'printing.printer_engine',
        'desktop.wizard.setup_wizard',
        'desktop.utils.theme',
        'desktop.utils.widgets',
        'desktop.utils.api_client',
        'desktop.utils.log_config',
        'desktop.tabs.debt_tab',
        'backend.app',
        'backend.web_service',
        'backend.cloudflare_setup',
        'backend.telegram_hub',
        'backend.updater',
        'config.deploy',
        'backend.db_backup',
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
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(HERE, 'assets', 'mbt_icon.ico')
         if os.path.exists(os.path.join(HERE, 'assets', 'mbt_icon.ico'))
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
