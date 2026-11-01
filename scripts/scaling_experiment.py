"""Capital immobilized vs number of users, and how much it depends on the simulator's assumptions.

Re-simulates the population at several sizes and seeds and runs the same backtest as
`experiments.factorial_table` (proposed policy vs the fixed buffer at the same service level).
Writes reports/experiments/scaling.csv, scaling_by_partner.csv and sensitivity.csv.

Run: PYTHONPATH=src uv run python scripts/scaling_experiment.py [--quick]
"""
from __future__ import annotations

import gc
import sys
import time
from dataclasses import replace
from datetime import date
from pathlib import Path

import pandas as pd

from treasury import backtest
from treasury.backtest import CONFIG, Dataset, run
from treasury.calendar import Calendar
from treasury.experiments import HORIZON, PROPOSED, factory, matched_buffer
from treasury.harness import default_origins
from treasury.policy import load_policy
from treasury.rails import load_rails
from treasury.routing import load_partners
from treasury.simulate.events import SimParams
from treasury.simulate.pipeline import simulate_routed
from treasury.simulate.population import load_archetypes

OUT = Path(__file__).resolve().parents[1] / "reports" / "experiments"
START, END = date(2025, 11, 1), date(2026, 10, 31)
SEEDS = (42, 7, 123)
SIZES = (2_000, 5_000, 10_000, 20_000, 50_000, 100_000, 200_000)
BASE_USERS = 20_000
N_PATHS = 1000


def load_dataset(n_users: int, seed: int, params: SimParams) -> Dataset:
    cal = Calendar.from_yaml(CONFIG / "calendar_ar.yaml")
    partners = load_partners(CONFIG / "partners.yaml")
    archetypes = load_archetypes(CONFIG / "archetypes.yaml")
    users, events, macro = simulate_routed(n_users, archetypes, cal, partners, START, END, seed, params)
    return Dataset.from_frames(users, events, {"end": END.isoformat(), "seed": seed}, macro)


def window_facts(dataset: Dataset, origins: list[date], warmup_days: int) -> dict:
    """Mean gross outflow per day and mean active users over the evaluated days."""
    first = pd.Timestamp(origins[0]) + pd.Timedelta(days=warmup_days)
    stop = pd.Timestamp(origins[-1]) + pd.Timedelta(days=7)
    events = dataset.events
    settled = events[(events["direction"] == 1) & (events["settle_at"] >= first) & (events["settle_at"] < stop)]
    days = (stop - first).days
    dates = pd.date_range(first, stop, freq="D", inclusive="left")
    activation = dataset.users["activation_date"].to_numpy()
    active = sum(int((activation <= d.to_datetime64()).sum()) for d in dates) / len(dates)
    return {"daily_outflow": float(settled["amount"].sum()) / days, "active_users": active}


def evaluate(dataset: Dataset, keys: dict, rails: tuple[str, ...] = ("wire", "stablecoin")) -> tuple[list[dict], list[dict]]:
    cfg = load_policy(CONFIG / "policy.yaml")
    origins = default_origins(dataset.end, n=8, step_days=7, horizon=HORIZON)
    rows, partner_rows = [], []
    for rail in rails:
        prop = run(dataset, factory(PROPOSED, N_PATHS), "forecast", rail, cfg, origins, n_paths=N_PATHS)
        days, matched = matched_buffer(dataset, rail, prop.metrics["shortfall_rate"], origins, cfg)
        ref = run(dataset, None, "fixed", rail, cfg, origins)
        facts = window_facts(dataset, origins, prop.metrics["warmup_days"])
        for cell, res, buffer_days in (("proposed", prop, None), ("reference_matched", matched, days),
                                       ("reference", ref, float(cfg.fixed_buffer_days))):
            m = res.metrics
            rows.append({**keys, **facts, "rail": rail, "cell": cell, "buffer_days": buffer_days,
                         "capital": m["capital_total_mean"], "shortfall_rate": m["shortfall_rate"],
                         "shortfall_amount": m["shortfall_amount_total"], "fees": m["fees"],
                         "n_transfers": m["n_transfers"], "n_days": m["n_days"],
                         "cover_days": m["capital_total_mean"] / facts["daily_outflow"]})
            for _, p in res.by_partner.iterrows():
                partner_rows.append({**keys, "rail": rail, "cell": cell, "partner": p["partner"],
                                     "rail_used": p["rail_used"], "capital": p["capital_mean"]})
    return rows, partner_rows


def scaling(sizes, seeds) -> None:
    rows, partner_rows = [], []
    for n_users in sizes:
        for seed in seeds:
            began = time.perf_counter()
            dataset = load_dataset(n_users, seed, SimParams())
            r, p = evaluate(dataset, {"n_users": n_users, "seed": seed})
            rows += r
            partner_rows += p
            del dataset
            gc.collect()
            pd.DataFrame(rows).to_csv(OUT / "scaling.csv", index=False)
            pd.DataFrame(partner_rows).to_csv(OUT / "scaling_by_partner.csv", index=False)
            print(f"size {n_users} seed {seed}: {time.perf_counter() - began:.0f}s", flush=True)


def sensitivity(seeds) -> None:
    """One assumption at a time at the base size; the rest stay at their base value."""
    rails = load_rails(CONFIG / "rails.yaml")
    cases: list[tuple[str, str, SimParams, float]] = [
        ("macro_sigma", "0.05", SimParams(sigma_m=0.05), 0.5),
        ("macro_sigma", "0.15 (base)", SimParams(), 0.5),
        ("macro_sigma", "0.30", SimParams(sigma_m=0.30), 0.5),
        ("payday", "late (base)", SimParams(), 0.5),
        ("payday", "uniform", SimParams(payday_hypothesis="uniform"), 0.5),
        ("payday", "bimodal", SimParams(payday_hypothesis="bimodal"), 0.5),
        ("stablecoin_lead_hours", "0.5 (base)", SimParams(), 0.5),
        ("stablecoin_lead_hours", "6", SimParams(), 6.0),
        ("stablecoin_lead_hours", "24", SimParams(), 24.0),
        ("stablecoin_lead_hours", "48", SimParams(), 48.0),
    ]
    rows = []
    original = backtest.load_rails
    try:
        for assumption, value, params, lead in cases:
            patched = {**rails, "stablecoin": replace(rails["stablecoin"], lead_time_hours=lead)}
            backtest.load_rails = lambda _path, patched=patched: patched
            for seed in seeds:
                dataset = load_dataset(BASE_USERS, seed, params)
                r, _ = evaluate(dataset, {"assumption": assumption, "value": value, "seed": seed})
                rows += r
                del dataset
                gc.collect()
                pd.DataFrame(rows).to_csv(OUT / "sensitivity.csv", index=False)
                print(f"{assumption}={value} seed {seed}", flush=True)
    finally:
        backtest.load_rails = original


if __name__ == "__main__":
    quick = "--quick" in sys.argv
    scaling((2_000, 20_000), (42,)) if quick else scaling(SIZES, SEEDS)
    if not quick:
        sensitivity(SEEDS)
