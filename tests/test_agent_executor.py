import json
from dataclasses import replace

import pandas as pd
import pytest

from treasury.agent.executor import (
    SimulatedExecutor,
    TransferLedger,
    ledger_status,
    read_ledger,
)
from treasury.agent.guardrails import Limits, check, load_autonomy
from treasury.agent.run import (
    FORECAST_DAYS_OUT,
    execute_day,
    format_summary,
    partner_currencies,
)
from treasury.backtest import CONFIG
from treasury.calendar import Calendar
from treasury.rails import load_rails

CAL = Calendar.from_yaml(CONFIG / "calendar_ar.yaml")
RAILS = load_rails(CONFIG / "rails.yaml")
CFG = replace(load_autonomy(), enabled=True, max_forecast_age_hours=24, sanity_multiple=3,
              limits={"ARS": Limits(max_per_transfer=100e6, max_per_partner_day=150e6, max_all_partners_day=300e6)})
LOT = 1000.0


def _check(**kw):
    args = dict(partner="card_network", rail="wire", currency="ARS", policy_amount=80e6, p_unresolvable=0.0,
                forecast_age_hours=9.0, trailing_max_drain=100e6, spent_partner_today=0.0, spent_all_today=0.0,
                lot_size=LOT, p_threshold=0.05)
    return check(kw.pop("cfg", CFG), **(args | kw))


def test_config_block_loads():
    cfg = load_autonomy()
    assert cfg.enabled and "ARS" in cfg.limits
    assert cfg.destination("fci_custodian", "wire") and cfg.destination("fci_custodian", "stablecoin") is None


def test_check_within_limits_executes_policy_amount():
    v = _check()
    assert (v.amount, v.limit_applied, v.remainder, v.alerts) == (80e6, None, 0.0, [])


def test_check_caps_at_remaining_limit_with_remainder_alert():
    v = _check(policy_amount=130_500_500.0, spent_partner_today=0.0)
    assert v.amount == 100e6 and v.limit_applied == "max_per_transfer" and v.remainder == 30_500_500.0
    [alert] = v.alerts
    assert (alert.code, alert.action, alert.details["remainder"]) == ("limit_capped", "capped", 30_500_500.0)

    v = _check(policy_amount=90e6, spent_partner_today=99_999_500.0)  # 50,000,500 left today, floored to the lot
    assert v.amount == 50_000_000.0 and v.limit_applied == "max_per_partner_day" and v.remainder == 40e6
    v = _check(policy_amount=90e6, spent_all_today=300e6)
    assert v.held and v.alerts[0].action == "hold" and v.limit_applied == "max_all_partners_day"


def test_check_holds_on_kill_switch_forecast_and_sanity():
    assert _check(cfg=replace(CFG, enabled=False)).alerts[0].code == "kill_switch"
    assert _check(forecast_age_hours=None).alerts[0].code == "forecast_missing"
    stale = _check(forecast_age_hours=33.0)
    assert stale.held and stale.alerts[0].code == "forecast_stale"
    insane = _check(policy_amount=90e6, trailing_max_drain=20e6)  # bound 60M
    assert insane.held and insane.alerts[0].code == "sanity_bound" and insane.alerts[0].details["bound"] == 60e6
    assert _check(rail="stablecoin", partner="fci_custodian").alerts[0].code == "no_destination"
    assert _check(currency="BRL").alerts[0].code == "no_limits"
    assert all(v.held for v in (stale, insane))


def test_check_alerts_but_executes_on_high_p_unresolvable():
    v = _check(p_unresolvable=0.2)
    assert v.amount == 80e6 and [(a.code, a.action) for a in v.alerts] == [("p_unresolvable", "execute")]


def test_executor_is_idempotent_and_uses_the_allow_listed_account(tmp_path):
    ledger = TransferLedger(tmp_path / "t.jsonl")
    ex = SimulatedExecutor(ledger, CFG, RAILS, CAL)
    at = pd.Timestamp("2026-10-26 09:00")
    t1, created = ex.execute("card_network", "wire", 50e6, "ARS", at, "run", 50e6)
    t2, again = ex.execute("card_network", "wire", 50e6, "ARS", at, "run", 50e6)
    assert created and not again and t1 == t2 and len(read_ledger(ledger.path)) == 1
    assert t1.destination == CFG.destination("card_network", "wire") and t1.currency == "ARS"
    assert t1.idempotency_key == "card_network@2026-10-26T09:00:00"
    with pytest.raises(ValueError, match="limits"):  # above max_per_transfer
        ex.execute("card_network", "wire", 101e6, "ARS", at + pd.Timedelta(hours=1), "run", 101e6)
    ex.execute("card_network", "wire", 100e6, "ARS", at + pd.Timedelta(hours=1), "run", 100e6)  # 150M today
    with pytest.raises(ValueError, match="limits"):  # above max_per_partner_day
        ex.execute("card_network", "wire", LOT, "ARS", at + pd.Timedelta(hours=2), "run", LOT)
    with pytest.raises(ValueError, match="allow-listed"):
        ex.execute("fci_custodian", "stablecoin", 1e6, "ARS", at, "run", 1e6)
    with pytest.raises(ValueError, match="kill switch"):
        SimulatedExecutor(ledger, replace(CFG, enabled=False), RAILS, CAL).execute(
            "remittance", "wire", 1e6, "ARS", at, "run", 1e6)
    assert len(read_ledger(ledger.path)) == 2


def test_status_transitions_by_time(tmp_path):
    ledger = TransferLedger(tmp_path / "t.jsonl")
    ex = SimulatedExecutor(ledger, CFG, RAILS, CAL)
    # Friday 2026-10-23 after the 15:00 wire cutoff: accepted Monday 10-26, credited 2 business days later.
    wire, _ = ex.execute("card_network", "wire", 10e6, "ARS", pd.Timestamp("2026-10-23 16:00"), "run", 10e6)
    assert (wire.accepted_at, wire.arrival_at) == ("2026-10-26T00:00:00", "2026-10-28T10:00:00")
    expected = {"2026-10-23 15:00": None, "2026-10-24 12:00": "instructed", "2026-10-26 09:00": "in_transit",
                "2026-10-28 09:59": "in_transit", "2026-10-28 10:00": "credited"}
    assert {t: wire.status_at(pd.Timestamp(t)) for t in expected} == expected
    coin, _ = ex.execute("crypto_exchange", "stablecoin", 1e6, "ARS", pd.Timestamp("2026-10-24 18:00"), "run", 1e6)
    assert coin.status_at(pd.Timestamp("2026-10-24 18:00")) == "in_transit"
    assert coin.status_at(pd.Timestamp("2026-10-24 18:30")) == "credited"
    statuses = {s["partner"]: s["status"] for s in ledger_status(ledger.path, pd.Timestamp("2026-10-25 12:00"))}
    assert statuses == {"card_network": "instructed", "crypto_exchange": "credited"}
    assert [t.partner for t in ledger.in_transit("card_network", pd.Timestamp("2026-10-27"))] == ["card_network"]


def test_partner_currency_from_config(tmp_path, ctx):
    path = tmp_path / "partners.yaml"
    path.write_text("card_network: {currency: USD}\n")
    currencies = partner_currencies(ctx.partners, path)
    assert currencies["card_network"] == "USD" and currencies["remittance"] == "ARS"


def _day(ctx, tmp_path, cfg, name="t.jsonl", data_through=pd.Timestamp("2026-10-25")):
    ledger = TransferLedger(tmp_path / name)
    return execute_day(ctx, ledger, data_through, "stablecoin", cfg), ledger


def test_execute_day_caps_alerts_and_is_idempotent(ctx, funded, tmp_path):
    biggest = max(funded, key=lambda p: funded[p]["amount"])
    cap = funded[biggest]["amount"] / 2
    cfg = replace(CFG, sanity_multiple=1e9, limits={"ARS": Limits(cap, 10 * cap, 100 * cap)})
    result, ledger = _day(ctx, tmp_path, cfg)
    rows = {r["partner"]: r for r in result["partners"]}
    row = rows[biggest]
    assert row["status"] == "capped" and row["limit_applied"] == "max_per_transfer"
    assert row["executed_amount"] == pytest.approx(cap // LOT * LOT)
    assert row["remainder"] == pytest.approx(row["policy_amount"] - row["executed_amount"])
    assert any(a["code"] == "limit_capped" for a in row["alerts"])
    assert {p for p, r in rows.items() if r["executed_amount"] > 0} == set(funded)
    assert all(r["status"] == "no_deposit" for p, r in rows.items() if p not in funded)
    lines = ledger.path.read_text()

    again, _ = _day(ctx, tmp_path, cfg)
    assert ledger.path.read_text() == lines  # nothing sent twice
    again_rows = {r["partner"]: r for r in again["partners"]}
    assert all(again_rows[p]["status"] == "already_executed" for p in funded)
    assert again_rows[biggest]["executed_amount"] == row["executed_amount"]
    assert again_rows[biggest]["alerts"] == row["alerts"]


def test_execute_day_kill_switch_holds_everything(ctx, funded, tmp_path):
    result, ledger = _day(ctx, tmp_path, replace(CFG, enabled=False))
    assert not ledger.path.exists()
    assert all(r["status"] == "held" and r["alerts"][0]["code"] == "kill_switch" for r in result["partners"])
    assert "APAGADO" in format_summary(result)


def test_execute_day_sanity_bound_and_stale_forecast_hold(ctx, funded, tmp_path):
    insane, ledger = _day(ctx, tmp_path, replace(CFG, sanity_multiple=1e-9))
    rows = {r["partner"]: r for r in insane["partners"]}
    assert all(rows[p]["status"] == "held" and rows[p]["alerts"][0]["code"] == "sanity_bound" for p in funded)
    assert not ledger.path.exists()
    stale, _ = _day(ctx, tmp_path, CFG, "stale.jsonl", data_through=pd.Timestamp("2026-10-22"))
    assert stale["forecast_age_hours"] == 81
    assert all(r["status"] == "held" and r["alerts"][0]["code"] == "forecast_stale" for r in stale["partners"])
    missing, _ = _day(ctx, tmp_path, CFG, "missing.jsonl", data_through=None)
    assert all(r["alerts"][0]["code"] == "forecast_missing" for r in missing["partners"])


def test_execute_day_json_shape(ctx, funded, tmp_path):
    cfg = replace(CFG, sanity_multiple=1e9, limits={"ARS": Limits(1e12, 1e12, 1e12)})
    result, _ = _day(ctx, tmp_path, cfg)
    json.dumps(result, allow_nan=False)
    assert {"as_of", "review_at", "rail", "forecast_run_id", "autonomy", "totals", "partners"} <= set(result)
    assert [r["partner"] for r in result["partners"]] == list(ctx.partners)
    keys = {"partner", "currency", "rail", "destination", "status", "forecast_tomorrow", "available", "in_transit",
            "need", "policy_amount", "executed_amount", "limit_applied", "remainder", "eta", "alerts", "rationale",
            "forecast_7d"}
    review_day = ctx.review_at.date().isoformat()
    for r in result["partners"]:
        assert keys <= set(r) and r["currency"] == "ARS" and r["rationale"]
        assert 0 < len(r["forecast_7d"]) <= FORECAST_DAYS_OUT
        assert all(d["date"] > review_day and d["q05"] <= d["q50"] <= d["q99"] for d in r["forecast_7d"])
        assert r["forecast_tomorrow"] == r["forecast_7d"][0]
        if r["partner"] in funded:
            assert r["status"] == "executed" and r["executed_amount"] == funded[r["partner"]]["amount"]
            assert r["eta"] == r["transfer"]["arrival_at"] and r["transfer"]["status"] in ("in_transit", "credited")
    assert result["totals"]["ARS"]["executed_in_run"] == pytest.approx(sum(d["amount"] for d in funded.values()))
    summary = format_summary(result)
    assert all(p in summary for p in ctx.partners) and "Pronóstico mañana" in summary
