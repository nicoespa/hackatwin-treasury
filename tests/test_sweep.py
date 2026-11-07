import numpy as np
import pandas as pd

from treasury.policy import Decision, PolicyConfig, recommend_sweep, rest_of_day_need
from treasury.rails import Rail
from treasury.routing import Partner

CFG = PolicyConfig(alpha=0.99, cost_of_capital_annual=0.12, cost_per_usd_rejected=0.05, lot_size=1000, review_hour=9,
                   fixed_buffer_days=5, sweep=True, sweep_headroom=1.0, sweep_min_share=1.0)
FAST = Rail("stablecoin", 0.5, False, None, None, 2, 10)
BANK = Rail("wire", 48, True, 15, 10, 30, 0)


def _decision(amount=0.0, target=100_000.0):
    return Decision(amount, 0.0, target, 0.0, None, None)


def test_sweeps_only_the_surplus_above_twice_the_need():
    assert recommend_sweep(_decision(), 350_500, FAST, CFG) == 150_000  # keeps 2 × 100k, floors to the lot


def test_no_sweep_when_small_on_bank_rails_or_when_depositing():
    assert recommend_sweep(_decision(), 250_000, FAST, CFG) == 0  # surplus 50k < 100 % of the target
    assert recommend_sweep(_decision(), 900_000, BANK, CFG) == 0  # banks are closed at night and on weekends
    assert recommend_sweep(_decision(amount=5_000), 900_000, FAST, CFG) == 0


def test_rest_of_day_keeps_what_can_still_settle_today():
    assert recommend_sweep(_decision(target=0.0), 120_000, FAST, CFG, rest_of_day=50_000) == 20_000
    realtime = Partner("p", ("x",), 0, 23, True, False, ("stablecoin",))
    lagged = Partner("q", ("y",), 1, 17, False, False, ("stablecoin",))
    paths = np.full(1000, 240.0)
    assert rest_of_day_need(paths, realtime, pd.Timestamp("2026-10-16 18:00"), 0.99) == 60.0  # 6 of 24 hours left
    assert rest_of_day_need(paths, lagged, pd.Timestamp("2026-10-16 15:00"), 0.99) == 240.0  # before the cutoff
    assert rest_of_day_need(paths, lagged, pd.Timestamp("2026-10-16 18:00"), 0.99) == 0.0
