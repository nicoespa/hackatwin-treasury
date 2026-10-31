import numpy as np
import pandas as pd
import pytest

from treasury.ledger import Credit, Flow, balance_path, first_shortfall, max_need, min_deposit, min_deposit_paths

DAY = "2026-11-02"


def ts(hhmm: str) -> pd.Timestamp:
    return pd.Timestamp(f"{DAY} {hhmm}")


def test_credit_at_18_does_not_cover_outflow_at_10():
    flows = [Flow(ts("10:00"), 100.0)]
    credits = [Credit(ts("18:00"), 100.0)]
    path = balance_path(0.0, flows, credits)

    assert first_shortfall(path) == ts("10:00")
    assert max_need(path, 0.0) == 100
    assert min_deposit(0.0, flows, credits, arrival_at=ts("18:00")).unresolvable is True


def test_credit_before_outflow_covers_it():
    flows = [Flow(ts("10:00"), 100.0)]
    credits = [Credit(ts("09:00"), 100.0)]
    path = balance_path(0.0, flows, credits)

    assert first_shortfall(path) is None
    assert min_deposit(0.0, flows, credits, arrival_at=ts("09:00")).amount == 0


def test_intraday_net_zero_needs_gross():
    path = balance_path(0.0, [Flow(ts("10:00"), 100.0), Flow(ts("18:00"), -100.0)], [])

    assert max_need(path, 0.0) == 100


def test_inflow_before_outflow_nets():
    path = balance_path(0.0, [Flow(ts("09:00"), -100.0), Flow(ts("10:00"), 100.0)], [])

    assert max_need(path, 0.0) == 0


def test_min_deposit_covers_post_arrival_shortfall():
    flows = [Flow(ts("10:00"), 30.0), Flow(ts("12:00"), 100.0)]
    result = min_deposit(50.0, flows, [], arrival_at=ts("11:00"))

    assert result.amount == 80
    assert result.unresolvable is False
    assert result.first_shortfall == ts("12:00")


def test_min_deposit_reports_pre_arrival_shortfall():
    flows = [Flow(ts("10:00"), 30.0), Flow(ts("12:00"), 100.0)]
    result = min_deposit(0.0, flows, [], arrival_at=ts("11:00"))

    # The brief listed 100 here, but its own definition gives 130: the balance carried
    # into the 11:00 arrival is -30 (the pre-arrival shortfall is not undone), so the
    # deposit must cover -130 at 12:00. Ruled by the controller: literal definition wins.
    assert result.amount == 130
    assert result.unresolvable is True
    assert result.first_shortfall == ts("10:00")


def test_same_instant_credit_applies_before_outflow():
    at = ts("10:00")
    path = balance_path(0.0, [Flow(at, 100.0)], [Credit(at, 100.0)])

    assert first_shortfall(path) is None
    assert max_need(path, 0.0) == 0


def test_same_instant_inflow_applies_before_outflow():
    at = ts("10:00")
    path = balance_path(0.0, [Flow(at, 100.0), Flow(at, -100.0)], [])

    assert first_shortfall(path) is None
    assert list(path["delta"]) == [100.0, -100.0]


def test_path_is_sorted_and_cumulative():
    flows = [Flow(ts("12:00"), 40.0), Flow(ts("08:00"), 10.0)]
    path = balance_path(100.0, flows, [Credit(ts("10:00"), 5.0)])

    assert list(path.columns) == ["at", "delta", "balance"]
    assert list(path["at"]) == [ts("08:00"), ts("10:00"), ts("12:00")]
    assert list(path["delta"]) == [-10.0, 5.0, -40.0]
    assert list(path["balance"]) == [90.0, 95.0, 55.0]


def test_deposit_at_arrival_instant_covers_flows_at_that_instant():
    at = ts("10:00")
    result = min_deposit(0.0, [Flow(at, 70.0)], [], arrival_at=at)

    assert result.amount == 70
    assert result.unresolvable is False


def test_empty_inputs():
    path = balance_path(25.0, [], [])

    assert len(path) == 0
    assert list(path.columns) == ["at", "delta", "balance"]
    assert max_need(path, 25.0) == 0
    assert first_shortfall(path) is None
    result = min_deposit(25.0, [], [], arrival_at=ts("10:00"))
    assert (result.amount, result.unresolvable, result.first_shortfall) == (0, False, None)


def test_min_deposit_paths_matches_min_deposit_per_path():
    rng = np.random.default_rng(0)
    flow_at = pd.DatetimeIndex([ts("00:00"), ts("08:00"), ts("09:30"), ts("12:00"), ts("12:00"), ts("20:00")])
    signs = np.array([1, 1, 1, 1, -1, 1])
    amounts = rng.uniform(0, 100, size=(50, len(flow_at))) * signs
    credits = [Credit(ts("12:00"), 60.0), Credit(ts("18:00"), 40.0)]
    result = min_deposit_paths(80.0, flow_at, amounts, credits, arrival_at=ts("09:30"))
    for i, row in enumerate(amounts):
        flows = [Flow(at, float(a)) for at, a in zip(flow_at, row)]
        one = min_deposit(80.0, flows, credits, arrival_at=ts("09:30"))
        assert result.amount[i] == pytest.approx(one.amount)
        assert result.unresolvable[i] == one.unresolvable
        assert result.need[i] == pytest.approx(max_need(balance_path(80.0, flows, []), 80.0))


def test_min_deposit_paths_rejects_mixed_sign_columns():
    with pytest.raises(ValueError):
        min_deposit_paths(0.0, pd.DatetimeIndex([ts("10:00")]), np.array([[1.0], [-1.0]]), [], ts("09:00"))
