from datetime import date

import numpy as np
import pandas as pd

from treasury.harness import default_origins, rolling_origin
from treasury.metrics import summarize
from treasury.models.base import QCOLS, daily_partner_table
from treasury.models.segment_lgbm import CV_RANGE, SegmentLGBM, common_factor, node_cv

END = date(2026, 10, 31)


def test_segment_model_quantiles_shape_and_monotone(history, drivers):
    origin = pd.Timestamp("2026-10-01")  # autodebit bills fall due on days 1..10
    dates = pd.date_range(origin, periods=7, freq="D")
    model = SegmentLGBM(n_paths=500)
    assert model.name == "segment_factor"
    assert SegmentLGBM(use_factor=False).name == "segment_nofactor"
    model.fit(history[history["date"] < origin], drivers[drivers["date"] < origin])
    assert model.sigma_f > 0 and 0 <= model.phi_f <= 0.95
    pred = model.predict(dates, drivers[drivers["date"] <= dates[-1]])
    assert list(pred.columns) == ["date", "partner", *QCOLS]
    assert len(pred) == 7 * 6
    assert (pred[list(QCOLS)].diff(axis=1).iloc[:, 1:] >= 0).all().all()
    assert model.last_paths.shape == (500, 7, 6)
    assert model.partner_index == sorted(history["partner"].unique())
    assert model.last_dates.equals(dates)
    confirmed = drivers.set_index("date").loc[dates, [f"confirmed_{p}" for p in model.partner_index]].to_numpy()
    assert confirmed.sum() > 0
    assert (model.last_paths >= confirmed[None] - 1e-6).all()
    q50 = pred.pivot(index="date", columns="partner", values="q50")[model.partner_index].to_numpy()
    np.testing.assert_allclose(q50, np.quantile(model.last_paths, 0.5, axis=0), rtol=1e-9)
    nofactor = SegmentLGBM(use_factor=False, n_paths=500)
    nofactor.fit(history[history["date"] < origin], drivers[drivers["date"] < origin])
    assert nofactor.sigma_f == 0.0


def test_segment_model_pit_flat_with_factor(history, drivers):
    origins = default_origins(END)
    preds = pd.concat([
        rolling_origin(history, drivers, lambda: SegmentLGBM(use_factor=True), origins),
        rolling_origin(history, drivers, lambda: SegmentLGBM(use_factor=False), origins),
    ])
    actual = daily_partner_table(history)[["date", "partner", "outflow"]]
    summary = summarize(preds, actual, by=("model",)).set_index("model")
    assert summary.loc["segment_factor", "pit_ks"] < summary.loc["segment_nofactor", "pit_ks"]


def _pure_common_shock(seed: int = 0):
    rng = np.random.default_rng(seed)
    n_days, n_nodes = 56, 12
    r_hat = rng.uniform(0.5, 1.5, size=(n_days, n_nodes))
    base = rng.uniform(1e5, 1e6, size=(n_days, n_nodes))
    g = rng.normal(0.0, 0.2, n_days)
    r = r_hat + r_hat * (np.exp(g)[:, None] - 1.0)  # residual = r_hat · (exp(g_d) - 1), nothing idiosyncratic
    return r, r_hat, base, g


def test_cv_excludes_common_factor():
    r, r_hat, base, g = _pure_common_shock()
    products = ["a", "b"] * 6
    g_hat, sigma_f, _ = common_factor(r * base, r_hat * base)
    np.testing.assert_allclose(g_hat, g)
    assert sigma_f > 0.1
    np.testing.assert_array_equal(node_cv(r, r_hat, g_hat, products), CV_RANGE[0])
    assert (node_cv(r, r_hat, np.zeros_like(g_hat), products) > CV_RANGE[0]).all()


def test_common_factor_guards():
    r, r_hat, base, g = _pure_common_shock()
    actual, mu = r * base, r_hat * base
    mu[:, 0] = np.nan  # a node without baseline must not enter the actual total either
    np.testing.assert_allclose(common_factor(actual, mu)[0], g)
    sparse = actual.copy()
    sparse[13:] = 0.0  # 13 usable days, below MIN_FACTOR_DAYS
    g0, sigma_f, phi_f = common_factor(sparse, r_hat * base)
    assert sigma_f == 0.0 and phi_f == 0.0 and (g0 == 0).all()
    gappy = actual.copy()
    gappy[::2] = 0.0  # no two consecutive usable days: no pair for the autocorrelation
    assert common_factor(gappy, r_hat * base)[2] == 0.0
