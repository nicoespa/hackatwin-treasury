import copy
import json

import numpy as np
import pandas as pd
import pytest

from treasury.agent import tools


def test_propose_transfer_tool_only_enqueues(ctx, funded):
    balances, pending = copy.deepcopy(ctx.balances), copy.deepcopy(ctx.pending_credits)
    events_hash = pd.util.hash_pandas_object(ctx.dataset.events, index=False).sum()
    pid, decision = next(iter(funded.items()))
    lot = ctx.policy_cfg.lot_size

    with pytest.raises(ValueError, match="policy amount"):
        tools.propose_transfer(ctx, pid, "stablecoin", decision["amount"] + 2 * lot, "bigger")
    assert ctx.queue.list() == []

    out = tools.propose_transfer(ctx, pid, "stablecoin", decision["amount"] + lot / 2, "within one lot")
    json.dumps(out)
    assert out["amount"] == decision["amount"]  # the policy amount is what gets queued
    assert (out["partner"], out["rail"], out["forecast_run_id"]) == (pid, decision["rail_used"], ctx.forecast_run_id)
    assert (out["seed"], out["n_paths"]) == (ctx.model.seed, ctx.model.n_paths) == (0, 300)
    assert len(ctx.queue.list()) == 1
    with pytest.raises(ValueError, match="already"):
        tools.propose_transfer(ctx, pid, "stablecoin", decision["amount"], "twice")

    assert ctx.balances == balances and ctx.pending_credits == pending
    assert pd.util.hash_pandas_object(ctx.dataset.events, index=False).sum() == events_hash


def test_read_tools_are_json_and_consistent(ctx, funded):
    pid = next(iter(funded))
    forecast = tools.get_forecast(ctx, pid)
    json.dumps(forecast)
    q = np.array([forecast[k] for k in ("q05", "q50", "q95", "q99")])
    assert q.shape[1] == len(forecast["dates"]) and (np.diff(q, axis=0) >= 0).all()
    assert forecast["dates"][0] == ctx.review_at.normalize().date().isoformat()

    balance = tools.get_balance(ctx, pid)
    assert balance == json.loads(json.dumps(balance)) and balance["available"] == ctx.balances[pid]

    day = forecast["dates"][1]
    parts = tools.explain_components(ctx, pid, day)
    json.dumps(parts)
    assert 0.0 <= parts["factor_share"] <= 1.0 and parts["residual_by_segment"]
    j = ctx.model.partner_index.index(pid)
    mean_path = ctx.model.last_paths[:, 1, j].mean()
    assert parts["confirmed"] + sum(parts["residual_by_segment"].values()) == pytest.approx(mean_path, rel=0.15)

    assert {s["name"] for s in tools.TOOL_SCHEMAS} == set(tools.TOOLS)
    assert tools.dispatch(ctx, "get_balance", {"partner": pid}) == balance
    with pytest.raises(KeyError):
        tools.dispatch(ctx, "execute_payment", {})
