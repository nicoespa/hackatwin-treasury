"""Synthetic wallet population, its events, stress scenarios and realism checks."""

from treasury.simulate.events import SimParams, anses_boost_date, macro_factor, simulate_events
from treasury.simulate.population import (
    PAYDAY_HYPOTHESES,
    apply_cohort_waves,
    apply_payday_shift,
    generate_users,
    load_archetypes,
)
from treasury.simulate.scenarios import (
    Campaign,
    CohortWave,
    FxJump,
    PartnerOutage,
    PaydayShift,
    Scenario,
    scenario_overrides,
)
from treasury.simulate.validate import validate

__all__ = [
    "PAYDAY_HYPOTHESES",
    "Campaign",
    "CohortWave",
    "FxJump",
    "PartnerOutage",
    "PaydayShift",
    "Scenario",
    "SimParams",
    "anses_boost_date",
    "apply_cohort_waves",
    "apply_payday_shift",
    "generate_users",
    "load_archetypes",
    "macro_factor",
    "scenario_overrides",
    "simulate_events",
    "validate",
]
