from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from treasury.harness import default_origins, rolling_origin
from treasury.metrics import summarize
from treasury.models.base import QCOLS, daily_partner_table
from treasury.models.seasonal_naive import SeasonalNaive

PARTNERS = ["bills_aggregator", "card_network", "fci_custodian", "crypto_exchange", "cash_network", "remittance"]
END = date(2026, 6, 30)


@pytest.fixture(scope="module")
def history() -> pd.DataFrame:
    days = pd.date_range("2026-02-01", END, freq="D")
    rows = [
        {"date": d, "segment": seg, "product": f"{p}_x", "partner": p,
         "outflow": (i + 1) * 100.0 * (1 + d.day_of_week) * (0.5 if seg == "gig" else 1.0),
         "inflow": 10.0, "confirmed_outflow": 0.0}
        for i, p in enumerate(PARTNERS)
        for seg in ("salaried", "gig")
        for d in days
    ]
    return pd.DataFrame(rows)


def test_default_origins_leave_a_full_week_inside_the_data():
    origins = default_origins(END)
    assert origins == [date(2026, 5, 5) + timedelta(days=7 * k) for k in range(8)]
    assert max(origins) + timedelta(days=6) <= END


def test_rolling_origin_shapes(history):
    preds = rolling_origin(history, None, SeasonalNaive, default_origins(END), horizon=7)
    assert list(preds.columns) == ["model", "origin", "date", "horizon", "partner", *QCOLS, "actual"]
    assert len(preds) == 8 * 7 * 6
    assert preds["actual"].notna().all()
    assert set(preds["horizon"]) == set(range(1, 8))
    assert (preds["model"] == "seasonal_naive").all()
    assert ((preds["date"] - pd.to_datetime(preds["origin"])).dt.days + 1 == preds["horizon"]).all()
    # noise-free weekday pattern: the baseline is exact
    assert preds["q50"].to_numpy() == pytest.approx(preds["actual"].to_numpy())


def test_rolling_origin_fits_only_on_the_past(history):
    seen: list[tuple[pd.Timestamp, pd.Timestamp]] = []

    class Spy(SeasonalNaive):
        def fit(self, history, drivers):
            seen.append((history["date"].max(), drivers["date"].max()))
            super().fit(history, drivers)

    drivers = pd.DataFrame({"date": pd.date_range("2026-02-01", END, freq="D"), "x": 1.0})
    origins = default_origins(END, n=3)
    rolling_origin(history, drivers, Spy, origins)
    assert seen == [(pd.Timestamp(o) - pd.Timedelta(days=1),) * 2 for o in origins]


def test_summarize_keys_and_exact_baseline(history):
    preds = rolling_origin(history, None, SeasonalNaive, default_origins(END))
    actual = daily_partner_table(history)[["date", "partner", "outflow"]]
    summary = summarize(preds, actual)
    assert list(summary.columns) == [
        "model", "partner", "horizon", "wape_q50", "pinball_q90", "pinball_q99", "cov_90", "cov_99", "crps", "pit_ks",
    ]
    assert len(summary) == 6 * 7
    assert np.allclose(summary["wape_q50"], 0.0)
    assert (summary["cov_99"] == 1.0).all()
