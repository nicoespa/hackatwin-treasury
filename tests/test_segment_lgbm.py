import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from treasury.features import build_drivers
from treasury.harness import default_origins, rolling_origin
from treasury.metrics import summarize
from treasury.models.base import QCOLS, daily_node_table, daily_partner_table
from treasury.models.segment_lgbm import SegmentLGBM

ROOT = Path(__file__).resolve().parents[1]
SIM = ROOT / "data" / "sim" / "base"
END = date(2026, 10, 31)


@pytest.fixture(scope="module")
def sim() -> tuple[pd.DataFrame, pd.DataFrame]:
    if not (SIM / "events.parquet").exists():
        from treasury.cli import simulate

        simulate(users=20_000, start=pd.Timestamp("2025-11-01").to_pydatetime(),
                 end=pd.Timestamp("2026-10-31").to_pydatetime(), seed=42, out=SIM,
                 payday_hypothesis="late", sigma_m=0.15, phi=0.7)
    return pd.read_parquet(SIM / "users.parquet"), pd.read_parquet(SIM / "events.parquet")


@pytest.fixture(scope="module")
def history(sim) -> pd.DataFrame:
    return daily_node_table(sim[1])


@pytest.fixture(scope="module")
def drivers(sim) -> pd.DataFrame:
    return build_drivers(*sim, pd.date_range("2025-11-01", END, freq="D"))


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
    began = time.perf_counter()
    preds = pd.concat([
        rolling_origin(history, drivers, lambda: SegmentLGBM(use_factor=True), origins),
        rolling_origin(history, drivers, lambda: SegmentLGBM(use_factor=False), origins),
    ])
    print(f"rolling origin for (d) and (d-): {time.perf_counter() - began:.1f}s")
    actual = daily_partner_table(history)[["date", "partner", "outflow"]]
    summary = summarize(preds, actual, by=("model",)).set_index("model")
    print(summary[["pinball_q90", "cov_90", "pit_ks"]])
    assert summary.loc["segment_factor", "pit_ks"] < summary.loc["segment_nofactor", "pit_ks"]
