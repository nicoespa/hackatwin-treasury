"""Exchange rates of the international variant: simulated daily paths, the demand scenarios they and
the tourism season drive, and conversion of partner-currency amounts to USD.

Rates are quoted per USD (``ars_per_usd``, ``brl_per_usd``); ``ars_per_brl`` is their ratio.
``config/intl/market.yaml`` holds every parameter.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from treasury.simulate.scenarios import _Neutral

FX_STREAM = 0xF0  # second entropy word: FX draws never share a stream with the event simulator
DAYS_PER_MONTH = 30.4375
PAIRS = ("ars_per_usd", "brl_per_usd", "ars_per_brl")


def simulate_fx(cfg: Mapping, dates: pd.DatetimeIndex, seed: int) -> pd.DataFrame:
    """``date, ars_per_usd, brl_per_usd`` for every date, deterministic in ``seed``.

    Each rate is a log random walk from ``start`` with drift ``crawl_monthly`` (per 30.44 days) and
    daily noise ``vol_daily``; the peso also jumps (devalues) on a day with probability
    ``jump_prob_daily`` by ``N(jump_mean, jump_sd)`` in log terms, floored at 0.
    """
    rng = np.random.default_rng([seed, FX_STREAM])
    n = len(dates)
    out = {"date": pd.DatetimeIndex(dates)}
    for pair in ("ars_per_usd", "brl_per_usd"):
        p = cfg[pair]
        steps = np.log1p(p["crawl_monthly"]) / DAYS_PER_MONTH + p["vol_daily"] * rng.standard_normal(n)
        if p.get("jump_prob_daily", 0.0):
            jumps = rng.random(n) < p["jump_prob_daily"]
            steps += jumps * np.maximum(0.0, rng.normal(p["jump_mean"], p["jump_sd"], n))
        steps[0] = 0.0
        out[pair] = p["start"] * np.exp(np.cumsum(steps))
    return pd.DataFrame(out)


def with_cross(fx: pd.DataFrame) -> pd.DataFrame:
    return fx.assign(ars_per_brl=fx["ars_per_usd"] / fx["brl_per_usd"])


def change_vs_trailing(series: pd.Series, days: int) -> pd.Series:
    """``log(x_t / mean(x_{t-days} .. x_{t-1}))``: how much dearer the currency got than its recent
    level (0 on the first day). Known on day ``t`` once ``x_t`` is."""
    trailing = series.shift(1).rolling(days, min_periods=1).mean()
    return np.log(series / trailing).fillna(0.0)


def tourism_index(cfg: Mapping, dates: pd.DatetimeIndex) -> np.ndarray:
    """Tourism-season multiplier of each date: the largest ``lift`` among the windows holding it
    (``base`` outside every window). A calendar of school holidays, known ahead."""
    dates = pd.DatetimeIndex(dates)
    index = np.full(len(dates), float(cfg.get("base", 1.0)))
    for w in cfg["windows"]:
        inside = (dates >= pd.Timestamp(w["start"])) & (dates <= pd.Timestamp(w["end"]))
        index = np.where(inside, np.maximum(index, w["lift"]), index)
    return index


@dataclass(frozen=True)
class DailyLift(_Neutral):
    """Multiply ``products`` for every segment by ``lift[day]`` (1 on days it lacks)."""

    products: tuple[str, ...]
    lift: Mapping[date, float] = field(repr=False)

    def multiplier(self, day: date, segment: str, product: str) -> float:
        return self.lift.get(day, 1.0) if product in self.products else 1.0


def demand_scenarios(market: Mapping, fx: pd.DataFrame) -> list[DailyLift]:
    """The FX and tourism demand of ``market.yaml`` as scenarios for the simulator.

    For each ``demand`` entry, its products scale by ``exp(-elasticity * change)`` with ``change``
    the ``change_vs_trailing`` of its pair over ``window_days``: spending abroad falls when the
    peso has just weakened against that currency. ``tourism`` scales its products by
    ``tourism_index``.
    """
    fx = with_cross(fx)
    days = [d.date() for d in fx["date"]]
    out = []
    for spec in market.get("demand", []):
        change = change_vs_trailing(fx[spec["pair"]], spec["window_days"]).to_numpy()
        out.append(DailyLift(tuple(spec["products"]), dict(zip(days, np.exp(-spec["elasticity"] * change)))))
    if tourism := market.get("tourism"):
        out.append(DailyLift(tuple(tourism["products"]), dict(zip(days, tourism_index(tourism, fx["date"])))))
    return out


def fx_drivers(fx: pd.DataFrame, market: Mapping, dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Drivers keyed by ``date``: ``fx_<pair>`` levels, ``fx_<pair>_chg<window>`` of every
    ``demand`` entry, and ``tourism_index`` when ``market`` has a tourism season. ``fx_*`` values
    are realized: ``features.known_at`` freezes them at the forecast origin."""
    fx = with_cross(fx).set_index("date").reindex(pd.DatetimeIndex(dates)).ffill()
    out = pd.DataFrame({"date": pd.DatetimeIndex(dates)})
    for pair in ("ars_per_usd", "brl_per_usd"):
        out[f"fx_{pair}"] = fx[pair].to_numpy()
    for spec in market.get("demand", []):
        name = f"fx_{spec['pair']}_chg{spec['window_days']}"
        out[name] = change_vs_trailing(fx[spec["pair"]], spec["window_days"]).to_numpy()
    if tourism := market.get("tourism"):
        out["tourism_index"] = tourism_index(tourism, dates)
    return out


def usd_per_unit(fx: pd.DataFrame | None, currency: str, at) -> np.ndarray:
    """USD value of one unit of ``currency`` on the date of each of ``at`` (the latest rate on or
    before it). USD is 1; a missing ``fx`` only works for USD."""
    at = pd.DatetimeIndex(np.atleast_1d(pd.to_datetime(at))).normalize()
    if currency == "USD":
        return np.ones(len(at))
    if fx is None:
        raise ValueError(f"converting {currency} to USD needs exchange rates")
    column = {"ARS": "ars_per_usd", "BRL": "brl_per_usd"}[currency]
    rates = fx.set_index("date")[column].sort_index()
    pos = np.clip(rates.index.searchsorted(at, "right") - 1, 0, len(rates) - 1)
    return 1.0 / rates.to_numpy()[pos]
