"""Seasonal-naive baseline: recent same-weekday mean plus its empirical residual quantiles."""

from __future__ import annotations

import numpy as np
import pandas as pd

from treasury.models.base import QCOLS, QUANTILES, daily_partner_table, enforce_quantiles

_DAY_NS = pd.Timedelta(days=1).value
MIN_WEEKS = 2


class SeasonalNaive:
    """Per partner and phase of the season (weekday for ``season=7``), over the last
    ``window_weeks`` seasons before the origin: point = mean outflow of that phase, quantiles =
    point + empirical quantiles of the phase's residuals (outflow - phase mean). Any horizon reuses
    the same profile. With fewer than ``window_weeks`` seasons of history it uses every full season
    available, and raises ``ValueError`` below ``MIN_WEEKS``.
    """

    name = "seasonal_naive"

    def __init__(self, season: int = 7, window_weeks: int = 8) -> None:
        self.season = season
        self.window_weeks = window_weeks
        self._profile: pd.DataFrame | None = None

    def _phase(self, dates: pd.Series | pd.DatetimeIndex) -> np.ndarray:
        return (np.asarray(dates, dtype="datetime64[ns]").astype(np.int64) // _DAY_NS) % self.season

    def fit(self, history: pd.DataFrame, drivers: pd.DataFrame | None = None) -> None:
        daily = daily_partner_table(history)
        n_days = daily["date"].nunique()
        weeks = min(self.window_weeks, n_days // self.season)
        if weeks < MIN_WEEKS:
            raise ValueError(f"need at least {MIN_WEEKS * self.season} days of history, got {n_days}")
        start = daily["date"].max() - pd.Timedelta(days=weeks * self.season - 1)
        recent = daily[daily["date"] >= start].assign(phase=lambda d: self._phase(d["date"]))
        by_phase = recent.groupby(["partner", "phase"])["outflow"]
        resid = recent["outflow"] - by_phase.transform("mean")
        spread = resid.groupby([recent["partner"], recent["phase"]]).quantile(list(QUANTILES)).unstack()
        self._profile = spread.add(by_phase.mean(), axis=0).set_axis(list(QCOLS), axis=1)

    def predict(self, dates: pd.DatetimeIndex, drivers: pd.DataFrame | None = None) -> pd.DataFrame:
        if self._profile is None:
            raise RuntimeError("fit before predict")
        partners = self._profile.index.unique("partner")
        grid = pd.MultiIndex.from_product([pd.DatetimeIndex(dates), partners], names=["date", "partner"])
        frame = grid.to_frame(index=False)
        keys = pd.MultiIndex.from_arrays([frame["partner"], self._phase(frame["date"])])
        frame[list(QCOLS)] = self._profile.reindex(keys).to_numpy()
        return enforce_quantiles(frame)
