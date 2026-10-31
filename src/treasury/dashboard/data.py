"""Tables the dashboard shows, built only from existing functions; no Streamlit here.

The stress rerun re-simulates the last ``STRESS_DAYS`` of the base population with the saved
seed and the chosen scenarios, forecasts the last ``FORECAST_DAYS`` with a ``SegmentLGBM`` fitted
before them, and reads the policy's decision at the evening review of that week's first day (the
last of ``review_hours_247``). On a 24/7 rail that is the review that funds the next day: at the
morning one the whole day's forecast outflow is placed at the review, before any deposit can land,
so the deposit is always 0. On a business-day rail an order from that review lands when the next
business day's review would.

The model is fitted on the base population re-simulated over its whole period with
``experiments.PAST_CAMPAIGNS`` (same users, seed and parameters): on the base data every
``campaign_lift`` is 1, so a model fitted there cannot learn what a campaign does and would ignore
the campaign and FX sliders.
"""

from __future__ import annotations

import copy
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from treasury.agent.queue import APPROVALS_NEEDED, Proposal
from treasury.agent.tools import ToolContext, explain_components, get_policy_decision
from treasury.backtest import CONFIG, HORIZON, Dataset
from treasury.calendar import Calendar
from treasury.experiments import LABELS, MODEL_FACTORIES, PAST_CAMPAIGNS, RAILS, factory
from treasury.features import build_drivers
from treasury.harness import default_origins, rolling_origin
from treasury.metrics import pit
from treasury.models.base import daily_node_table, daily_partner_table
from treasury.models.seasonal_naive import seasonal_mean
from treasury.models.segment_lgbm import SegmentLGBM
from treasury.obligations import detect_recurring
from treasury.policy import load_policy
from treasury.rails import load_rails
from treasury.routing import load_partners, route_events
from treasury.simulate import (
    Campaign,
    CohortWave,
    FxJump,
    PartnerOutage,
    SimParams,
    apply_cohort_waves,
    generate_users,
    load_archetypes,
    scenario_overrides,
    simulate_events,
)
from treasury.simulate.pipeline import simulate_routed

STRESS_DAYS = 60
FORECAST_DAYS = 7
FX_DAYS = 3
STRESS_RAIL = "stablecoin"
EXPERIMENT_TABLES = ("ablation_pooled", "ablation_by_partner", "factorial", "frontier", "unknown_scenario")
ABLATION_COLUMNS = ["label", "model", "wape_q50", "pinball_q90", "cov_90", "pit_ks"]
FACTORIAL_COLUMNS = ["rail", "cell", "policy", "buffer_days", "capital_total_mean", "shortfall_rate", "cost_total",
                     "n_transfers", "rail_note"]
CELLS = ("reference", "proposed", "reference_matched")


def load_experiments(folder: Path) -> dict[str, pd.DataFrame]:
    """Every CSV of ``folder`` by file stem."""
    return {p.stem: pd.read_csv(p) for p in sorted(Path(folder).glob("*.csv"))}


def headline(factorial: pd.DataFrame) -> pd.DataFrame:
    """Per rail the success-criterion comparison: ``proposed`` vs ``reference_matched`` (the fixed
    buffer at the proposed policy's service level) and ``capital_saved = 1 - proposed / matched``."""
    cells = factorial.set_index(["rail", "cell"])
    rows = []
    for rail in RAILS:
        prop, ref = cells.loc[(rail, "proposed")], cells.loc[(rail, "reference_matched")]
        rows.append({
            "rail": rail, "proposed_capital": prop["capital_total_mean"],
            "proposed_shortfall_rate": prop["shortfall_rate"], "matched_buffer_days": ref["buffer_days"],
            "matched_capital": ref["capital_total_mean"], "matched_shortfall_rate": ref["shortfall_rate"],
            "capital_saved": 1 - prop["capital_total_mean"] / ref["capital_total_mean"],
        })
    return pd.DataFrame(rows)


def factorial_view(factorial: pd.DataFrame) -> pd.DataFrame:
    """The factorial's cells per rail in ``CELLS`` order; ``equal_service`` marks the two cells
    that are at the same service level (``proposed`` and ``reference_matched``)."""
    order = {c: i for i, c in enumerate(CELLS)}
    view = factorial.assign(_r=factorial["rail"].map(list(RAILS).index), _c=factorial["cell"].map(order))
    view = view.sort_values(["_r", "_c"], ignore_index=True)[FACTORIAL_COLUMNS]
    return view.assign(equal_service=view["cell"] != "reference")


def config_alpha(factorial: pd.DataFrame) -> float:
    """The alpha of the factorial's ``proposed`` cells (``policy`` is ``forecast_a<alpha>``)."""
    policy = factorial.loc[factorial["cell"] == "proposed", "policy"].iloc[0]
    return float(policy.removeprefix("forecast_a"))


def frontier_at_alpha(frontier: pd.DataFrame, alpha: float, factorial: pd.DataFrame | None = None) -> pd.DataFrame:
    """Per rail the proposed policy at ``alpha`` and the cheapest fixed buffer of the sweep whose
    shortfall rate is at most the proposed one's (NaN when none is); ``source = "sweep"``.

    At the factorial's ``config_alpha`` (when ``factorial`` is given) the rows are the factorial's
    ``proposed`` and ``reference_matched`` cells instead (``source = "factorial"``): the buffer found
    by bisection, so the saving matches ``headline``."""
    if factorial is not None and np.isclose(alpha, config_alpha(factorial)):
        head = headline(factorial)
        return pd.DataFrame({
            "rail": head["rail"], "alpha": alpha, "proposed_capital": head["proposed_capital"],
            "proposed_shortfall_rate": head["proposed_shortfall_rate"], "fixed_days": head["matched_buffer_days"],
            "fixed_capital": head["matched_capital"], "fixed_shortfall_rate": head["matched_shortfall_rate"],
            "capital_saved": head["capital_saved"], "source": "factorial",
        })
    rows = []
    for rail, g in frontier.groupby("rail", sort=False):
        prop = g[(g["policy"] == "forecast") & np.isclose(g["param"], alpha)].iloc[0]
        safe = g[(g["policy"] == "fixed") & (g["shortfall_rate"] <= prop["shortfall_rate"])]
        best = safe.loc[safe["capital_total_mean"].idxmin()] if len(safe) else None
        fixed_capital = best["capital_total_mean"] if best is not None else np.nan
        rows.append({
            "rail": rail, "alpha": alpha, "proposed_capital": prop["capital_total_mean"],
            "proposed_shortfall_rate": prop["shortfall_rate"],
            "fixed_days": best["param"] if best is not None else np.nan, "fixed_capital": fixed_capital,
            "fixed_shortfall_rate": best["shortfall_rate"] if best is not None else np.nan,
            "capital_saved": 1 - prop["capital_total_mean"] / fixed_capital, "source": "sweep",
        })
    return pd.DataFrame(rows)


def surprise_summary(unknown: pd.DataFrame) -> pd.DataFrame:
    """The pooled rows of ``unknown_scenario.csv``: forecast scores and the policy's backtest of
    (c) and (d) when the test campaign and cohort wave are announced and when they are a surprise."""
    cols = ["label", "model", "variant", "pinball_q90", "cov_90", "capital_total_mean", "shortfall_rate"]
    return unknown[unknown["scope"] == "pooled"][cols].reset_index(drop=True)


def pit_values(
    dataset: Dataset, n_origins: int = 4, models: Sequence[str] = tuple(MODEL_FACTORIES), n_paths: int = 1000,
) -> pd.DataFrame:
    """``label, model, pit`` of every forecast point of ``rolling_origin`` (``HORIZON`` days at the
    last ``n_origins`` weekly origins)."""
    origins = default_origins(dataset.end, n=n_origins, step_days=7, horizon=HORIZON)
    frames = []
    for model in models:
        preds = rolling_origin(dataset.history, dataset.drivers, factory(model, n_paths), origins, horizon=HORIZON)
        frames.append(pd.DataFrame({"label": LABELS[model], "model": model, "pit": pit(preds["actual"], preds)}))
    return pd.concat(frames, ignore_index=True)


def queue_frame(proposals: Sequence[Proposal]) -> pd.DataFrame:
    """One display row per proposal, newest first; ``approvals`` as ``given/needed``."""
    rows = [{
        **{k: v for k, v in asdict(p).items() if k not in ("approvals", "rejection")},
        "approvals": f"{len(p.approvals)}/{APPROVALS_NEEDED.get(p.tier, 0)}",
        "approvers": ", ".join(a["approver"] for a in p.approvals),
        "rejection": f"{p.rejection['approver']}: {p.rejection['reason']}" if p.rejection else "",
    } for p in proposals]
    frame = pd.DataFrame(rows)
    return frame.sort_values("created_at", ascending=False, ignore_index=True) if len(frame) else frame


@dataclass(frozen=True)
class StressSpec:
    """The stress tab's controls. Every scenario covers the forecast week; the FX jump starts
    ``fx_day`` days into it and lasts ``FX_DAYS``. ``payday_hypothesis`` None keeps the saved users."""

    campaign_lift: float = 1.0
    campaign_product: str = "bill_payment"
    cohort_size: int = 0
    cohort_segment: str = "young_heavy"
    fx_lift: float = 1.0
    fx_day: int = 0
    outage: bool = False
    outage_partner: str = "bills_aggregator"
    reroute_to: str = "remittance"
    payday_hypothesis: str | None = None

    def scenarios(self, first: date, last: date) -> list:
        out: list = []
        if self.campaign_lift != 1.0:
            out.append(Campaign(first, last, (self.campaign_product,), self.campaign_lift))
        if self.cohort_size > 0:
            out.append(CohortWave(first, self.cohort_size, self.cohort_segment))
        if self.fx_lift != 1.0:
            out.append(FxJump(first + timedelta(days=self.fx_day), FX_DAYS, self.fx_lift))
        if self.outage:
            out.append(PartnerOutage(self.outage_partner, first, last, self.reroute_to))
        return out


@dataclass(eq=False)
class StressBase:
    """What every rerun shares: the training dataset and the model fitted before ``as_of``."""

    train: Dataset
    users: pd.DataFrame
    model: SegmentLGBM
    as_of: pd.Timestamp
    dates: pd.DatetimeIndex
    window_start: date
    archetypes: dict
    params: SimParams
    seed: int
    cal: Calendar
    partners: dict
    rails: dict
    inflow: dict[str, np.ndarray]
    recurring: pd.DataFrame


def _params(p: dict, payday_hypothesis: str | None = None) -> SimParams:
    return SimParams(sigma_m=p["sigma_m"], phi=p["phi"], payday_hypothesis=payday_hypothesis or p["payday_hypothesis"],
                     inflation_monthly=p["inflation_monthly"])


def build_stress_base(base: Dataset, n_paths: int = 1000) -> StressBase:
    """Re-simulate ``base``'s population with ``PAST_CAMPAIGNS`` and fit ``SegmentLGBM`` on the
    days before ``as_of = end - FORECAST_DAYS + 1``."""
    p, end = base.params, base.end
    cal = Calendar.from_yaml(CONFIG / "calendar_ar.yaml")
    partners, rails = load_partners(CONFIG / "partners.yaml"), load_rails(CONFIG / "rails.yaml")
    archetypes, params = load_archetypes(CONFIG / "archetypes.yaml"), _params(p)
    users, events, macro = simulate_routed(p["n_users"], archetypes, cal, partners, date.fromisoformat(p["start"]),
                                           end, p["seed"], params, PAST_CAMPAIGNS)
    train = Dataset.from_frames(users, events, p, macro, PAST_CAMPAIGNS)
    as_of = pd.Timestamp(end - timedelta(days=FORECAST_DAYS - 1))
    dates = pd.date_range(as_of, periods=FORECAST_DAYS, freq="D")
    model = SegmentLGBM(n_paths=n_paths)
    model.fit(train.history[train.history["date"] < as_of], train.drivers[train.drivers["date"] < as_of])
    past = daily_partner_table(train.history[train.history["date"] < as_of]).pivot(index="date", columns="partner",
                                                                                   values="inflow")
    unconfirmed = events[~events["confirmed"] & (events["direction"] == 1)]
    return StressBase(
        train=train, users=base.users, model=model, as_of=as_of, dates=dates,
        window_start=end - timedelta(days=STRESS_DAYS - 1), archetypes=archetypes, params=params, seed=p["seed"],
        cal=cal, partners=partners, rails=rails,
        inflow={pid: np.nan_to_num(seasonal_mean(past[pid], dates)) for pid in partners},
        recurring=detect_recurring(unconfirmed, as_of),
    )


def review_at(as_of: pd.Timestamp) -> pd.Timestamp:
    return as_of + pd.Timedelta(hours=max(load_policy(CONFIG / "policy.yaml").review_hours_247))


@dataclass(eq=False)
class StressRun:
    """One rerun: ``table`` per partner (``rail_used, target, amount, p_unresolvable,
    forecast_week`` = mean forecast outflow over the week, ``realized_week`` = the re-simulated
    outflow), the ``ctx`` it was decided on and the ``balances`` it started from."""

    table: pd.DataFrame
    ctx: ToolContext
    balances: dict[str, float]


def _resimulate(sb: StressBase, spec: StressSpec, scenarios: list) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Users and routed events of ``[window_start, end]`` under ``scenarios``."""
    end = sb.dates[-1].date()
    params = sb.params if spec.payday_hypothesis is None else replace(sb.params, payday_hypothesis=spec.payday_hypothesis)
    users = sb.users
    if spec.payday_hypothesis is not None:
        first = date.fromisoformat(sb.train.params["start"])
        users = generate_users(len(sb.users), sb.archetypes, first, sb.train.end, sb.seed, params)
    users = apply_cohort_waves(users, scenarios, sb.archetypes, sb.seed, params)
    events, _ = simulate_events(users, sb.archetypes, sb.cal, sb.window_start, end, params, scenarios, sb.seed)
    return users, route_events(events, sb.partners, sb.cal, scenario_overrides(scenarios, sb.partners))


def stress_run(sb: StressBase, spec: StressSpec, balances: dict[str, float] | None = None) -> StressRun:
    """Re-simulate with ``spec``, forecast the week from the model's fit and decide every partner on
    ``STRESS_RAIL`` (its only rail when it does not take it) at ``review_at`` (see the module).

    ``balances`` (available, nothing in transit) defaults to this run's own targets, so a run
    without ``balances`` deposits nothing: pass the baseline's to read what a scenario adds."""
    scenarios = spec.scenarios(sb.dates[0].date(), sb.dates[-1].date())
    users, routed = _resimulate(sb, spec, scenarios)
    window = pd.date_range(sb.window_start, sb.dates[-1], freq="D")
    drivers = build_drivers(users, routed, window, scenarios)
    before = sb.train.drivers[sb.train.drivers["date"] < pd.Timestamp(sb.window_start)]
    drivers = pd.concat([before, drivers[before.columns]], ignore_index=True)
    model = copy.copy(sb.model)  # predict stores its paths on the model; keep the cached one untouched
    model.predict(sb.dates, drivers[drivers["date"] <= sb.dates[-1]])
    cfg = load_policy(CONFIG / "policy.yaml")
    ctx = ToolContext(
        model=model, dataset=replace(sb.train, drivers=drivers, cache={}), partners=sb.partners, rails=sb.rails,
        cal=sb.cal, policy_cfg=cfg, balances={pid: 0.0 for pid in sb.partners},
        pending_credits={pid: [] for pid in sb.partners}, review_at=review_at(sb.as_of),
        forecast_run_id=f"stress@{sb.as_of.date()}", queue=None, inflow=sb.inflow, recurring=sb.recurring,
    )
    if balances is None:
        balances = {pid: get_policy_decision(ctx, pid, STRESS_RAIL)["target"] for pid in sb.partners}
    ctx.balances = dict(balances)
    week = daily_partner_table(daily_node_table(routed))
    week = week[week["date"].between(sb.dates[0], sb.dates[-1])].groupby("partner")["outflow"].sum()
    mean_week = model.last_paths.mean(axis=0).sum(axis=0)
    rows = []
    for pid in sb.partners:
        d = get_policy_decision(ctx, pid, STRESS_RAIL)
        rows.append({
            "partner": pid, "rail_used": d["rail_used"], "balance": ctx.balances[pid], "target": d["target"],
            "amount": d["amount"], "p_unresolvable": d["p_unresolvable"],
            "forecast_week": float(mean_week[model.partner_index.index(pid)]),
            "realized_week": float(week.get(pid, 0.0)),
        })
    return StressRun(pd.DataFrame(rows), ctx, dict(balances))


def compare(baseline: pd.DataFrame, stressed: pd.DataFrame) -> pd.DataFrame:
    """``stressed`` with ``delta_<col>`` against ``baseline`` for target, deposit, forecast and
    realized week."""
    base = baseline.set_index("partner")
    out = stressed.set_index("partner").copy()
    for col, name in (("target", "delta_target"), ("amount", "delta_amount"), ("forecast_week", "delta_forecast_week"),
                      ("realized_week", "delta_realized_week")):
        out[name] = out[col] - base[col].reindex(out.index)
    return out.reset_index()


def components(run: StressRun, partner: str) -> pd.DataFrame:
    """``explain_components`` of ``partner`` on every forecast date, one row per date with the
    residual's segments as ``segment:<name>`` columns."""
    rows = []
    for day in run.ctx.model.last_dates:
        c = explain_components(run.ctx, partner, day.date().isoformat())
        rows.append({
            "date": c["date"], "confirmed": c["confirmed"], "predicted_recurring": c["predicted_recurring"],
            "residual_total": c["residual_total"], "factor_share": c["factor_share"],
            **{f"segment:{s}": v for s, v in c["residual_by_segment"].items()},
        })
    return pd.DataFrame(rows).fillna(0.0)
