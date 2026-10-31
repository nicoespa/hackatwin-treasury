from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from treasury.calendar import Calendar
from treasury.ledger import Credit
from treasury.policy import (
    fixed_buffer_decision,
    load_policy,
    next_review,
    recommend_deposit,
    review_times,
    target_balance,
)
from treasury.rails import load_rails
from treasury.routing import Partner

CONFIG = Path(__file__).resolve().parents[1] / "config"
CAL = Calendar.from_yaml(CONFIG / "calendar_ar.yaml")
RAILS = load_rails(CONFIG / "rails.yaml")
CFG = load_policy(CONFIG / "policy.yaml")
DAILY = 100_000.0
DATES = pd.date_range("2026-09-07", periods=14, freq="D")  # Monday; no holiday before 10-12
PARTNER = Partner("p", ("x",), 0, 15, True, False, ("wire", "stablecoin"))


def _drain(n_paths: int = 20) -> np.ndarray:
    return np.full((n_paths, len(DATES)), DAILY)


def _decide(rail: str, review_at: str, opening: float, partner: Partner = PARTNER, **kw):
    return recommend_deposit(
        _drain(), DATES, partner, RAILS[rail], opening, kw.pop("pending", []), pd.Timestamp(review_at), CAL, CFG, **kw
    )


def test_policy_config_values():
    assert (CFG.alpha, CFG.cost_of_capital_annual, CFG.cost_per_usd_rejected) == (0.99, 0.12, 0.05)
    assert (CFG.lot_size, CFG.review_hour, CFG.fixed_buffer_days) == (1000, 9, 5)


def test_target_balance_is_quantile():
    samples = np.random.default_rng(0).gamma(2.0, 50.0, 10_000)
    assert target_balance(samples, 0.95) == pytest.approx(np.quantile(samples, 0.95))
    assert target_balance(samples, 0.99) > target_balance(samples, 0.90)


def test_recommend_deposit_flags_unresolvable_when_shortfall_before_arrival():
    # Monday 09:00 by wire lands Wednesday 10:00: Monday, Tuesday and Wednesday drain before it.
    short = _decide("wire", "2026-09-07 09:00", opening=2 * DAILY)
    assert short.p_unresolvable == 1.0
    assert short.arrival_at == pd.Timestamp("2026-09-09 10:00")
    assert short.window_end == pd.Timestamp("2026-09-10 10:00")
    assert short.amount == 2 * DAILY  # Thursday plus the deficit carried into the arrival
    covered = _decide("wire", "2026-09-07 09:00", opening=3 * DAILY)
    assert covered.p_unresolvable == 0.0
    assert covered.amount == DAILY
    assert covered.target == 4 * DAILY
    assert covered.expected_shortfall_if_none == pytest.approx(DAILY)
    pending = _decide("wire", "2026-09-07 09:00", opening=3 * DAILY, pending=[Credit(pd.Timestamp("2026-09-08 10:00"), DAILY)])
    assert pending.amount == 0 and pending.expected_shortfall_if_none == 0


def test_monday_accumulates_weekend_for_wire():
    # Wednesday's wire lands Friday 10:00 and must carry Saturday, Sunday and Monday (Monday's
    # drain is placed at 00:00, before Monday's own wire lands at 10:00).
    wednesday = _decide("wire", "2026-09-09 09:00", opening=3 * DAILY)
    assert wednesday.p_unresolvable == 0.0
    assert wednesday.amount == 3 * DAILY
    assert wednesday.amount == 3 * _decide("wire", "2026-09-07 09:00", opening=3 * DAILY).amount
    short = _decide("wire", "2026-09-09 09:00", opening=2.5 * DAILY)
    assert short.p_unresolvable == 1.0  # Friday's drain at 00:00 is not covered
    # A stablecoin partner reviewed twice daily goes into Friday with one day and refills at 18:00.
    morning = _decide("stablecoin", "2026-09-11 09:00", opening=DAILY)
    assert morning.p_unresolvable == 0.0 and morning.amount == 0
    assert morning.target < 1.5 * DAILY
    evening = _decide("stablecoin", "2026-09-11 18:00", opening=0.0, realized_today=DAILY)
    assert evening.window_end == pd.Timestamp("2026-09-12 09:30")
    assert evening.p_unresolvable == 0.0 and evening.amount == DAILY


def test_inflows_of_netting_partner_offset_later_days():
    netting = replace(PARTNER, nets_inflows=True)
    inflow = np.full(len(DATES), DAILY / 2)
    gross = _decide("wire", "2026-09-09 09:00", opening=3 * DAILY, partner=netting)
    net = _decide("wire", "2026-09-09 09:00", opening=3 * DAILY, partner=netting, inflow_forecast=inflow)
    assert gross.amount == 3 * DAILY
    assert net.amount == DAILY  # Fri/Sat/Sun inflows at 15:00 offset the weekend; Monday's lands after the window


def test_alpha_quantile_of_path_amounts():
    rng = np.random.default_rng(3)
    paths = rng.uniform(0.5, 1.5, (2000, len(DATES))) * DAILY
    args = (DATES, PARTNER, RAILS["wire"], 3 * DAILY, [], pd.Timestamp("2026-09-07 09:00"), CAL)
    low = recommend_deposit(paths, *args, replace(CFG, alpha=0.5))
    high = recommend_deposit(paths, *args, replace(CFG, alpha=0.99))
    assert high.amount > low.amount and high.amount % CFG.lot_size == 0


def test_fixed_buffer_tops_up_to_days_of_mean():
    assert fixed_buffer_decision(DAILY, 3, 1.2 * DAILY, 1000).amount == 1.8 * DAILY
    assert fixed_buffer_decision(DAILY, 3, 4 * DAILY, 1000).amount == 0
    assert fixed_buffer_decision(DAILY, 3, 0.0, 1000).target == 3 * DAILY


def test_review_cadence():
    wire, coin = RAILS["wire"], RAILS["stablecoin"]
    start, stop = pd.Timestamp("2026-10-09"), pd.Timestamp("2026-10-14")  # Fri .. Tue, Monday 10-12 is a holiday
    assert review_times(wire, start, stop, CAL, CFG) == [pd.Timestamp("2026-10-09 09:00"), pd.Timestamp("2026-10-13 09:00")]
    assert len(review_times(coin, start, stop, CAL, CFG)) == 10
    assert next_review(coin, pd.Timestamp("2026-10-09 09:00"), CFG) == pd.Timestamp("2026-10-09 18:00")
    assert next_review(coin, pd.Timestamp("2026-10-09 18:00"), CFG) == pd.Timestamp("2026-10-10 09:00")
    assert next_review(wire, pd.Timestamp("2026-10-09 09:00"), CFG) == pd.Timestamp("2026-10-10 09:00")


@pytest.mark.parametrize(
    ("friday", "arrival", "window_end"),
    [
        ("2026-09-04", "2026-09-08 10:00", "2026-09-09 10:00"),
        ("2026-10-09", "2026-10-14 10:00", "2026-10-15 10:00"),  # Monday 10-12 is a holiday
    ],
)
def test_friday_wire_lands_after_the_weekend(friday, arrival, window_end):
    dates = pd.date_range(friday, periods=14, freq="D")
    decision = recommend_deposit(
        np.full((5, 14), DAILY), dates, PARTNER, RAILS["wire"], 0.0, [], pd.Timestamp(f"{friday} 09:00"), CAL, CFG
    )
    assert decision.arrival_at == pd.Timestamp(arrival)
    assert decision.window_end == pd.Timestamp(window_end)
    assert decision.p_unresolvable == 1.0
