import json
from pathlib import Path

import pandas as pd
import pytest

from treasury.backtest import Dataset
from treasury.features import build_drivers
from treasury.models.base import daily_node_table

SIM = Path(__file__).resolve().parents[1] / "data" / "sim" / "base"
START, END = "2025-11-01", "2026-10-31"


@pytest.fixture(scope="session")
def sim() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Base dataset ``(users, events)``, simulated on first use when missing."""
    if not (SIM / "events.parquet").exists():
        from treasury.cli import simulate

        simulate(users=20_000, start=pd.Timestamp(START).to_pydatetime(),
                 end=pd.Timestamp(END).to_pydatetime(), seed=42, out=SIM,
                 payday_hypothesis="late", sigma_m=0.15, phi=0.7)
    return pd.read_parquet(SIM / "users.parquet"), pd.read_parquet(SIM / "events.parquet")


@pytest.fixture(scope="session")
def history(sim) -> pd.DataFrame:
    return daily_node_table(sim[1])


@pytest.fixture(scope="session")
def drivers(sim) -> pd.DataFrame:
    return build_drivers(*sim, pd.date_range(START, END, freq="D"))


@pytest.fixture(scope="session")
def dataset(sim) -> Dataset:
    return Dataset.from_frames(*sim, params=json.loads((SIM / "params.json").read_text()))
