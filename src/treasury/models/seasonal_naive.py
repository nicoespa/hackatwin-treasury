"""Seasonal-naive baseline: recent same-weekday mean plus its empirical residual quantiles."""

from __future__ import annotations

import numpy as np
import pandas as pd

from treasury.models.base import QCOLS, QUANTILES, daily_partner_table, enforce_quantiles

_DAY_NS = pd.Timedelta(days=1).value
MIN_WEEKS = 2
WINDOW_WEEKS = 8


def seasonal_lag(series: pd.Series, dates: pd.DatetimeIndex, lag: int, season: int = 7) -> np.ndarray:
    """``series`` (daily, indexed by date) at ``date - lag`` for each date; a lagged date after the
    last observed one falls back whole seasons to the latest observed date in the same phase.
    NaN before the first observed date."""
    last = series.index.max()
    src = pd.DatetimeIndex(dates) - pd.Timedelta(days=lag)
    seasons_back = np.ceil(np.maximum((src - last).days.to_numpy(), 0) / season).astype(int)
    return series.reindex(src - pd.to_timedelta(season * seasons_back, unit="D")).to_numpy(dtype=float)


def seasonal_mean(
    series: pd.Series, dates: pd.DatetimeIndex, weeks: int = WINDOW_WEEKS, season: int = 7
) -> np.ndarray:
    """The seasonal-naive point for each date: mean of the latest ``weeks`` observed values in the
    date's phase, at least one season before it. With fewer than ``weeks`` observed it averages
    those available, and is NaN below ``MIN_WEEKS``."""
    values = np.column_stack([seasonal_lag(series, dates, season * k, season) for k in range(1, weeks + 1)])
    enough = np.isfinite(values).sum(axis=1) >= min(MIN_WEEKS, weeks)
    with np.errstate(invalid="ignore"):
        mean = np.nanmean(np.where(enough[:, None], values, 0.0), axis=1)
    return np.where(enough, mean, np.nan)


class SeasonalNaive:
    """Per partner and phase of the season (weekday for ``season=7``), over the last
    ``window_weeks`` seasons before the origin: point = mean outflow of that phase
    (``seasonal_mean``), quantiles = point + empirical quantiles of the phase's residuals
    (outflow - phase mean). Any horizon reuses the same profile. With fewer than ``window_weeks``
    seasons of history it uses every full season available, and raises ``ValueError`` below
    ``MIN_WEEKS``.
    """

    name = "seasonal_naive"

    def __init__(self, season: int = 7, window_weeks: int = WINDOW_WEEKS) -> None:
        self.season = season
        self.window_weeks = window_weeks
        self._profile: pd.DataFrame | None = None

    def _phase(self, dates: pd.Series | pd.DatetimeIndex) -> np.ndarray:
        return (np.asarray(dates, dtype="datetime64[ns]").astype(np.int64) // _DAY_NS) % self.season

    def fit(self, history: pd.DataFrame, drivers: pd.DataFrame | None = None) -> None:
        wide = daily_partner_table(history).pivot(index="date", columns="partner", values="outflow")
        weeks = min(self.window_weeks, len(wide) // self.season)
        if weeks < MIN_WEEKS:
            raise ValueError(f"need at least {MIN_WEEKS * self.season} days of history, got {len(wide)}")
        recent = wide.iloc[-weeks * self.season :]
        ahead = pd.date_range(wide.index[-1] + pd.Timedelta(days=1), periods=self.season, freq="D")
        point = pd.DataFrame(
            {p: seasonal_mean(wide[p], ahead, weeks, self.season) for p in wide}, index=self._phase(ahead)
        )
        phase = self._phase(recent.index)
        resid = (recent - point.loc[phase].to_numpy()).set_axis(phase, axis=0)
        spread = resid.groupby(level=0).quantile(list(QUANTILES)).stack().unstack(1)
        spread.index = spread.index.set_names(["phase", "partner"]).swaplevel()
        self._profile = spread.add(point.stack().swaplevel().rename_axis(["partner", "phase"]), axis=0).set_axis(
            list(QCOLS), axis=1
        )

    def predict(self, dates: pd.DatetimeIndex, drivers: pd.DataFrame | None = None) -> pd.DataFrame:
        if self._profile is None:
            raise RuntimeError("fit before predict")
        partners = self._profile.index.unique("partner")
        grid = pd.MultiIndex.from_product([pd.DatetimeIndex(dates), partners], names=["date", "partner"])
        frame = grid.to_frame(index=False)
        keys = pd.MultiIndex.from_arrays([frame["partner"], self._phase(frame["date"])])
        frame[list(QCOLS)] = self._profile.reindex(keys).to_numpy()
        return enforce_quantiles(frame)
