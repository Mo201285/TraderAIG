"""HTTP surface for the launch-readiness gate (read-only, evidence-only)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from fastapi.testclient import TestClient

import operations.api as api
from operations.api import app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)  # no lifespan: no server-side startup side effects


def _readiness(client):
    r = client.get("/system/launch-readiness")
    assert r.status_code == 200
    return r.json()


def test_launch_readiness_route_shape(client):
    body = _readiness(client)
    assert body["present"] is True
    assert isinstance(body["ready"], bool)
    assert isinstance(body["blocking"], list)
    assert isinstance(body["checks"], list)
    assert body["is_authorisation"] is False
    assert body["trade_authority"] == "risk/governor.py"
    ids = {c["id"] for c in body["checks"]}
    assert {"auth_enforced", "live_rail_armed", "live_gates_consistent"} <= ids


def test_launch_readiness_matches_registered_route_table(client):
    paths = {r.path for r in api.app.routes}
    assert "/system/launch-readiness" in paths


def test_launch_readiness_read_only(client):
    for c in _readiness(client)["checks"]:
        assert c["severity"] in ("hard", "advisory")


def test_launch_readiness_secrets_never_travel(client, monkeypatch):
    """Key values must never serialize into the payload -- only presence."""
    from types import SimpleNamespace

    from core import config as core_config
    from core.config import settings as real_settings

    mt5 = SimpleNamespace(terminal_path=real_settings.mt5.terminal_path,
                          login=999001, server="MetaQuotes-Demo")
    cex = SimpleNamespace(
        mode="live", live_allowed=True, venue="binance",
        binance_api_key="k-LAUNCH-SECRET-1", binance_api_secret="s-LAUNCH-SECRET-1",
        okx_api_key="", okx_api_secret="", okx_passphrase="",
        bybit_api_key="", bybit_api_secret="")
    pay = SimpleNamespace(
        mode="live", live_allowed=True, provider="stripe",
        stripe_secret_key="sk-live-LAUNCH-SECRET-2", pi_api_key="")
    monkeypatch.setattr(core_config, "settings",
                        SimpleNamespace(mt5=mt5, cex=cex, payments=pay))
    r = client.get("/system/launch-readiness")
    assert r.status_code == 200
    text = r.text
    assert "k-LAUNCH-SECRET-1" not in text
    assert "s-LAUNCH-SECRET-1" not in text
    assert "sk-live-LAUNCH-SECRET-2" not in text
