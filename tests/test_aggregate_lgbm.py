import time
from datetime import date

import pandas as pd

from treasury.harness import default_origins, rolling_origin
from treasury.metrics import summarize
from treasury.models.aggregate_lgbm import AggregateLGBM
from treasury.models.base import QCOLS, daily_partner_table
from treasury.models.seasonal_naive import SeasonalNaive

END = date(2026, 10, 31)


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
