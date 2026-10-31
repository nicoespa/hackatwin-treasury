"""Probabilistic forecast metrics on the ``QUANTILES`` grid."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from treasury.models.base import QCOLS, QUANTILES

_GRID_P = np.array([0.0, *QUANTILES])


def pinball(y: np.ndarray, q: np.ndarray, tau: float) -> float:
    """Mean pinball (quantile) loss of quantile forecast ``q`` at level ``tau``."""
    diff = np.asarray(y, float) - np.asarray(q, float)
    return float(np.mean(np.maximum(tau * diff, (tau - 1) * diff)))


def coverage(y: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> float:
    """Fraction of ``y`` with ``lo <= y <= hi``."""
    y = np.asarray(y, float)
    return float(np.mean((np.asarray(lo) <= y) & (y <= np.asarray(hi))))


def wape(y: np.ndarray, yhat: np.ndarray) -> float:
    """``sum|y - yhat| / sum|y|``; NaN when every ``y`` is 0."""
    denom = float(np.abs(y).sum())
    return float(np.abs(np.asarray(y) - np.asarray(yhat)).sum()) / denom if denom else float("nan")


def _cdf(y: np.ndarray, x: np.ndarray, side: str) -> np.ndarray:
    """Piecewise-linear CDF through (x[:, k], _GRID_P[k]): right limit for ``side="right"``, left otherwise."""
    j = (x <= y[:, None]).sum(1) if side == "right" else (x < y[:, None]).sum(1)
    k = np.clip(j, 1, x.shape[1] - 1)
    rows = np.arange(len(y))
    x0, x1 = x[rows, k - 1], x[rows, k]
    with np.errstate(divide="ignore", invalid="ignore"):
        frac = np.clip((y - x0) / (x1 - x0), 0.0, 1.0)
    p = _GRID_P[k - 1] + frac * (_GRID_P[k] - _GRID_P[k - 1])
    return np.where(j == 0, 0.0, np.where(j == x.shape[1], _GRID_P[-1], p))


def pit(y: np.ndarray, quantile_df: pd.DataFrame) -> np.ndarray:
    """Probability integral transform of ``y`` under each row's quantile forecast.

    The CDF is linear between grid quantiles. Below ``q05`` the first segment (q05-q10) is
    extrapolated down to probability 0 and clipped there; above ``q99`` the PIT is 1. Where several
    quantiles coincide with ``y`` (a point mass) the PIT is the midpoint of the CDF jump.
    """
    y = np.asarray(y, float)
    q = quantile_df[list(QCOLS)].to_numpy(float)
    x = np.column_stack([2 * q[:, 0] - q[:, 1], q])
    value = (_cdf(y, x, "left") + _cdf(y, x, "right")) / 2
    return np.where(y > q[:, -1], 1.0, value)


def pit_ks(pit_values: np.ndarray) -> float:
    """Kolmogorov-Smirnov distance of a PIT sample from Uniform(0, 1)."""
    return float(stats.kstest(pit_values, "uniform").statistic)


def crps_from_quantiles(y: np.ndarray, quantile_df: pd.DataFrame) -> float:
    """CRPS approximated as the mean over the ``QUANTILES`` grid of ``2 * pinball(tau)``.

    The grid is coarse and uneven, so this is a quantile-score proxy for CRPS, comparable across
    models on the same grid rather than equal to the exact integral.
    """
    return float(np.mean([2 * pinball(y, quantile_df[c].to_numpy(), t) for t, c in zip(QUANTILES, QCOLS)]))


def _scores(g: pd.DataFrame) -> pd.Series:
    y = g["actual"].to_numpy(float)
    return pd.Series(
        {
            "wape_q50": wape(y, g["q50"].to_numpy()),
            "pinball_q90": pinball(y, g["q90"].to_numpy(), 0.90),
            "pinball_q99": pinball(y, g["q99"].to_numpy(), 0.99),
            "cov_90": coverage(y, g["q05"].to_numpy(), g["q95"].to_numpy()),
            "cov_99": float(np.mean(y <= g["q99"].to_numpy())),
            "crps": crps_from_quantiles(y, g),
            "pit_ks": pit_ks(pit(y, g)),
        }
    )


def summarize(preds: pd.DataFrame, actual: pd.DataFrame) -> pd.DataFrame:
    """Scores per ``model, partner, horizon``.

    ``preds`` has ``model, origin, date, horizon, partner, q05..q99``; ``actual`` has ``date,
    partner, outflow`` and is joined on ``(date, partner)``; predictions without an actual are
    dropped. ``cov_90`` is the share inside [q05, q95]; ``cov_99`` the share at or below q99.
    """
    truth = actual[["date", "partner", "outflow"]].rename(columns={"outflow": "actual"})
    joined = preds.drop(columns="actual", errors="ignore").merge(
        truth, on=["date", "partner"], how="inner", validate="many_to_one"
    )
    groups = joined.groupby(["model", "partner", "horizon"])[[*QCOLS, "actual"]]
    return groups.apply(_scores).reset_index()
