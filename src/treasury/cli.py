"""Command-line entry point: ``simulate`` a routed dataset, ``backtest`` a policy, run the ``experiments``."""

from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path

import typer

from treasury.calendar import Calendar
from treasury.routing import load_partners
from treasury.simulate import SimParams, load_archetypes, validate
from treasury.simulate.pipeline import simulate_routed
from treasury.simulate.scenarios import Scenario

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

    population, routed, macro = simulate_routed(users, archetypes, cal, partners, first, last, seed, params, scenarios)
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


@app.command()
def backtest(
    data: Path = Path("data/sim/base"),
    model: str = "segment_factor",
    rail: str = "stablecoin",
    policy: str = typer.Option("forecast", help="forecast or fixed"),
    alpha: float | None = None,
    n_paths: int = 1000,
    n_origins: int = 8,
    central_reserve: float = 0.0,
) -> None:
    """Walk-forward backtest of one policy and rail; prints its metrics as JSON."""
    from treasury.backtest import HORIZON, Dataset, run
    from treasury.experiments import MODEL_FACTORIES, factory
    from treasury.harness import default_origins
    from treasury.policy import load_policy

    if policy not in ("forecast", "fixed"):
        raise typer.BadParameter(f"policy must be forecast or fixed, got {policy!r}")
    if model not in MODEL_FACTORIES:
        raise typer.BadParameter(f"model must be one of {list(MODEL_FACTORIES)}, got {model!r}")
    cfg = load_policy(CONFIG / "policy.yaml")
    cfg = cfg if alpha is None else replace(cfg, alpha=alpha)
    dataset = Dataset.load(data)
    origins = default_origins(dataset.end, n=n_origins, step_days=7, horizon=HORIZON)
    result = run(dataset, factory(model, n_paths) if policy == "forecast" else None, policy, rail, cfg, origins,
                 central_reserve=central_reserve, n_paths=n_paths)
    metrics = {k: None if isinstance(v, float) and math.isnan(v) else v for k, v in result.metrics.items()}
    typer.echo(json.dumps(metrics, indent=2))


@app.command()
def experiments(data: Path = Path("data/sim/base"), out: Path = Path("reports/experiments"), n_paths: int = 1000) -> None:
    """Write the ablation, factorial, frontier, designed-to-lose and unknown-scenario CSVs to OUT."""
    from treasury.experiments import run_all

    began = time.perf_counter()
    timings = run_all(data, out, n_paths)
    typer.echo(json.dumps(timings))
    typer.echo(f"experiments written to {out} in {time.perf_counter() - began:.0f}s")
