"""Daily event generator: per-user Poisson intensities scaled by a shared macro factor."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

import numpy as np
import pandas as pd
from scipy.signal import lfilter

from treasury.calendar import Calendar
from treasury.simulate.population import (
    ANSES,
    SALARIED,
    apply_cohort_waves,
    apply_payday_shift,
    check_payday_hypothesis,
)
from treasury.simulate.scenarios import Scenario

DAYS_PER_MONTH = 30.4375
EARLY_MONTH_PRODUCT, EARLY_MONTH_LAST_DAY, EARLY_MONTH_MULT = "bill_payment", 10, 1.4
PAYDAY_PRODUCTS = ("bill_payment", "fci_subscription")
PAYDAY_MULT, DAY_AFTER_PAYDAY_MULT = 3.0, 1.8  # on payday and on the next business day
ANSES_PRODUCTS, ANSES_MULT = ("cash_out", "bill_payment"), 2.5
SAC_PRODUCTS, SAC_MULT = ("fci_subscription", "card_purchase"), 1.3
BILL_PAY_PROBABILITY = 0.9
BILL_PAY_OFFSETS = (-2, 3)  # manual bills are paid on a day in [due - 2, due + 3]


@dataclass(frozen=True)
class SimParams:
    sigma_m: float = 0.15
    phi: float = 0.7
    payday_hypothesis: Literal["late", "uniform", "bimodal"] = "late"
    inflation_monthly: float = 0.02

    def __post_init__(self) -> None:
        check_payday_hypothesis(self.payday_hypothesis)


def macro_factor(n_days: int, params: SimParams, rng: np.random.Generator) -> np.ndarray:
    """Shared lognormal AR(1) factor with stationary ``sd(log m_t) = sigma_m``."""
    shocks = rng.normal(0.0, params.sigma_m * np.sqrt(1 - params.phi**2), n_days)
    shocks[0] = rng.normal(0.0, params.sigma_m)
    return np.exp(lfilter([1.0], [1.0, -params.phi], shocks))


def _cols(products: list[str], names: Sequence[str]) -> list[int]:
    return [products.index(p) for p in names if p in products]


def _scenario_matrix(day: date, scenarios: Sequence[Scenario], segments: list[str], products: list[str]) -> np.ndarray:
    return np.array(
        [[np.prod([s.multiplier(day, seg, prod) for s in scenarios]) for prod in products] for seg in segments]
    )


def _recurring_bills(
    users: pd.DataFrame,
    seg_code: np.ndarray,
    act_idx: np.ndarray,
    log_median: np.ndarray,
    sigma: np.ndarray,
    bill_col: int,
    start: date,
    n_days: int,
    rng: np.random.Generator,
) -> tuple[np.ndarray, ...]:
    """``(user_pos, day_idx, amount, confirmed, counterparty)`` for every recurring bill payment.

    Each bill keeps one due day (1..10) and one amount. Autodebit bills are paid on the
    due day; manual ones, with probability 0.9, on a day in ``[due - 2, due + 3]``.
    """
    n_bills = users["n_bills"].to_numpy()
    owner = np.repeat(np.arange(len(users)), n_bills)
    nth = np.arange(len(owner)) - np.repeat(np.cumsum(n_bills) - n_bills, n_bills)
    due = rng.integers(1, 11, size=len(owner))
    seg = seg_code[owner]
    amount = np.round(np.exp(log_median[seg, bill_col] + sigma[seg, bill_col] * rng.standard_normal(len(owner))), 2)
    autodebit = users["has_autodebit"].to_numpy()[owner]
    counterparty = users["user_id"].to_numpy()[owner].astype(str).astype(object) + "-b" + nth.astype(str).astype(object)

    first = pd.Timestamp(start).to_period("M")
    months = pd.period_range(first, first + n_days // 28 + 1, freq="M")
    picks = []
    for month in months:
        offset = np.where(autodebit, 0, rng.integers(BILL_PAY_OFFSETS[0], BILL_PAY_OFFSETS[1] + 1, size=len(owner)))
        pays = autodebit | (rng.random(len(owner)) < BILL_PAY_PROBABILITY)
        day_idx = (month.start_time - pd.Timestamp(start)).days + due - 1 + offset
        keep = pays & (day_idx >= 0) & (day_idx < n_days) & (act_idx[owner] <= day_idx)
        picks.append((np.flatnonzero(keep), day_idx[keep]))
    rows = np.concatenate([r for r, _ in picks])
    return owner[rows], np.concatenate([d for _, d in picks]), amount[rows], autodebit[rows], counterparty[rows]


def simulate_events(
    users: pd.DataFrame,
    archetypes: dict,
    cal: Calendar,
    start: date,
    end: date,
    params: SimParams,
    scenarios: Sequence[Scenario],
    seed: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Events ``at, user_id, segment, product, amount, confirmed, counterparty`` and the ``date, m_t`` macro factor."""
    users = apply_cohort_waves(users, scenarios, archetypes, seed, params.payday_hypothesis)
    users = apply_payday_shift(users, scenarios)
    macro_rng, adopt_rng, day_rng, bill_rng, detail_rng = map(
        np.random.default_rng, np.random.SeedSequence(seed).spawn(5)
    )

    specs = archetypes["archetypes"]
    segments = list(specs)
    products = [p for p in archetypes["hour_profiles"] if any(p in s["products"] for s in specs.values())]
    shape = (len(segments), len(products))
    rate, adoption, log_median, sigma = np.zeros(shape), np.zeros(shape), np.zeros(shape), np.zeros(shape)
    for i, seg in enumerate(segments):
        for j, prod in enumerate(products):
            if spec := specs[seg]["products"].get(prod):
                rate[i, j], adoption[i, j] = spec["base_rate_per_day"], spec["adoption"]
                log_median[i, j], sigma[i, j] = np.log(spec["amount_median"]), spec["amount_sigma"]
    dow_mult = np.array([archetypes["dow_mult"][p] for p in products])  # (P, 7)

    dates = pd.date_range(pd.Timestamp(start), pd.Timestamp(end), freq="D")
    n_days = len(dates)
    m_t = macro_factor(n_days, params, macro_rng)

    seg_code = users["segment"].map({s: i for i, s in enumerate(segments)}).to_numpy()
    act_idx = ((users["activation_date"] - pd.Timestamp(start)).dt.days).to_numpy()
    payday = users["payday_bd"].to_numpy()
    anses_day = users["anses_day"].to_numpy()
    salaried = np.flatnonzero(users["segment"].to_numpy() == SALARIED)
    anses = np.flatnonzero(users["segment"].to_numpy() == ANSES)
    user_rate = rate[seg_code] * (adopt_rng.random((len(users), len(products))) < adoption[seg_code])
    payday_cols, anses_cols, sac_cols = (_cols(products, p) for p in (PAYDAY_PRODUCTS, ANSES_PRODUCTS, SAC_PRODUCTS))
    early_col = _cols(products, [EARLY_MONTH_PRODUCT])

    ev_user, ev_prod, ev_day = [], [], []
    for i, ts in enumerate(dates):
        day = ts.date()
        day_mult = dow_mult[:, day.weekday()].copy()
        if day.day <= EARLY_MONTH_LAST_DAY:
            day_mult[early_col] *= EARLY_MONTH_MULT
        lam = user_rate * (day_mult * m_t[i])
        if scenarios:
            lam *= _scenario_matrix(day, scenarios, segments, products)[seg_code]
        if nbd := cal.nth_business_day_of_month(day):
            mult = np.where(
                payday[salaried] == nbd, PAYDAY_MULT, np.where(payday[salaried] + 1 == nbd, DAY_AFTER_PAYDAY_MULT, 1.0)
            )
            lam[np.ix_(salaried, payday_cols)] *= mult[:, None]
            mult = np.where(anses_day[anses] == nbd, ANSES_MULT, 1.0)
            lam[np.ix_(anses, anses_cols)] *= mult[:, None]
        if cal.is_sac_window(day):
            lam[np.ix_(salaried, sac_cols)] *= SAC_MULT
        lam[act_idx > i] = 0.0
        counts = day_rng.poisson(lam)
        u, p = np.nonzero(counts)
        c = counts[u, p]
        ev_user.append(np.repeat(u, c))
        ev_prod.append(np.repeat(p, c))
        ev_day.append(np.full(c.sum(), i))

    user_pos, prod, day_idx = (np.concatenate(a) for a in (ev_user, ev_prod, ev_day))
    seg = seg_code[user_pos]
    drift = np.log1p(params.inflation_monthly) * day_idx / DAYS_PER_MONTH
    z = detail_rng.standard_normal(len(user_pos))
    amount = np.round(np.exp(log_median[seg, prod] + drift + sigma[seg, prod] * z), 2)
    confirmed = np.zeros(len(user_pos), dtype=bool)
    counterparty = np.full(len(user_pos), "", dtype=object)

    bill_col = products.index("bill_payment")
    b_user, b_day, b_amount, b_confirmed, b_counterparty = _recurring_bills(
        users, seg_code, act_idx, log_median, sigma, bill_col, start, n_days, bill_rng
    )
    user_pos = np.concatenate([user_pos, b_user])
    prod = np.concatenate([prod, np.full(len(b_user), bill_col)])
    day_idx = np.concatenate([day_idx, b_day])
    amount = np.concatenate([amount, b_amount])
    confirmed = np.concatenate([confirmed, b_confirmed])
    counterparty = np.concatenate([counterparty, b_counterparty])

    hour = np.empty(len(prod), dtype=np.int64)
    for j, name in enumerate(products):
        rows = prod == j
        weights = np.asarray(archetypes["hour_profiles"][name], dtype=float)
        hour[rows] = detail_rng.choice(24, size=rows.sum(), p=weights / weights.sum())
    minutes = day_idx * 1440 + hour * 60 + detail_rng.integers(0, 60, size=len(prod))
    at = np.datetime64(pd.Timestamp(start), "ns") + minutes.astype("timedelta64[m]")

    order = np.argsort(at, kind="stable")
    events = pd.DataFrame(
        {
            "at": at[order],
            "user_id": users["user_id"].to_numpy()[user_pos[order]],
            "segment": np.array(segments, dtype=object)[seg_code[user_pos[order]]],
            "product": np.array(products, dtype=object)[prod[order]],
            "amount": amount[order],
            "confirmed": confirmed[order],
            "counterparty": counterparty[order],
        }
    )
    macro = pd.DataFrame({"date": dates, "m_t": m_t})
    return events, macro
