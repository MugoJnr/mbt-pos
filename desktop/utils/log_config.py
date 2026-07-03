"""
MBT POS — Centralised Logging Configuration
MugoByte Technologies | mugobyte.com

Each module logs to its own file. All critical/unhandled errors go to app_error.log.
"""
import logging
import logging.handlers
import os
import sys
import traceback

_CONFIGURED = False


def setup_logging(base_dir: str):
    """
    Call once at startup (from launcher.py).
    Creates per-module rotating log files.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    log_dir = os.path.join(base_dir, 'logs')
    os.makedirs(log_dir, exist_ok=True)

    fmt = logging.Formatter(
        '%(asctime)s [%(levelname)s] [%(name)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    def _file_handler(filename, level=logging.INFO):
        path = os.path.join(log_dir, filename)
        h = logging.handlers.RotatingFileHandler(
            path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding='utf-8'
        )
        h.setLevel(level)
        h.setFormatter(fmt)
        return h

    # Root logger — catches everything not otherwise handled
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(_file_handler('app.log'))

    # Module-specific loggers
    _modules = {
        'desktop.utils.api_client':       ('inventory.log',     logging.DEBUG),
        'desktop.tabs.inventory_tab':     ('inventory.log',     logging.DEBUG),
        'desktop.tabs.sales_tab':         ('pos.log',           logging.DEBUG),
        'desktop.tabs.debt_tab':          ('debt.log',          logging.DEBUG),
        'desktop.tabs.reports_tab':       ('reports.log',       logging.INFO),
        'desktop.tabs.admin_tab':         ('admin.log',         logging.INFO),
        'desktop.tabs.settings_tab':      ('settings.log',      logging.INFO),
        'desktop.tabs.security_tab':      ('security.log',      logging.INFO),
        'desktop.utils.security':         ('security.log',      logging.DEBUG),
        'backend.app':                    ('backend.log',       logging.INFO),
        'licensing':                      ('license.log',       logging.INFO),
        'diagnostics':                    ('diagnostics.log',   logging.INFO),
    }
    for name, (fname, level) in _modules.items():
        log = logging.getLogger(name)
        log.addHandler(_file_handler(fname, level))
        log.propagate = True   # also goes to root/app.log

    # Structured error logger for uncaught exceptions
    err_log = logging.getLogger('mbt_errors')
    err_log.addHandler(_file_handler('app_error.log', logging.ERROR))

    # Intercept uncaught exceptions
    def _exc_hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        tb_str = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logging.getLogger('mbt_errors').critical(
            f"UNCAUGHT EXCEPTION:\n{tb_str}"
        )
    sys.excepthook = _exc_hook
