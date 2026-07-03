"""
MBT POS — Web Diagnostics Tool
MugoByte Technologies | mugobyte.com

Checks:
  - Python version
  - Required packages
  - Port availability (5050, 5051)
  - Flask backend health
  - Cloudflared presence and version
  - Internet connectivity
  - Cloudflare tunnel status
  - Database accessibility
  - Log files

Run: python WEB_DIAGNOSTICS.py
"""
import os
import sys
import json
import time
import socket
import subprocess
import importlib
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent

W = '\033[93m'   # yellow
G = '\033[92m'   # green
R = '\033[91m'   # red
B = '\033[94m'   # blue
E = '\033[0m'    # reset
BOLD = '\033[1m'

# Enable ANSI on Windows
if sys.platform == 'win32':
    os.system('color')

def ok(msg):   print(f"  {G}✓{E} {msg}")
def fail(msg): print(f"  {R}✗{E} {msg}")
def warn(msg): print(f"  {W}!{E} {msg}")
def info(msg): print(f"  {B}→{E} {msg}")
def header(msg): print(f"\n{BOLD}{msg}{E}\n" + "─"*50)


def check_python():
    header("Python Environment")
    v = sys.version_info
    if v >= (3, 9):
        ok(f"Python {v.major}.{v.minor}.{v.micro} ({sys.executable})")
    else:
        fail(f"Python {v.major}.{v.minor} — need 3.9+. Get Python 3.11 from python.org")


def check_packages():
    header("Required Packages")
    required = {
        'flask':    'Flask',
        'jwt':      'PyJWT',
        'flask_cors': 'flask-cors (optional)',
    }
    for mod, name in required.items():
        try:
            m = importlib.import_module(mod)
            ver = getattr(m, '__version__', '?')
            ok(f"{name} {ver}")
        except ImportError:
            if 'optional' in name:
                warn(f"{name} not installed (non-critical)")
            else:
                fail(f"{name} not installed → run: pip install {mod} --break-system-packages")


def check_ports():
    header("Port Status")
    ports = {5050: 'Flask backend', 5051: 'Status server'}
    results = {}
    for port, label in ports.items():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            in_use = s.connect_ex(('127.0.0.1', port)) == 0
        if in_use:
            ok(f"Port {port} ({label}) — IN USE (service running)")
        else:
            warn(f"Port {port} ({label}) — free (service not started yet)")
        results[port] = in_use
    return results


def check_flask():
    header("Flask Backend")
    import urllib.request
    try:
        req = urllib.request.urlopen('http://127.0.0.1:5050/api/health', timeout=4)
        data = json.loads(req.read())
        ok(f"Flask responding — status: {data.get('status','?')}, time: {data.get('time','?')[:19]}")
        return True
    except Exception as e:
        fail(f"Flask not responding: {e}")
        info("Fix: run 'START WEB.bat' or 'python backend/app.py'")
        return False


def check_database():
    header("Database")
    db_path = BASE_DIR / 'data' / 'mbt_pos.db'
    if db_path.exists():
        size = db_path.stat().st_size
        ok(f"Database found: {db_path} ({size/1024:.1f} KB)")
        try:
            import sqlite3
            conn = sqlite3.connect(str(db_path), timeout=3)
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            conn.close()
            ok(f"Tables: {', '.join(sorted(tables))}")
            required_tables = {'users','products','sales','sale_items','audit_log','system_settings'}
            debt_tables = {'customers','debt_invoices','debt_payments'}
            missing = required_tables - set(tables)
            missing_debt = debt_tables - set(tables)
            if missing:
                fail(f"Missing tables: {missing}")
            if missing_debt:
                warn(f"Debt tables missing: {missing_debt} — run app once to create them")
        except Exception as e:
            fail(f"Cannot read database: {e}")
    else:
        warn(f"Database not found at {db_path}")
        info("It will be created automatically when Flask starts")


def check_internet():
    header("Internet Connectivity")
    checks = [
        ('1.1.1.1', 53,  'Cloudflare DNS'),
        ('8.8.8.8', 53,  'Google DNS'),
        ('cloudflare.com', 443, 'Cloudflare HTTPS'),
    ]
    any_ok = False
    for host, port, label in checks:
        try:
            s = socket.socket(); s.settimeout(3)
            s.connect((host, port)); s.close()
            ok(f"{label} reachable")
            any_ok = True
        except Exception:
            fail(f"{label} unreachable")
    return any_ok


def check_cloudflared():
    header("Cloudflare Tunnel (cloudflared)")
    candidates = [
        str(BASE_DIR / 'cloudflared.exe'),
        str(BASE_DIR / 'cloudflared'),
        'cloudflared',
        r'C:\Program Files\cloudflared\cloudflared.exe',
        '/usr/local/bin/cloudflared',
    ]
    found = None
    for c in candidates:
        try:
            r = subprocess.run([c, '--version'], capture_output=True, timeout=5)
            if r.returncode == 0:
                version = (r.stdout + r.stderr).decode().strip()
                ok(f"cloudflared found: {c}")
                ok(f"Version: {version[:60]}")
                found = c
                break
        except Exception:
            pass
    if not found:
        fail("cloudflared not found in any expected location")
        info("Fix: run 'SETUP CLOUDFLARE.bat' — it will download cloudflared automatically")
        return False

    # Check if tunnel is running
    try:
        r = subprocess.run(['tasklist' if sys.platform=='win32' else 'pgrep', '-f', 'cloudflared'],
                           capture_output=True, text=True, timeout=5)
        if 'cloudflared' in r.stdout.lower():
            ok("cloudflared process is running")
        else:
            warn("cloudflared process not currently running")
            info("It will start automatically when 'START WEB.bat' runs")
    except Exception:
        warn("Could not check cloudflared process status")

    # Check config
    config_paths = [
        Path.home() / '.cloudflared' / 'config.yml',
        BASE_DIR / 'cloudflared-config.yml',
    ]
    for cp in config_paths:
        if cp.exists():
            ok(f"Config found: {cp}")
            break
    else:
        warn("No cloudflared config.yml found")
        info("Fix: run 'SETUP CLOUDFLARE.bat' to configure the tunnel")

    return True


def check_logs():
    header("Log Files")
    log_dir = BASE_DIR / 'logs'
    if not log_dir.exists():
        warn("logs/ directory does not exist yet")
        return
    log_files = list(log_dir.glob('*.log'))
    if not log_files:
        info("No log files yet — logs appear after first run")
        return
    for lf in sorted(log_files):
        size = lf.stat().st_size
        lines = 0
        last_line = ''
        try:
            with open(lf, 'r', encoding='utf-8', errors='replace') as f:
                for line in f: lines += 1; last_line = line.strip()
        except Exception: pass
        errors = 0
        try:
            with open(lf, 'r', encoding='utf-8', errors='replace') as f:
                errors = sum(1 for l in f if 'ERROR' in l or 'CRITICAL' in l)
        except Exception: pass
        status = f"{G}✓{E}" if errors == 0 else f"{W}!{E}"
        print(f"  {status} {lf.name:<30} {size/1024:6.1f}KB  {lines} lines  {errors} errors")
        if errors > 0 and last_line:
            print(f"      Last line: {last_line[:80]}")


def check_web_files():
    header("Web Dashboard Files")
    required = [
        BASE_DIR / 'web' / 'templates' / 'dashboard.html',
        BASE_DIR / 'web' / 'web_routes.py',
        BASE_DIR / 'web_launcher.py',
        BASE_DIR / 'backend' / 'app.py',
    ]
    for f in required:
        if f.exists():
            ok(f"{f.relative_to(BASE_DIR)} ({f.stat().st_size/1024:.1f}KB)")
        else:
            fail(f"MISSING: {f.relative_to(BASE_DIR)}")


def check_status_endpoint():
    header("Launcher Status Endpoint")
    import urllib.request
    try:
        req = urllib.request.urlopen('http://127.0.0.1:5051/status', timeout=3)
        data = json.loads(req.read())
        overall = data.get('overall','?')
        color = G if overall == 'healthy' else W
        print(f"  {color}→{E} Overall: {overall}")
        print(f"    Flask:   {'✓' if data['flask']['ok'] else '✗'} (restarts: {data['flask']['restarts']})")
        print(f"    Tunnel:  {'✓' if data['tunnel']['ok'] else '✗'} (restarts: {data['tunnel']['restarts']})")
        print(f"    Net:     {'✓' if data['internet']['ok'] else '✗'}")
        print(f"    Domain:  {data['tunnel_domain']}")
    except Exception:
        warn("Status endpoint not reachable (launcher not running)")
        info("Start with 'START WEB.bat' then re-run this tool")


def suggest_fixes(flask_ok, net_ok, cloudflared_ok):
    issues = []
    if not flask_ok: issues.append("Flask is not running")
    if not net_ok:   issues.append("No internet connection")
    if not cloudflared_ok: issues.append("cloudflared not installed")

    if issues:
        header("Suggested Fixes")
        for i in issues:
            warn(i)
        print()
        if not flask_ok:
            info("→ Run 'START WEB.bat' to start all services automatically")
        if not net_ok:
            info("→ Check your router/modem and reconnect to internet")
        if not cloudflared_ok:
            info("→ Run 'SETUP CLOUDFLARE.bat' to install and configure cloudflared")
    else:
        header("Result")
        ok("Everything looks good!")
        ok(f"Web dashboard: https://edmuspos.mugobyte.com")
        ok(f"Local access:  http://localhost:5050")


if __name__ == '__main__':
    print(f"\n{BOLD}{'='*52}")
    print("  MBT POS — Web Service Diagnostics")
    print(f"  MugoByte Technologies  ·  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*52}{E}")

    check_python()
    check_packages()
    check_ports()
    flask_ok = check_flask()
    check_database()
    net_ok = check_internet()
    cloudflared_ok = check_cloudflared()
    check_web_files()
    check_logs()
    check_status_endpoint()
    suggest_fixes(flask_ok, net_ok, cloudflared_ok)

    print()
    if sys.platform == 'win32':
        input("Press Enter to close...")
