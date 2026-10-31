"""Intraday balance engine for a prefunded partner account."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

# Order of application among events sharing a timestamp.
_CREDIT, _INFLOW, _OUTFLOW = 0, 1, 2


@dataclass(frozen=True)
class Flow:
    """Movement on the partner balance: positive is an outflow, negative an inflow."""

    at: pd.Timestamp
    amount: float


@dataclass(frozen=True)
class Credit:
    """Replenishment that becomes available at ``at``."""

    at: pd.Timestamp
    amount: float


@dataclass(frozen=True)
class DepositResult:
    amount: float
    unresolvable: bool
    first_shortfall: pd.Timestamp | None


def balance_path(
    opening_available: float, flows: Sequence[Flow], credits: Sequence[Credit]
) -> pd.DataFrame:
    """Running balance after each event, as columns ``at, delta, balance``.

    Events are sorted by ``at``; at equal timestamps credits apply first, then
    inflows, then outflows.
    """
    at = pd.DatetimeIndex([c.at for c in credits] + [f.at for f in flows]).as_unit("ns")
    credit_amounts = np.fromiter((c.amount for c in credits), float, len(credits))
    flow_amounts = np.fromiter((f.amount for f in flows), float, len(flows))
    delta = np.concatenate([credit_amounts, -flow_amounts])
    rank = np.concatenate(
        [
            np.full(len(credits), _CREDIT),
            np.where(flow_amounts < 0, _INFLOW, _OUTFLOW),
        ]
    )
    order = np.lexsort((rank, at.asi8))
    delta = delta[order]
    return pd.DataFrame(
        {
            "at": at[order],
            "delta": delta,
            "balance": opening_available + np.cumsum(delta),
        }
    )


def max_need(path: pd.DataFrame, opening_available: float) -> float:
    """Largest cumulative net debit against the opening balance (0 if never below it)."""
    if path.empty:
        return 0.0
    return max(0.0, opening_available - float(path["balance"].min()))


def first_shortfall(path: pd.DataFrame) -> pd.Timestamp | None:
    """First ``at`` where the balance is negative, or None."""
    negative = path["balance"].to_numpy() < 0
    if not negative.any():
        return None
    return path["at"].iloc[int(negative.argmax())]


def min_deposit(
    opening_available: float,
    flows: Sequence[Flow],
    credits: Sequence[Credit],
    arrival_at: pd.Timestamp,
) -> DepositResult:
    """Smallest credit arriving at ``arrival_at`` that keeps every later balance >= 0.

    A shortfall before arrival cannot be fixed by this deposit: it is flagged as
    ``unresolvable`` and the balance it leaves is carried into the arrival, so
    ``amount`` also has to absorb it.
    """
    path = balance_path(opening_available, flows, credits)
    balance = path["balance"].to_numpy()
    after = path["at"].to_numpy() >= np.datetime64(pd.Timestamp(arrival_at).as_unit("ns"))
    amount = max(0.0, -float(balance[after].min())) if after.any() else 0.0
    return DepositResult(
        amount=amount,
        unresolvable=bool((balance[~after] < 0).any()),
        first_shortfall=first_shortfall(path),
    )
