"""Argentine business-day calendar loaded from YAML."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

Window = tuple[date, date]


def _in_any(d: date, windows: tuple[Window, ...]) -> bool:
    return any(start <= d <= end for start, end in windows)


@dataclass(frozen=True)
class Calendar:
    """Business-day calendar valid only inside ``[coverage_start, coverage_end]``.

    Every date-taking method accepts ``date``, ``datetime`` or ``pandas.Timestamp``
    (compared by calendar date) and raises ``ValueError`` outside coverage.
    """

    holidays: frozenset[date]
    coverage_start: date
    coverage_end: date
    sac_windows: tuple[Window, ...] = ()
    anses_windows: tuple[Window, ...] = ()

    @classmethod
    def from_yaml(cls, path: str | Path) -> Calendar:
        raw = yaml.safe_load(Path(path).read_text())

        def windows(key: str) -> tuple[Window, ...]:
            return tuple((w["start"], w["end"]) for w in raw.get(key, []))

        return cls(
            holidays=frozenset(raw.get("holidays", [])),
            coverage_start=raw["coverage"]["start"],
            coverage_end=raw["coverage"]["end"],
            sac_windows=windows("sac_windows"),
            anses_windows=windows("anses_windows"),
        )

    def _checked(self, d: date) -> date:
        if isinstance(d, datetime):
            d = d.date()
        if not self.coverage_start <= d <= self.coverage_end:
            raise ValueError(
                f"{d.isoformat()} is outside calendar coverage "
                f"{self.coverage_start.isoformat()}..{self.coverage_end.isoformat()}"
            )
        return d

    def _is_business_day(self, d: date) -> bool:
        return d.weekday() < 5 and d not in self.holidays

    def is_business_day(self, d: date) -> bool:
        return self._is_business_day(self._checked(d))

    def add_business_days(self, d: date, n: int) -> date:
        """Move ``n`` business days from ``d``; ``n == 0`` returns ``d`` unchanged."""
        d = self._checked(d)
        step = timedelta(days=1 if n > 0 else -1)
        remaining = abs(n)
        while remaining:
            d += step
            if self._is_business_day(d):
                remaining -= 1
        return self._checked(d)

    def nth_business_day_of_month(self, d: date) -> int:
        """1-based index of ``d`` among its month's business days; 0 if not a business day."""
        d = self._checked(d)
        if not self._is_business_day(d):
            return 0
        first = d.replace(day=1)
        return sum(self._is_business_day(first + timedelta(days=i)) for i in range(d.day))

    def business_days_to_month_end(self, d: date) -> int:
        """Business days strictly after ``d`` up to the last day of its month."""
        d = self._checked(d)
        count = 0
        nxt = d + timedelta(days=1)
        while nxt.month == d.month:
            count += self._is_business_day(nxt)
            nxt += timedelta(days=1)
        return count

    def is_sac_window(self, d: date) -> bool:
        return _in_any(self._checked(d), self.sac_windows)

    def anses_window(self, d: date) -> bool:
        """True on business days inside an ANSES payment window."""
        d = self._checked(d)
        return self._is_business_day(d) and _in_any(d, self.anses_windows)
