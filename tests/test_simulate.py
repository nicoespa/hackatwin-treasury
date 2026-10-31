from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from treasury.calendar import Calendar
from treasury.routing import INFLOW_PRODUCTS, load_partners, route_events
from treasury.simulate import (
    Campaign,
    CohortWave,
    FxJump,
    PartnerOutage,
    PaydayShift,
    SimParams,
    anses_boost_date,
    apply_cohort_waves,
    apply_payday_shift,
    generate_users,
    load_archetypes,
    scenario_overrides,
    simulate_events,
    validate,
)

ROOT = Path(__file__).resolve().parents[1]
START = date(2025, 11, 1)


@pytest.fixture(scope="module")
def cal() -> Calendar:
    return Calendar.from_yaml(ROOT / "config" / "calendar_ar.yaml")


@pytest.fixture(scope="module")
def partners():
    return load_partners(ROOT / "config" / "partners.yaml")


@pytest.fixture(scope="module")
def archetypes():
    return load_archetypes(ROOT / "config" / "archetypes.yaml")


def _acf(x: np.ndarray, lag: int) -> float:
    x = x - x.mean()
    return float((x[:-lag] * x[lag:]).sum() / (x * x).sum())


def test_archetypes_config_is_consistent(archetypes, partners):
    known = {product for partner in partners.values() for product in partner.products}
    specs = archetypes["archetypes"]
    assert sum(spec["share"] for spec in specs.values()) == pytest.approx(1.0)
    for spec in specs.values():
        products = spec["products"]
        assert set(products) <= known
        for inflow, outflow in [
            ("card_refund", "card_purchase"),
            ("fci_redemption", "fci_subscription"),
            ("crypto_sell", "crypto_buy"),
            ("cash_in", "cash_out"),
        ]:
            if outflow in products:
                ratio = products[inflow]["base_rate_per_day"] / products[outflow]["base_rate_per_day"]
                assert 0.05 <= ratio <= 0.30
    assert specs["salaried_formal"]["products"]["bill_payment"]["base_rate_per_day"] == 0.08
    assert specs["investor"]["products"]["fci_subscription"]["base_rate_per_day"] == 0.15
    assert specs["crypto_active"]["products"]["crypto_buy"]["base_rate_per_day"] == 0.12
    assert INFLOW_PRODUCTS <= known


def test_users_shares_and_payday_hypothesis(archetypes):
    end = date(2026, 10, 31)
    late = generate_users(20_000, archetypes, START, end, seed=1, payday_hypothesis="late")
    shares = late["segment"].value_counts(normalize=True)
    for segment, spec in archetypes["archetypes"].items():
        assert abs(shares[segment] - spec["share"]) <= 0.02

    salaried = late["segment"] == "salaried_formal"
    assert late.loc[salaried, "payday_bd"].mean() > 2.8
    assert late.loc[salaried, "payday_bd"].between(1, 4).all()
    assert late.loc[~salaried, "payday_bd"].isna().all()
    anses = late["segment"] == "anses_beneficiary"
    assert late.loc[anses, "anses_day"].between(9, 25).all()
    assert late.loc[~anses, "anses_day"].isna().all()
    assert (late["activation_date"] == pd.Timestamp(START)).mean() == pytest.approx(0.6, abs=0.01)
    assert not late.loc[late["n_bills"] == 0, "has_autodebit"].any()

    uniform = generate_users(20_000, archetypes, START, end, seed=1, payday_hypothesis="uniform")
    assert uniform.loc[uniform["segment"] == "salaried_formal", "payday_bd"].mean() == pytest.approx(2.5, abs=0.1)

    with pytest.raises(ValueError):
        SimParams(payday_hypothesis="weekly")


def test_macro_factor_autocorrelation(archetypes, cal):
    end = date(2026, 10, 31)
    users = generate_users(200, archetypes, START, end, seed=3)
    _, macro = simulate_events(users, archetypes, cal, START, end, SimParams(), [], seed=3)
    assert len(macro) == 365
    log_m = np.log(macro["m_t"].to_numpy())
    assert 0.5 <= _acf(log_m, 1) <= 0.85


def test_events_have_confirmed_only_for_autodebit(archetypes, cal):
    end = date(2025, 12, 31)
    users = generate_users(2_000, archetypes, START, end, seed=5)
    events, _ = simulate_events(users, archetypes, cal, START, end, SimParams(), [], seed=5)
    assert list(events.columns) == ["at", "user_id", "segment", "product", "amount", "confirmed", "counterparty"]
    autodebit = set(users.loc[users["has_autodebit"], "user_id"])
    confirmed = events[events["confirmed"]]
    assert len(confirmed) > 0
    assert set(confirmed["user_id"]) <= autodebit
    assert (confirmed["product"] == "bill_payment").all()
    assert (confirmed["counterparty"] != "").all()
    # An autodebit bill is paid every month on its fixed due day for the same amount.
    per_bill = confirmed.groupby("counterparty").agg(
        days=("at", lambda s: s.dt.day.nunique()), amounts=("amount", "nunique")
    )
    assert (per_bill["days"] == 1).all() and (per_bill["amounts"] == 1).all()
    assert events["at"].between(pd.Timestamp(START), pd.Timestamp("2026-01-01")).all()


def test_campaign_raises_volume(archetypes, cal):
    end = date(2025, 11, 30)
    users = generate_users(2_000, archetypes, START, end, seed=7)
    window = (date(2025, 11, 15), date(2025, 11, 21))
    campaign = Campaign(start=window[0], end=window[1], products=("bill_payment",), lift=1.5)

    def volume(scenarios) -> float:
        events, _ = simulate_events(users, archetypes, cal, START, end, SimParams(), scenarios, seed=7)
        day = events["at"].dt.normalize()
        rows = (events["product"] == "bill_payment") & day.between(pd.Timestamp(window[0]), pd.Timestamp(window[1]))
        return float(events.loc[rows, "amount"].sum())

    assert volume([campaign]) >= 1.3 * volume([])


def test_scenarios(archetypes, partners):
    users = generate_users(1_000, archetypes, START, date(2026, 4, 30), seed=9)
    wave = CohortWave(start=date(2026, 2, 1), n_users=300, segment="young_heavy")
    grown = apply_cohort_waves(users, [wave, PaydayShift(delta_bd=1)], archetypes, seed=9)
    added = grown.iloc[len(users) :]
    assert len(added) == 300
    assert added["user_id"].tolist() == list(range(users["user_id"].max() + 1, users["user_id"].max() + 301))
    assert (added["segment"] == "young_heavy").all()
    assert (added["activation_date"] == pd.Timestamp("2026-02-01")).all()
    assert wave.extra_users(date(2026, 2, 1)) == 300 and wave.extra_users(date(2026, 2, 2)) == 0

    shifted = apply_payday_shift(users, [PaydayShift(delta_bd=2)])
    salaried = users["segment"] == "salaried_formal"
    expected = (users.loc[salaried, "payday_bd"] + 2).clip(1, 4)
    assert shifted.loc[salaried, "payday_bd"].tolist() == expected.tolist()
    assert shifted.loc[~salaried, "payday_bd"].isna().all()

    fx = FxJump(date=date(2026, 1, 5), days=3)
    assert fx.multiplier(date(2026, 1, 7), "informal", "crypto_buy") == 3.0
    assert fx.multiplier(date(2026, 1, 8), "informal", "crypto_buy") == 1.0
    assert fx.multiplier(date(2026, 1, 6), "informal", "crypto_sell") == 1.0

    outage = PartnerOutage(
        partner="card_network", start=date(2026, 1, 5), end=date(2026, 1, 6), reroute_to="crypto_exchange"
    )
    overrides = outage.overrides(partners)
    assert {o.product for o in overrides} == {"card_purchase", "card_refund"}
    assert {(o.start, o.end, o.partner_id) for o in overrides} == {
        (date(2026, 1, 5), date(2026, 1, 6), "crypto_exchange")
    }
    assert outage.multiplier(date(2026, 1, 5), "informal", "card_purchase") == 1.0
    assert scenario_overrides([fx, outage, wave], partners) == overrides


def test_anses_boost_rolls_to_first_business_day_on_or_after_anses_day(cal):
    # 2026-04-25 is a Saturday; 2025-12-25 is Christmas (a Thursday, then a normal Friday).
    assert anses_boost_date(date(2026, 4, 1), 25, cal) == date(2026, 4, 27)
    assert anses_boost_date(date(2025, 12, 1), 25, cal) == date(2025, 12, 26)
    for month in [date(2025, 11, 1), date(2025, 12, 1), date(2026, 4, 1), date(2026, 10, 1)]:
        for anses_day in range(9, 26):
            boost = anses_boost_date(month, anses_day, cal)
            assert cal.is_business_day(boost) and boost.month == month.month and boost.day >= anses_day
            skipped = pd.date_range(month.replace(day=anses_day), boost, inclusive="left")
            assert not any(cal.is_business_day(d.date()) for d in skipped)


def test_anses_boost_reaches_every_beneficiary_each_month(archetypes, cal):
    # Only cash_out (bill_payment present but unused), at a rate high enough that every boosted user transacts.
    anses_only = {
        **archetypes,
        "archetypes": {
            "anses_beneficiary": {
                "share": 1.0,
                "bills_mean": 0.0,
                "products": {
                    "bill_payment": {
                        "adoption": 0.0,
                        "base_rate_per_day": 0.0,
                        "amount_median": 1,
                        "amount_sigma": 0.1,
                    },
                    "cash_out": {
                        "adoption": 1.0,
                        "base_rate_per_day": 40.0,
                        "amount_median": 1000,
                        "amount_sigma": 0.1,
                    },
                },
            }
        },
    }
    end = date(2025, 12, 31)
    users = generate_users(300, anses_only, START, START, seed=13)
    events, _ = simulate_events(users, anses_only, cal, START, end, SimParams(sigma_m=0.0), [], seed=13)
    daily = events.assign(day=events["at"].dt.normalize()).groupby(["user_id", "day"]).size()
    for month in [date(2025, 11, 1), date(2025, 12, 1)]:
        for user in users.itertuples():
            boost = pd.Timestamp(anses_boost_date(month, int(user.anses_day), cal))
            user_days = daily.loc[user.user_id]
            others = user_days[(user_days.index.month == month.month) & (user_days.index != boost)]
            assert daily.loc[(user.user_id, boost)] > 1.5 * others.mean()


def test_cohort_wave_users_reach_the_table_and_start_on_wave_day(archetypes, cal):
    end = date(2026, 1, 31)
    users = generate_users(2_000, archetypes, START, end, seed=15)
    wave = CohortWave(start=date(2026, 1, 10), n_users=500, segment="young_heavy")
    prepared = apply_payday_shift(apply_cohort_waves(users, [wave], archetypes, seed=15), [wave])
    assert len(prepared) == len(users) + 500
    events, _ = simulate_events(prepared, archetypes, cal, START, end, SimParams(), [wave], seed=15)
    wave_ids = set(prepared["user_id"].iloc[len(users) :])
    from_wave = events[events["user_id"].isin(wave_ids)]
    assert len(from_wave) > 0
    assert (from_wave["at"] >= pd.Timestamp(wave.start)).all()
    assert set(events["user_id"]) <= set(prepared["user_id"])


def test_validate_flags(archetypes, cal, partners):
    end = date(2026, 4, 30)
    users = generate_users(20_000, archetypes, START, end, seed=11)
    events, _ = simulate_events(users, archetypes, cal, START, end, SimParams(), [], seed=11)
    flags = validate(route_events(events, partners, cal), cal)
    assert flags["dispersion_index"] > 1.5
    assert flags["salaried_argmax_in_bd1_5"] is True
    assert flags["acf7_gt_acf3"] is True
    assert flags["p99_over_median"] > 1.0
