"""Optional orders to the autonomous agent, in plain Spanish ("frená los envíos", "riesgo medio").

The agent never needs them: they only constrain it. ``parse`` turns a sentence into one ``Order``. With
``ANTHROPIC_API_KEY`` set, Claude reads the sentence (one forced tool call); without it, or if the call
fails, a small keyword parser does. Both return the same structure, so the engine never sees free text.
"""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass

RISK = {"bajo": 0.99, "medio": 0.95, "alto": 0.90}
RISK_ORDER = [0.99, 0.95, 0.90]  # from least to most risk
MODEL = "claude-haiku-5-5"


@dataclass(frozen=True)
class Order:
    action: str  # pause | resume | set_risk | set_cap | clear_cap | send_now | status | unknown
    risk: float | None = None
    amount: float | None = None
    source: str = "rules"


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def _amount(number: str, unit: str | None) -> float:
    n = number.replace(" ", "")
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", n):
        n = n.replace(".", "")
    n = n.replace(",", ".")
    value = float(n)
    return value * 1e6 if unit or value < 10_000 else value


def parse_rules(text: str, alpha: float) -> Order:
    t = _plain(text)
    num = r"\$?\s*(\d[\d.,]*)\s*(m\b|millones|palos)?"
    if re.search(r"(saca|quita|sin)\w*\s+(el\s+)?(tope|limite|maximo)", t):
        return Order("clear_cap")
    if m := re.search(r"(mas de|tope( de)?|maximo( de)?|limite( de)?|hasta)\s*" + num, t):
        return Order("set_cap", amount=_amount(m.group(len(m.groups()) - 1), m.group(len(m.groups()))))
    if m := re.search(r"\bmand\w*\s+" + num, t):
        return Order("send_now", amount=_amount(m.group(1), m.group(2)))
    for word, value in RISK.items():
        if re.search(r"riesgo\s+" + word, t):
            return Order("set_risk", risk=value)
    i = min(range(3), key=lambda k: abs(RISK_ORDER[k] - alpha))
    if re.search(r"conservador|mas segur|baja\w*\s+(el\s+)?riesgo|menos riesgo", t):
        return Order("set_risk", risk=RISK_ORDER[max(0, i - 1)])
    if re.search(r"agresiv|sub\w*\s+(el\s+)?riesgo|mas riesgo|menos plata parada", t):
        return Order("set_risk", risk=RISK_ORDER[min(2, i + 1)])
    if re.search(r"no mand|fren|paus|\bpara\b|parar|deten|stop|no envie", t):
        return Order("pause")
    if re.search(r"segu|reanud|volve|activ|retom|despaus", t):
        return Order("resume")
    if re.search(r"estado|cuanto|como (vas|esta)|saldo|resumen", t):
        return Order("status")
    return Order("unknown")


TOOL = {
    "name": "apply_order",
    "description": "Turn the treasury user's sentence into one order for the autonomous prefunding agent.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["pause", "resume", "set_risk", "set_cap", "clear_cap", "send_now", "status", "unknown"],
                       "description": "pause: stop sending money (keeps forecasting). resume: send again. set_risk: change the risk level. "
                                      "set_cap: max amount per transfer. clear_cap: remove that max. send_now: send an amount now. "
                                      "status: the user asks how things are. unknown: anything else."},
            "risk": {"type": "string", "enum": ["bajo", "medio", "alto"], "description": "For set_risk. Bajo covers a bad day of 1 in 100, medio 1 in 20, alto 1 in 10."},
            "amount_ars": {"type": "number", "description": "For set_cap and send_now, in pesos (\"100 M\" is 100000000)."},
        },
        "required": ["action"],
    },
}


def parse(text: str, alpha: float) -> Order:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return parse_rules(text, alpha)
    try:
        import anthropic

        msg = anthropic.Anthropic().messages.create(
            model=MODEL, max_tokens=300, tools=[TOOL], tool_choice={"type": "tool", "name": "apply_order"},
            system="You map one sentence from a wallet's treasury team (Argentine Spanish) to an order for the agent that "
                   f"prefunds their payment partner. The current risk level covers a bad day at quantile {alpha}.",
            messages=[{"role": "user", "content": text}])
        args = next(b.input for b in msg.content if b.type == "tool_use")
        return Order(args["action"], risk=RISK.get(args.get("risk", "")), amount=args.get("amount_ars"), source="claude")
    except Exception:  # noqa: BLE001 (any API failure falls back to the keyword parser)
        return parse_rules(text, alpha)
