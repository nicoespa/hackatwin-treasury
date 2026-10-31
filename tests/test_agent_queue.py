import pytest

from treasury.agent.queue import ApprovalQueue, Tiers, load_tiers, tier_for

TIERS = Tiers(T1_auto_max=50_000, T2_single_max=250_000, T3_dual_max=1_000_000)


def test_config_tiers_are_the_ruled_ars_values():
    assert load_tiers() == Tiers(T1_auto_max=50_000_000, T2_single_max=250_000_000, T3_dual_max=2_000_000_000)


def test_queue_roundtrip_and_tiers(tmp_path):
    path = tmp_path / "queue.jsonl"
    queue = ApprovalQueue(path, tiers=TIERS)
    assert tier_for(50_000, TIERS) == "T1" and tier_for(1_000_000, TIERS) == "T3"
    assert tier_for(1_000_001, TIERS) == "T4_blocked"

    t1 = queue.propose("remittance", "stablecoin", 50_000, "small", "run-1")
    assert (t1.tier, t1.status, t1.approvals) == ("T1", "auto_approved", [])
    assert len(t1.id) == 32

    t2 = queue.propose("remittance", "stablecoin", 50_001, "single", "run-1")
    assert (t2.tier, t2.status) == ("T2", "pending")
    assert queue.approve(t2.id, "ana").status == "approved"

    t3 = queue.propose("card_network", "stablecoin", 250_001, "dual", "run-1")
    assert t3.tier == "T3"
    first = queue.approve(t3.id, "Ana ")
    assert first.status == "pending" and [a["approver"] for a in first.approvals] == ["ana"]
    assert first.approvals[0]["at"]
    with pytest.raises(ValueError, match="already approved"):
        queue.approve(t3.id, " ANA")  # same person, other spelling
    with pytest.raises(ValueError, match="empty"):
        queue.approve(t3.id, "  ")
    assert queue.approve(t3.id, "beto").status == "approved"

    with pytest.raises(ValueError, match="T4_blocked"):
        queue.propose("card_network", "stablecoin", 1_000_001, "too big", "run-1")

    t4 = queue.propose("bills_aggregator", "wire", 120_000, "to reject", "run-1")
    rejected = queue.reject(t4.id, "Ana", "balance already enough")
    assert rejected.status == "rejected"
    assert rejected.rejection["approver"] == "ana" and rejected.rejection["reason"] == "balance already enough"
    assert rejected.rejection["at"]
    with pytest.raises(ValueError, match="rejected"):
        queue.approve(t4.id, "beto")
    with pytest.raises(ValueError):
        queue.approve(t1.id, "ana")  # auto-approved: nothing left to approve

    reloaded = ApprovalQueue(path, tiers=TIERS)
    latest = {p.id: p for p in reloaded.list()}
    assert list(latest) == [t1.id, t2.id, t3.id, t4.id]
    assert [a["approver"] for a in latest[t3.id].approvals] == ["ana", "beto"]
    assert latest[t3.id].status == "approved"
    assert reloaded.get(t4.id).status == "rejected"
    assert [p.id for p in reloaded.list(status="approved")] == [t2.id, t3.id]
    assert reloaded.list(status="pending") == []
    # append-only: 4 proposals + 3 approvals + 1 rejection, the blocked one never written
    assert len(path.read_text().splitlines()) == 8
    with pytest.raises(KeyError):
        reloaded.get("missing")


def test_proposal_keeps_forecast_seed_and_paths_and_old_records_load(tmp_path):
    import json

    path = tmp_path / "queue.jsonl"
    queue = ApprovalQueue(path, tiers=TIERS)
    new = queue.propose("remittance", "stablecoin", 1_000, "r", "run-1", seed=0, n_paths=2000)
    old = {k: v for k, v in json.loads(path.read_text()).items() if k not in ("seed", "n_paths")} | {"id": "old"}
    with path.open("a") as f:
        f.write(json.dumps(old) + "\n")
    reloaded = ApprovalQueue(path, tiers=TIERS)
    assert (reloaded.get(new.id).seed, reloaded.get(new.id).n_paths) == (0, 2000)
    assert (reloaded.get("old").seed, reloaded.get("old").n_paths) == (None, None)
