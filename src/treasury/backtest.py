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
from treasury.features import build_drivers
from treasury.ledger import Credit, balance_arrays
from treasury.models.base import Forecaster, daily_node_table, daily_partner_table
from treasury.models.seasonal_naive import seasonal_mean
from treasury.montecarlo import paths_from_quantiles
from treasury.policy import PolicyConfig, fixed_buffer_decision, recommend_deposit, review_times
from treasury.rails import Rail, arrival_time, load_rails
from treasury.routing import Partner, load_partners

CONFIG = Path(__file__).resolve().parents[2] / "config"
HORIZON = 14
TRAILING_DAYS = 28  # window of the fixed buffer's trailing mean drain


@dataclass(eq=False)
class Dataset:
    """A routed simulation: ``users``, ``events`` and its ``params``, plus the node table
    ``history`` (dates up to ``params["end"]``) and the ``drivers`` over those dates."""

    users: pd.DataFrame
    events: pd.DataFrame
    params: dict
    history: pd.DataFrame
    drivers: pd.DataFrame
    macro: pd.DataFrame | None = None
    cache: dict = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def load(cls, folder: str | Path) -> Dataset:
        folder = Path(folder)
        return cls.from_frames(
            pd.read_parquet(folder / "users.parquet"),
            pd.read_parquet(folder / "events.parquet"),
            params=json.loads((folder / "params.json").read_text()),
            macro=pd.read_parquet(folder / "macro.parquet"),
        )

    @classmethod
    def from_frames(
        cls, users: pd.DataFrame, events: pd.DataFrame, params: dict, macro: pd.DataFrame | None = None,
        scenarios: Sequence = (),
    ) -> Dataset:
        history = daily_node_table(events)
        history = history[history["date"] <= pd.Timestamp(params["end"])].reset_index(drop=True)
        dates = pd.date_range(history["date"].min(), history["date"].max(), freq="D")
        return cls(users, events, params, history, build_drivers(users, events, dates, scenarios), macro)

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


def walk_forward(
    dataset: Dataset, model_factory: Callable[[], Forecaster], origins: Sequence[date],
    horizon: int = HORIZON, n_paths: int = 1000, seed: int = 0,
) -> list[Forecast]:
    """Fit a fresh model on the data before each origin and forecast ``horizon`` days. Paths are
    the model's own ``last_paths`` when it has them, else ``paths_from_quantiles``. Cached on
    the dataset by model name, origins, horizon, ``n_paths`` and ``seed``."""
    key = (model_factory().name, tuple(origins), horizon, n_paths, seed)
    if key in dataset.cache:
        return dataset.cache[key]
    history, drivers = dataset.history, dataset.drivers
    out = []
    for k, origin in enumerate(origins):
        start = pd.Timestamp(origin)
        dates = pd.date_range(start, periods=horizon, freq="D")
        model = model_factory()
        model.fit(history[history["date"] < start], drivers[drivers["date"] < start])
        pred = model.predict(dates, drivers[drivers["date"] <= dates[-1]])
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


def _shortfalls(log: pd.DataFrame, initial: float, start: pd.Timestamp, n_days: int) -> dict:
    """Per partner-day window: any negative balance, and ``max(0, -min balance)`` in the window
    (the balance carried in at the window's start included); plus negative-episode durations."""
    at, balance = pd.DatetimeIndex(log["at"]), log["balance"].to_numpy()
    starts = start + pd.to_timedelta(np.arange(n_days), unit="D")
    before = np.searchsorted(at.asi8, starts.asi8, "left")
    carried = np.where(before > 0, balance[np.maximum(before - 1, 0)], initial)
    day = ((at - start) // pd.Timedelta(days=1)).to_numpy()
    inside = pd.Series(balance).groupby(day).min().reindex(range(n_days)).to_numpy()
    low = np.fmin(carried, inside)
    negative = balance < 0
    begins = np.flatnonzero(negative & ~np.concatenate([[initial < 0], negative[:-1]]))
    ends = [np.flatnonzero(~negative[b:])[:1] for b in begins]
    stop = start + pd.Timedelta(days=n_days)
    durations = [((at[b + e[0]] if len(e) else stop) - at[b]) / pd.Timedelta(hours=1) for b, e in zip(begins, ends)]
    return {"windows": int((low < 0).sum()), "amount": float(np.maximum(0.0, -low).sum()), "durations": durations}


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
) -> BacktestResult:
    """Backtest ``policy`` from the first origin to one step after the last.

    Each partner uses ``rail_name`` if it accepts it, else its only rail. It starts at the fixed
    buffer's target at the first origin. At each review the available balance is the realized one
    (deposits landed, flows settled before the review); ``fixed`` tops the balance plus deposits in
    transit up to ``fixed_buffer_days`` of the trailing 28-day mean drain, ``forecast`` calls
    ``recommend_deposit`` on the latest origin's paths. Metrics are over partner-day windows.
    """
    cal = Calendar.from_yaml(CONFIG / "calendar_ar.yaml")
    partners, rails = load_partners(CONFIG / "partners.yaml"), load_rails(CONFIG / "rails.yaml")
    step = pd.Timedelta(days=(origins[1] - origins[0]).days if len(origins) > 1 else 7)
    start, stop = pd.Timestamp(origins[0]), pd.Timestamp(origins[-1]) + step
    n_days = (stop - start).days
    forecasts = walk_forward(dataset, model_factory, origins, horizon, n_paths, seed) if policy == "forecast" else []
    daily = daily_partner_table(dataset.history)
    daily["drain"] = daily["outflow"] - daily["inflow"] * daily["partner"].map({p: q.nets_inflows for p, q in partners.items()})
    drain = daily.pivot(index="date", columns="partner", values="drain")

    def trailing(pid: str, day: pd.Timestamp) -> float:
        return float(drain.loc[day - pd.Timedelta(days=TRAILING_DAYS) : day - pd.Timedelta(days=1), pid].mean())

    logs, rows, by_partner, initial = [], [], [], {}
    for pid, partner in partners.items():
        rail = _rail_for(partner, rails, rail_name)
        flow_at, signed = _realized(dataset, partner, start, stop)
        drained, out_cum = np.cumsum(signed), np.cumsum(np.maximum(signed, 0.0))
        initial[pid] = policy_cfg.fixed_buffer_days * trailing(pid, start)
        sent: list[tuple[pd.Timestamp, pd.Timestamp, float]] = []
        for t in review_times(rail, start, stop, cal, policy_cfg):
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
                    fc.paths[:, :, j], fc.dates, partner, rail, available, pending, t, cal, policy_cfg,
                    realized_today=today, inflow_forecast=fc.inflow[:, j],
                )
                if decision.window_end.normalize() > fc.dates[-1]:
                    raise ValueError(f"forecast from {fc.origin.date()} ends before the window of the review at {t}")
            arrival = arrival_time(rail, t, cal)
            if decision.amount > 0:
                sent.append((t, arrival, decision.amount))
            rows.append({"at": t, "partner": pid, "rail_used": rail.name, "available": available,
                         "pending": sum(c.amount for c in pending), **vars(decision), "arrival_at": arrival})
        instruct, arrive, amount = (np.array([s[k] for s in sent], dtype=d) for k, d in
                                    ((0, "datetime64[ns]"), (1, "datetime64[ns]"), (2, float)))
        log = partner_ledger(initial[pid], flow_at, signed, instruct, arrive, amount)
        log = log[log["at"] < stop.to_datetime64()].assign(partner=pid)
        short = _shortfalls(log, initial[pid], start, n_days)
        capital = np.maximum(log["balance"].to_numpy(), 0.0) + log["in_transit"].to_numpy()
        by_partner.append({
            "partner": pid, "rail_used": rail.name, "initial": initial[pid],
            "capital_mean": time_weighted_mean(log["at"], capital, initial[pid], start, stop),
            "shortfall_windows": short["windows"], "shortfall_amount": short["amount"],
            "durations": short["durations"], "n_transfers": len(sent),
            "fees": float(sum(rail.fixed_fee + rail.bps / 1e4 * a for _, _, a in sent)),
        })
        logs.append(log)
    partner_table = pd.DataFrame(by_partner)
    decisions = pd.DataFrame(rows)
    return BacktestResult(
        ledger_log=pd.concat(logs, ignore_index=True)[["at", "partner", "balance", "in_transit"]],
        decisions=decisions,
        metrics=_metrics(partner_table, decisions, policy_cfg, central_reserve, n_days),
        by_partner=partner_table.drop(columns="durations"),
        initial=initial,
    )


def _metrics(table: pd.DataFrame, decisions: pd.DataFrame, cfg: PolicyConfig, central_reserve: float, n_days: int) -> dict:
    durations = [d for ds in table["durations"] for d in ds]
    p_unres = decisions["p_unresolvable"].dropna()
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
        "rail_used": dict(zip(table["partner"], table["rail_used"])),
    }
