"""Daily tables every forecaster consumes and the ``Forecaster`` protocol they implement."""

from __future__ import annotations

from typing import Protocol

import numpy as np
import pandas as pd

QUANTILES = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99)
QCOLS = ("q05", "q10", "q25", "q50", "q75", "q90", "q95", "q99")

NODE = ["segment", "product", "partner"]
FLOWS = ["outflow", "inflow", "confirmed_outflow"]


def daily_node_table(events_routed: pd.DataFrame) -> pd.DataFrame:
    """Daily flows per (segment, product, partner) node, by settlement date.

    Columns ``date, segment, product, partner, outflow, inflow, confirmed_outflow``: ``outflow``
    sums ``amount`` where ``direction == 1``, ``inflow`` where ``direction == -1``, and
    ``confirmed_outflow`` the confirmed part of ``outflow``. Every node that occurs gets a row on
    every date of the data's settlement range, zero when nothing settled.
    """
    out = events_routed["direction"].to_numpy() == 1
    amount = events_routed["amount"].to_numpy()
    flows = pd.DataFrame(
        {
            "date": events_routed["settle_at"].dt.normalize(),
            **{col: events_routed[col] for col in NODE},
            "outflow": np.where(out, amount, 0.0),
            "inflow": np.where(out, 0.0, amount),
            "confirmed_outflow": np.where(out & events_routed["confirmed"].to_numpy(), amount, 0.0),
        }
    )
    daily = flows.groupby(["date", *NODE])[FLOWS].sum()
    dates = pd.date_range(flows["date"].min(), flows["date"].max(), freq="D", name="date")
    nodes = daily.index.droplevel("date").unique()
    dense = pd.MultiIndex.from_tuples(
        [(d, *node) for d in dates for node in nodes], names=["date", *NODE]
    )
    return daily.reindex(dense, fill_value=0.0).reset_index()


def daily_partner_table(node_table: pd.DataFrame) -> pd.DataFrame:
    """Node table summed per partner: ``date, partner, outflow, inflow, net, confirmed_outflow``.

    Dense over the node table's dates × partners; ``net = outflow - inflow``.
    """
    daily = node_table.groupby(["date", "partner"])[FLOWS].sum()
    dense = pd.MultiIndex.from_product(
        [daily.index.unique("date"), daily.index.unique("partner")], names=["date", "partner"]
    )
    daily = daily.reindex(dense, fill_value=0.0).reset_index()
    daily["net"] = daily["outflow"] - daily["inflow"]
    return daily[["date", "partner", "outflow", "inflow", "net", "confirmed_outflow"]]


def enforce_quantiles(df: pd.DataFrame) -> pd.DataFrame:
    """Copy of ``df`` with the quantile columns sorted per row (non-crossing) and clipped at 0."""
    out = df.copy()
    cols = list(QCOLS)
    out[cols] = np.clip(np.sort(out[cols].to_numpy(dtype=float), axis=1), 0.0, None)
    return out


class Forecaster(Protocol):
    """Probabilistic forecaster of partner-level daily gross ``outflow``.

    ``history`` is the node table (``daily_node_table``) up to the forecast origin; ``drivers``
    is an optional frame keyed by ``date``. ``predict`` returns ``date, partner, q05..q99`` with
    quantiles passed through ``enforce_quantiles``.
    """

    name: str

    def fit(self, history: pd.DataFrame, drivers: pd.DataFrame | None) -> None: ...

    def predict(self, dates: pd.DatetimeIndex, drivers: pd.DataFrame | None) -> pd.DataFrame: ...
