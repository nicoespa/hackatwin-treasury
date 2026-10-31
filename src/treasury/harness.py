"""Rolling-origin evaluation: refit at each origin, forecast the next ``horizon`` days."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date, timedelta

import pandas as pd

from treasury.models.base import QCOLS, Forecaster, daily_partner_table


def default_origins(end: date, n: int = 8, step_days: int = 7) -> list[date]:
    """``end - step_days * k`` for ``k = n..1``, oldest first.

    ``end`` is the last complete date of the data. With ``step_days >= horizon`` every origin's
    horizon ends before ``end``, so the forecast windows never run past the data.
    """
    return [end - timedelta(days=step_days * k) for k in range(n, 0, -1)]


def rolling_origin(
    history: pd.DataFrame,
    drivers: pd.DataFrame | None,
    model_factory: Callable[[], Forecaster],
    origins: Sequence[date],
    horizon: int = 7,
) -> pd.DataFrame:
    """Forecasts of ``origin .. origin + horizon - 1`` from a fresh model fit at every origin.

    ``history`` is the node table. Each model is fit on ``history`` and ``drivers`` rows dated
    before the origin; ``predict`` gets the drivers dated up to the last forecast date. Returns
    ``model, origin, date, horizon, partner, q05..q99, actual`` with ``actual`` the partner
    outflow on ``date``.
    """
    truth = daily_partner_table(history)[["date", "partner", "outflow"]].rename(columns={"outflow": "actual"})
    frames = []
    for origin in origins:
        start = pd.Timestamp(origin)
        dates = pd.date_range(start, periods=horizon, freq="D")
        model = model_factory()
        model.fit(history[history["date"] < start], None if drivers is None else drivers[drivers["date"] < start])
        pred = model.predict(dates, None if drivers is None else drivers[drivers["date"] <= dates[-1]])
        frames.append(
            pred.assign(
                model=model.name,
                origin=start,
                horizon=(pred["date"] - start).dt.days + 1,
            )
        )
    preds = pd.concat(frames, ignore_index=True)[["model", "origin", "date", "horizon", "partner", *QCOLS]]
    return preds.merge(truth, on=["date", "partner"], how="left", validate="many_to_one")
