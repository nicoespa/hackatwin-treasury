"""A config set: the directory holding one variant's archetypes, partners, rails, policy and calendars.

``config/`` is the domestic set; ``config/intl/`` the international one. A dataset records the set
it was simulated with in ``params.json`` (``config``), so the backtest loads the matching files.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from functools import cache
from pathlib import Path

import yaml

from treasury.calendar import Calendar
from treasury.policy import PolicyConfig, load_policy
from treasury.rails import Rail, load_rails
from treasury.routing import HOME_COUNTRY, Partner, load_partners

CONFIG = Path(__file__).resolve().parents[2] / "config"
NAMED = {"domestic": CONFIG, "intl": CONFIG / "intl"}


@cache
def _calendar(path: Path) -> Calendar:
    return Calendar.from_yaml(path)


@dataclass(frozen=True)
class ConfigSet:
    """``accepts`` overrides some partners' ``accepts_rails`` (e.g. a partner that takes no stablecoin)."""

    dir: Path
    accepts: tuple[tuple[str, tuple[str, ...]], ...] = ()

    @classmethod
    def resolve(cls, name: str | Path | None = None, accepts: Mapping[str, Sequence[str]] | None = None) -> ConfigSet:
        """``None`` or ``"domestic"`` is ``config/``, ``"intl"`` is ``config/intl/``, anything else a
        directory (relative to the working directory, else to the repository root)."""
        if name is None or str(name) in NAMED:
            path = NAMED[str(name or "domestic")]
        else:
            path = Path(name)
            path = path if path.is_absolute() or path.exists() else CONFIG.parent / path
        return cls(path, tuple(sorted((pid, tuple(r)) for pid, r in (accepts or {}).items())))

    def calendar(self, country: str = HOME_COUNTRY) -> Calendar:
        """``calendar_<country>.yaml`` of this set, else of ``config/`` (the Argentine one is shared)."""
        path = self.dir / f"calendar_{country}.yaml"
        return _calendar(path if path.exists() else CONFIG / path.name)

    def partners(self) -> dict[str, Partner]:
        partners = load_partners(self.dir / "partners.yaml")
        for pid, rails in self.accepts:
            partners[pid] = replace(partners[pid], accepts_rails=rails)
        return partners

    def rails(self) -> dict[str, Rail]:
        return load_rails(self.dir / "rails.yaml")

    def policy(self) -> PolicyConfig:
        return load_policy(self.dir / "policy.yaml")

    def archetypes(self) -> dict:
        from treasury.simulate.population import load_archetypes

        return load_archetypes(self.dir / "archetypes.yaml")

    def market(self) -> dict | None:
        """``market.yaml`` (FX paths, demand elasticities, tourism season), absent for domestic."""
        path = self.dir / "market.yaml"
        return yaml.safe_load(path.read_text()) if path.exists() else None

    def rail_calendar(self, partner: Partner) -> Calendar:
        """Days a business-day rail moves money to ``partner``: business days at home and in its country."""
        return Calendar.joint(self.calendar(), self.calendar(partner.country))

    def joint_calendar(self) -> Calendar:
        """Business days at home and in every partner's country."""
        countries = sorted({p.country for p in self.partners().values()})
        return Calendar.joint(self.calendar(), *(self.calendar(c) for c in countries))

    def settle_calendars(self) -> dict[str, Calendar]:
        """Settlement calendar of each lagged partner abroad (real-time and home partners use the home one)."""
        return {pid: self.calendar(p.country) for pid, p in self.partners().items()
                if p.country != HOME_COUNTRY and not p.is_realtime}

    def settle_lags(self) -> dict[str, tuple[Calendar, int]]:
        """``settle_calendars`` with each partner's settlement lag in business days."""
        partners = self.partners()
        return {pid: (cal, partners[pid].settle_lag_business_days) for pid, cal in self.settle_calendars().items()}
