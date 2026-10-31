import time
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from treasury.harness import default_origins, rolling_origin
from treasury.metrics import summarize
from treasury.models.aggregate_lgbm import AggregateLGBM
from treasury.models.base import QCOLS, daily_node_table, daily_partner_table
from treasury.models.seasonal_naive import SeasonalNaive
from treasury.features import build_drivers

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


def test_aggregate_lgbm_beats_naive_on_sim(history, drivers):
    origins = default_origins(END)
    began = time.perf_counter()
    preds = pd.concat([
        rolling_origin(history, drivers, AggregateLGBM, origins),
        rolling_origin(history, drivers, SeasonalNaive, origins),
    ])
    print(f"rolling origin for (b) and naive: {time.perf_counter() - began:.1f}s")
    actual = daily_partner_table(history)[["date", "partner", "outflow"]]
    summary = summarize(preds, actual, by=("model", "partner"))
    scores = summary.pivot(index="partner", columns="model", values="pinball_q90")
    print(scores)
    assert len(scores) == 6
    assert (scores["aggregate_drivers"] < scores["seasonal_naive"]).sum() >= 4
    assert (scores["aggregate_drivers"] <= 1.10 * scores["seasonal_naive"]).all()


def test_model_c_adds_confirmed_back(history, drivers):
    origin = pd.Timestamp("2026-10-01")  # autodebit bills fall due on days 1..10
    dates = pd.date_range(origin, periods=7, freq="D")
    model = AggregateLGBM(use_obligations=True)
    assert model.name == "aggregate_drivers_obligations"
    model.fit(history[history["date"] < origin], drivers[drivers["date"] < origin])
    pred = model.predict(dates, drivers[drivers["date"] <= dates[-1]])
    assert list(pred.columns) == ["date", "partner", *QCOLS]
    assert len(pred) == 7 * 6
    confirmed = drivers.set_index("date").loc[dates].melt(
        value_vars=[c for c in drivers if c.startswith("confirmed_")], var_name="partner", value_name="confirmed",
        ignore_index=False,
    ).reset_index().assign(partner=lambda d: d["partner"].str.removeprefix("confirmed_"))
    joined = pred.merge(confirmed, on=["date", "partner"], how="left", validate="one_to_one").fillna({"confirmed": 0.0})
    assert joined["confirmed"].sum() > 0
    assert (joined["q05"] >= joined["confirmed"] - 1e-6).all()
    assert (joined[list(QCOLS)].diff(axis=1).iloc[:, 1:] >= 0).all().all()
