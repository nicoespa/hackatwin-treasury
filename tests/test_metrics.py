import numpy as np
import pandas as pd
import pytest
from scipy import stats

from treasury.metrics import coverage, crps_from_quantiles, pinball, pit, pit_ks, wape
from treasury.models.base import QCOLS, QUANTILES, daily_node_table, daily_partner_table, enforce_quantiles


def _gaussian_quantiles(n: int) -> pd.DataFrame:
    return pd.DataFrame(np.tile(stats.norm.ppf(QUANTILES), (n, 1)), columns=list(QCOLS))


def test_pit_uniform_for_calibrated_gaussian():
    y = np.random.default_rng(0).standard_normal(2000)
    assert pit_ks(pit(y, _gaussian_quantiles(len(y)))) < 0.05


def test_pit_detects_overconfident_forecast():
    y = 3 * np.random.default_rng(1).standard_normal(2000)
    assert pit_ks(pit(y, _gaussian_quantiles(len(y)))) > 0.2


def test_pit_tails_and_point_mass():
    q = pd.DataFrame([[1.0, 2, 3, 4, 5, 6, 7, 8], [0.0] * 8], columns=list(QCOLS))
    assert pit(np.array([9.0, 0.0]), q) == pytest.approx([1.0, (0.0 + 0.99) / 2])
    assert pit(np.array([4.5, -0.5]), q) == pytest.approx([(0.50 + 0.75) / 2, 0.0])
    # below q05 the first grid segment is extrapolated down to probability 0
    assert pit(np.array([0.5, -1.0]), q.iloc[[0, 0]]) == pytest.approx([0.025, 0.0])


def test_pinball_known_value():
    y = np.array([1.0, 2.0, 3.0])
    assert pinball(y, np.full(3, 2.0), 0.9) == pytest.approx((0.1 + 0.0 + 0.9) / 3)
    assert pinball(y, np.full(3, 2.0), 0.5) == pytest.approx((0.5 + 0.0 + 0.5) / 3)


def test_crps_is_zero_for_a_perfect_point_mass_and_grows_with_error():
    q = pd.DataFrame([[5.0] * 8], columns=list(QCOLS))
    assert crps_from_quantiles(np.array([5.0]), q) == 0.0
    assert crps_from_quantiles(np.array([7.0]), q) == pytest.approx(2 * np.mean([t * 2 for t in QUANTILES]))


def test_wape_and_coverage_known_values():
    y = np.array([10.0, 20.0, 30.0])
    assert wape(y, np.array([12.0, 18.0, 30.0])) == pytest.approx(4 / 60)
    assert coverage(y, np.array([0.0, 21.0, 30.0]), np.array([10.0, 25.0, 31.0])) == pytest.approx(2 / 3)


def test_daily_node_table_dense_and_sums():
    ts = pd.Timestamp
    events = pd.DataFrame(
        {
            "settle_at": [ts("2026-01-01 10:00"), ts("2026-01-01 15:00"), ts("2026-01-01 16:00"), ts("2026-01-03 09:00")],
            "segment": ["salaried", "salaried", "salaried", "gig"],
            "product": ["card_purchase", "card_purchase", "card_refund", "cash_out"],
            "partner": ["card_network", "card_network", "card_network", "cash_network"],
            "amount": [100.0, 50.0, 30.0, 70.0],
            "confirmed": [True, False, True, True],
            "direction": np.array([1, 1, -1, 1], dtype="int8"),
        }
    )
    nodes = daily_node_table(events)
    assert list(nodes.columns) == ["date", "segment", "product", "partner", "outflow", "inflow", "confirmed_outflow"]
    assert len(nodes) == 3 * 3  # three nodes, dense over 2026-01-01..03
    purchases = nodes[nodes["product"] == "card_purchase"].set_index("date")
    assert purchases.loc[ts("2026-01-01"), ["outflow", "inflow", "confirmed_outflow"]].tolist() == [150.0, 0.0, 100.0]
    assert purchases.loc[ts("2026-01-02"), "outflow"] == 0.0
    refunds = nodes[nodes["product"] == "card_refund"].set_index("date")
    assert refunds.loc[ts("2026-01-01"), ["outflow", "inflow"]].tolist() == [0.0, 30.0]

    partners = daily_partner_table(nodes)
    assert list(partners.columns) == ["date", "partner", "outflow", "inflow", "net", "confirmed_outflow"]
    assert len(partners) == 3 * 2
    card = partners[partners["partner"] == "card_network"].set_index("date")
    assert card.loc[ts("2026-01-01"), ["outflow", "inflow", "net"]].tolist() == [150.0, 30.0, 120.0]
    assert partners["outflow"].sum() == pytest.approx(220.0)


def test_enforce_quantiles_sorts_and_clips():
    df = pd.DataFrame([[3.0, -1, 2, 5, 4, 6, 8, 7]], columns=list(QCOLS)).assign(partner="p")
    out = enforce_quantiles(df)
    assert out.loc[0, list(QCOLS)].tolist() == [0.0, 2, 3, 4, 5, 6, 7, 8]
    assert out.loc[0, "partner"] == "p"
    assert df.loc[0, "q10"] == -1  # input untouched
