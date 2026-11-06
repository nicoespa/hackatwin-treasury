"""Daily run of the agent: the policy decides, the LLM explains, and either a human approves or the
agent executes within hard limits.

For each partner the deterministic policy computes the deposit first. The LLM (optional) reads the
decision and the tools' outputs and writes a rationale plus an optional ``exception``; it cannot
change the amount. Every number in its rationale must appear in the tool outputs, else a templated
rationale replaces it.

Two modes:

- ``propose_for_day``: the deposit is queued for human approval by tier (``agent.queue``); nothing
  is executed.
- ``run_day`` / ``execute_day`` (autonomous, no human in the loop): the policy amount goes through
  the guardrails of ``agent.guardrails`` (kill switch, stale or missing forecast, sanity bound,
  ``p_unresolvable`` alert, per-transfer / per-partner-day / all-partners-day limits from
  ``config/policy.yaml`` → ``autonomy``) and the simulated executor (``agent.executor``) records the
  transfer, idempotent per partner and review time, into the partner's allow-listed account. When the
  policy amount exceeds a limit the agent sends the limit (rounded down to the lot) and alerts with the
  remainder rather than sending nothing, since a partner left short rejects user payments. No network
  call moves money.
"""

from __future__ import annotations

import json
import logging
import math
import re
import tempfile
from collections.abc import Sequence
from dataclasses import asdict, replace
from pathlib import Path
from typing import Literal

import anthropic
import numpy as np
import pandas as pd
import yaml

from treasury.agent import tools
from treasury.agent.executor import SimulatedExecutor, TransferLedger, idempotency_key
from treasury.agent.guardrails import AutonomyConfig, check, load_autonomy, money
from treasury.agent.queue import ApprovalQueue, Proposal, Tiers, tier_for
from treasury.agent.tools import ToolContext
from treasury.backtest import (
    CONFIG,
    HORIZON,
    TRAILING_DAYS,
    Dataset,
    Segmenter,
    _rail_for,
    segmented_inputs,
)
from treasury.calendar import Calendar
from treasury.features import known_at
from treasury.ledger import Credit
from treasury.models.base import daily_partner_table
from treasury.models.seasonal_naive import seasonal_mean
from treasury.models.segment_lgbm import SegmentLGBM
from treasury.obligations import detect_recurring
from treasury.policy import PolicyConfig, recommend_deposit
from treasury.rails import Rail
from treasury.routing import Partner

log = logging.getLogger(__name__)

MODEL = "claude-opus-5-5"
MAX_ROUNDS = 8
EXCEPTION_P_UNRESOLVABLE = 0.05
RULES = {"exception_p_unresolvable": EXCEPTION_P_UNRESOLVABLE}  # thresholds of the prompt, citable
SYSTEM = f"""You explain treasury funding decisions to the humans who approve them.

A deterministic policy has already decided how much to deposit at one partner. You cannot change
that amount. Your job is to explain it and to flag anomalies.

Rules:
- Use the tools to read the forecast, the balance, the decision and its components.
- Cite only numbers returned by the tools, written as they appear or rounded (thousands separators
  and percentages are fine). Do not compute new numbers, do not invent any. Name quantiles as
  q05/q50/q95/q99 rather than writing their levels. The rationale must cite the policy amount or
  target.
- You may call propose_transfer once for the partner, with exactly the policy amount. If you do
  not, the deposit is queued for you with your final rationale.
- Set exception only when you see an anomaly a human should look at, such as p_unresolvable above
  {EXCEPTION_P_UNRESOLVABLE} or a forecast far above the partner's usual level; otherwise null.
- Finish with only a JSON object: {{"rationale": "<two or three sentences>", "exception": null}}."""

_DATETIME = re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:[+-]\d{2}:\d{2})?)?|\b\d{1,2}:\d{2}\b")
_NUMBER = re.compile(r"(?<![\w.,])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?")


def _round_sig(x: float, sig: int) -> float:
    return 0.0 if x == 0 else round(x, sig - 1 - math.floor(math.log10(abs(x))))


def _same(a: float, b: float, sig: int) -> bool:
    return math.isclose(_round_sig(a, sig), _round_sig(b, sig), rel_tol=1e-9)


def _tool_numbers(value) -> list[float]:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return []
    if isinstance(value, dict):
        return [n for v in value.values() for n in _tool_numbers(v)]
    if isinstance(value, list | tuple):
        return [n for v in value for n in _tool_numbers(v)]
    return [abs(float(value))] if math.isfinite(float(value)) else []


def validate_rationale(
    rationale: str, tool_outputs: Sequence, must_cite: Sequence[float] = (), require_number: bool = True,
) -> bool:
    """True when every number in ``rationale`` appears among the numbers of ``tool_outputs``, at
    least one number is cited (unless ``require_number`` is False) and, when ``must_cite`` is
    given, one of the cited numbers is one of them (the policy amount or target).

    Dates and clock times are skipped. A token (``1,234.5``, ``12``, ``1.2%`` read as ``0.012``)
    matches a number when both round to the same ``min(3, digits shown)`` significant digits, so
    ``1.2%`` cites ``0.0123`` and ``1,230,000`` cites ``1,234,567.9``. Signs are ignored.
    """
    known = _tool_numbers(list(tool_outputs))
    cited: list[tuple[float, int]] = []
    for token in _NUMBER.findall(_DATETIME.sub(" ", rationale)):
        sig = max(1, min(3, len(re.sub(r"\D", "", token).lstrip("0"))))
        value = float(token.rstrip("%").replace(",", "")) / (100 if token.endswith("%") else 1)
        if not any(_same(t, value, sig) for t in known):
            return False
        cited.append((value, sig))
    if (require_number or must_cite) and not cited:
        return False
    return not must_cite or any(_same(abs(m), v, sig) for v, sig in cited for m in must_cite)


def templated_rationale(decision: dict, balance: dict, reason: str) -> str:
    return (f"Target {decision['target']:,.0f}, available {balance['available']:,.0f}, deposit "
            f"{decision['amount']:,.0f} via {decision['rail_used']}; p_unresolvable "
            f"{decision['p_unresolvable']:.1%} [templated: {reason}]")


def _final_json(text: str) -> tuple[str, str | None] | None:
    try:
        parsed = json.loads(text[text.index("{"): text.rindex("}") + 1])
    except ValueError:
        return None
    if not isinstance(parsed, dict) or not isinstance(parsed.get("rationale"), str):
        return None
    exception = parsed.get("exception")
    return parsed["rationale"], exception if isinstance(exception, str) and exception.strip() else None


def _explain(ctx: ToolContext, client, partner: str, rail: str, decision: dict, balance: dict) -> Proposal:
    """Run the tool-use loop for one partner and queue the proposal it ends in. Every fallback to
    the template, and every dropped exception, is logged with the partner and the reason."""
    outputs: list[dict] = [decision, RULES]
    made: list[Proposal] = []

    def checked(rationale: str, exception: str | None) -> tuple[str, str | None, list[str]]:
        notes = []
        if not validate_rationale(rationale, outputs, must_cite=(decision["amount"], decision["target"])):
            notes.append("templated rationale (rationale rejected by the validator)")
            rationale = templated_rationale(decision, balance, "rationale rejected by the validator")
        if exception is not None and not validate_rationale(exception, outputs, require_number=False):
            notes.append(f"exception dropped, it cites numbers absent from the tool outputs: {exception!r}")
            exception = None
        return rationale, exception, notes

    def propose(args: dict) -> dict:
        if args.get("partner") != partner or args.get("rail") != rail:
            raise ValueError(f"this review is for {partner} on {rail}")
        rationale, exception, notes = checked(args["rationale"], args.get("exception"))
        out = tools.propose_transfer(ctx, partner, rail, args["amount"], rationale, exception)
        made.append(Proposal(**out))
        for note in notes:
            log.warning("%s: %s", partner, note)
        return out

    def run_tool(block) -> dict:
        try:
            args = dict(block.input)
            out = propose(args) if block.name == "propose_transfer" else tools.dispatch(ctx, block.name, args)
        except (KeyError, TypeError, ValueError) as e:
            return {"type": "tool_result", "tool_use_id": block.id, "content": f"error: {e}", "is_error": True}
        if block.name != "propose_transfer":  # its rationale must not vouch for itself
            outputs.append(out)
        return {"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(out)}

    messages: list[dict] = [{"role": "user", "content": f"Review the deposit for partner {partner} on rail {rail}. "
                             "The policy decision:\n" + json.dumps(decision)}]
    final, reason = None, None
    try:
        for _ in range(MAX_ROUNDS):
            response = client.messages.create(model=MODEL, max_tokens=16000, system=SYSTEM, tools=tools.TOOL_SCHEMAS,
                                              messages=messages, output_config={"effort": "medium"})
            if response.stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": [run_tool(b) for b in response.content
                                                             if b.type == "tool_use"]})
                continue
            if response.stop_reason == "end_turn":
                final = _final_json("".join(b.text for b in response.content if b.type == "text"))
                reason = None if final else "unparseable final JSON"
            else:
                reason = str(response.stop_reason)  # refusal, max_tokens, ...
            break
        else:
            reason = f"round cap of {MAX_ROUNDS} exhausted"
    except anthropic.APIError as e:
        log.warning("LLM call failed for %s: %s", partner, e, exc_info=True)
        reason = "LLM call failed"
    if made:
        return made[0]
    if final is None:
        log.warning("%s: templated rationale (%s)", partner, reason)
        rationale, exception, notes = templated_rationale(decision, balance, reason), None, []
    else:
        rationale, exception, notes = checked(*final)
    proposal = Proposal(**tools.propose_transfer(ctx, partner, rail, decision["amount"], rationale, exception))
    for note in notes:
        log.warning("%s: %s", partner, note)
    return proposal


def propose_for_day(ctx: ToolContext, client=None, rail: str = "stablecoin") -> list[Proposal]:
    """One proposal per partner the policy funds, in partner order. With ``client=None`` the LLM is
    skipped and every rationale is templated (``[templated: offline]``). A deposit above
    ``T3_dual_max`` is logged as blocked and not queued. A partner that already has a proposal for
    ``ctx.forecast_run_id`` keeps it (re-running a day queues nothing new)."""
    existing = {p.partner: p for p in ctx.queue.list() if p.forecast_run_id == ctx.forecast_run_id}
    out = []
    for partner in ctx.partners:
        if partner in existing:
            out.append(existing[partner])
            continue
        decision = tools.get_policy_decision(ctx, partner, rail)
        if decision["amount"] <= 0:
            continue
        if tier_for(decision["amount"], ctx.queue.tiers) == "T4_blocked":
            log.warning("%s: %s via %s is above T3_dual_max; blocked, not queued", partner,
                        f"{decision['amount']:,.0f}", decision["rail_used"])
            continue
        balance = tools.get_balance(ctx, partner)
        if client is None:
            rationale = templated_rationale(decision, balance, "offline")
            out.append(Proposal(**tools.propose_transfer(ctx, partner, rail, decision["amount"], rationale)))
        else:
            out.append(_explain(ctx, client, partner, decision["rail_used"], decision, balance))
    return out


def fixed_buffer_balances(dataset: Dataset, partners: dict[str, Partner], as_of: pd.Timestamp,
                          cfg: PolicyConfig) -> dict[str, float]:
    """``fixed_buffer_days`` × the trailing 28-day mean drain before ``as_of``, as the backtest's
    opening balances: what a fixed-buffer treasury would hold at the review."""
    drain = _trailing_drain(dataset, partners, as_of).mean()
    return {pid: float(cfg.fixed_buffer_days * max(drain.get(pid, 0.0), 0.0)) for pid in partners}


def _trailing_drain(dataset: Dataset, partners: dict[str, Partner], as_of: pd.Timestamp):
    """Daily net drain (outflow, minus inflow for partners that net it) of the ``TRAILING_DAYS``
    before ``as_of``, grouped by partner."""
    daily = daily_partner_table(dataset.history)
    daily = daily[(daily["date"] < as_of) & (daily["date"] >= as_of - pd.Timedelta(days=TRAILING_DAYS))]
    nets = daily["partner"].map({p: q.nets_inflows for p, q in partners.items()})
    return (daily["outflow"] - daily["inflow"] * nets).groupby(daily["partner"])


def trailing_max_drain(dataset: Dataset, partners: dict[str, Partner], as_of: pd.Timestamp) -> dict[str, float]:
    """The largest daily net drain of each partner over the ``TRAILING_DAYS`` before ``as_of``."""
    drain = _trailing_drain(dataset, partners, pd.Timestamp(as_of).normalize()).max()
    return {pid: float(max(drain.get(pid, 0.0), 0.0)) for pid in partners}


def target_balances(model: SegmentLGBM, dataset: Dataset, partners: dict[str, Partner], rails: dict[str, Rail],
                    rail: str, day: pd.Timestamp, last_date: pd.Timestamp, cal: Calendar,
                    cfg: PolicyConfig, rail_cals: dict[str, Calendar] | None = None,
                    inputs: tuple[pd.DataFrame, pd.DataFrame] | None = None) -> dict[str, float]:
    """The policy's own ``target`` per partner at the last review of ``day`` on ``rail`` (or the
    partner's only rail): ``review_hour`` on business-day rails, the last of ``review_hours_247``
    on 24/7 ones, whose evening window covers the next day. ``model``'s paths run from ``day`` to
    ``last_date``; this overwrites its last prediction. ``inputs`` replaces the dataset's
    ``(history, drivers)`` (segmented ones, for instance)."""
    history, drivers = inputs or (dataset.history, dataset.drivers)
    day = pd.Timestamp(day).normalize()
    dates = pd.date_range(day, last_date, freq="D")
    model.predict(dates, known_at(drivers[drivers["date"] <= last_date], day))
    past = daily_partner_table(history[history["date"] < day]).pivot(index="date", columns="partner", values="inflow")
    out = {}
    for pid, p in partners.items():
        rail_used = _rail_for(p, rails, rail)
        hour = cfg.review_hour if rail_used.business_days_only else max(cfg.review_hours_247)
        paths = model.last_paths[:, :, model.partner_index.index(pid)]
        out[pid] = recommend_deposit(paths, dates, p, rail_used, 0.0, [], day + pd.Timedelta(hours=hour),
                                     (rail_cals or {}).get(pid, cal), cfg,
                                     inflow_forecast=np.nan_to_num(seasonal_mean(past[pid], dates))).target
    return out


START_BALANCES = ("target", "fixed")


def build_context(dataset: Dataset, as_of: pd.Timestamp, queue: ApprovalQueue, n_paths: int = 2000,
                  horizon: int = HORIZON, rail: str = "stablecoin",
                  start_balances: Literal["target", "fixed"] = "target",
                  segmenter: Segmenter | None = None) -> ToolContext:
    """Fit ``SegmentLGBM`` on the data before ``as_of``, forecast up to ``horizon`` days (no further
    than the drivers reach) and review at ``review_hour`` on ``as_of`` with nothing in transit.

    ``start_balances="target"`` starts each partner at the policy's own target at the last review of
    the day before (``target_balances`` on ``rail``, same fitted model): a treasury already running
    the policy. ``"fixed"`` starts at ``fixed_buffer_balances``, which on wire partners leaves many
    paths short before the deposit instructed on ``as_of`` lands.

    With ``segmenter`` the model's segments are inferred from the transactions before ``as_of``
    (``backtest.segmented_inputs``) instead of read from the data's ``segment`` column."""
    if start_balances not in START_BALANCES:
        raise ValueError(f"start_balances must be one of {START_BALANCES}, got {start_balances!r}")
    as_of = pd.Timestamp(as_of).normalize()
    configs = dataset.configs
    cal, cfg, partners, rails = configs.joint_calendar(), configs.policy(), configs.partners(), configs.rails()
    rail_cals = {pid: configs.rail_calendar(p) for pid, p in partners.items()}
    if segmenter is None:
        history, drivers = dataset.history, dataset.drivers
    else:
        history, drivers, _ = segmented_inputs(dataset, segmenter, as_of.date())
    dates = pd.date_range(as_of, min(as_of + pd.Timedelta(days=horizon - 1), drivers["date"].max()), freq="D")
    model = SegmentLGBM(n_paths=n_paths)
    model.fit(history[history["date"] < as_of], drivers[drivers["date"] < as_of])
    if start_balances == "target":
        balances = target_balances(model, dataset, partners, rails, rail, as_of - pd.Timedelta(days=1), dates[-1], cal,
                                   cfg, rail_cals, (history, drivers))
    else:
        balances = fixed_buffer_balances(dataset, partners, as_of, cfg)
    model.predict(dates, known_at(drivers[drivers["date"] <= dates[-1]], as_of))
    past = daily_partner_table(history[history["date"] < as_of]).pivot(index="date", columns="partner", values="inflow")
    events = dataset.events
    return ToolContext(
        model=model, dataset=dataset, partners=partners, rails=rails, cal=cal, policy_cfg=cfg,
        balances=balances,
        pending_credits={pid: [] for pid in partners},
        review_at=as_of + pd.Timedelta(hours=cfg.review_hour),
        forecast_run_id=f"{model.name}@{as_of.date()}",
        queue=queue,
        inflow={pid: np.nan_to_num(seasonal_mean(past[pid], dates)) for pid in partners},
        recurring=detect_recurring(events[~events["confirmed"] & (events["direction"] == 1)], as_of),
        rail_cals=rail_cals,
    )


# --- autonomous mode -------------------------------------------------------------------------------

FORECAST_DAYS_OUT = 7  # days of forecast quantiles per partner in the run's JSON


def partner_currencies(partners: dict[str, Partner], path=CONFIG / "partners.yaml") -> dict[str, str]:
    """Each partner's ``currency``: the ``Partner`` field when it has one, else the ``currency`` key
    of its entry in ``partners.yaml``, else ``ARS``."""
    raw = yaml.safe_load(Path(path).read_text()) or {}
    return {pid: (raw.get(pid) or {}).get("currency") or getattr(p, "currency", None) or "ARS"
            for pid, p in partners.items()}


def _forecast_days(ctx: ToolContext, partner: str) -> list[dict]:
    """Quantiles of each forecast day after the review day, up to ``FORECAST_DAYS_OUT`` days."""
    f = tools.get_forecast(ctx, partner)
    rows = [{"date": d, **{q: f[q][i] for q in ("q05", "q50", "q95", "q99")}} for i, d in enumerate(f["dates"])]
    return [r for r in rows if r["date"] > ctx.review_at.date().isoformat()][:FORECAST_DAYS_OUT]


def _rationale(ctx: ToolContext, client, partner: str, decision: dict, balance: dict) -> tuple[str, str | None]:
    """The LLM's rationale and exception for the policy decision (its scratch proposal goes to a
    queue that is thrown away), or the templated rationale offline or when the policy sends nothing."""
    if client is None or decision["amount"] <= 0:
        return templated_rationale(decision, balance, "offline" if client is None else "no deposit"), None
    with tempfile.TemporaryDirectory() as tmp:
        scratch = replace(ctx, queue=ApprovalQueue(Path(tmp) / "scratch.jsonl", tiers=_UNBOUNDED))
        proposal = _explain(scratch, client, partner, decision["rail_used"], decision, balance)
    return proposal.rationale, proposal.exception


_UNBOUNDED = Tiers(math.inf, math.inf, math.inf)


def execute_day(ctx: ToolContext, ledger: TransferLedger, data_through: pd.Timestamp | None, rail: str = "stablecoin",
                autonomy: AutonomyConfig | None = None, client=None) -> dict:
    """Decide, guard and execute (simulated) every partner's deposit at ``ctx.review_at``, with no
    human in the loop. Returns the run as a JSON-serialisable dict (see ``run_day``).

    Per partner: transfers in the ledger still in transit at the review become its pending credits;
    the policy decides; ``guardrails.check`` caps or holds the amount (``data_through`` is the last
    day of data behind the forecast, ``None`` when there is none); the executor records the transfer.
    A partner whose idempotency key (partner + review time) is already in the ledger reports that
    transfer and sends nothing new. The LLM, when ``client`` is given, only writes the rationale."""
    configs = ctx.dataset.configs
    cfg = autonomy or load_autonomy(configs.dir / "policy.yaml")
    executor = SimulatedExecutor(ledger, cfg, ctx.rails, ctx.cal, ctx.rail_cals)
    review_at = pd.Timestamp(ctx.review_at)
    age = None if data_through is None else (review_at - (pd.Timestamp(data_through).normalize()
                                                          + pd.Timedelta(days=1))) / pd.Timedelta(hours=1)
    currencies = partner_currencies(ctx.partners, configs.dir / "partners.yaml")
    max_drain = trailing_max_drain(ctx.dataset, ctx.partners, review_at)
    pending = {pid: [Credit(pd.Timestamp(t.arrival_at), t.amount) for t in ledger.in_transit(pid, review_at)]
               for pid in ctx.partners}
    ctx = replace(ctx, pending_credits=pending)
    rows = []
    for pid in ctx.partners:
        currency = currencies[pid]
        rail_used = _rail_for(ctx.partners[pid], ctx.rails, rail).name
        try:
            decision = tools.get_policy_decision(ctx, pid, rail)
            forecast = _forecast_days(ctx, pid)
        except ValueError as e:  # the forecast does not cover this partner's decision window
            log.warning("%s: forecast missing: %s", pid, e)
            decision, forecast = None, []
        balance = tools.get_balance(ctx, pid)
        existing = ledger.get(idempotency_key(pid, review_at))
        if existing is not None:
            transfer, status = existing, "already_executed"
            alerts, limit, remainder = existing.alerts, existing.limit_applied, existing.policy_amount - existing.amount
        else:
            verdict = check(cfg, partner=pid, rail=rail_used, currency=currency,
                            policy_amount=decision["amount"] if decision else 0.0,
                            p_unresolvable=decision["p_unresolvable"] if decision else None,
                            forecast_age_hours=age if decision else None, trailing_max_drain=max_drain[pid],
                            spent_partner_today=ledger.instructed_on(review_at, currency, pid),
                            spent_all_today=ledger.instructed_on(review_at, currency),
                            lot_size=ctx.policy_cfg.lot_size, p_threshold=EXCEPTION_P_UNRESOLVABLE)
            alerts, limit, remainder = [asdict(a) for a in verdict.alerts], verdict.limit_applied, verdict.remainder
            transfer = None
            if verdict.amount > 0:
                transfer, _ = executor.execute(pid, rail_used, verdict.amount, currency, review_at, ctx.forecast_run_id,
                                               decision["amount"], limit, alerts)
                status = "capped" if limit else "executed"
            else:
                status = "held" if alerts else "no_deposit"
        for a in alerts:
            log.warning("%s: alert %s (%s): %s", pid, a["code"], a["action"], a["message"])
        rationale, exception = _rationale(ctx, client, pid, decision, balance) if decision else (None, None)
        rows.append({
            "partner": pid, "currency": currency, "rail": rail_used, "destination": cfg.destination(pid, rail_used),
            "status": status,
            "forecast_tomorrow": forecast[0] if forecast else None,
            "available": balance["available"],
            "in_transit": float(sum(c.amount for c in pending[pid])),
            "need": decision["target"] if decision else None,
            "p_unresolvable": decision["p_unresolvable"] if decision else None,
            "policy_amount": decision["amount"] if decision else None,
            "executed_amount": transfer.amount if transfer else 0.0,
            "limit_applied": limit,
            "remainder": remainder,
            "transfer": asdict(transfer) | {"status": transfer.status_at(review_at)} if transfer else None,
            "eta": transfer.arrival_at if transfer else None,
            "alerts": alerts,
            "rationale": rationale,
            "exception": exception,
            "forecast_7d": forecast,
        })
    totals = {}
    for cur in sorted(set(currencies.values())):
        limits = cfg.limits.get(cur)
        totals[cur] = {"executed_in_run": float(sum(r["executed_amount"] for r in rows if r["currency"] == cur)),
                       "instructed_today": ledger.instructed_on(review_at, cur),
                       "max_all_partners_day": limits.max_all_partners_day if limits else None}
    return {
        "as_of": review_at.date().isoformat(), "review_at": review_at.isoformat(), "rail": rail,
        "forecast_run_id": ctx.forecast_run_id, "seed": ctx.model.seed, "n_paths": ctx.model.n_paths,
        "data_through": None if data_through is None else pd.Timestamp(data_through).date().isoformat(),
        "forecast_age_hours": age, "llm": client is not None,
        "autonomy": {"enabled": cfg.enabled, "max_forecast_age_hours": cfg.max_forecast_age_hours,
                     "sanity_multiple": cfg.sanity_multiple, "limits": {c: asdict(v) for c, v in cfg.limits.items()}},
        "totals": totals, "ledger": str(ledger.path), "partners": rows,
    }


def run_day(dataset: Dataset, as_of: pd.Timestamp, ledger: TransferLedger, rail: str = "stablecoin",
            autonomy: AutonomyConfig | None = None, client=None, n_paths: int = 2000,
            segmenter: Segmenter | None = None) -> dict:
    """Autonomous daily run at ``as_of``: fit and forecast as ``build_context`` (opening balances at
    the policy's target of the day before), then ``execute_day``. An ``as_of`` at midnight reviews at
    ``review_hour``; any other time reviews at that instant. The data behind the forecast ends the
    day before ``as_of``.

    The result has the run's metadata, the autonomy limits, per-currency totals and one row per
    partner: forecast for tomorrow (q05..q99), available balance, in-transit credits, need (the
    policy's target), policy and executed amounts, the limit applied and the remainder, rail,
    destination, ETA, alerts, the rationale and the next ``FORECAST_DAYS_OUT`` days of quantiles."""
    as_of = pd.Timestamp(as_of)
    day = as_of.normalize()
    with tempfile.TemporaryDirectory() as tmp:
        ctx = build_context(dataset, day, ApprovalQueue(Path(tmp) / "unused.jsonl", tiers=_UNBOUNDED),
                            n_paths=n_paths, rail=rail, segmenter=segmenter)
    if as_of != day:
        ctx = replace(ctx, review_at=as_of)
    past = dataset.history["date"][dataset.history["date"] < day]
    return execute_day(ctx, ledger, past.max() if len(past) else None, rail, autonomy, client)


def format_summary(result: dict) -> str:
    """Short Spanish summary of an autonomous run, one block per partner."""
    state = "activo" if result["autonomy"]["enabled"] else "APAGADO (kill switch)"
    lines = [f"Agente autónomo · revisión {result['review_at'][:16].replace('T', ' ')} · riel preferido "
             f"{result['rail']} · ejecución {state} · LLM {'sí' if result['llm'] else 'no (rationale templado)'}"]
    for r in result["partners"]:
        cur, f = r["currency"], r["forecast_tomorrow"]
        lines.append(f"\n{r['partner']} [{cur}] → {r['rail']}")
        if f:
            lines.append(f"  Pronóstico mañana ({f['date']}): q50 {money(f['q50'], cur)} · q99 {money(f['q99'], cur)}")
        else:
            lines.append("  Pronóstico: no disponible")
        lines.append(f"  Saldo disponible {money(r['available'], cur)} · en tránsito {money(r['in_transit'], cur)} "
                     f"· necesidad {money(r['need'], cur)}")
        decided = f"  Decidido {money(r['policy_amount'], cur)} · ejecutado {money(r['executed_amount'], cur)}"
        if r["limit_applied"]:
            decided += f" (tope {r['limit_applied']}, faltan {money(r['remainder'], cur)})"
        if r["eta"]:
            decided += f" · llega {r['eta'][:16].replace('T', ' ')}"
        lines.append(decided + f" · estado {r['status']}")
        for a in r["alerts"]:
            lines.append(f"  ALERTA [{a['code']}/{a['action']}] {a['message']}")
    for cur, t in result["totals"].items():
        cap = f" de {money(t['max_all_partners_day'], cur)} diarios" if t["max_all_partners_day"] else ""
        lines.append(f"\nTotal {cur}: ejecutado en esta corrida {money(t['executed_in_run'], cur)}; "
                     f"instruido hoy {money(t['instructed_today'], cur)}{cap}")
    return "\n".join(lines)
