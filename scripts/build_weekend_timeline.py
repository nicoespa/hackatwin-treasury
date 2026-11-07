"""Timeline of one weekend of 24/7 rebalancing, for the demo dashboard.

Runs the tuned rebalancing variant (reviews every 3 hours, sweep with headroom, k-means segments) on
data/sim/base and writes every review between START and STOP: per account the balance at the review,
what it may need (the window's target), the deposit or sweep, and the rail it used.

Run: PYTHONPATH=src uv run python scripts/build_weekend_timeline.py
Writes reports/demo/weekend_timeline.json.
"""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from treasury.backtest import Dataset, run
from treasury.experiments import PROPOSED, factory
from treasury.harness import default_origins
from treasury.segmentation import KMeansSegmenter

START, STOP = pd.Timestamp("2026-10-16 15:00"), pd.Timestamp("2026-10-19 12:00")
NAMES = {"bills_aggregator": "Servicios", "card_network": "Tarjetas", "crypto_exchange": "Cripto",
         "remittance": "Envíos", "fci_custodian": "Inversiones", "cash_network": "Efectivo"}
OUT = Path("reports/demo/weekend_timeline.json")


def main() -> None:
    dataset = Dataset.load("data/sim/base")
    cfg = replace(dataset.configs.policy(), review_hours_247=tuple(range(0, 24, 3)), sweep=True,
                  sweep_headroom=1.0, sweep_min_share=1.0)
    evaluated = default_origins(date.fromisoformat(dataset.params["end"]), n=8, step_days=7, horizon=14)
    res = run(dataset, factory(PROPOSED, 1000), "forecast", "stablecoin", cfg, evaluated, n_paths=1000,
              segmenter=KMeansSegmenter())
    d = res.decisions[(res.decisions["at"] >= START) & (res.decisions["at"] <= STOP)]
    log = res.ledger_log
    events = []
    for r in d.sort_values(["at", "partner"]).itertuples():
        bal = log[(log["partner"] == r.partner) & (log["at"] <= r.at)]["balance"]
        events.append({"at": r.at.isoformat(), "account": NAMES[r.partner], "rail": r.rail_used,
                       "balance": float(bal.iloc[-1]) if len(bal) else float(r.available), "need": float(r.target),
                       "deposit": float(r.amount), "sweep": float(r.sweep),
                       "arrival": None if r.amount <= 0 else pd.Timestamp(r.arrival_at).isoformat()})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"start": START.isoformat(), "stop": STOP.isoformat(), "events": events,
                               "metrics": {"capital": res.metrics["capital_total_mean"],
                                           "shortfall_rate": res.metrics["shortfall_rate"]}}, indent=1))
    print(len(events), "events;", sum(e["deposit"] > 0 for e in events), "deposits,", sum(e["sweep"] > 0 for e in events), "sweeps")


if __name__ == "__main__":
    main()
