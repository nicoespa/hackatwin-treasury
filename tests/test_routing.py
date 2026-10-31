from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from treasury.calendar import Calendar
from treasury.routing import (
    INFLOW_PRODUCTS,
    RouteOverride,
    load_partners,
    partner_for_product,
    route_events,
    settle_at,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def cal() -> Calendar:
    return Calendar.from_yaml(ROOT / "config" / "calendar_ar.yaml")


@pytest.fixture(scope="module")
def partners():
    return load_partners(ROOT / "config" / "partners.yaml")


def _events(rows: list[tuple[str, str]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "at": pd.to_datetime([at for at, _ in rows]),
            "user_id": range(len(rows)),
            "segment": "core",
            "product": [product for _, product in rows],
            "amount": 100.0,
            "confirmed": True,
        }
    )


def test_load_partners_reads_config(partners):
    assert set(partners) == {
        "bills_aggregator",
        "card_network",
        "fci_custodian",
        "crypto_exchange",
        "cash_network",
        "remittance",
    }
    card = partners["card_network"]
    assert card.products == ("card_purchase", "card_refund")
    assert (card.settle_lag_business_days, card.settle_cutoff_hour) == (1, 17)
    assert (card.same_day_before_cutoff, card.nets_inflows) == (False, True)
    assert card.accepts_rails == ("wire", "stablecoin")
    assert partners["crypto_exchange"].accepts_rails == ("stablecoin",)


def test_weekend_card_purchase_settles_tuesday(partners, cal):
    # Sat 2026-11-07: day0 is Mon 2026-11-09, +1 business day at the 17:00 cutoff.
    got = settle_at(pd.Timestamp("2026-11-07 11:00"), partners["card_network"], cal)
    assert got == pd.Timestamp("2026-11-10 17:00")


def test_friday_after_cutoff_card_purchase_settles_tuesday(partners, cal):
    card = partners["card_network"]
    assert settle_at(pd.Timestamp("2026-11-06 17:30"), card, cal) == pd.Timestamp("2026-11-10 17:00")
    assert settle_at(pd.Timestamp("2026-11-06 16:59"), card, cal) == pd.Timestamp("2026-11-09 17:00")


def test_bill_payment_settles_realtime(partners, cal):
    bills = partner_for_product("bill_payment", partners)
    assert bills.id == "bills_aggregator"
    for at in ("2026-11-04 10:15", "2026-11-04 20:00", "2026-11-08 03:00"):
        assert settle_at(pd.Timestamp(at), bills, cal) == pd.Timestamp(at)


def test_route_marks_inflow_direction(partners, cal):
    events = _events([("2026-11-04 10:00", "fci_redemption"), ("2026-11-04 10:00", "fci_subscription")])
    routed = route_events(events, partners, cal)
    assert routed["partner"].tolist() == ["fci_custodian", "fci_custodian"]
    assert routed["direction"].tolist() == [-1, 1]
    assert routed["direction"].dtype == "int8"
    assert INFLOW_PRODUCTS == frozenset({"card_refund", "fci_redemption", "crypto_sell", "cash_in"})


def test_route_events_matches_scalar_settle_at_and_keeps_input(partners, cal):
    rows = [
        ("2026-11-06 16:00", "card_purchase"),
        ("2026-11-06 18:00", "card_refund"),
        ("2026-11-07 09:00", "cash_out"),
        ("2026-11-06 17:59", "cash_in"),
        ("2026-11-08 22:00", "bill_payment"),
        ("2026-11-23 12:00", "remittance_out"),
        ("2026-11-23 12:00", "card_purchase"),
    ]
    events = _events(rows)
    before = events.copy()
    routed = route_events(events, partners, cal)
    pd.testing.assert_frame_equal(events, before)
    expected = [settle_at(at, partners[p], cal) for at, p in zip(routed["at"], routed["partner"])]
    assert routed["settle_at"].tolist() == expected
    assert routed["partner"].tolist() == [
        "card_network",
        "card_network",
        "cash_network",
        "cash_network",
        "bills_aggregator",
        "remittance",
        "card_network",
    ]


def test_override_reroutes_product_within_window(partners, cal):
    events = _events(
        [
            ("2026-11-09 10:00", "card_purchase"),
            ("2026-11-10 10:00", "card_purchase"),
            ("2026-11-11 23:59", "card_purchase"),
            ("2026-11-12 10:00", "card_purchase"),
            ("2026-11-10 10:00", "card_refund"),
        ]
    )
    outage = RouteOverride(
        product="card_purchase", start=date(2026, 11, 10), end=date(2026, 11, 11), partner_id="bills_aggregator"
    )
    routed = route_events(events, partners, cal, overrides=[outage])
    assert routed["partner"].tolist() == [
        "card_network",
        "bills_aggregator",
        "bills_aggregator",
        "card_network",
        "card_network",
    ]
    # The override partner is real-time, so rerouted events settle at the event instant.
    assert routed["settle_at"].iloc[1] == pd.Timestamp("2026-11-10 10:00")
    assert routed["settle_at"].iloc[2] == pd.Timestamp("2026-11-11 23:59")
    assert routed["settle_at"].iloc[0] == pd.Timestamp("2026-11-10 17:00")


def test_unknown_product_raises(partners, cal):
    with pytest.raises(KeyError, match="lottery_ticket"):
        partner_for_product("lottery_ticket", partners)
    with pytest.raises(KeyError, match="lottery_ticket"):
        route_events(_events([("2026-11-04 10:00", "lottery_ticket")]), partners, cal)


def test_duplicate_product_rejected(tmp_path):
    path = tmp_path / "partners.yaml"
    fields = (
        "settle_lag_business_days: 0\n    settle_cutoff_hour: 15\n    same_day_before_cutoff: true\n"
        "    nets_inflows: false\n    accepts_rails: [wire]\n"
    )
    path.write_text(f"a:\n    products: [bill_payment]\n    {fields}b:\n    products: [bill_payment]\n    {fields}")
    with pytest.raises(ValueError, match="bill_payment"):
        load_partners(path)
