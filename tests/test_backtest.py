from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from treasury.backtest import partner_ledger, run, time_weighted_mean
from treasury.harness import default_origins
from treasury.models.seasonal_naive import SeasonalNaive
from treasury.policy import load_policy

CFG = load_policy(Path(__file__).resolve().parents[1] / "config" / "policy.yaml")
END = date(2026, 10, 31)
ORIGINS = default_origins(END, n=3, step_days=7, horizon=14)


def ts(s: str) -> np.datetime64:
    return np.datetime64(pd.Timestamp(f"2026-09-07 {s}").as_unit("ns"))


def test_capital_counts_in_transit_once():
    flow_at = np.array([ts("08:00"), ts("10:00"), ts("12:00")])
    log = partner_ledger(
        100.0, flow_at, np.array([10.0, 20.0, -5.0]),
        instruct_at=np.array([ts("09:00")]), arrival_at=np.array([ts("11:00")]), amounts=np.array([50.0]),
    )
    capital = (log["balance"] + log["in_transit"]).to_numpy()
    landing = int(np.flatnonzero(log["at"] == pd.Timestamp("2026-09-07 11:00"))[0])
    assert capital[landing] == capital[landing - 1]  # the credit moves from in transit to available
    assert log.loc[log["at"] == pd.Timestamp("2026-09-07 09:00"), "in_transit"].item() == 50.0
    assert log["in_transit"].iloc[-1] == 0.0
    assert log["balance"].iloc[-1] == 100.0 - 10 - 20 + 50 + 5
    start, stop = pd.Timestamp("2026-09-07 08:00"), pd.Timestamp("2026-09-07 12:00")
    # 08-09: 90, 09-10: 90 + 50 in transit, 10-11: 70 + 50, 11-12: 120
    assert time_weighted_mean(log["at"], capital, 100.0, start, stop) == pytest.approx((90 + 140 + 120 + 120) / 4)


@pytest.mark.parametrize("policy", ["fixed", "forecast"])
def test_backtest_on_base_data(dataset, policy):
    result = run(dataset, SeasonalNaive if policy == "forecast" else None, policy, "stablecoin", CFG, ORIGINS,
                 central_reserve=1e6, n_paths=200, seed=0)
    m = result.metrics
    for key in ("capital_total_mean", "shortfall_windows", "shortfall_rate", "shortfall_amount_total",
                "shortfall_duration_hours_mean", "n_transfers", "fees", "cost_total", "p_unresolvable_mean"):
        assert key in m
    assert m["rail_used"]["fci_custodian"] == "wire" and m["rail_used"]["cash_network"] == "wire"
    assert m["rail_used"]["crypto_exchange"] == "stablecoin" and m["rail_used"]["card_network"] == "stablecoin"
    assert m["capital_total_mean"] > 1e6 and 0 <= m["shortfall_rate"] <= 1
    assert m["warmup_days"] == 4  # start Sunday 10-04: Monday's wire lands Wednesday 10-07 10:00
    assert m["n_days"] == 21 - 4 and m["shortfall_windows"] <= 6 * m["n_days"]
    evaluated = result.decisions[result.decisions["at"] >= pd.Timestamp("2026-10-08")]
    assert m["n_transfers"] == int((evaluated["amount"] > 0).sum()) > 0
    wire = result.decisions[result.decisions["rail_used"] == "wire"]
    assert (wire["at"].dt.hour == 9).all() and (wire["at"].dt.day_of_week < 5).all()
    coin = result.decisions[result.decisions["rail_used"] == "stablecoin"]
    assert set(coin["at"].dt.hour) == {9, 18}
    if policy == "forecast":
        assert 0 <= m["p_unresolvable_mean"] <= 1
        assert (result.decisions["window_end"] > result.decisions["arrival_at"]).all()
    else:
        assert np.isnan(m["p_unresolvable_mean"])
    k = CFG.cost_of_capital_annual * m["capital_total_mean"] * m["n_days"] / 365
    assert m["cost_total"] == pytest.approx(k + m["fees"] + CFG.cost_per_usd_rejected * m["shortfall_amount_total"])


def test_ledger_log_reconciles_with_events(dataset):
    result = run(dataset, None, "fixed", "wire", CFG, ORIGINS, central_reserve=0.0)
    start, stop = pd.Timestamp(ORIGINS[0]), pd.Timestamp(ORIGINS[-1]) + pd.Timedelta(days=7)
    ev = dataset.events
    ev = ev[(ev["partner"] == "card_network") & (ev["settle_at"] >= start) & (ev["settle_at"] < stop)]
    drained = (ev["amount"] * ev["direction"]).sum()
    log = result.ledger_log[result.ledger_log["partner"] == "card_network"]
    first = result.decisions[result.decisions["partner"] == "card_network"]
    landed = first.loc[first["arrival_at"] < stop, "amount"].sum()
    assert log["balance"].iloc[-1] == pytest.approx(result.initial["card_network"] + landed - drained)


def test_higher_alpha_holds_more_capital(dataset):
    lo = run(dataset, SeasonalNaive, "forecast", "stablecoin", replace(CFG, alpha=0.5), ORIGINS, 0.0, n_paths=200)
    hi = run(dataset, SeasonalNaive, "forecast", "stablecoin", replace(CFG, alpha=0.995), ORIGINS, 0.0, n_paths=200)
    assert hi.metrics["capital_total_mean"] > lo.metrics["capital_total_mean"]
    assert hi.metrics["shortfall_rate"] <= lo.metrics["shortfall_rate"]


def test_warmup_windows_are_reported_apart(dataset):
    default = run(dataset, None, "fixed", "wire", CFG, ORIGINS).metrics
    full = run(dataset, None, "fixed", "wire", CFG, ORIGINS, warmup_days=0).metrics
    assert full["n_days"] == 21 and full["warmup_shortfall_windows"] == 0
    assert full["shortfall_windows"] == default["shortfall_windows"] + default["warmup_shortfall_windows"]
    assert full["shortfall_amount_total"] == pytest.approx(
        default["shortfall_amount_total"] + default["warmup_shortfall_amount"]
    )
