"""Command-line entry point: ``simulate`` a routed dataset, ``backtest`` a policy, run the ``experiments``,
and the ``agent`` that queues transfer proposals for human approval or runs autonomously within hard
limits (``agent run``, simulated execution)."""

from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path

import pandas as pd
import typer

from treasury.configset import ConfigSet
from treasury.simulate import SimParams, validate
from treasury.simulate.pipeline import simulate_routed
from treasury.simulate.scenarios import Scenario

CONFIG = Path(__file__).resolve().parents[2] / "config"

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback()
def main() -> None:
    """Predictive treasury for a wallet's prefunded partner balances."""


@app.command()
def simulate(
    users: int = 20_000,
    start: datetime = typer.Option("2025-11-01", formats=["%Y-%m-%d"]),
    end: datetime = typer.Option("2026-10-31", formats=["%Y-%m-%d"]),
    seed: int = 42,
    out: Path = Path("data/sim/base"),
    payday_hypothesis: str = "late",
    sigma_m: float = 0.15,
    phi: float = 0.7,
    config: str = "domestic",
) -> None:
    """Simulate users and routed events; write users, events, macro parquet and params.json to OUT.

    CONFIG is the config set: domestic (config/), intl (config/intl/) or a directory. A config set with a ``market.yaml`` (intl) also simulates daily exchange rates, written to
    fx.parquet, and makes demand react to them and to the tourism season."""
    from treasury.fx import demand_scenarios, simulate_fx

    began = time.perf_counter()
    configs = ConfigSet.resolve(config)
    market = configs.market()
    params = SimParams(sigma_m=sigma_m, phi=phi, payday_hypothesis=payday_hypothesis,
                       **({"inflation_monthly": market["amount_inflation_monthly"]} if market else {}))
    cal = configs.calendar()
    first, last = start.date(), end.date()
    fx = simulate_fx(market, pd.date_range(first, last, freq="D"), seed) if market else None
    scenarios: list[Scenario] = demand_scenarios(market, fx) if market else []

    population, routed, macro = simulate_routed(users, configs.archetypes(), cal, configs.partners(), first, last, seed,
                                                params, scenarios, configs.settle_calendars())
    checks = validate(routed, cal)

    out.mkdir(parents=True, exist_ok=True)
    population.to_parquet(out / "users.parquet", index=False)
    routed.to_parquet(out / "events.parquet", index=False)
    macro.to_parquet(out / "macro.parquet", index=False)
    if fx is not None:
        fx.to_parquet(out / "fx.parquet", index=False)
    meta = {
        "config": config,
        **asdict(params),
        "seed": seed,
        "n_users": len(population),
        "start": first.isoformat(),
        "end": last.isoformat(),
        "n_events": len(routed),
        "validation": checks,
    }
    (out / "params.json").write_text(json.dumps(meta, indent=2) + "\n")
    typer.echo(f"{len(routed):,} events for {len(population):,} users in {time.perf_counter() - began:.1f}s -> {out}")
    typer.echo(json.dumps(checks))


@app.command()
def backtest(
    data: Path = Path("data/sim/base"),
    model: str = "segment_factor",
    rail: str = "stablecoin",
    policy: str = typer.Option("forecast", help="forecast or fixed"),
    alpha: float | None = None,
    n_paths: int = 1000,
    n_origins: int = 8,
    central_reserve: float = 0.0,
) -> None:
    """Walk-forward backtest of one policy and rail; prints its metrics as JSON."""
    from treasury.backtest import HORIZON, Dataset, run
    from treasury.experiments import MODEL_FACTORIES, factory
    from treasury.harness import default_origins

    if policy not in ("forecast", "fixed"):
        raise typer.BadParameter(f"policy must be forecast or fixed, got {policy!r}")
    if model not in MODEL_FACTORIES:
        raise typer.BadParameter(f"model must be one of {list(MODEL_FACTORIES)}, got {model!r}")
    dataset = Dataset.load(data)
    cfg = dataset.configs.policy()
    cfg = cfg if alpha is None else replace(cfg, alpha=alpha)
    origins = default_origins(dataset.end, n=n_origins, step_days=7, horizon=HORIZON)
    result = run(dataset, factory(model, n_paths) if policy == "forecast" else None, policy, rail, cfg, origins,
                 central_reserve=central_reserve, n_paths=n_paths)
    metrics = {k: None if isinstance(v, float) and math.isnan(v) else v for k, v in result.metrics.items()}
    typer.echo(json.dumps(metrics, indent=2))


@app.command()
def experiments(data: Path = Path("data/sim/base"), out: Path = Path("reports/experiments"), n_paths: int = 1000) -> None:
    """Write the ablation, factorial, frontier, designed-to-lose and unknown-scenario CSVs to OUT."""
    from treasury.experiments import run_all

    began = time.perf_counter()
    timings = run_all(data, out, n_paths)
    typer.echo(json.dumps(timings))
    typer.echo(f"experiments written to {out} in {time.perf_counter() - began:.0f}s")


@app.command("intl-experiments")
def intl_experiments(data: Path = Path("data/sim/intl"), out: Path = Path("reports/experiments"),
                     n_paths: int = 1000) -> None:
    """Write intl_factorial.csv (fixed buffer vs proposed, swift vs stablecoin, in USD) and its per-partner table."""
    from treasury.intl import run_intl

    began = time.perf_counter()
    table, _ = run_intl(data, out, n_paths)
    cols = ["rail", "variant", "cell", "buffer_days", "capital_usd", "shortfall_rate", "n_transfers", "fees_usd"]
    typer.echo(table[cols].to_string(index=False))
    typer.echo(f"intl experiments written to {out} in {time.perf_counter() - began:.0f}s")


agent = typer.Typer(no_args_is_help=True, help="Transfers: the policy decides, the LLM explains, a human approves "
                    "(propose) or the agent executes within hard limits (run).")
app.add_typer(agent, name="agent")
QUEUE = Path("data/queue.jsonl")
LEDGER = Path("data/transfers.jsonl")


def _show(proposal) -> None:
    typer.echo(json.dumps(asdict(proposal), indent=2))


def _decide(action) -> None:
    """Run a queue action and show the result; an unknown id or a refused change exits 1."""
    try:
        _show(action())
    except KeyError as e:
        raise typer.BadParameter(f"no proposal with id {e}") from None
    except ValueError as e:
        typer.echo(f"refused: {e}", err=True)
        raise typer.Exit(1) from None


@agent.command("propose")
def agent_propose(
    data: Path = Path("data/sim/base"),
    as_of: datetime = typer.Option("2026-10-26", formats=["%Y-%m-%d"]),
    rail: str = "stablecoin",
    no_llm: bool = typer.Option(False, "--no-llm", help="Templated rationales, no API call."),
    queue: Path = QUEUE,
    n_paths: int = 2000,
    start_balances: str = typer.Option("target", help="Opening balances: 'target' (the policy's own target at the "
                                       "previous day's review) or 'fixed' (fixed_buffer_days of trailing mean drain)."),
) -> None:
    """Fit the segment model on data before AS_OF, queue one proposal per partner the policy funds.

    Balances start at the policy's own target for the day before AS_OF (--start-balances target,
    the default) or at the fixed-buffer target (fixed), with nothing in transit (demo). Without
    --no-llm, ANTHROPIC_API_KEY must be set; the LLM only writes the rationale and may flag an
    exception."""
    import logging
    import os

    from treasury.agent.queue import ApprovalQueue
    from treasury.agent.run import START_BALANCES, build_context, propose_for_day
    from treasury.backtest import Dataset

    if start_balances not in START_BALANCES:
        raise typer.BadParameter(f"--start-balances must be one of {', '.join(START_BALANCES)}")
    logging.basicConfig(format="%(levelname)s %(message)s")
    client = None
    if not no_llm:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise typer.BadParameter("set ANTHROPIC_API_KEY or pass --no-llm")
        import anthropic

        client = anthropic.Anthropic(api_key=key)
    ctx = build_context(Dataset.load(data), as_of, ApprovalQueue(queue), n_paths=n_paths, rail=rail,
                        start_balances=start_balances)
    for proposal in propose_for_day(ctx, client=client, rail=rail):
        _show(proposal)


@agent.command("run")
def agent_run(
    as_of: datetime = typer.Option("2026-10-26", formats=["%Y-%m-%d", "%Y-%m-%dT%H:%M"],
                                   help="Review day (YYYY-MM-DD, reviewed at review_hour) or instant (YYYY-MM-DDTHH:MM)."),
    rail: str = typer.Option("stablecoin", help="Preferred rail, one of the dataset's config set (stablecoin, "
                             "wire; intl: swift)."),
    data: Path = Path("data/sim/base"),
    out: Path = Path("reports/demo/agent_run.json"),
    ledger: Path = LEDGER,
    no_llm: bool = typer.Option(False, "--no-llm", help="Templated rationales even if ANTHROPIC_API_KEY is set."),
    n_paths: int = 2000,
    segments: str = typer.Option("kmeans", help="kmeans: segments inferred from transactions; labels: the "
                                 "simulator's own segment labels."),
) -> None:
    """Autonomous daily run: forecast, decide, apply the limits and guardrails of config/policy.yaml
    (autonomy), execute (simulated, into the ledger) and print a summary; writes the run as JSON to OUT.

    Idempotent per partner and review time: rerunning the same review sends nothing new. The LLM
    writes the rationale only when ANTHROPIC_API_KEY is set (and not --no-llm); it never changes an
    amount."""
    import logging
    import os

    from treasury.agent.executor import TransferLedger
    from treasury.agent.run import format_summary, run_day
    from treasury.backtest import Dataset

    dataset = Dataset.load(data)
    known = sorted(dataset.configs.rails())
    if rail not in known:
        raise typer.BadParameter(f"--rail must be one of {', '.join(known)} for this dataset, got {rail!r}")
    logging.basicConfig(format="%(levelname)s %(message)s")
    client = None
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key and not no_llm:
        import anthropic

        client = anthropic.Anthropic(api_key=key)
    if segments not in ("kmeans", "labels"):
        raise typer.BadParameter(f"--segments must be kmeans or labels, got {segments!r}")
    from treasury.segmentation import KMeansSegmenter

    segmenter = KMeansSegmenter() if segments == "kmeans" else None
    result = run_day(dataset, as_of, TransferLedger(ledger), rail=rail, client=client, n_paths=n_paths,
                     segmenter=segmenter)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    typer.echo(format_summary(result))
    typer.echo(f"\n-> {out} · ledger {ledger}")


@agent.command("approve")
def agent_approve(id: str, approver: str = typer.Option(...), queue: Path = QUEUE) -> None:
    """Approve a pending proposal (T3 needs two distinct approvers). Executes nothing."""
    from treasury.agent.queue import ApprovalQueue

    _decide(lambda: ApprovalQueue(queue).approve(id, approver))


@agent.command("reject")
def agent_reject(id: str, approver: str = typer.Option(...), reason: str = typer.Option(...), queue: Path = QUEUE) -> None:
    """Reject a pending proposal with a reason."""
    from treasury.agent.queue import ApprovalQueue

    _decide(lambda: ApprovalQueue(queue).reject(id, approver, reason))


@agent.command("list")
def agent_list(status: str | None = None, queue: Path = QUEUE) -> None:
    """Latest state of every proposal, optionally only those with STATUS."""
    from treasury.agent.queue import ApprovalQueue

    for proposal in ApprovalQueue(queue).list(status=status):
        _show(proposal)
