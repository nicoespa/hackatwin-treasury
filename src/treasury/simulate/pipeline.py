"""End-to-end simulation: users, scenario adjustments, events and their routing to partners."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

import pandas as pd

from treasury.calendar import Calendar
from treasury.routing import Partner, route_events
from treasury.simulate.events import SimParams, simulate_events
from treasury.simulate.population import (
    apply_cohort_waves,
    apply_payday_shift,
    generate_users,
)
from treasury.simulate.scenarios import Scenario, scenario_overrides


def simulate_routed(
    n_users: int,
    archetypes: dict,
    cal: Calendar,
    partners: Mapping[str, Partner],
    start: date,
    end: date,
    seed: int,
    params: SimParams,
    scenarios: Sequence[Scenario] = (),
    partner_cals: Mapping[str, Calendar] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """``(users, routed events, macro)`` for ``n_users`` base users plus any ``CohortWave`` users.
    ``partner_cals`` are the settlement calendars of partners abroad (``route_events``)."""
    users = generate_users(n_users, archetypes, start, end, seed, params)
    users = apply_payday_shift(apply_cohort_waves(users, scenarios, archetypes, seed, params), scenarios)
    events, macro = simulate_events(users, archetypes, cal, start, end, params, scenarios, seed)
    return users, route_events(events, partners, cal, scenario_overrides(scenarios, partners), partner_cals), macro
