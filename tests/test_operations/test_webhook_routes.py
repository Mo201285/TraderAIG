"""The `/webhooks/{provider_id}/referral` route over the real app (G4).

The domain tests cover signature and intake; this layer covers what only the
route can get wrong:

- the webhook path is *open* (no session required) even when enforcement is on,
  because the caller is a provider authenticated by signature, not a user with a
  session -- and the read of a delivery log stays gated;
- the route maps each refusal to the right status: a bad/missing/stale signature
  or an unconfigured provider is `401`, an unknown code or malformed body is
  `400`, and a re-sent registration is a truthful `200` `duplicate`;
- an accepted delivery records the event and grants nothing (`is_authorisation:
  False`, the Risk Governor the only trade authority);
- an unreachable store is `503`, not a fake result.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from operations.api import app  # noqa: E402
from persistence.db import bind_test_session  # noqa: E402
from persistence.models_accounts import (  # noqa: E402
    ExternalProviderRecord,
    ExternalReferralEvent,
    ProviderWebhookDelivery,
    ReferralRecord,
)
from persistence.repositories_accounts import (  # noqa: E402
    ExternalProviderRepository,
    ReferralRepository,
)
from core.secrets_vault import webhook_slot  # noqa: E402
from providers.webhooks import sign_payload  # noqa: E402

PROVIDER = "fortraders"
SECRET = "route-wh-secret-0123456789"


class _FakeVault:
    def __init__(self, slots=None):
        self._store = dict(slots or {})

    def set(self, slot, value):
        self._store[slot] = value

    def resolve(self, slot):
        return self._store.get(slot, "")

    def exists(self, slot):
        return slot in self._store


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _isolated_vault(monkeypatch):
    """Never read the machine's real vault: default to an empty one.

    The real vault can carry an enrolled `webhook.<provider>.signing_secret`
    (an operator enrolling a partner is the whole point of G4), so a test that
    relies on "no secret is configured" would silently depend on the developer's
    machine state. Empty by default; `enrolled_secret` overrides it.
    """
    monkeypatch.setattr("providers.webhooks.vault", _FakeVault({}))


@pytest.fixture
def webhook_db(monkeypatch):
    session = bind_test_session()
    for model in (ReferralRecord, ExternalReferralEvent,
                  ProviderWebhookDelivery, ExternalProviderRecord):
        session.execute(delete(model))
    session.commit()
    monkeypatch.setattr("persistence.repositories_accounts.make_live_session",
                        lambda: session)
    return session


@pytest.fixture
def seeded_provider(webhook_db):
    ExternalProviderRepository(webhook_db).register(
        provider_id=PROVIDER, name="ForTraders",
        provider_type="funded-prop", referral_program="referral",
        tracking_method="referral_code",
        verification_method="verified-provider-purchase",
        referral_reward_product="challenge_basic",
        affiliate_code="GL0TZ8VSBI",
        tracking_url="https://app.fortraders.com/trading/new-challenge",
        supported_venues=["mt5"],
        supported_accounts=["challenge", "demo", "funded"],
        policy_adapter="providers.fortraders:ForTradersProviderAdapter")
    return ExternalProviderRepository(webhook_db).get(PROVIDER)


@pytest.fixture
def pending_code(webhook_db, seeded_provider):
    return ReferralRepository(webhook_db).issue(
        provider_id=PROVIDER, referral_code="FT-WH-1", owner_user_id="sponsor-1")


@pytest.fixture
def enrolled_secret(monkeypatch):
    monkeypatch.setattr(
        "providers.webhooks.vault",
        _FakeVault({webhook_slot(PROVIDER): SECRET}))
    return SECRET


def _payload(*, code="FT-WH-1", reg="REG-1", provider=PROVIDER):
    return {"provider_id": provider, "referral_code": code,
            "external_registration_id": reg}


def _post(client, *, body=None, secret=SECRET, ts=None, provider=PROVIDER,
          signature=None, headers=None):
    ts = int(time.time()) if ts is None else int(ts)
    raw = json.dumps(body if body is not None else _payload()).encode("utf-8")
    sig = signature if signature is not None else sign_payload(
        secret, timestamp=ts, body=raw)
    h = {"X-TAIG-Signature": sig, "X-TAIG-Timestamp": str(ts)}
    if headers:
        h.update(headers)
    return client.post(f"/webhooks/{provider}/referral", content=raw, headers=h)


def test_the_webhook_path_is_open_when_enforcement_is_on(client, webhook_db,
                                                         pending_code,
                                                         enrolled_secret,
                                                         monkeypatch):
    # No session, enforcement on, and no principal: the provider is authenticated
    # by its signature alone, so the call still reaches the handler.
    monkeypatch.setenv("TRADERAIG_AUTH", "1")
    from governance.identity import identity
    from governance.auth import auth
    monkeypatch.setattr(identity, "list_users", lambda: [object()])
    assert auth.enforcement_enabled() is True
    resp = _post(client)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_an_accepted_delivery_records_an_event(client, webhook_db, pending_code,
                                               enrolled_secret):
    resp = _post(client)
    assert resp.status_code == 200
    body = resp.json()
    assert body["reason"] == "accepted"
    assert body["event"]["channel"] == "webhook"
    assert body["is_authorisation"] is False
    assert body["trade_authority"] == "risk/governor.py"


def test_a_resend_is_a_200_duplicate(client, webhook_db, pending_code,
                                     enrolled_secret):
    assert _post(client).status_code == 200
    resp = _post(client)
    assert resp.status_code == 200
    assert resp.json()["reason"] == "duplicate"
    assert resp.json()["duplicate"] is True


def test_a_bad_signature_is_401(client, webhook_db, pending_code,
                                enrolled_secret):
    resp = _post(client, signature="sha256=deadbeef")
    assert resp.status_code == 401
    assert resp.json()["reason"] == "bad_signature"


def test_a_missing_signature_is_401(client, webhook_db, pending_code,
                                    enrolled_secret):
    resp = _post(client, signature="")
    assert resp.status_code == 401


def test_a_stale_timestamp_is_401(client, webhook_db, pending_code,
                                  enrolled_secret):
    raw = json.dumps(_payload()).encode("utf-8")
    old_sig = sign_payload(SECRET, timestamp=1, body=raw)
    resp = client.post(f"/webhooks/{PROVIDER}/referral", content=raw,
                       headers={"X-TAIG-Signature": old_sig,
                                "X-TAIG-Timestamp": "1"})
    assert resp.status_code == 401
    assert resp.json()["reason"] == "stale_timestamp"


def test_an_unconfigured_provider_is_401(client, webhook_db, seeded_provider,
                                         pending_code):
    # No secret enrolled (no `enrolled_secret` fixture): nothing is accepted.
    resp = _post(client)
    assert resp.status_code == 401
    assert resp.json()["reason"] == "no_signing_secret"


def test_an_unknown_code_is_400(client, webhook_db, pending_code,
                                enrolled_secret):
    resp = _post(client, body=_payload(code="FT-NOPE"))
    assert resp.status_code == 400
    assert resp.json()["reason"] == "unknown_code"


def test_a_malformed_body_is_400(client, webhook_db, pending_code,
                                 enrolled_secret):
    ts = int(time.time())
    raw = json.dumps({"provider_id": PROVIDER}).encode("utf-8")
    sig = sign_payload(SECRET, timestamp=ts, body=raw)
    resp = client.post(f"/webhooks/{PROVIDER}/referral", content=raw,
                       headers={"X-TAIG-Signature": sig,
                                "X-TAIG-Timestamp": str(ts)})
    assert resp.status_code == 400
    assert resp.json()["reason"] == "invalid_body"


def test_an_unknown_provider_is_401(client, webhook_db, enrolled_secret):
    body = _payload(provider="ghostfirm")
    resp = _post(client, body=body, provider="ghostfirm")
    assert resp.status_code == 401
    assert resp.json()["reason"] == "unknown_provider"


def test_store_failure_is_503(client, webhook_db, pending_code,
                              enrolled_secret, monkeypatch):
    def _boom():
        raise RuntimeError("store down")

    monkeypatch.setattr("persistence.repositories_accounts.make_live_session",
                        _boom)
    resp = _post(client)
    assert resp.status_code == 503


# --- reads ---------------------------------------------------------------


def test_the_policy_read_is_open_and_carries_no_secret(client):
    body = client.get("/webhooks").json()
    assert body["read_only"] is True
    assert body["signature_header"] == "X-TAIG-Signature"
    assert "accepted" in body["outcomes"]
    assert body["is_authorisation"] is False
    # The scheme is described, but no secret value is present.
    assert SECRET not in json.dumps(body)


def test_the_delivery_log_records_accepted_and_refused(client, webhook_db,
                                                       pending_code,
                                                       enrolled_secret):
    _post(client)                              # accepted
    _post(client, signature="sha256=deadbeef")  # refused
    rows = client.get("/webhooks/deliveries").json()
    assert rows["ok"] is True
    assert rows["read_only"] is True
    outcomes = sorted(r["outcome"] for r in rows["deliveries"])
    assert outcomes == ["accepted", "bad_signature"]
    assert rows["summary"]["accepted"] == 1
    assert rows["is_authorisation"] is False


def test_the_delivery_log_filters_by_outcome(client, webhook_db, pending_code,
                                             enrolled_secret):
    _post(client)
    _post(client, signature="sha256=deadbeef")
    rows = client.get("/webhooks/deliveries?outcome=bad_signature").json()
    assert [r["outcome"] for r in rows["deliveries"]] == ["bad_signature"]
