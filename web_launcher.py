"""
MBT POS — Silent Web Service Launcher
MugoByte Technologies | mugobyte.com

Runs completely invisibly:
  - No CMD window
  - No console output
  - No prompts
  - No interference with the desktop POS
  - All output goes to logs/web_launcher.log only

Launched by a .vbs script (not .bat) so no CMD window ever appears.
Self-heals Flask + cloudflared tunnel silently.
"""
import os, sys, time, json, socket, logging, threading, subprocess, urllib.request
from pathlib import Path
from datetime import datetime

# ── Paths ──────────────────────────────────────────────────────────────────
BASE_DIR = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
LOG_DIR  = BASE_DIR / 'logs'
LOG_DIR.mkdir(parents=True, exist_ok=True)
(BASE_DIR / 'data').mkdir(exist_ok=True)
(BASE_DIR / 'config').mkdir(exist_ok=True)

# ── Silent logging — file only, never stdout ───────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler(LOG_DIR / 'web_launcher.log', encoding='utf-8')]
)
log = logging.getLogger('launcher')

# ── Config ─────────────────────────────────────────────────────────────────
def load_cfg():
    try:
        from backend.cloudflare_setup import load_web_config
        return load_web_config()
    except Exception:
        return {
            "flask_port": 5050, "flask_host": "0.0.0.0",
            "tunnel_domain": "", "tunnel_name": "",
            "remote_enabled": False,
            "check_interval": 30, "max_restarts": 50, "cloudflared_exe": "",
        }

CFG = load_cfg()

# ── Windows subprocess flags — always hide every child window ──────────────
if sys.platform == 'win32':
    import ctypes
    _DETACHED   = 0x00000008   # DETACHED_PROCESS
    _NO_WINDOW  = 0x08000000   # CREATE_NO_WINDOW
    _NEW_GROUP  = 0x00000200   # CREATE_NEW_PROCESS_GROUP
    _SW_FLAGS   = _NO_WINDOW   # used for all subprocesses
    def _hide():
        """Return creationflags that suppress ALL windows for a subprocess."""
        return _NO_WINDOW
else:
    def _hide(): return 0

# ── Global state ───────────────────────────────────────────────────────────
_flask_proc  = None
_tunnel_proc = None
_flask_restarts  = 0
_tunnel_restarts = 0
_lock = threading.Lock()

# ══════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════

def _run(*cmd, **kw):
    """Run a command with no visible window, capture output."""
    return subprocess.run(
        list(cmd), capture_output=True, timeout=kw.pop('timeout', 10),
        creationflags=_hide(), **kw
    )


def is_online():
    for host, port in [('1.1.1.1', 53), ('8.8.8.8', 53)]:
        try:
            s = socket.socket(); s.settimeout(3); s.connect((host, port)); s.close(); return True
        except Exception: pass
    return False


def port_in_use(port):
    with socket.socket() as s:
        return s.connect_ex(('127.0.0.1', port)) == 0


def kill_port(port):
    log.warning(f"Port {port} occupied — clearing...")
    if sys.platform == 'win32':
        try:
            r = _run('netstat', '-ano')
            pids = set()
            for line in r.stdout.decode(errors='replace').splitlines():
                if f':{port}' in line and 'LISTENING' in line:
                    parts = line.split()
                    try: pids.add(int(parts[-1]))
                    except ValueError: pass
            for pid in pids:
                if pid > 4:
                    _run('taskkill', '/F', '/PID', str(pid))
                    log.info(f"Killed PID {pid} (port {port})")
        except Exception as e: log.error(f"kill_port: {e}")
    else:
        try: _run('fuser', '-k', f'{port}/tcp')
        except Exception as e: log.error(f"kill_port: {e}")
    time.sleep(1)


def ensure_port_free(port, retries=3):
    for _ in range(retries):
        if not port_in_use(port): return True
        kill_port(port)
        time.sleep(2)
    return not port_in_use(port)


def find_python():
    for c in [
        r'C:\MBT_Build\_python311\python.exe',   # installed by INSTALL.bat
        sys.executable,
        'python', 'python3',
        r'C:\Python311\python.exe',
        r'C:\Python312\python.exe',
        r'C:\Python310\python.exe',
    ]:
        try:
            r = _run(c, '--version')
            if b'Python 3' in r.stdout + r.stderr: return c
        except Exception: pass
    return sys.executable

# ══════════════════════════════════════════════════════════════════════════
# FLASK
# ══════════════════════════════════════════════════════════════════════════

def is_flask_alive():
    try:
        r = urllib.request.urlopen(f"http://127.0.0.1:{CFG['flask_port']}/api/health", timeout=3)
        return r.status == 200
    except Exception: return False


def start_flask():
    global _flask_restarts
    port   = CFG['flask_port']
    app_py = BASE_DIR / 'backend' / 'app.py'
    if not app_py.exists():
        log.error(f"backend/app.py not found"); return None
    if not ensure_port_free(port):
        log.error(f"Port {port} blocked"); return None

    python = find_python()
    env    = os.environ.copy()
    env['PYTHONPATH'] = str(BASE_DIR)

    # Redirect Flask stdout/stderr to its own log file — never to screen
    flask_log = open(LOG_DIR / 'flask.log', 'a', encoding='utf-8')
    try:
        proc = subprocess.Popen(
            [python, str(app_py)],
            cwd=str(BASE_DIR), env=env,
            stdout=flask_log, stderr=flask_log,
            creationflags=_hide(),
            # On Windows, prevent the child inheriting our (invisible) console
            close_fds=True,
        )
        _flask_restarts += 1
        log.info(f"Flask starting PID={proc.pid} (restart #{_flask_restarts})")
        # Wait up to 10s for health check
        for _ in range(20):
            time.sleep(0.5)
            if is_flask_alive(): log.info("Flask is up"); return proc
            if proc.poll() is not None: log.error(f"Flask exited early (code {proc.returncode})"); return None
        log.warning("Flask health check timeout — continuing")
        return proc
    except Exception as e:
        log.error(f"start_flask: {e}"); return None

# ══════════════════════════════════════════════════════════════════════════
# CLOUDFLARED
# ══════════════════════════════════════════════════════════════════════════


def download_cloudflared():
    """Auto-download cloudflared if not found — runs silently."""
    if sys.platform == 'win32':
        url  = 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe'
        dest = str(BASE_DIR / 'cloudflared.exe')
    elif sys.platform == 'darwin':
        url  = 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz'
        dest = '/usr/local/bin/cloudflared'
    else:
        url  = 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64'
        dest = str(BASE_DIR / 'cloudflared')
    log.info(f"Downloading cloudflared from GitHub → {dest}")
    try:
        urllib.request.urlretrieve(url, dest)
        if sys.platform != 'win32':
            os.chmod(dest, 0o755)
        log.info("cloudflared downloaded successfully")
        return dest
    except Exception as e:
        log.error(f"cloudflared download failed: {e}")
        return None

def find_cloudflared():
    if CFG.get('cloudflared_exe') and Path(CFG['cloudflared_exe']).exists():
        return CFG['cloudflared_exe']
    candidates = [
        str(BASE_DIR / 'cloudflared.exe'), str(BASE_DIR / 'cloudflared'),
        r'C:\Program Files\cloudflared\cloudflared.exe',
        r'C:\cloudflared\cloudflared.exe',
        str(Path.home() / '.cloudflared' / 'cloudflared.exe'),
        'cloudflared', '/usr/local/bin/cloudflared',
    ]
    for c in candidates:
        try:
            r = _run(c, '--version')
            if r.returncode == 0: log.info(f"cloudflared: {c}"); return c
        except Exception: pass
    return None


def tunnel_config():
    for p in [Path.home()/'.cloudflared'/'config.yml', BASE_DIR/'cloudflared-config.yml']:
        if p.exists(): return str(p)
    return None


def start_tunnel(exe):
    global _tunnel_restarts
    if not exe: return None
    if not is_flask_alive(): log.warning("Flask not alive — skipping tunnel"); return None

    port   = CFG['flask_port']
    domain = CFG['tunnel_domain']
    cfg    = tunnel_config()

    if cfg:
        cmd = [exe, 'tunnel', '--config', cfg, 'run']
    else:
        cmd = [exe, 'tunnel', '--url', f'http://localhost:{port}',
               '--hostname', domain]

    cf_log = open(LOG_DIR / 'cloudflared.log', 'a', encoding='utf-8')
    try:
        proc = subprocess.Popen(
            cmd, cwd=str(BASE_DIR),
            stdout=cf_log, stderr=cf_log,
            creationflags=_hide(),
            close_fds=True,
        )
        _tunnel_restarts += 1
        log.info(f"Tunnel starting PID={proc.pid} (restart #{_tunnel_restarts}) → {domain}")
        time.sleep(3)
        if proc.poll() is None: return proc
        log.warning(f"Tunnel exited immediately (code {proc.returncode})")
        return proc
    except Exception as e:
        log.error(f"start_tunnel: {e}"); return None

# ══════════════════════════════════════════════════════════════════════════
# STATUS SERVER  (localhost:5051/status — for diagnostics only)
# ══════════════════════════════════════════════════════════════════════════

def run_status_server():
    from http.server import HTTPServer, BaseHTTPRequestHandler
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            if self.path != '/status':
                self.send_response(404); self.end_headers(); return
            s = {
                'time': datetime.now().isoformat(),
                'flask':  {'ok': is_flask_alive(), 'restarts': _flask_restarts,
                           'pid': _flask_proc.pid if _flask_proc else None},
                'tunnel': {'ok': _tunnel_proc is not None and _tunnel_proc.poll() is None,
                           'restarts': _tunnel_restarts,
                           'pid': _tunnel_proc.pid if _tunnel_proc else None},
                'internet': is_online(),
                'port': CFG['flask_port'], 'domain': CFG['tunnel_domain'],
            }
            body = json.dumps(s).encode()
            self.send_response(200)
            self.send_header('Content-Type','application/json')
            self.send_header('Access-Control-Allow-Origin','*')
            self.end_headers(); self.wfile.write(body)
    try: HTTPServer(('127.0.0.1', 5051), H).serve_forever()
    except Exception as e: log.warning(f"Status server: {e}")

# ══════════════════════════════════════════════════════════════════════════
# MONITOR  (runs forever, restarts crashed services silently)
# ══════════════════════════════════════════════════════════════════════════

def monitor(exe):
    global _flask_proc, _tunnel_proc
    interval = CFG['check_interval']
    log.info(f"Monitor started (interval={interval}s)")
    while True:
        time.sleep(interval)
        with _lock:
            # Flask check
            flask_dead = _flask_proc is None or _flask_proc.poll() is not None
            if flask_dead:
                log.warning(f"Flask down — restarting (#{_flask_restarts})")
                if _flask_restarts < CFG['max_restarts']:
                    _flask_proc = start_flask()
            elif not is_flask_alive():
                log.warning("Flask unhealthy — restarting")
                try: _flask_proc.terminate()
                except Exception: pass
                time.sleep(2)
                _flask_proc = start_flask()

            # Tunnel check
            if is_online() and exe:
                t_dead = _tunnel_proc is None or _tunnel_proc.poll() is not None
                if t_dead and _tunnel_restarts < CFG['max_restarts']:
                    log.warning(f"Tunnel down — restarting (#{_tunnel_restarts})")
                    _tunnel_proc = start_tunnel(exe)

# ══════════════════════════════════════════════════════════════════════════
# INTERNET WAIT
# ══════════════════════════════════════════════════════════════════════════

def wait_internet(max_wait=300):
    if is_online(): return
    log.info("Waiting for internet...")
    waited = 0
    while not is_online() and waited < max_wait:
        time.sleep(5); waited += 5
    if is_online(): log.info("Internet connected")
    else: log.warning("No internet after wait — tunnel will retry later")

# ══════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════

def main():
    global _flask_proc, _tunnel_proc
    log.info("MBT POS Web Launcher starting")
    log.info(f"BASE_DIR={BASE_DIR}  port={CFG['flask_port']}  domain={CFG['tunnel_domain']}")

    wait_internet()

    _flask_proc = start_flask()
    if not _flask_proc:
        log.critical("Flask failed to start — aborting"); sys.exit(1)

    exe = find_cloudflared()
    if not exe and is_online():
        log.info("cloudflared not found — attempting auto-download")
        exe = download_cloudflared()
        if exe:
            log.info("cloudflared downloaded — starting tunnel")
    if exe:
        _tunnel_proc = start_tunnel(exe)
    else:
        log.warning("cloudflared unavailable — tunnel disabled. Run SETUP CLOUDFLARE.bat")

    threading.Thread(target=run_status_server, daemon=True).start()
    threading.Thread(target=monitor, args=(exe,), daemon=True).start()

    log.info(f"All services running. Dashboard → https://{CFG['tunnel_domain']}")

    # Stay alive silently — no output, no prompts
    try:
        while True: time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        log.info("Shutting down")
        try:
            if _tunnel_proc: _tunnel_proc.terminate()
            if _flask_proc:  _flask_proc.terminate()
        except Exception: pass


if __name__ == '__main__':
    main()
