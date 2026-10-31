import numpy as np
import pandas as pd
import pytest

from treasury.metrics import coverage
from treasury.models.base import QCOLS
from treasury.models.seasonal_naive import SeasonalNaive

LEVELS = {"alpha": [10.0, 20, 30, 40, 50, 5, 1], "beta": [7.0, 7, 7, 7, 7, 0, 0]}


def _weekday_history(days: pd.DatetimeIndex) -> pd.DataFrame:
    rows = [
        {"date": d, "segment": "s", "product": f"{p}_product", "partner": p,
         "outflow": LEVELS[p][d.day_of_week], "inflow": 0.0, "confirmed_outflow": LEVELS[p][d.day_of_week]}
        for p in LEVELS
        for d in days
    ]
    return pd.DataFrame(rows)


def test_seasonal_naive_weekday_pattern():
    history = _weekday_history(pd.date_range("2026-01-01", periods=70, freq="D"))
    model = SeasonalNaive()
    model.fit(history, None)
    dates = pd.date_range("2026-03-12", periods=14, freq="D")
    pred = model.predict(dates, None)
    assert model.name == "seasonal_naive"
    assert list(pred.columns) == ["date", "partner", *QCOLS]
    assert len(pred) == 14 * 2
    level = np.array([LEVELS[p][d.day_of_week] for d, p in zip(pred["date"], pred["partner"])])
    assert pred["q50"].to_numpy() == pytest.approx(level)
    assert coverage(level, pred["q05"].to_numpy(), pred["q99"].to_numpy()) == 1.0


def test_seasonal_naive_uses_only_recent_weeks_and_noise_widens_bands():
    days = pd.date_range("2026-01-01", periods=84, freq="D")
    history = _weekday_history(days)
    old = history["date"] < days[-56]
    history.loc[old, "outflow"] += 1000.0  # outside the 8-week window: must not leak into the point
    noise = np.random.default_rng(0).normal(0, 1, (~old).sum())
    history.loc[~old, "outflow"] += np.abs(noise)
    model = SeasonalNaive()
    model.fit(history, None)
    pred = model.predict(pd.date_range(days[-1] + pd.Timedelta(days=1), periods=7, freq="D"), None)
    assert (pred["q50"] < 100).all()
    alpha = pred[pred["partner"] == "alpha"]
    assert (alpha["q95"] > alpha["q05"]).all()
    assert (pred[list(QCOLS)].diff(axis=1).iloc[:, 1:] >= 0).all().all()
    assert (pred[list(QCOLS)] >= 0).all().all()


def test_seasonal_naive_needs_two_weeks():
    model = SeasonalNaive()
    model.fit(_weekday_history(pd.date_range("2026-01-01", periods=14, freq="D")), None)
    with pytest.raises(ValueError):
        model.fit(_weekday_history(pd.date_range("2026-01-01", periods=13, freq="D")), None)
