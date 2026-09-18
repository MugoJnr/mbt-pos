#!/usr/bin/env python3
"""10-minute UpdateChecker flap soak (v3.0.99).

Drives a flapping is_online getter and counts reconnect-triggered log lines.
Exit 0 if reconnect triggers stay within debounce budget.

Usage:
  C:\\MBT_Build\\_python311\\python.exe scripts\\qa_updater_flap_soak.py [--seconds 120]
"""
from __future__ import annotations

import argparse
import logging
import sys
import threading
import time

# Project root
sys.path.insert(0, r'C:\MBT_Build\mbt_pos')

from backend.updater import (  # noqa: E402
    FIRST_CHECK_DELAY,
    UpdateChecker,
    next_reconnect_watch_state,
    should_trigger_reconnect_check,
)


class _CountingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.reconnect = 0
        self.checks = 0

    def emit(self, record: logging.LogRecord) -> None:
        msg = record.getMessage()
        if 'Internet reconnected' in msg:
            self.reconnect += 1
        if 'Update check starting' in msg:
            self.checks += 1


def simulate_logic_only(seconds: int) -> int:
    """Fast pure-logic soak (no threads): flap every 30s of virtual time."""
    pending = False
    online_since = None
    last_online = False
    last_check = 0.0
    triggers = 0
    t0 = time.time()
    slices = max(1, seconds // 30)
    for i in range(slices):
        now = t0 + i * 30
        now_online = (i % 2 == 0)
        pending, online_since = next_reconnect_watch_state(
            now_online=now_online,
            last_online=last_online,
            pending_reconnect=pending,
            online_since=online_since,
            now=now,
        )
        if should_trigger_reconnect_check(
            now_online=now_online,
            pending_reconnect=pending,
            online_since=online_since,
            last_reconnect_check_at=last_check,
            now=now,
        ):
            triggers += 1
            last_check = now
            pending = False
        last_online = now_online
    return triggers


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--seconds', type=int, default=120)
    ap.add_argument('--live-thread', action='store_true',
                    help='Also start UpdateChecker thread (slow; needs FIRST_CHECK_DELAY)')
    args = ap.parse_args()

    triggers = simulate_logic_only(args.seconds)
    print(f'logic_flap_reconnect_triggers={triggers} window_sec={args.seconds}')
    if triggers > 1:
        print('FAIL: flap produced more than one reconnect trigger')
        return 1

    if args.live_thread:
        handler = _CountingHandler()
        logging.getLogger('backend.updater').addHandler(handler)
        logging.getLogger('backend.updater').setLevel(logging.INFO)
        state = {'n': 0}

        def online():
            state['n'] += 1
            return (state['n'] % 2) == 0

        # Patch first-check delay for soak
        import backend.updater as up
        old = up.FIRST_CHECK_DELAY
        up.FIRST_CHECK_DELAY = 2
        checker = UpdateChecker('3.0.99', is_online_getter=online)
        checker._fetch_release_info = lambda: None  # type: ignore
        checker.start()
        time.sleep(max(15, min(args.seconds, 90)))
        checker._stop.set()
        up.FIRST_CHECK_DELAY = old
        print(
            f'live_reconnect_logs={handler.reconnect} '
            f'live_check_starts={handler.checks}'
        )
        if handler.reconnect > 1:
            print('FAIL: live reconnect storm')
            return 1

    print('PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
