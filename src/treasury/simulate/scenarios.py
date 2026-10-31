"""Stress scenarios the demo applies on top of the base population."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol

from treasury.routing import Partner, RouteOverride


class Scenario(Protocol):
    def multiplier(self, day: date, segment: str, product: str) -> float: ...

    def extra_users(self, day: date) -> int: ...


class _Neutral:
    """Scenario defaults: no intensity change and no new users."""

    def multiplier(self, day: date, segment: str, product: str) -> float:
        return 1.0

    def extra_users(self, day: date) -> int:
        return 0


@dataclass(frozen=True)
class Campaign(_Neutral):
    """Multiply ``products`` for every segment on ``[start, end]``."""

    start: date
    end: date
    products: tuple[str, ...]
    lift: float

    def multiplier(self, day: date, segment: str, product: str) -> float:
        return self.lift if product in self.products and self.start <= day <= self.end else 1.0


@dataclass(frozen=True)
class CohortWave(_Neutral):
    """``n_users`` new ``segment`` users activating on ``start``."""

    start: date
    n_users: int
    segment: str

    def extra_users(self, day: date) -> int:
        return self.n_users if day == self.start else 0


@dataclass(frozen=True)
class FxJump(_Neutral):
    """A devaluation scare: ``crypto_buy`` multiplied by ``crypto_lift`` on ``[date, date + days)``."""

    date: date
    days: int
    crypto_lift: float = 3.0

    def multiplier(self, day: date, segment: str, product: str) -> float:
        in_window = self.date <= day < self.date + timedelta(days=self.days)
        return self.crypto_lift if product == "crypto_buy" and in_window else 1.0


@dataclass(frozen=True)
class PartnerOutage(_Neutral):
    """``partner`` is down on ``[start, end]``; its products settle at ``reroute_to`` instead."""

    partner: str
    start: date
    end: date
    reroute_to: str

    def overrides(self, partners: Mapping[str, Partner]) -> list[RouteOverride]:
        return [
            RouteOverride(product, self.start, self.end, self.reroute_to) for product in partners[self.partner].products
        ]


@dataclass(frozen=True)
class PaydayShift(_Neutral):
    """Every salaried user's payday moves ``delta_bd`` business days (kept within 1..4)."""

    delta_bd: int


def scenario_overrides(scenarios: Sequence[Scenario], partners: Mapping[str, Partner]) -> list[RouteOverride]:
    """Routing overrides from every scenario that remaps partners (``PartnerOutage``)."""
    return [o for s in scenarios if hasattr(s, "overrides") for o in s.overrides(partners)]
