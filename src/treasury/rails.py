"""Replenishment rails and when a deposit instructed on them arrives."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

from treasury.calendar import Calendar


@dataclass(frozen=True)
class Rail:
    name: str
    lead_time_hours: float
    business_days_only: bool
    instruct_cutoff_hour: int | None
    credit_hour: int | None
    fixed_fee: float
    bps: float


def load_rails(path: str | Path) -> dict[str, Rail]:
    raw = yaml.safe_load(Path(path).read_text())
    return {name: Rail(name=name, **fields) for name, fields in raw.items()}


def arrival_time(rail: Rail, instruct_at: pd.Timestamp, cal: Calendar) -> pd.Timestamp:
    """When funds instructed at ``instruct_at`` become available at the partner.

    24/7 rails arrive ``lead_time_hours`` later. Business-day rails start counting
    on the instruct date if it is a business day before the cutoff hour, else on
    the next business day, and credit ``ceil(lead_time_hours / 24)`` business days
    later at ``credit_hour``.
    """
    instruct_at = pd.Timestamp(instruct_at)
    if not rail.business_days_only:
        return instruct_at + pd.Timedelta(hours=rail.lead_time_hours)

    day = instruct_at.date()
    before_cutoff = rail.instruct_cutoff_hour is None or instruct_at.hour < rail.instruct_cutoff_hour
    # From a non-business day, add_business_days(day, 1) lands on the first business day after it.
    start = day if cal.is_business_day(day) and before_cutoff else cal.add_business_days(day, 1)
    arrival = cal.add_business_days(start, math.ceil(rail.lead_time_hours / 24))
    return pd.Timestamp(arrival) + pd.Timedelta(hours=rail.credit_hour)
