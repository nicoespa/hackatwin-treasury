"""Segment model on inferred (k-means) segments vs the simulator's archetype labels vs the aggregate model.

Forecast scores as in `experiments.ablation_table` and the backtest as in
`experiments.factorial_table` (proposed policy vs the fixed buffer at the same service level), plus
per origin the chosen k, silhouette, adjusted Rand index against the hidden archetypes and the
segment profiles. Writes reports/experiments/segmentation_*.csv, segmentation.md and the
segmentation section of reports/experiments/README.md.

Run from the repo root: PYTHONPATH=src .venv/bin/python scripts/segmentation_experiment.py [--data data/sim/base] [--n-paths 1000]
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from treasury.experiments import run_segmentation


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path("data/sim/base"))
    parser.add_argument("--out", type=Path, default=Path("reports/experiments"))
    parser.add_argument("--n-paths", type=int, default=1000)
    args = parser.parse_args()
    began = time.perf_counter()
    tables = run_segmentation(args.data, args.out, n_paths=args.n_paths)
    for name in ("segmentation_forecast", "segmentation_clusters"):
        print(tables[name].to_string(index=False))
    backtest = tables["segmentation_backtest"]
    print(backtest[["variant", "rail", "cell", "buffer_days", "capital_total_mean", "shortfall_rate"]].to_string(index=False))
    print(f"done in {time.perf_counter() - began:.0f} s")


if __name__ == "__main__":
    main()
