"""Monte Carlo of node flows sharing one daily macro factor, summed to partners.

Paths are ``[n_paths, n_dates, n_partners]`` arrays. Nodes are independent given the factor, so
without it the partner sums concentrate (law of large numbers) and the partner-level spread is
artificially narrow; the shared factor keeps the common, non-diversifiable part of the error.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd
from scipy import stats

from treasury.models.base import QCOLS, QUANTILES


def _log_factor(rng: np.random.Generator, n_paths: int, n_dates: int, sigma_f: float, phi_f: float) -> np.ndarray:
    """``log f`` per path and date: stationary AR(1) with marginal ``N(0, sigma_f)``, shifted by
    ``-sigma_f**2 / 2`` so the factor itself has mean 1 and ``mu`` stays the mean of the paths."""
    x = np.empty((n_paths, n_dates))
    x[:, 0] = rng.normal(0.0, sigma_f, n_paths)
    innovation = sigma_f * np.sqrt(1.0 - phi_f**2)
    for t in range(1, n_dates):
        x[:, t] = phi_f * x[:, t - 1] + rng.normal(0.0, innovation, n_paths)
    return x - sigma_f**2 / 2


def simulate_paths(
    mu: np.ndarray,
    cv: np.ndarray,
    node_partner: np.ndarray,
    n_partners: int,
    sigma_f: float,
    phi_f: float,
    n_paths: int,
    seed: int,
) -> np.ndarray:
    """Partner-level paths ``[n_paths, n_dates, n_partners]`` of node draws ``mu · f_d · eps``.

    ``mu`` is ``[n_dates, n_nodes]``; ``f_d`` the shared factor (``_log_factor``, one per path
    and date, common to every node); ``eps ~ Gamma(shape=1/cv², scale=cv²)`` is each node's
    independent mean-1 noise with coefficient of variation ``cv`` (``[n_nodes]``). Node draws are
    summed into partner ``node_partner[j]`` (``[n_nodes]``, ints in ``0..n_partners-1``).
    """
    mu = np.asarray(mu, float)
    cv = np.asarray(cv, float)
    n_dates, n_nodes = mu.shape
    rng = np.random.default_rng(seed)
    factor = np.exp(_log_factor(rng, n_paths, n_dates, sigma_f, phi_f))
    shape = 1.0 / cv**2
    eps = rng.gamma(shape, 1.0 / shape, size=(n_paths, n_dates, n_nodes))
    onehot = np.zeros((n_nodes, n_partners))
    onehot[np.arange(n_nodes), np.asarray(node_partner, int)] = 1.0
    return (mu[None] * eps) @ onehot * factor[..., None]


def need_from_paths(paths: np.ndarray, window: int) -> np.ndarray:
    """``[n_paths, n_partners]``: the peak cumulative sum over the first ``window`` dates.

    For pure-outflow paths the peak is the sum at ``window``; for net paths (outflow - inflow) it
    is the largest running deficit, which a prefunded balance must cover at every point.
    """
    return np.cumsum(paths[:, :window], axis=1).max(axis=1)


def _qcol(tau: float) -> str:
    return f"q{round(tau * 100):02d}"


def cumulative_quantiles(
    paths: np.ndarray, taus: Sequence[float], partners: Sequence[str] | None = None
) -> pd.DataFrame:
    """Quantiles of the cumulative sum per horizon: ``horizon, partner, q<tau>...``.

    ``horizon`` is 1-based; ``partner`` is the column index of ``paths`` unless ``partners``
    names them.
    """
    n_dates, n_partners = paths.shape[1:]
    q = np.quantile(np.cumsum(paths, axis=1), list(taus), axis=0)  # [n_taus, n_dates, n_partners]
    labels = list(range(n_partners)) if partners is None else list(partners)
    out = pd.DataFrame(
        {
            "horizon": np.repeat(np.arange(1, n_dates + 1), n_partners),
            "partner": np.tile(labels, n_dates),
        }
    )
    for tau, values in zip(taus, q):
        out[_qcol(tau)] = values.reshape(-1)
    return out


def paths_from_quantiles(
    quantile_df: pd.DataFrame, n_paths: int, seed: int, rho: float = 0.0
) -> tuple[np.ndarray, list[str], pd.DatetimeIndex]:
    """Sample paths ``[n_paths, n_dates, n_partners]`` from per-day quantile forecasts.

    ``quantile_df`` has ``date, partner, q05..q99`` for every date × partner. Each (date,
    partner) marginal is the piecewise-linear quantile function through the ``QUANTILES`` grid:
    below ``q05`` the q05-q10 segment is extended linearly down to probability 0 and clipped at
    0, above ``q99`` it holds ``q99``. Uniforms come from a Gaussian copula that is AR(1) across
    consecutive days with correlation ``rho``, independent across partners.

    A quantile-only model says nothing about how its errors persist from day to day, so the
    default ``rho=0`` draws days independently: a multi-day sum then concentrates and its tail
    is understated whenever the real errors are serially correlated. The segment model does not
    have this limitation; its shared AR(1) factor carries the persistence into its paths.
    Returns ``(paths, partners, dates)`` with partners and dates sorted.
    """
    partners = sorted(quantile_df["partner"].unique())
    dates = pd.DatetimeIndex(sorted(quantile_df["date"].unique()))
    grid_index = pd.MultiIndex.from_product([dates, partners])
    q = quantile_df.set_index(["date", "partner"])[list(QCOLS)].reindex(grid_index).to_numpy(float)
    if np.isnan(q).any():
        raise ValueError("quantile_df must have every quantile for every date x partner")
    q = q.reshape(len(dates), len(partners), len(QCOLS))
    lower = np.maximum(0.0, 2 * q[..., :1] - q[..., 1:2])
    x = np.concatenate([lower, q, q[..., -1:]], axis=-1)  # [n_dates, n_partners, n_grid]
    grid = np.array([0.0, *QUANTILES, 1.0])

    rng = np.random.default_rng(seed)
    z = rng.standard_normal((n_paths, len(dates), len(partners)))
    for t in range(1, len(dates)):
        z[:, t] = rho * z[:, t - 1] + np.sqrt(1.0 - rho**2) * z[:, t]
    u = stats.norm.cdf(z)
    k = np.clip(np.searchsorted(grid, u, side="right"), 1, len(grid) - 1)
    xb = np.broadcast_to(x, (n_paths, *x.shape))
    x0 = np.take_along_axis(xb, (k - 1)[..., None], axis=-1)[..., 0]
    x1 = np.take_along_axis(xb, k[..., None], axis=-1)[..., 0]
    frac = (u - grid[k - 1]) / (grid[k] - grid[k - 1])
    return x0 + frac * (x1 - x0), partners, dates
