"""Tools the agent's LLM may call. Every one returns a JSON-serialisable dict built from the fitted
model, the dataset and the deterministic policy; ``propose_transfer`` is the only side effect and
it only appends to the approval queue (nothing here executes a payment)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from treasury.agent.queue import ApprovalQueue
from treasury.backtest import Dataset, _rail_for
from treasury.calendar import Calendar
from treasury.ledger import Credit
from treasury.models.segment_lgbm import SegmentLGBM
from treasury.policy import Decision, PolicyConfig, recommend_deposit
from treasury.rails import Rail
from treasury.routing import Partner


@dataclass
class ToolContext:
    """Everything a review reads. ``model`` has already predicted the days from ``review_at``;
    ``balances`` is the available balance per partner and ``pending_credits`` the deposits in
    transit; ``inflow`` the seasonal-mean inflow per partner on ``model.last_dates`` (credited only
    to partners that net inflows) and ``recurring`` the non-confirmed recurring outflow streams
    (``obligations.detect_recurring``)."""

    model: SegmentLGBM
    dataset: Dataset
    partners: dict[str, Partner]
    rails: dict[str, Rail]
    cal: Calendar
    policy_cfg: PolicyConfig
    balances: dict[str, float]
    pending_credits: dict[str, list[Credit]]
    review_at: pd.Timestamp
    forecast_run_id: str
    queue: ApprovalQueue
    inflow: dict[str, np.ndarray]
    recurring: pd.DataFrame
    rail_cals: dict[str, Calendar] = field(default_factory=dict)  # per partner; else ``cal``

    def cal_for(self, partner: str) -> Calendar:
        """Days a business-day rail moves money to ``partner`` (its country's and the home calendar)."""
        return self.rail_cals.get(partner, self.cal)


def _paths(ctx: ToolContext, partner: str) -> np.ndarray:
    return ctx.model.last_paths[:, :, ctx.model.partner_index.index(partner)]


def _decision(ctx: ToolContext, partner: str, rail: str) -> tuple[Decision, Rail]:
    """The policy's decision at ``review_at``. ``realized_today = 0``: the whole day's outflow is
    taken as still to come, the conservative reading of a balance observed at the review."""
    p, dates = ctx.partners[partner], ctx.model.last_dates
    rail_used = _rail_for(p, ctx.rails, rail)
    decision = recommend_deposit(
        _paths(ctx, partner), dates, p, rail_used, ctx.balances[partner], ctx.pending_credits.get(partner, []),
        ctx.review_at, ctx.cal_for(partner), ctx.policy_cfg, inflow_forecast=ctx.inflow[partner],
    )
    if decision.window_end.normalize() > dates[-1]:
        raise ValueError(f"forecast ends {dates[-1].date()}, before the window of {partner} ({decision.window_end})")
    return decision, rail_used


def get_forecast(ctx: ToolContext, partner: str) -> dict:
    """Quantiles of the partner's daily gross outflow on the forecast days from the review on."""
    dates = ctx.model.last_dates
    ahead = np.asarray(dates >= ctx.review_at.normalize())
    q = np.quantile(_paths(ctx, partner)[:, ahead], [0.05, 0.50, 0.95, 0.99], axis=0)
    out = {"partner": partner, "dates": [d.date().isoformat() for d in dates[ahead]]}
    return out | {k: [round(float(v), 2) for v in row] for k, row in zip(("q05", "q50", "q95", "q99"), q)}


def get_balance(ctx: ToolContext, partner: str) -> dict:
    return {
        "partner": partner,
        "available": float(ctx.balances[partner]),
        "pending_credits": [{"at": c.at.isoformat(), "amount": float(c.amount)} for c in ctx.pending_credits.get(partner, [])],
    }


def get_policy_decision(ctx: ToolContext, partner: str, rail: str) -> dict:
    """The deterministic deposit for ``partner`` (on ``rail`` if it accepts it, else its only
    rail), plus the policy's ``alpha`` and ``lot_size``."""
    decision, rail_used = _decision(ctx, partner, rail)
    fields = {k: v.isoformat() if isinstance(v, pd.Timestamp) else v for k, v in vars(decision).items()}
    return {"partner": partner, "rail_used": rail_used.name, **fields,
            "alpha": ctx.policy_cfg.alpha, "lot_size": ctx.policy_cfg.lot_size}


def explain_components(ctx: ToolContext, partner: str, date: str) -> dict:
    """What the forecast mean of ``partner`` on ``date`` is made of.

    ``confirmed`` is the known autodebit total (``confirmed_<partner>``); ``residual_by_segment``
    the model's node means summed per segment (their sum plus ``confirmed`` is the mean of the
    paths); ``predicted_recurring`` the expected non-confirmed recurring payments due that day
    (``p_occur × amount_median``, dated by payment rather than settlement), a part of the residual
    shown for context, not an extra amount. ``factor_share`` approximates the share of the day's
    variance (in relative terms) due to the common factor: ``sigma_f² / (sigma_f² + Σ(cv·mu)² /
    (Σ mu)²)`` over the partner's nodes, which treats the log-factor variance and the summed node
    noise as additive.
    """
    day = pd.Timestamp(date).normalize()
    if day not in ctx.model.last_dates:
        raise ValueError(f"{day.date()} is not a forecast date")
    nodes = ctx.model.last_node_means
    rows = nodes[(nodes["date"] == day) & (nodes["partner"] == partner)]
    mu_total = float(rows["mu"].sum())
    node_var = float(((rows["cv"] * rows["mu"]) ** 2).sum()) / mu_total**2 if mu_total > 0 else 0.0
    factor_var = ctx.model.sigma_f**2
    rec = ctx.recurring[(ctx.recurring["partner"] == partner) & (ctx.recurring["next_date"].dt.normalize() == day)]
    confirmed = ctx.dataset.drivers.set_index("date").at[day, f"confirmed_{partner}"]
    return {
        "partner": partner,
        "date": day.date().isoformat(),
        "confirmed": round(float(confirmed), 2),
        "predicted_recurring": round(float((rec["p_occur"] * rec["amount_median"]).sum()), 2),
        "residual_by_segment": {s: round(float(v), 2) for s, v in rows.groupby("segment")["mu"].sum().items()},
        "residual_total": round(mu_total, 2),
        "factor_share": round(factor_var / (factor_var + node_var), 4) if factor_var + node_var > 0 else 0.0,
    }


def propose_transfer(
    ctx: ToolContext, partner: str, rail: str, amount: float, rationale: str, exception: str | None = None,
) -> dict:
    """Queue the policy's deposit for approval. Refuses an ``amount`` more than one lot away from
    the policy amount, a partner the policy funds with nothing, and a second proposal for the same
    partner and forecast run. The queued amount is always the policy's."""
    decision, rail_used = _decision(ctx, partner, rail)
    lot = ctx.policy_cfg.lot_size
    if decision.amount <= 0:
        raise ValueError(f"the policy recommends no deposit for {partner}")
    if abs(float(amount) - decision.amount) > lot:
        raise ValueError(f"amount {float(amount):,.0f} differs from the policy amount {decision.amount:,.0f} "
                         f"by more than one lot ({lot:,.0f})")
    if any(p.partner == partner and p.forecast_run_id == ctx.forecast_run_id for p in ctx.queue.list()):
        raise ValueError(f"{partner} already has a proposal for forecast run {ctx.forecast_run_id}")
    return asdict(ctx.queue.propose(partner, rail_used.name, decision.amount, rationale, ctx.forecast_run_id, exception,
                                    seed=ctx.model.seed, n_paths=ctx.model.n_paths))


TOOLS: dict[str, Callable[..., dict]] = {
    f.__name__: f for f in (get_forecast, get_balance, get_policy_decision, explain_components, propose_transfer)
}

_PARTNER = {"type": "string", "description": "Partner id, e.g. card_network."}
_RAIL = {"type": "string", "enum": ["wire", "stablecoin"], "description": "Preferred rail."}


def _schema(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"name": name, "description": description,
            "input_schema": {"type": "object", "properties": properties, "required": required,
                             "additionalProperties": False}}


TOOL_SCHEMAS = [
    _schema("get_forecast", "Quantiles q05/q50/q95/q99 of the partner's daily gross outflow for each forecast "
            "day from the review on.", {"partner": _PARTNER}, ["partner"]),
    _schema("get_balance", "The partner's available balance and deposits in transit.", {"partner": _PARTNER},
            ["partner"]),
    _schema("get_policy_decision", "The deterministic funding policy's deposit: amount, target, p_unresolvable "
            "(share of paths short before the deposit lands), expected_shortfall_if_none, arrival and window end, "
            "rail_used, alpha and lot_size.", {"partner": _PARTNER, "rail": _RAIL}, ["partner", "rail"]),
    _schema("explain_components", "Decomposition of the forecast mean on one date: confirmed autodebits, model "
            "residual by segment, predicted recurring payments (part of the residual) and the common factor's "
            "share of the variance.", {"partner": _PARTNER, "date": {"type": "string", "description": "YYYY-MM-DD"}},
            ["partner", "date"]),
    _schema("propose_transfer", "Queue the policy's deposit for human approval (never executes a payment). "
            "amount must be exactly the policy amount; call at most once per partner.",
            {"partner": _PARTNER, "rail": _RAIL, "amount": {"type": "number"},
             "rationale": {"type": "string", "description": "Cites only numbers returned by the tools."},
             "exception": {"type": "string", "description": "Anomaly for the approver; omit if none."}},
            ["partner", "rail", "amount", "rationale"]),
]


def dispatch(ctx: ToolContext, name: str, args: dict) -> dict:
    """Run tool ``name`` with ``args``; ``KeyError`` for a tool that does not exist."""
    return TOOLS[name](ctx, **args)
