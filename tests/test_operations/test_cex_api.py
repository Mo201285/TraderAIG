"""API smoke tests for the CEX gateway + live engine endpoints (no network)."""

import pytest


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from operations.api import app
    return TestClient(app)


def test_cex_status_endpoint(client):
    resp = client.get("/cex/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["venue"] in {"binance", "okx", "bybit"}
    assert "mode" in body
    assert "locked" in body
    assert "gate_live_allowed" in body


def test_cex_venues_endpoint(client):
    resp = client.get("/cex/venues")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body["available"]) >= {"binance", "okx", "bybit"}
    assert body["selected"] in body["available"]


def test_cex_engine_status_endpoint(client):
    resp = client.get("/cex/engine")
    assert resp.status_code == 200
    body = resp.json()
    assert "venue" in body
    assert "paper" in body
    assert "running" in body
    assert "cycles" in body


def test_cex_engine_start_stop_lifecycle(client):
    """Paper watch start/stop must round-trip through the singleton."""
    resp = client.post("/cex/engine/start", json={"interval": 3600})
    assert resp.status_code == 200
    body = resp.json()
    assert body["started"] is True
    assert body["status"]["running"] is True
    assert body["status"]["paper"] is True

    resp2 = client.post("/cex/engine/stop")
    assert resp2.status_code == 200
    assert resp2.json()["stopped"] is True
    assert resp2.json()["status"]["running"] is False
