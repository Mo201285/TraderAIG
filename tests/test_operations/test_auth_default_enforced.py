"""Auth is enforced by default, with a bootstrap exemption (28.19/28.4).

The platform used to ship with `TRADERAIG_AUTH` unset meaning *enforcement off*:
a fresh install answered every request as the acting principal, and the login
screen was a door that did not lock. Enforcement is now ON by default -- an
unset variable no longer means "open" -- while still being opt-out on an
isolated host (`TRADERAIG_AUTH=0`).

Two things make the default honest rather than merely strict:

* **The bootstrap exemption.** With enforcement on and *no identity yet*, there
  is no principal to check a caller against, so the middleware lets the request
  through -- the exact rule `_guard` / `_own` / `owner_scope` already apply. The
  first user is created, and enforcement becomes real the moment a second
  request could be attributed to someone. Without this, a fresh install could
  not create its first user over the API at all.
* **The report matches the gate.** `/system/health` must not say "NOT enforced"
  while the middleware refuses unauthenticated callers; the two are read from
  the same policy so they cannot disagree.

This file pins the default in both directions, the bootstrap boundary, and the
report -- because the failure being guarded against is a security claim that is
not true, not a login that does not work.
"""

import os
import sys
import tempfile

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))

import pytest


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from operations.api import app
    return TestClient(app)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    """No identity or credential may leak between tests here either."""
    from governance.identity import identity

    monkeypatch.delenv("TRADERAIG_AUTH", raising=False)
    monkeypatch.delenv("AUTH_SERVICE_TOKEN", raising=False)
    monkeypatch.delenv("IDENTITY_PRIMARY_EMAIL", raising=False)
    monkeypatch.setenv("TRADERAIG_REVOCATION_FILE",
                       os.path.join(tempfile.mkdtemp(prefix="revocations-"),
                                    "session_revocations.json"))
    users = dict(identity._users)
    subs = dict(identity._subscriptions)
    try:
        yield
    finally:
        identity._users.clear()
        identity._users.update(users)
        identity._subscriptions.clear()
        identity._subscriptions.update(subs)


# ---------------------------------------------------------------------------
# the default itself
# ---------------------------------------------------------------------------

def test_enforcement_is_on_by_default():
    """An unset TRADERAIG_AUTH now means enforced, not open."""
    from governance.auth import AuthService

    assert AuthService.enforcement_enabled() is True


def test_enforcement_can_still_be_turned_off_explicitly(monkeypatch):
    """Opt-out is still available on an isolated host."""
    from governance.auth import AuthService

    for off in ("0", "false", "False", "no", "off", ""):
        monkeypatch.setenv("TRADERAIG_AUTH", off)
        assert AuthService.enforcement_enabled() is False, off


def test_enforcement_on_values_are_honoured(monkeypatch):
    from governance.auth import AuthService

    for on in ("1", "true", "True", "yes", "on"):
        monkeypatch.setenv("TRADERAIG_AUTH", on)
        assert AuthService.enforcement_enabled() is True, on


# ---------------------------------------------------------------------------
# the bootstrap exemption (fresh install)
# ---------------------------------------------------------------------------

def test_first_user_can_be_created_on_a_fresh_enforced_install(client):
    """No identity yet + enforcement on: the first POST /users must succeed."""
    from governance.identity import identity

    identity._users.clear()
    assert client.post("/users", json={"email": "first@x.co"}).status_code == 201


def test_once_a_user_exists_anonymous_writes_are_refused(client):
    """The exemption ends the moment a caller could be attributed (28.19)."""
    from governance.identity import identity

    identity._users.clear()
    assert client.post("/users", json={"email": "first@x.co"}).status_code == 201
    # now a caller exists; an anonymous second write is not the bootstrap case
    res = client.post("/users", json={"email": "second@x.co"})
    assert res.status_code == 401
    assert res.json()["enforcement"] == "TRADERAIG_AUTH=1"


def test_anonymous_reads_are_refused_once_a_user_exists(client):
    """Read gating: the same boundary applies to GET (28.19)."""
    from governance.identity import identity

    identity._users.clear()
    assert client.post("/users", json={"email": "first@x.co"}).status_code == 201
    assert client.get("/users").status_code == 401


def test_reference_reads_stay_open_without_a_session(client):
    """The public product surface belongs to no tenant and stays reachable."""
    from governance.identity import identity

    identity._users.clear()
    assert client.post("/users", json={"email": "first@x.co"}).status_code == 201
    assert client.get("/site").status_code == 200


# ---------------------------------------------------------------------------
# the report matches the gate
# ---------------------------------------------------------------------------

def test_health_reports_enforcement_on_by_default(client):
    from governance.identity import identity

    identity._users.clear()
    # bootstrap request: create the principal so health reflects a real install
    assert client.post("/users", json={"email": "first@x.co"}).status_code == 201
    health = client.get("/system/health").json()
    assert health["auth"]["enforcement_enabled"] is True
    assert health["auth"]["reads_gated"] is True
    # the tenancy report must not contradict the gate
    assert "NOT enforced" not in health["tenancy"]["auth_enforcement"]


def test_health_reports_off_when_explicitly_disabled(client, monkeypatch):
    from governance.identity import identity

    identity._users.clear()
    monkeypatch.setenv("TRADERAIG_AUTH", "0")
    assert client.post("/users", json={"email": "first@x.co"}).status_code == 201
    health = client.get("/system/health").json()
    assert health["auth"]["enforcement_enabled"] is False
    assert "NOT enforced" in health["tenancy"]["auth_enforcement"]


# ---------------------------------------------------------------------------
# launch readiness now sees the hard precondition satisfied
# ---------------------------------------------------------------------------

def test_launch_readiness_auth_check_is_green_by_default():
    """The hard `auth_enforced` precondition is satisfied by the new default."""
    from core.config import settings
    from governance.auth import auth
    from operations.launch import assess

    body = assess(settings, enforcement=auth.enforcement_enabled(),
                  registered_accounts=0)
    checks = {c["id"]: c for c in body["checks"]}
    assert checks["auth_enforced"]["ok"] is True
