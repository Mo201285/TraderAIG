"""Server-side authoritative entitlements (ENGINEERING MAST 28.17).

The control plane enforces decision endpoints against the primary (first)
identity's entitlements. While NO identity is configured the API is in
bootstrap mode and passes (a fresh install has no principal to check);
once a primary identity exists the gate is hard: 403 without the required
entitlement. These tests must reset the process-global identity singleton
around themselves so every other suite keeps seeing the empty store.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient  # noqa: E402

from governance.identity import (  # noqa: E402
    identity,
)

from operations.api import app  # noqa: E402


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_identity():
    users = identity._users
    subs = identity._subscriptions
    audit = identity._audit
    identity._users = {}
    identity._subscriptions = {}
    identity._audit = []
    yield
    identity._users = users
    identity._subscriptions = subs
    identity._audit = audit


@pytest.fixture(autouse=True)
def _stop_cex_engine():
    yield
    try:
        from operations.cex_engine import cex_live_engine
        cex_live_engine.stop()
    except Exception:  # noqa: BLE001
        pass


def _session_for(user_id: str) -> dict:
    """A session for `user_id`, so I4's multi-tenant enforcement is satisfied.

    Issued out of band rather than through `/auth/password` (which refuses to
    bootstrap a credential-less principal once enforcement is on) so a test
    about entitlement resolution does not have to also be a test about the
    login flow.
    """
    from governance.auth import auth as auth_svc
    identity.set_password(user_id, "ent-session-password-123")
    return {"Authorization": f"Bearer {auth_svc.issue(user_id)[0]}"}


def _spawn(client, plan: str, activate: bool):
    resp = client.post("/users", json={
        "email": f"ent-{sys.hash_info.width}-{abs(hash(plan))}@x.co",
        "display_name": "ent-test",
        "plan": plan})
    assert resp.status_code == 201
    user_id = resp.json()["user_id"]
    if activate:
        r = client.post(f"/users/{user_id}/subscription/activate",
                        json={"plan": plan})
        assert r.status_code == 200
    return user_id


# -- gate state -----------------------------------------------------------


def test_bootstrap_mode_reports_inactive(client):
    st = client.get("/entitlements/status").json()
    assert st["enforcement_active"] is False
    assert st["bootstrap"] is True
    assert st["actor"] is None


def test_primary_identity_flips_enforcement_active(client):
    _spawn(client, "institutional", activate=True)
    st = client.get("/entitlements/status").json()
    assert st["enforcement_active"] is True
    assert st["bootstrap"] is False
    assert st["actor"] is not None
    assert st["entitlements"]["can_manage_risk"] is True
    assert st["entitlements"]["can_trade"] is True


# -- bootstrap pass (no identity yet) -------------------------------------


@pytest.mark.parametrize("method,path,payload", [
    ("post", "/portfolio/allocation",
     {"strategy_id": "ent-boot:test", "cap": 0.10}),
    ("delete", "/portfolio/allocation/ent-boot:test", None),
    ("post", "/ops/review/apply",
     {"kind": "promote", "strategy_id": "ent-boot:ghost"}),
])
def test_decode_endpoints_pass_in_bootstrap(client, method, path, payload):
    r = getattr(client, method)(path, json=payload) if payload is not None \
        else getattr(client, method)(path)
    # bootstrap gate must never mask the underlying 404/409 semantics
    assert r.status_code in (200, 400, 404, 409)


def test_cex_engine_start_passes_in_bootstrap(client):
    r = client.post("/cex/engine/start", json={"interval": 15})
    assert r.status_code == 200


# -- hard gate once an identity exists ------------------------------------


def test_free_user_403_on_risk_governance(client):
    _spawn(client, "free", activate=True)
    r = client.post("/portfolio/allocation",
                    json={"strategy_id": "ent-free:test", "cap": 0.10})
    assert r.status_code == 403
    assert "can_manage_risk" in r.json()["detail"]


def test_free_user_403_on_trade_authority(client):
    _spawn(client, "free", activate=True)
    r = client.post("/cex/engine/start", json={"interval": 15})
    assert r.status_code == 403
    assert "can_trade" in r.json()["detail"]


def test_pro_trader_has_trade_but_not_risk_management(client):
    _spawn(client, "pro", activate=True)
    assert client.post("/cex/engine/start", json={"interval": 15}).status_code == 200
    r = client.post("/portfolio/allocation",
                    json={"strategy_id": "ent-pro:test", "cap": 0.10})
    assert r.status_code == 403


def test_institutional_user_grants_both(client):
    _spawn(client, "institutional", activate=True)
    assert client.post("/cex/engine/start", json={"interval": 15}).status_code == 200
    r = client.post("/portfolio/allocation",
                    json={"strategy_id": "ent-inst:test", "cap": 0.10})
    assert r.status_code == 200


def test_risk_policy_endpoint_scopes_to_owner(client):
    uid = _spawn(client, "institutional", activate=True)
    r = client.put(f"/users/{uid}/risk-policy",
                   json={"max_risk_per_trade": 0.02})
    assert r.status_code == 200


def test_explicit_primary_email_selects_the_acting_identity(client, monkeypatch):
    """The acting authority is named explicitly, not inferred from who was
    created first (creation order is not stable across rehydration).

    Two users exist, so slice I4 makes this multi-tenant and enforcement turns
    on; the caller therefore presents the named principal's session, which is
    the shape a real deployment has.
    """
    client.post("/users", json={"email": "first@x.co", "plan": "free"})
    founder = client.post("/users", json={
        "email": "founder@x.co", "plan": "institutional"}).json()["user_id"]
    client.post(f"/users/{founder}/subscription/activate",
                json={"plan": "institutional"})
    monkeypatch.setenv("IDENTITY_PRIMARY_EMAIL", "founder@x.co")

    st = client.get("/entitlements/status",
                    headers=_session_for(founder)).json()

    assert st["actor"] == founder
    assert st["bootstrap"] is False


def test_gate_follows_the_principal_not_the_first_user(client, monkeypatch):
    """First-created user is fully entitled, the named principal is not:
    the gate must deny, which proves it reads the principal.

    Slice I4: multi-tenant, so the named principal authenticates before the
    gate is judged — the 403 that follows is the entitlement one, not auth.
    """
    privileged = client.post("/users", json={
        "email": "privileged@x.co", "plan": "institutional"}).json()["user_id"]
    client.post(f"/users/{privileged}/subscription/activate",
                json={"plan": "institutional"})
    principal = client.post("/users", json={
        "email": "principal@x.co", "plan": "free"}).json()["user_id"]
    client.post(f"/users/{principal}/subscription/activate", json={"plan": "free"})
    monkeypatch.setenv("IDENTITY_PRIMARY_EMAIL", "principal@x.co")

    r = client.post("/portfolio/allocation",
                    json={"strategy_id": "ent-principal:test", "cap": 0.10},
                    headers=_session_for(principal))

    assert r.status_code == 403
    assert "can_manage_risk" in r.json()["detail"]


def test_without_explicit_principal_the_first_user_still_acts(client, monkeypatch):
    monkeypatch.delenv("IDENTITY_PRIMARY_EMAIL", raising=False)
    first = client.post("/users", json={"email": "first-acts@x.co", "plan": "free"}) \
        .json()["user_id"]

    st = client.get("/entitlements/status").json()

    assert st["actor"] == first
