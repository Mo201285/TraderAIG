"""Payment/billing smoke + gate tests (no network, no secrets ever printed)."""

import hashlib
import hmac
import json
import os
import time

import pytest


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from operations.api import app
    return TestClient(app)


@pytest.fixture(autouse=True)
def _no_leaked_principal(monkeypatch):
    """Make this module hermetic: no acting principal and no user may leak out.

    `_user_id` points `IDENTITY_PRIMARY_EMAIL` at the user it creates, which is
    how these tests bill themselves, so without a reset that value survives into
    any later test that does not create a user.

    Deleting the env var alone was NOT enough, and the gap it left is worth
    recording: with no primary email set, `principal_user_id()` falls back to the
    first-created user, so these throwaway payment users became the acting
    principal for whatever ran next — one of them left on a `starter` plan, and
    the next 28 gated tests failed on `can_manage_risk`. It was invisible in a
    full-suite run only because alphabetical collection happens to run
    `test_operations` BEFORE `test_payments`; collected the other way round the
    suite was red. A green suite that is really a coin-flip on collection order
    is not a green suite, so the user maps are snapshotted and restored too.
    """
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


def _user_id(client, plan="free") -> str:
    """Create a user AND make it the acting principal.

    The billing routes enforce ownership, so a test that creates a user and
    then bills it is only meaningful if that user is the one acting. These tests
    used to pass precisely because nothing checked: an anonymous caller could
    bill and activate any `user_id`, which is the hole the ownership guard now
    closes. Pointing the principal at the test user makes the suite exercise the
    production shape — self-service billing by the operator — instead of
    depending on the vulnerability.
    """
    resp = client.post("/users", json={"email": f"{time.time_ns()}@x.co",
                                       "display_name": "pay-test",
                                       "plan": plan})
    assert resp.status_code == 201
    user_id = resp.json()["user_id"]
    os.environ["IDENTITY_PRIMARY_EMAIL"] = resp.json().get("email", "")
    return user_id


def _session_for(user_id: str) -> dict:
    """A session for `user_id`, satisfying I4's multi-tenant enforcement.

    Issued out of band rather than through `/auth/password` (which refuses to
    bootstrap a credential-less principal once enforcement is on), so a test
    about ownership/refusal does not have to also test the login flow.
    """
    from governance.auth import auth as auth_svc
    from governance.identity import identity

    identity.set_password(user_id, "pay-session-password-123")
    return {"Authorization": f"Bearer {auth_svc.issue(user_id)[0]}"}


# -- API surface ---------------------------------------------------------


def test_payments_status_endpoint(client):
    resp = client.get("/payments/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "payments"
    assert body["provider"] == "sandbox"
    assert body["mode"] == "sandbox"
    assert "locked" in body and "gate_live_allowed" in body


def test_payments_providers_endpoint(client):
    resp = client.get("/payments/providers")
    assert resp.status_code == 200
    names = {r["name"] for r in resp.json()["available"]}
    assert names >= {"sandbox", "stripe", "pi"}


def test_payments_status_never_leaks_secrets(client):
    raw = client.get("/payments/status").text
    assert "sk_test" not in raw and "sk_live" not in raw


def test_charge_sandbox_activates_subscription(client):
    uid = _user_id(client)
    resp = client.post("/payments/charge", json={
        "user_id": uid, "amount_usd": 49, "plan": "starter",
        "description": "Starter 30d"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "succeeded"
    assert body["subscription_activated"] is True
    wallet = client.get(f"/payments/wallet/{uid}").json()
    assert wallet["balance_usd"] == 49.0
    user = client.get(f"/users/{uid}").json()
    assert user["subscription_status"] == "active"
    assert "can_trade" in user["entitlements"]


def test_charge_for_an_unknown_user_is_refused_when_a_principal_acts(client):
    """A `user_id` that is not the principal's is refused, unknown or not.

    Note this is no longer a 404. Once a principal exists (here, explicitly, so
    the assertion does not depend on which user some earlier test left in the
    process-wide identity store) a `user_id` that is not the principal's fails
    the ownership check, and that is the better answer: answering 404 for "no
    such user" and 403 for "not yours" would let a caller enumerate which users
    exist. The genuine bootstrap case — an empty identity store, where a 404 is
    still correct and a fresh install can tell a typo from a valid id — is
    covered in `test_ownership_isolation.py`, which isolates the store.
    """
    _user_id(client)
    resp = client.post("/payments/charge", json={
        "user_id": "nope", "amount_usd": 5})
    assert resp.status_code == 403
    assert "ownership denied" in resp.json()["detail"]


def test_charge_for_another_user_is_refused_even_when_the_user_exists(client):
    """A real, different user must be refused the same way a bogus id is.

    Two users exist here, so I4 makes the box multi-tenant and turns enforcement
    on: the acting principal authenticates, and the 403s that follow are the
    ownership refusals -- not auth ones.
    """
    mine = _user_id(client)
    headers = _session_for(mine)
    other = client.post("/users", json={"email": f"{time.time_ns()}@y.co"})
    assert other.status_code == 201
    other_id = other.json()["user_id"]

    bogus = client.post("/payments/charge", json={
        "user_id": "nope", "amount_usd": 5}, headers=headers)
    someone_elses = client.post("/payments/charge", json={
        "user_id": other_id, "amount_usd": 5}, headers=headers)
    assert bogus.status_code == 403
    assert someone_elses.status_code == 403
    assert bogus.json() == someone_elses.json()
    assert client.post("/payments/charge", json={
        "user_id": mine, "amount_usd": 5}, headers=headers).status_code == 200


def test_charge_bad_amount_400(client):
    uid = _user_id(client)
    resp = client.post("/payments/charge", json={
        "user_id": uid, "amount_usd": 0})
    assert resp.status_code == 400


def test_charge_unknown_plan_400(client):
    uid = _user_id(client)
    resp = client.post("/payments/charge", json={
        "user_id": uid, "amount_usd": 10, "plan": "platinum"})
    assert resp.status_code == 400


def test_wallet_of_another_user_is_refused_without_enumeration(client):
    """A wallet that is not yours is refused, and the refusal reveals nothing.

    This used to assert `404` for a wallet id that does not exist. That is the
    wrong assertion now, and the old status was the better answer for a
    different reason: distinguishing "no such user" (404) from "not yours"
    (403) is an enumeration oracle. A bogus id and a real, different user's id
    must get the same answer, so the route cannot be used to discover who
    exists.
    """
    mine = _user_id(client)
    headers = _session_for(mine)
    other = client.post("/users", json={"email": f"{time.time_ns()}@y.co"})
    assert other.status_code == 201
    other_id = other.json()["user_id"]

    bogus = client.get("/payments/wallet/nope", headers=headers)
    someone_elses = client.get(f"/payments/wallet/{other_id}", headers=headers)

    assert bogus.status_code == 403
    assert someone_elses.status_code == 403
    assert bogus.json() == someone_elses.json(), (
        "the refusal must be identical for a bogus id and a real other user, "
        "otherwise the route enumerates which users exist")
    # The operator can still read their own wallet.
    assert client.get(f"/payments/wallet/{mine}", headers=headers).status_code == 200


def test_refund_lifecycle_via_api(client):
    uid = _user_id(client)
    charged = client.post("/payments/charge", json={
        "user_id": uid, "amount_usd": 129, "plan": "pro"}).json()
    cid = charged["charge_id"]
    refunded = client.post("/payments/refund", json={"charge_id": cid})
    assert refunded.status_code == 200
    assert refunded.json()["status"] == "refunded"
    wallet = client.get(f"/payments/wallet/{uid}").json()
    assert wallet["balance_usd"] == 0.0
    assert wallet["succeeded"] == 0
    assert wallet["refunded"] == 2


def test_refund_unknown_charge_400(client):
    resp = client.post("/payments/refund", json={"charge_id": "ch_bogus"})
    assert resp.status_code == 400


def test_stripe_charge_locked_without_gate(client):
    uid = _user_id(client)
    resp = client.post("/payments/charge", json={
        "user_id": uid, "amount_usd": 5, "provider": "stripe"})
    assert resp.status_code == 409
    assert "LOCKED" in resp.json()["detail"]


# -- Service gate (offline) ----------------------------------------------


def test_sandbox_service_never_locked():
    from governance.payments import PaymentService
    svc = PaymentService(mode="sandbox", live_allowed=False)
    assert svc.locked is False


def test_stripe_locked_until_gate_armed():
    from governance.payments import PaymentLockedError, PaymentService, StripePaymentProvider
    prov = StripePaymentProvider(secret_key="sk_test_fake")
    assert PaymentService(mode="sandbox", live_allowed=False,
                          provider=prov).locked is True
    armed = PaymentService(mode="live", live_allowed=True, provider=prov)
    assert armed.live_armed is True
    assert armed.locked is False
    assert PaymentService(mode="live", live_allowed=False,
                          provider=prov).locked is True
    no_key = PaymentService(mode="live", live_allowed=True,
                            provider=StripePaymentProvider(secret_key=""))
    assert no_key.live_armed is False
    with pytest.raises(PaymentLockedError):
        PaymentService(mode="sandbox", live_allowed=False,
                       provider=prov).charge("u", 5)


def test_stripe_signature_good_and_bad():
    from governance.payments import PaymentLockedError, StripePaymentProvider, PaymentService
    secret = "whsec_test"
    prov = StripePaymentProvider(secret_key="sk_test_fake",
                                 webhook_secret=secret)
    body = json.dumps({"id": "evt_1", "type": "charge.succeeded"})
    ts = str(int(time.time()))
    sig = hmac.new(secret.encode(), f"{ts}.{body}".encode(),
                   hashlib.sha256).hexdigest()
    assert prov.verify_webhook(body, f"t={ts},v1={sig}") is True
    assert prov.verify_webhook(body, "t=1,v1=deadbeef") is False
    with pytest.raises(PaymentLockedError):
        PaymentService(mode="live", live_allowed=True,
                       provider=prov).handle_webhook(body, "t=1,v1=bad")
    assert prov.verify_webhook(body, "") is False  # unsigned live rejected


def test_live_charge_pending_then_webhook_confirms():
    from governance.payments import PaymentService, PaymentStatus
    from governance.identity import SubscriptionPlan, identity

    class FakeStripe:
        name = "stripe"
        _webhook_secret = "whsec_dev"

        def configured(self):
            return True

        def charge(self, amount_usd, description="", metadata=None):
            return {"ok": True, "charge_id": "ch_dev_123",
                    "status": "succeeded", "amount_usd": amount_usd}

        def refund(self, charge_id):
            return {"ok": True, "charge_id": charge_id}

        def verify_webhook(self, payload, signature):
            return signature == "valid"

    user = identity.create_user(
        email=f"{time.time_ns()}@live.co", display_name="live-flow",
        plan=SubscriptionPlan.FREE)
    svc = PaymentService(mode="live", live_allowed=True,
                         provider=FakeStripe())
    result = svc.charge(user.user_id, 399, plan="institutional")
    assert result.status == PaymentStatus.PENDING
    assert svc.wallet(user.user_id)["pending"] == 1

    event = json.dumps({
        "type": "charge.succeeded",
        "data": {"object": {"id": "ch_dev_123",
                            "metadata": {"user_id": user.user_id}}},
    })
    out = svc.handle_webhook(event, "valid")
    assert out["processed"] is True
    assert out["subscription_activated"] is True
    wallet = svc.wallet(user.user_id)
    assert wallet["balance_usd"] == 399.0
    assert wallet["pending"] == 0
    assert identity.get_user(user.user_id).subscription_status.value == "active"


def test_refund_only_succeeded():
    from governance.payments import PaymentService, PaymentStatus
    from governance.identity import SubscriptionPlan, identity

    svc = PaymentService()
    uid = identity.create_user(
        email=f"{time.time_ns()}@r.co", display_name="ref",
        plan=SubscriptionPlan.FREE).user_id
    ok = svc.charge(uid, 49, plan="starter")
    assert ok.status == PaymentStatus.SUCCEEDED
    ref = svc.refund(ok.charge_id)
    assert ref.status == PaymentStatus.REFUNDED
    again = svc.refund(ok.charge_id)
    assert again.status != PaymentStatus.REFUNDED
    assert again.message.startswith("only succeeded")
    assert svc.wallet(uid)["balance_usd"] == 0.0
