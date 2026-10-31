"""Aggregate quantile LightGBM per partner, in ratio space to the seasonal-naive baseline.

Model (b) (``use_obligations=False``) forecasts gross partner ``outflow``. Model (c)
(``use_obligations=True``) forecasts the residual ``outflow - confirmed_outflow`` and adds the
confirmed obligations (``confirmed_<partner>`` from the drivers) back to every quantile once.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor

from treasury.calendar import Calendar
from treasury.features import calendar_features
from treasury.models.base import QCOLS, QUANTILES, enforce_quantiles
from treasury.models.seasonal_naive import seasonal_lag, seasonal_mean
from treasury.obligations import split_residual
from treasury.routing import load_partners

CONFIG = Path(__file__).resolve().parents[3] / "config"
LAGS = (7, 14, 28)
LEVEL_DAYS = 28  # trailing window for the baseline floor and the n_active ratio
FLOOR_SHARE = 0.01  # baseline floor as a share of the trailing level
# The plan's 400 trees / 15 leaves / 20 per leaf overfit the daily noise on ~300 rows per partner.
DEFAULT_PARAMS: Mapping[str, float] = {
    "n_estimators": 200, "learning_rate": 0.05, "num_leaves": 7, "min_child_samples": 40,
}


def trailing_level(series: pd.Series, dates: pd.DatetimeIndex) -> np.ndarray:
    """``series``' trailing ``LEVEL_DAYS``-day mean ending 7 days before each date (the last
    observed day when that is later), so it is known at any horizon up to 7 days."""
    level = series.rolling(LEVEL_DAYS, min_periods=7).mean()
    week_back, last = dates - pd.Timedelta(days=7), series.index.max()
    return level.reindex(week_back.where(week_back <= last, last)).to_numpy()


def seasonal_baseline(series: pd.Series, dates: pd.DatetimeIndex) -> np.ndarray:
    """``seasonal_mean`` floored at ``FLOOR_SHARE`` of the ``trailing_level``."""
    return np.fmax(seasonal_mean(series, dates), FLOOR_SHARE * trailing_level(series, dates))


def ratio_to_baseline(series: pd.Series, base: np.ndarray) -> np.ndarray:
    """``y / base``; 1 where ``base`` is 0 and NaN where it is NaN."""
    y = series.to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(base > 0, y / base, np.where(np.isnan(base), np.nan, 1.0))


def driver_features(
    dates: pd.DatetimeIndex, drivers: pd.DataFrame, cal: Calendar, payday_hypothesis: str
) -> pd.DataFrame:
    """Float features indexed by ``dates``: ``calendar_features``, per segment
    ``n_active_ratio_<seg>`` and ``n_new_ratio_<seg>``, and every ``campaign_lift_*``.
    ``ValueError`` when ``drivers`` lacks one of ``dates``."""
    drv = drivers.set_index("date").sort_index()
    missing = dates.difference(drv.index)
    if len(missing):
        raise ValueError(f"drivers missing for {len(missing)} dates, first {missing[0].date()}")
    stationary = {}
    for col in [c for c in drv if c.startswith("n_active_")]:
        segment = col.removeprefix("n_active_")
        active = drv[col].astype(float)
        trailing = active.rolling(LEVEL_DAYS, min_periods=1).mean()
        stationary[f"n_active_ratio_{segment}"] = (active / trailing).where(trailing > 0, 1.0)
        stationary[f"n_new_ratio_{segment}"] = (drv[f"n_new_30d_{segment}"] / active).where(active > 0, 0.0)
    lifts = drv[[c for c in drv if c.startswith("campaign_lift_")]]
    cal_df = calendar_features(dates, cal, payday_hypothesis).set_index("date")
    return pd.concat([cal_df, pd.DataFrame(stationary).reindex(dates), lifts.reindex(dates)], axis=1).astype(float)



class AggregateLGBM:
    """One ``LGBMRegressor(objective="quantile", alpha=tau)`` per partner and quantile level,
    fitted on the ratio ``r = y / baseline``.

    ``baseline`` is the seasonal-naive point (``seasonal_mean``: same-weekday mean of the latest
    8 observed weeks, at least 7 days back), floored at ``FLOOR_SHARE`` of the target's trailing
    ``LEVEL_DAYS``-day mean ending 7 days back; ``r = 1`` where the floored baseline is 0. Trees
    then learn the deviation from the seasonal profile, not the trending level.

    Features: ``calendar_features``; per segment ``n_active_ratio_<seg>`` (``n_active`` over its
    trailing 28-day mean, > 1 on a cohort wave) and ``n_new_ratio_<seg>`` (``n_new_30d /
    n_active``); the ``campaign_lift_*`` of the partner's products; lags 7/14/28 of ``r``.
    ``confirmed_*`` is never a feature. ``predict`` multiplies the quantiles of ``r`` by the
    target dates' baseline. Baseline and lags come from the stored history: for horizons up to 7
    days all of it is observed, and beyond that a date after the last observed day falls back
    whole weeks to the latest observed same weekday (``seasonal_lag``).
    """

    def __init__(
        self,
        name: str | None = None,
        use_obligations: bool = False,
        quantiles: Sequence[float] = QUANTILES,
        params: Mapping[str, float] | None = None,
        payday_hypothesis: str = "late",
    ) -> None:
        if len(quantiles) != len(QCOLS):
            raise ValueError(f"need one quantile per column of {QCOLS}")
        self.name = name or ("aggregate_drivers_obligations" if use_obligations else "aggregate_drivers")
        self.use_obligations = use_obligations
        self.quantiles = tuple(quantiles)
        self.params = dict(DEFAULT_PARAMS if params is None else params)
        self.payday_hypothesis = payday_hypothesis
        self._cal = Calendar.from_yaml(CONFIG / "calendar_ar.yaml")
        self._products = {pid: p.products for pid, p in load_partners(CONFIG / "partners.yaml").items()}
        self._target: pd.DataFrame | None = None
        self._ratio: pd.DataFrame | None = None
        self._models: dict[str, list[LGBMRegressor]] = {}

    def _target_table(self, history: pd.DataFrame) -> pd.DataFrame:
        """Daily target per partner: index ``date`` (every day), one column per partner."""
        col = "outflow"
        if self.use_obligations:
            history, col = split_residual(history), "outflow_residual"
        wide = history.groupby(["date", "partner"])[col].sum().unstack("partner")
        days = pd.date_range(wide.index.min(), wide.index.max(), freq="D", name="date")
        return wide.reindex(days).fillna(0.0)

    def _partner_features(self, shared: pd.DataFrame, partner: str) -> pd.DataFrame:
        lifts = {f"campaign_lift_{p}" for p in self._products[partner]}
        X = shared[[c for c in shared if not c.startswith("campaign_lift_") or c in lifts]].copy()
        for k in LAGS:
            X[f"lag_{k}"] = seasonal_lag(self._ratio[partner], X.index, k)
        return X

    def fit(self, history: pd.DataFrame, drivers: pd.DataFrame | None) -> None:
        if drivers is None:
            raise ValueError(f"{self.name} needs drivers")
        self._target = self._target_table(history)
        days = self._target.index
        self._ratio = pd.DataFrame(
            {p: ratio_to_baseline(self._target[p], seasonal_baseline(self._target[p], days)) for p in self._target},
            index=days,
        )
        shared = driver_features(days, drivers, self._cal, self.payday_hypothesis)
        self._models = {}
        for partner in self._target.columns:
            X = self._partner_features(shared, partner)
            y = self._ratio[partner].to_numpy()
            rows = np.isfinite(y) & np.isfinite(X.to_numpy()).all(axis=1)
            self._models[partner] = [
                LGBMRegressor(objective="quantile", alpha=tau, random_state=0, n_jobs=1, verbose=-1, **self.params).fit(
                    X[rows], y[rows]
                )
                for tau in self.quantiles
            ]

    def predict(self, dates: pd.DatetimeIndex, drivers: pd.DataFrame | None) -> pd.DataFrame:
        if self._target is None:
            raise RuntimeError("fit before predict")
        if drivers is None:
            raise ValueError(f"{self.name} needs drivers")
        dates = pd.DatetimeIndex(dates)
        shared = driver_features(dates, drivers, self._cal, self.payday_hypothesis)
        frames = []
        for partner, models in self._models.items():
            X = self._partner_features(shared, partner)
            base = seasonal_baseline(self._target[partner], dates)
            q = np.column_stack([m.predict(X) for m in models]) * base[:, None]
            frames.append(pd.DataFrame(q, columns=list(QCOLS)).assign(date=dates, partner=partner))
        pred = enforce_quantiles(pd.concat(frames, ignore_index=True))
        if self.use_obligations:
            confirmed = drivers.set_index("date").reindex(dates)
            add = np.concatenate([confirmed[f"confirmed_{p}"].to_numpy() for p in self._models])
            pred[list(QCOLS)] = pred[list(QCOLS)].to_numpy() + add[:, None]
        pred = pred.sort_values(["date", "partner"], kind="stable", ignore_index=True)
        return pred[["date", "partner", *QCOLS]]
