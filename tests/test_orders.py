import pytest

from treasury.orders import parse_rules


@pytest.mark.parametrize("text, action, risk, amount", [
    ("Frená los envíos", "pause", None, None),
    ("no mandes más plata", "pause", None, None),
    ("no mandes más de 100 M", "set_cap", None, 100e6),
    ("riesgo medio", "set_risk", 0.95, None),
    ("subí el riesgo", "set_risk", 0.95, None),
    ("sé más conservador", "set_risk", 0.99, None),
    ("Reanudá", "resume", None, None),
    ("mandá 50 millones", "send_now", None, 50e6),
    ("sacá el tope", "clear_cap", None, None),
    ("¿cómo vas?", "status", None, None),
    ("hola", "unknown", None, None),
])
def test_parse_rules(text, action, risk, amount):
    order = parse_rules(text, alpha=0.99)
    assert (order.action, order.risk, order.amount) == (action, risk, amount)
