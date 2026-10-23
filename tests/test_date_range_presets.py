"""Dashboard period presets cover a whole week and a whole month."""
from datetime import date

from desktop.utils.option_lists import date_range_for_preset


def test_single_day_presets():
    today = date(2026, 10, 16)
    assert date_range_for_preset("today", today) == (today, today)
    assert date_range_for_preset("yesterday", today) == (date(2026, 10, 15), date(2026, 10, 15))


def test_week_is_monday_through_sunday():
    today = date(2026, 10, 16)  # Friday
    start, end = date_range_for_preset("week", today)
    assert start == date(2026, 10, 12)
    assert end == date(2026, 10, 18)
    assert start.weekday() == 0
    assert end.weekday() == 6


def test_month_is_the_whole_calendar_month():
    today = date(2026, 10, 16)
    assert date_range_for_preset("month", today) == (date(2026, 10, 1), date(2026, 10, 31))
    assert date_range_for_preset("last_month", today) == (date(2026, 9, 1), date(2026, 9, 30))
