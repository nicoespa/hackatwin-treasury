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


def _application_order(credit_at: np.ndarray, flow_at: np.ndarray, flow_is_inflow: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Times of ``credits + flows`` in application order and the permutation into that order.

    Events are sorted by time; at equal timestamps credits apply first, then inflows, then outflows.
    """
    at = np.concatenate([np.asarray(credit_at, "datetime64[ns]"), np.asarray(flow_at, "datetime64[ns]")])
    rank = np.concatenate([np.full(len(credit_at), _CREDIT), np.where(flow_is_inflow, _INFLOW, _OUTFLOW)])
    order = np.lexsort((rank, at.view(np.int64)))
    return at[order], order


def balance_arrays(
    opening_available: float,
    flow_at: np.ndarray,
    flow_amounts: np.ndarray,
    credit_at: np.ndarray,
    credit_amounts: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``balance_path`` on arrays: ``(at, delta, balance)`` in application order."""
    flow_amounts = np.asarray(flow_amounts, float)
    at, order = _application_order(credit_at, flow_at, flow_amounts < 0)
    delta = np.concatenate([np.asarray(credit_amounts, float), -flow_amounts])[order]
    return at, delta, opening_available + np.cumsum(delta)


def balance_path(
    opening_available: float, flows: Sequence[Flow], credits: Sequence[Credit]
) -> pd.DataFrame:
    """Running balance after each event, as columns ``at, delta, balance``.

    Events are sorted by ``at``; at equal timestamps credits apply first, then
    inflows, then outflows.
    """
    at, delta, balance = balance_arrays(
        opening_available,
        pd.DatetimeIndex([f.at for f in flows]).as_unit("ns").to_numpy(),
        np.fromiter((f.amount for f in flows), float, len(flows)),
        pd.DatetimeIndex([c.at for c in credits]).as_unit("ns").to_numpy(),
        np.fromiter((c.amount for c in credits), float, len(credits)),
    )
    return pd.DataFrame({"at": pd.DatetimeIndex(at), "delta": delta, "balance": balance})


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


@dataclass(frozen=True)
class PathDeposits:
    """``min_deposit`` and ``max_need`` for every path of a Monte Carlo set (arrays ``[n_paths]``)."""

    amount: np.ndarray
    unresolvable: np.ndarray
    need: np.ndarray


def min_deposit_paths(
    opening_available: float,
    flow_at: pd.DatetimeIndex,
    flow_amounts: np.ndarray,
    credits: Sequence[Credit],
    arrival_at: pd.Timestamp,
) -> PathDeposits:
    """``min_deposit`` per path for paths that share flow times but not amounts.

    ``flow_amounts`` is ``[n_paths, n_flows]`` (positive outflow, negative inflow) at ``flow_at``;
    a column must not mix signs, since sign decides the order at equal timestamps. Path ``i``
    gives the same ``amount`` and ``unresolvable`` as ``min_deposit`` on its flows, and ``need``
    is ``max_need`` of its balance path without credits.
    """
    amounts = np.atleast_2d(np.asarray(flow_amounts, float))
    inflow = (amounts < 0).any(axis=0)
    if (inflow & (amounts > 0).any(axis=0)).any():
        raise ValueError("a flow column mixes inflow and outflow amounts across paths")
    flow_at = pd.DatetimeIndex(flow_at).as_unit("ns").to_numpy()
    credit_at = pd.DatetimeIndex([c.at for c in credits]).as_unit("ns").to_numpy()
    credit_amounts = np.fromiter((c.amount for c in credits), float, len(credits))
    at, order = _application_order(credit_at, flow_at, inflow)
    delta = np.concatenate([np.broadcast_to(credit_amounts, (len(amounts), len(credits))), -amounts], axis=1)
    balance = opening_available + np.cumsum(delta[:, order], axis=1)
    after = at >= np.datetime64(pd.Timestamp(arrival_at).as_unit("ns"))
    post_min = balance[:, after].min(axis=1) if after.any() else np.zeros(len(amounts))
    flows_only = np.cumsum(-amounts[:, np.lexsort((~inflow, flow_at.view(np.int64)))], axis=1)
    lowest = flows_only.min(axis=1) if flows_only.shape[1] else np.zeros(len(amounts))
    return PathDeposits(
        amount=np.maximum(0.0, -post_min),
        unresolvable=(balance[:, ~after] < 0).any(axis=1),
        need=np.maximum(0.0, -lowest),
    )
