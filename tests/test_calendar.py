from datetime import date
from pathlib import Path

import pytest

from treasury.calendar import Calendar

CONFIG = Path(__file__).resolve().parents[1] / "config" / "calendar_ar_2026.yaml"


@pytest.fixture(scope="module")
def cal() -> Calendar:
    return Calendar.from_yaml(CONFIG)


def test_holiday_is_not_business_day(cal):
    assert cal.is_business_day(date(2026, 5, 25)) is False
    assert cal.is_business_day(date(2026, 5, 26)) is True


def test_puentes_are_holidays(cal):
    for d in (date(2026, 3, 23), date(2026, 7, 10), date(2026, 12, 7)):
        assert d in cal.holidays


def test_add_business_days_skips_weekend_and_holiday(cal):
    assert cal.add_business_days(date(2026, 5, 22), 1) == date(2026, 5, 26)


def test_add_business_days_zero_and_negative(cal):
    assert cal.add_business_days(date(2026, 5, 26), 0) == date(2026, 5, 26)
    assert cal.add_business_days(date(2026, 5, 26), -1) == date(2026, 5, 22)


def test_nth_business_day(cal):
    assert cal.nth_business_day_of_month(date(2026, 11, 4)) == 3
    assert cal.nth_business_day_of_month(date(2026, 11, 7)) == 0


def test_business_days_to_month_end(cal):
    # Nov 2026: Mon 23 is a holiday; business days after Wed 25 are 26, 27, 30.
    assert cal.business_days_to_month_end(date(2026, 11, 25)) == 3
    assert cal.business_days_to_month_end(date(2026, 11, 30)) == 0


def test_sac_window(cal):
    assert cal.is_sac_window(date(2026, 6, 30)) is True
    assert cal.is_sac_window(date(2026, 7, 15)) is False


def test_anses_window(cal):
    assert cal.anses_window(date(2026, 3, 10)) is True
    assert cal.anses_window(date(2026, 3, 5)) is False
    assert cal.anses_window(date(2026, 3, 14)) is False  # Saturday inside the range
