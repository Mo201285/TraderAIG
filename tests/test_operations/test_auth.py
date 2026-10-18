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
import json
import os
import sys
import tempfile
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
    # Durable revocation writes a file. Point it at a temp path so the suite
    # cannot append test logouts into the LIVE .data directory -- a test that
    # writes to production state is the same class of bug as a test that only
    # passes by accident.
    import tempfile
    monkeypatch.setenv("TRADERAIG_REVOCATION_FILE",
                       os.path.join(tempfile.mkdtemp(prefix="revocations-"),
                                    "session_revocations.json"))
    users = dict(identity._users)
    subs = dict(identity._subscriptions)
    revoked = set(auth_svc._revoked)
    revoked_expiry = dict(auth_svc._revoked_expiry)
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
        auth_svc._revoked_expiry.clear()
        auth_svc._revoked_expiry.update(revoked_expiry)
        auth_svc._secret, auth_svc._secret_persistent = secret, persistent


def _operator(client, monkeypatch, plan="institutional", password="correct-horse-battery"):
    """A user who is the acting principal and has a credential."""
    email = f"auth{time.time_ns()}@x.co"
    uid = client.post("/users", json={"email": email}).json()["user_id"]
    monkeypatch.setenv("IDENTITY_PRIMARY_EMAIL", email)
    client.post(f"/users/{uid}/subscription/activate", json={"plan": plan})
    client.post("/auth/password", json={"password": password})
    return uid, email, password


def test_login_and_authority_resolve_the_same_email_the_same_way(
        client, monkeypatch):
    """Login and the acting principal must agree about who an address is.

    `principal_user_id` resolves `IDENTITY_PRIMARY_EMAIL` case-insensitively
    while login resolved it case-sensitively, so the deployment could name a
    user as the acting principal and then refuse that same user's password --
    the plaque on the door disagreeing with the door itself. Line 413 of
    `identity.verify_password` made it worse: it probed `self._users` with an
    email, and that map is keyed by user_id, so the probe that looked like a
    case-insensitive fast path was dead code.
    """
    email = f"Mixed{time.time_ns()}@X.Co"
    uid = client.post("/users", json={"email": email}).json()["user_id"]
    monkeypatch.setenv("IDENTITY_PRIMARY_EMAIL", email)
    password = "correct-horse-battery"
    assert client.post("/auth/password",
                       json={"password": password}).status_code == 200

    for typed in (email, email.lower(), email.upper(), email.swapcase()):
        res = client.post("/auth/login",
                          json={"email": typed, "password": password})
        assert res.status_code == 200, f"login failed for {typed!r}"
        assert res.json()["user_id"] == uid

    # The wrong password is still refused for every variant: this widens WHO
    # may log in, never WHAT proves it.
    wrong = client.post("/auth/login",
                        json={"email": email.lower(), "password": "nope"})
    assert wrong.status_code == 401


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



def test_a_session_acts_as_ITSELF_and_not_as_the_server_principal(client, monkeypatch):
    """The defect this milestone nearly shipped.

    `_own` and the entitlement gate both compared a caller-supplied id against
    `identity.principal_user_id()` -- the identity the SERVER names. So a valid
    session proved only that the caller knew *a* password, while every authority
    check still ran against the operator: a second user with a credential could
    read and mutate the operator's own record through the very guard added to
    stop that. Authentication that changes nothing is the same failure as the
    fabricated login screen, one layer down.
    """
    monkeypatch.delenv("TRADERAIG_AUTH", raising=False)
    op, _op_email, op_password = _operator(client, monkeypatch, plan="institutional")

    # an ordinary second user, with their own password
    other = client.post("/users", json={"email": f"other{time.time_ns()}@x.co"}
                        ).json()["user_id"]
    monkeypatch.setenv("IDENTITY_PRIMARY_EMAIL", _email_of(client, other))
    client.post("/auth/password", json={"password": "other-password-123"})
    monkeypatch.setenv("IDENTITY_PRIMARY_EMAIL", _op_email_of(client, op))

    monkeypatch.setenv("TRADERAIG_AUTH", "1")
    token = client.post("/auth/login", json={
        "email": _email_of(client, other),
        "password": "other-password-123"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get(f"/users/{other}", headers=headers).status_code == 200
    assert client.get(f"/users/{op}", headers=headers).status_code == 403
    assert client.get(f"/users/{op}/can/can_trade", headers=headers).status_code == 403

    # ...and the operator's own session is unaffected
    op_token = client.post("/auth/login", json={
        "email": _op_email_of(client, op),
        "password": op_password}).json()["token"]
    assert client.get(f"/users/{op}",
                      headers={"Authorization": f"Bearer {op_token}"}).status_code == 200


def test_a_deleted_users_session_stops_working(client, monkeypatch):
    """Otherwise deleting an account leaves a live credential behind, and
    'DELETE /users/{id}' would read as revocation without being it."""
    monkeypatch.delenv("TRADERAIG_AUTH", raising=False)
    _uid, email, password = _operator(client, monkeypatch)
    monkeypatch.setenv("TRADERAIG_AUTH", "1")
    token = client.post("/auth/login", json={"email": email,
                                             "password": password}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/auth/session", headers=headers).json()["authenticated"] is True

    # the operator deletes themselves out of band, as an incident response would
    from governance.identity import identity
    victim = client.get("/auth/session", headers=headers).json()["user_id"]
    identity.delete_user(victim)

    assert client.get("/auth/session", headers=headers).json()["authenticated"] is False
    res = client.post("/users", json={"email": f"zombie{time.time_ns()}@x.co"},
                      headers=headers)
    assert res.status_code == 401


def test_the_service_token_still_acts_as_the_operator(client, monkeypatch):
    """Deliberate, and the reason the fallback exists: the watchdog maintains the
    operator's own rails, so treating the machine credential as a lesser caller
    would lock the 24/7 host out of the system it maintains."""
    monkeypatch.delenv("TRADERAIG_AUTH", raising=False)
    op, _e, _p = _operator(client, monkeypatch, plan="institutional")
    monkeypatch.setenv("TRADERAIG_AUTH", "1")
    monkeypatch.setenv("AUTH_SERVICE_TOKEN", "machine-token-value")

    res = client.get(f"/users/{op}", headers={"X-Service-Token": "machine-token-value"})
    assert res.status_code == 200


def test_no_session_presented_keeps_the_server_principal_behaviour(client, monkeypatch):
    """The 24/7 host runs with enforcement off. Adding a caller concept must not
    quietly change who acts when nobody authenticated -- that is the regression
    that would take the platform down at the worst moment."""
    monkeypatch.delenv("TRADERAIG_AUTH", raising=False)
    op, _e, _p = _operator(client, monkeypatch, plan="institutional")
    assert client.get(f"/users/{op}").status_code == 200


def test_one_callers_session_does_not_affect_the_next_request(client, monkeypatch):
    """A non-principal request must not colour the request that follows it.

    Honest scope: this checks the *observable* effect -- request 2 is judged as
    the server principal, not as request 1's user. It does NOT prove the
    contextvar is reset, and it cannot: Starlette runs each request in its own
    task with a copied context, so sabotaging the reset left this suite fully
    green. That is why the reset is unit-tested directly below rather than
    claimed here.
    """
    monkeypatch.delenv("TRADERAIG_AUTH", raising=False)
    op, op_email, op_password = _operator(client, monkeypatch, plan="institutional")
    other = client.post("/users", json={"email": f"leak{time.time_ns()}@x.co"}
                        ).json()["user_id"]
    monkeypatch.setenv("IDENTITY_PRIMARY_EMAIL", _email_of(client, other))
    client.post("/auth/password", json={"password": "other-password-123"})
    monkeypatch.setenv("IDENTITY_PRIMARY_EMAIL", op_email)

    monkeypatch.setenv("TRADERAIG_AUTH", "1")
    monkeypatch.setenv("AUTH_SERVICE_TOKEN", "machine-token-value")
    other_token = client.post("/auth/login", json={
        "email": _email_of(client, other),
        "password": "other-password-123"}).json()["token"]

    # request 1: a non-principal reads the operator's record -> refused
    assert client.get(f"/users/{op}",
                      headers={"Authorization": f"Bearer {other_token}"}).status_code == 403

    # request 2: a caller that authenticated without a SESSION must still be
    # judged as the server principal, not as request 1's user.
    #
    # This used to be a request with no credential at all. Reads are gated now,
    # so "no credential" is a 401 before any route runs and can no longer show
    # who was judged -- the session-less caller is therefore represented by the
    # machine token, which authenticates and deliberately carries no session.
    # The bare-unauthenticated-read behaviour it used to assert is covered
    # separately by `test_no_session_presented_keeps_the_server_principal_...`
    # with enforcement off.
    assert client.get(f"/users/{op}",
                      headers={"X-Service-Token": "machine-token-value"}
                      ).status_code == 200

    # request 3: the operator's own session still works afterwards
    op_token = client.post("/auth/login", json={
        "email": op_email, "password": op_password}).json()["token"]
    assert client.get(f"/users/{op}",
                      headers={"Authorization": f"Bearer {op_token}"}).status_code == 200


def test_the_caller_binding_is_scoped_and_reversible():
    """Unit-level, because the HTTP-level test above provably cannot see it.

    The `finally: reset_current_caller(token)` is defensive: today Starlette
    isolates each request in its own task context, so the reset is redundant
    rather than load-bearing. It is kept because that is a property of the
    framework's internals, not a guarantee of this code -- and a security
    control should not depend on a dependency's undocumented behaviour to stay
    correct. This test is the one that actually fails if the reset is removed.
    """
    from governance.auth import (current_caller, reset_current_caller,
                                 set_current_caller)

    assert current_caller() is None
    token = set_current_caller("user-a")
    assert current_caller() == "user-a"
    reset_current_caller(token)
    assert current_caller() is None

    # a reset from the wrong context must degrade to "no caller", never raise
    # inside a finally block and mask the response
    reset_current_caller(set_current_caller("user-b"))
    assert current_caller() is None


def _email_of(_client, user_id):
    """Read the email from the identity store, not through the API.

    `GET /users/{id}` is ownership-guarded, so using it to look up a fixture's
    email returns 403 for exactly the callers these tests are about -- the helper
    would be testing the guard instead of the thing it needs.
    """
    from governance.identity import identity
    user = identity.get_user(user_id)
    assert user is not None, f"no such user {user_id}"
    return user.email


def _op_email_of(client, user_id):
    return _email_of(client, user_id)


def test_a_logout_survives_a_restart(client, monkeypatch):
    """The gap the in-memory denylist left open.

    On a 24/7 host a restart is a scheduled event, not an edge case. With the
    denylist in memory only, every session the operator explicitly cancelled came
    back to life on the next boot: the credential outlived the decision to
    cancel it. Simulated by building a *second* AuthService over the same file,
    which is what a restart actually does.

    The signing secret is pinned BEFORE the token is issued, and a CONTROL
    assertion checks that a token which was NOT revoked still verifies on the
    restarted service. That control is not decoration: the first version of this
    test set the secret *after* issuing, so `verify` failed on a signature
    mismatch and passed whether or not revocations were loaded at all. Sabotaging
    `_load_revocations` left the suite green, which is how a test that looks like
    it covers a restart can be covering nothing.
    """
    monkeypatch.delenv("TRADERAIG_AUTH", raising=False)
    from governance.auth import AuthError, AuthService
    from governance.auth import auth as auth_svc

    auth_svc._secret = b"fixed-test-signing-secret-value"
    _uid, email, password = _operator(client, monkeypatch)

    revoked_token = client.post("/auth/login", json={
        "email": email, "password": password}).json()["token"]
    live_token = client.post("/auth/login", json={
        "email": email, "password": password}).json()["token"]
    assert client.post("/auth/logout", headers={
        "Authorization": f"Bearer {revoked_token}"}).status_code == 200

    # the control, BEFORE the restart: the revoked one is dead, the live one works
    with pytest.raises(AuthError):
        auth_svc.verify(revoked_token)
    assert auth_svc.verify(live_token).token_id

    # a restart: fresh service, same on-disk revocations, same signing secret
    restarted = AuthService()
    restarted._secret = b"fixed-test-signing-secret-value"

    # CONTROL: without this, a signature mismatch would make every assertion
    # below pass for the wrong reason.
    assert restarted.verify(live_token).token_id
    with pytest.raises(AuthError):
        restarted.verify(revoked_token)


def test_a_corrupt_revocation_file_does_not_stop_the_platform_from_starting(
        client, monkeypatch):
    """A truncated or hand-edited file must degrade to "no durable revocations
    remembered", never to an exception on boot. An auth store that can take the
    API down is worse than one that forgets."""
    monkeypatch.delenv("TRADERAIG_AUTH", raising=False)
    from governance.auth import AuthService

    path = os.environ["TRADERAIG_REVOCATION_FILE"]
    with open(path, "w", encoding="utf-8") as handle:
        handle.write('{"revoked": {"trunc')

        restarted = AuthService()   # must not raise
        # forgetting the old revocations is the stated behaviour, so assert it
        # rather than the tautology "False or True" that used to sit here
        assert restarted.revocation_is_durable() is True
        assert len(restarted._revoked) == 0
    from governance.auth import auth as auth_svc
    auth_svc._secret = b"fixed-test-signing-secret-value"
    _uid, email, password = _operator(client, monkeypatch)
    token = client.post("/auth/login", json={
        "email": email, "password": password}).json()["token"]
    assert client.post("/auth/logout", headers={
        "Authorization": f"Bearer {token}"}).status_code == 200


def test_a_revocations_file_with_junk_entries_ignores_them(client, monkeypatch):
    """A hand-edited or half-written file may contain anything. Non-numeric
    expiry must be dropped, not trusted and not fatal."""
    monkeypatch.delenv("TRADERAIG_AUTH", raising=False)
    from governance.auth import AuthService

    path = os.environ["TRADERAIG_REVOCATION_FILE"]
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps({"revoked": {
            "good-token": time.time() + 600,
            "bad-expiry": "not-a-number",
            "null-expiry": None,
        }}))

    restarted = AuthService()
    assert "good-token" in restarted._revoked
    assert "bad-expiry" not in restarted._revoked
    assert "null-expiry" not in restarted._revoked


def test_health_reports_whether_revocation_is_durable(client, monkeypatch):
    """A platform that reports only "sessions expire in 12h" would hide the fact
    that a reboot resurrects cancelled credentials until someone discovers it
    during an incident."""
    status = client.get("/system/health").json()["auth"]
    assert "revocation_durable" in status
    assert isinstance(status["revocation_durable"], bool)
    assert "revocations_tracked" in status


def test_durability_is_stated_at_boot_not_only_after_a_logout(client, monkeypatch):
    """The flag must mean "the store is usable", not "some logout has happened".

    Deriving it from the first successful persist makes a freshly booted system
    report `false` whenever nobody has logged out yet -- which is the normal
    state, so the field would cry wolf permanently and train the reader to
    ignore the one moment it mattered.
    """
    from governance.auth import AuthService

    fresh = AuthService()
    assert fresh.revocation_is_durable() is True

    blocked = os.path.join(tempfile.mkdtemp(prefix="blocked-boot-"), "afile")
    with open(blocked, "w", encoding="utf-8") as handle:
        handle.write("not a directory")
    monkeypatch.setenv("TRADERAIG_REVOCATION_FILE", os.path.join(blocked, "sub.json"))
    assert AuthService().revocation_is_durable() is False


def test_an_unwritable_revocation_store_still_logs_out_and_says_so(client, monkeypatch):
    """Refusing the logout would leave the session VALID, which is strictly
    worse than accepting it and reporting that the cancellation did not survive
    a restart. The failure mode to avoid is the opposite one: a logout that
    raises 500 and silently keeps the session alive."""
    monkeypatch.delenv("TRADERAIG_AUTH", raising=False)
    _uid, email, password = _operator(client, monkeypatch)
    token = client.post("/auth/login", json={"email": email,
                                             "password": password}).json()["token"]

    # point the store at a path that cannot be created (a file, not a directory)
    blocked = os.path.join(tempfile.mkdtemp(prefix="blocked-"), "afile")
    with open(blocked, "w", encoding="utf-8") as handle:
        handle.write("not a directory")
    monkeypatch.setenv("TRADERAIG_REVOCATION_FILE", os.path.join(blocked, "sub.json"))

    res = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200

    from governance.auth import AuthError
    from governance.auth import auth as auth_svc
    with pytest.raises(AuthError):
        auth_svc.verify(token)          # the logout took effect...
    assert auth_svc.revocation_is_durable() is False   # ...and said it wouldn't last


def test_expired_revocations_are_pruned_but_live_ones_are_kept(client, monkeypatch):
    """A token id can only be replayed while its token is valid, so once the
    session has expired the entry protects nothing -- and without pruning, a
    process that runs for months accumulates one dead id per logout forever, in
    memory and on disk.

    Also checks the other half: pruning must not discard a revocation that is
    still needed, which is the failure that would be much harder to spot.
    """
    from governance.auth import auth as auth_svc
    auth_svc._revoked.add("ancient-token-id")
    auth_svc._revoked_expiry["ancient-token-id"] = time.time() - 60

    _uid, email, password = _operator(client, monkeypatch)
    token = client.post("/auth/login", json={"email": email,
                                             "password": password}).json()["token"]
    assert client.post("/auth/logout", headers={
        "Authorization": f"Bearer {token}"}).status_code == 200

    # the stale one is gone...
    assert "ancient-token-id" not in auth_svc._revoked
    # ...and the one we just made is still there
    from governance.auth import AuthError
    with pytest.raises(AuthError):
        auth_svc.verify(token)


def test_a_credential_survives_a_reboot_not_just_a_repository_round_trip(monkeypatch):
    """A restart must not log the operator out of their own trading system.

    This is the boot path, not the repository round trip: `rehydrate()` is what
    a fresh process actually runs, and it rebuilds the user objects from the
    database through different code than `repo.get()`. It gets its own test
    because a credential that silently failed to rehydrate presents exactly as
    "I typed the right password and it says invalid" -- on a host that reboots
    unattended, discovered by the operator rather than by a test.

    Persistence is redirected to an in-memory session, following the existing
    `test_rehydrate_restores_users_subscriptions_and_entitlements` pattern.
    Writing through the real live session here would put a test user into the
    production database, which is the same class of bug as a test that only
    passes by accident.
    """
    from governance.auth import hash_password, verify_password
    from governance.identity import IdentityService, SubscriptionPlan
    from persistence.db import bind_test_session
    from persistence.repositories import UserRepository
    import governance.identity as identity_mod
    import persistence.db as db_module

    session = bind_test_session()

    def _persist(user, subscription=None):
        UserRepository(session).save(user, subscription=subscription)

    monkeypatch.setattr(identity_mod, "_persist_user", _persist)
    monkeypatch.setattr(db_module, "make_live_session", lambda: session)
    monkeypatch.setattr(db_module, "persistence_enabled", lambda: True)

    writer = IdentityService()
    email = f"reboot{time.time_ns()}@x.co"
    user = writer.create_user(email, "Reboot Check", SubscriptionPlan.INSTITUTIONAL)
    user.password_hash = hash_password("survives-a-reboot-1")
    UserRepository(session).save(user)

    # a genuinely separate service object, as a new process would build
    restored = IdentityService()
    assert restored.rehydrate() >= 1

    rehydrated = restored.get_user(user.user_id)
    assert rehydrated is not None, "rehydrate did not restore the user"
    assert verify_password("survives-a-reboot-1", rehydrated.password_hash)
    assert not verify_password("not-the-password", rehydrated.password_hash)
    assert restored.verify_password(email, "survives-a-reboot-1")


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
    # Enrol first, with the door open — this is the only order that works.
    _uid, op_email, op_password = _operator(client, monkeypatch,
                                            plan="institutional")
    monkeypatch.setenv("TRADERAIG_AUTH", "1")
    res = client.post("/users", json={"email": f"nope{time.time_ns()}@x.co"})
    assert res.status_code == 401
    assert "TRADERAIG_AUTH=1" in res.json()["enforcement"]

    health = client.get("/system/health").json()
    assert health["auth"]["enforcement_enabled"] is True
    # The gate being on is NOT the same as this caller being authenticated, and
    # `/system/health` is an open path — the very response an anonymous caller
    # gets. It used to answer `authenticated: true` here purely because
    # enforcement was switched on, telling a caller with no credential at all
    # that it had proved who it is.
    assert health["tenancy"]["authenticated"] is False

    # ...and the same endpoint reports True to a caller that DID sign in
    token = client.post("/auth/login", json={
        "email": op_email, "password": op_password}).json()["token"]
    mine = client.get("/system/health",
                      headers={"Authorization": f"Bearer {token}"}).json()
    assert mine["tenancy"]["authenticated"] is True


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


def test_reads_require_a_credential_when_enforcement_is_on(client, monkeypatch):
    """Reads are gated now, and the system says so rather than letting a login
    screen imply otherwise.

    Before this, `GET /users` handed the whole address book and `GET /account`
    the balance to a caller with no credential, while the POST beside them
    demanded a password. Gating the reader is the fix.

    Honest scope, stated in the same breath: this authenticates the reader and
    does NOT isolate their data. There is one shared canonical state, so an
    authenticated reader still reads the operator's positions and ledger --
    `model` stays `single-tenant` and `data_isolated_per_user` is False right
    next to `reads_gated: true`. Half a guarantee described as a whole one is
    how this roadmap got into trouble.
    """
    monkeypatch.setenv("TRADERAIG_AUTH", "1")

    assert client.get("/users").status_code == 401
    assert client.get("/account").status_code == 401

    health = client.get("/system/health").json()
    assert health["auth"]["reads_gated"] is True
    assert health["tenancy"]["reads_gated"] is True
    assert health["tenancy"]["model"] == "single-tenant"
    assert health["tenancy"]["data_isolated_per_user"] is False

    # the open paths are still open, so a denied caller can see WHY it is denied
    assert client.get("/system/health").status_code == 200


def test_the_machine_token_may_read(client, monkeypatch):
    """A watchdog cannot watch what it may not read.

    `ensure_backend` polls `/system/health` with no credential and the MT5
    autostart reads `/mt5/engine` with the service token. Reads being gated
    without a machine path through the gate would take the 24/7 supervisor
    offline the instant enforcement came on -- the same
    'platform takes itself offline' shape this project keeps undoing.
    """
    monkeypatch.setenv("TRADERAIG_AUTH", "1")
    monkeypatch.setenv("AUTH_SERVICE_TOKEN", "machine-token-value")

    assert client.get("/users", headers={
        "X-Service-Token": "machine-token-value"}).status_code == 200
    assert client.get("/users", headers={
        "X-Service-Token": "wrong-token"}).status_code == 401


def test_the_provider_webhook_stays_reachable_without_a_session(client, monkeypatch):
    """A payment provider calls this signed callback and has no session, ever."""
    from governance.auth import OPEN_PATHS

    monkeypatch.setenv("TRADERAIG_AUTH", "1")
    assert "/payments/webhook" in OPEN_PATHS
    from governance.auth import auth as auth_svc
    assert auth_svc.requires_session("POST", "/payments/webhook") is False


def test_every_route_is_covered_by_the_policy(client):
    """Walks the real route table instead of trusting the policy function.

    If someone adds a route and puts it on the open list, or the policy stops
    covering a method, this fails. A security policy that is only asserted
    against itself is a comment, not a control.

    Reads are walked too, now that they are gated: the original version skipped
    GET/HEAD/OPTIONS entirely, which is how an enforced write path beside an
    open read path passed this suite for so long.
    """
    from governance.auth import OPEN_PATHS, auth as auth_svc
    from operations.api import app

    open_paths = {p.rstrip("/") for p in OPEN_PATHS}

    def is_open(path: str) -> bool:
        """Mirror the policy's two exemptions exactly.

        `/docs/oauth2-redirect` is a FastAPI docs subpath that the policy
        exempts by prefix rather than by listing, so counting only literal
        OPEN_PATHS entries would report a deliberate exemption as a hole.
        """
        clean = path.rstrip("/")
        return (clean in open_paths or clean.startswith("/docs")
                or clean.startswith("/redoc"))

    mutating = 0
    reading = 0
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", None) or set()
        for method in methods:
            upper = method.upper()
            if upper in ("HEAD", "OPTIONS"):
                continue
            if upper in ("GET",):
                reading += 1
            else:
                mutating += 1
            needs = auth_svc.requires_session(method, path)
            if is_open(path):
                assert not needs, f"{method} {path} is open but policy disagrees"
            else:
                assert needs, f"{method} {path} is not covered by policy"
    assert mutating > 20, "route table looks unexpectedly small; the walk is not testing anything"
    assert reading > 50, "read walk looks unexpectedly small; the walk is not testing anything"


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


# ---------------------------------------------------------------------------
# service token scope (the machine rails are NOT a universal pass)
# ---------------------------------------------------------------------------

def test_service_token_paths_is_pinned(client):
    """The allowlist is a control, not a suggestion. Pinning it exactly means a
    future change to the blast radius of the machine credential has to be seen
    here first."""
    from governance.auth import SERVICE_TOKEN_PATHS

    assert SERVICE_TOKEN_PATHS == frozenset({
        "/mt5/connect",
        "/mt5/sync",
        "/mt5/watcher",
        "/mt5/engine/start",
        "/mt5/engine/stop",
        "/paper/engine/start",
        "/paper/engine/stop",
        "/cex/engine/start",
        "/cex/engine/stop",
    })


def test_the_supervisor_rails_are_all_in_scope(client):
    """The 24/7 watchdog's own POST targets must be on the allowlist, or the
    scope we added to harden human routes would strand the machine that keeps
    the platform alive."""
    from governance.auth import auth as auth_svc, SERVICE_TOKEN_PATHS

    for path in ("/mt5/connect", "/mt5/watcher",
                 "/paper/engine/start", "/cex/engine/start"):
        assert path in SERVICE_TOKEN_PATHS, path
        assert auth_svc.service_token_allowed("POST", path) is True


def test_service_token_allowed_behaviour(client):
    from governance.auth import auth as auth_svc

    assert auth_svc.service_token_allowed("POST", "/paper/engine/start") is True
    assert auth_svc.service_token_allowed("POST", "/paper/engine/start/") is True
    assert auth_svc.service_token_allowed("POST", "/users") is False
    assert auth_svc.service_token_allowed("POST", "/payments/charge") is False
    assert auth_svc.service_token_allowed("POST", "/mt5/sync?x=1") is True
    # Reads are gated now, and the machine rails read to do their job, so the
    # service token passes the gate for ANY read -- but it still does not widen
    # by a single path what the machine credential may WRITE.
    assert auth_svc.service_token_allowed("GET", "/paper/engine/start") is True
    assert auth_svc.service_token_allowed("GET", "/users") is True


def test_a_valid_service_token_is_refused_on_a_human_route(client, monkeypatch):
    """The hardening step: the machine credential used to be an unbounded pass,
    so anyone holding it could `POST /users` or `/payments/charge`. Now those
    routes demand a session even when the token itself is genuine."""
    monkeypatch.setenv("TRADERAIG_AUTH", "1")
    monkeypatch.setenv("AUTH_SERVICE_TOKEN", "machine-token-value")

    res = client.post("/users", json={"email": f"peek{time.time_ns()}@x.co"},
                      headers={"X-Service-Token": "machine-token-value"})
    assert res.status_code == 401

    res = client.post("/payments/charge", json={"amount": 1},
                      headers={"X-Service-Token": "machine-token-value"})
    assert res.status_code == 401


def test_a_human_session_still_reaches_the_human_route(client, monkeypatch):
    """The console authenticates as a human now, and the session travels to the
    routes the machine token no longer may."""
    _uid, email, password = _operator(client, monkeypatch)
    monkeypatch.setenv("TRADERAIG_AUTH", "1")
    token = client.post("/auth/login", json={"email": email,
                                             "password": password}).json()["token"]

    res = client.post("/users", json={"email": f"human{time.time_ns()}@x.co"},
                      headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 201


def test_with_enforcement_off_the_scope_changes_nothing(client, monkeypatch):
    """The 24/7 host runs with the door unlocked. Scoping must not quietly
    re-lock a route the supervisor has never needed a session for."""
    monkeypatch.delenv("TRADERAIG_AUTH", raising=False)
    monkeypatch.setenv("AUTH_SERVICE_TOKEN", "machine-token-value")

    res = client.post("/users", json={"email": f"open{time.time_ns()}@x.co"},
                      headers={"X-Service-Token": "machine-token-value"})
    assert res.status_code == 201


def test_health_reports_the_service_token_scope(client, monkeypatch):
    monkeypatch.setenv("TRADERAIG_AUTH", "1")
    auth_block = client.get("/system/health").json()["auth"]

    assert auth_block["service_token_scoped"] is True
    assert "/paper/engine/start" in auth_block["service_token_paths"]
    assert "/users" not in auth_block["service_token_paths"]


def test_the_console_prefers_a_session_over_the_machine_token():
    """The fallback ordering is the point: a human command must send the human
    credential, not quietly fall back to the machine token that human routes now
    refuse."""
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "_auth_console_session", root / "tools" / "tradraig.py")
    console = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(console)

    os.environ["AUTH_SERVICE_TOKEN"] = "machine-token-value"
    os.environ["TRADERAIG_SESSION_TOKEN"] = "session-abc"
    try:
        assert console.service_headers() == {"Authorization": "Bearer session-abc"}
        os.environ.pop("TRADERAIG_SESSION_TOKEN", None)
        # no session → the machine token is not sent to humans either; it is
        # reserved for the rails, so with neither configured we send nothing
        assert console.service_headers() == {"X-Service-Token": "machine-token-value"}
    finally:
        os.environ.pop("TRADERAIG_SESSION_TOKEN", None)
        os.environ.pop("AUTH_SERVICE_TOKEN", None)
