import pytest

from treasury.agent.queue import ApprovalQueue, load_tiers, tier_for


def test_queue_roundtrip_and_tiers(tmp_path):
    path = tmp_path / "queue.jsonl"
    queue = ApprovalQueue(path)
    tiers = load_tiers()
    assert tier_for(50_000, tiers) == "T1" and tier_for(1_000_000, tiers) == "T3"
    assert tier_for(1_000_001, tiers) == "T4_blocked"

    t1 = queue.propose("remittance", "stablecoin", 50_000, "small", "run-1")
    assert (t1.tier, t1.status, t1.approvals) == ("T1", "auto_approved", [])
    assert len(t1.id) == 32

    t2 = queue.propose("remittance", "stablecoin", 50_001, "single", "run-1")
    assert (t2.tier, t2.status) == ("T2", "pending")
    assert queue.approve(t2.id, "ana").status == "approved"

    t3 = queue.propose("card_network", "stablecoin", 250_001, "dual", "run-1")
    assert t3.tier == "T3"
    first = queue.approve(t3.id, "ana")
    assert (first.status, first.approvals) == ("pending", ["ana"])
    with pytest.raises(ValueError, match="already approved"):
        queue.approve(t3.id, "ana")
    assert queue.approve(t3.id, "beto").status == "approved"

    with pytest.raises(ValueError, match="T4_blocked"):
        queue.propose("card_network", "stablecoin", 1_000_001, "too big", "run-1")

    t4 = queue.propose("bills_aggregator", "wire", 120_000, "to reject", "run-1")
    rejected = queue.reject(t4.id, "ana", "balance already enough")
    assert rejected.status == "rejected"
    assert rejected.rejection["approver"] == "ana" and rejected.rejection["reason"] == "balance already enough"
    with pytest.raises(ValueError, match="rejected"):
        queue.approve(t4.id, "beto")
    with pytest.raises(ValueError):
        queue.approve(t1.id, "ana")  # auto-approved: nothing left to approve

    reloaded = ApprovalQueue(path)
    latest = {p.id: p for p in reloaded.list()}
    assert list(latest) == [t1.id, t2.id, t3.id, t4.id]
    assert latest[t3.id].approvals == ["ana", "beto"] and latest[t3.id].status == "approved"
    assert reloaded.get(t4.id).status == "rejected"
    assert [p.id for p in reloaded.list(status="approved")] == [t2.id, t3.id]
    assert reloaded.list(status="pending") == []
    # append-only: 4 proposals + 3 approvals + 1 rejection, the blocked one never written
    assert len(path.read_text().splitlines()) == 8
    with pytest.raises(KeyError):
        reloaded.get("missing")
