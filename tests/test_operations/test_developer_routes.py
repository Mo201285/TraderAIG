"""The Developer API-token routes over the real app (S10 Developer Platform).

The layer the module tests cannot see: the routes resolve the acting principal,
keep the secret out of every read, and -- the point of the feature -- a
presented token is wired into caller resolution so it acts as its OWNER under the
existing entitlement gate, with scopes as a ceiling. Guarded here:

- the policy surface reports the bounded scopes and the prefix;
- minting needs an acting principal (`409`), returns the secret once, and the
  list/get surfaces never expose the secret or its digest;
- an unknown scope is `400`, an unknown token id is a distinct `404`;
- with enforcement on, a `read`-only token cannot authenticate a mutating
  request (`403`) while a write-scoped token can, and an unauthenticated
  mutation is refused (`401`);
- a token whose owner no longer exists is not a usable caller.
"""

from pathlib import Path
import sys
import time

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from operations.api import app  # noqa: E402
from operations import api as api_mod  # noqa: E402

OPERATOR_PASSWORD = "correct-horse-battery"


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """No principal, enforcement default, and a private token registry."""
    from governance.identity import identity
    from governance.api_tokens import ApiTokenService

    monkeypatch.delenv("TRADERAIG_AUTH", raising=False)
    monkeypatch.delenv("IDENTITY_PRIMARY_EMAIL", raising=False)
    monkeypatch.setenv("TRADERAIG_API_TOKENS_FILE",
                       str(tmp_path / "api_tokens.json"))
    monkeypatch.setattr(api_mod, "api_tokens", ApiTokenService())
    users = dict(identity._users)
    subs = dict(identity._subscriptions)
    try:
        yield
    finally:
        identity._users.clear()
        identity._users.update(users)
        identity._subscriptions.clear()
        identity._subscriptions.update(subs)


def _operator(client, monkeypatch):
    email = f"dev{time.time_ns()}@x.co"
    uid = client.post("/users", json={"email": email}).json()["user_id"]
    monkeypatch.setenv("IDENTITY_PRIMARY_EMAIL", email)
    client.post(f"/users/{uid}/subscription/activate",
                json={"plan": "institutional"})
    client.post("/auth/password", json={"password": OPERATOR_PASSWORD})
    return uid


def test_policy_surface(client):
    r = client.get("/developer/policy")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["prefix"] == "taigdev_"
    assert set(body["scopes"]) == {"read", "trade", "manage_risk"}
    assert body["hashed_at_rest"] is True


def test_mint_needs_a_principal(client):
    from governance.identity import identity

    identity._users.clear()
    identity._subscriptions.clear()
    r = client.post("/developer/tokens", json={"label": "ci"})
    assert r.status_code == 409


def test_mint_list_get_never_expose_the_secret(client, monkeypatch):
    _operator(client, monkeypatch)
    minted = client.post("/developer/tokens",
                         json={"label": "ci", "scopes": ["read"]})
    assert minted.status_code == 200
    body = minted.json()
    token = body["token"]
    assert token.startswith("taigdev_")
    assert "not retrievable" in body["warning"]
    token_id = body["token_id"]

    listed = client.get("/developer/tokens").json()
    assert listed["count"] == 1
    row = listed["tokens"][0]
    assert "token" not in row and "hash" not in row
    assert row["token_id"] == token_id

    got = client.get(f"/developer/tokens/{token_id}").json()
    assert got["token"]["token_id"] == token_id
    assert "token" not in got["token"]
    assert client.get("/developer/tokens/deadbeef").status_code == 404


def test_mint_unknown_scope_is_400(client, monkeypatch):
    _operator(client, monkeypatch)
    r = client.post("/developer/tokens",
                    json={"label": "ci", "scopes": ["root"]})
    assert r.status_code == 400
    assert r.json()["reason"] == "invalid_token_request"


def test_revoke_then_inactive(client, monkeypatch):
    _operator(client, monkeypatch)
    token_id = client.post("/developer/tokens",
                           json={"label": "ci"}).json()["token_id"]
    revoked = client.post(f"/developer/tokens/{token_id}/revoke")
    assert revoked.status_code == 200
    assert revoked.json()["token"]["active"] is False
    assert client.get(f"/developer/tokens/{token_id}").json()["token"]["active"] \
        is False
    assert client.post("/developer/tokens/deadbeef/revoke").status_code == 404


def test_read_token_cannot_mutate_but_write_token_can(client, monkeypatch):
    uid = _operator(client, monkeypatch)
    read_token = api_mod.api_tokens.mint(uid, label="r", scopes=("read",))["token"]
    write_token = api_mod.api_tokens.mint(uid, label="w",
                                          scopes=("trade",))["token"]
    monkeypatch.setenv("TRADERAIG_AUTH", "1")

    read_headers = {"Authorization": f"Bearer {read_token}"}
    write_headers = {"Authorization": f"Bearer {write_token}"}

    # A read-only token is a ceiling that forbids writes outright.
    refused = client.post("/developer/tokens", json={"label": "x"},
                          headers=read_headers)
    assert refused.status_code == 403
    assert "read-only" in refused.json()["detail"]

    # A write-scoped token authenticates a mutation as its owner.
    allowed = client.post("/developer/tokens", json={"label": "x"},
                          headers=write_headers)
    assert allowed.status_code == 200

    # Reads are open and the read token still identifies the owner.
    listed = client.get("/developer/tokens", headers=read_headers)
    assert listed.status_code == 200
    assert listed.json()["count"] == 3


def test_unauthenticated_mutation_is_refused_when_enforcement_on(client,
                                                                 monkeypatch):
    _operator(client, monkeypatch)
    monkeypatch.setenv("TRADERAIG_AUTH", "1")
    r = client.post("/developer/tokens", json={"label": "ci"})
    assert r.status_code == 401


def test_token_without_a_live_owner_is_not_a_caller(client, monkeypatch):
    ghost = api_mod.api_tokens.mint("ghost-user", label="ghost")["token"]
    monkeypatch.setenv("TRADERAIG_AUTH", "1")
    r = client.get("/developer/tokens",
                   headers={"Authorization": f"Bearer {ghost}"})
    assert r.status_code == 409  # reads are open; no principal is resolved
