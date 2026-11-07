"""24/7 rebalancing: more frequent reviews and sweeping surpluses back to the pool.

On the stablecoin rail (24/7) the agent can review at night and on weekends. Variants of the proposed
policy (k-means segments) on the same evaluated weeks as the other experiments:
- reviews at 9 and 18 (today's setting), with and without sweep;
- reviews every 3 hours, with and without sweep.
Partners that only take bank transfers keep business-day reviews and never sweep.

Run: PYTHONPATH=src uv run python scripts/rebalance_experiment.py data/sim/base
Writes reports/experiments/rebalance.csv and rebalance_moves.csv (the sweeps and deposits of the best variant).
"""
from __future__ import annotations

import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

import pandas as pd

from treasury.backtest import Dataset, run
from treasury.experiments import PROPOSED, factory
from treasury.harness import default_origins
from treasury.segmentation import KMeansSegmenter

OUT = Path("reports/experiments")
EVERY_3H = tuple(range(0, 24, 3))
TUNED = dict(sweep=True, sweep_headroom=1.0, sweep_min_share=1.0)  # keep 2x the window's need; sweep only big surpluses
VARIANTS = {
    "9 y 18 h, sin barrido": dict(review_hours_247=(9, 18), sweep=False),
    "cada 3 h, sin barrido": dict(review_hours_247=EVERY_3H, sweep=False),
    "cada 3 h, barrido sin margen": dict(review_hours_247=EVERY_3H, sweep=True),
    "cada 3 h, barrido con margen": dict(review_hours_247=EVERY_3H, **TUNED),
}


def main(folder: str) -> None:
    dataset = Dataset.load(folder)
    base = dataset.configs.policy()
    evaluated = default_origins(date.fromisoformat(dataset.params["end"]), n=8, step_days=7, horizon=14)
    rows, best = [], None
    for name, change in VARIANTS.items():
        res = run(dataset, factory(PROPOSED, 1000), "forecast", "stablecoin", replace(base, **change), evaluated,
                  n_paths=1000, segmenter=KMeansSegmenter())
        m = res.metrics
        sweeps = res.decisions.loc[res.decisions["at"] >= pd.Timestamp(evaluated[0]), "sweep"]
        rows.append({"variant": name, "capital": m["capital_total_mean"], "shortfall_rate": m["shortfall_rate"],
                     "n_transfers": m["n_transfers"], "fees": m["fees"], "n_sweeps": int((sweeps > 0).sum()),
                     "swept_total": float(sweeps.sum())})
        print(rows[-1], flush=True)
        best = res if name == "cada 3 h, barrido con margen" else best
    table = pd.DataFrame(rows)
    table["vs_today"] = 1 - table["capital"] / table.loc[0, "capital"]
    # Fee (bps of the amount moved) at which the capital freed pays for the extra moves. The stablecoin
    # rail charges 10 bps, so the extra volume moved is the extra fees over 0.001.
    days = (pd.Timestamp(evaluated[-1]) + pd.Timedelta(days=7) - pd.Timestamp(evaluated[0])).days - 4
    extra_moved = (table["fees"] - table.loc[0, "fees"]) / 0.001
    for k in (0.12, 0.30):
        saved = (table.loc[0, "capital"] - table["capital"]) * k * days / 365
        table[f"breakeven_bps_k{int(k * 100)}"] = (saved / extra_moved.where(extra_moved > 1e6) * 1e4).round(1)
    table.to_csv(OUT / "rebalance.csv", index=False)
    moves = best.decisions[(best.decisions["amount"] > 0) | (best.decisions["sweep"] > 0)]
    moves[["at", "partner", "rail_used", "available", "target", "amount", "sweep", "arrival_at"]].to_csv(
        OUT / "rebalance_moves.csv", index=False)
    print(table.to_string(index=False))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/sim/base")
