"""Simulated executor for the autonomous agent: records transfers in an append-only JSONL ledger and
never calls a network. Each transfer carries an idempotency key (partner + review time), so a rerun
of the same review returns the transfer already recorded instead of sending it again.

The destination is never chosen by the caller: the executor reads it from the allow-list in
``config/policy.yaml`` → ``autonomy.destinations`` (per partner and rail). The executor also re-checks
the kill switch and the hard limits (``guardrails.Limits``) and refuses a transfer that breaks them,
so a bug upstream cannot move more than the limits allow.

A transfer's status follows from the clock: ``instructed`` at ``instructed_at``, ``in_transit`` once
the rail accepts it (``accepted_at``: at once on 24/7 rails; on business-day rails on a business day
before ``instruct_cutoff_hour``, else at 00:00 of the next business day), ``credited`` at
``arrival_at = rails.arrival_time``.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd

from treasury.agent.guardrails import AutonomyConfig
from treasury.calendar import Calendar
from treasury.rails import Rail, arrival_time

STATUSES = ("instructed", "in_transit", "credited")


@dataclass(frozen=True)
class Transfer:
    """One simulated transfer. Times are ISO strings; ``alerts`` are the guardrail alerts raised when
    it was executed (so a rerun reports them again) and ``policy_amount`` the policy's amount before
    any limit was applied."""

    idempotency_key: str
    partner: str
    rail: str
    amount: float
    currency: str
    destination: str
    instructed_at: str
    accepted_at: str
    arrival_at: str
    forecast_run_id: str
    policy_amount: float
    limit_applied: str | None = None
    alerts: list[dict] = field(default_factory=list)
    created_at: str = ""

    def status_at(self, at: pd.Timestamp) -> str | None:
        """``None`` before ``instructed_at``, then ``instructed``, ``in_transit`` and ``credited``."""
        at = pd.Timestamp(at)
        if at < pd.Timestamp(self.instructed_at):
            return None
        if at >= pd.Timestamp(self.arrival_at):
            return "credited"
        return "in_transit" if at >= pd.Timestamp(self.accepted_at) else "instructed"


def idempotency_key(partner: str, review_at: pd.Timestamp) -> str:
    return f"{partner}@{pd.Timestamp(review_at).isoformat()}"


def accepted_at(rail: Rail, instruct_at: pd.Timestamp, cal: Calendar) -> pd.Timestamp:
    """When the rail takes the order and the funds leave: at once on 24/7 rails; on business-day
    rails at ``instruct_at`` on a business day before the cutoff, else the next business day 00:00."""
    instruct_at = pd.Timestamp(instruct_at)
    if not rail.business_days_only:
        return instruct_at
    day = instruct_at.date()
    before_cutoff = rail.instruct_cutoff_hour is None or instruct_at.hour < rail.instruct_cutoff_hour
    if cal.is_business_day(day) and before_cutoff:
        return instruct_at
    return pd.Timestamp(cal.add_business_days(day, 1))


class TransferLedger:
    """JSONL file with one line per transfer; the idempotency key is unique."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def read(self) -> list[Transfer]:
        if not self.path.exists():
            return []
        return [Transfer(**json.loads(line)) for line in self.path.read_text().splitlines() if line.strip()]

    def get(self, key: str) -> Transfer | None:
        return next((t for t in self.read() if t.idempotency_key == key), None)

    def statuses(self, at: pd.Timestamp) -> list[dict]:
        """Every transfer with its status at ``at`` (``None`` if instructed later)."""
        return [asdict(t) | {"status": t.status_at(at)} for t in self.read()]

    def instructed_on(self, day: pd.Timestamp, currency: str, partner: str | None = None) -> float:
        """Total instructed in ``currency`` on the calendar day of ``day`` (one partner, or all)."""
        day = pd.Timestamp(day).normalize()
        return float(sum(t.amount for t in self.read() if t.currency == currency
                         and pd.Timestamp(t.instructed_at).normalize() == day
                         and (partner is None or t.partner == partner)))

    def in_transit(self, partner: str, at: pd.Timestamp) -> list[Transfer]:
        """Transfers to ``partner`` instructed before ``at`` and not yet credited at ``at``."""
        at = pd.Timestamp(at)
        return [t for t in self.read() if t.partner == partner and pd.Timestamp(t.instructed_at) < at
                and t.status_at(at) != "credited"]


class SimulatedExecutor:
    """Executes transfers into the ledger, never over the network."""

    def __init__(self, ledger: TransferLedger, cfg: AutonomyConfig, rails: dict[str, Rail], cal: Calendar,
                 rail_cals: dict[str, Calendar] | None = None) -> None:
        self.ledger, self.cfg, self.rails, self.cal = ledger, cfg, rails, cal
        self.rail_cals = rail_cals or {}  # per partner, for rails that move only on business days

    def execute(self, partner: str, rail: str, amount: float, currency: str, review_at: pd.Timestamp,
                forecast_run_id: str, policy_amount: float, limit_applied: str | None = None,
                alerts: list[dict] | None = None) -> tuple[Transfer, bool]:
        """Record the transfer of ``amount`` to ``partner``'s allow-listed account on ``rail``;
        returns ``(transfer, created)``. A key already in the ledger returns that transfer with
        ``created=False`` and sends nothing. Refuses (``ValueError``) when the kill switch is off,
        the amount is not positive, the partner has no allow-listed account on the rail, the
        currency has no limits, or the amount breaks a limit."""
        review_at = pd.Timestamp(review_at)
        key = idempotency_key(partner, review_at)
        existing = self.ledger.get(key)
        if existing is not None:
            return existing, False
        if not self.cfg.enabled:
            raise ValueError("autonomy kill switch is on (enabled: false): nothing is executed")
        if amount <= 0:
            raise ValueError(f"amount must be positive, got {amount}")
        destination = self.cfg.destination(partner, rail)
        if destination is None:
            raise ValueError(f"{partner} has no allow-listed destination on {rail}")
        limits = self.cfg.limits.get(currency)
        if limits is None:
            raise ValueError(f"no autonomy limits for currency {currency}")
        spent_partner = self.ledger.instructed_on(review_at, currency, partner)
        spent_all = self.ledger.instructed_on(review_at, currency)
        if (amount > limits.max_per_transfer or spent_partner + amount > limits.max_per_partner_day
                or spent_all + amount > limits.max_all_partners_day):
            raise ValueError(f"{amount:,.0f} {currency} to {partner} breaks the autonomy limits")
        rail_obj = self.rails[rail]
        transfer = Transfer(
            idempotency_key=key, partner=partner, rail=rail, amount=float(amount), currency=currency,
            destination=destination, instructed_at=review_at.isoformat(),
            accepted_at=accepted_at(rail_obj, review_at, self.rail_cals.get(partner, self.cal)).isoformat(),
            arrival_at=arrival_time(rail_obj, review_at, self.rail_cals.get(partner, self.cal)).isoformat(),
            forecast_run_id=forecast_run_id, policy_amount=float(policy_amount), limit_applied=limit_applied,
            alerts=list(alerts or []), created_at=pd.Timestamp.now(tz="UTC").isoformat(),
        )
        self.ledger.path.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger.path.open("a") as f:
            f.write(json.dumps(asdict(transfer)) + "\n")
        return transfer, True


def read_ledger(path: str | Path) -> list[Transfer]:
    return TransferLedger(path).read()


def ledger_status(path: str | Path, at: pd.Timestamp) -> list[dict]:
    """Every transfer in the ledger at ``path`` with its status at ``at``."""
    return TransferLedger(path).statuses(at)
