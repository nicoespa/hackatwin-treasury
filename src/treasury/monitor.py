"""Live monitoring dashboard of the autonomous agent.

A small local web server (standard library only) serves one page and ``/api/state``, a JSON view of
what the agent did: the reviews in the runs log, the transfers in the ledger and, once computed, eight
weeks of balances with the agent and with a fixed rule. The page polls the state every few seconds, so
a review executed from the MCP server (or ``treasury monitor --seed``) shows up on its own.

Paths are shared with ``treasury.mcp_server`` through environment variables: ``TREASURY_DATA``
(default ``data/sim/base``), ``TREASURY_LEDGER`` (``data/transfers_mcp.jsonl``), ``TREASURY_RUNS``
(``data/agent_runs.jsonl``) and ``TREASURY_STATE`` (``data/agent_state.json``).
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import replace
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pandas as pd

from treasury.agent.executor import ledger_status

DATA = Path(os.environ.get("TREASURY_DATA", "data/sim/base"))
LEDGER = Path(os.environ.get("TREASURY_LEDGER", "data/transfers_mcp.jsonl"))
RUNS = Path(os.environ.get("TREASURY_RUNS", "data/agent_runs.jsonl"))
STATE = Path(os.environ.get("TREASURY_STATE", "data/agent_state.json"))
SERIES = Path(os.environ.get("TREASURY_SERIES", "data/monitor_series.json"))
PAGE = Path(__file__).with_name("monitor.html")
LOGO = Path(__file__).with_name("monitor_logo.png")

NAMES = {  # partner ids as a treasury team would name the accounts
    "bills_aggregator": "Pago de servicios", "card_network": "Tarjetas", "fci_custodian": "Inversiones",
    "crypto_exchange": "Cripto", "cash_network": "Efectivo", "remittance": "Envíos al exterior",
    "pix_br": "Brasil", "usd_acquirer": "Estados Unidos",
}
SYMBOL = {"ARS": "$", "USD": "US$", "BRL": "R$"}


def record_run(run: dict, path: Path | None = None) -> None:
    """Append an executed review (``run_day``'s result) to the runs log read by the dashboard."""
    path = path or RUNS
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(run, default=str) + "\n")


def read_runs(path: Path | None = None) -> list[dict]:
    path = path or RUNS
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def money(x: float | None, currency: str) -> str:
    if x is None:
        return "s/d"
    big = abs(x) >= 1e6
    text = f"{x / 1e6:,.0f} M" if big else f"{x:,.0f}"
    return f"{SYMBOL.get(currency, currency)} " + text.replace(",", ".")


def explain(row: dict) -> str:
    """One plain Spanish sentence on why the agent sent (or did not send) money to a partner."""
    cur, need, have = row["currency"], row.get("need"), (row.get("available") or 0) + (row.get("in_transit") or 0)
    if need is None:
        return "No había pronóstico para esta cuenta: no envió nada y avisó."
    head = f"Hasta la próxima carga podían salir hasta {money(need, cur)} en un día malo, y había {money(have, cur)}."
    if row["status"] == "held":
        return head + " El agente estaba pausado o un control lo frenó: no envió nada y avisó."
    if row["status"] == "capped":
        return (head + f" Hacían falta {money(row['policy_amount'], cur)}, pero el tope por envío es "
                f"{money(row['executed_amount'], cur)}: mandó el tope y avisó por {money(row['remainder'], cur)}.")
    if row["executed_amount"] > 0:
        return head + f" Mandó {money(row['executed_amount'], cur)}."
    return head + " Alcanzaba: no mandó nada."


def _paused() -> bool:
    try:
        return bool(json.loads(STATE.read_text()).get("paused", False))
    except (FileNotFoundError, json.JSONDecodeError):
        return False


def state() -> dict:
    """Everything the page shows, built from the runs log, the ledger and the cached balance series."""
    runs = read_runs()
    clock = pd.Timestamp(runs[-1]["review_at"]) + pd.Timedelta(hours=1) if runs else None
    latest: dict[str, dict] = {}
    moves = []
    for run in runs:
        for p in run["partners"]:
            latest[p["partner"]] = p | {"review_at": run["review_at"]}
            if (p.get("policy_amount") or 0) > 0 or p["status"] == "held":
                moves.append({"review_at": run["review_at"], "partner": p["partner"], "name": NAMES.get(p["partner"], p["partner"]),
                              "currency": p["currency"], "asked": p.get("policy_amount") or 0, "sent": p["executed_amount"],
                              "eta": p.get("eta"), "status": p["status"], "why": explain(p)})
    transfers = ledger_status(LEDGER, clock) if (LEDGER.exists() and clock is not None) else []
    by_key = {t["idempotency_key"]: t["status"] for t in transfers}
    for m in moves:
        m["transfer_status"] = by_key.get(f"{m['partner']}@{pd.Timestamp(m['review_at']).isoformat()}")
    accounts = [{"partner": pid, "name": NAMES.get(pid, pid), "currency": r["currency"],
                 "loaded": (r.get("available") or 0) + (r.get("in_transit") or 0), "need": r.get("need"),
                 "status": r["status"], "review_at": r["review_at"]} for pid, r in latest.items()]
    series = json.loads(SERIES.read_text()) if SERIES.exists() else None
    return {"executing": not _paused(), "runs": len(runs), "last_review": runs[-1]["review_at"] if runs else None,
            "accounts": accounts, "moves": moves[::-1], "series": series}


def compute_series(origins_end: date | None = None) -> None:
    """Daily minimum balance per partner over the evaluated weeks, with the agent (k-means segments)
    and with a fixed rule set from the 16 weeks before (``scripts/exante_buffer_experiment.py``)."""
    from treasury.backtest import Dataset, run
    from treasury.experiments import PROPOSED, factory, matched_buffer
    from treasury.harness import default_origins
    from treasury.segmentation import KMeansSegmenter

    dataset = Dataset.load(DATA)
    cfg = dataset.configs.policy()
    rail = "swift" if "swift" in dataset.configs.rails() else "wire"
    end = origins_end or date.fromisoformat(dataset.params["end"])
    evaluated = default_origins(end, n=8, step_days=7, horizon=14)
    calibration = [evaluated[0] - timedelta(days=7 * k) for k in range(16, 0, -1)]
    days, _ = matched_buffer(dataset, rail, 0.0, calibration, cfg)
    results = {"prefoundly": run(dataset, factory(PROPOSED, 1000), "forecast", rail, cfg, evaluated, n_paths=1000,
                                 segmenter=KMeansSegmenter()),
               "fixed": run(dataset, None, "fixed", rail, replace(cfg, fixed_buffer_days=days), evaluated)}
    out = {"buffer_days": days, "capital": {k: r.metrics["capital_total_mean"] for k, r in results.items()},
           "shortfall_rate": {k: r.metrics["shortfall_rate"] for k, r in results.items()}, "partners": {}}
    for name, res in results.items():
        log = res.ledger_log.assign(day=pd.to_datetime(res.ledger_log["at"]).dt.normalize())
        daily = log.groupby(["partner", "day"])["balance"].min().reset_index()
        for pid, g in daily.groupby("partner"):
            out["partners"].setdefault(pid, {})[name] = {"days": [d.strftime("%Y-%m-%d") for d in g["day"]],
                                                         "min": g["balance"].round(0).tolist()}
    SERIES.parent.mkdir(parents=True, exist_ok=True)
    SERIES.write_text(json.dumps(out))


class _Handler(BaseHTTPRequestHandler):
    def _send(self, body: bytes, kind: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        if self.path.startswith("/api/state"):
            self._send(json.dumps(state(), default=str).encode(), "application/json")
        elif self.path in ("/", "/index.html"):
            self._send(PAGE.read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/logo.png":
            self._send(LOGO.read_bytes(), "image/png")
        else:
            self.send_error(404)

    def log_message(self, *args) -> None:
        pass


def serve(port: int = 8600, background_series: bool = True) -> ThreadingHTTPServer:
    """Start the dashboard on 127.0.0.1:``port``; computes the balance series in the background when
    it is not cached yet."""
    if background_series and not SERIES.exists():
        threading.Thread(target=compute_series, daemon=True).start()
    return ThreadingHTTPServer(("127.0.0.1", port), _Handler)


def seed(days: list[str], rail: str = "wire") -> None:
    """Run and execute the agent's 09:00 review on each day, in order, into the shared ledger and runs
    log (the same thing the MCP tool ``run_review(execute=true)`` does)."""
    from treasury.agent.executor import TransferLedger
    from treasury.agent.guardrails import load_autonomy
    from treasury.agent.run import run_day
    from treasury.backtest import Dataset
    from treasury.segmentation import KMeansSegmenter

    dataset = Dataset.load(DATA)
    autonomy = load_autonomy(dataset.configs.dir / "policy.yaml")
    autonomy = replace(autonomy, enabled=autonomy.enabled and not _paused())
    for d in days:
        record_run(run_day(dataset, pd.Timestamp(d), TransferLedger(LEDGER), rail=rail, autonomy=autonomy,
                           segmenter=KMeansSegmenter()))
