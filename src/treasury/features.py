"""Drivers a forecaster may use: calendar features and the wide drivers table keyed by ``date``."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
import pandas as pd

from treasury.calendar import Calendar
from treasury.simulate.population import check_payday_hypothesis

NEW_USER_WINDOW_DAYS = 30


def calendar_features(dates: pd.DatetimeIndex, cal: Calendar, payday_hypothesis: str = "late") -> pd.DataFrame:
    """One row per date: ``date, dow, dom, bd_index, bd_to_month_end, is_business_day, is_holiday,
    is_sac_window, is_anses_window, payday_mass, is_first_bd, is_last_bd``.

    ``bd_index`` is the 1-based business day of the month (0 on non-business days) and
    ``payday_mass`` the payday hypothesis' probability at that index (0 outside 1..4).
    """
    mass = check_payday_hypothesis(payday_hypothesis)
    days = [d.date() for d in pd.DatetimeIndex(dates)]
    bd_index = np.array([cal.nth_business_day_of_month(d) for d in days])
    business = np.array([cal.is_business_day(d) for d in days])
    to_end = np.array([cal.business_days_to_month_end(d) for d in days])
    by_index = np.zeros(32)
    by_index[1 : len(mass) + 1] = mass
    return pd.DataFrame(
        {
            "date": pd.DatetimeIndex(dates),
            "dow": [d.weekday() for d in days],
            "dom": [d.day for d in days],
            "bd_index": bd_index,
            "bd_to_month_end": to_end,
            "is_business_day": business,
            "is_holiday": [d in cal.holidays for d in days],
            "is_sac_window": [cal.is_sac_window(d) for d in days],
            "is_anses_window": [cal.anses_window(d) for d in days],
            "payday_mass": by_index[bd_index],
            "is_first_bd": bd_index == 1,
            "is_last_bd": business & (to_end == 0),
        }
    )


def _users_active(activation: pd.Series, dates: pd.DatetimeIndex) -> np.ndarray:
    """Users with ``activation_date <= date`` for every date."""
    sorted_days = np.sort(activation.dt.normalize().to_numpy())
    return np.searchsorted(sorted_days, dates.to_numpy(), side="right")


COHORT_PREFIXES = ("n_active_", "n_new_30d_")


def cohort_drivers(users: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
    """``date`` plus, per ``users["segment"]`` (sorted), ``n_active_<segment>`` (users with
    ``activation_date <= date``) and ``n_new_30d_<segment>`` (activated in ``(date - 30, date]``)."""
    dates = pd.DatetimeIndex(dates)
    out = pd.DataFrame({"date": dates})
    for segment, group in users.groupby("segment", sort=True):
        active = _users_active(group["activation_date"], dates)
        before = _users_active(group["activation_date"], dates - pd.Timedelta(days=NEW_USER_WINDOW_DAYS))
        out[f"n_active_{segment}"] = active
        out[f"n_new_30d_{segment}"] = active - before
    return out


def build_drivers(
    users: pd.DataFrame,
    events_routed: pd.DataFrame,
    dates: pd.DatetimeIndex,
    scenarios: Sequence = (),
    fx: pd.DataFrame | None = None,
    market: Mapping | None = None,
    settle_lags: Mapping[str, tuple[Calendar, int]] | None = None,
) -> pd.DataFrame:
    """Wide drivers table, one row per date of ``dates``, built only from what is known ahead.

    - ``n_active_<segment>``: users of the segment with ``activation_date <= date``. Activation
      cohorts are planned, so the count is known at any origin; no realized activity enters it.
    - ``n_new_30d_<segment>``: users of the segment activated in ``(date - 30, date]``.
    - ``campaign_lift_<product>``: product over ``scenarios`` of ``multiplier(date, segment,
      product)`` (1.0 without scenarios). Campaigns are segment-independent, so one segment is used.
    - ``confirmed_<partner>``: summed ``amount`` of confirmed outflows (``confirmed`` and
      ``direction == 1``) by settlement date and partner. Confirmed events are autodebit bills
      with a fixed amount and due date, so they are known ahead of their settlement date.

    The international variant adds, after those (the domestic table is unchanged without them):

    - ``fx_*`` from ``fx.fx_drivers(fx, market)``: exchange rates and their recent change. They are
      realized values; ``known_at`` freezes them at the forecast origin, so a forecast only sees the
      latest rates before it.
    - ``tourism_index``: the tourism-season calendar of ``market``, known ahead.
    - ``settles_<partner>``: for each ``settle_lags`` partner (a lagged partner abroad, settling
      ``lag`` business days later on its country's calendar), the calendar days of events that
      settle on the date (``settle_load``): 0 on its non-business days, more after a weekend or a
      holiday there. Known ahead from the calendar.

    The amount of an unconfirmed event is never read, so realized flows cannot leak in.
    """
    dates = pd.DatetimeIndex(dates)
    out = cohort_drivers(users, dates)

    segment = str(users["segment"].min())
    for product in sorted(events_routed["product"].unique()):
        out[f"campaign_lift_{product}"] = [
            float(np.prod([s.multiplier(d.date(), segment, product) for s in scenarios])) for d in dates
        ]

    known = events_routed["confirmed"].to_numpy() & (events_routed["direction"].to_numpy() == 1)
    confirmed = events_routed.loc[known, ["settle_at", "partner", "amount"]]
    by_day = confirmed.groupby([confirmed["settle_at"].dt.normalize().rename("date"), "partner"])["amount"].sum()
    wide = by_day.unstack("partner").reindex(index=dates, columns=sorted(events_routed["partner"].unique()))
    for partner in wide.columns:
        out[f"confirmed_{partner}"] = wide[partner].fillna(0.0).to_numpy()
    if fx is not None:
        from treasury.fx import fx_drivers

        extra = fx_drivers(fx, market or {}, dates)
        out = pd.concat([out, extra.drop(columns="date")], axis=1)
    for partner, (pcal, lag) in sorted((settle_lags or {}).items()):
        out[f"settles_{partner}"] = [settle_load(pcal, lag, d.date()) for d in dates]
    return out


def settle_load(cal: Calendar, lag: int, d) -> float:
    """Calendar days of events that a partner settling ``lag`` business days later on ``cal``
    settles on ``d``: 0 if ``d`` is not a business day, else the days between the business days
    ``lag`` and ``lag + 1`` before it (3 on the Tuesday of a T+1 partner, 4 after a Monday
    holiday). NaN when that reaches outside the calendar's coverage."""
    if not cal.is_business_day(d):
        return 0.0
    try:
        return float((cal.add_business_days(d, -lag) - cal.add_business_days(d, -lag - 1)).days)
    except ValueError:
        return float("nan")


def known_at(drivers: pd.DataFrame, origin: pd.Timestamp) -> pd.DataFrame:
    """``drivers`` as known at ``origin``: every ``fx_*`` column on and after ``origin`` takes its
    value on the last date before it (a random-walk forecast of the rate). Unchanged, the same
    object, when there is no ``fx_*`` column."""
    cols = [c for c in drivers if c.startswith("fx_")]
    if not cols:
        return drivers
    out = drivers.copy()
    later = out["date"] >= pd.Timestamp(origin)
    before = out.loc[~later].sort_values("date")
    out.loc[later, cols] = before[cols].iloc[-1].to_numpy() if len(before) else np.nan
    return out
