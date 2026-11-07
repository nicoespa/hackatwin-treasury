"""Plan once a business day, then adjust every 3 hours on 24/7 accounts, against planning alone.

Runs ``treasury.live.LiveSim.evaluate`` (no clock) over the evaluated weeks with weekly forecast
origins and k-means segments, on the accounts that take stablecoin.

Run: PYTHONPATH=src uv run python scripts/plan_adjust_experiment.py
Writes reports/experiments/plan_adjust.csv.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from treasury.harness import default_origins
from treasury.live import LiveSim

OUT = Path("reports/experiments/plan_adjust.csv")


def main() -> None:
    origins = default_origins(date(2026, 10, 31), n=8, step_days=7, horizon=14)
    sim = LiveSim(origins=origins, only=("bills_aggregator", "card_network", "crypto_exchange", "remittance"))
    start, stop = pd.Timestamp(origins[0]) + pd.Timedelta(days=4, hours=9), pd.Timestamp(origins[-1]) + pd.Timedelta(days=7)
    rows = []
    for adjust in (False, True):
        sim.adjust = sim.give_back = adjust
        sim.review_every = 3
        r = sim.evaluate(start, stop)
        rows.append({"variant": "plan y ajustes cada 3 h" if adjust else "solo plan", "capital": r["capital"],
                     "short_account_hours": r["short_account_hours"], "credit_used": r["credit_used"], **r["moves"]})
        print(rows[-1], flush=True)
    table = pd.DataFrame(rows).fillna(0)
    table["vs_plan_only"] = 1 - table["capital"] / table.loc[0, "capital"]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(OUT, index=False)
    print(table.to_string(index=False))


if __name__ == "__main__":
    main()
