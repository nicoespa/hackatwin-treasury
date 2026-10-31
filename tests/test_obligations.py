import numpy as np
import pandas as pd
import pytest

from treasury.obligations import confirmed_obligations, detect_recurring, split_residual

COLUMNS = [
    "at", "user_id", "segment", "product", "amount", "confirmed", "counterparty", "partner", "settle_at", "direction",
]


def _event(at: str, user: int, amount: float, confirmed: bool = False, counterparty: str = "",
           partner: str = "bills_aggregator", settle: str | None = None, direction: int = 1) -> dict:
    ts = pd.Timestamp(at)
    return {
        "at": ts, "user_id": user, "segment": "s", "product": "bill_payment", "amount": amount,
        "confirmed": confirmed, "counterparty": counterparty, "partner": partner,
        "settle_at": pd.Timestamp(settle) if settle else ts, "direction": direction,
    }


def _frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=COLUMNS).astype({"direction": np.int8})


def test_confirmed_obligations_only_confirmed_rows():
    events = _frame([
        _event("2026-03-02 10:00", 1, 100.0, confirmed=True, settle="2026-03-03 15:00"),
        _event("2026-03-02 11:00", 2, 50.0, confirmed=True, settle="2026-03-03 09:00"),
        _event("2026-03-02 12:00", 3, 999.0, confirmed=False, settle="2026-03-03 15:00"),
        _event("2026-03-02 12:00", 4, 7.0, confirmed=True, partner="card_network", settle="2026-03-04 17:00"),
        _event("2026-03-02 13:00", 5, 30.0, confirmed=True, settle="2026-03-10 15:00"),  # outside horizon
        _event("2026-03-02 13:00", 6, 40.0, confirmed=True, settle="2026-03-03 15:00", direction=-1),
    ])
    horizon = pd.date_range("2026-03-03", periods=7, freq="D")
    out = confirmed_obligations(events, pd.Timestamp("2026-03-03"), horizon)
    assert list(out.columns) == ["date", "partner", "amount"]
    assert out.to_dict("records") == [
        {"date": pd.Timestamp("2026-03-03"), "partner": "bills_aggregator", "amount": 150.0},
        {"date": pd.Timestamp("2026-03-04"), "partner": "card_network", "amount": 7.0},
    ]


def test_detect_recurring_monthly_bill():
    rows = [_event(f"2026-{m:02d}-10 09:00", 1, 100.0, counterparty="1-b0") for m in range(1, 6)]
    rows += [_event(f"2026-{m:02d}-03 09:00", 1, 20.0 + m, counterparty="1-b1") for m in range(1, 6)]
    # irregular stream: gaps 5, 40, 12 days
    rows += [_event(d, 2, 60.0, counterparty="2-b0") for d in ("2026-01-01", "2026-01-06", "2026-02-15", "2026-02-27")]
    rows += [_event(d, 3, 80.0, counterparty="3-b0") for d in ("2026-04-01", "2026-05-01")]  # too few
    rows += [_event("2026-02-01", 4, 5.0)]  # not a bill
    rows += [_event("2026-05-20 08:00", 1, 9999.0, counterparty="1-b0")]  # at as_of: not yet known
    as_of = pd.Timestamp("2026-05-20")
    out = detect_recurring(_frame(rows), as_of)
    assert list(out.columns) == [
        "user_id", "counterparty", "partner", "period_days", "next_date", "p_occur", "amount_median",
    ]
    assert set(out["counterparty"]) == {"1-b0", "1-b1"}
    bill = out.set_index("counterparty").loc["1-b0"]
    assert bill["period_days"] == pytest.approx(30, abs=1.5)
    assert bill["next_date"] == pd.Timestamp("2026-06-10")
    assert bill["p_occur"] >= 0.8
    assert bill["amount_median"] == 100.0
    assert bill["partner"] == "bills_aggregator"


def test_detect_recurring_penalizes_missed_periods():
    rows = [_event(f"2026-{m:02d}-10", 1, 100.0, counterparty="1-b0") for m in (1, 2, 3)]
    out = detect_recurring(_frame(rows), pd.Timestamp("2026-07-01"))
    # paid 3 of the 6 monthly periods since the first payment
    assert out.loc[0, "p_occur"] == pytest.approx(0.5, abs=0.1)


def test_split_residual_non_negative():
    history = pd.DataFrame({
        "date": pd.to_datetime(["2026-01-01"] * 3),
        "segment": ["a", "b", "c"], "product": "bill_payment", "partner": "bills_aggregator",
        "outflow": [100.0, 40.0, 0.0], "inflow": 0.0, "confirmed_outflow": [30.0, 40.0, 5.0],
    })
    out = split_residual(history)
    assert out["outflow_residual"].tolist() == [70.0, 0.0, 0.0]
    assert (out["outflow_residual"] >= 0).all()
    pd.testing.assert_frame_equal(out.drop(columns="outflow_residual"), history)
