"""Aggregate realism checks on a simulated (and routed) event log."""

from __future__ import annotations

import numpy as np
import pandas as pd

from treasury.calendar import Calendar
from treasury.simulate.events import PAYDAY_PRODUCTS
from treasury.simulate.population import SALARIED

ARGMAX_LAST_BD = 5
ARGMAX_MIN_SHARE = 8 / 12  # salaried peaks on business days 1-5 in at least 8 of 12 months
TREND_WINDOW_DAYS = 28


def _daily(events: pd.DataFrame, days: pd.DatetimeIndex) -> pd.Series:
    return events.groupby(events["at"].dt.normalize())["amount"].sum().reindex(days, fill_value=0.0)


def detrended(daily: pd.Series) -> pd.Series:
    """``daily`` over its centered 28-day rolling mean: removes population growth and inflation."""
    return daily / daily.rolling(TREND_WINDOW_DAYS, center=True, min_periods=TREND_WINDOW_DAYS // 2).mean()


def _acf(x: np.ndarray, lag: int) -> float:
    x = x - x.mean()
    return float((x[:-lag] * x[lag:]).sum() / (x * x).sum())


def _cv(x: pd.Series) -> float:
    return float(x.std(ddof=1) / x.mean())


def validate(events_routed: pd.DataFrame, cal: Calendar) -> dict[str, float | bool]:
    """Realism checks on the daily totals of a routed event log.

    Every series is detrended (ratio to its centered 28-day mean) so that cohort growth
    and inflation do not inflate dispersion or mask the weekly cycle:

    - ``dispersion_index``: var/mean of daily event counts after detrending, rescaled to the overall mean count.
    - ``acf7_gt_acf3``: lag-7 autocorrelation of the detrended daily amount exceeds lag-3.
    - ``salaried_argmax_in_bd1_5``: salaried ``bill_payment`` + ``fci_subscription`` peaks on business days 1-5
      in at least 8 of 12 months.
    - ``p99_over_median``: tail of the daily total amount.
    - ``detrended_outflow_cv``: CV of the detrended daily outflow (``direction == 1``) amount by event date.
    """
    at = events_routed["at"].dt.normalize()
    days = pd.date_range(at.min(), at.max(), freq="D")
    counts = at.value_counts().reindex(days, fill_value=0).astype(float)
    flat_counts = detrended(counts) * counts.mean()
    amount = _daily(events_routed, days)
    seasonal = detrended(amount).to_numpy()
    outflow = _daily(events_routed[events_routed["direction"] == 1], days)

    payday_rows = (events_routed["segment"] == SALARIED) & events_routed["product"].isin(PAYDAY_PRODUCTS)
    salaried = _daily(events_routed[payday_rows], days)
    peaks = salaried.groupby(salaried.index.to_period("M")).idxmax()
    in_window = [1 <= cal.nth_business_day_of_month(d) <= ARGMAX_LAST_BD for d in peaks]

    return {
        "dispersion_index": float(flat_counts.var(ddof=1) / flat_counts.mean()),
        "acf7_gt_acf3": bool(_acf(seasonal, 7) > _acf(seasonal, 3)),
        "salaried_argmax_in_bd1_5": bool(np.mean(in_window) >= ARGMAX_MIN_SHARE),
        "p99_over_median": float(amount.quantile(0.99) / amount.median()),
        "detrended_outflow_cv": _cv(detrended(outflow)),
    }
