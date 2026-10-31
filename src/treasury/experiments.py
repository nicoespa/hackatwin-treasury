"""The demo's tables: model ablation, policy x rail factorial, capital-service frontier, a dataset
designed for the bottom-up model to lose, and an evaluation under scenarios the training data lacks."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import date
from functools import partial
from pathlib import Path

import pandas as pd

from treasury.backtest import CONFIG, HORIZON, Dataset, run, walk_forward
from treasury.calendar import Calendar
from treasury.features import build_drivers
from treasury.harness import default_origins
from treasury.metrics import summarize
from treasury.models.aggregate_lgbm import AggregateLGBM
from treasury.models.base import Forecaster, daily_partner_table
from treasury.models.seasonal_naive import SeasonalNaive
from treasury.models.segment_lgbm import SegmentLGBM
from treasury.policy import PolicyConfig, load_policy
from treasury.routing import load_partners
from treasury.simulate import Campaign, CohortWave, SimParams, load_archetypes
from treasury.simulate.pipeline import simulate_routed

MODEL_FACTORIES: dict[str, Callable[..., Forecaster]] = {
    "seasonal_naive": lambda n_paths=1000: SeasonalNaive(),
    "aggregate_drivers": lambda n_paths=1000: AggregateLGBM(use_obligations=False),
    "aggregate_drivers_obligations": lambda n_paths=1000: AggregateLGBM(use_obligations=True),
    "segment_factor": lambda n_paths=1000: SegmentLGBM(use_factor=True, n_paths=n_paths),
    "segment_nofactor": lambda n_paths=1000: SegmentLGBM(use_factor=False, n_paths=n_paths),
}
LABELS = dict(zip(MODEL_FACTORIES, ("(a)", "(b)", "(c)", "(d)", "(d-)")))
PROPOSED = "segment_factor"
RAILS = ("wire", "stablecoin")
POLICY_COLUMNS = ["capital_total_mean", "shortfall_rate", "shortfall_amount_total", "cost_total", "n_transfers"]
DESIGNED_START = date(2026, 6, 1)  # the segment model needs 112 days of history before the first origin
UNKNOWN_SCENARIOS = [
    Campaign(date(2026, 10, 5), date(2026, 10, 7), ("card_purchase",), lift=1.8),
    CohortWave(date(2026, 9, 15), 3000, "young_heavy"),
]


def factory(name: str, n_paths: int = 1000) -> Callable[[], Forecaster]:
    return partial(MODEL_FACTORIES[name], n_paths=n_paths)


def _origins(dataset: Dataset, origins: Sequence[date] | None, n: int = 8) -> list[date]:
    return list(origins) if origins is not None else default_origins(dataset.end, n=n, step_days=7, horizon=HORIZON)


def _policy(cfg: PolicyConfig | None) -> PolicyConfig:
    return cfg or load_policy(CONFIG / "policy.yaml")


def ablation_table(
    dataset: Dataset, origins: Sequence[date] | None = None, models: Sequence[str] = tuple(MODEL_FACTORIES),
    n_paths: int = 1000, by: tuple[str, ...] = ("model",),
) -> pd.DataFrame:
    """``summarize`` scores of each model's walk-forward forecasts (``HORIZON`` days per origin),
    pooled over partners and horizons by default; ``by=("model", "partner")`` keeps partners."""
    origins = _origins(dataset, origins)
    preds = pd.concat(
        [f.quantiles for m in models for f in walk_forward(dataset, factory(m, n_paths), origins, n_paths=n_paths)]
    )
    table = summarize(preds, daily_partner_table(dataset.history), by=by)
    table.insert(0, "label", table["model"].map(LABELS))
    order = table["model"].map(list(MODEL_FACTORIES).index).rename("order")
    return table.join(order).sort_values(["order", *by[1:]], ignore_index=True).drop(columns="order")


def _row(result, **keys) -> dict:
    m = result.metrics
    note = ", ".join(f"{p}={r}" for p, r in m["rail_used"].items() if r != keys.get("rail"))
    return {**keys, **{c: m[c] for c in POLICY_COLUMNS}, "p_unresolvable_mean": m["p_unresolvable_mean"],
            "rail_note": note or "all partners on this rail"}


def factorial_table(
    dataset: Dataset, origins: Sequence[date] | None = None, n_paths: int = 1000, cfg: PolicyConfig | None = None,
) -> pd.DataFrame:
    """2x2: ``reference`` (fixed buffer of ``fixed_buffer_days`` of trailing mean drain, no model)
    vs ``proposed`` (``segment_factor`` paths + forecast policy at ``alpha``), x (wire, stablecoin).
    ``rail_note`` names the partners that cannot take the cell's rail and use their only one."""
    origins, cfg = _origins(dataset, origins), _policy(cfg)
    rows = []
    for rail in RAILS:
        ref = run(dataset, None, "fixed", rail, cfg, origins, n_paths=n_paths)
        rows.append(_row(ref, cell="reference", rail=rail, model="none", policy=f"fixed_{cfg.fixed_buffer_days:g}d"))
        prop = run(dataset, factory(PROPOSED, n_paths), "forecast", rail, cfg, origins, n_paths=n_paths)
        rows.append(_row(prop, cell="proposed", rail=rail, model=PROPOSED, policy=f"forecast_a{cfg.alpha:g}"))
    return pd.DataFrame(rows)


def frontier(
    dataset: Dataset, alphas: Sequence[float] = (0.90, 0.95, 0.99, 0.995), origins: Sequence[date] | None = None,
    n_paths: int = 1000, cfg: PolicyConfig | None = None, buffer_days: Sequence[float] = (2, 3, 5, 7, 10),
) -> pd.DataFrame:
    """Capital vs shortfall per rail: the proposed model at each ``alpha``, and for comparison at
    equal service level the fixed buffer at each of ``buffer_days``."""
    origins, cfg = _origins(dataset, origins), _policy(cfg)
    rows = []
    for rail in RAILS:
        for alpha in alphas:
            res = run(dataset, factory(PROPOSED, n_paths), "forecast", rail, replace(cfg, alpha=alpha), origins, n_paths=n_paths)
            rows.append(_row(res, rail=rail, policy="forecast", model=PROPOSED, param_name="alpha", param=alpha))
        for days in buffer_days:
            res = run(dataset, None, "fixed", rail, replace(cfg, fixed_buffer_days=days), origins, n_paths=n_paths)
            rows.append(_row(res, rail=rail, policy="fixed", model="none", param_name="buffer_days", param=float(days)))
    return pd.DataFrame(rows)


def _simulate(n_users: int, archetypes: dict, start: date, end: date, seed: int, params: SimParams, scenarios=()):
    cal = Calendar.from_yaml(CONFIG / "calendar_ar.yaml")
    return simulate_routed(n_users, archetypes, cal, load_partners(CONFIG / "partners.yaml"), start, end, seed, params,
                           scenarios)


def designed_to_lose(seed: int, n_paths: int = 1000, n_users: int = 20_000) -> pd.DataFrame:
    """Pooled ablation of (c) vs (d) on a population of five identical segments (copies of
    ``salaried_formal``, shares 0.2), where splitting by segment carries no information.

    The population runs from ``DESIGNED_START`` (not three months back: the segment model needs
    112 days of history before the first of the four origins) to 2026-10-31.
    """
    archetypes = load_archetypes(CONFIG / "archetypes.yaml")
    salaried = archetypes["archetypes"]["salaried_formal"]
    archetypes = {**archetypes, "archetypes": {f"seg_{c}": {**salaried, "share": 0.2} for c in "abcde"}}
    end = date(2026, 10, 31)
    users, events, macro = _simulate(n_users, archetypes, DESIGNED_START, end, seed, SimParams())
    dataset = Dataset.from_frames(users, events, {"end": end.isoformat(), "seed": seed}, macro)
    origins = default_origins(end, n=4, step_days=7, horizon=HORIZON)
    return ablation_table(dataset, origins, models=("aggregate_drivers_obligations", PROPOSED), n_paths=n_paths)


def unknown_scenario_eval(
    base: Dataset, seed: int | None = None, n_paths: int = 1000, origins: Sequence[date] | None = None,
    cfg: PolicyConfig | None = None, rail: str = "stablecoin",
) -> pd.DataFrame:
    """(c) and (d) on a regeneration of ``base`` (same users, dates and simulation ``seed``,
    default the base's) with ``UNKNOWN_SCENARIOS``: a card campaign, unlike anything in the
    training history, and a cohort wave. ``announced`` builds the drivers with the scenarios and
    every user; ``surprise`` with no scenarios and without the wave's users (the wave is not in
    the planned cohorts). Models train on each variant's data before each origin. Reports pooled
    forecast scores and the forecast policy's backtest on ``rail``."""
    p = base.params
    seed = p["seed"] if seed is None else seed
    params = SimParams(sigma_m=p["sigma_m"], phi=p["phi"], payday_hypothesis=p["payday_hypothesis"],
                       inflation_monthly=p["inflation_monthly"])
    archetypes = load_archetypes(CONFIG / "archetypes.yaml")
    start, end = date.fromisoformat(p["start"]), date.fromisoformat(p["end"])
    users, events, macro = _simulate(p["n_users"], archetypes, start, end, seed, params, UNKNOWN_SCENARIOS)
    scenario = Dataset.from_frames(users, events, {**p, "n_users": len(users), "n_events": len(events)}, macro,
                                   UNKNOWN_SCENARIOS)
    planned = users[users["user_id"] < p["n_users"]]
    dates = pd.DatetimeIndex(scenario.drivers["date"])
    variants = {
        "announced": scenario,
        "surprise": replace(scenario, drivers=build_drivers(planned, events, dates), cache={}),
    }
    origins, cfg = _origins(base, origins), _policy(cfg)
    rows = []
    for variant, dataset in variants.items():
        scores = ablation_table(dataset, origins, models=("aggregate_drivers_obligations", PROPOSED), n_paths=n_paths)
        for _, score in scores.iterrows():
            bt = run(dataset, factory(score["model"], n_paths), "forecast", rail, cfg, origins, n_paths=n_paths).metrics
            rows.append({"label": score["label"], "model": score["model"], "variant": variant, "rail": rail,
                         **score[["pinball_q90", "cov_90", "pit_ks", "wape_q50"]].to_dict(),
                         "capital_total_mean": bt["capital_total_mean"], "shortfall_rate": bt["shortfall_rate"],
                         "shortfall_amount_total": bt["shortfall_amount_total"]})
    return pd.DataFrame(rows)


def run_all(data: Path, out: Path, n_paths: int = 1000) -> dict[str, float]:
    """Write every table as CSV under ``out`` with a README naming the source dataset; returns the
    wall time of each table in seconds."""
    out.mkdir(parents=True, exist_ok=True)
    dataset = Dataset.load(data)
    timings: dict[str, float] = {}
    tables: dict[str, Callable[[], pd.DataFrame]] = {
        "ablation_pooled": lambda: ablation_table(dataset, n_paths=n_paths),
        "ablation_by_partner": lambda: ablation_table(dataset, n_paths=n_paths, by=("model", "partner")),
        "factorial": lambda: factorial_table(dataset, n_paths=n_paths),
        "frontier": lambda: frontier(dataset, n_paths=n_paths),
        "designed_to_lose": lambda: designed_to_lose(seed=dataset.params["seed"], n_paths=n_paths),
        "unknown_scenario": lambda: unknown_scenario_eval(dataset, n_paths=n_paths),
    }
    for name, build in tables.items():
        began = time.perf_counter()
        build().to_csv(out / f"{name}.csv", index=False)
        timings[name] = round(time.perf_counter() - began, 1)
    _write_readme(out, data, dataset, timings, n_paths)
    return timings


TABLE_CONTENTS = {
    "ablation_pooled": f"forecast scores of models (a)..(d-), pooled over partners and horizons 1..{HORIZON}",
    "ablation_by_partner": "the same per partner",
    "factorial": "reference (fixed buffer) vs proposed ((d) + forecast policy) x (wire, stablecoin), at config values",
    "frontier": "capital vs shortfall rate per rail: (d) at each alpha, the fixed buffer at each number of days",
    "designed_to_lose": "(c) vs (d) on five identical segments, 4 origins",
    "unknown_scenario": "(c) and (d) under an unseen card campaign and cohort wave, announced vs surprise",
}
NOTES = [
    "Amounts are in the simulation's currency (ARS). Shortfall windows are partner-days: a window is short",
    "when the realized balance goes below 0 in it, and its shortfall amount is `max(0, -min balance)`.",
    "`capital_total_mean` is the time-weighted mean of every partner's non-negative available balance plus",
    "the deposits in transit, plus the central reserve (0 here); `cost_total` charges it at",
    "`cost_of_capital_annual` over the backtest days, plus rail fees and `cost_per_usd_rejected` per unit short.",
]


def _write_readme(out: Path, data: Path, dataset: Dataset, timings: dict[str, float], n_paths: int) -> None:
    lines = [
        "# Experiments",
        "",
        f"Generated by `treasury experiments --data {data} --out {out}` with `n_paths={n_paths}`, origins",
        f"`default_origins({dataset.end}, n=8, step_days=7, horizon={HORIZON})` and `config/policy.yaml`.",
        "",
        "| file | content | seconds |",
        "|---|---|---|",
        *(f"| {name}.csv | {TABLE_CONTENTS[name]} | {seconds} |" for name, seconds in timings.items()),
        "",
        *NOTES,
        "",
        f"Source dataset `{data / 'params.json'}`:",
        "",
        "```json",
        json.dumps(dataset.params, indent=2),
        "```",
        "",
    ]
    (out / "README.md").write_text("\n".join(lines))
