import json

from treasury import monitor


def _row(**kw):
    base = {"partner": "bills_aggregator", "currency": "ARS", "status": "executed", "available": 900e6, "in_transit": 0.0,
            "need": 1022e6, "policy_amount": 122e6, "executed_amount": 122e6, "remainder": 0.0, "eta": "2026-10-05T10:00:00"}
    return base | kw


def test_explain_covers_each_outcome():
    assert "Mandó $ 122 M" in monitor.explain(_row())
    capped = monitor.explain(_row(status="capped", policy_amount=578e6, executed_amount=500e6, remainder=78e6))
    assert "tope por envío es $ 500 M" in capped and "avisó por $ 78 M" in capped
    assert "pausado" in monitor.explain(_row(status="held", executed_amount=0.0))
    assert "Alcanzaba" in monitor.explain(_row(status="no_deposit", policy_amount=0.0, executed_amount=0.0))
    assert "No había pronóstico" in monitor.explain(_row(need=None))


def test_state_reads_runs_log(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "RUNS", tmp_path / "runs.jsonl")
    monkeypatch.setattr(monitor, "LEDGER", tmp_path / "ledger.jsonl")
    monkeypatch.setattr(monitor, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(monitor, "SERIES", tmp_path / "series.json")
    assert monitor.state()["runs"] == 0
    run = {"review_at": "2026-10-01T09:00:00", "partners": [_row(), _row(partner="card_network", status="no_deposit",
                                                                           policy_amount=0.0, executed_amount=0.0)]}
    monitor.record_run(run, tmp_path / "runs.jsonl")
    (tmp_path / "state.json").write_text(json.dumps({"paused": True}))
    s = monitor.state()
    assert s["runs"] == 1 and not s["executing"]
    assert [m["name"] for m in s["moves"]] == ["Pago de servicios"]
    assert {a["name"] for a in s["accounts"]} == {"Pago de servicios", "Tarjetas"}
