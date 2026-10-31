"""Monte Carlo of node flows sharing one daily macro factor, summed to partners.

Paths are ``[n_paths, n_dates, n_partners]`` arrays. Nodes are independent given the factor, so
without it the partner sums concentrate (law of large numbers) and the partner-level spread is
artificially narrow; the shared factor keeps the common, non-diversifiable part of the error.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd


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
