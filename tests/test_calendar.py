from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from treasury.calendar import Calendar

CONFIG = Path(__file__).resolve().parents[1] / "config" / "calendar_ar.yaml"


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
    # After Fri 2026-11-20: 24, 25, 26, 27, 30; Mon 23 (Soberanía) is skipped.
    assert cal.business_days_to_month_end(date(2026, 11, 20)) == 5
    assert cal.business_days_to_month_end(date(2026, 11, 30)) == 0


def test_sac_window(cal):
    assert cal.is_sac_window(date(2026, 6, 30)) is True
    assert cal.is_sac_window(date(2026, 7, 15)) is False


def test_anses_window(cal):
    assert cal.anses_window(date(2026, 3, 10)) is True
    assert cal.anses_window(date(2026, 3, 5)) is False
    assert cal.anses_window(date(2026, 3, 14)) is False  # Saturday inside the range


def test_2025_holiday_is_not_business_day(cal):
    assert cal.is_business_day(date(2025, 12, 8)) is False
    assert cal.is_business_day(date(2025, 11, 21)) is False


def test_timestamp_input_behaves_like_date(cal):
    assert cal.is_business_day(pd.Timestamp("2026-05-25")) is False


@pytest.mark.parametrize("outside", [date(2025, 10, 31), date(2027, 1, 1)])
def test_out_of_coverage_raises(cal, outside):
    calls = [
        cal.is_business_day,
        lambda d: cal.add_business_days(d, 1),
        cal.nth_business_day_of_month,
        cal.business_days_to_month_end,
        cal.is_sac_window,
        cal.anses_window,
    ]
    for call in calls:
        with pytest.raises(ValueError, match=outside.isoformat()):
            call(outside)


def test_add_business_days_result_out_of_coverage_raises(cal):
    with pytest.raises(ValueError, match="2027-01-01"):
        cal.add_business_days(date(2026, 12, 31), 1)
