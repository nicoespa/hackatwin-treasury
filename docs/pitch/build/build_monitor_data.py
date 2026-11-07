"""Data for the monitoring dashboard: the agent's week of bank-transfer reviews and 8 weeks of balances."""
import json, sys, tempfile, warnings
from dataclasses import replace
from datetime import date
from pathlib import Path
warnings.filterwarnings("ignore")
import pandas as pd
from treasury.agent.executor import TransferLedger
from treasury.agent.run import run_day
from treasury.backtest import Dataset, run
from treasury.experiments import PROPOSED, factory
from treasury.harness import default_origins
from treasury.segmentation import KMeansSegmenter
out = Path(sys.argv[1]); ds = Dataset.load("data/sim/intl"); seg = KMeansSegmenter()
runs = {}
for day in ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"]:
    with tempfile.TemporaryDirectory() as tmp:
        r = run_day(ds, pd.Timestamp(day), TransferLedger(Path(tmp) / "l.jsonl"), rail="swift", n_paths=2000, segmenter=seg)
    for p in r["partners"]: p.pop("rationale", None); p.pop("exception", None)
    r.pop("ledger", None); runs[day] = r; print(day, flush=True)
cfg = ds.configs.policy(); ev = default_origins(date(2026, 10, 31), n=8, step_days=7, horizon=14)
series = {}
for name, res in [("prefoundly", run(ds, factory(PROPOSED, 1000), "forecast", "swift", cfg, ev, n_paths=1000, segmenter=seg)),
                  ("fixed", run(ds, None, "fixed", "swift", replace(cfg, fixed_buffer_days=10.75), ev))]:
    log = res.ledger_log.copy(); log["day"] = pd.to_datetime(log["at"]).dt.normalize()
    g = log.groupby(["partner", "day"]).agg(min_balance=("balance", "min")).reset_index()
    g = g[(g["day"] >= "2026-09-03") & (g["day"] <= "2026-10-09")]
    series[name] = {pid: {"days": [d.strftime("%Y-%m-%d") for d in gg["day"]], "min": gg["min_balance"].round(0).tolist()} for pid, gg in g.groupby("partner")}
fx = pd.read_parquet("data/sim/intl/fx.parquet"); fxw = fx[(fx["date"] >= "2026-10-01") & (fx["date"] <= "2026-10-16")]
out.write_text(json.dumps({"runs": runs, "series": series, "fx": dict(zip(fxw["date"].dt.strftime("%Y-%m-%d"), fxw["brl_per_usd"].round(4)))}, default=str))
print("wrote", out.stat().st_size)
