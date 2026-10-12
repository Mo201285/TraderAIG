"""S6 XTAIG Economy routes over the real app (row 781).

The read-only policy surface and the governed award route: a passing validation
credits the recorded owner through the one wallet ledger, the amount comes from
the stored report (not the request), and the grant is idempotent.
"""

import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from operations.api import app  # noqa: E402


class _Enum:
    def __init__(self, value):
        self.value = value


class _FakeAsset:
    def __init__(self, *, validation, metadata, stage="candidate",
                 family="ict", asset="XAUUSD"):
        self.validation = validation
        self.metadata = metadata
        self.stage = _Enum(stage)
        self.family = _Enum(family)
        self.asset = asset


class _FakeLayer:
    def __init__(self, assets):
        self._assets = assets

    def asset(self, strategy_id):
        return self._assets.get(strategy_id)


def _passing_report():
    return {
        "strategy_id": "s-1", "asset": "XAUUSD", "passed": True, "samples": 120,
        "win_rate": 0.55, "expected_value": 0.2, "profit_factor": 1.8,
        "max_drawdown": 0.12, "oos_ev": 0.15, "walkforward_wins": 3,
        "walkforward_folds": 4, "monte_carlo_survival": 0.9,
    }


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    from governance.identity import identity
    from governance.payments import payments_service

    monkeypatch.delenv("TRADERAIG_AUTH", raising=False)
    users = dict(identity._users)
    subs = dict(identity._subscriptions)
    ledger = list(payments_service._ledger)
    try:
        yield
    finally:
        identity._users.clear()
        identity._users.update(users)
        identity._subscriptions.clear()
        identity._subscriptions.update(subs)
        payments_service._ledger[:] = ledger


def _operator(client, monkeypatch, plan="institutional"):
    email = f"eco{time.time_ns()}@x.co"
    uid = client.post("/users", json={"email": email}).json()["user_id"]
    monkeypatch.setenv("IDENTITY_PRIMARY_EMAIL", email)
    client.post(f"/users/{uid}/subscription/activate", json={"plan": plan})
    return uid


def test_policy_route_is_read_only(client):
    res = client.get("/economy/research-reward/policy")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["source"] == "research_rewards"
    assert body["is_authorisation"] is False
    assert body["trade_authority"] == "risk/governor.py"


def test_award_requires_the_risk_capability(client, monkeypatch):
    uid = client.post("/users",
                      json={"email": f"eco{time.time_ns()}@x.co"}).json()["user_id"]
    client.post(f"/users/{uid}/subscription/activate", json={"plan": "free"})
    monkeypatch.setattr("operations.api._acting_actor", lambda: uid)
    res = client.post("/economy/research-reward", json={"strategy_id": "s-1"})
    assert res.status_code == 403


def test_award_unknown_strategy_is_404(client, monkeypatch):
    _operator(client, monkeypatch)
    monkeypatch.setattr("operations.api._asset_layer",
                        lambda: _FakeLayer({}))
    res = client.post("/economy/research-reward", json={"strategy_id": "ghost"})
    assert res.status_code == 404


def test_passing_validation_credits_the_owner_wallet_once(client, monkeypatch):
    uid = _operator(client, monkeypatch)
    layer = _FakeLayer({"s-1": _FakeAsset(validation=_passing_report(),
                                          metadata={"owner": uid})})
    monkeypatch.setattr("operations.api._asset_layer", lambda: layer)

    first = client.post("/economy/research-reward", json={"strategy_id": "s-1"})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["granted"] is True
    assert body["user_id"] == uid
    assert body["credits"] > 0
    assert body["wallet_balance"] == body["credits"]
    assert body["is_authorisation"] is False

    wallet = client.get(f"/payments/wallet/{uid}").json()
    assert wallet["earned_usd"] == body["credits"]

    second = client.post("/economy/research-reward", json={"strategy_id": "s-1"})
    assert second.status_code == 200
    assert second.json()["granted"] is False
    assert second.json()["reason"] == "already_credited"
    assert client.get(f"/payments/wallet/{uid}").json()["balance_usd"] \
        == body["credits"]
