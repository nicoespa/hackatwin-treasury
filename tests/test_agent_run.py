import json
import re
from dataclasses import replace
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from treasury.agent import tools
from treasury.agent.queue import ApprovalQueue, Tiers, tier_for
from treasury.agent.run import MODEL, propose_for_day, validate_rationale


def _queue(ctx, name: str, tiers=None):
    return replace(ctx, queue=ApprovalQueue(ctx.queue.path.with_name(name), tiers=tiers or ctx.queue.tiers))


class FakeClient:
    """Scripted stand-in for ``anthropic.Anthropic``: round 1 calls three tools (the third a
    ``propose_transfer``, off the policy amount when ``misquote``), round 2 returns the final text
    built by ``final(decision, forecast, balance, results)`` from the tool results it got back."""

    def __init__(self, final, misquote: bool = True, in_loop_rationale: str = "Queued at the policy amount."):
        self.final, self.misquote, self.in_loop_rationale = final, misquote, in_loop_rationale
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        messages = kwargs["messages"]
        partner = re.search(r'"partner": "(\w+)"', messages[0]["content"]).group(1)
        decision = json.loads(messages[0]["content"].split("\n", 1)[1])
        if len(messages) == 1:
            blocks = [
                SimpleNamespace(type="text", text="Looking at the numbers."),
                SimpleNamespace(type="tool_use", id="t1", name="get_forecast", input={"partner": partner}),
                SimpleNamespace(type="tool_use", id="t2", name="get_balance", input={"partner": partner}),
                SimpleNamespace(type="tool_use", id="t3", name="propose_transfer", input={
                    "partner": partner, "rail": decision["rail_used"],
                    "amount": decision["amount"] * 3 + 10_000 if self.misquote else decision["amount"],
                    "rationale": self.in_loop_rationale}),
            ]
            return SimpleNamespace(stop_reason="tool_use", content=blocks)
        results = {r["tool_use_id"]: r for r in messages[-1]["content"]}
        text = self.final(decision, json.loads(results["t1"]["content"]), json.loads(results["t2"]["content"]), results)
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=text)])


class FailingClient:
    def __init__(self):
        self.messages = self

    def create(self, **kwargs):
        raise anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))


def test_rationale_numbers_validated(ctx, funded, caplog):
    outputs = [{"amount": 120_000.0, "target": 300_000.0, "p_unresolvable": 0.0123, "q99": [1_234_567.891]}]
    must = (120_000.0, 300_000.0)
    assert validate_rationale("Deposit 120,000; p_unresolvable 1.2% (1.23%); q99 1,234,568 on 2026-10-27 at 09:00",
                              outputs, must)
    assert not validate_rationale("Deposit 130,000 to be safe", outputs)
    assert not validate_rationale("", outputs) and not validate_rationale("Deposit as the policy says.", outputs)
    assert not validate_rationale("q99 1,234,568 today", outputs, must)  # cites neither amount nor target
    assert validate_rationale("Target 300,000 covers q99.", outputs, must)
    assert validate_rationale("crypto rally", outputs, require_number=False)

    def honest(decision, forecast, balance, results):
        assert results["t3"]["is_error"] is True and "policy amount" in results["t3"]["content"]
        return json.dumps({"rationale": f"Deposit {decision['amount']:,.0f}; available {balance['available']:,.0f}; "
                                        f"q99 today {forecast['q99'][0]:,.0f}.",
                           "exception": "q99 999,999,999,999 is far above normal"})

    client = FakeClient(honest)
    with caplog.at_level("WARNING", logger="treasury.agent.run"):
        proposals = propose_for_day(ctx, client=client)
    assert {p.partner: p.amount for p in proposals} == {pid: d["amount"] for pid, d in funded.items()}
    assert all("[templated" not in p.rationale and p.rationale.startswith("Deposit") for p in proposals)
    assert all(p.exception is None for p in proposals) and "exception dropped" in caplog.text
    assert client.calls[0]["model"] == MODEL
    assert {t["name"] for t in client.calls[0]["tools"]} == set(tools.TOOLS)

    def inventive(decision, forecast, balance, results):
        return "```json\n" + json.dumps({"rationale": "Deposit 987,654,321 because demand will triple.",
                                         "exception": "crypto rally"}) + "\n```"

    caplog.clear()
    with caplog.at_level("WARNING", logger="treasury.agent.run"):
        proposals = propose_for_day(_queue(ctx, "other.jsonl"), client=FakeClient(inventive))
    assert proposals and all(p.rationale.endswith("[templated: rationale rejected by the validator]") for p in proposals)
    assert all(p.exception == "crypto rally" for p in proposals)
    assert all(pid in caplog.text for pid in funded) and "rationale rejected" in caplog.text
    assert {p.partner: p.amount for p in proposals} == {pid: d["amount"] for pid, d in funded.items()}

    # in-loop propose_transfer at the policy amount: a number-free rationale is templated, a cited one kept
    proposals = propose_for_day(_queue(ctx, "loop.jsonl"), client=FakeClient(inventive, misquote=False))
    assert {p.partner for p in proposals} == set(funded)
    assert all(p.rationale.endswith("[templated: rationale rejected by the validator]") for p in proposals)
    first = next(iter(funded.values()))
    cited = FakeClient(inventive, misquote=False, in_loop_rationale=f"Deposit {first['amount']:,.0f}.")
    proposal = propose_for_day(_queue(ctx, "cited.jsonl"), client=cited)[0]
    assert proposal.rationale == f"Deposit {first['amount']:,.0f}."


def test_llm_failure_is_templated_and_logged(ctx, funded, caplog):
    with caplog.at_level("WARNING", logger="treasury.agent.run"):
        proposals = propose_for_day(ctx, client=FailingClient())
    assert {p.partner for p in proposals} == set(funded)
    assert all(p.rationale.endswith("[templated: LLM call failed]") for p in proposals)
    assert all(f"LLM call failed for {pid}" in caplog.text for pid in funded)


def test_propose_for_day_offline(ctx, funded):
    proposals = propose_for_day(ctx, client=None)
    assert [p.partner for p in proposals] == list(funded)
    for p in proposals:
        d = funded[p.partner]
        assert p.amount == d["amount"] and p.rail == d["rail_used"] and p.tier == tier_for(p.amount, ctx.queue.tiers)
        assert p.tier != "T4_blocked" and p.status == ("auto_approved" if p.tier == "T1" else "pending")
        assert p.rationale.endswith("[templated: offline]") and f"deposit {p.amount:,.0f} via {p.rail}" in p.rationale
        assert p.exception is None
    again = propose_for_day(ctx, client=None)  # same run id: nothing new is queued
    assert [p.id for p in again] == [p.id for p in proposals]
    assert len(ctx.queue.path.read_text().splitlines()) == len(proposals)


def test_propose_for_day_skips_blocked(ctx, funded, caplog):
    strict = _queue(ctx, "strict.jsonl", Tiers(T1_auto_max=1_000, T2_single_max=10_000, T3_dual_max=100_000))
    blocked = [pid for pid, d in funded.items() if tier_for(d["amount"], strict.queue.tiers) == "T4_blocked"]
    assert blocked
    with caplog.at_level("WARNING", logger="treasury.agent.run"):
        proposals = propose_for_day(strict, client=None)
    assert not {p.partner for p in proposals} & set(blocked)
    assert all(pid in caplog.text for pid in blocked) and "blocked" in caplog.text
