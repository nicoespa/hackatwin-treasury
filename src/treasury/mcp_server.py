"""MCP server: lets an AI agent watch and control the autonomous treasury agent.

Tools read the simulated dataset (``TREASURY_DATA``, default ``data/sim/intl``) and the transfer
ledger (``TREASURY_LEDGER``, default ``data/transfers_mcp.jsonl``). Executions are simulated: the
ledger is the only thing written. The pause switch is stored in ``TREASURY_STATE`` (default
``data/agent_state.json``) and overrides ``autonomy.enabled`` of the dataset's config set, so a
paused agent decides but sends nothing.

Run: ``treasury-mcp`` (stdio), or register it in an MCP client, e.g. Claude Code:
``claude mcp add prefoundly -- uv run --directory <repo> treasury-mcp``.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, replace
from functools import cache
from pathlib import Path

import pandas as pd
from mcp.server.mcpserver import MCPServer

from treasury.agent.executor import TransferLedger, ledger_status
from treasury.agent.guardrails import AutonomyConfig, load_autonomy
from treasury.agent.run import format_summary, run_day
from treasury.backtest import Dataset
from treasury.segmentation import KMeansSegmenter

DATA = Path(os.environ.get("TREASURY_DATA", "data/sim/intl"))
LEDGER = Path(os.environ.get("TREASURY_LEDGER", "data/transfers_mcp.jsonl"))
STATE = Path(os.environ.get("TREASURY_STATE", "data/agent_state.json"))

server = MCPServer(
    name="prefoundly",
    title="Prefoundly treasury agent",
    instructions=(
        "Tools to monitor and control a wallet's autonomous prefunding agent. Amounts are in each "
        "partner's currency. Dates are YYYY-MM-DD inside the simulated year. run_review with "
        "execute=false only shows what the agent would do; with execute=true it records simulated "
        "transfers, within hard limits the agent cannot change."
    ),
)


@cache
def _dataset() -> Dataset:
    return Dataset.load(DATA)


def _paused() -> bool:
    try:
        return bool(json.loads(STATE.read_text()).get("paused", False))
    except (FileNotFoundError, json.JSONDecodeError):
        return False


def _autonomy() -> AutonomyConfig:
    cfg = load_autonomy(_dataset().configs.dir / "policy.yaml")
    return replace(cfg, enabled=cfg.enabled and not _paused())


def _rails() -> list[str]:
    return sorted(_dataset().configs.rails())


def _check_rail(rail: str) -> None:
    if rail not in _rails():
        raise ValueError(f"rail must be one of {', '.join(_rails())}, got {rail!r}")


def _review(as_of: str, rail: str, execute: bool) -> dict:
    _check_rail(rail)
    if execute:
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        return run_day(_dataset(), pd.Timestamp(as_of), TransferLedger(LEDGER), rail=rail, autonomy=_autonomy(),
                       segmenter=KMeansSegmenter())
    with tempfile.TemporaryDirectory() as tmp:
        return run_day(_dataset(), pd.Timestamp(as_of), TransferLedger(Path(tmp) / "dry_run.jsonl"), rail=rail,
                       autonomy=_autonomy(), segmenter=KMeansSegmenter())


@server.tool()
def get_status(at: str | None = None) -> dict:
    """Whether the agent may execute, its limits per currency, and every transfer in the ledger with
    its status at ``at`` (YYYY-MM-DD[THH:MM], default: now in the simulation's last day)."""
    when = pd.Timestamp(at) if at else pd.Timestamp(_dataset().params["end"]) + pd.Timedelta(hours=23)
    cfg = _autonomy()
    return {
        "dataset": str(DATA), "executing": cfg.enabled, "paused": _paused(),
        "limits": {cur: asdict(v) for cur, v in cfg.limits.items()},
        "transfers": ledger_status(LEDGER, when) if LEDGER.exists() else [],
    }


@server.tool()
def get_limits() -> dict:
    """Hard limits per currency, allow-listed destination accounts and guardrail thresholds."""
    cfg = _autonomy()
    return {"limits": {cur: asdict(v) for cur, v in cfg.limits.items()}, "destinations": cfg.destinations,
            "max_forecast_age_hours": cfg.max_forecast_age_hours, "sanity_multiple": cfg.sanity_multiple}


@server.tool()
def forecast(partner: str, as_of: str, rail: str = "swift") -> dict:
    """Next 7 days of outflow quantiles (q05, q50, q95, q99) for ``partner``, plus what the policy
    needs at the 09:00 review of ``as_of`` on ``rail``. Nothing is executed."""
    run = _review(as_of, rail, execute=False)
    row = next((p for p in run["partners"] if p["partner"] == partner), None)
    if row is None:
        raise ValueError(f"unknown partner {partner!r}; known: {', '.join(p['partner'] for p in run['partners'])}")
    keys = ("partner", "currency", "rail", "available", "in_transit", "need", "policy_amount", "forecast_7d")
    return {k: row[k] for k in keys}


@server.tool()
def run_review(as_of: str, rail: str = "swift", execute: bool = False) -> dict:
    """The agent's 09:00 review of ``as_of``: forecast, decision, limits and guardrails per partner.
    ``execute=false`` (default) is a dry run; ``execute=true`` records simulated transfers in the
    ledger (idempotent per partner and review time). Returns a Spanish summary and the details."""
    run = _review(as_of, rail, execute)
    return {"executed": execute, "summary": format_summary(run), "partners": [
        {k: p[k] for k in ("partner", "currency", "rail", "status", "available", "need", "policy_amount",
                           "executed_amount", "limit_applied", "remainder", "eta", "alerts")}
        for p in run["partners"]]}


@server.tool()
def list_transfers(at: str | None = None) -> list[dict]:
    """Simulated transfers in the ledger with their status (instructed, in_transit, credited) at ``at``."""
    when = pd.Timestamp(at) if at else pd.Timestamp(_dataset().params["end"]) + pd.Timedelta(hours=23)
    return ledger_status(LEDGER, when) if LEDGER.exists() else []


@server.tool()
def set_autonomy(enabled: bool) -> dict:
    """Pause (``enabled=false``) or resume the agent's executions. A paused agent still reviews and
    reports, but sends nothing. Limits in the config set always apply on top."""
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"paused": not enabled}))
    return {"paused": not enabled, "executing": _autonomy().enabled}


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
