"""Hard limits and guardrails of the autonomous agent (``config/policy.yaml`` → ``autonomy``).

Limits are per currency (the partner's ``currency``, ``ARS`` when it has none): ``max_per_transfer``,
``max_per_partner_day`` and ``max_all_partners_day`` (calendar day of the review). Each partner pays
only into its allow-listed account per rail (``destinations``); a partner or rail without one is
held. ``enabled: false`` is the kill switch: nothing is executed.

``check`` turns the policy amount into the amount to execute, with an explicit ``Alert`` for every
guardrail that fires:

- kill switch on, forecast missing or older than ``max_forecast_age_hours``, no destination, no
  limits for the currency: hold (execute nothing).
- amount above ``sanity_multiple`` × the partner's trailing 28-day max daily drain: hold, since an
  amount that large more likely comes from a broken forecast than from demand.
- ``p_unresolvable`` above the threshold: execute, and alert (the deposit cannot prevent a shortfall
  before it lands; a human should look).
- amount above the remaining limit: execute up to the limit, rounded down to ``lot_size``, and alert
  with the remainder. Sending nothing would leave the partner short and reject user payments; sending
  the capped amount covers as much as the limits allow and the alert asks a human for the rest.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from treasury.agent.queue import POLICY_YAML


@dataclass(frozen=True)
class Limits:
    max_per_transfer: float
    max_per_partner_day: float
    max_all_partners_day: float


@dataclass(frozen=True)
class AutonomyConfig:
    enabled: bool
    limits: dict[str, Limits]
    destinations: dict[str, dict[str, str]]
    max_forecast_age_hours: float
    sanity_multiple: float

    def destination(self, partner: str, rail: str) -> str | None:
        return self.destinations.get(partner, {}).get(rail)


def load_autonomy(path: str | Path = POLICY_YAML) -> AutonomyConfig:
    raw = dict(yaml.safe_load(Path(path).read_text())["autonomy"])
    raw["limits"] = {cur: Limits(**v) for cur, v in raw["limits"].items()}
    raw["destinations"] = {pid: dict(v) for pid, v in (raw.get("destinations") or {}).items()}
    return AutonomyConfig(**raw)


@dataclass(frozen=True)
class Alert:
    """``action`` is what the agent did: ``hold`` (nothing sent), ``execute`` (sent the policy
    amount) or ``capped`` (sent less than the policy amount)."""

    partner: str
    code: str
    action: str
    message: str
    details: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Verdict:
    amount: float
    limit_applied: str | None
    remainder: float
    alerts: list[Alert]

    @property
    def held(self) -> bool:
        return self.amount <= 0


def money(x: float | None, currency: str) -> str:
    """Spanish separators, in millions from one million up (``1.234,5 M ARS``), else whole units
    (``350.000 USD``); ``s/d`` when missing."""
    if x is None:
        return "s/d"
    big = abs(x) >= 1e6
    text = f"{x / 1e6:,.1f}" if big else f"{x:,.0f}"
    text = text.replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{text} M {currency}" if big else f"{text} {currency}"


def floor_to_lot(amount: float, lot_size: float) -> float:
    return float(lot_size * math.floor(round(amount / lot_size, 9))) if amount > 0 else 0.0


def check(cfg: AutonomyConfig, *, partner: str, rail: str, currency: str, policy_amount: float,
          p_unresolvable: float | None, forecast_age_hours: float | None, trailing_max_drain: float,
          spent_partner_today: float, spent_all_today: float, lot_size: float, p_threshold: float) -> Verdict:
    """The amount to execute for ``partner`` and the alerts raised (see the module docstring).
    ``forecast_age_hours=None`` means the forecast is missing; ``policy_amount <= 0`` executes
    nothing and raises only the forecast and kill-switch alerts."""

    def hold(code: str, message: str, **details) -> Verdict:
        return Verdict(0.0, None, max(policy_amount, 0.0), [Alert(partner, code, "hold", message, details)])

    if not cfg.enabled:
        return hold("kill_switch", "Kill switch activo (autonomy.enabled: false): no se ejecuta nada.")
    if forecast_age_hours is None:
        return hold("forecast_missing", "Falta el pronóstico para la ventana de la decisión: retenido.")
    if forecast_age_hours > cfg.max_forecast_age_hours:
        return hold("forecast_stale", f"Pronóstico de hace {forecast_age_hours:.0f} h (máximo "
                    f"{cfg.max_forecast_age_hours:.0f} h): retenido.", age_hours=forecast_age_hours)
    if policy_amount <= 0:
        return Verdict(0.0, None, 0.0, [])
    if cfg.destination(partner, rail) is None:
        return hold("no_destination", f"Sin cuenta destino habilitada para {partner} en {rail}: retenido.")
    limits = cfg.limits.get(currency)
    if limits is None:
        return hold("no_limits", f"Sin límites de autonomía para {currency}: retenido.")
    bound = cfg.sanity_multiple * max(trailing_max_drain, 0.0)
    if policy_amount > bound:
        return hold("sanity_bound", f"Monto {money(policy_amount, currency)} supera {cfg.sanity_multiple:g}× el máximo "
                    f"drenaje diario de 28 días ({money(bound, currency)}): retenido, revisar el pronóstico.",
                    bound=bound, trailing_max_drain=trailing_max_drain)
    alerts = []
    if p_unresolvable is not None and p_unresolvable > p_threshold:
        alerts.append(Alert(partner, "p_unresolvable", "execute", f"p_unresolvable {p_unresolvable:.1%} > "
                            f"{p_threshold:.0%}: el depósito puede llegar tarde; ejecutado, revisar.",
                            {"p_unresolvable": p_unresolvable, "threshold": p_threshold}))
    remaining = {
        "max_per_transfer": limits.max_per_transfer,
        "max_per_partner_day": limits.max_per_partner_day - spent_partner_today,
        "max_all_partners_day": limits.max_all_partners_day - spent_all_today,
    }
    binding = min(remaining, key=remaining.get)
    if policy_amount <= remaining[binding]:
        return Verdict(float(policy_amount), None, 0.0, alerts)
    amount = floor_to_lot(remaining[binding], lot_size)
    remainder = float(policy_amount - amount)
    action = "capped" if amount > 0 else "hold"
    alerts.append(Alert(partner, "limit_capped", action, f"Tope {binding}: se ejecutan {money(amount, currency)} de "
                        f"{money(policy_amount, currency)}; faltan {money(remainder, currency)}, requiere decisión humana.",
                        {"limit": binding, "remaining": remaining[binding], "remainder": remainder}))
    return Verdict(amount, binding, remainder, alerts)
