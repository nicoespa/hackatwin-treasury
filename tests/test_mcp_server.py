import asyncio

import pytest

pytest.importorskip("mcp")

from treasury import mcp_server  # noqa: E402


def test_tools_are_registered():
    names = {t.name for t in asyncio.run(mcp_server.server.list_tools())}
    assert names == {"get_status", "get_limits", "forecast", "run_review", "list_transfers", "set_autonomy"}


def test_pause_overrides_autonomy(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_server, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(mcp_server, "_autonomy", lambda: mcp_server.replace(
        mcp_server.load_autonomy(mcp_server.Path("config/policy.yaml")), enabled=not mcp_server._paused()))
    assert mcp_server.set_autonomy(False) == {"paused": True, "executing": False}
    assert mcp_server._paused()
    assert mcp_server.set_autonomy(True) == {"paused": False, "executing": True}


def test_unknown_rail_is_rejected(monkeypatch):
    monkeypatch.setattr(mcp_server, "_rails", lambda: ["stablecoin", "swift"])
    with pytest.raises(ValueError, match="rail must be one of"):
        mcp_server._check_rail("carrier-pigeon")
