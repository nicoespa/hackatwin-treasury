"""Append-only approval queue for proposed transfers. Nothing here moves money: a proposal only
records what the policy recommends and who signed off on it.

Tiers by amount (``config/policy.yaml`` → ``tiers``): up to ``T1_auto_max`` a proposal is queued
already ``auto_approved`` (still auditable); up to ``T2_single_max`` it waits for one approver; up
to ``T3_dual_max`` for two distinct approvers; above that it is ``T4_blocked`` and never queued.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from uuid import uuid4

import pandas as pd
import yaml

POLICY_YAML = Path(__file__).resolve().parents[3] / "config" / "policy.yaml"
APPROVALS_NEEDED = {"T2": 1, "T3": 2}


@dataclass(frozen=True)
class Tiers:
    T1_auto_max: float
    T2_single_max: float
    T3_dual_max: float


def load_tiers(path: str | Path = POLICY_YAML) -> Tiers:
    return Tiers(**yaml.safe_load(Path(path).read_text())["tiers"])


def tier_for(amount: float, tiers: Tiers) -> str:
    if amount <= tiers.T1_auto_max:
        return "T1"
    if amount <= tiers.T2_single_max:
        return "T2"
    return "T3" if amount <= tiers.T3_dual_max else "T4_blocked"


@dataclass(frozen=True)
class Proposal:
    """One state of a proposed transfer. ``status`` is ``auto_approved``, ``pending``, ``approved``
    or ``rejected``; ``approvals`` holds ``{approver, at}`` and ``rejection`` ``{approver, reason,
    at}``; ``exception`` is the anomaly the LLM flagged for the approver, if any."""

    id: str
    created_at: str
    partner: str
    rail: str
    amount: float
    tier: str
    rationale: str
    forecast_run_id: str
    status: str
    approvals: list[dict] = field(default_factory=list)
    rejection: dict | None = None
    exception: str | None = None


class ApprovalQueue:
    """JSONL file where every state change appends the full record; the latest line per id wins."""

    def __init__(self, path: str | Path, tiers: Tiers | None = None) -> None:
        self.path = Path(path)
        self.tiers = tiers or load_tiers()

    def _append(self, proposal: Proposal) -> Proposal:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps(asdict(proposal)) + "\n")
        return proposal

    def _latest(self) -> dict[str, Proposal]:
        if not self.path.exists():
            return {}
        latest: dict[str, Proposal] = {}
        for line in self.path.read_text().splitlines():
            if line.strip():
                record = json.loads(line)
                latest[record["id"]] = Proposal(**record)
        return latest

    def propose(
        self, partner: str, rail: str, amount: float, rationale: str, forecast_run_id: str,
        exception: str | None = None,
    ) -> Proposal:
        tier = tier_for(amount, self.tiers)
        if tier == "T4_blocked":
            raise ValueError(f"{amount:,.0f} to {partner} is above T3_dual_max: T4_blocked, not queued")
        return self._append(Proposal(
            id=uuid4().hex, created_at=_now(), partner=partner, rail=rail,
            amount=float(amount), tier=tier, rationale=rationale, forecast_run_id=forecast_run_id,
            status="auto_approved" if tier == "T1" else "pending", exception=exception,
        ))

    def get(self, id: str) -> Proposal:
        return self._latest()[id]

    def list(self, status: str | None = None) -> list[Proposal]:
        return [p for p in self._latest().values() if status is None or p.status == status]

    def _pending(self, id: str) -> Proposal:
        proposal = self.get(id)
        if proposal.status != "pending":
            raise ValueError(f"proposal {id} is {proposal.status}, not pending")
        return proposal

    def approve(self, id: str, approver: str) -> Proposal:
        proposal, who = self._pending(id), _approver_id(approver)
        if who in (a["approver"] for a in proposal.approvals):
            raise ValueError(f"{who} already approved {id}; {proposal.tier} needs distinct approvers")
        approvals = [*proposal.approvals, {"approver": who, "at": _now()}]
        status = "approved" if len(approvals) >= APPROVALS_NEEDED[proposal.tier] else "pending"
        return self._append(replace(proposal, approvals=approvals, status=status))

    def reject(self, id: str, approver: str, reason: str) -> Proposal:
        proposal = self._pending(id)
        rejection = {"approver": _approver_id(approver), "reason": reason, "at": _now()}
        return self._append(replace(proposal, status="rejected", rejection=rejection))


def _approver_id(approver: str) -> str:
    """Approver ids compare case- and whitespace-insensitively, so "Ana " and "ana" are one person."""
    who = approver.strip().lower()
    if not who:
        raise ValueError("approver must not be empty")
    return who


def _now() -> str:
    return pd.Timestamp.now(tz="UTC").isoformat()
