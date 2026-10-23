"""Sale-date caption: Today, backdated, and future."""
from datetime import date

from desktop.utils.shop_time import sale_day_caption


TODAY = date(2026, 10, 17)


def test_today_is_the_word_today():
    text, tone = sale_day_caption(TODAY, today=TODAY)
    assert text == "Today"
    assert tone == "today"


def test_yesterday_is_red_backdated_label():
    text, tone = sale_day_caption(date(2026, 10, 16), today=TODAY)
    assert text == "16 Oct 2026 — BACKDATED"
    assert tone == "backdated"


def test_future_is_future_label():
    text, tone = sale_day_caption(date(2026, 10, 18), today=TODAY)
    assert text == "18 Oct 2026 — FUTURE DATE"
    assert tone == "future"


def test_returning_to_today_clears_the_warning():
    text, tone = sale_day_caption(date(2026, 10, 17), today=TODAY)
    assert text == "Today"
    assert tone == "today"


def test_midnight_boundary_uses_the_passed_business_day():
    text, tone = sale_day_caption(date(2026, 10, 18), today=date(2026, 10, 18))
    assert text == "Today"
    assert tone == "today"
