"""Ownership isolation: a caller-supplied `user_id` is not an authority (28.17/28.18).

The audit behind these tests: this deployment is single-tenant, and six routes
accepted a `user_id` from the URL without ever asking who was asking. The worst
was `POST /users/{id}/subscription/activate` — the entitlement self-service path
left deliberately ungated so a new principal could not be acquisition-
deadlocked — which meant any caller that could reach the port could read another
user's entitlements and upgrade or downgrade their subscription. The entitlement
gate was advisory precisely where it mattered most.

The fix is not to pretend this is multi-tenant. It is to make the real boundary
explicit: one acting principal, which may act on its own record and nobody
else's, with bootstrap (no principal yet) passing because there is nothing to
protect.

Slice I4 note: this fixture deliberately holds TWO users, which now means the
deployment is multi-tenant and read/write enforcement turns itself on. The tests
therefore carry the acting principal's session on every request — which is the
stronger shape anyway: ownership must refuse a fully authenticated peer, not
merely an anonymous caller.
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from operations.api import app  # noqa: E402
from governance.identity import (  # noqa: E402
    Entitlement, IdentityService, SubscriptionPlan, identity as _global_identity)


def identity_can_trade(user_id: str) -> bool:
    """Read a peer's entitlements through the service, not through the route.

    The `/users/{id}/can/{ent}` route is itself ownership-guarded now, so it
    cannot be used to demonstrate that the peer is privileged — that would be a
    test that passes for the wrong reason.
    """
    return _global_identity.can(user_id, Entitlement.CAN_TRADE)


@pytest.fixture()
def two_identities(monkeypatch):
    """Two peers: both institutional, both active, one acting principal.

    The second user is deliberately given the SAME entitlements as the
    principal. That is the only way to prove the new ownership layer does real
    work: on `PUT /users/{id}/risk-policy` the entitlement gate is evaluated
    against the *target*, so a low-privilege target is already refused one
    layer earlier. What has to stop a fully-privileged peer from editing
    someone else's risk limits is ownership — and that is what is under test.

    Because two users exist, slice I4 makes this multi-tenant and turns
    enforcement on, so the returned client presents the principal's session on
    every call. `client` carries the credential; `client_unauthenticated` is
    the same app without it, for the one test that asserts enforcement is real.
    """
    from governance.auth import auth as auth_svc

    svc = IdentityService()
    svc.rehydrate()
    principal = svc.create_user(email="owner@institution.com",
                                display_name="Owner",
                                plan=SubscriptionPlan.INSTITUTIONAL)
    svc.activate_subscription(principal.user_id, SubscriptionPlan.INSTITUTIONAL)
    other = svc.create_user(email="peer@elsewhere.test",
                            display_name="Peer Institution",
                            plan=SubscriptionPlan.INSTITUTIONAL)
    svc.activate_subscription(other.user_id, SubscriptionPlan.INSTITUTIONAL)
    monkeypatch.setattr(_global_identity, "_users", svc._users)
    monkeypatch.setattr(_global_identity, "_subscriptions", svc._subscriptions)
    monkeypatch.setattr(_global_identity, "_audit", svc._audit)
    monkeypatch.setenv("IDENTITY_PRIMARY_EMAIL", "owner@institution.com")

    _global_identity.set_password(principal.user_id, "owner-password-123")
    token = auth_svc.issue(principal.user_id)[0]

    authenticated = TestClient(app, headers={"Authorization": f"Bearer {token}"})
    plain = TestClient(app)
    yield authenticated, principal.user_id, other.user_id, plain


def test_the_peer_is_equally_privileged_so_only_ownership_can_stop_it(
        two_identities):
    """Guard the guard: an IDOR test is worthless if the peer was weak.

    On the risk-policy PUT the entitlement gate is checked against the *target*
    user, so a `free` target would have been refused with
    "entitlement ... required" and this suite would have passed while proving
    nothing about ownership. The peer therefore holds CAN_TRADE, and the
    refusal must be the ownership one.
    """
    client, principal, other, _plain = two_identities
    assert identity_can_trade(other) is True
    # The principal's own record is reachable: the guard is real, not a blanket deny.
    assert client.get(f"/users/{principal}").status_code == 200
    for resp in (client.get(f"/users/{other}"),
                 client.put(f"/users/{other}/risk-policy",
                            json={"max_risk_per_trade": 0.99})):
        assert resp.status_code == 403, resp.text
        assert "ownership denied" in resp.json()["detail"]
        assert "entitlement" not in resp.json()["detail"]


def test_enforcement_turns_on_when_a_second_tenant_exists(two_identities):
    """/system/health must say what the deployment is, not imply less.

    Slice I4 reverses the old single-tenant claim: two users exist here, so the
    deployment IS multi-tenant, reads are gated, and an unauthenticated caller
    is refused a tenant route while global reference reads stay open. The
    session-carrying client is authenticated; the plain one is not.
    """
    client, principal, _other, plain = two_identities
    tenancy = plain.get("/system/health").json()["tenancy"]
    assert tenancy["model"] == "multi-tenant"
    assert tenancy["multi_tenant"] is True
    assert tenancy["reads_gated"] is True
    assert tenancy["acting_principal"] == principal
    # No session presented to /system/health -> authenticated is false there.
    assert tenancy["authenticated"] is False

    # The enforcement is real: a tenant route with no session is refused...
    assert plain.get("/account").status_code in (401, 403)
    # ...while a global reference read carries no tenant and stays open.
    assert plain.get("/providers").status_code == 200

    # The gaps still open are named; the enforcement policy is no longer one.
    note = tenancy["note"]
    assert "still open" in note
    assert "enforcement policy that only" not in note


@pytest.mark.parametrize("method,path,kwargs", [
    ("GET", "/users/{other}", {}),
    ("GET", "/users/{other}/can/can_trade", {}),
    ("GET", "/users/{other}/risk-policy", {}),
    ("PUT", "/users/{other}/risk-policy",
     {"json": {"max_risk_per_trade": 0.99}}),
    ("POST", "/users/{other}/subscription/activate",
     {"json": {"plan": "institutional"}}),
    ("GET", "/payments/wallet/{other}", {}),
])
def test_principal_cannot_reach_another_users_record(two_identities,
                                                     method, path, kwargs):
    """The IDOR, closed on every route that took a user_id."""
    client, _, other, _plain = two_identities
    call = getattr(client, method.lower())
    resp = call(path.format(other=other), **kwargs)
    assert resp.status_code == 403, resp.text
    assert "ownership denied" in resp.json()["detail"]


def test_principal_can_still_reach_its_own_record(two_identities):
    """The fix must not lock the operator out of their own deployment."""
    client, principal, _, _plain = two_identities
    assert client.get(f"/users/{principal}").status_code == 200
    assert client.get(f"/users/{principal}/can/can_trade").json()["allowed"] is True
    assert client.get(f"/users/{principal}/risk-policy").status_code == 200
    assert client.get(f"/payments/wallet/{principal}").status_code == 200


def test_own_subscription_activation_still_works(two_identities):
    """Documented entitlement-recovery path must survive the ownership check."""
    client, principal, _, _plain = two_identities
    resp = client.post(f"/users/{principal}/subscription/activate",
                       json={"plan": "institutional"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["plan"] == "institutional"


def test_other_users_subscription_is_not_changed_by_the_denied_call(
        two_identities):
    """A 403 must be a refusal, not a partial write.

    This is the documented footgun from the 24/7 milestone: activating with an
    empty/incorrect plan SILENTLY DOWNGRADES a live institutional identity and
    drops `can_trade`, 403-ing `/mt5/*`. The peer here is institutional, so a
    denied request to activate them on `free` is exactly the downgrade attack —
    and the peer must still be institutional afterwards. A handler that checked
    ownership after mutating would pass a status-code test and still leave the
    damage done.
    """
    client, principal, other, _plain = two_identities
    assert identity_can_trade(other) is True
    denied = client.post(f"/users/{other}/subscription/activate",
                         json={"plan": "free"})
    assert denied.status_code == 403
    users = _global_identity._users
    assert users[other].plan == SubscriptionPlan.INSTITUTIONAL
    assert identity_can_trade(other) is True
    # ...and the principal's own record is untouched by the attempt.
    assert client.get(f"/users/{principal}").json()["plan"] == "institutional"


def test_ownership_denial_is_audited(two_identities):
    """A refused authority call leaves the same trail an entitlement denial does."""
    client, _, other, _plain = two_identities
    client.get(f"/users/{other}/risk-policy")
    actions = [e.action for e in _global_identity.audit_log(limit=200)]
    assert "ownership.denied" in actions


def test_a_caller_cannot_mint_entitlements_for_another_user(two_identities):
    """The billing endpoint was the way around the entitlement gate.

    This is the finding that mattered most. `POST /payments/charge` takes
    `user_id` in the BODY, so a path-parameter sweep missed it entirely, and it
    activates a real subscription when a `plan` is supplied. Verified against
    the running backend before it was fixed: an unauthenticated POST returned
    `activated=True` for an arbitrary user id. The route had been left
    deliberately ungated because gating activation was feared to deadlock a new
    principal — but ungated meant *any* caller could grant *anybody* an
    institutional subscription, and could aim `plan: "free"` at the operator to
    strip `can_trade` and make the next watchdog tick 403 on `/mt5/connect`.
    """
    client, _, other, _plain = two_identities
    resp = client.post("/payments/charge", json={
        "user_id": other, "amount_usd": 1, "plan": "institutional"})
    assert resp.status_code == 403, resp.text
    assert "ownership denied" in resp.json()["detail"]
    # The peer's record is untouched: no upgrade, no money, no charge.
    assert _global_identity.get_user(other).plan == SubscriptionPlan.INSTITUTIONAL
    assert identity_can_trade(other) is True


def test_the_principal_can_still_bill_itself(two_identities):
    """Self-service billing is the production shape and must keep working."""
    client, principal, _, _plain = two_identities
    resp = client.post("/payments/charge", json={
        "user_id": principal, "amount_usd": 5, "plan": "institutional"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "succeeded"
    assert client.get(f"/payments/wallet/{principal}").status_code == 200


def test_refund_checks_the_owner_of_the_charge_not_a_supplied_id(two_identities):
    """A refund takes a `charge_id` and no user, so ownership has to be derived.

    A refund route given a caller-supplied `user_id` would be checking
    ownership of something other than the charge it is about to reverse, so the
    owner is resolved from the charge id inside the service.
    """
    from governance.payments import payments_service
    client, principal, other, _plain = two_identities
    # Create a charge owned by the PEER directly through the service: the API
    # route that would create it is (correctly) refusing to bill anyone else,
    # which is exactly why the refund test has to reach past the API to set up.
    entry = payments_service.charge(user_id=other, amount_usd=3.0)
    assert entry.status.value == "succeeded"
    resp = client.post("/payments/refund", json={"charge_id": entry.charge_id})
    assert resp.status_code == 403, resp.text
    assert "ownership denied" in resp.json()["detail"]


def test_bootstrap_passes_when_no_principal_exists(monkeypatch):
    """No principal = nothing to own yet, so enrolment must not be deadlocked.

    This is the same reasoning that keeps the entitlement gate in bootstrap
    mode, and the documented `POST /users/{id}/subscription/activate` path is
    how the first identity is created — locking it would make a fresh install
    unrecoverable.
    """
    empty = IdentityService()
    monkeypatch.setattr(_global_identity, "_users", empty._users)
    monkeypatch.setenv("IDENTITY_PRIMARY_EMAIL", "nobody@nowhere.test")
    client = TestClient(app)
    created = client.post("/users", json={"email": "first@install.test"})
    assert created.status_code in (200, 201), created.text
    user_id = created.json()["user_id"]
    assert client.get(f"/users/{user_id}").status_code == 200
    assert client.get(f"/users/{user_id}/risk-policy").status_code == 200
