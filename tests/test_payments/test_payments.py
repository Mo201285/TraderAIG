"""Payment/billing smoke + gate tests (no network, no secrets ever printed)."""

import hashlib
import hmac
import json
import time

import pytest


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from operations.api import app
    return TestClient(app)


def _user_id(client, plan="free") -> str:
    resp = client.post("/users", json={"email": f"{time.time_ns()}@x.co",
                                       "display_name": "pay-test",
                                       "plan": plan})
    assert resp.status_code == 201
    return resp.json()["user_id"]


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


def test_charge_unknown_user_404(client):
    resp = client.post("/payments/charge", json={
        "user_id": "nope", "amount_usd": 5})
    assert resp.status_code == 404


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


def test_wallet_unknown_user_404(client):
    resp = client.get("/payments/wallet/nope")
    assert resp.status_code == 404


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
