"""Proposed policy vs a fixed buffer chosen without seeing the evaluated weeks.

`factorial_table` matches the fixed buffer on the evaluated weeks themselves (the fewest days with
the proposed policy's shortfall rate there): a hindsight benchmark no treasury can set ahead of time.
Here the buffer days are the fewest with zero shortfalls over the `CALIBRATION_WEEKS` before the first
evaluated origin, then run on the evaluated weeks. Both benchmarks are written, with capital in the
data's currency and, for a dataset with exchange rates, in USD. The proposed policy runs twice: on the
simulator's segment labels (`proposed_oracle`) and on k-means segments inferred from transactions
(`proposed_kmeans`, what a real wallet can do); the hindsight buffer is matched to the k-means one.

Run: PYTHONPATH=src uv run python scripts/exante_buffer_experiment.py data/sim/base data/sim/intl
Writes reports/experiments/exante_buffer.csv.
"""
from __future__ import annotations

import sys
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from treasury.backtest import Dataset, run
from treasury.experiments import PROPOSED, factory, matched_buffer
from treasury.harness import default_origins
from treasury.intl import usd_by_partner
from treasury.segmentation import KMeansSegmenter

CALIBRATION_WEEKS = 16
N_PATHS = 1000
OUT = Path("reports/experiments/exante_buffer.csv")


def _row(dataset: Dataset, name: str, rail: str, benchmark: str, result, origins, days: float | None) -> dict:
    row = {"dataset": name, "rail": rail, "benchmark": benchmark, "buffer_days": days,
           "capital": result.metrics["capital_total_mean"], "shortfall_rate": result.metrics["shortfall_rate"],
           "n_transfers": result.metrics["n_transfers"]}
    if dataset.fx is not None:
        row["capital_usd"] = float(usd_by_partner(result, dataset, origins)["capital_mean_usd"].sum())
    return row


def main(folders: list[str]) -> None:
    rows = []
    for folder in folders:
        dataset, name = Dataset.load(folder), Path(folder).name
        cfg, rails = dataset.configs.policy(), sorted(dataset.configs.rails())
        end = date.fromisoformat(dataset.params["end"])
        evaluated = default_origins(end, n=8, step_days=7, horizon=14)
        calibration = [evaluated[0] - timedelta(days=7 * k) for k in range(CALIBRATION_WEEKS, 0, -1)]
        for rail in rails:
            oracle = run(dataset, factory(PROPOSED, N_PATHS), "forecast", rail, cfg, evaluated, n_paths=N_PATHS)
            rows.append(_row(dataset, name, rail, "proposed_oracle", oracle, evaluated, None))
            proposed = run(dataset, factory(PROPOSED, N_PATHS), "forecast", rail, cfg, evaluated, n_paths=N_PATHS,
                           segmenter=KMeansSegmenter())
            rows.append(_row(dataset, name, rail, "proposed_kmeans", proposed, evaluated, None))
            days, hindsight = matched_buffer(dataset, rail, proposed.metrics["shortfall_rate"], evaluated, cfg)
            rows.append(_row(dataset, name, rail, "fixed_hindsight", hindsight, evaluated, days))
            days, _ = matched_buffer(dataset, rail, 0.0, calibration, cfg)
            exante = run(dataset, None, "fixed", rail, replace(cfg, fixed_buffer_days=days), evaluated)
            rows.append(_row(dataset, name, rail, "fixed_exante", exante, evaluated, days))
            print(pd.DataFrame(rows[-4:]).to_string(index=False), flush=True)
    table = pd.DataFrame(rows)
    key = "capital_usd" if "capital_usd" in table else "capital"
    base = table.assign(c=table[key].fillna(table["capital"]))
    for variant in ("kmeans", "oracle"):
        prop = base[base["benchmark"] == f"proposed_{variant}"].set_index(["dataset", "rail"])["c"]
        table[f"saved_by_{variant}"] = [None if b.startswith("proposed") else 1 - prop[(d, r)] / c
                                        for d, r, b, c in zip(base["dataset"], base["rail"], base["benchmark"], base["c"])]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(OUT, index=False)
    print(table.to_string(index=False))


if __name__ == "__main__":
    main(sys.argv[1:])
