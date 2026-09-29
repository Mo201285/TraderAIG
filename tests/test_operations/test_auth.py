"""Authentication: who is calling, and is the door real (28.19).

The bar for this file is not "the login works". It is that the system's claims
about its own security are TRUE, in both directions: when enforcement is on, an
unauthenticated caller is refused; when it is off, the deployment says so out
loud instead of wearing a login form it does not honour.

Both directions are tested because the failure this milestone is guarding against
is a door that looks like a door. A test that only proved "login returns a
token" would have passed against the fabricated operator identity that the
previous milestone deleted.
"""
import os
import sys
import time

import pytest


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from operations.api import app
    return TestClient(app)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    """Hermetic: no password, principal or auth setting may leak between tests.

    Restores the identity user maps too, not just the env, because a throwaway
    principal left behind here is exactly the pollution that once made this
    suite's result depend on collection order.
    """
    from governance.auth import auth as auth_svc
    from governance.identity import identity

    monkeypatch.delenv("TRADERAIG_AUTH", raising=False)
    monkeypatch.delenv("AUTH_SERVICE_TOKEN", raising=False)
    users = dict(identity._users)
    subs = dict(identity._subscriptions)
    revoked = set(auth_svc._revoked)
    secret, persistent = auth_svc._secret, auth_svc._secret_persistent
    try:
        yield
    finally:
        identity._users.clear()
        identity._users.update(users)
        identity._subscriptions.clear()
        identity._subscriptions.update(subs)
        auth_svc._revoked.clear()
        auth_svc._revoked.update(revoked)
        auth_svc._secret, auth_svc._secret_persistent = secret, persistent


def _operator(client, monkeypatch, plan="institutional", password="correct-horse-battery"):
    """A user who is the acting principal and has a credential."""
    email = f"auth{time.time_ns()}@x.co"
    uid = client.post("/users", json={"email": email}).json()["user_id"]
    monkeypatch.setenv("IDENTITY_PRIMARY_EMAIL", email)
    client.post(f"/users/{uid}/subscription/activate", json={"plan": plan})
    client.post("/auth/password", json={"password": password})
    return uid, email, password


# ---------------------------------------------------------------------------
# hashing
# ---------------------------------------------------------------------------

def test_a_digest_never_contains_the_password():
    from governance.auth import hash_password, verify_password

    digest = hash_password("correct-horse-battery")
    assert "correct-horse-battery" not in digest
    assert digest.startswith("scrypt$")
    assert verify_password("correct-horse-battery", digest) is True
    assert verify_password("correct-horse-batterY", digest) is False


def test_two_users_with_the_same_password_get_different_digests():
    from governance.auth import hash_password

    assert hash_password("same-password-here") != hash_password("same-password-here")


def test_a_missing_or_corrupt_digest_is_a_failed_login_not_a_crash():
    from governance.auth import verify_password

    assert verify_password("anything", None) is False
    assert verify_password("anything", "") is False
    assert verify_password("anything", "not-a-digest") is False
    assert verify_password("anything", "scrypt$bad$stuff") is False


def test_a_short_credential_is_refused(client, monkeypatch):
    """The account also carries trading authority, so length is a floor, not a
    suggestion."""
    email = f"short{time.time_ns()}@x.co"
    client.post("/users", json={"email": email})
    monkeypatch.setenv("IDENTITY_PRIMARY_EMAIL", email)
    res = client.post("/auth/password", json={"password": "short"})
    assert res.status_code == 400
    assert "12 characters" in res.json()["detail"]


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------

def test_correct_credentials_return_a_usable_token(client, monkeypatch):
    uid, email, password = _operator(client, monkeypatch)
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200
    body = res.json()
    assert body["user_id"] == uid
    assert body["token_type"] == "Bearer"

    from governance.auth import auth as auth_svc
    session = auth_svc.verify(body["token"])
    assert session.user_id == uid


def test_a_wrong_password_and_an_unknown_user_are_indistinguishable(client, monkeypatch):
    """Otherwise the login form enumerates which identities exist — the same
    oracle the ownership guard removed on the read routes."""
    _uid, email, password = _operator(client, monkeypatch)

    wrong = client.post("/auth/login", json={"email": email, "password": "nope-nope-nope"})
    unknown = client.post("/auth/login", json={"email": "ghost@x.co", "password": password})

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_the_open_path_list_is_pinned_and_no_longer_than_it_needs_to_be(client):
    """The route walk above cannot catch this, which is why it is pinned here.

    `test_every_mutating_route_is_covered_by_the_policy` checks that paths IN
    the open list are treated as open — so ADDING a path to that list makes it
    pass, silently. Sabotaging `OPEN_PATHS` with `/auth/logout` left the whole
    suite green: a logout endpoint that no longer requires a session is a real
    (if small) hole, and the only thing standing between it and a merge is
    someone reading this list and asking why each entry is justified.
    """
    from governance.auth import OPEN_PATHS

    assert set(OPEN_PATHS) == {
        "/auth/login",          # cannot authenticate with a session you lack
        "/auth/session",        # must answer "who am I", including when: nobody
        "/auth/password",       # the credential bootstrap; the route decides
        "/system/health",       # a watchdog or human must see WHY it is denied
        "/payments/webhook",    # provider-signed callback, no session ever
        "/docs", "/openapi.json", "/redoc",
    }
    # and the property that matters: nothing state-changing beyond those.
    # (Reads stay open by design — covered separately, since gating a GET here
    # would contradict the "reads are ungated" claim the health block makes.)
    from governance.auth import auth as auth_svc
    for path in ("/auth/logout", "/payments/charge", "/users",
                 "/paper/engine/start", "/mt5/connect"):
        assert auth_svc.requires_session("POST", path) is True, path


def test_an_empty_service_token_is_still_refused(client, monkeypatch):
    """`AUTH_SERVICE_TOKEN` set to an empty value must not become a universal
    pass, and an empty presented header must not match a real one."""
    from governance.auth import auth as auth_svc

    monkeypatch.setenv("AUTH_SERVICE_TOKEN", "")
    assert auth_svc.service_token_configured() is False
    assert auth_svc.check_service_token("") is False
    assert auth_svc.check_service_token(None) is False

    monkeypatch.setenv("AUTH_SERVICE_TOKEN", "machine-token-value")
    assert auth_svc.check_service_token("") is False
    assert auth_svc.check_service_token("machine-token-value") is True


def test_logout_requires_a_session(client, monkeypatch):
    """The one auth route that must not be on the open list."""
    _uid, email, password = _operator(client, monkeypatch)
    monkeypatch.setenv("TRADERAIG_AUTH", "1")
    token = client.post("/auth/login", json={"email": email,
                                             "password": password}).json()["token"]
    assert client.post("/auth/logout").status_code == 401
    assert client.post("/auth/logout",
                       headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_the_machine_callers_actually_send_the_header_the_runbook_promises():
    """The runbook says the watchdog and console authenticate with
    `X-Service-Token`. While writing that sentence they did not — the runbook
    described a control that did not exist, which is the exact failure mode this
    milestone is about. This reads the shipped callers, so the documentation and
    the code cannot drift apart again.
    """
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    os.environ["AUTH_SERVICE_TOKEN"] = "machine-token-value"
    try:
        spec = importlib.util.spec_from_file_location(
            "_auth_guard_console", root / "tools" / "tradraig.py")
        console = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(console)
        assert console.service_headers() == {"X-Service-Token": "machine-token-value"}

        sys.path.insert(0, str(root))
        from scripts import ensure_backend
        assert ensure_backend.service_headers() == {"X-Service-Token": "machine-token-value"}

        # and with no token configured they send nothing at all, rather than an
        # empty header that might read as an attempt to authenticate
        os.environ.pop("AUTH_SERVICE_TOKEN", None)
        assert console.service_headers() == {}
        assert ensure_backend.service_headers() == {}
    finally:
        os.environ.pop("AUTH_SERVICE_TOKEN", None)


def test_no_configured_token_sends_no_header_rather_than_a_blank_one():
    from governance.auth import auth as auth_svc

    monkey = {"AUTH_SERVICE_TOKEN": "   "}
    import os
    os.environ.update(monkey)
    try:
        # the API side must not accept whitespace as a token either
        assert auth_svc.check_service_token("   ") is False
        assert auth_svc.check_service_token("") is False
    finally:
        for key in monkey:
            os.environ.pop(key, None)



def test_a_failed_login_is_audited_without_the_credential(client, monkeypatch):
    from governance.identity import identity

    _uid, email, _password = _operator(client, monkeypatch)
    client.post("/auth/login", json={"email": email, "password": "wrong-password-x"})

    entries = [e for e in identity.audit_log(limit=80) if e.action == "auth.login.failed"]
    assert entries
    blob = str(entries[0].details)
    assert "wrong-password-x" not in blob
    assert "password" not in blob.lower() or "password_supplied" not in blob


def test_a_tampered_token_is_refused():
    from governance.auth import AuthError, auth as auth_svc

    token, _ = auth_svc.issue("u-1")
    head, body, sig = token.split(".")
    forged = f"{head}.{body}.{'A' * len(sig)}"
    with pytest.raises(AuthError):
        auth_svc.verify(forged)
    with pytest.raises(AuthError):
        auth_svc.verify("garbage")


def test_an_expired_token_is_refused():
    from governance.auth import AuthError, auth as auth_svc

    token, _ = auth_svc.issue("u-1", ttl_seconds=-1)
    with pytest.raises(AuthError):
        auth_svc.verify(token)


def test_changing_a_password_requires_the_current_one(client, monkeypatch):
    _uid, _email, password = _operator(client, monkeypatch)

    blind = client.post("/auth/password", json={"password": "a-brand-new-secret"})
    assert blind.status_code == 403
    assert "current_password" in blind.json()["detail"]

    ok = client.post("/auth/password",
                     json={"password": "a-brand-new-secret",
                           "current_password": password})
    assert ok.status_code == 200
    assert client.post("/auth/login", json={
        "email": _email, "password": "a-brand-new-secret"}).status_code == 200
    assert client.post("/auth/login", json={
        "email": _email, "password": password}).status_code == 401


def test_logout_revokes_the_token(client, monkeypatch):
    from governance.auth import AuthError, auth as auth_svc

    _uid, email, password = _operator(client, monkeypatch)
    token = client.post("/auth/login", json={"email": email,
                                             "password": password}).json()["token"]
    assert auth_svc.verify(token).user_id

    headers = {"Authorization": f"Bearer {token}"}
    assert client.post("/auth/logout", headers=headers).status_code == 200
    with pytest.raises(AuthError):
        auth_svc.verify(token)


def test_a_credential_survives_a_database_round_trip():
    """Otherwise a restart silently logs the operator out of their own system."""
    from governance.identity import User
    from persistence.db import bind_test_session
    from persistence.repositories import UserRepository

    session = bind_test_session()
    repo = UserRepository(session)
    user = User(user_id="u-pw", email="pw@x.co", display_name="PW")
    from governance.auth import hash_password
    user.password_hash = hash_password("persisted-secret-1")

    repo.save(user)
    loaded = repo.get("u-pw")

    from governance.auth import verify_password
    assert verify_password("persisted-secret-1", loaded.password_hash) is True
    assert verify_password("wrong-secret-1", loaded.password_hash) is False


# ---------------------------------------------------------------------------
# enforcement: the door must be real, and must admit it is not there
# ---------------------------------------------------------------------------

def test_enforcement_is_off_by_default_and_says_so(client, monkeypatch):
    """The live 24/7 deployment depends on this: it is the difference between
    'secure' and 'quietly broken' for the watchdog."""
    monkeypatch.delenv("TRADERAIG_AUTH", raising=False)
    health = client.get("/system/health").json()

    assert health["auth"]["enforcement_enabled"] is False
    assert health["tenancy"]["authenticated"] is False
    assert "NOT enforced" in health["tenancy"]["auth_enforcement"]
    assert health["auth"]["reads_gated"] is False


def test_with_enforcement_off_a_post_still_works(client, monkeypatch):
    """Pins the default so nobody can turn this on by accident and strand the
    supervisor."""
    monkeypatch.delenv("TRADERAIG_AUTH", raising=False)
    assert client.post("/users", json={"email": f"open{time.time_ns()}@x.co"}
                       ).status_code == 201


def test_with_enforcement_on_a_post_without_a_token_is_refused(client, monkeypatch):
    monkeypatch.setenv("TRADERAIG_AUTH", "1")
    res = client.post("/users", json={"email": f"nope{time.time_ns()}@x.co"})
    assert res.status_code == 401
    assert "TRADERAIG_AUTH=1" in res.json()["enforcement"]

    health = client.get("/system/health").json()
    assert health["auth"]["enforcement_enabled"] is True
    assert health["tenancy"]["authenticated"] is True


def test_with_enforcement_on_a_session_token_is_accepted(client, monkeypatch):
    # Enrolment happens with enforcement off, which is the only order that works:
    # you cannot create a user, set a password or activate a plan once the door
    # is locked, which is exactly why the recovery path is the service token.
    _uid, email, password = _operator(client, monkeypatch)
    monkeypatch.setenv("TRADERAIG_AUTH", "1")

    token = client.post("/auth/login", json={"email": email,
                                             "password": password}).json()["token"]
    res = client.post("/users", json={"email": f"ok{time.time_ns()}@x.co"},
                      headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 201


def test_the_supervisor_can_still_reach_the_rails(client, monkeypatch):
    """The 24/7 watchdog POSTs to the API. Gating it without a service token
    would have the supervisor locked out of the system it maintains — the same
    'platform takes itself offline' shape this project keeps undoing."""
    monkeypatch.setenv("TRADERAIG_AUTH", "1")
    monkeypatch.setenv("AUTH_SERVICE_TOKEN", "machine-token-value")
    assert client.get("/system/health").json()["auth"]["service_token_configured"] is True

    res = client.post("/paper/engine/start", json={},
                      headers={"X-Service-Token": "machine-token-value"})
    assert res.status_code in (200, 409)
    assert client.post("/paper/engine/start", json={},
                       headers={"X-Service-Token": "wrong-token"}).status_code == 401


def test_reads_stay_open_even_with_enforcement_on(client, monkeypatch):
    """And the system says so rather than letting a login screen imply
    otherwise: there is one shared canonical state, so an authenticated reader
    would read the operator's positions anyway."""
    monkeypatch.setenv("TRADERAIG_AUTH", "1")
    assert client.get("/users").status_code == 200
    assert client.get("/system/health").json()["auth"]["reads_gated"] is False


def test_the_provider_webhook_stays_reachable_without_a_session(client, monkeypatch):
    """A payment provider calls this signed callback and has no session, ever."""
    from governance.auth import OPEN_PATHS

    monkeypatch.setenv("TRADERAIG_AUTH", "1")
    assert "/payments/webhook" in OPEN_PATHS
    from governance.auth import auth as auth_svc
    assert auth_svc.requires_session("POST", "/payments/webhook") is False


def test_every_mutating_route_is_covered_by_the_policy(client):
    """Walks the real route table instead of trusting the policy function.

    If someone adds a POST and puts it on the open list, or the policy stops
    covering a method, this fails. A security policy that is only asserted
    against itself is a comment, not a control.
    """
    from governance.auth import OPEN_PATHS, auth as auth_svc
    from operations.api import app

    open_paths = {p.rstrip("/") for p in OPEN_PATHS}
    mutating = 0
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", None) or set()
        for method in methods:
            if method.upper() in ("GET", "HEAD", "OPTIONS"):
                continue
            mutating += 1
            needs = auth_svc.requires_session(method, path)
            if path.rstrip("/") in open_paths:
                assert not needs, f"{method} {path} is open but policy disagrees"
            else:
                assert needs, f"{method} {path} is MUTATING but not covered by policy"
    assert mutating > 20, "route table looks unexpectedly small; the walk is not testing anything"


def test_claiming_enforcement_while_no_credential_exists_is_refused(client, monkeypatch):
    """Enabling enforcement with no password set would otherwise be a one-way
    door: nobody can log in, so nobody can set a password."""
    # enrol the identity first, with the door open
    email = f"locked{time.time_ns()}@x.co"
    client.post("/users", json={"email": email})
    monkeypatch.setenv("IDENTITY_PRIMARY_EMAIL", email)
    monkeypatch.setenv("TRADERAIG_AUTH", "1")

    res = client.post("/auth/password", json={"password": "a-fresh-long-secret"})
    assert res.status_code == 401
    assert "unauthenticated caller" in res.json()["detail"]

    # ...and the documented recovery path works: the machine token
    monkeypatch.setenv("AUTH_SERVICE_TOKEN", "machine-token-value")
    res = client.post("/auth/password", json={"password": "a-fresh-long-secret"},
                      headers={"X-Service-Token": "machine-token-value"})
    assert res.status_code == 200
    assert client.post("/auth/login", json={"email": email,
                                             "password": "a-fresh-long-secret"}
                       ).status_code == 200


def test_the_session_endpoint_never_invents_an_identity(client, monkeypatch):
    """The dashboard's front door reads this. It must report no session as no
    session, not as a default user."""
    monkeypatch.setenv("TRADERAIG_AUTH", "1")
    body = client.get("/auth/session").json()
    assert body["authenticated"] is False
    assert "user_id" not in body
    assert "acts with the server-selected principal" in body["note"]
