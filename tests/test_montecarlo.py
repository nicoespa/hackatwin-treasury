import numpy as np
import pandas as pd
import pytest

from treasury.models.base import QCOLS, QUANTILES
from treasury.montecarlo import cumulative_quantiles, need_from_paths, paths_from_quantiles, simulate_paths


def _mu(n_dates: int, n_nodes: int, seed: int = 1) -> np.ndarray:
    return np.random.default_rng(seed).uniform(10.0, 100.0, size=(n_dates, n_nodes))


@pytest.mark.parametrize("sigma_f", [0.0, 0.15])
def test_paths_shape_and_mean(sigma_f):
    mu = _mu(7, 12)
    node_partner = np.array([0, 0, 1, 1, 1, 2, 2, 2, 2, 0, 1, 2])
    cv = np.full(12, 0.5)
    paths = simulate_paths(mu, cv, node_partner, 3, sigma_f, 0.6, n_paths=20_000, seed=0)
    assert paths.shape == (20_000, 7, 3)
    expected = np.column_stack([mu[:, node_partner == p].sum(1) for p in range(3)])
    np.testing.assert_allclose(paths.mean(axis=0), expected, rtol=0.03)
    assert (paths >= 0).all()


def test_paths_deterministic_per_seed():
    mu, cv, node_partner = _mu(5, 4), np.full(4, 0.3), np.array([0, 1, 1, 0])
    a = simulate_paths(mu, cv, node_partner, 2, 0.1, 0.5, n_paths=100, seed=3)
    b = simulate_paths(mu, cv, node_partner, 2, 0.1, 0.5, n_paths=100, seed=3)
    np.testing.assert_array_equal(a, b)


def test_factor_increases_aggregate_variance():
    mu = np.full((7, 200), 50.0)
    cv, node_partner = np.full(200, 0.3), np.zeros(200, dtype=int)

    def aggregate_cv(sigma_f: float) -> float:
        total = simulate_paths(mu, cv, node_partner, 1, sigma_f, 0.5, n_paths=4000, seed=0)[:, :, 0]
        return float(np.mean(total.std(axis=0) / total.mean(axis=0)))

    assert aggregate_cv(0.15) > 3 * aggregate_cv(0.0)


def test_need_ge_terminal_sum():
    net = np.random.default_rng(0).normal(0.0, 10.0, size=(500, 7, 3))
    for window in (1, 3, 7):
        need = need_from_paths(net, window)
        assert need.shape == (500, 3)
        assert (need >= net[:, :window].sum(axis=1) - 1e-9).all()
    assert (need_from_paths(net, 7) > net.sum(axis=1)).any()
    gross = np.abs(net)
    np.testing.assert_allclose(need_from_paths(gross, 5), gross[:, :5].sum(axis=1))


def test_cumulative_quantiles():
    paths = np.random.default_rng(0).gamma(2.0, 5.0, size=(4000, 3, 2))
    out = cumulative_quantiles(paths, (0.1, 0.5, 0.9))
    assert list(out.columns) == ["horizon", "partner", "q10", "q50", "q90"]
    assert len(out) == 6
    h3 = out[(out["horizon"] == 3) & (out["partner"] == 1)].iloc[0]
    np.testing.assert_allclose(h3["q50"], np.quantile(paths[:, :, 1].sum(axis=1), 0.5))
    assert (out["q10"] <= out["q50"]).all() and (out["q50"] <= out["q90"]).all()
    named = cumulative_quantiles(paths, (0.5,), partners=["a", "b"])
    assert set(named["partner"]) == {"a", "b"}


def _quantile_frame(n_dates: int = 14) -> pd.DataFrame:
    dates = pd.date_range("2026-10-01", periods=n_dates, freq="D")
    rows = []
    for d in dates:
        for partner, scale in (("b", 2.0), ("a", 1.0)):
            q = scale * np.array([60, 70, 85, 100, 115, 130, 140, 160], float)
            rows.append({"date": d, "partner": partner, **dict(zip(QCOLS, q))})
    return pd.DataFrame(rows)


def test_paths_from_quantiles_marginals_match_quantiles():
    frame = _quantile_frame()
    paths, partners, dates = paths_from_quantiles(frame, n_paths=20_000, seed=0)
    assert paths.shape == (20_000, 14, 2)
    assert partners == ["a", "b"]
    assert dates.equals(pd.DatetimeIndex(sorted(frame["date"].unique())))
    expected = frame[frame["partner"] == "a"].iloc[0][list(QCOLS)].to_numpy(float)
    np.testing.assert_allclose(np.quantile(paths[:, 3, 0], QUANTILES), expected, rtol=0.02)
    np.testing.assert_allclose(np.quantile(paths[:, 3, 1], QUANTILES), 2 * expected, rtol=0.02)
    assert paths.min() >= 0 and paths.max() <= 2 * 160 + 1e-9


def test_paths_from_quantiles_rho_raises_weekly_sum_variance():
    frame = _quantile_frame()
    iid = paths_from_quantiles(frame, n_paths=5000, seed=1)[0]
    corr = paths_from_quantiles(frame, n_paths=5000, seed=1, rho=0.9)[0]
    assert (corr[:, :7].sum(axis=1).var(axis=0) > 3 * iid[:, :7].sum(axis=1).var(axis=0)).all()
    assert np.quantile(corr[:, 3, 0], 0.5) == pytest.approx(100, rel=0.03)
