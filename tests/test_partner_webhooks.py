"""The inbound partner webhook seam (G4): signature, intake, and the log.

The T2 referral loop already had an event store and an operator intake route
(`POST /referral-events`); G4 adds the *channel* a real partner uses -- a signed
webhook. The two things that must be true and are easy to get subtly wrong are
tested here at the domain layer, without a route:

- a delivery is authenticated by an HMAC over the raw body plus a timestamp, so
  a forged body, a wrong secret, a missing signature and a replayed timestamp are
  each refused with their own reason -- and an unconfigured provider (no secret
  enrolled) accepts *nothing*;
- an authenticated delivery records exactly the registration event the manual
  route would (`channel="webhook"`), a re-send is a truthful `duplicate` rather
  than a second event, and an accepted delivery grants nothing and verifies
  nothing -- `is_authorisation: False`, the Risk Governor still the only trade
  authority;
- every attempt -- accepted, duplicate or refused -- leaves a delivery row, so
  the partner's traffic is observable instead of silently swallowed;
- the signing secret lives in the vault as `webhook.<provider>.signing_secret`
  and is never enumerated by `list_slots()` (a provider roster does not belong
  on the shared status endpoint).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import delete

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.secrets_vault import (  # noqa: E402
    SecretsVault,
    is_known_slot,
    parse_dynamic_slot,
    webhook_slot,
)
from persistence.db import bind_test_session  # noqa: E402
from persistence.models_accounts import (  # noqa: E402
    ExternalProviderRecord,
    ExternalReferralEvent,
    ProviderWebhookDelivery,
    ReferralRecord,
)
from persistence.repositories_accounts import (  # noqa: E402
    ExternalProviderRepository,
    ProviderWebhookDeliveryRepository,
    ReferralEventRepository,
    ReferralRepository,
)
from providers.webhooks import (  # noqa: E402
    WebhookService,
    sign_payload,
    verify_signature,
)

PROVIDER = "fortraders"
CODE = "FT-WH-1"
SECRET = "wh-test-secret-0123456789"


class _FakeVault:
    """A dict-backed stand-in for SecretsVault (the real one is DPAPI-only).

    Mirrors what the vault would reject -- only known slot names are accepted --
    so a typo'd slot is caught here exactly as the real vault would catch it.
    """

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def set(self, slot: str, value: str) -> None:
        if not is_known_slot(slot):
            raise KeyError(f"unknown slot {slot!r}")
        self._store[slot] = value

    def resolve(self, slot: str) -> str:
        return self._store.get(slot, "")

    def exists(self, slot: str) -> bool:
        return slot in self._store


@pytest.fixture
def session():
    s = bind_test_session()
    for model in (ReferralRecord, ExternalReferralEvent,
                  ProviderWebhookDelivery, ExternalProviderRecord):
        s.execute(delete(model))
    s.commit()
    return s


@pytest.fixture
def seeded_provider(session):
    ExternalProviderRepository(session).register(
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
    return ExternalProviderRepository(session).get(PROVIDER)


@pytest.fixture
def pending_code(session, seeded_provider):
    return ReferralRepository(session).issue(
        provider_id=PROVIDER, referral_code=CODE, owner_user_id="sponsor-1")


@pytest.fixture
def fvault():
    v = _FakeVault()
    v.set(webhook_slot(PROVIDER), SECRET)
    return v


@pytest.fixture
def service(session, fvault, pending_code):
    return WebhookService(
        provider_repo=ExternalProviderRepository(session),
        referral_repo=ReferralRepository(session),
        event_repo=ReferralEventRepository(session),
        delivery_repo=ProviderWebhookDeliveryRepository(session),
        vault_obj=fvault)


def _body(*, code=CODE, reg="REG-1", provider=PROVIDER):
    return json.dumps({"provider_id": provider, "referral_code": code,
                       "external_registration_id": reg}).encode("utf-8")


def _deliver(service, *, body=None, secret=SECRET, timestamp=1_700_000_000,
             now=1_700_000_000, signature=None, provider=PROVIDER):
    body = body if body is not None else _body()
    sig = signature if signature is not None else sign_payload(
        secret, timestamp=timestamp, body=body)
    return service.deliver(provider, body=body, signature=sig,
                           timestamp=timestamp, now=now)


# --- signature primitive -------------------------------------------------


def test_sign_and_verify_round_trip():
    body = _body()
    sig = sign_payload(SECRET, timestamp=1_700_000_000, body=body)
    assert sig.startswith("sha256=")
    assert verify_signature(SECRET, timestamp=1_700_000_000, body=body,
                            signature=sig, now=1_700_000_000) == ""


def test_verify_refuses_a_missing_signature():
    body = _body()
    assert verify_signature(SECRET, timestamp=1_700_000_000, body=body,
                            signature="", now=1_700_000_000) == "missing_signature"


def test_verify_refuses_a_stale_timestamp():
    body = _body()
    sig = sign_payload(SECRET, timestamp=1_700_000_000, body=body)
    assert verify_signature(SECRET, timestamp=1_700_000_000, body=body,
                            signature=sig, now=1_700_000_400) == "stale_timestamp"


def test_verify_refuses_a_wrong_secret():
    body = _body()
    sig = sign_payload("other-secret", timestamp=1_700_000_000, body=body)
    assert verify_signature(SECRET, timestamp=1_700_000_000, body=body,
                            signature=sig, now=1_700_000_000) == "bad_signature"


def test_verify_refuses_a_tampered_body():
    sig = sign_payload(SECRET, timestamp=1_700_000_000, body=_body(reg="REG-1"))
    tampered = _body(reg="REG-2")
    assert verify_signature(SECRET, timestamp=1_700_000_000, body=tampered,
                            signature=sig, now=1_700_000_000) == "bad_signature"


# --- vault slot family ---------------------------------------------------


def test_webhook_slot_is_a_known_dynamic_slot():
    slot = webhook_slot(PROVIDER)
    assert slot == "webhook.fortraders.signing_secret"
    assert is_known_slot(slot)
    parts = parse_dynamic_slot(slot)
    assert parts and parts["kind"] == "webhook"
    assert parts["provider_id"] == "fortraders"
    assert parts["field"] == "signing_secret"


def test_webhook_slot_rejects_a_bad_provider_id():
    with pytest.raises(ValueError):
        webhook_slot("Fort Traders!")


def test_webhook_slots_are_not_enumerated_on_the_status_endpoint(tmp_path):
    # A fresh vault's catalog listing must not include any webhook slot, even
    # after one is written: the roster of partners does not belong on the shared
    # `/secrets/status` endpoint.
    v = SecretsVault(data_dir=tmp_path)
    if not v.is_persistable():
        pytest.skip("DPAPI backend unavailable on this platform")
    v.set(webhook_slot(PROVIDER), SECRET)
    listed = v.list_slots()
    assert not any(slot.startswith("webhook.") for slot in listed)


# --- intake --------------------------------------------------------------


def test_a_valid_delivery_records_an_event(service, session, pending_code):
    result = _deliver(service)
    assert result["ok"] is True
    assert result["reason"] == "accepted"
    assert result["is_authorisation"] is False
    assert result["trade_authority"] == "risk/governor.py"
    event = result["event"]
    assert event["event_status"] == "received"
    assert event["channel"] == "webhook"
    assert event["external_registration_id"] == "REG-1"
    assert event["reward_product"] == "challenge_basic"
    # The event really is in the store, not just in the returned dict.
    stored = ReferralEventRepository(session).by_referral(event["referral_id"])
    assert stored is not None and stored["event_id"] == event["event_id"]


def test_a_valid_delivery_leaves_an_accepted_row(service, session):
    result = _deliver(service)
    rows = ProviderWebhookDeliveryRepository(session).list_all()
    assert len(rows) == 1
    assert rows[0]["outcome"] == "accepted"
    assert rows[0]["event_id"] == result["event"]["event_id"]
    assert rows[0]["signature_status"] == "ok"


def test_a_resend_is_a_duplicate_not_a_second_event(service, session):
    first = _deliver(service)
    again = _deliver(service)
    assert first["ok"] is True
    assert again["ok"] is False
    assert again["reason"] == "duplicate"
    assert again.get("duplicate") is True
    events = ReferralEventRepository(session).list_all()
    assert len(events) == 1
    outcomes = [r["outcome"]
                for r in ProviderWebhookDeliveryRepository(session).list_all()]
    assert outcomes == ["accepted", "duplicate"]


def test_an_unknown_provider_is_refused_and_recorded(service, session):
    body = _body(provider="ghostfirm")
    result = service.deliver("ghostfirm", body=body,
                             signature=sign_payload(SECRET, timestamp=1, body=body),
                             timestamp=1, now=1)
    assert result["ok"] is False
    assert result["reason"] == "unknown_provider"
    assert ProviderWebhookDeliveryRepository(session).list_all()[0]["outcome"] \
        == "unknown_provider"


def test_a_provider_without_a_secret_accepts_nothing(session, pending_code):
    # A service whose vault has no secret for the provider.
    service = WebhookService(
        provider_repo=ExternalProviderRepository(session),
        referral_repo=ReferralRepository(session),
        event_repo=ReferralEventRepository(session),
        delivery_repo=ProviderWebhookDeliveryRepository(session),
        vault_obj=_FakeVault())
    result = _deliver(service)
    assert result["ok"] is False
    assert result["reason"] == "no_signing_secret"
    assert ReferralEventRepository(session).list_all() == []
    assert ProviderWebhookDeliveryRepository(session).list_all()[0][
        "signature_status"] == "no_secret"


def test_a_bad_signature_is_refused_and_recorded(service, session):
    result = _deliver(service, signature="sha256=deadbeef")
    assert result["ok"] is False
    assert result["reason"] == "bad_signature"
    assert ReferralEventRepository(session).list_all() == []
    row = ProviderWebhookDeliveryRepository(session).list_all()[0]
    assert row["outcome"] == "bad_signature"
    assert row["signature_status"] == "bad_signature"


def test_a_stale_delivery_is_refused_and_recorded(service, session):
    result = _deliver(service, timestamp=1_700_000_000, now=1_700_001_000)
    assert result["ok"] is False
    assert result["reason"] == "stale_timestamp"
    assert ProviderWebhookDeliveryRepository(session).list_all()[0]["outcome"] \
        == "stale_timestamp"


def test_a_missing_signature_is_refused(service):
    result = _deliver(service, signature="")
    assert result["ok"] is False
    assert result["reason"] == "missing_signature"


def test_a_body_without_fields_is_refused(service, session):
    body = json.dumps({"provider_id": PROVIDER}).encode("utf-8")
    result = _deliver(service, body=body)
    assert result["ok"] is False
    assert result["reason"] == "invalid_body"
    assert ProviderWebhookDeliveryRepository(session).list_all()[0]["outcome"] \
        == "invalid_body"


def test_a_body_naming_another_provider_is_refused(service, session):
    body = _body(provider="somebodyelse")
    result = _deliver(service, body=body)
    assert result["ok"] is False
    assert result["reason"] == "invalid_body"


def test_an_unknown_code_is_refused_and_recorded(service, session):
    result = _deliver(service, body=_body(code="FT-NOPE"))
    assert result["ok"] is False
    assert result["reason"] == "unknown_code"
    assert ReferralEventRepository(session).list_all() == []
    assert ProviderWebhookDeliveryRepository(session).list_all()[0]["outcome"] \
        == "unknown_code"


def test_delivery_never_grants_or_verifies(service, session):
    _deliver(service)
    events = ReferralEventRepository(session).list_all()
    assert events[0]["event_status"] == "received"
    # Nothing was attributed, no reward was issued -- the webhook is intake only.
    assert events[0]["reward_status"] == ""
    assert events[0]["referred_user_id"] == ""


# --- reads ---------------------------------------------------------------


def test_deliveries_read_filters_by_provider_and_outcome(service, session):
    _deliver(service)
    _deliver(service)  # duplicate
    rows = service.deliveries(provider_id=PROVIDER, outcome="duplicate")
    assert len(rows) == 1
    assert rows[0]["outcome"] == "duplicate"
    assert rows[0]["is_authorisation"] is False


def test_summary_counts_outcomes(service):
    _deliver(service)
    _deliver(service)
    summary = service.summary(service.deliveries())
    assert summary["count"] == 2
    assert summary["accepted"] == 1
    assert summary["by_outcome"] == {"accepted": 1, "duplicate": 1}
    assert summary["is_authorisation"] is False
    assert summary["trade_authority"] == "risk/governor.py"


def test_has_signing_secret_reports_without_leaking(service, fvault):
    assert service.has_signing_secret(PROVIDER) is True
    assert service.has_signing_secret("ghostfirm") is False


def test_seed_registers_the_public_tracking_coordinates(seeded_provider):
    row = seeded_provider
    assert row["affiliate_code"] == "GL0TZ8VSBI"
    assert row["tracking_url"].startswith("https://app.fortraders.com")
    # The public coordinates are not a secret; the signing secret is elsewhere.
    assert "signing_secret" not in row
