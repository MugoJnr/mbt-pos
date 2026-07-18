"""
MBT POS — Enterprise Audio Experience Engine
Offline-first singleton. Only entry point: AudioManager.play(event).

Collision prevention: priority, cooldown, throttle, queue, event grouping,
hardware-beep skip, Focus / Presentation / Quiet Hours modes.
Never blocks the UI thread.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import threading
import time
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

log = logging.getLogger('audio_manager')

# ── Priority ──────────────────────────────────────────────────────────────────
PRIORITY = {
    'critical': 100,
    'high': 75,
    'medium': 50,
    'low': 25,
}

# Default event metadata: priority, category, cooldown_ms
EVENT_META: Dict[str, Dict[str, Any]] = {
    'startup':           {'priority': 'medium', 'category': 'system',   'cooldown_ms': 2000},
    'login_success':     {'priority': 'medium', 'category': 'system',   'cooldown_ms': 500},
    'login_fail':        {'priority': 'high',   'category': 'alerts',   'cooldown_ms': 800},
    'barcode_scan':      {'priority': 'medium', 'category': 'pos',      'cooldown_ms': 80},
    'product_add':       {'priority': 'medium', 'category': 'pos',      'cooldown_ms': 60},
    'product_remove':    {'priority': 'low',    'category': 'pos',      'cooldown_ms': 80},
    'sale_complete':     {'priority': 'high',   'category': 'pos',      'cooldown_ms': 400},
    'void':              {'priority': 'critical','category': 'pos',     'cooldown_ms': 500},
    'payment_cash':      {'priority': 'medium', 'category': 'payments', 'cooldown_ms': 200},
    'payment_mpesa':     {'priority': 'medium', 'category': 'payments', 'cooldown_ms': 200},
    'payment_card':      {'priority': 'medium', 'category': 'payments', 'cooldown_ms': 200},
    'payment_credit':    {'priority': 'medium', 'category': 'payments', 'cooldown_ms': 200},
    'low_stock':         {'priority': 'high',   'category': 'alerts',   'cooldown_ms': 3000,
                          'group': 'low_stock', 'group_ms': 2500},
    'error':             {'priority': 'critical','category': 'alerts',  'cooldown_ms': 5000},
    'warning':           {'priority': 'high',   'category': 'alerts',   'cooldown_ms': 3000},
    'success':           {'priority': 'medium', 'category': 'ui',       'cooldown_ms': 250},
    'ai_thinking':       {'priority': 'low',    'category': 'ai',       'cooldown_ms': 10000},
    'ai_ready':          {'priority': 'low',    'category': 'ai',       'cooldown_ms': 2000},
    'permission_denied': {'priority': 'high',   'category': 'alerts',   'cooldown_ms': 1500},
    'dialog_open':       {'priority': 'low',    'category': 'ui',       'cooldown_ms': 50},
    'dialog_close':      {'priority': 'low',    'category': 'ui',       'cooldown_ms': 50},
    'save':              {'priority': 'medium', 'category': 'ui',       'cooldown_ms': 400},
    'delete':            {'priority': 'high',   'category': 'ui',       'cooldown_ms': 400},
    'nav_switch':        {'priority': 'low',    'category': 'ui',       'cooldown_ms': 120},
    'click':             {'priority': 'low',    'category': 'ui',       'cooldown_ms': 50},
    'notification':      {'priority': 'medium', 'category': 'alerts',   'cooldown_ms': 800},
    'accounting_post':   {'priority': 'medium', 'category': 'system',   'cooldown_ms': 500},
}

# Presentation mode: only these (plus critical)
PRESENTATION_ALLOW = {
    'sale_complete', 'payment_cash', 'payment_mpesa', 'payment_card',
    'payment_credit', 'void', 'error', 'barcode_scan', 'product_add',
}

# Focus mode: mute UI chrome
FOCUS_MUTE_EVENTS = {
    'nav_switch', 'click', 'dialog_open', 'dialog_close', 'ai_thinking', 'ai_ready',
}

THEMES = (
    'professional', 'minimal', 'retail', 'supermarket',
    'pharmacy', 'restaurant', 'warehouse', 'silent',
)

CATEGORIES = ('system', 'pos', 'payments', 'alerts', 'ui', 'ai')

DEFAULT_SETTINGS: Dict[str, Any] = {
    'enabled': True,
    'theme': 'professional',
    'master_volume': 0.75,
    'reduced_mode': False,
    'mute_all': False,
    'focus_mode': False,
    'presentation_mode': False,
    'quiet_hours_enabled': False,
    'quiet_hours_start': '22:00',
    'quiet_hours_end': '07:00',
    'hw_scanner_beep': False,
    'hw_printer_beep': False,
    'hw_drawer_beep': False,
    'hw_card_beep': False,
    'category_volume': {c: 1.0 for c in CATEGORIES},
    'category_mute': {c: False for c in CATEGORIES},
    'event_enabled': {e: True for e in EVENT_META},
    'custom_overrides': {},  # event -> relative path under custom/
}

MAX_CONCURRENT = 2
HISTORY_LEN = 40


def _bundle_root() -> str:
    if getattr(sys, 'frozen', False):
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass and os.path.isdir(os.path.join(meipass, 'assets', 'sounds')):
            return meipass
        exe_dir = os.path.dirname(sys.executable)
        if os.path.isdir(os.path.join(exe_dir, 'assets', 'sounds')):
            return exe_dir
        return meipass or exe_dir
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def sounds_root() -> str:
    return os.path.join(_bundle_root(), 'assets', 'sounds')


def library_root() -> str:
    return os.path.join(sounds_root(), 'library')


def themes_root() -> str:
    return os.path.join(sounds_root(), 'themes')


def _config_dir() -> str:
    try:
        from mbt_paths import get_project_root
        d = os.path.join(get_project_root(), 'config')
    except Exception:
        d = os.path.join(
            os.environ.get('LOCALAPPDATA') or os.path.expanduser('~'),
            'MugoByte', 'MBT POS', 'config')
    os.makedirs(d, exist_ok=True)
    return d


def settings_path() -> str:
    return os.path.join(_config_dir(), 'audio_settings.json')


def custom_sounds_dir() -> str:
    d = os.path.join(_config_dir(), 'audio_custom')
    os.makedirs(d, exist_ok=True)
    return d


def _now_ms() -> float:
    return time.monotonic() * 1000.0


def _parse_hhmm(s: str) -> int:
    try:
        parts = (s or '0:0').strip().split(':')
        return int(parts[0]) * 60 + int(parts[1])
    except Exception:
        return 0


def _in_quiet_hours(start: str, end: str) -> bool:
    from datetime import datetime
    now = datetime.now().hour * 60 + datetime.now().minute
    a, b = _parse_hhmm(start), _parse_hhmm(end)
    if a == b:
        return False
    if a < b:
        return a <= now < b
    return now >= a or now < b


class AudioManager:
    """Thread-safe singleton audio engine."""

    _instance: Optional['AudioManager'] = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst._initialized = False
                cls._instance = inst
            return cls._instance

    @classmethod
    def instance(cls) -> 'AudioManager':
        return cls()

    def __init__(self):
        if getattr(self, '_initialized', False):
            return
        self._initialized = True
        self._settings = dict(DEFAULT_SETTINGS)
        self._settings['category_volume'] = dict(DEFAULT_SETTINGS['category_volume'])
        self._settings['category_mute'] = dict(DEFAULT_SETTINGS['category_mute'])
        self._settings['event_enabled'] = dict(DEFAULT_SETTINGS['event_enabled'])
        self._settings['custom_overrides'] = {}
        self._theme_map: Dict[str, str] = {}
        self._cache: Dict[str, Any] = {}  # path -> QSoundEffect
        self._last_play: Dict[str, float] = {}
        self._group_pending: Dict[str, Dict[str, Any]] = {}
        self._group_timers: Dict[str, Any] = {}
        self._playing: List[Tuple[float, str, int]] = []  # end_ms, event, pri
        self._queue: Deque[Tuple[str, int, dict]] = deque()
        self._history: Deque[dict] = deque(maxlen=HISTORY_LEN)
        self._qt_ready = False
        self._effects_parent = None
        self._diag_listeners: List[Callable] = []
        self._load_settings()
        self._load_theme(self._settings.get('theme') or 'professional')

    # ── Settings I/O ──────────────────────────────────────────────────────────

    def _load_settings(self):
        path = settings_path()
        if not os.path.isfile(path):
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return
            for k, v in data.items():
                if k in ('category_volume', 'category_mute', 'event_enabled', 'custom_overrides'):
                    if isinstance(v, dict):
                        base = self._settings.get(k) or {}
                        base.update(v)
                        self._settings[k] = base
                else:
                    self._settings[k] = v
        except Exception as e:
            log.warning('audio settings load: %s', e)

    def save_settings(self, patch: Optional[dict] = None) -> bool:
        if patch:
            for k, v in patch.items():
                if k in ('category_volume', 'category_mute', 'event_enabled', 'custom_overrides'):
                    if isinstance(v, dict):
                        cur = dict(self._settings.get(k) or {})
                        cur.update(v)
                        self._settings[k] = cur
                else:
                    self._settings[k] = v
        try:
            path = settings_path()
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(self._settings, f, indent=2)
            theme = self._settings.get('theme') or 'professional'
            self._load_theme(theme)
            self._cache.clear()
            return True
        except Exception as e:
            log.warning('audio settings save: %s', e)
            return False

    def get_settings(self) -> dict:
        return json.loads(json.dumps(self._settings))

    def restore_defaults(self) -> bool:
        self._settings = json.loads(json.dumps(DEFAULT_SETTINGS))
        return self.save_settings()

    def set_theme(self, theme: str) -> bool:
        theme = (theme or 'professional').strip().lower()
        if theme not in THEMES:
            theme = 'professional'
        return self.save_settings({'theme': theme})

    def _load_theme(self, theme: str):
        theme = (theme or 'professional').strip().lower()
        path = os.path.join(themes_root(), f'{theme}.json')
        mapping: Dict[str, str] = {}
        if os.path.isfile(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                mapping = dict(data.get('events') or {})
            except Exception as e:
                log.warning('theme load %s: %s', theme, e)
        if theme == 'silent':
            mapping = {e: '' for e in EVENT_META}
        # Fallback: map every event to library/<file>.wav from professional defaults
        if not mapping and theme != 'silent':
            mapping = self._default_event_files()
        self._theme_map = mapping
        self._settings['theme'] = theme

    @staticmethod
    def _default_event_files() -> Dict[str, str]:
        return {
            'startup': 'library/startup.wav',
            'login_success': 'library/login_ok.wav',
            'login_fail': 'library/login_fail.wav',
            'barcode_scan': 'library/barcode.wav',
            'product_add': 'library/product_add.wav',
            'product_remove': 'library/product_remove.wav',
            'sale_complete': 'library/sale_complete.wav',
            'void': 'library/void.wav',
            'payment_cash': 'library/pay_cash.wav',
            'payment_mpesa': 'library/pay_mpesa.wav',
            'payment_card': 'library/pay_card.wav',
            'payment_credit': 'library/pay_credit.wav',
            'low_stock': 'library/low_stock.wav',
            'error': 'library/error.wav',
            'warning': 'library/warning.wav',
            'success': 'library/success.wav',
            'ai_thinking': 'library/ai_thinking.wav',
            'ai_ready': 'library/ai_ready.wav',
            'permission_denied': 'library/permission.wav',
            'dialog_open': 'library/dialog_open.wav',
            'dialog_close': 'library/dialog_close.wav',
            'save': 'library/save.wav',
            'delete': 'library/delete.wav',
            'nav_switch': 'library/nav.wav',
            'click': 'library/click.wav',
            'notification': 'library/notify.wav',
            'accounting_post': 'library/success.wav',
        }

    # ── Resolve path ──────────────────────────────────────────────────────────

    def resolve_path(self, event: str) -> Optional[str]:
        custom = (self._settings.get('custom_overrides') or {}).get(event)
        if custom:
            p = custom if os.path.isabs(custom) else os.path.join(custom_sounds_dir(), custom)
            if os.path.isfile(p):
                return p
        rel = self._theme_map.get(event)
        if not rel:
            return None
        p = rel if os.path.isabs(rel) else os.path.join(sounds_root(), rel.replace('/', os.sep))
        return p if os.path.isfile(p) else None

    def diagnostics(self) -> dict:
        missing = []
        present = []
        for ev in EVENT_META:
            p = self.resolve_path(ev)
            if p:
                present.append({'event': ev, 'path': p})
            else:
                if (self._settings.get('theme') or '') != 'silent':
                    missing.append(ev)
        return {
            'theme': self._settings.get('theme'),
            'master_volume': self._settings.get('master_volume'),
            'mute_all': self._settings.get('mute_all'),
            'focus_mode': self._settings.get('focus_mode'),
            'presentation_mode': self._settings.get('presentation_mode'),
            'quiet_hours': {
                'enabled': self._settings.get('quiet_hours_enabled'),
                'start': self._settings.get('quiet_hours_start'),
                'end': self._settings.get('quiet_hours_end'),
                'active': self._quiet_active(),
            },
            'category_volume': self._settings.get('category_volume'),
            'category_mute': self._settings.get('category_mute'),
            'present': present,
            'missing': missing,
            'history': list(self._history),
            'sounds_root': sounds_root(),
            'settings_path': settings_path(),
        }

    # ── Policy gates ──────────────────────────────────────────────────────────

    def _quiet_active(self) -> bool:
        if not self._settings.get('quiet_hours_enabled'):
            return False
        return _in_quiet_hours(
            self._settings.get('quiet_hours_start') or '22:00',
            self._settings.get('quiet_hours_end') or '07:00')

    def _hardware_skip(self, event: str) -> bool:
        s = self._settings
        if event == 'barcode_scan' and s.get('hw_scanner_beep'):
            return True
        if event in ('sale_complete',) and s.get('hw_printer_beep'):
            # printer beep is separate; still play sale unless drawer/printer flagged for payment
            pass
        if event.startswith('payment_') and s.get('hw_card_beep') and event == 'payment_card':
            return True
        if event == 'sale_complete' and s.get('hw_drawer_beep'):
            # cash drawer hardware beep — skip software sale chime if configured
            return True
        return False

    def _allowed(self, event: str, priority_name: str) -> Tuple[bool, str]:
        if not self._settings.get('enabled', True):
            return False, 'disabled'
        if self._settings.get('mute_all'):
            return False, 'mute_all'
        if self._settings.get('theme') == 'silent':
            return False, 'silent_theme'
        if not (self._settings.get('event_enabled') or {}).get(event, True):
            return False, 'event_disabled'
        meta = EVENT_META.get(event) or {}
        cat = meta.get('category') or 'ui'
        if (self._settings.get('category_mute') or {}).get(cat):
            return False, f'mute_{cat}'
        if self._hardware_skip(event):
            return False, 'hardware_beep'
        if self._settings.get('focus_mode') and event in FOCUS_MUTE_EVENTS:
            return False, 'focus_mode'
        if self._settings.get('presentation_mode'):
            if event not in PRESENTATION_ALLOW and priority_name != 'critical':
                return False, 'presentation_mode'
        if self._quiet_active() and priority_name not in ('critical', 'high'):
            return False, 'quiet_hours'
        if self._settings.get('reduced_mode') and priority_name == 'low':
            return False, 'reduced_mode'
        return True, 'ok'

    def _cooldown_ok(self, event: str, cooldown_ms: int) -> bool:
        last = self._last_play.get(event, 0)
        return (_now_ms() - last) >= max(0, cooldown_ms)

    def _current_max_priority(self) -> int:
        now = _now_ms()
        self._playing = [(e, ev, p) for e, ev, p in self._playing if e > now]
        if not self._playing:
            return 0
        return max(p for _, _, p in self._playing)

    # ── Public API ────────────────────────────────────────────────────────────

    def play(self, event_name: str, **kwargs) -> bool:
        """Play a logical event asynchronously. Never blocks the UI."""
        event = (event_name or '').strip()
        if not event:
            return False
        meta = EVENT_META.get(event) or {
            'priority': 'medium', 'category': 'ui', 'cooldown_ms': 200}
        pri_name = kwargs.get('priority') or meta.get('priority') or 'medium'
        pri = PRIORITY.get(pri_name, 50)
        cooldown = int(kwargs.get('cooldown_ms', meta.get('cooldown_ms', 200)))

        ok, reason = self._allowed(event, pri_name)
        if not ok:
            self._record(event, False, reason)
            return False

        # Event grouping (e.g. many low_stock → one sound)
        group = meta.get('group')
        if group and not kwargs.get('force'):
            self._schedule_group(group, event, int(meta.get('group_ms', 2000)), pri)
            return True

        if not self._cooldown_ok(event, cooldown):
            self._record(event, False, 'cooldown')
            return False

        # Priority: Low never interrupts High+; Critical interrupts all
        cur = self._current_max_priority()
        if pri < PRIORITY['high'] and cur >= PRIORITY['high'] and pri_name != 'critical':
            # queue only one of this event
            self._enqueue_unique(event, pri, kwargs)
            self._record(event, False, 'queued_behind_higher')
            return False
        if pri_name == 'critical' and cur > 0:
            self._stop_all()

        # Concurrent low: discard obsolete duplicates in queue
        if pri_name == 'low' and len(self._playing) >= MAX_CONCURRENT:
            self._record(event, False, 'max_concurrent')
            return False

        path = self.resolve_path(event)
        if not path:
            self._record(event, False, 'missing_file')
            return False

        self._last_play[event] = _now_ms()
        vol = self._volume_for(event, meta.get('category') or 'ui')
        if os.environ.get('MBT_AUDIO_DRY', '').strip() in ('1', 'true', 'yes'):
            self._playing.append((_now_ms() + 50, event, pri))
            self._record(event, True, 'dry_run')
            return True
        scheduled = self._play_async(event, path, vol, pri)
        self._record(event, scheduled, 'play' if scheduled else 'backend_fail')
        return scheduled

    def play_payment(self, method: str) -> bool:
        m = (method or 'cash').strip().lower()
        if 'mpesa' in m or 'm-pesa' in m:
            return self.play('payment_mpesa')
        if 'card' in m:
            return self.play('payment_card')
        if 'credit' in m or 'part payment' in m or 'account' in m:
            return self.play('payment_credit')
        return self.play('payment_cash')

    def preview(self, event_name: str) -> bool:
        """Force-play for Settings preview (bypasses most modes except mute_all)."""
        if self._settings.get('mute_all'):
            return False
        # Temporarily ignore focus/presentation/quiet for preview
        saved = {
            'focus_mode': self._settings.get('focus_mode'),
            'presentation_mode': self._settings.get('presentation_mode'),
            'quiet_hours_enabled': self._settings.get('quiet_hours_enabled'),
        }
        try:
            self._settings['focus_mode'] = False
            self._settings['presentation_mode'] = False
            self._settings['quiet_hours_enabled'] = False
            self._last_play.pop(event_name, None)
            return self.play(event_name, force=True, cooldown_ms=0)
        finally:
            self._settings.update(saved)

    def set_custom_sound(self, event: str, source_path: str) -> Optional[str]:
        if event not in EVENT_META or not os.path.isfile(source_path):
            return None
        ext = os.path.splitext(source_path)[1].lower()
        if ext not in ('.wav', '.ogg', '.mp3'):
            return None
        dest_name = f'{event}{ext}'
        dest = os.path.join(custom_sounds_dir(), dest_name)
        try:
            shutil.copy2(source_path, dest)
            overs = dict(self._settings.get('custom_overrides') or {})
            overs[event] = dest_name
            self.save_settings({'custom_overrides': overs})
            self._cache.clear()
            return dest
        except Exception as e:
            log.warning('custom sound: %s', e)
            return None

    def clear_custom_sound(self, event: str) -> bool:
        overs = dict(self._settings.get('custom_overrides') or {})
        overs.pop(event, None)
        return self.save_settings({'custom_overrides': overs})

    # ── Grouping / queue ──────────────────────────────────────────────────────

    def _schedule_group(self, group: str, event: str, wait_ms: int, pri: int):
        pending = self._group_pending.get(group) or {'count': 0, 'event': event, 'pri': pri}
        pending['count'] = int(pending.get('count') or 0) + 1
        pending['event'] = event
        pending['pri'] = max(int(pending.get('pri') or 0), pri)
        self._group_pending[group] = pending

        def _flush():
            info = self._group_pending.pop(group, None)
            self._group_timers.pop(group, None)
            if not info:
                return
            # Play once for the batch
            ev = info.get('event') or event
            self._last_play.pop(ev, None)
            self.play(ev, force=True)

        # Reset debounce timer
        old = self._group_timers.get(group)
        if old is not None:
            try:
                old.stop()
            except Exception:
                pass
        try:
            from PyQt5.QtCore import QTimer
            t = QTimer()
            t.setSingleShot(True)
            t.timeout.connect(_flush)
            t.start(max(50, wait_ms))
            self._group_timers[group] = t
        except Exception:
            # No Qt yet — flush immediately after wait via thread
            def _late():
                time.sleep(wait_ms / 1000.0)
                _flush()
            threading.Thread(target=_late, daemon=True, name='AudioGroup').start()

    def _enqueue_unique(self, event: str, pri: int, kwargs: dict):
        # Discard obsolete identical events in queue
        self._queue = deque([(e, p, k) for e, p, k in self._queue if e != event])
        self._queue.append((event, pri, kwargs))

    def _drain_queue(self):
        while self._queue:
            if self._current_max_priority() >= PRIORITY['high']:
                break
            event, pri, kwargs = self._queue.popleft()
            self.play(event, **kwargs)

    # ── Playback backends (async) ─────────────────────────────────────────────

    def _volume_for(self, event: str, category: str) -> float:
        master = float(self._settings.get('master_volume') or 0.75)
        cat = float((self._settings.get('category_volume') or {}).get(category, 1.0))
        if self._settings.get('reduced_mode'):
            master *= 0.45
        if self._quiet_active():
            master *= 0.35
        return max(0.0, min(1.0, master * cat))

    def ensure_qt(self, parent=None):
        """Call once from main thread after QApplication exists."""
        self._effects_parent = parent
        self._qt_ready = True

    def _play_async(self, event: str, path: str, volume: float, pri: int) -> bool:
        # Prefer QSoundEffect only when a QApplication + event loop exist
        try:
            from PyQt5.QtWidgets import QApplication
            from PyQt5.QtCore import QTimer, QUrl
            app = QApplication.instance()
            if app is None:
                return self._play_winsound_async(path)
            from PyQt5.QtMultimedia import QSoundEffect

            def _do():
                try:
                    eff = self._cache.get(path)
                    if eff is None:
                        eff = QSoundEffect(self._effects_parent)
                        eff.setSource(QUrl.fromLocalFile(path))
                        self._cache[path] = eff
                    eff.setVolume(max(0.0, min(1.0, volume)))
                    dur_ms = 350
                    self._playing.append((_now_ms() + dur_ms, event, pri))
                    eff.play()
                    QTimer.singleShot(dur_ms + 20, self._drain_queue)
                except Exception as e:
                    log.debug('QSoundEffect fail, fallback: %s', e)
                    self._play_winsound_async(path)

            QTimer.singleShot(0, _do)
            return True
        except Exception:
            return self._play_winsound_async(path)

    def _play_winsound_async(self, path: str) -> bool:
        if sys.platform != 'win32':
            return False
        try:
            import winsound

            def _run():
                try:
                    winsound.PlaySound(
                        path,
                        winsound.SND_FILENAME | winsound.SND_NODEFAULT | winsound.SND_ASYNC | winsound.SND_NOSTOP,
                    )
                except Exception as e:
                    log.debug('winsound: %s', e)

            threading.Thread(target=_run, daemon=True, name='MBTAudio').start()
            return True
        except Exception:
            return False

    def _stop_all(self):
        self._playing.clear()
        for eff in list(self._cache.values()):
            try:
                if hasattr(eff, 'stop'):
                    eff.stop()
            except Exception:
                pass

    def _record(self, event: str, played: bool, reason: str):
        entry = {
            't': time.strftime('%H:%M:%S'),
            'event': event,
            'played': played,
            'reason': reason,
        }
        self._history.appendleft(entry)
        for fn in list(self._diag_listeners):
            try:
                fn(entry)
            except Exception:
                pass

    def list_events(self) -> List[str]:
        return list(EVENT_META.keys())


# Module-level convenience
def play(event_name: str, **kwargs) -> bool:
    return AudioManager.instance().play(event_name, **kwargs)


def get_audio() -> AudioManager:
    return AudioManager.instance()
