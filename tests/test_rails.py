from pathlib import Path

import pandas as pd
import pytest

from treasury.calendar import Calendar
from treasury.rails import arrival_time, load_rails

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def cal() -> Calendar:
    return Calendar.from_yaml(ROOT / "config" / "calendar_ar.yaml")


@pytest.fixture(scope="module")
def rails():
    return load_rails(ROOT / "config" / "rails.yaml")


def test_load_rails_reads_config(rails):
    wire = rails["wire"]
    assert wire.name == "wire"
    assert (wire.lead_time_hours, wire.business_days_only) == (48, True)
    assert (wire.instruct_cutoff_hour, wire.credit_hour) == (15, 10)
    assert (wire.fixed_fee, wire.bps) == (30, 0)
    coin = rails["stablecoin"]
    assert (coin.lead_time_hours, coin.business_days_only) == (0.5, False)
    assert (coin.instruct_cutoff_hour, coin.credit_hour) == (None, None)
    assert (coin.fixed_fee, coin.bps) == (2, 10)


def test_wire_friday_after_cutoff_arrives_wednesday(rails, cal):
    # 2026-11-09 (Mon) is a business day; counting starts there, +2 business days.
    got = arrival_time(rails["wire"], pd.Timestamp("2026-11-06 16:00"), cal)
    assert got == pd.Timestamp("2026-11-11 10:00")


def test_wire_saturday_counts_from_monday(rails, cal):
    got = arrival_time(rails["wire"], pd.Timestamp("2026-11-07 09:00"), cal)
    assert got == pd.Timestamp("2026-11-11 10:00")


def test_wire_business_day_before_cutoff_counts_from_same_day(rails, cal):
    got = arrival_time(rails["wire"], pd.Timestamp("2026-11-09 14:59"), cal)
    assert got == pd.Timestamp("2026-11-11 10:00")


def test_wire_at_cutoff_hour_counts_from_next_day(rails, cal):
    got = arrival_time(rails["wire"], pd.Timestamp("2026-11-09 15:00"), cal)
    assert got == pd.Timestamp("2026-11-12 10:00")


def test_wire_skips_holiday(rails, cal):
    # 2026-11-23 (Mon) is a holiday: Fri 11-20 after cutoff starts Tue 11-24, +2 = Thu 11-26.
    got = arrival_time(rails["wire"], pd.Timestamp("2026-11-20 16:00"), cal)
    assert got == pd.Timestamp("2026-11-26 10:00")


def test_stablecoin_sunday_arrives_in_30_min(rails, cal):
    got = arrival_time(rails["stablecoin"], pd.Timestamp("2026-11-08 22:45"), cal)
    assert got == pd.Timestamp("2026-11-08 23:15")
