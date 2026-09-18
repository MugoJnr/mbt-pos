"""v3.0.99 — UpdateChecker reconnect hysteresis (no false-reconnect storm)."""
from __future__ import annotations

from backend.updater import (
    ONLINE_STABLE_SEC,
    RECONNECT_CHECK_COOLDOWN_SEC,
    next_reconnect_watch_state,
    should_trigger_reconnect_check,
)


def test_flapping_online_never_triggers_reconnect_check():
    """Edmus class: T/F every 30s must not fire reconnect GitHub checks."""
    pending = False
    online_since = None
    last_online = False
    last_check = 0.0
    triggers = 0
    t0 = 1_000_000.0
    for i in range(40):  # ~20 min of 30s slices
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
    assert triggers == 0


def test_stable_reconnect_triggers_once_after_hysteresis():
    pending = False
    online_since = None
    last_online = False
    last_check = 0.0
    t0 = 2_000_000.0
    # offline
    pending, online_since = next_reconnect_watch_state(
        now_online=False, last_online=True, pending_reconnect=False,
        online_since=None, now=t0,
    )
    last_online = False
    # edge online
    now = t0 + 30
    pending, online_since = next_reconnect_watch_state(
        now_online=True, last_online=last_online, pending_reconnect=pending,
        online_since=online_since, now=now,
    )
    assert pending is True
    assert not should_trigger_reconnect_check(
        now_online=True, pending_reconnect=pending, online_since=online_since,
        last_reconnect_check_at=last_check, now=now,
    )
    last_online = True
    # still pending, not yet stable
    now = t0 + 30 + (ONLINE_STABLE_SEC - 10)
    pending, online_since = next_reconnect_watch_state(
        now_online=True, last_online=last_online, pending_reconnect=pending,
        online_since=online_since, now=now,
    )
    assert not should_trigger_reconnect_check(
        now_online=True, pending_reconnect=pending, online_since=online_since,
        last_reconnect_check_at=last_check, now=now,
    )
    # past stable window
    now = t0 + 30 + ONLINE_STABLE_SEC + 1
    assert should_trigger_reconnect_check(
        now_online=True, pending_reconnect=pending, online_since=online_since,
        last_reconnect_check_at=last_check, now=now,
    )
    last_check = now
    pending = False
    # immediate second attempt blocked by cooldown
    now2 = now + 60
    pending2, since2 = next_reconnect_watch_state(
        now_online=True, last_online=False, pending_reconnect=False,
        online_since=None, now=now2,
    )
    assert pending2 is True
    now3 = now2 + ONLINE_STABLE_SEC + 1
    assert not should_trigger_reconnect_check(
        now_online=True, pending_reconnect=pending2, online_since=since2,
        last_reconnect_check_at=last_check, now=now3,
        cooldown_sec=RECONNECT_CHECK_COOLDOWN_SEC,
    )
    # after cooldown
    now4 = last_check + RECONNECT_CHECK_COOLDOWN_SEC + 1
    pending4, since4 = next_reconnect_watch_state(
        now_online=True, last_online=False, pending_reconnect=False,
        online_since=None, now=now4 - ONLINE_STABLE_SEC,
    )
    pending4, since4 = next_reconnect_watch_state(
        now_online=True, last_online=True, pending_reconnect=pending4,
        online_since=since4, now=now4,
    )
    assert should_trigger_reconnect_check(
        now_online=True, pending_reconnect=pending4, online_since=since4,
        last_reconnect_check_at=last_check, now=now4,
    )


def test_ten_minute_flap_budget_max_one_trigger_even_if_stable_window_met_briefly():
    """If online never holds ONLINE_STABLE_SEC, zero triggers in 10 minutes."""
    pending = False
    online_since = None
    last_online = True
    last_check = 0.0
    triggers = 0
    t0 = 3_000_000.0
    for i in range(20):
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
    assert triggers == 0
