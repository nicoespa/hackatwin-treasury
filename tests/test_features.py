from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from treasury.calendar import Calendar
from treasury.features import build_drivers, calendar_features
from treasury.simulate.population import PAYDAY_HYPOTHESES
from treasury.simulate.scenarios import Campaign, CohortWave

ROOT = Path(__file__).resolve().parents[1]
SEGMENTS = ("salaried_formal", "informal")


@pytest.fixture(scope="module")
def cal() -> Calendar:
    return Calendar.from_yaml(ROOT / "config" / "calendar_ar.yaml")


def test_calendar_features_payday_mass(cal):
    dates = pd.date_range("2025-11-01", "2026-01-31", freq="D")
    feats = calendar_features(dates, cal)
    assert list(feats.columns) == [
        "date", "dow", "dom", "bd_index", "bd_to_month_end", "is_business_day", "is_holiday",
        "is_sac_window", "is_anses_window", "payday_mass", "is_first_bd", "is_last_bd",
    ]
    assert (feats["date"] == dates).all()
    late = PAYDAY_HYPOTHESES["late"]
    for k in range(1, 5):
        assert (feats.loc[feats["bd_index"] == k, "payday_mass"] == late[k - 1]).all()
    assert (feats.loc[~feats["bd_index"].between(1, 4), "payday_mass"] == 0).all()
    # the hypothesis puts all of each month's salary mass on its first four business days
    by_month = feats.groupby(feats["date"].dt.to_period("M"))
    assert np.allclose(by_month["payday_mass"].sum(), 1.0)
    assert (by_month["is_first_bd"].sum() == 1).all() and (by_month["is_last_bd"].sum() == 1).all()
    # 2025-11-01 is a Saturday, 2025-11-03 the first business day; 2025-12-08 is a weekday holiday
    row = feats.set_index("date")
    assert row.loc["2025-11-01", "bd_index"] == 0 and row.loc["2025-11-01", "payday_mass"] == 0
    assert row.loc["2025-11-03", "is_first_bd"] and row.loc["2025-11-03", "payday_mass"] == late[0]
    assert row.loc["2025-12-08", "is_holiday"] and not row.loc["2025-12-08", "is_business_day"]
    assert row.loc["2025-11-28", "is_last_bd"]
    uniform = calendar_features(dates, cal, payday_hypothesis="uniform")
    assert (uniform.loc[uniform["bd_index"].between(1, 4), "payday_mass"] == 0.25).all()


def _users() -> pd.DataFrame:
    activation = ["2025-10-01", "2025-11-10", "2025-11-20", "2025-12-15", "2025-11-05"]
    return pd.DataFrame(
        {
            "user_id": range(5),
            "segment": [SEGMENTS[0]] * 4 + [SEGMENTS[1]],
            "activation_date": pd.to_datetime(activation),
        }
    )


def _events(rng: np.random.Generator) -> pd.DataFrame:
    n = 400
    at = pd.Timestamp("2025-11-01") + pd.to_timedelta(rng.integers(0, 60 * 24 * 60, n), unit="min")
    product = rng.choice(["bill_payment", "card_purchase", "card_refund"], n)
    partner = np.where(product == "bill_payment", "bills_aggregator", "card_network")
    confirmed = (product == "bill_payment") & (rng.random(n) < 0.5)
    return pd.DataFrame(
        {
            "at": at,
            "user_id": rng.integers(0, 5, n),
            "segment": rng.choice(SEGMENTS, n),
            "product": product,
            "amount": np.round(rng.lognormal(6, 1, n), 2),
            "confirmed": confirmed,
            "counterparty": np.where(confirmed, "c", ""),
            "partner": partner,
            "settle_at": at + pd.Timedelta(days=1),
            "direction": np.where(product == "card_refund", -1, 1).astype(np.int8),
        }
    )


def test_drivers_no_leakage():
    dates = pd.date_range("2025-11-01", "2025-12-31", freq="D")
    users, events = _users(), _events(np.random.default_rng(0))
    base = build_drivers(users, events, dates)
    unconfirmed = ~events["confirmed"]

    # build_drivers never reads the amount of an unconfirmed event
    inflated = events.assign(amount=events["amount"].where(~unconfirmed, events["amount"] * 10))
    pd.testing.assert_frame_equal(build_drivers(users, inflated, dates), base)

    # dropping or rescaling unconfirmed events after as_of leaves every later row unchanged
    as_of = pd.Timestamp("2025-12-01")
    late = unconfirmed & (events["at"] >= as_of)
    pd.testing.assert_frame_equal(build_drivers(users, events[~late], dates), base)

    confirmed = events[events["confirmed"] & (events["direction"] == 1)]
    expected = confirmed.groupby(confirmed["settle_at"].dt.normalize())["amount"].sum()
    got = base.set_index("date")["confirmed_bills_aggregator"]
    assert got.sum() == pytest.approx(expected.sum())
    assert got.reindex(expected.index).to_numpy() == pytest.approx(expected.to_numpy())
    assert (base["confirmed_card_network"] == 0).all()


def test_drivers_cohorts_and_campaigns():
    dates = pd.date_range("2025-11-01", "2025-12-31", freq="D")
    campaign = Campaign(date(2025, 12, 1), date(2025, 12, 7), ("card_purchase",), 1.5)
    drivers = build_drivers(
        _users(), _events(np.random.default_rng(1)), dates, scenarios=(campaign, CohortWave(date(2025, 12, 1), 9, "x"))
    )
    assert drivers["date"].tolist() == dates.tolist()
    row = drivers.set_index("date")
    assert row.loc["2025-11-09", "n_active_salaried_formal"] == 1
    assert row.loc["2025-11-20", "n_active_salaried_formal"] == 3
    assert row.loc["2025-12-31", "n_active_salaried_formal"] == 4
    assert row.loc["2025-11-04", "n_active_informal"] == 0 and row.loc["2025-11-05", "n_active_informal"] == 1
    # n_new_30d counts activations in (date - 30, date]
    assert row.loc["2025-11-20", "n_new_30d_salaried_formal"] == 2
    assert row.loc["2025-12-15", "n_new_30d_salaried_formal"] == 2
    assert row.loc["2025-12-20", "n_new_30d_salaried_formal"] == 1
    assert row.loc["2025-12-01":"2025-12-07", "campaign_lift_card_purchase"].eq(1.5).all()
    assert row.loc["2025-12-08", "campaign_lift_card_purchase"] == 1.0
    assert row["campaign_lift_bill_payment"].eq(1.0).all()
