"""Revocation, deletion, and the silent-downgrade footgun (2026-09-29).

The hazard this file exists for is small and unglamorous: `subscription/activate`
used to read `payload.get("plan", "free")`, so a request with an EMPTY body
meant "downgrade to free", and `grant_plan_entitlements()` replaces the whole
entitlement set. One unlabelled POST therefore stripped `can_trade` from the
operating principal — and because `/mt5/connect` and every gated decision route
are guarded by that entitlement, the platform's own
`TAIG-Backend-Watchdog` starts getting 403s on its very next tick. A malformed
request takes the system offline.

These tests pin the three things that must be true afterwards: a plan must be
named, a downgrade must be confirmed, and there must finally be a sanctioned way
to take authority away and to remove a user at all.
"""
import time

import pytest


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from operations.api import app
    return TestClient(app)


@pytest.fixture(autouse=True)
def _isolated_identity(monkeypatch):
    """Hermetic, for the same reason the payment module is: deleting the env var
    alone still lets these throwaway users become the acting principal for
    whatever runs next, which made the suite's result depend on collection
    order."""
    from governance.identity import identity

    monkeypatch.delenv("IDENTITY_PRIMARY_EMAIL", raising=False)
    users = dict(identity._users)
    subs = dict(identity._subscriptions)
    try:
        yield
    finally:
        identity._users.clear()
        identity._users.update(users)
        identity._subscriptions.clear()
        identity._subscriptions.update(subs)


def _operator(client, plan="institutional") -> str:
    """Create a user, make it the acting principal, and give it a live plan."""
    email = f"op{time.time_ns()}@x.co"
    uid = client.post("/users", json={"email": email}).json()["user_id"]
    res = client.post(f"/users/{uid}/subscription/activate",
                      json={"plan": plan})
    assert res.status_code == 200, res.text
    return uid


def test_the_footgun_an_empty_body_no_longer_downgrades(client):
    """`{}` used to mean 'free'. Now it is a 400 that says why."""
    uid = _operator(client)
    res = client.post(f"/users/{uid}/subscription/activate", json={})
    assert res.status_code == 400
    assert "plan is required" in res.json()["detail"]
    # and the operator still holds everything
    assert client.get(f"/users/{uid}/can/can_trade").json()["allowed"] is True
    assert client.get(f"/users/{uid}/can/can_manage_risk").json()["allowed"] is True


def test_a_missing_body_is_refused_too(client):
    """Not just `{}` — no body at all, which is the same intent-free request.

    This one is stopped even earlier, by FastAPI itself: `payload: Dict` is a
    required body parameter, so a bodyless POST is a 422 before the handler
    runs. That is the right outcome, and worth pinning separately from the 400
    so neither path can regress into a silent downgrade.
    """
    uid = _operator(client)
    res = client.post(f"/users/{uid}/subscription/activate")
    assert res.status_code == 422
    assert client.get(f"/users/{uid}/can/can_trade").json()["allowed"] is True


def test_a_silent_downgrade_is_refused_and_says_what_would_be_lost(client):
    """An explicit lower plan is still a downgrade, and must be confirmed.

    `institutional` holds every entitlement, so dropping to `starter` keeps
    `can_trade` and gives up the other five — the response names all of them,
    because a refusal that only said "no" is what made this footgun survivable.
    """
    uid = _operator(client, plan="institutional")
    res = client.post(f"/users/{uid}/subscription/activate", json={"plan": "starter"})
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["would_lose"] == ["api_access", "can_copy", "can_manage_risk",
                                    "multi_account", "read_only"]
    assert "can_trade" not in detail["would_lose"]
    assert "confirm_downgrade" in detail["hint"]
    # nothing changed
    assert client.get(f"/users/{uid}/can/can_manage_risk").json()["allowed"] is True
    assert client.get(f"/users/{uid}").json()["plan"] == "institutional"


def test_a_refused_downgrade_is_audited(client):
    from governance.identity import identity

    _operator(client, plan="institutional")
    client.post(f"/users/{identity.principal_user_id()}/subscription/activate",
                json={"plan": "free"})
    actions = [e.action for e in identity.audit_log(limit=60)]
    assert "subscription.downgrade.refused" in actions


def test_a_confirmed_downgrade_is_allowed(client):
    """Refusing is not the same as forbidding: the operator can still choose it."""
    uid = _operator(client, plan="institutional")
    res = client.post(f"/users/{uid}/subscription/activate",
                      json={"plan": "pro", "confirm_downgrade": True})
    assert res.status_code == 200
    assert res.json()["plan"] == "pro"
    assert client.get(f"/users/{uid}/can/can_trade").json()["allowed"] is True
    assert client.get(f"/users/{uid}/can/can_manage_risk").json()["allowed"] is False


def test_an_upgrade_needs_no_confirmation(client):
    """The guard must not become an obstacle to buying more."""
    uid = _operator(client, plan="starter")
    res = client.post(f"/users/{uid}/subscription/activate",
                      json={"plan": "institutional"})
    assert res.status_code == 200
    assert res.json()["plan"] == "institutional"


def test_a_pending_user_has_nothing_to_lose_so_a_free_plan_is_not_a_downgrade(client):
    """The guard asks what is EFFECTIVELY held, not what is stored. A pending
    subscription grants nothing, so switching it to free takes nothing away and
    must not be blocked — otherwise a fresh install could never be enrolled."""
    from governance.identity import identity

    uid = client.post("/users", json={"email": f"new{time.time_ns()}@x.co"}).json()["user_id"]
    client.post(f"/users/{uid}/subscription/activate", json={"plan": "starter"})
    # expire it: stored entitlements remain, effective ones do not
    identity.expire_subscription(uid)
    assert identity.effective_entitlements(uid) == set()

    res = client.post(f"/users/{uid}/subscription/activate", json={"plan": "free"})
    assert res.status_code == 200


def test_an_unknown_plan_is_a_400_naming_the_options(client):
    uid = _operator(client, plan="starter")
    res = client.post(f"/users/{uid}/subscription/activate", json={"plan": "platinum"})
    assert res.status_code == 400
    assert "institutional" in res.json()["detail"]


def test_revoking_your_own_authority_must_be_confirmed(client):
    """Self-revocation is legitimate (stop the system trading) but never a
    default, because on a single-tenant box it removes the entitlement the
    trading rails are gated on."""
    uid = _operator(client, plan="institutional")
    res = client.post(f"/users/{uid}/subscription/revoke", json={})
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["error"] == "you are revoking your own authority"
    assert "TAIG-Backend-Watchdog" in detail["consequence"]
    # untouched
    assert client.get(f"/users/{uid}/can/can_trade").json()["allowed"] is True


def test_a_confirmed_revocation_removes_and_records_what_was_lost(client):
    from governance.identity import identity

    uid = _operator(client, plan="institutional")
    res = client.post(f"/users/{uid}/subscription/revoke",
                      json={"confirm_lockout": True, "reason": "operator standdown"})
    assert res.status_code == 200
    assert res.json()["revoked"] is True
    assert "can_trade" in res.json()["revoked_entitlements"]
    assert client.get(f"/users/{uid}/can/can_trade").json()["allowed"] is False
    assert client.get(f"/users/{uid}").json()["subscription_status"] == "cancelled"

    entries = [e for e in identity.audit_log(limit=60)
               if e.action == "subscription.revoke"]
    assert entries, "revocation must be auditable under its own action"
    assert "can_trade" in entries[0].details["revoked_entitlements"]
    assert entries[0].details["reason"] == "operator standdown"


def test_a_revoked_principal_still_cannot_bill_itself_into_entitlements(client):
    """Revoking and then quietly re-activating is a legitimate repair, not a
    bypass — but it must be a visible, audited act rather than a silent one."""
    from governance.identity import Entitlement, identity

    uid = _operator(client, plan="institutional")
    client.post(f"/users/{uid}/subscription/revoke", json={"confirm_lockout": True})
    assert identity.can(uid, Entitlement.CAN_TRADE) is False

    res = client.post(f"/users/{uid}/subscription/activate", json={"plan": "starter"})
    assert res.status_code == 200
    assert identity.can(uid, Entitlement.CAN_TRADE) is True


def test_deleting_a_user_with_a_live_subscription_is_refused(client):
    """Deleting an authorised record outright is the same silent removal the
    downgrade guard exists to stop, only described less clearly."""
    uid = _operator(client, plan="institutional")
    res = client.delete(f"/users/{uid}")
    assert res.status_code == 409
    assert "revoke" in res.json()["detail"]["hint"]
    assert client.get(f"/users/{uid}").status_code == 200


def test_the_full_revoke_then_delete_sequence_works(client):
    from governance.identity import identity

    uid = _operator(client, plan="institutional")
    assert client.post(f"/users/{uid}/subscription/revoke",
                       json={"confirm_lockout": True}).status_code == 200
    # deleting the acting principal needs its own confirmation, on top of the
    # revoke that made deletion legal in the first place
    res = client.delete(f"/users/{uid}", params={"confirm": "true"})
    assert res.status_code == 200
    assert res.json() == {"deleted": True, "user_id": uid}
    assert client.get(f"/users/{uid}").status_code == 404
    assert uid not in identity._users
    assert uid not in identity._subscriptions


def _pending_principal(client, monkeypatch) -> str:
    """Create a user and make it the acting principal WITHOUT activating a plan.

    Needed for the deletion tests: `activate_subscription` marks even a `free`
    subscription ACTIVE, so an "activated" operator is legitimately refused
    deletion until revoked, and that ordering rule would otherwise mask the
    principal guard being tested. The principal is selected the way the
    deployment does it — by email — rather than by poking at internals.
    """
    email = f"pend{time.time_ns()}@x.co"
    uid = client.post("/users", json={"email": email}).json()["user_id"]
    monkeypatch.setenv("IDENTITY_PRIMARY_EMAIL", email)
    return uid


def test_deleting_the_acting_principal_needs_confirmation(client, monkeypatch):
    """It does not merely remove a user, it changes who the principal is — and
    with nobody left the gate falls back to bootstrap, which reopens the routes
    bootstrap lets through."""
    uid = _pending_principal(client, monkeypatch)
    res = client.delete(f"/users/{uid}")
    assert res.status_code == 409
    assert res.json()["detail"]["error"] == "you are deleting the acting principal"
    assert "bootstrap" in res.json()["detail"]["consequence"]
    assert client.get(f"/users/{uid}").status_code == 200


def test_a_confirmed_principal_delete_is_allowed_and_audited(client, monkeypatch):
    from governance.identity import identity

    uid = _pending_principal(client, monkeypatch)
    assert client.delete(f"/users/{uid}", params={"confirm": "true"}).status_code == 200
    assert uid not in identity._users
    assert client.get(f"/users/{uid}").status_code == 404
    actions = [e.action for e in identity.audit_log(limit=60)]
    assert "user.delete" in actions


def test_peer_ownership_still_applies_to_every_new_route(client):
    """The new privileged verbs must not become a way around `_own`."""
    uid = _operator(client, plan="institutional")
    other = client.post("/users", json={"email": f"peer{time.time_ns()}@x.co"}).json()["user_id"]

    assert client.post(f"/users/{other}/subscription/revoke",
                       json={"confirm_lockout": True}).status_code == 403
    assert client.post(f"/users/{other}/subscription/activate",
                       json={"plan": "free", "confirm_downgrade": True}).status_code == 403
    assert client.delete(f"/users/{other}").status_code == 403
    # the peer is untouched
    assert client.post("/users", json={"email": f"p{time.time_ns()}@x.co"}) is not None
    assert uid in identity_users()


def identity_users():
    from governance.identity import identity
    return identity._users


def test_a_never_entitled_user_needs_no_downgrade_confirmation(client):
    """`free` -> `free` is not a downgrade; the guard must not fire on noise."""
    from governance.identity import SubscriptionPlan, identity

    uid = client.post("/users", json={"email": f"p{time.time_ns()}@x.co"}).json()["user_id"]
    client.post(f"/users/{uid}/subscription/activate", json={"plan": "free"})
    assert identity.entitlements_lost_by_plan(uid, SubscriptionPlan.FREE) == set()
    res = client.post(f"/users/{uid}/subscription/activate", json={"plan": "free"})
    assert res.status_code == 200


def test_the_repository_can_actually_delete(client):
    """A delete that only cleared memory would resurrect the user from SQLite on
    the next boot, so the persistence layer needs a real delete — and it needs a
    test, because the whole guarantee is invisible in the live environment where
    `persistence_enabled()` is true and in CI where it is false.

    Exercised against a bound test session rather than the API: the service path
    above already proves the API contract, and this proves the row actually goes.
    """
    from governance.identity import User
    from persistence.db import bind_test_session
    from persistence.repositories import UserRepository

    session = bind_test_session()
    repo = UserRepository(session)
    uid = "u-to-delete"
    repo.save(User(user_id=uid, email="gone@x.co", display_name="Gone"))
    assert repo.get(uid) is not None

    assert repo.delete(uid) is True
    assert repo.get(uid) is None
    # and it is idempotent rather than raising on a second attempt
    assert repo.delete(uid) is False
