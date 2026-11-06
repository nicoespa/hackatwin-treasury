"""Partners and the routing of user events to the time they hit a partner balance."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from treasury.calendar import Calendar

# Products that credit the partner balance (direction -1); every other product drains it.
INFLOW_PRODUCTS = frozenset({"card_refund", "fci_redemption", "crypto_sell", "cash_in"})
INTL_INFLOW_PRODUCTS = frozenset({"intl_card_refund", "usd_income"})  # the international variant's
HOME_COUNTRY = "ar"


@dataclass(frozen=True)
class Partner:
    id: str
    products: tuple[str, ...]
    settle_lag_business_days: int
    settle_cutoff_hour: int
    same_day_before_cutoff: bool
    nets_inflows: bool
    accepts_rails: tuple[str, ...]
    country: str = HOME_COUNTRY  # whose bank calendar its settlement lag counts
    currency: str = "ARS"  # of its balance and of the amounts of its products

    @property
    def is_realtime(self) -> bool:
        return self.settle_lag_business_days == 0 and self.same_day_before_cutoff


@dataclass(frozen=True)
class RouteOverride:
    """Route ``product`` events dated in ``[start, end]`` to ``partner_id`` instead."""

    product: str
    start: date
    end: date
    partner_id: str


def load_partners(path: str | Path) -> dict[str, Partner]:
    raw = yaml.safe_load(Path(path).read_text())
    partners: dict[str, Partner] = {}
    owner: dict[str, str] = {}
    for pid, fields in raw.items():
        partner = Partner(
            id=pid,
            products=tuple(fields["products"]),
            settle_lag_business_days=fields["settle_lag_business_days"],
            settle_cutoff_hour=fields["settle_cutoff_hour"],
            same_day_before_cutoff=fields["same_day_before_cutoff"],
            nets_inflows=fields["nets_inflows"],
            accepts_rails=tuple(fields["accepts_rails"]),
            country=fields.get("country", HOME_COUNTRY),
            currency=fields.get("currency", "ARS"),
        )
        for product in partner.products:
            if product in owner:
                raise ValueError(f"product {product!r} is listed by both {owner[product]!r} and {pid!r}")
            owner[product] = pid
        partners[pid] = partner
    return partners


def partner_for_product(product: str, partners: Mapping[str, Partner]) -> Partner:
    for partner in partners.values():
        if product in partner.products:
            return partner
    raise KeyError(f"no partner settles product {product!r}")


def _lagged_settle(day: date, before_cutoff: bool, partner: Partner, cal: Calendar) -> pd.Timestamp:
    # From a non-business day, add_business_days(day, 1) lands on the first business day after it.
    day0 = day if cal.is_business_day(day) and before_cutoff else cal.add_business_days(day, 1)
    settle_day = cal.add_business_days(day0, partner.settle_lag_business_days)
    return pd.Timestamp(settle_day) + pd.Timedelta(hours=partner.settle_cutoff_hour)


def settle_at(event_at: pd.Timestamp, partner: Partner, cal: Calendar) -> pd.Timestamp:
    """When an event at ``event_at`` moves ``partner``'s balance.

    Real-time partners (lag 0, same day before cutoff) settle at ``event_at`` itself,
    weekends included; their cutoff hour plays no part. Lagged partners count from
    the event date if it is a business day before the cutoff, else from the next
    business day, and settle ``settle_lag_business_days`` later at the cutoff hour.
    """
    event_at = pd.Timestamp(event_at)
    if partner.is_realtime:
        return event_at
    return _lagged_settle(event_at.date(), event_at.hour < partner.settle_cutoff_hour, partner, cal)


def route_events(
    events: pd.DataFrame,
    partners: Mapping[str, Partner],
    cal: Calendar,
    overrides: Sequence[RouteOverride] | None = None,
    partner_cals: Mapping[str, Calendar] | None = None,
) -> pd.DataFrame:
    """Return a copy of ``events`` with ``partner``, ``settle_at`` and ``direction`` added.

    ``direction`` is +1 for outflows and -1 for products in ``INFLOW_PRODUCTS`` or
    ``INTL_INFLOW_PRODUCTS``. A lagged partner
    counts its lag on ``partner_cals[partner]`` when given (its country's calendar), else on ``cal``.
    Lagged settlement is computed once per (partner, date, before-cutoff) rather than per row.
    """
    routed = events.copy()
    owner = {product: partner.id for partner in partners.values() for product in partner.products}
    unknown = sorted(set(routed["product"].unique()) - set(owner))
    if unknown:
        raise KeyError(f"no partner settles product(s) {unknown}")

    partner_ids = routed["product"].map(owner)
    days = routed["at"].dt.normalize()
    for override in overrides or ():
        if override.partner_id not in partners:
            raise KeyError(f"override routes to unknown partner {override.partner_id!r}")
        window = days.between(pd.Timestamp(override.start), pd.Timestamp(override.end))
        partner_ids = partner_ids.mask((routed["product"] == override.product) & window, override.partner_id)
    routed["partner"] = partner_ids

    settle = routed["at"].copy()
    for pid in partner_ids.unique():
        partner = partners[pid]
        if partner.is_realtime:
            continue
        rows = partner_ids == pid
        day = days[rows]
        before = routed.loc[rows, "at"].dt.hour < partner.settle_cutoff_hour
        pcal = (partner_cals or {}).get(pid, cal)
        on_time = {d: _lagged_settle(d.date(), True, partner, pcal) for d in day.unique()}
        late = {d: _lagged_settle(d.date(), False, partner, pcal) for d in day.unique()}
        settle[rows] = day.map(on_time).where(before, day.map(late))
    routed["settle_at"] = settle

    inflow = routed["product"].isin(INFLOW_PRODUCTS | INTL_INFLOW_PRODUCTS).to_numpy()
    routed["direction"] = np.where(inflow, -1, 1).astype(np.int8)
    return routed
