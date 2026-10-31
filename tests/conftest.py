import json
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from treasury.agent.queue import Tiers
from treasury.backtest import Dataset
from treasury.features import build_drivers
from treasury.models.base import daily_node_table

SIM = Path(__file__).resolve().parents[1] / "data" / "sim" / "base"
START, END = "2025-11-01", "2026-10-31"
# The ruled approval tiers (ARS), injected so the agent tests do not depend on config/policy.yaml.
ARS_TIERS = Tiers(T1_auto_max=50_000_000, T2_single_max=250_000_000, T3_dual_max=2_000_000_000)


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


@pytest.fixture(scope="session")
def agent_ctx(dataset, tmp_path_factory):
    """A ``ToolContext`` on the base data at 2026-10-26 with a small ``SegmentLGBM`` (300 paths)."""
    from treasury.agent.queue import ApprovalQueue
    from treasury.agent.run import build_context

    queue = ApprovalQueue(tmp_path_factory.mktemp("agent") / "queue.jsonl", tiers=ARS_TIERS)
    return build_context(dataset, pd.Timestamp("2026-10-26"), queue, n_paths=300)


@pytest.fixture
def ctx(agent_ctx, tmp_path):
    """``agent_ctx`` with an empty queue of its own, on ``ARS_TIERS``."""
    from treasury.agent.queue import ApprovalQueue

    return replace(agent_ctx, queue=ApprovalQueue(tmp_path / "queue.jsonl", tiers=ARS_TIERS))


@pytest.fixture(scope="session")
def funded(agent_ctx) -> dict[str, dict]:
    """The policy decision (preferred rail stablecoin) of every partner it funds, in partner order."""
    from treasury.agent import tools

    decisions = {pid: tools.get_policy_decision(agent_ctx, pid, "stablecoin") for pid in agent_ctx.partners}
    funded = {pid: d for pid, d in decisions.items() if d["amount"] > 0}
    assert funded, "no partner needs a deposit at 2026-10-26"
    return funded
