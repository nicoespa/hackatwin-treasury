"""Obligations layer: outflows known ahead of time, and recurring payments detected from history.

Anti-double-counting rule: confirmed outflows are known ahead, so a model trained on the residual
(``outflow - confirmed_outflow``, see ``split_residual``) adds each confirmed amount back exactly
once at prediction time; a model trained on gross ``outflow`` must not add it again.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

MONTHLY_PERIOD_DAYS = (27, 33)  # a median gap in this range is a calendar-monthly bill


def confirmed_obligations(
    events_routed: pd.DataFrame, as_of: pd.Timestamp, horizon_dates: pd.DatetimeIndex
) -> pd.DataFrame:
    """Confirmed outflows settling on ``horizon_dates``: ``date, partner, amount``, one row per
    (date, partner) with any.

    These are autodebit bills with a fixed amount and due date, known at ``as_of`` by construction;
    ``as_of`` is kept in the signature for the audit trail.
    """
    rows = events_routed[events_routed["confirmed"] & (events_routed["direction"] == 1)]
    day = rows["settle_at"].dt.normalize().rename("date")
    rows = rows[day.isin(pd.DatetimeIndex(horizon_dates))]
    out = rows.groupby([day[rows.index], "partner"])["amount"].sum().reset_index()
    return out[["date", "partner", "amount"]]


def detect_recurring(
    events_routed: pd.DataFrame,
    as_of: pd.Timestamp,
    min_occurrences: int = 3,
    tolerance_days: int = 3,
) -> pd.DataFrame:
    """Recurring payment streams per (user, counterparty) from events before ``as_of``.

    Columns ``user_id, counterparty, partner, period_days, next_date, p_occur, amount_median``.
    ``period_days`` is the median gap in days between consecutive payments; a stream is kept with
    at least ``min_occurrences`` payments and every gap within ``tolerance_days`` of that median.
    ``next_date`` is the last payment plus one calendar month when the period is monthly
    (``MONTHLY_PERIOD_DAYS``), else plus the rounded period. ``p_occur`` is payments over the
    periods expected from the first payment to ``as_of``, clipped to [0, 1].
    """
    as_of = pd.Timestamp(as_of)
    keys = ["user_id", "counterparty"]
    ev = events_routed.loc[
        (events_routed["at"] < as_of) & (events_routed["counterparty"] != ""), [*keys, "partner", "at", "amount"]
    ].assign(day=lambda d: d["at"].dt.normalize())
    ev = ev.sort_values([*keys, "day"], kind="stable")
    ev["gap"] = ev.groupby(keys)["day"].diff().dt.days
    ev["median_gap"] = ev.groupby(keys)["gap"].transform("median")
    ev["dev"] = (ev["gap"] - ev["median_gap"]).abs()
    streams = ev.groupby(keys).agg(
        partner=("partner", "last"),
        n=("day", "size"),
        first=("day", "first"),
        last=("day", "last"),
        period_days=("median_gap", "first"),
        spread=("dev", "max"),
        amount_median=("amount", "median"),
    )
    streams = streams[(streams["n"] >= min_occurrences) & (streams["spread"] <= tolerance_days)].reset_index()

    period = streams["period_days"].to_numpy(float)
    monthly = (period >= MONTHLY_PERIOD_DAYS[0]) & (period <= MONTHLY_PERIOD_DAYS[1])
    plus_month = streams["last"] + pd.DateOffset(months=1)
    plus_period = streams["last"] + pd.to_timedelta(np.round(period), unit="D")
    streams["next_date"] = plus_month.where(monthly, plus_period)
    expected = np.floor((as_of - streams["first"]).dt.days.to_numpy() / period) + 1
    streams["p_occur"] = np.clip(streams["n"].to_numpy() / expected, 0.0, 1.0)
    return streams[["user_id", "counterparty", "partner", "period_days", "next_date", "p_occur", "amount_median"]]


def split_residual(history: pd.DataFrame) -> pd.DataFrame:
    """Copy of the node table with ``outflow_residual = max(outflow - confirmed_outflow, 0)``.

    The node table already carries the confirmed part of each node's outflow, so the residual is
    the part a model must forecast; the confirmed part is added back once at prediction time.
    """
    out = history.copy()
    out["outflow_residual"] = np.clip(out["outflow"].to_numpy() - out["confirmed_outflow"].to_numpy(), 0.0, None)
    return out
