"""Performance of the aggregated /system/health surface (UPDATE.md §50)."""

import pytest

from operations.api import app

ALLOWED = ("Healthy", "Degraded", "Disconnected", "Error")

COMPONENT_LABELS = (
    "api", "database", "market_data", "ai", "dspy", "governance", "risk",
    "execution", "reconciliation", "learning", "storage",
)


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    return TestClient(app)


def test_system_health_shape(client):
    resp = client.get("/system/health")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["ok"], bool)
    assert body["overall"] in ALLOWED
    assert "generated_at" in body
    for label in COMPONENT_LABELS:
        comp = body["components"][label]
        assert comp["status"] in ALLOWED
        assert isinstance(comp["ok"], bool)
        assert isinstance(comp["detail"], str)
    assert "single authority" in body["governance"]


def test_system_health_every_component_is_consistent(client):
    body = client.get("/system/health").json()
    for label, comp in body["components"].items():
        if comp["status"] == "Healthy":
            assert comp["ok"] is True, label
        elif comp["status"] in ("Disconnected", "Error"):
            assert comp["ok"] is False, label
