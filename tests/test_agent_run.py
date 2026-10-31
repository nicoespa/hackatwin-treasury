import json
import re
from dataclasses import replace
from types import SimpleNamespace

import pytest

from treasury.agent import tools
from treasury.agent.queue import ApprovalQueue, Tiers, load_tiers, tier_for
from treasury.agent.run import MODEL, propose_for_day, validate_rationale

# The simulated amounts are ARS; config tiers (50k/250k/1M) would block every deposit of the base data.
ARS_TIERS = Tiers(50_000_000, 250_000_000, 1_000_000_000)


@pytest.fixture
def ctx(agent_ctx, tmp_path):
    return replace(agent_ctx, queue=ApprovalQueue(tmp_path / "queue.jsonl", tiers=ARS_TIERS))


def _expected(ctx) -> dict[str, dict]:
    out = {}
    for pid in ctx.partners:
        decision = tools.get_policy_decision(ctx, pid, "stablecoin")
        if decision["amount"] > 0:
            out[pid] = decision
    return out


class FakeClient:
    """Scripted stand-in for ``anthropic.Anthropic``: round 1 calls three tools (one of them an
    attempt to change the amount), round 2 returns the final JSON built by ``final``."""

    def __init__(self, final, misquote: bool = True):
        self.final = final
        self.misquote = misquote
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        messages = kwargs["messages"]
        partner = re.search(r'"partner": "(\w+)"', messages[0]["content"]).group(1)
        if len(messages) == 1:
            decision = json.loads(messages[0]["content"].split("\n", 1)[1])
            blocks = [
                SimpleNamespace(type="text", text="Looking at the numbers."),
                SimpleNamespace(type="tool_use", id="t1", name="get_forecast", input={"partner": partner}),
                SimpleNamespace(type="tool_use", id="t2", name="get_balance", input={"partner": partner}),
                SimpleNamespace(type="tool_use", id="t3", name="propose_transfer", input={
                    "partner": partner, "rail": decision["rail_used"], "amount": decision["amount"] * 3 + 10_000 if self.misquote else decision["amount"],
                    "rationale": "Queued at the policy amount."}),
            ]
            return SimpleNamespace(stop_reason="tool_use", content=blocks)
        results = {r["tool_use_id"]: r for r in messages[-1]["content"]}
        text = self.final(json.loads(results["t1"]["content"]), json.loads(results["t2"]["content"]), results)
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=text)])


def test_rationale_numbers_validated(ctx):
    outputs = [{"amount": 120_000.0, "p_unresolvable": 0.0123, "q99": [1_234_567.891]}]
    assert validate_rationale("Deposit 120,000; p_unresolvable 1.2% (1.23%); q99 1,234,568 on 2026-10-27 at 09:00", outputs)
    assert not validate_rationale("Deposit 130,000 to be safe", outputs)

    def honest(forecast, balance, results):
        assert results["t3"]["is_error"] is True and "policy amount" in results["t3"]["content"]
        return json.dumps({"rationale": f"Available {balance['available']:,.0f}; q99 today "
                                        f"{forecast['q99'][0]:,.0f}.", "exception": None})

    client = FakeClient(honest)
    expected = _expected(ctx)
    proposals = propose_for_day(ctx, client=client)
    assert {p.partner: p.amount for p in proposals} == {pid: d["amount"] for pid, d in expected.items()}
    assert all("[templated]" not in p.rationale and p.rationale.startswith("Available") for p in proposals)
    assert client.calls[0]["model"] == MODEL
    assert {t["name"] for t in client.calls[0]["tools"]} == set(tools.TOOLS)

    def inventive(forecast, balance, results):
        return "```json\n" + json.dumps({"rationale": "Deposit 987,654,321 because demand will triple.",
                                         "exception": "crypto rally"}) + "\n```"

    ctx2 = replace(ctx, queue=ApprovalQueue(ctx.queue.path.with_name("other.jsonl"), tiers=ARS_TIERS))
    proposals = propose_for_day(ctx2, client=FakeClient(inventive))
    assert proposals and all(p.rationale.endswith("[templated]") for p in proposals)
    assert all(p.exception == "crypto rally" for p in proposals)
    assert {p.partner: p.amount for p in proposals} == {pid: d["amount"] for pid, d in expected.items()}

    # an in-loop propose_transfer at the policy amount queues with its own (number-free) rationale
    ctx3 = replace(ctx, queue=ApprovalQueue(ctx.queue.path.with_name("loop.jsonl"), tiers=ARS_TIERS))
    proposals = propose_for_day(ctx3, client=FakeClient(inventive, misquote=False))
    assert {p.partner for p in proposals} == set(expected)
    assert all(p.rationale == "Queued at the policy amount." and p.exception is None for p in proposals)


def test_propose_for_day_offline(ctx):
    expected = _expected(ctx)
    assert expected
    proposals = propose_for_day(ctx, client=None)
    assert sorted(p.partner for p in proposals) == sorted(expected)
    for p in proposals:
        d = expected[p.partner]
        assert p.amount == d["amount"] and p.rail == d["rail_used"] and p.tier == tier_for(p.amount, ARS_TIERS)
        assert p.status == ("auto_approved" if p.tier == "T1" else "pending")
        assert p.rationale.endswith("[templated]") and f"deposit {p.amount:,.0f} via {p.rail}" in p.rationale
        assert p.exception is None
    again = propose_for_day(ctx, client=None)  # same run id: nothing new is queued
    assert [p.id for p in again] == [p.id for p in proposals]
    assert len(ctx.queue.path.read_text().splitlines()) == len(proposals)


def test_propose_for_day_skips_blocked(ctx, caplog):
    strict = replace(ctx, queue=ApprovalQueue(ctx.queue.path.with_name("strict.jsonl"), tiers=load_tiers()))
    big = [pid for pid, d in _expected(ctx).items() if tier_for(d["amount"], strict.queue.tiers) == "T4_blocked"]
    assert big
    with caplog.at_level("WARNING", logger="treasury.agent.run"):
        proposals = propose_for_day(strict, client=None)
    assert not {p.partner for p in proposals} & set(big)
    assert all(pid in caplog.text for pid in big) and "blocked" in caplog.text
