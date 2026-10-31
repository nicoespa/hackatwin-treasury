"""Synthetic users: segments, activation cohorts, paydays and recurring bills."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import yaml

from treasury.simulate.scenarios import CohortWave, PaydayShift, Scenario

if TYPE_CHECKING:
    from treasury.simulate.events import SimParams

# Probability that a salaried user is paid on business day 1, 2, 3 or 4 of the month.
PAYDAY_HYPOTHESES: dict[str, tuple[float, ...]] = {
    "late": (0.10, 0.20, 0.30, 0.40),
    "uniform": (0.25, 0.25, 0.25, 0.25),
    "bimodal": (0.45, 0.05, 0.05, 0.45),
}
SALARIED = "salaried_formal"
ANSES = "anses_beneficiary"
ANSES_FIRST_DAY, ANSES_LAST_DAY = 9, 25  # calendar days of month over which ANSES pays
INITIAL_SHARE = 0.6
MAX_BILLS = 6


def load_archetypes(path: str | Path) -> dict:
    """Read ``archetypes.yaml`` and check shares and per-product profiles."""
    cfg = yaml.safe_load(Path(path).read_text())
    specs = cfg["archetypes"]
    total = sum(spec["share"] for spec in specs.values())
    if not np.isclose(total, 1.0):
        raise ValueError(f"archetype shares sum to {total}, not 1")
    for name, spec in specs.items():
        for product in spec["products"]:
            if len(cfg["hour_profiles"].get(product, ())) != 24:
                raise ValueError(f"{name}: product {product!r} needs a 24-hour profile")
            if len(cfg["dow_mult"].get(product, ())) != 7:
                raise ValueError(f"{name}: product {product!r} needs 7 day-of-week multipliers")
    return cfg


def check_payday_hypothesis(name: str) -> tuple[float, ...]:
    if name not in PAYDAY_HYPOTHESES:
        raise ValueError(f"unknown payday hypothesis {name!r}; expected one of {sorted(PAYDAY_HYPOTHESES)}")
    return PAYDAY_HYPOTHESES[name]


def _segment_counts(n: int, shares: np.ndarray) -> np.ndarray:
    """Largest-remainder allocation of ``n`` users to ``shares``."""
    exact = shares * n
    counts = np.floor(exact).astype(int)
    counts[np.argsort(counts - exact)[: n - counts.sum()]] += 1
    return counts


def _activation_dates(n: int, start: date, end: date, rng: np.random.Generator) -> np.ndarray:
    """60 % of users at ``start``; the rest in equal cohorts on each month start in ``(start, end]``."""
    cohorts = pd.date_range(pd.Timestamp(start) + pd.Timedelta(days=1), pd.Timestamp(end), freq="MS")
    dates = np.full(n, np.datetime64(start, "ns"))
    if len(cohorts):
        late = rng.permutation(n)[round(n * INITIAL_SHARE) :]
        for cohort, idx in zip(cohorts, np.array_split(late, len(cohorts)), strict=True):
            dates[idx] = cohort.to_datetime64()
    return dates


def generate_users(
    n: int,
    archetypes: dict,
    start: date,
    end: date,
    seed: int,
    params: SimParams,
) -> pd.DataFrame:
    """``n`` users with ``user_id, segment, activation_date, payday_bd, anses_day, n_bills, has_autodebit``.

    ``payday_bd`` is a business-day index (1..4) for salaried users; ``anses_day`` is a
    calendar day of month (9..25) for ANSES beneficiaries. Paydays follow
    ``params.payday_hypothesis``.
    """
    payday_p = check_payday_hypothesis(params.payday_hypothesis)
    rng = np.random.default_rng(seed)
    specs = archetypes["archetypes"]
    names = list(specs)
    counts = _segment_counts(n, np.array([specs[s]["share"] for s in names]))
    segment = rng.permutation(np.repeat(np.array(names, dtype=object), counts))

    salaried = segment == SALARIED
    payday_bd = np.where(salaried, rng.choice(np.arange(1, 5), size=n, p=payday_p), np.nan)
    anses_day = np.where(segment == ANSES, rng.integers(ANSES_FIRST_DAY, ANSES_LAST_DAY + 1, size=n), np.nan)
    bills_mean = np.array([specs[s]["bills_mean"] for s in segment], dtype=float)
    n_bills = np.minimum(rng.poisson(bills_mean), MAX_BILLS)
    has_autodebit = (n_bills > 0) & (rng.random(n) < 0.5)

    return pd.DataFrame(
        {
            "user_id": np.arange(n, dtype=np.int64),
            "segment": segment.astype(str),
            "activation_date": _activation_dates(n, start, end, rng),
            "payday_bd": payday_bd,
            "anses_day": anses_day,
            "n_bills": n_bills.astype(np.int64),
            "has_autodebit": has_autodebit,
        }
    )


def apply_cohort_waves(
    users: pd.DataFrame,
    scenarios: Sequence[Scenario],
    archetypes: dict,
    seed: int,
    params: SimParams,
) -> pd.DataFrame:
    """Append each ``CohortWave``'s users, activating on its start, with ids after the last one."""
    frames = [users]
    next_id = int(users["user_id"].max()) + 1 if len(users) else 0
    waves = [s for s in scenarios if isinstance(s, CohortWave)]
    for i, wave in enumerate(waves):
        n = wave.extra_users(wave.start)
        only = {**archetypes, "archetypes": {wave.segment: {**archetypes["archetypes"][wave.segment], "share": 1.0}}}
        added = generate_users(n, only, wave.start, wave.start, seed + 1 + i, params)
        added["user_id"] += next_id
        next_id += n
        frames.append(added)
    return pd.concat(frames, ignore_index=True) if waves else users


def apply_payday_shift(users: pd.DataFrame, scenarios: Sequence[Scenario]) -> pd.DataFrame:
    """Move every salaried payday by the summed ``PaydayShift.delta_bd``, clipped to 1..4."""
    delta = sum(s.delta_bd for s in scenarios if isinstance(s, PaydayShift))
    if not delta:
        return users
    shifted = users.copy()
    shifted["payday_bd"] = (shifted["payday_bd"] + delta).clip(1, 4)
    return shifted
