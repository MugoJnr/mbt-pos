"""Live proof that clicking the MBT POS icon twice behaves for a real shop.

Run against a source tree or an installed build:
    python scripts/_verify_single_instance_live.py
    python scripts/_verify_single_instance_live.py "C:\\Program Files\\MugoByte\\MBT POS\\MBT_POS.exe"
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

user32 = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
WARN_TITLE = 'MBT POS Is Already Running'


def _windows_of(pid):
    found = []

    def cb(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, buf, 512)
            found.append((hwnd, buf.value))
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return found


def _any_window_titled(text):
    hits = []

    def cb(hwnd, _):
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        if text.lower() in buf.value.lower():
            hits.append(buf.value)
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return hits


def _wait_for_window(proc, timeout=60.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return None, time.time()
        wins = _windows_of(proc.pid)
        if wins:
            return wins[0], time.time()
        time.sleep(0.05)
    return None, time.time()


def _launch(command, env=None):
    return subprocess.Popen(
        command, cwd=os.path.dirname(command[0]) or ROOT,
        env=env or os.environ.copy(),
    )


def _kill_all():
    for image in ('MBT_POS.exe',):
        subprocess.run(['taskkill', '/F', '/IM', image],
                       capture_output=True)
    time.sleep(1.5)


def main() -> int:
    env = os.environ.copy()
    env.pop('QT_QPA_PLATFORM', None)  # a real shop has a real screen

    if len(sys.argv) > 1:
        command = [sys.argv[1]]
    else:
        command = [sys.executable, os.path.join(ROOT, 'launcher.py')]

    failures = []
    _kill_all()

    # ---- Case 1: second click once the window is up -> raise it, no dialog.
    first = _launch(command, env)
    (win, _) = _wait_for_window(first, timeout=90)
    if not win:
        print('FAIL first instance never showed a window')
        first.kill()
        return 1
    hwnd, title = win
    print(f'first instance pid={first.pid} window={hwnd:#x} title={title!r}')
    time.sleep(2.0)

    user32.SetForegroundWindow(user32.GetDesktopWindow())
    second = _launch(command, env)
    second.wait(timeout=90)
    time.sleep(1.5)

    if second.returncode != 0:
        failures.append(f'second click exited {second.returncode}, expected 0')
    if first.poll() is not None:
        failures.append('second click killed the running instance')
    warned = _any_window_titled(WARN_TITLE)
    if warned:
        failures.append(f'second click showed the stuck dialog: {warned}')
    fg = user32.GetForegroundWindow()
    fg_owner = wintypes.DWORD()
    user32.GetWindowThreadProcessId(fg, ctypes.byref(fg_owner))
    if fg_owner.value != first.pid:
        failures.append(
            f'running window was not raised (foreground pid {fg_owner.value})')
    else:
        print('second click raised the existing window')

    survivors = subprocess.run(
        ['tasklist', '/FI', 'IMAGENAME eq MBT_POS.exe'],
        capture_output=True, text=True).stdout
    print('running copies:\n' + survivors.strip())

    first.kill()
    _kill_all()

    # ---- Case 2: impatient double click during startup -> silence.
    third = _launch(command, env)
    time.sleep(0.4)  # still booting, no window yet
    fourth = _launch(command, env)
    fourth.wait(timeout=90)
    if fourth.returncode != 0:
        failures.append(f'click during startup exited {fourth.returncode}')
    warned = _any_window_titled(WARN_TITLE)
    if warned:
        failures.append(
            f'click during startup showed the stuck dialog: {warned}')
    else:
        print('click during startup stayed silent')

    (win2, _) = _wait_for_window(third, timeout=90)
    if not win2:
        failures.append('startup was blocked by the extra click')
    else:
        print(f'first instance still opened normally: window={win2[0]:#x}')
    third.kill()
    _kill_all()

    print()
    if failures:
        for f in failures:
            print('FAIL ' + f)
        return 1
    print('PASS single-instance behaviour verified')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
