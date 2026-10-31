"""Command-line entry point: ``treasury simulate`` builds a routed synthetic dataset."""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import typer

from treasury.calendar import Calendar
from treasury.routing import load_partners, route_events
from treasury.simulate import (
    SimParams,
    apply_cohort_waves,
    apply_payday_shift,
    generate_users,
    load_archetypes,
    simulate_events,
    validate,
)
from treasury.simulate.scenarios import Scenario, scenario_overrides

CONFIG = Path(__file__).resolve().parents[2] / "config"

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback()
def main() -> None:
    """Predictive treasury for a wallet's prefunded partner balances."""


@app.command()
def simulate(
    users: int = 20_000,
    start: datetime = typer.Option("2025-11-01", formats=["%Y-%m-%d"]),
    end: datetime = typer.Option("2026-10-31", formats=["%Y-%m-%d"]),
    seed: int = 42,
    out: Path = Path("data/sim/base"),
    payday_hypothesis: str = "late",
    sigma_m: float = 0.15,
    phi: float = 0.7,
) -> None:
    """Simulate users and routed events; write users, events, macro parquet and params.json to OUT."""
    began = time.perf_counter()
    params = SimParams(sigma_m=sigma_m, phi=phi, payday_hypothesis=payday_hypothesis)
    cal = Calendar.from_yaml(CONFIG / "calendar_ar.yaml")
    partners = load_partners(CONFIG / "partners.yaml")
    archetypes = load_archetypes(CONFIG / "archetypes.yaml")
    first, last = start.date(), end.date()
    scenarios: list[Scenario] = []

    population = generate_users(users, archetypes, first, last, seed, payday_hypothesis)
    population = apply_cohort_waves(population, scenarios, archetypes, seed, payday_hypothesis)
    population = apply_payday_shift(population, scenarios)
    events, macro = simulate_events(population, archetypes, cal, first, last, params, scenarios, seed)
    routed = route_events(events, partners, cal, scenario_overrides(scenarios, partners))
    checks = validate(routed, cal)

    out.mkdir(parents=True, exist_ok=True)
    population.to_parquet(out / "users.parquet", index=False)
    routed.to_parquet(out / "events.parquet", index=False)
    macro.to_parquet(out / "macro.parquet", index=False)
    meta = {
        **asdict(params),
        "seed": seed,
        "n_users": len(population),
        "start": first.isoformat(),
        "end": last.isoformat(),
        "n_events": len(routed),
        "validation": checks,
    }
    (out / "params.json").write_text(json.dumps(meta, indent=2) + "\n")
    typer.echo(f"{len(routed):,} events for {len(population):,} users in {time.perf_counter() - began:.1f}s -> {out}")
    typer.echo(json.dumps(checks))
