import re
import time
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from conftest import ARS_TIERS

from treasury.agent.queue import ApprovalQueue
from treasury.dashboard import data
from treasury.simulate import Campaign, CohortWave, FxJump, PartnerOutage

REPORTS = Path(__file__).resolve().parents[1] / "reports" / "experiments"


def _readme_saved() -> dict[str, int]:
    """The ``capital saved`` column of the README's ``Same service level`` table, in percent."""
    text = (REPORTS / "README.md").read_text().split("## Same service level")[1].split("##")[0]
    rows = [line.split("|")[1:-1] for line in text.splitlines() if line.startswith(("| wire", "| stablecoin"))]
    return {cells[0].strip(): int(re.sub(r"\D", "", cells[-1])) for cells in rows}


def test_headline_numbers_from_factorial():
    assert set(_readme_saved()) == {"wire", "stablecoin"}
    table = data.headline(pd.read_csv(REPORTS / "factorial.csv"))
    assert list(table["rail"]) == ["wire", "stablecoin"]
    for rail, saved in _readme_saved().items():
        row = table.set_index("rail").loc[rail]
        assert round(row["capital_saved"] * 100) == saved
        assert row["capital_saved"] == pytest.approx(1 - row["proposed_capital"] / row["matched_capital"])
        assert row["proposed_shortfall_rate"] <= row["matched_shortfall_rate"] + 1e-12 or row["matched_shortfall_rate"] == 0


def test_factorial_view_orders_cells_per_rail_and_keeps_the_four_metrics():
    view = data.factorial_view(pd.read_csv(REPORTS / "factorial.csv"))
    assert list(zip(view["rail"], view["cell"])) == [
        (r, c) for r in ("wire", "stablecoin") for c in ("reference", "proposed", "reference_matched")
    ]
    assert {"capital_total_mean", "shortfall_rate", "cost_total", "n_transfers", "buffer_days"} <= set(view.columns)
    assert view["equal_service"].tolist() == [False, True, True] * 2


def test_frontier_at_alpha_picks_cheapest_buffer_at_least_as_safe():
    frontier = pd.DataFrame([
        {"rail": "wire", "policy": "forecast", "param": 0.9, "capital_total_mean": 100.0, "shortfall_rate": 0.01},
        {"rail": "wire", "policy": "forecast", "param": 0.99, "capital_total_mean": 120.0, "shortfall_rate": 0.0},
        {"rail": "wire", "policy": "fixed", "param": 3.0, "capital_total_mean": 90.0, "shortfall_rate": 0.05},
        {"rail": "wire", "policy": "fixed", "param": 5.0, "capital_total_mean": 150.0, "shortfall_rate": 0.01},
        {"rail": "wire", "policy": "fixed", "param": 8.0, "capital_total_mean": 200.0, "shortfall_rate": 0.0},
    ])
    out = data.frontier_at_alpha(frontier, 0.9).iloc[0]
    assert out["proposed_capital"] == 100.0 and out["fixed_days"] == 5.0 and out["fixed_capital"] == 150.0
    assert out["capital_saved"] == pytest.approx(1 - 100 / 150)
    strict = data.frontier_at_alpha(frontier, 0.99).iloc[0]
    assert strict["fixed_days"] == 8.0
    frontier.loc[4, "shortfall_rate"] = 0.02  # no buffer in the sweep is as safe as alpha 0.99
    assert np.isnan(data.frontier_at_alpha(frontier, 0.99).iloc[0]["fixed_capital"])


def test_frontier_at_config_alpha_uses_the_factorial_matched_row():
    factorial = pd.read_csv(REPORTS / "factorial.csv")
    at = data.frontier_at_alpha(pd.read_csv(REPORTS / "frontier.csv"), 0.99, factorial).set_index("rail")
    head = data.headline(factorial).set_index("rail")
    for rail in ("wire", "stablecoin"):
        assert at.loc[rail, "source"] == "factorial"
        assert at.loc[rail, "fixed_days"] == head.loc[rail, "matched_buffer_days"]
        assert at.loc[rail, "fixed_capital"] == head.loc[rail, "matched_capital"]
        assert at.loc[rail, "capital_saved"] == pytest.approx(head.loc[rail, "capital_saved"])
    other = data.frontier_at_alpha(pd.read_csv(REPORTS / "frontier.csv"), 0.9, factorial)
    assert set(other["source"]) == {"sweep"}


def test_surprise_summary_reads_pooled_rows():
    unknown = pd.read_csv(REPORTS / "unknown_scenario.csv")
    out = data.surprise_summary(unknown)
    assert set(out["label"]) == {"(c)", "(d)"}
    assert set(out["variant"]) == {"announced", "surprise"}
    row = out[(out["label"] == "(d)") & (out["variant"] == "surprise")].iloc[0]
    assert row["capital_total_mean"] == pytest.approx(1750455875.1419373)


def test_every_dashboard_table_is_in_the_reports():
    assert "designed_to_lose" in data.EXPERIMENT_TABLES
    assert all((REPORTS / f"{t}.csv").exists() for t in data.EXPERIMENT_TABLES)


def test_designed_to_lose_sentence_from_the_csv():
    table = pd.read_csv(REPORTS / "designed_to_lose.csv")
    rows = table.set_index("label")
    gaps = data.designed_to_lose_gaps(table)
    assert gaps["pinball_q90"] == pytest.approx(rows.loc["(d)", "pinball_q90"] / rows.loc["(c)", "pinball_q90"] - 1)
    assert gaps["crps"] == pytest.approx(rows.loc["(d)", "crps"] / rows.loc["(c)", "crps"] - 1)
    assert round(gaps["pinball_q90"], 2) == 0.13 and round(gaps["crps"], 2) == -0.12
    assert data.designed_to_lose_sentence(table) == "(d) es 13 % peor que (c) en pinball_q90 y 12 % mejor en CRPS"
    flipped = table.assign(crps=table["crps"][::-1].to_numpy())  # (d) now worse on CRPS too
    assert data.designed_to_lose_sentence(flipped).endswith("14 % peor en CRPS")


def test_unknown_scenarios_text_from_the_experiment_constants():
    from datetime import date

    assert data.unknown_scenarios_text() == "Campaña de tarjeta (×1,8, 5–7 oct) y ola de 3.000 usuarios young_heavy (15 sep)"
    other = data.unknown_scenarios_text(Campaign(date(2026, 1, 30), date(2026, 2, 2), ("bill_payment",), 1.25),
                                        CohortWave(date(2026, 3, 1), 12_500, "salaried_formal"))
    assert other == "Campaña de pago de facturas (×1,25, 30 ene–2 feb) y ola de 12.500 usuarios salaried_formal (1 mar)"


def test_config_cells_of_the_reports_match_config():
    """The dashboard labels the factorial's config cells from config/policy.yaml: the CSVs must
    have been generated with it."""
    from treasury.backtest import CONFIG
    from treasury.policy import load_policy

    cfg = load_policy(CONFIG / "policy.yaml")
    factorial = pd.read_csv(REPORTS / "factorial.csv")
    assert (factorial.loc[factorial["cell"] == "reference", "buffer_days"] == cfg.fixed_buffer_days).all()
    assert data.config_alpha(factorial) == cfg.alpha


def test_zero_shortfall_alpha_per_rail():
    from treasury.experiments import zero_shortfall_alpha

    assert zero_shortfall_alpha(pd.read_csv(REPORTS / "frontier.csv")) == {"wire": 0.9, "stablecoin": 0.99}
    frontier = pd.DataFrame([
        {"rail": "wire", "policy": "forecast", "param": 0.9, "shortfall_rate": 0.0},
        {"rail": "wire", "policy": "forecast", "param": 0.99, "shortfall_rate": 0.01},  # not 0 from 0.9 on
        {"rail": "stablecoin", "policy": "forecast", "param": 0.9, "shortfall_rate": 0.02},
        {"rail": "stablecoin", "policy": "forecast", "param": 0.99, "shortfall_rate": 0.0},
    ])
    assert zero_shortfall_alpha(frontier) == {"wire": None, "stablecoin": 0.99}
    assert zero_shortfall_alpha(frontier.assign(shortfall_rate=0.5)) == {"wire": None, "stablecoin": None}


def test_pit_values_in_unit_interval_per_model(dataset):
    out = data.pit_values(dataset, n_origins=1, models=("seasonal_naive", "segment_factor"), n_paths=200)
    assert set(out["model"]) == {"seasonal_naive", "segment_factor"}
    assert set(out["label"]) == {"(a)", "(d)"}
    assert out["pit"].between(0, 1).all()
    assert (out.groupby("model").size() == 6 * 14).all()  # partners x horizon at one origin


def test_queue_frame_counts_approvals(tmp_path):
    queue = ApprovalQueue(tmp_path / "q.jsonl", tiers=ARS_TIERS)
    t3 = queue.propose("fci_custodian", "wire", 300_000_000, "r", "run@1")
    queue.approve(t3.id, "ana")
    queue.propose("cash_network", "wire", 10_000_000, "r", "run@1")
    frame = data.queue_frame(queue.list())
    row = frame.set_index("partner").loc["fci_custodian"]
    assert row["status"] == "pending" and row["approvals"] == "1/2" and row["tier"] == "T3"
    assert frame.set_index("partner").loc["cash_network", "status"] == "auto_approved"
    assert data.queue_frame([]).empty


def test_stress_spec_builds_scenarios_in_the_forecast_week():
    first, last = pd.Timestamp("2026-10-25").date(), pd.Timestamp("2026-10-31").date()
    assert data.StressSpec().scenarios(first, last) == []
    spec = data.StressSpec(campaign_lift=1.5, campaign_product="bill_payment", cohort_size=1000,
                           cohort_segment="young_heavy", fx_lift=3.0, fx_day=2, outage=True,
                           outage_partner="bills_aggregator", reroute_to="remittance")
    assert spec.scenarios(first, last) == [
        Campaign(first, last, ("bill_payment",), 1.5),
        CohortWave(first, 1000, "young_heavy"),
        FxJump(first + timedelta(days=2), data.FX_DAYS, 3.0),
        PartnerOutage("bills_aggregator", first, last, "remittance"),
    ]


@pytest.fixture(scope="module")
def stress_base(dataset):
    return data.build_stress_base(dataset, n_paths=500)


@pytest.fixture(scope="module")
def baseline(stress_base):
    return data.stress_run(stress_base, data.StressSpec())


def test_stress_baseline_starts_funded_at_its_own_targets(stress_base, baseline):
    table = baseline.table.set_index("partner")
    assert stress_base.as_of == pd.Timestamp(stress_base.train.end) - pd.Timedelta(days=6)
    assert len(stress_base.dates) == 7
    assert (table["balance"] == table["target"]).all()
    assert (table["amount"] <= 1e-3 * table["target"]).all()  # funded at its target: a few lots at most
    assert table.loc["crypto_exchange", "rail_used"] == "stablecoin"
    assert table.loc["fci_custodian", "rail_used"] == "wire"  # no stablecoin: its only rail


def test_stress_rerun_changes_bills_deposit(stress_base, baseline):
    spec = data.StressSpec(campaign_lift=1.5, campaign_product="bill_payment")
    began = time.perf_counter()
    stressed = data.stress_run(stress_base, spec, balances=baseline.balances)
    elapsed = time.perf_counter() - began
    diff = data.compare(baseline.table, stressed.table).set_index("partner")
    assert diff.loc["bills_aggregator", "delta_amount"] > 0.1 * diff.loc["bills_aggregator", "target"]
    assert diff.loc["bills_aggregator", "delta_target"] > 0
    assert diff.loc["bills_aggregator", "delta_forecast_week"] > 0
    assert diff.loc["card_network", "delta_target"] == 0  # bill_payment does not settle there
    assert diff.loc["card_network", "delta_amount"] == 0
    assert elapsed < 10


def test_stress_outage_moves_realized_flow_not_the_forecast(stress_base, baseline):
    spec = data.StressSpec(outage=True, outage_partner="bills_aggregator", reroute_to="remittance")
    diff = data.compare(baseline.table, data.stress_run(stress_base, spec, balances=baseline.balances).table)
    diff = diff.set_index("partner")
    assert diff.loc["bills_aggregator", "realized_week"] == 0
    assert diff.loc["remittance", "delta_realized_week"] > 0
    assert diff.loc["bills_aggregator", "delta_forecast_week"] == 0  # the model has no outage driver


def test_stress_components_per_forecast_date(stress_base, baseline):
    comp = data.components(baseline, "bills_aggregator")
    assert list(comp["date"]) == [d.date().isoformat() for d in stress_base.dates]
    assert {"confirmed", "predicted_recurring", "residual_total", "factor_share"} <= set(comp.columns)
    segments = [c for c in comp.columns if c.startswith("segment:")]
    assert segments and np.allclose(comp[segments].sum(axis=1), comp["residual_total"], rtol=1e-6, atol=1)
