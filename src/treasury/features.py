"""Drivers a forecaster may use: calendar features and the wide drivers table keyed by ``date``."""

from __future__ import annotations

from collections.abc import Sequence

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


def build_drivers(
    users: pd.DataFrame,
    events_routed: pd.DataFrame,
    dates: pd.DatetimeIndex,
    scenarios: Sequence = (),
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

    The amount of an unconfirmed event is never read, so realized flows cannot leak in.
    """
    dates = pd.DatetimeIndex(dates)
    out = pd.DataFrame({"date": dates})
    for segment, group in users.groupby("segment", sort=True):
        active = _users_active(group["activation_date"], dates)
        before = _users_active(group["activation_date"], dates - pd.Timedelta(days=NEW_USER_WINDOW_DAYS))
        out[f"n_active_{segment}"] = active
        out[f"n_new_30d_{segment}"] = active - before

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
    return out
