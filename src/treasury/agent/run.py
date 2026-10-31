"""Daily run of the agent: the policy decides, the LLM explains, a human approves.

For each partner the deterministic policy computes the deposit first. The LLM (optional) reads
the decision and the tools' outputs and writes a rationale plus an optional ``exception``; it
cannot change the amount. Every number in its rationale must appear in the tool outputs, else a
templated rationale replaces it. The result is queued for approval; nothing executes a payment.
"""

from __future__ import annotations

import json
import logging
import math
import re
from collections.abc import Sequence

import anthropic
import numpy as np
import pandas as pd

from treasury.agent import tools
from treasury.agent.queue import ApprovalQueue, Proposal, tier_for
from treasury.agent.tools import ToolContext
from treasury.backtest import CONFIG, HORIZON, TRAILING_DAYS, Dataset
from treasury.calendar import Calendar
from treasury.models.base import daily_partner_table
from treasury.models.seasonal_naive import seasonal_mean
from treasury.models.segment_lgbm import SegmentLGBM
from treasury.obligations import detect_recurring
from treasury.policy import PolicyConfig, load_policy
from treasury.rails import load_rails
from treasury.routing import Partner, load_partners

log = logging.getLogger(__name__)

MODEL = "claude-opus-5-5"
MAX_ROUNDS = 8
SYSTEM = """You explain treasury funding decisions to the humans who approve them.

A deterministic policy has already decided how much to deposit at one partner. You cannot change
that amount. Your job is to explain it and to flag anomalies.

Rules:
- Use the tools to read the forecast, the balance, the decision and its components.
- Cite only numbers returned by the tools, written as they appear or rounded (thousands separators
  and percentages are fine). Do not compute new numbers, do not invent any. Name quantiles as
  q05/q50/q95/q99 rather than writing their levels.
- You may call propose_transfer once for the partner, with exactly the policy amount. If you do
  not, the deposit is queued for you with your final rationale.
- Set exception only when you see an anomaly a human should look at, such as p_unresolvable above
  0.05 or a forecast far above the partner's usual level; otherwise null.
- Finish with only a JSON object: {"rationale": "<two or three sentences>", "exception": null}."""

_DATETIME = re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:[+-]\d{2}:\d{2})?)?|\b\d{1,2}:\d{2}\b")
_NUMBER = re.compile(r"(?<![\w.,])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?")


def _round_sig(x: float, sig: int) -> float:
    return 0.0 if x == 0 else round(x, sig - 1 - math.floor(math.log10(abs(x))))


def _tool_numbers(value) -> list[float]:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return []
    if isinstance(value, dict):
        return [n for v in value.values() for n in _tool_numbers(v)]
    if isinstance(value, list | tuple):
        return [n for v in value for n in _tool_numbers(v)]
    return [abs(float(value))] if math.isfinite(float(value)) else []


def validate_rationale(rationale: str, tool_outputs: Sequence) -> bool:
    """True when every number in ``rationale`` appears among the numbers of ``tool_outputs``.

    Dates and clock times are skipped. A token (``1,234.5``, ``12``, ``1.2%`` read as ``0.012``)
    matches a tool number when both round to the same ``min(3, digits shown)`` significant digits,
    so ``1.2%`` cites ``0.0123`` and ``1,230,000`` cites ``1,234,567.9``. Signs are ignored.
    """
    known = _tool_numbers(list(tool_outputs))
    for token in _NUMBER.findall(_DATETIME.sub(" ", rationale)):
        digits = re.sub(r"\D", "", token).lstrip("0")
        sig = max(1, min(3, len(digits)))
        value = float(token.rstrip("%").replace(",", "")) / (100 if token.endswith("%") else 1)
        if not any(math.isclose(_round_sig(t, sig), _round_sig(value, sig), rel_tol=1e-9) for t in known):
            return False
    return True


def templated_rationale(decision: dict, balance: dict) -> str:
    return (f"Target {decision['target']:,.0f}, available {balance['available']:,.0f}, deposit "
            f"{decision['amount']:,.0f} via {decision['rail_used']}; p_unresolvable "
            f"{decision['p_unresolvable']:.1%} [templated]")


def _final_json(text: str) -> tuple[str, str | None] | None:
    try:
        parsed = json.loads(text[text.index("{"): text.rindex("}") + 1])
    except ValueError:
        return None
    if not isinstance(parsed, dict) or not isinstance(parsed.get("rationale"), str):
        return None
    exception = parsed.get("exception")
    return parsed["rationale"], exception if isinstance(exception, str) and exception.strip() else None


def _explain(ctx: ToolContext, client, partner: str, rail: str, decision: dict, fallback: str) -> Proposal:
    """Run the tool-use loop for one partner and queue the proposal it ends in."""
    outputs: list[dict] = [decision]
    made: list[Proposal] = []

    def propose(args: dict) -> dict:
        if args.get("partner") != partner or args.get("rail") != rail:
            raise ValueError(f"this review is for {partner} on {rail}")
        rationale = args["rationale"] if validate_rationale(args["rationale"], outputs) else fallback
        out = tools.propose_transfer(ctx, partner, rail, args["amount"], rationale, args.get("exception"))
        made.append(Proposal(**out))
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
    final = None
    try:
        for _ in range(MAX_ROUNDS):
            response = client.messages.create(model=MODEL, max_tokens=16000, system=SYSTEM, tools=tools.TOOL_SCHEMAS,
                                              messages=messages, output_config={"effort": "medium"})
            if response.stop_reason != "tool_use":
                if response.stop_reason == "end_turn":
                    final = _final_json("".join(b.text for b in response.content if b.type == "text"))
                break
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": [run_tool(b) for b in response.content if b.type == "tool_use"]})
    except anthropic.APIError:
        final = None  # the API failing must not stop the queue: fall back to the template
    if made:
        return made[0]
    rationale, exception = final if final else (fallback, None)
    if not validate_rationale(rationale, outputs):
        rationale = fallback
    return Proposal(**tools.propose_transfer(ctx, partner, rail, decision["amount"], rationale, exception))


def propose_for_day(ctx: ToolContext, client=None, rail: str = "stablecoin") -> list[Proposal]:
    """One proposal per partner the policy funds, in partner order. With ``client=None`` the LLM is
    skipped and every rationale is templated. A deposit above ``T3_dual_max`` is logged as blocked
    and not queued. A partner that already has a proposal for ``ctx.forecast_run_id`` keeps it
    (re-running a day queues nothing new)."""
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
        fallback = templated_rationale(decision, tools.get_balance(ctx, partner))
        if client is None:
            out.append(Proposal(**tools.propose_transfer(ctx, partner, rail, decision["amount"], fallback)))
        else:
            out.append(_explain(ctx, client, partner, decision["rail_used"], decision, fallback))
    return out


def fixed_buffer_balances(dataset: Dataset, partners: dict[str, Partner], as_of: pd.Timestamp,
                          cfg: PolicyConfig) -> dict[str, float]:
    """``fixed_buffer_days`` × the trailing 28-day mean drain before ``as_of``, as the backtest's
    opening balances: what a fixed-buffer treasury would hold at the review."""
    daily = daily_partner_table(dataset.history)
    daily = daily[(daily["date"] < as_of) & (daily["date"] >= as_of - pd.Timedelta(days=TRAILING_DAYS))]
    nets = daily["partner"].map({p: q.nets_inflows for p, q in partners.items()})
    drain = (daily["outflow"] - daily["inflow"] * nets).groupby(daily["partner"]).mean()
    return {pid: float(cfg.fixed_buffer_days * max(drain.get(pid, 0.0), 0.0)) for pid in partners}


def build_context(dataset: Dataset, as_of: pd.Timestamp, queue: ApprovalQueue, n_paths: int = 2000,
                  horizon: int = HORIZON) -> ToolContext:
    """Fit ``SegmentLGBM`` on the data before ``as_of``, forecast up to ``horizon`` days (no further
    than the drivers reach) and review at ``review_hour`` on ``as_of`` with fixed-buffer balances
    and nothing in transit."""
    as_of = pd.Timestamp(as_of).normalize()
    cal, cfg = Calendar.from_yaml(CONFIG / "calendar_ar.yaml"), load_policy(CONFIG / "policy.yaml")
    partners, rails = load_partners(CONFIG / "partners.yaml"), load_rails(CONFIG / "rails.yaml")
    history, drivers = dataset.history, dataset.drivers
    dates = pd.date_range(as_of, min(as_of + pd.Timedelta(days=horizon - 1), drivers["date"].max()), freq="D")
    model = SegmentLGBM(n_paths=n_paths)
    model.fit(history[history["date"] < as_of], drivers[drivers["date"] < as_of])
    model.predict(dates, drivers[drivers["date"] <= dates[-1]])
    past = daily_partner_table(history[history["date"] < as_of]).pivot(index="date", columns="partner", values="inflow")
    events = dataset.events
    return ToolContext(
        model=model, dataset=dataset, partners=partners, rails=rails, cal=cal, policy_cfg=cfg,
        balances=fixed_buffer_balances(dataset, partners, as_of, cfg),
        pending_credits={pid: [] for pid in partners},
        review_at=as_of + pd.Timedelta(hours=cfg.review_hour),
        forecast_run_id=f"{model.name}@{as_of.date()}",
        queue=queue,
        inflow={pid: np.nan_to_num(seasonal_mean(past[pid], dates)) for pid in partners},
        recurring=detect_recurring(events[~events["confirmed"] & (events["direction"] == 1)], as_of),
    )
