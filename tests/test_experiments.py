import json
from datetime import date

import pandas as pd
import pytest
from typer.testing import CliRunner

from treasury.cli import app
from treasury.experiments import (
    MODEL_FACTORIES,
    ablation_table,
    designed_to_lose,
    factorial_table,
    frontier,
    unknown_scenario_eval,
)
from treasury.harness import default_origins

END = date(2026, 10, 31)
ORIGINS = default_origins(END, n=3, step_days=7, horizon=14)


def test_model_factories_cover_the_ablation():
    assert list(MODEL_FACTORIES) == [
        "seasonal_naive", "aggregate_drivers", "aggregate_drivers_obligations", "segment_factor", "segment_nofactor",
    ]
    assert MODEL_FACTORIES["segment_factor"](n_paths=123).n_paths == 123


def test_ablation_table_pooled_and_by_partner(dataset):
    pooled = ablation_table(dataset, ORIGINS, models=("seasonal_naive",), n_paths=200)
    assert pooled[["label", "model"]].values.tolist() == [["(a)", "seasonal_naive"]]
    assert {"pinball_q90", "cov_90", "pit_ks", "crps"} <= set(pooled.columns)
    per_partner = ablation_table(dataset, ORIGINS, models=("seasonal_naive",), n_paths=200, by=("model", "partner"))
    assert len(per_partner) == 6


def test_factorial_table_has_four_cells(dataset):
    table = factorial_table(dataset, ORIGINS, n_paths=200)
    assert len(table) == 4
    assert set(zip(table["cell"], table["rail"])) == {
        ("reference", "wire"), ("reference", "stablecoin"), ("proposed", "wire"), ("proposed", "stablecoin"),
    }
    for col in ("capital_total_mean", "shortfall_rate", "shortfall_amount_total", "cost_total", "n_transfers"):
        assert table[col].notna().all()
    stable = table[table["rail"] == "stablecoin"]["rail_note"].iloc[0]
    assert "fci_custodian=wire" in stable and "cash_network=wire" in stable


def test_frontier_rises_with_alpha(dataset):
    table = frontier(dataset, alphas=(0.9, 0.995), origins=ORIGINS, n_paths=200, buffer_days=(3,))
    proposed = table[table["policy"] == "forecast"].set_index(["rail", "param"])
    assert len(proposed) == 4 and len(table) == 6
    for rail in ("wire", "stablecoin"):
        assert proposed.loc[(rail, 0.995), "capital_total_mean"] > proposed.loc[(rail, 0.9), "capital_total_mean"]


def test_cli_backtest_prints_metrics(tmp_path):
    result = CliRunner().invoke(app, [
        "backtest", "--data", "data/sim/base", "--model", "seasonal_naive", "--rail", "wire", "--policy", "forecast",
        "--alpha", "0.95", "--n-paths", "200", "--n-origins", "2",
    ])
    assert result.exit_code == 0, result.output
    metrics = json.loads(result.output)
    assert metrics["rail_used"]["crypto_exchange"] == "stablecoin" and metrics["n_days"] == 14


@pytest.mark.slow
def test_designed_to_lose_segment_does_not_win():
    table = designed_to_lose(seed=7).set_index("model")
    assert table.loc["segment_factor", "pinball_q90"] >= 0.97 * table.loc["aggregate_drivers_obligations", "pinball_q90"]


@pytest.mark.slow
def test_unknown_scenario_eval_runs(dataset):
    table = unknown_scenario_eval(dataset, n_paths=200)
    assert set(zip(table["model"], table["variant"])) == {
        (m, v) for m in ("aggregate_drivers_obligations", "segment_factor") for v in ("announced", "surprise")
    }
    for col in ("pinball_q90", "cov_90", "pit_ks", "capital_total_mean", "shortfall_rate"):
        assert pd.to_numeric(table[col]).notna().all()
