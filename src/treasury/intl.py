"""International variant's report: capital, shortfalls and fees per partner in its own currency and in
USD, and the fixed buffer vs proposed policy factorial on swift vs stablecoin (``intl_factorial``)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from treasury.backtest import HORIZON, BacktestResult, Dataset, run, time_weighted_mean
from treasury.experiments import PROPOSED, factory, matched_buffer
from treasury.fx import usd_per_unit
from treasury.harness import default_origins
from treasury.policy import PolicyConfig

RAILS = ("swift", "stablecoin")
# Variants of partner rail acceptance the factorial also runs on the stablecoin rail.
ACCEPTS_VARIANTS = {"all accept stablecoin": None, "usd_acquirer swift only": {"usd_acquirer": ["swift"]}}


def evaluated_period(result: BacktestResult, origins: Sequence[date]) -> tuple[pd.Timestamp, pd.Timestamp]:
    """``[evaluated, stop)``: the backtest's post-warm-up days."""
    evaluated = pd.Timestamp(origins[0]) + pd.Timedelta(days=result.metrics["warmup_days"])
    return evaluated, evaluated + pd.Timedelta(days=result.metrics["n_days"])


def usd_by_partner(result: BacktestResult, dataset: Dataset, origins: Sequence[date]) -> pd.DataFrame:
    """Per partner, over the evaluated period, in its ``currency`` and in USD.

    - ``capital_mean`` (local) and ``capital_mean_usd``: the time-weighted capital (non-negative
      balance plus deposits in transit), each ledger row converted at its day's rate.
    - ``shortfall_amount`` and ``shortfall_amount_usd``, at the period's mean rate.
    - ``fees_usd``: per evaluated transfer the rail's ``fixed_fee`` (USD) plus ``bps`` of the
      amount converted at the instruction day's rate.
    """
    configs, fx = dataset.configs, dataset.fx
    partners, rails = configs.partners(), configs.rails()
    evaluated, stop = evaluated_period(result, origins)
    days = pd.date_range(evaluated, stop - pd.Timedelta(days=1), freq="D")
    sent = result.decisions[(result.decisions["amount"] > 0) & (result.decisions["at"] >= evaluated)]
    rows = []
    for r in result.by_partner.itertuples(index=False):
        currency, rail = partners[r.partner].currency, rails[r.rail_used]
        log = result.ledger_log[result.ledger_log["partner"] == r.partner]
        capital = np.maximum(log["balance"].to_numpy(), 0.0) + log["in_transit"].to_numpy()
        opening = r.initial * usd_per_unit(fx, currency, evaluated)[0]
        mine = sent[sent["partner"] == r.partner]
        rows.append({
            "partner": r.partner, "currency": currency, "rail_used": r.rail_used,
            "capital_mean": r.capital_mean,
            "capital_mean_usd": time_weighted_mean(log["at"], capital * usd_per_unit(fx, currency, log["at"]),
                                                   opening, evaluated, stop),
            "shortfall_windows": r.shortfall_windows, "shortfall_amount": r.shortfall_amount,
            "shortfall_amount_usd": r.shortfall_amount * float(usd_per_unit(fx, currency, days).mean()),
            "n_transfers": r.n_transfers,
            "fees_usd": float(len(mine) * rail.fixed_fee
                              + rail.bps / 1e4 * (mine["amount"] * usd_per_unit(fx, currency, mine["at"])).sum()),
        })
    return pd.DataFrame(rows)


def usd_totals(by_partner: pd.DataFrame, metrics: dict, cfg: PolicyConfig) -> dict:
    """Totals in USD; ``cost_total_usd`` charges ``cost_of_capital_annual`` on the capital over the
    evaluated days, plus fees and ``cost_per_usd_rejected`` per USD short."""
    capital, fees = float(by_partner["capital_mean_usd"].sum()), float(by_partner["fees_usd"].sum())
    short = float(by_partner["shortfall_amount_usd"].sum())
    return {
        "capital_usd": capital, "shortfall_rate": metrics["shortfall_rate"],
        "realized_service": 1.0 - metrics["shortfall_rate"], "shortfall_usd": short,
        "n_transfers": metrics["n_transfers"], "fees_usd": fees,
        "cost_total_usd": cfg.cost_of_capital_annual * capital * metrics["n_days"] / 365 + fees
        + cfg.cost_per_usd_rejected * short,
        "warmup_days": metrics["warmup_days"], "warmup_shortfall_windows": metrics["warmup_shortfall_windows"],
    }


def intl_factorial(
    dataset: Dataset, origins: Sequence[date] | None = None, n_paths: int = 1000, cfg: PolicyConfig | None = None,
    rails: Sequence[str] = RAILS,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """``(table, by_partner)``: per rail and rail-acceptance variant, ``reference`` (fixed buffer of
    the config's days), ``proposed`` (``segment_factor`` + forecast policy at the config's alpha)
    and ``reference_matched`` (the fixed buffer with the fewest days at the proposed policy's
    post-warm-up shortfall rate, as ``experiments.factorial_table``). Amounts in USD; ``by_partner``
    has each partner's currency and USD figures. The swift rail runs only the default variant.
    Variants share the forecasts (the dataset cache): rails do not change them."""
    origins = list(origins) if origins is not None else default_origins(dataset.end, n=8, step_days=7, horizon=HORIZON)
    cfg = cfg or dataset.configs.policy()
    rows, parts = [], []

    def add(result: BacktestResult, ds: Dataset, **keys) -> None:
        by = usd_by_partner(result, ds, origins)
        parts.append(by.assign(**keys))
        rows.append({**keys, **usd_totals(by, result.metrics, cfg),
                     "rail_note": ", ".join(f"{p}={r}" for p, r in result.metrics["rail_used"].items()
                                            if r != keys["rail"]) or "all partners on this rail"})

    for rail in rails:
        for variant, accepts in ACCEPTS_VARIANTS.items():
            if accepts and rail == "swift":
                continue
            ds = replace(dataset, params={**dataset.params, "accepts_rails": accepts}) if accepts else dataset
            keys = {"rail": rail, "variant": variant}
            add(run(ds, None, "fixed", rail, cfg, origins, n_paths=n_paths), ds, cell="reference", **keys,
                policy="fixed", buffer_days=float(cfg.fixed_buffer_days))
            prop = run(ds, factory(PROPOSED, n_paths), "forecast", rail, cfg, origins, n_paths=n_paths)
            add(prop, ds, cell="proposed", **keys, policy=f"forecast_a{cfg.alpha:g}", buffer_days=float("nan"))
            days, matched = matched_buffer(ds, rail, prop.metrics["shortfall_rate"], origins, cfg)
            add(matched, ds, cell="reference_matched", **keys, policy="fixed", buffer_days=days)
    return pd.DataFrame(rows), pd.concat(parts, ignore_index=True)


def intl_alpha_sweep(
    dataset: Dataset, origins: Sequence[date] | None = None, n_paths: int = 1000, cfg: PolicyConfig | None = None,
    alphas: Sequence[float] = (0.8, 0.9, 0.95, 0.99), rails: Sequence[str] = RAILS,
) -> pd.DataFrame:
    """The proposed policy at each of ``alphas`` per rail (default acceptance), in USD."""
    origins = list(origins) if origins is not None else default_origins(dataset.end, n=8, step_days=7, horizon=HORIZON)
    cfg = cfg or dataset.configs.policy()
    rows = []
    for rail in rails:
        for alpha in alphas:
            res = run(dataset, factory(PROPOSED, n_paths), "forecast", rail, replace(cfg, alpha=alpha), origins,
                      n_paths=n_paths)
            rows.append({"rail": rail, "alpha": alpha,
                         **usd_totals(usd_by_partner(res, dataset, origins), res.metrics, cfg)})
    return pd.DataFrame(rows)


def run_intl(data: Path, out: Path, n_paths: int = 1000) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Write ``intl_factorial.csv``, ``intl_factorial_by_partner.csv`` and ``intl_alpha_sweep.csv``
    under ``out``; returns the factorial and its per-partner table."""
    out.mkdir(parents=True, exist_ok=True)
    dataset = Dataset.load(data)
    table, by_partner = intl_factorial(dataset, n_paths=n_paths)
    table.to_csv(out / "intl_factorial.csv", index=False)
    by_partner.to_csv(out / "intl_factorial_by_partner.csv", index=False)
    intl_alpha_sweep(dataset, n_paths=n_paths).to_csv(out / "intl_alpha_sweep.csv", index=False)
    return table, by_partner
