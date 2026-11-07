"""Funding decisions: how much to send a partner at each review, from forecast paths or a fixed buffer."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from treasury.calendar import Calendar
from treasury.ledger import Credit, min_deposit_paths
from treasury.rails import Rail, arrival_time
from treasury.routing import Partner


@dataclass(frozen=True)
class PolicyConfig:
    alpha: float
    cost_of_capital_annual: float
    cost_per_usd_rejected: float
    lot_size: float
    review_hour: int
    fixed_buffer_days: float
    review_hours_247: tuple[int, ...] = (9, 18)
    # Place a lagged partner's later-day outflow at its settle_cutoff_hour, when it settles, instead
    # of 00:00 (the domestic default keeps 00:00, so a credit landing that day never covers it).
    place_lagged_at_cutoff: bool = False
    # Sweep: on 24/7 rails, a review that deposits nothing withdraws the balance above the window's
    # target back to the wallet's pool, when it exceeds sweep_min_share of that target.
    sweep: bool = False
    sweep_min_share: float = 0.1
    sweep_headroom: float = 0.0  # keep target × (1 + headroom) at the partner after a sweep


def load_policy(path: str | Path) -> PolicyConfig:
    raw = yaml.safe_load(Path(path).read_text())
    raw.pop("tiers", None)  # approval tiers belong to the agent's queue (agent.queue.load_tiers)
    raw.pop("autonomy", None)  # autonomous-execution limits (agent.guardrails.load_autonomy)
    return PolicyConfig(**{**raw, "review_hours_247": tuple(raw.get("review_hours_247", (9, 18)))})


@dataclass(frozen=True)
class Decision:
    """A review's recommendation. ``p_unresolvable`` and ``expected_shortfall_if_none`` are NaN
    and the times None for the fixed buffer, which looks at no forecast."""

    amount: float
    p_unresolvable: float
    target: float
    expected_shortfall_if_none: float
    arrival_at: pd.Timestamp | None
    window_end: pd.Timestamp | None


def ceil_to_lot(amount: float, lot_size: float) -> float:
    return float(lot_size * math.ceil(round(amount / lot_size, 9))) if amount > 0 else 0.0


def target_balance(need_samples: np.ndarray, alpha: float) -> float:
    """The balance that covers the need in a share ``alpha`` of the samples."""
    return float(np.quantile(need_samples, alpha))


def next_review(rail: Rail, at: pd.Timestamp, cfg: PolicyConfig) -> pd.Timestamp:
    """The review after ``at``: next day at ``review_hour`` on business-day rails (the arrival of an
    order from a non-business day equals that of the next business day's review), else the next of
    ``review_hours_247`` today or the first one tomorrow."""
    at = pd.Timestamp(at)
    day = at.normalize()
    if rail.business_days_only:
        return day + pd.Timedelta(days=1, hours=cfg.review_hour)
    later = [h for h in sorted(cfg.review_hours_247) if day + pd.Timedelta(hours=h) > at]
    return day + pd.Timedelta(hours=later[0]) if later else day + pd.Timedelta(days=1, hours=min(cfg.review_hours_247))


def review_times(rail: Rail, start: pd.Timestamp, stop: pd.Timestamp, cal: Calendar, cfg: PolicyConfig) -> list[pd.Timestamp]:
    """Review instants in ``[start, stop)``: ``review_hour`` on business days for business-day rails
    (no instruction is possible on other days), every ``review_hours_247`` hour daily otherwise."""
    hours = (cfg.review_hour,) if rail.business_days_only else tuple(sorted(cfg.review_hours_247))
    times = []
    for day in pd.date_range(pd.Timestamp(start).normalize(), pd.Timestamp(stop), freq="D"):
        if rail.business_days_only and not cal.is_business_day(day.date()):
            continue
        times += [t for h in hours if start <= (t := day + pd.Timedelta(hours=h)) < stop]
    return times


def window_flows(
    paths_partner: np.ndarray,
    dates: pd.DatetimeIndex,
    partner: Partner,
    review_at: pd.Timestamp,
    window_end: pd.Timestamp,
    realized_today: float = 0.0,
    inflow_forecast: np.ndarray | None = None,
    lagged_at_cutoff: bool = False,
) -> tuple[pd.DatetimeIndex, np.ndarray]:
    """Forecast flows of every date in ``[review_at, window_end]``: ``(at, amounts [n_paths, n_flows])``.

    Placement is conservative. A later day's outflow sits at 00:00, so a credit landing during the
    day never covers it; with ``lagged_at_cutoff`` (for a lagged partner, whose events all settle
    at its ``settle_cutoff_hour``) it sits at that hour instead, dropped if after ``window_end``,
    and so does the review day's when the review comes before that hour; for a partner that nets inflows, that day's ``inflow_forecast`` is a
    negative flow at its ``settle_cutoff_hour`` (dropped if after ``window_end``). On the review
    day only the outflow still to come, ``max(0, path - realized_today)``, enters at ``review_at``,
    with no inflow credit.
    """
    at: list[pd.Timestamp] = []
    cols: list[np.ndarray] = []
    today = review_at.normalize()
    for j in np.flatnonzero((dates >= today) & (dates <= window_end.normalize())):
        day = dates[j]
        settles = day + pd.Timedelta(hours=partner.settle_cutoff_hour)
        if day == today:
            if lagged_at_cutoff and review_at < settles:  # today's settlement is still ahead, all of it
                if settles <= window_end:
                    at.append(settles)
                    cols.append(np.maximum(0.0, paths_partner[:, j] - realized_today))
            else:
                at.append(review_at)
                cols.append(np.maximum(0.0, paths_partner[:, j] - realized_today))
            continue
        outflow_at = settles if lagged_at_cutoff else day
        if outflow_at <= window_end:
            at.append(outflow_at)
            cols.append(paths_partner[:, j])
        inflow_at = day + pd.Timedelta(hours=partner.settle_cutoff_hour)
        if partner.nets_inflows and inflow_forecast is not None and inflow_at <= window_end:
            at.append(inflow_at)
            cols.append(np.full(len(paths_partner), -float(inflow_forecast[j])))
    amounts = np.column_stack(cols) if cols else np.zeros((len(paths_partner), 0))
    return pd.DatetimeIndex(at), amounts


def recommend_deposit(
    paths_partner: np.ndarray,
    dates: pd.DatetimeIndex,
    partner: Partner,
    rail: Rail,
    opening_available: float,
    pending_credits: Sequence[Credit],
    review_at: pd.Timestamp,
    cal: Calendar,
    policy_cfg: PolicyConfig,
    *,
    realized_today: float = 0.0,
    inflow_forecast: np.ndarray | None = None,
) -> Decision:
    """Deposit to instruct at ``review_at`` so the balance survives until the next order can land.

    The order lands at ``arrival_at = arrival_time(rail, review_at)``; the window it protects ends
    when the next review's order lands (``window_end``). Per path (``paths_partner`` is
    ``[n_paths, n_dates]`` of daily outflow on ``dates``) the flows of ``window_flows`` go through
    ``min_deposit_paths``; ``amount`` is the ``alpha``-quantile of the per-path minimum deposits
    rounded up to ``lot_size``, ``p_unresolvable`` the share of paths short before the arrival,
    ``target`` the ``alpha``-quantile of the per-path need over the window, and
    ``expected_shortfall_if_none`` the mean of ``max(0, need - opening - pending credits landing in
    the window)``.
    """
    review_at = pd.Timestamp(review_at)
    arrival = arrival_time(rail, review_at, cal)
    window_end = arrival_time(rail, next_review(rail, review_at, policy_cfg), cal)
    paths_partner = np.atleast_2d(np.asarray(paths_partner, float))
    at, amounts = window_flows(
        paths_partner, pd.DatetimeIndex(dates), partner, review_at, window_end, realized_today, inflow_forecast,
        lagged_at_cutoff=policy_cfg.place_lagged_at_cutoff and not partner.is_realtime,
    )
    result = min_deposit_paths(opening_available, at, amounts, pending_credits, arrival)
    landing = sum(c.amount for c in pending_credits if c.at <= window_end)
    return Decision(
        amount=ceil_to_lot(float(np.quantile(result.amount, policy_cfg.alpha)), policy_cfg.lot_size),
        p_unresolvable=float(result.unresolvable.mean()),
        target=target_balance(result.need, policy_cfg.alpha),
        expected_shortfall_if_none=float(np.maximum(0.0, result.need - opening_available - landing).mean()),
        arrival_at=arrival,
        window_end=window_end,
    )


def recommend_sweep(decision: Decision, opening_available: float, rail: Rail, policy_cfg: PolicyConfig,
                    rest_of_day: float = 0.0) -> float:
    """Amount to withdraw now from a partner back to the wallet's pool (0 when none).

    Only with ``policy_cfg.sweep``, on a rail that moves money any day and hour (a withdrawal at night
    or on a weekend has to land before banks open), and only when the review deposits nothing. The
    balance left must still cover the window's ``target`` (the ``alpha``-quantile of what the partner
    can pay out until the next order lands) times ``1 + sweep_headroom``; credits still in transit are not counted, so the balance
    alone covers the flows before they land. Below ``sweep_min_share`` of the target the move is not
    worth its fee. Rounded down to ``lot_size``.

    ``rest_of_day`` is what the partner can still pay out before midnight (``rest_of_day_need``). The
    window's target counts today's outflow as the forecast minus what already settled, which drops to
    zero on a day running above forecast, exactly when more is likely to come; the balance kept is at
    least ``rest_of_day``."""
    if not policy_cfg.sweep or rail.business_days_only or decision.amount > 0:
        return 0.0
    surplus = opening_available - max(decision.target, rest_of_day) * (1 + policy_cfg.sweep_headroom)
    if surplus <= 0 or surplus < policy_cfg.sweep_min_share * decision.target:
        return 0.0
    return float(policy_cfg.lot_size * np.floor(surplus / policy_cfg.lot_size))


def rest_of_day_need(paths_today: np.ndarray, partner: Partner, at: pd.Timestamp, alpha: float) -> float:
    """``alpha``-quantile of today's outflow paths times the share of the day still ahead at ``at``: the
    hours left for a partner that settles all day, all of it before a lagged partner's cutoff hour and
    nothing after it."""
    at = pd.Timestamp(at)
    hour = at.hour + at.minute / 60
    if partner.is_realtime:
        share = max(0.0, 24 - hour) / 24
    else:
        share = 1.0 if hour < partner.settle_cutoff_hour else 0.0
    return float(np.quantile(np.asarray(paths_today, float), alpha) * share)


def fixed_buffer_decision(trailing_daily_mean: float, days: float, opening_available: float, lot_size: float) -> Decision:
    """Reference rule (Marqeta-style): top the position up to ``days`` of trailing mean drain."""
    target = days * max(trailing_daily_mean, 0.0)
    return Decision(
        amount=ceil_to_lot(target - opening_available, lot_size),
        p_unresolvable=float("nan"),
        target=target,
        expected_shortfall_if_none=float("nan"),
        arrival_at=None,
        window_end=None,
    )
