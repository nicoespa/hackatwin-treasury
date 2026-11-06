"""International variant: joint calendars, SWIFT arrival, FX paths, USD reporting, and the domestic
config left exactly as it was."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from treasury.backtest import CONFIG, Dataset, run
from treasury.calendar import Calendar
from treasury.configset import ConfigSet
from treasury.features import known_at, settle_load
from treasury.fx import simulate_fx, usd_per_unit
from treasury.harness import default_origins
from treasury.intl import usd_by_partner
from treasury.policy import load_policy, window_flows
from treasury.rails import arrival_time
from treasury.routing import load_partners, route_events

INTL = ConfigSet.resolve("intl")
AR, BR, US = INTL.calendar("ar"), INTL.calendar("br"), INTL.calendar("us")
PARTNERS = INTL.partners()
SWIFT = INTL.rails()["swift"]


def test_intl_configs_load():
    assert set(PARTNERS) == {"pix_br", "usd_acquirer"}
    assert (PARTNERS["pix_br"].currency, PARTNERS["pix_br"].country) == ("BRL", "br")
    assert (PARTNERS["usd_acquirer"].currency, PARTNERS["usd_acquirer"].country) == ("USD", "us")
    assert PARTNERS["pix_br"].is_realtime and not PARTNERS["usd_acquirer"].is_realtime
    assert INTL.calendar("ar") == ConfigSet.resolve().calendar("ar")  # the Argentine calendar is shared
    assert INTL.policy().cost_of_capital_annual == 0.08
    swift_only = ConfigSet.resolve("intl", {"usd_acquirer": ["swift"]}).partners()
    assert swift_only["usd_acquirer"].accepts_rails == ("swift",) and swift_only["pix_br"].accepts_rails == ("swift", "stablecoin")


@pytest.mark.parametrize(("day", "ar", "br", "us"), [
    ("2026-01-19", True, True, False),    # Martin Luther King Jr. Day
    ("2026-02-16", False, False, False),  # Carnaval (AR, BR) and Washington's Birthday (US)
    ("2026-03-24", False, True, True),    # Día de la Memoria
    ("2026-06-04", True, False, True),    # Corpus Christi
    ("2026-07-03", True, True, True),     # Reserve Banks open the Friday before a Saturday holiday
    ("2025-11-20", True, False, True),    # Consciência Negra
    ("2026-11-26", True, True, False),    # Thanksgiving
])
def test_country_calendars(day, ar, br, us):
    d = date.fromisoformat(day)
    assert (AR.is_business_day(d), BR.is_business_day(d), US.is_business_day(d)) == (ar, br, us)
    assert Calendar.joint(AR, BR).is_business_day(d) == (ar and br)
    assert Calendar.joint(AR, US).is_business_day(d) == (ar and us)


def test_joint_of_one_calendar_is_itself():
    assert Calendar.joint(AR) == AR
    assert ConfigSet.resolve().rail_calendar(load_partners(CONFIG / "partners.yaml")["card_network"]) == AR


@pytest.mark.parametrize(("instruct", "partner", "arrives"), [
    ("2026-01-16 09:00", "usd_acquirer", "2026-01-21 12:00"),  # skips MLK Monday (US)
    ("2026-01-16 09:00", "pix_br", "2026-01-20 12:00"),        # Brazil is open on MLK day
    ("2026-06-03 09:00", "pix_br", "2026-06-08 12:00"),        # skips Corpus Christi (BR)
    ("2026-06-03 09:00", "usd_acquirer", "2026-06-05 12:00"),
    ("2026-03-20 09:00", "usd_acquirer", "2026-03-26 12:00"),  # skips the AR puente and Día de la Memoria
    ("2026-01-15 14:00", "usd_acquirer", "2026-01-21 12:00"),  # after the 13:00 cutoff: counts from Friday
])
def test_swift_arrival_skips_holidays_of_either_country(instruct, partner, arrives):
    cal = INTL.rail_calendar(PARTNERS[partner])
    assert arrival_time(SWIFT, pd.Timestamp(instruct), cal) == pd.Timestamp(arrives)


def test_card_settlement_lag_counts_us_business_days():
    events = pd.DataFrame({"at": pd.to_datetime(["2026-01-16 10:00", "2026-01-16 10:00"]), "user_id": [0, 1],
                           "segment": ["occasional"] * 2, "product": ["intl_card", "pix_brazil"],
                           "amount": [10.0, 50.0], "confirmed": [False, False], "counterparty": ["", ""]})
    routed = route_events(events, PARTNERS, AR, partner_cals=INTL.settle_calendars())
    assert routed["settle_at"].tolist() == [pd.Timestamp("2026-01-20 17:00"), pd.Timestamp("2026-01-16 10:00")]
    assert route_events(events, PARTNERS, AR)["settle_at"].iloc[0] == pd.Timestamp("2026-01-19 17:00")


def test_settle_load_counts_days_settling_on_a_date():
    assert settle_load(US, 1, date(2026, 1, 13)) == 3.0  # Tuesday: Friday after the cutoff to Monday
    assert settle_load(US, 1, date(2026, 1, 21)) == 4.0  # after MLK Monday
    assert settle_load(US, 1, date(2026, 1, 15)) == 1.0
    assert settle_load(US, 1, date(2026, 1, 17)) == 0.0  # Saturday


def test_fx_paths_are_deterministic_in_the_seed():
    market = INTL.market()
    dates = pd.date_range("2025-11-01", "2026-10-31", freq="D")
    a, b, c = simulate_fx(market, dates, 42), simulate_fx(market, dates, 42), simulate_fx(market, dates, 43)
    pd.testing.assert_frame_equal(a, b)
    assert not np.allclose(a["ars_per_usd"], c["ars_per_usd"])
    assert a["ars_per_usd"].iloc[0] == market["ars_per_usd"]["start"] and (a[["ars_per_usd", "brl_per_usd"]] > 0).all().all()
    assert a["ars_per_usd"].iloc[-1] > a["ars_per_usd"].iloc[0]  # the crawl and the jumps only depreciate the peso on net


def test_known_at_freezes_rates_at_the_origin():
    drivers = pd.DataFrame({"date": pd.date_range("2026-01-01", periods=5), "fx_ars_per_usd": [1.0, 2, 3, 4, 5],
                            "tourism_index": [1.0, 1, 2, 2, 2]})
    known = known_at(drivers, pd.Timestamp("2026-01-03"))
    assert known["fx_ars_per_usd"].tolist() == [1, 2, 2, 2, 2]
    assert known["tourism_index"].tolist() == [1, 1, 2, 2, 2]  # calendar drivers are known ahead
    domestic = drivers.drop(columns="fx_ars_per_usd")
    assert known_at(domestic, pd.Timestamp("2026-01-03")) is domestic


def test_lagged_outflow_placed_at_settle_hour():
    partner, dates = PARTNERS["usd_acquirer"], pd.date_range("2026-01-13", periods=3)
    paths = np.full((2, 3), 100.0)
    at, _ = window_flows(paths, dates, partner, pd.Timestamp("2026-01-13 09:00"), pd.Timestamp("2026-01-15 12:00"),
                         lagged_at_cutoff=True)
    assert list(at) == [pd.Timestamp("2026-01-13 17:00"), pd.Timestamp("2026-01-14 17:00")]  # 01-15 17:00 is after the window
    at, _ = window_flows(paths, dates, partner, pd.Timestamp("2026-01-13 09:00"), pd.Timestamp("2026-01-15 12:00"))
    assert list(at) == [pd.Timestamp("2026-01-13 09:00"), pd.Timestamp("2026-01-14"), pd.Timestamp("2026-01-15")]


def test_usd_per_unit_uses_the_latest_rate():
    fx = pd.DataFrame({"date": pd.to_datetime(["2026-01-01", "2026-01-02"]), "ars_per_usd": [1000.0, 1250.0],
                       "brl_per_usd": [5.0, 4.0]})
    at = pd.to_datetime(["2026-01-01 15:00", "2026-01-02 09:00", "2026-01-05 00:00"])
    assert usd_per_unit(fx, "BRL", at).tolist() == [0.2, 0.25, 0.25]
    assert usd_per_unit(fx, "ARS", at[:1]).tolist() == [0.001]
    assert usd_per_unit(None, "USD", at).tolist() == [1.0, 1.0, 1.0]
    with pytest.raises(ValueError):
        usd_per_unit(None, "BRL", at)


@pytest.fixture(scope="module")
def intl_data(tmp_path_factory):
    from treasury.cli import simulate

    out = tmp_path_factory.mktemp("intl")
    simulate(users=2000, start=pd.Timestamp("2026-06-01").to_pydatetime(), end=pd.Timestamp("2026-08-31").to_pydatetime(),
             seed=3, out=out, payday_hypothesis="late", sigma_m=0.15, phi=0.7, config="intl")
    return out


def test_intl_dataset_backtest_reports_partner_currency_and_usd(intl_data):
    dataset = Dataset.load(intl_data)
    assert dataset.params["config"] == "intl" and dataset.fx is not None
    assert {"fx_ars_per_brl_chg90", "tourism_index", "settles_usd_acquirer"} <= set(dataset.drivers)
    ev = dataset.events
    assert set(ev.loc[ev["product"] == "pix_brazil", "partner"]) == {"pix_br"}
    assert (ev.loc[ev["product"] == "usd_income", "direction"] == -1).all()
    origins = default_origins(dataset.end, n=2, step_days=7, horizon=14)
    result = run(dataset, None, "fixed", "swift", INTL.policy(), origins)
    assert set(result.metrics["rail_used"].values()) == {"swift"}
    by = usd_by_partner(result, dataset, origins).set_index("partner")
    assert by.loc["usd_acquirer", "capital_mean_usd"] == pytest.approx(by.loc["usd_acquirer", "capital_mean"])
    rate = 1 / dataset.fx["brl_per_usd"].iloc[-30:].mean()
    assert by.loc["pix_br", "capital_mean_usd"] == pytest.approx(by.loc["pix_br", "capital_mean"] * rate, rel=0.05)
    sent = result.decisions[(result.decisions["amount"] > 0) & (result.decisions["partner"] == "usd_acquirer")
                            & (result.decisions["at"] >= pd.Timestamp(origins[0]) + pd.Timedelta(days=result.metrics["warmup_days"]))]
    assert by.loc["usd_acquirer", "fees_usd"] == pytest.approx(30 * len(sent) + 30e-4 * sent["amount"].sum())


# Domestic results recorded at the base commit (c71bd17), before the international variant.
DOMESTIC_SIM_HASH, DOMESTIC_SIM_EVENTS = 1134699049685664654, 50879
DOMESTIC_DRIVERS_HASH = 1018656886796542808


def _hash(df: pd.DataFrame) -> int:
    return int(pd.util.hash_pandas_object(df, index=False).sum() % (2**61))


def test_domestic_simulation_is_unchanged():
    from treasury.simulate import SimParams, load_archetypes
    from treasury.simulate.pipeline import simulate_routed

    _, events, _ = simulate_routed(1000, load_archetypes(CONFIG / "archetypes.yaml"), AR,
                                   load_partners(CONFIG / "partners.yaml"), date(2026, 1, 1), date(2026, 3, 31), 7,
                                   SimParams())
    assert (len(events), _hash(events)) == (DOMESTIC_SIM_EVENTS, DOMESTIC_SIM_HASH)


def test_domestic_backtest_is_unchanged(dataset):
    assert _hash(dataset.drivers) == DOMESTIC_DRIVERS_HASH
    origins = default_origins(dataset.end, n=3, step_days=7, horizon=14)
    m = run(dataset, None, "fixed", "stablecoin", load_policy(CONFIG / "policy.yaml"), origins).metrics
    assert (m["capital_total_mean"], m["shortfall_rate"], m["n_transfers"], m["fees"]) == pytest.approx(
        (2138387892.3122942, 0.12745098039215685, 140, 5654993.0), rel=1e-12)
