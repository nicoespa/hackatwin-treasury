"""Walk-forward backtest of a funding policy against the realized simulated events.

Each origin refits the model on the data before it and forecasts ``horizon`` days; the decisions
of the following ``step`` days use that forecast for the dates still ahead. Realized balances
come from the routed events by ``settle_at``, with each deposit landing at its rail's arrival.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

from treasury.calendar import Calendar
from treasury.configset import ConfigSet
from treasury.features import COHORT_PREFIXES, build_drivers, cohort_drivers, known_at
from treasury.ledger import Credit, balance_arrays
from treasury.models.base import Forecaster, daily_node_table, daily_partner_table
from treasury.models.seasonal_naive import seasonal_mean
from treasury.montecarlo import paths_from_quantiles
from treasury.policy import (
    PolicyConfig,
    fixed_buffer_decision,
    recommend_deposit,
    review_times,
)
from treasury.rails import Rail, arrival_time
from treasury.routing import Partner
from treasury.segmentation import MIN_TENURE_DAYS, NEW, Segmentation

Segmenter = Callable[[pd.DataFrame, pd.DataFrame, pd.Timestamp], Segmentation]  # with a ``name`` attribute

CONFIG = Path(__file__).resolve().parents[2] / "config"
HORIZON = 14
TRAILING_DAYS = 28  # window of the fixed buffer's trailing mean drain


@dataclass(eq=False)
class Dataset:
    """A routed simulation: ``users``, ``events`` and its ``params``, plus the node table
    ``history`` (dates up to ``params["end"]``) and the ``drivers`` over those dates. ``fx`` holds
    the exchange rates of the international variant; ``params["config"]`` names its config set."""

    users: pd.DataFrame
    events: pd.DataFrame
    params: dict
    history: pd.DataFrame
    drivers: pd.DataFrame
    macro: pd.DataFrame | None = None
    cache: dict = field(default_factory=dict, repr=False, compare=False)
    fx: pd.DataFrame | None = None

    @classmethod
    def load(cls, folder: str | Path) -> Dataset:
        folder = Path(folder)
        return cls.from_frames(
            pd.read_parquet(folder / "users.parquet"),
            pd.read_parquet(folder / "events.parquet"),
            params=json.loads((folder / "params.json").read_text()),
            macro=pd.read_parquet(folder / "macro.parquet"),
            fx=pd.read_parquet(folder / "fx.parquet") if (folder / "fx.parquet").exists() else None,
        )

    @classmethod
    def from_frames(
        cls, users: pd.DataFrame, events: pd.DataFrame, params: dict, macro: pd.DataFrame | None = None,
        scenarios: Sequence = (), fx: pd.DataFrame | None = None,
    ) -> Dataset:
        history = daily_node_table(events)
        history = history[history["date"] <= pd.Timestamp(params["end"])].reset_index(drop=True)
        dates = pd.date_range(history["date"].min(), history["date"].max(), freq="D")
        configs = ConfigSet.resolve(params.get("config"))
        drivers = build_drivers(users, events, dates, scenarios, fx=fx, market=configs.market(),
                                settle_lags=configs.settle_lags())
        return cls(users, events, params, history, drivers, macro, fx=fx)

    @property
    def configs(self) -> ConfigSet:
        """The config set of ``params["config"]``, with ``params["accepts_rails"]`` overrides if any."""
        return ConfigSet.resolve(self.params.get("config"), self.params.get("accepts_rails"))

    @property
    def end(self) -> date:
        return date.fromisoformat(self.params["end"])


@dataclass(frozen=True)
class Forecast:
    """One origin's forecast: ``paths [n_paths, n_dates, n_partners]`` of daily outflow, the
    seasonal-naive mean ``inflow [n_dates, n_partners]`` and the model's ``quantiles``."""

    origin: pd.Timestamp
    dates: pd.DatetimeIndex
    partners: list[str]
    paths: np.ndarray
    inflow: np.ndarray
    quantiles: pd.DataFrame


def segmented_inputs(
    dataset: Dataset, segmenter: Segmenter, origin: date,
) -> tuple[pd.DataFrame, pd.DataFrame, Segmentation]:
    """Node history (dates before ``origin``) and drivers with every user's ``segment`` replaced
    by ``segmenter(users, events, origin)``, which sees only data before ``origin``, plus that
    segmentation.

    ``NEW`` is a lifecycle state, not a fixed group: every user is ``NEW`` for their first
    ``segmenter.min_tenure_days`` (default ``MIN_TENURE_DAYS``) after activation and then joins
    their cluster; users the segmenter labels ``NEW`` (too little history, or activated after
    ``origin``) stay ``NEW``. So the ``NEW`` nodes carry every cohort's first weeks over the whole
    history instead of only the last few weeks. The drivers keep every column of
    ``dataset.drivers`` except the cohort counts, rebuilt from the same membership spells.
    Cached on the dataset by the segmenter's ``name`` and ``origin``."""
    start = pd.Timestamp(origin)
    key = ("segmented", segmenter.name, start)
    if key in dataset.cache:
        return dataset.cache[key]
    segmentation = segmenter(dataset.users, dataset.events, start)
    tenure = pd.Timedelta(days=getattr(segmenter, "min_tenure_days", MIN_TENURE_DAYS))
    users = dataset.users.assign(segment=segmentation.labels.reindex(dataset.users["user_id"]).to_numpy())
    joins = users["activation_date"].dt.normalize() + tenure  # when a clustered user leaves NEW
    ev = dataset.events
    by_user = users.set_index("user_id")
    label = by_user["segment"].reindex(ev["user_id"]).to_numpy()
    joined = (ev["at"].to_numpy() >= joins.set_axis(users["user_id"]).reindex(ev["user_id"]).to_numpy())
    events = pd.DataFrame({
        "settle_at": ev["settle_at"], "segment": np.where(joined, label, NEW),
        "product": ev["product"], "partner": ev["partner"], "amount": ev["amount"],
        "direction": ev["direction"], "confirmed": ev["confirmed"],
    })
    history = daily_node_table(events)
    history = history[history["date"] < start].reset_index(drop=True)
    kept = dataset.drivers[[c for c in dataset.drivers if not c.startswith(COHORT_PREFIXES)]]
    dates = pd.DatetimeIndex(kept["date"])
    clustered = users["segment"] != NEW
    entries = pd.concat([
        users[["activation_date"]].assign(segment=NEW),
        pd.DataFrame({"activation_date": joins[clustered], "segment": users.loc[clustered, "segment"]}),
    ])
    cohorts = cohort_drivers(entries, dates)
    exits = cohort_drivers(pd.DataFrame({"activation_date": joins[clustered], "segment": NEW}), dates)
    cohorts[f"n_active_{NEW}"] -= exits[f"n_active_{NEW}"]
    drivers = cohorts.merge(kept, on="date", how="left")
    dataset.cache[key] = (history, drivers, segmentation)
    return dataset.cache[key]


def forecast_key(
    model_factory: Callable[[], Forecaster], origins: Sequence[date], horizon: int, n_paths: int, seed: int,
    segmenter: Segmenter | None = None,
) -> tuple:
    """Cache key of ``walk_forward``: model name, origins, horizon, ``n_paths``, ``seed`` and the
    segmenter's ``name`` (None for the data's own segment labels)."""
    return (model_factory().name, tuple(origins), horizon, n_paths, seed, getattr(segmenter, "name", None))


def walk_forward(
    dataset: Dataset, model_factory: Callable[[], Forecaster], origins: Sequence[date],
    horizon: int = HORIZON, n_paths: int = 1000, seed: int = 0, segmenter: Segmenter | None = None,
) -> list[Forecast]:
    """Fit a fresh model on the data before each origin and forecast ``horizon`` days. Paths are
    the model's own ``last_paths`` when it has them, else ``paths_from_quantiles``. The model sees
    the drivers ``known_at`` the origin (exchange rates frozen at their last value before it).
    Cached on the dataset by ``forecast_key``.

    Without ``segmenter`` the nodes and cohort drivers use the data's ``segment`` column. With
    one, each origin relabels users from the data before it (``segmented_inputs``); cluster names
    may differ across origins, which is harmless because each origin refits the model."""
    key = forecast_key(model_factory, origins, horizon, n_paths, seed, segmenter)
    if key in dataset.cache:
        return dataset.cache[key]
    history, drivers = dataset.history, dataset.drivers
    out = []
    for k, origin in enumerate(origins):
        start = pd.Timestamp(origin)
        dates = pd.date_range(start, periods=horizon, freq="D")
        if segmenter is not None:
            history, drivers, _ = segmented_inputs(dataset, segmenter, origin)
        model = model_factory()
        model.fit(history[history["date"] < start], drivers[drivers["date"] < start])
        pred = model.predict(dates, known_at(drivers[drivers["date"] <= dates[-1]], start))
        if getattr(model, "last_paths", None) is not None:
            paths, partners = model.last_paths, list(model.partner_index)
        else:
            paths, partners, _ = paths_from_quantiles(pred, n_paths, seed + k)
        inflow = daily_partner_table(history[history["date"] < start]).pivot(index="date", columns="partner", values="inflow")
        inflow = np.column_stack([np.nan_to_num(seasonal_mean(inflow[p], dates)) for p in partners])
        quantiles = pred.assign(model=model.name, origin=start, horizon=(pred["date"] - start).dt.days + 1)
        out.append(Forecast(start, dates, partners, paths, inflow, quantiles))
    dataset.cache[key] = out
    return out


@dataclass
class BacktestResult:
    ledger_log: pd.DataFrame  # at, partner, balance, in_transit
    decisions: pd.DataFrame
    metrics: dict
    by_partner: pd.DataFrame
    initial: dict[str, float]


def partner_ledger(
    opening: float, flow_at: np.ndarray, flow_amounts: np.ndarray,
    instruct_at: np.ndarray, arrival_at: np.ndarray, amounts: np.ndarray,
) -> pd.DataFrame:
    """Realized ``at, balance, in_transit`` of one partner. Each deposit is in transit from its
    instruction (a zero-amount row) until it lands at ``arrival_at``, then available."""
    flow_at = np.concatenate([flow_at, instruct_at]).astype("datetime64[ns]")
    flow_amounts = np.concatenate([flow_amounts, np.zeros(len(instruct_at))])
    at, _, balance = balance_arrays(opening, flow_at, flow_amounts, np.asarray(arrival_at, "datetime64[ns]"), amounts)

    def total_by(times: np.ndarray) -> np.ndarray:  # summed amounts with a time <= each row's
        order = np.argsort(times)
        return np.concatenate([[0.0], np.cumsum(amounts[order])])[np.searchsorted(times[order], at, "right")]

    in_transit = total_by(np.asarray(instruct_at, "datetime64[ns]")) - total_by(np.asarray(arrival_at, "datetime64[ns]"))
    return pd.DataFrame({"at": at, "balance": balance, "in_transit": in_transit})


def time_weighted_mean(at: pd.Series, value: np.ndarray, initial: float, start: pd.Timestamp, stop: pd.Timestamp) -> float:
    """Mean over ``[start, stop)`` of a step function equal to ``initial`` before the first ``at``
    and to ``value[i]`` from ``at[i]`` on."""
    edges = np.concatenate([[start.value], np.clip(pd.DatetimeIndex(at).asi8, start.value, stop.value), [stop.value]])
    return float(np.dot(np.diff(edges), np.concatenate([[initial], value])) / (stop.value - start.value))


def _shortfalls(log: pd.DataFrame, initial: float, start: pd.Timestamp, n_days: int, warmup_days: int) -> dict:
    """Per partner-day window: any negative balance, and ``max(0, -min balance)`` in the window
    (the balance carried in at the window's start included), split into the first ``warmup_days``
    windows and the rest; plus the durations of negative episodes that begin after the warm-up."""
    at, balance = pd.DatetimeIndex(log["at"]), log["balance"].to_numpy()
    starts = start + pd.to_timedelta(np.arange(n_days), unit="D")
    before = np.searchsorted(at.asi8, starts.asi8, "left")
    carried = np.where(before > 0, balance[np.maximum(before - 1, 0)], initial)
    day = ((at - start) // pd.Timedelta(days=1)).to_numpy()
    inside = pd.Series(balance).groupby(day).min().reindex(range(n_days)).to_numpy()
    low = np.fmin(carried, inside)
    short, amount = low < 0, np.maximum(0.0, -low)
    negative = balance < 0
    begins = np.flatnonzero(negative & ~np.concatenate([[initial < 0], negative[:-1]]))
    ends = [np.flatnonzero(~negative[b:])[:1] for b in begins]
    stop = start + pd.Timedelta(days=n_days)
    evaluated = start + pd.Timedelta(days=warmup_days)
    durations = [
        ((at[b + e[0]] if len(e) else stop) - at[b]) / pd.Timedelta(hours=1)
        for b, e in zip(begins, ends) if at[b] >= evaluated
    ]
    return {
        "windows": int(short[warmup_days:].sum()), "amount": float(amount[warmup_days:].sum()),
        "warmup_windows": int(short[:warmup_days].sum()), "warmup_amount": float(amount[:warmup_days].sum()),
        "durations": durations,
    }


def _realized(dataset: Dataset, partner: Partner, start: pd.Timestamp, stop: pd.Timestamp) -> tuple[np.ndarray, np.ndarray]:
    """Settlement times and signed amounts (outflow +, inflow - if the partner nets them) in ``[start, stop)``."""
    ev = dataset.events
    rows = (ev["partner"] == partner.id) & (ev["settle_at"] >= start) & (ev["settle_at"] < stop)
    if not partner.nets_inflows:
        rows &= ev["direction"] == 1
    ev = ev.loc[rows].sort_values("settle_at", kind="stable")
    return ev["settle_at"].to_numpy("datetime64[ns]"), (ev["amount"] * ev["direction"]).to_numpy(float)


def _sum_before(times: np.ndarray, cumulative: np.ndarray, t: pd.Timestamp) -> float:
    """``cumulative`` up to the last of ``times`` strictly before ``t`` (0 if none)."""
    i = np.searchsorted(times, t.to_datetime64(), "left")
    return float(cumulative[i - 1]) if i else 0.0


def default_warmup_days(start: pd.Timestamp, rails: dict[str, Rail], cal: Calendar, cfg: PolicyConfig) -> int:
    """Calendar days from ``start`` until the first order on the slowest rail can land (the day it
    lands included): until then a balance depends only on its opening, whatever the policy."""
    first = [arrival_time(r, review_times(r, start, start + pd.Timedelta(days=14), cal, cfg)[0], cal) for r in rails.values()]
    return int(np.ceil((max(first) - start) / pd.Timedelta(days=1)))


def _rail_for(partner: Partner, rails: dict[str, Rail], preferred: str) -> Rail:
    if preferred in partner.accepts_rails:
        return rails[preferred]
    if len(partner.accepts_rails) != 1:
        raise ValueError(f"{partner.id} does not accept {preferred!r} and has no single fallback")
    return rails[partner.accepts_rails[0]]


def run(
    dataset: Dataset,
    model_factory: Callable[[], Forecaster] | None,
    policy: Literal["fixed", "forecast"],
    rail_name: str,
    policy_cfg: PolicyConfig,
    origins: Sequence[date],
    central_reserve: float = 0.0,
    n_paths: int = 1000,
    seed: int = 0,
    horizon: int = HORIZON,
    warmup_days: int | None = None,
    segmenter: Segmenter | None = None,
) -> BacktestResult:
    """Backtest ``policy`` from the first origin to one step after the last.

    Configs (calendars, partners, rails) come from ``dataset.configs``. A business-day rail moves
    money only on days that are business days at home and in the partner's country
    (``ConfigSet.rail_calendar``). Amounts are in each partner's currency.

    Each partner uses ``rail_name`` if it accepts it, else its only rail. It starts at the fixed
    buffer's target at the first origin. At each review the available balance is the realized one
    (deposits landed, flows settled before the review); ``fixed`` tops the balance plus deposits in
    transit up to ``fixed_buffer_days`` of the trailing 28-day mean drain, ``forecast`` calls
    ``recommend_deposit`` on the latest origin's paths.

    Metrics cover the partner-days from ``start + warmup_days`` (default ``default_warmup_days``,
    the same for every policy and rail) to the end; the warm-up's shortfalls are reported apart as
    ``warmup_shortfall_windows`` and ``warmup_shortfall_amount``. Capital, transfers, fees and
    ``p_unresolvable_mean`` also count only the evaluated period. ``p_unresolvable_mean`` also
    leaves out the structural no-op reviews (``structural_noop``). ``segmenter`` goes to
    ``walk_forward``; the realized flows never depend on it.
    """
    configs = dataset.configs
    cal, partners, rails = configs.joint_calendar(), configs.partners(), configs.rails()
    step = pd.Timedelta(days=(origins[1] - origins[0]).days if len(origins) > 1 else 7)
    start, stop = pd.Timestamp(origins[0]), pd.Timestamp(origins[-1]) + step
    n_days = (stop - start).days
    warmup_days = default_warmup_days(start, rails, cal, policy_cfg) if warmup_days is None else warmup_days
    if not 0 <= warmup_days < n_days:
        raise ValueError(f"warmup_days={warmup_days} must be in [0, {n_days})")
    evaluated = start + pd.Timedelta(days=warmup_days)
    forecasts = walk_forward(dataset, model_factory, origins, horizon, n_paths, seed, segmenter) if policy == "forecast" else []
    daily = daily_partner_table(dataset.history)
    daily["drain"] = daily["outflow"] - daily["inflow"] * daily["partner"].map({p: q.nets_inflows for p, q in partners.items()})
    drain = daily.pivot(index="date", columns="partner", values="drain")

    def trailing(pid: str, day: pd.Timestamp) -> float:
        return float(drain.loc[day - pd.Timedelta(days=TRAILING_DAYS) : day - pd.Timedelta(days=1), pid].mean())

    logs, rows, by_partner, initial = [], [], [], {}
    for pid, partner in partners.items():
        rail, rail_cal = _rail_for(partner, rails, rail_name), configs.rail_calendar(partner)
        flow_at, signed = _realized(dataset, partner, start, stop)
        drained, out_cum = np.cumsum(signed), np.cumsum(np.maximum(signed, 0.0))
        initial[pid] = policy_cfg.fixed_buffer_days * trailing(pid, start)
        sent: list[tuple[pd.Timestamp, pd.Timestamp, float]] = []
        for t in review_times(rail, start, stop, rail_cal, policy_cfg):
            available = initial[pid] + sum(a for _, arr, a in sent if arr <= t) - _sum_before(flow_at, drained, t)
            pending = [Credit(arr, a) for _, arr, a in sent if arr > t]
            if policy == "fixed":
                position = available + sum(c.amount for c in pending)
                decision = fixed_buffer_decision(trailing(pid, t.normalize()), policy_cfg.fixed_buffer_days, position,
                                                 policy_cfg.lot_size)
            else:
                fc = next(f for f in reversed(forecasts) if f.origin <= t)
                j = fc.partners.index(pid)
                today = _sum_before(flow_at, out_cum, t) - _sum_before(flow_at, out_cum, t.normalize())
                decision = recommend_deposit(
                    fc.paths[:, :, j], fc.dates, partner, rail, available, pending, t, rail_cal, policy_cfg,
                    realized_today=today, inflow_forecast=fc.inflow[:, j],
                )
                if decision.window_end.normalize() > fc.dates[-1]:
                    raise ValueError(f"forecast from {fc.origin.date()} ends before the window of the review at {t}")
            arrival = arrival_time(rail, t, rail_cal)
            if decision.amount > 0:
                sent.append((t, arrival, decision.amount))
            rows.append({"at": t, "partner": pid, "rail_used": rail.name, "available": available,
                         "pending": sum(c.amount for c in pending), **vars(decision), "arrival_at": arrival})
        instruct, arrive, amount = (np.array([s[k] for s in sent], dtype=d) for k, d in
                                    ((0, "datetime64[ns]"), (1, "datetime64[ns]"), (2, float)))
        log = partner_ledger(initial[pid], flow_at, signed, instruct, arrive, amount)
        log = log[log["at"] < stop.to_datetime64()].assign(partner=pid)
        short = _shortfalls(log, initial[pid], start, n_days, warmup_days)
        capital = np.maximum(log["balance"].to_numpy(), 0.0) + log["in_transit"].to_numpy()
        counted = [a for t, _, a in sent if t >= evaluated]
        by_partner.append({
            "partner": pid, "rail_used": rail.name, "initial": initial[pid],
            "capital_mean": time_weighted_mean(log["at"], capital, initial[pid], evaluated, stop),
            "shortfall_windows": short["windows"], "shortfall_amount": short["amount"],
            "warmup_shortfall_windows": short["warmup_windows"], "warmup_shortfall_amount": short["warmup_amount"],
            "durations": short["durations"], "n_transfers": len(counted),
            "fees": float(sum(rail.fixed_fee + rail.bps / 1e4 * a for a in counted)),
        })
        logs.append(log)
    partner_table = pd.DataFrame(by_partner)
    decisions = pd.DataFrame(rows)
    return BacktestResult(
        ledger_log=pd.concat(logs, ignore_index=True)[["at", "partner", "balance", "in_transit"]],
        decisions=decisions,
        metrics=_metrics(partner_table, decisions[decisions["at"] >= evaluated], policy_cfg, central_reserve,
                         n_days - warmup_days, warmup_days),
        by_partner=partner_table.drop(columns="durations"),
        initial=initial,
    )


def structural_noop(decisions: pd.DataFrame) -> pd.Series:
    """Reviews that deposit nothing because their window holds no flow a deposit could cover:
    ``amount == 0`` and ``window_end`` before the next day's 00:00, where the next day's outflow is
    placed. That is the morning review of a 24/7 rail (its window closes when the evening order
    lands); the day's own outflow sits at the review, before any deposit lands."""
    window_end = pd.to_datetime(decisions["window_end"])
    next_day = pd.to_datetime(decisions["at"]).dt.normalize() + pd.Timedelta(days=1)
    return (decisions["amount"] == 0) & (window_end < next_day)


def _metrics(
    table: pd.DataFrame, decisions: pd.DataFrame, cfg: PolicyConfig, central_reserve: float, n_days: int, warmup_days: int,
) -> dict:
    """``p_unresolvable_mean`` is the mean over the evaluated forecast reviews except the
    ``structural_noop`` ones (NaN for the fixed buffer, which has no ``p_unresolvable``)."""
    durations = [d for ds in table["durations"] for d in ds]
    p_unres = decisions.loc[~structural_noop(decisions), "p_unresolvable"].dropna()
    capital = float(table["capital_mean"].sum()) + central_reserve
    fees, short_amount = float(table["fees"].sum()), float(table["shortfall_amount"].sum())
    return {
        "capital_total_mean": capital,
        "shortfall_windows": int(table["shortfall_windows"].sum()),
        "shortfall_rate": float(table["shortfall_windows"].sum() / (len(table) * n_days)),
        "shortfall_amount_total": short_amount,
        "shortfall_duration_hours_mean": float(np.mean(durations)) if durations else 0.0,
        "n_transfers": int(table["n_transfers"].sum()),
        "fees": fees,
        "cost_total": cfg.cost_of_capital_annual * capital * n_days / 365 + fees + cfg.cost_per_usd_rejected * short_amount,
        "p_unresolvable_mean": float(p_unres.mean()) if len(p_unres) else float("nan"),
        "n_days": n_days,
        "warmup_days": warmup_days,
        "warmup_shortfall_windows": int(table["warmup_shortfall_windows"].sum()),
        "warmup_shortfall_amount": float(table["warmup_shortfall_amount"].sum()),
        "rail_used": dict(zip(table["partner"], table["rail_used"])),
    }
