"""The `/referral-events` routes over the real app, plus the reward on verify.

The layer under test is the one the domain tests cannot see: routes that
resolve the acting principal, gate event attribution on account ownership, and
serialise the reward consequence of a verified referral. The route-specific
failures guarded here are:

- an event cannot be recorded without a principal (`409`), against an unknown
  code, a code that already moved on, or a duplicate registration (all `400`);
- attribution of an event needs the account's recorded owner (`403`) and an
  account that exists (`404`) -- the same ownership gate as referrals;
- event reads are scoped to the code's sponsor or the referred user (`403`),
  distinct from "no such event" (`404`);
- verification of a rewarding programme grants the product exactly once and
  the response reports it in an additive `reward` block; a programme without a
  reward contract still verifies with `reward.granted: False` and an empty
  status;
- every event and reward payload carries `is_authorisation: False` and names
  the Risk Governor;
- an unreachable store is `503`, not an empty result or a fake 200;
- the tenancy report truthfully describes the rewards surface.
"""

from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from operations.api import app  # noqa: E402
from persistence.db import bind_test_session  # noqa: E402
from persistence.models_accounts import (  # noqa: E402
    AccountConnectionRecord,
    AccountIdentityRecord,
    AccountRecord,
    ExternalProviderRecord,
    ExternalReferralEvent,
    ReferralRecord,
)
from persistence.models_trades import AccountStrategyBindingRecord  # noqa: E402
from persistence.repositories_accounts import (  # noqa: E402
    ExternalProviderRepository,
)

OPERATOR = "route-event-1"
OTHER_USER = "route-event-2"


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture
def referral_db(monkeypatch):
    session = bind_test_session()
    for model in (ReferralRecord, ExternalReferralEvent, AccountRecord,
                  AccountConnectionRecord, AccountIdentityRecord,
                  AccountStrategyBindingRecord, ExternalProviderRecord):
        session.execute(delete(model))
    session.commit()
    monkeypatch.setattr("persistence.repositories_accounts.make_live_session",
                        lambda: session)
    return session


@pytest.fixture(autouse=True)
def _restore_process_state():
    """`_full_loop` invents identity users and grants entitlements; restore the
    process-wide registries so later files (subscription lifecycle, execution
    gate) start with no acting principal left behind -- first-created-user-wins
    must not leak across a test file."""
    from governance.identity import identity
    from governance.products import products

    users = dict(identity._users)
    subs = dict(identity._subscriptions)
    bought = dict(products._entitlements)
    try:
        yield
    finally:
        identity._users.clear()
        identity._users.update(users)
        identity._subscriptions.clear()
        identity._subscriptions.update(subs)
        products._entitlements.clear()
        products._entitlements.update(bought)


@pytest.fixture
def seeded_provider(referral_db):
    ExternalProviderRepository(referral_db).register(
        provider_id="fortraders", name="ForTraders",
        provider_type="funded-prop", referral_program="referral",
        tracking_method="referral_code",
        verification_method="verified-provider-purchase",
        referral_reward_product="challenge_basic",
        supported_venues=["mt5"],
        supported_accounts=["challenge", "demo", "funded"],
        policy_adapter="providers.fortraders:ForTradersProviderAdapter")
    return ExternalProviderRepository(referral_db).get("fortraders")


@pytest.fixture
def accounts(referral_db, seeded_provider):
    from persistence.repositories_accounts import AccountRegistryRepository

    repo = AccountRegistryRepository(referral_db)
    mine = repo.register(venue="mt5", venue_login="EVT-A",
                         venue_server="S", owner_user_id=OPERATOR)
    theirs = repo.register(venue="mt5", venue_login="EVT-B",
                           venue_server="S", owner_user_id=OTHER_USER)
    return mine, theirs


def _as(monkeypatch, user: str):
    monkeypatch.setattr("operations.api.identity.principal_user_id",
                        lambda: user)
    return user


@pytest.fixture
def acting_as_operator(monkeypatch):
    monkeypatch.setattr("operations.api.identity.principal_user_id",
                        lambda: OPERATOR)
    return OPERATOR


@pytest.fixture
def no_principal(monkeypatch):
    monkeypatch.setattr("operations.api.identity.principal_user_id",
                        lambda: None)
    return None


def _seed_code(client, *, code="FT-EVT-1", headers=None):
    body = client.post("/referrals", json={
        "provider_id": "fortraders", "referral_code": code,
        "note": "route event test"}, headers=headers).json()
    assert body["ok"] is True
    return body["referral"]


def _seed_code_via_repo(referral_db, *, code="FT-EVT-1",
                        owner=OPERATOR) -> dict:
    """Seed a code without depending on who the route thinks the principal is."""
    from persistence.repositories_accounts import ReferralRepository

    return ReferralRepository(referral_db).issue(
        provider_id="fortraders", referral_code=code, owner_user_id=owner)


def _record_event_via_repo(referral_db, referral, *, reg="REG-1") -> dict:
    from persistence.repositories_accounts import ReferralEventRepository

    return ReferralEventRepository(referral_db).record(
        provider_id="fortraders", referral_code=referral["referral_code"],
        external_registration_id=reg, referral_id=referral["referral_id"])


def _record_event(client, *, code="FT-EVT-1", reg="REG-1", headers=None):
    body = client.post("/referral-events", json={
        "provider_id": "fortraders", "referral_code": code,
        "external_registration_id": reg}, headers=headers).json()
    assert body["ok"] is True
    return body["event"]


# -- record event ---------------------------------------------------------


def test_event_intake_requires_a_principal(client, referral_db, seeded_provider,
                                           no_principal):
    _seed_code_via_repo(referral_db)
    response = client.post("/referral-events", json={
        "provider_id": "fortraders", "referral_code": "FT-EVT-1",
        "external_registration_id": "REG-X"})
    assert response.status_code == 409
    assert response.json()["reason"] == "no_principal"


def test_event_intake_records_a_registration(client, referral_db,
                                             seeded_provider,
                                             acting_as_operator):
    code = _seed_code(client)
    body = client.post("/referral-events", json={
        "provider_id": "fortraders", "referral_code": "FT-EVT-1",
        "external_registration_id": "REG-1"}).json()
    assert body["ok"] is True
    assert body["action"] == "received"
    assert body["event"]["event_status"] == "received"
    assert body["event"]["referral_id"] == code["referral_id"]
    assert body["event"]["reward_product"] == "challenge_basic"
    assert body["is_authorisation"] is False
    assert body["trade_authority"] == "risk/governor.py"


def test_event_intake_refuses_a_duplicate_registration(client, referral_db,
                                                       seeded_provider,
                                                       acting_as_operator):
    _seed_code(client)
    _record_event(client)
    response = client.post("/referral-events", json={
        "provider_id": "fortraders", "referral_code": "FT-EVT-1",
        "external_registration_id": "REG-1"})
    assert response.status_code == 400
    assert "already recorded" in response.json()["detail"]


def test_event_intake_refuses_an_unknown_code(client, referral_db,
                                              seeded_provider,
                                              acting_as_operator):
    response = client.post("/referral-events", json={
        "provider_id": "fortraders", "referral_code": "FT-NOPE",
        "external_registration_id": "REG-9"})
    assert response.status_code == 400
    assert "not issued" in response.json()["detail"]


def test_event_intake_refuses_an_unused_code_body(client, referral_db,
                                                  seeded_provider,
                                                  acting_as_operator):
    response = client.post("/referral-events", json={})
    assert response.status_code == 400
    assert response.json()["reason"] == "invalid_event"


def test_event_intake_fails_closed_on_store_errors(client, referral_db,
                                                   seeded_provider,
                                                   acting_as_operator,
                                                   monkeypatch):
    _seed_code(client)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("store down")

    monkeypatch.setattr("persistence.repositories_accounts.make_live_session",
                        _boom)
    response = client.post("/referral-events", json={
        "provider_id": "fortraders", "referral_code": "FT-EVT-1",
        "external_registration_id": "REG-X"})
    assert response.status_code == 503


# -- attribute event ------------------------------------------------------


def test_event_attribute_requires_a_principal(client, referral_db,
                                              seeded_provider,
                                              no_principal):
    referral = _seed_code_via_repo(referral_db)
    event = _record_event_via_repo(referral_db, referral)
    response = client.post(
        f"/referral-events/{event['event_id']}/attribute",
        json={"account_id": "any-account"})
    assert response.status_code == 409


def test_event_attribute_binds_an_own_account(client, referral_db,
                                              seeded_provider, accounts,
                                              acting_as_operator):
    _seed_code(client)
    event = _record_event(client)
    mine, _theirs = accounts
    body = client.post(f"/referral-events/{event['event_id']}/attribute",
                       json={"account_id": mine["account_id"]}).json()
    assert body["ok"] is True
    assert body["action"] == "attributed"
    assert body["event"]["event_status"] == "attributed"
    assert body["event"]["referred_user_id"] == OPERATOR
    assert body["event"]["account_id"] == mine["account_id"]
    assert body["is_authorisation"] is False


def test_event_attribute_refuses_someone_elses_account(client, referral_db,
                                                       seeded_provider,
                                                       accounts,
                                                       acting_as_operator):
    _seed_code(client)
    event = _record_event(client)
    _mine, theirs = accounts
    response = client.post(f"/referral-events/{event['event_id']}/attribute",
                           json={"account_id": theirs["account_id"]})
    assert response.status_code == 403


def test_event_attribute_on_an_unknown_account_is_404(client, referral_db,
                                                      seeded_provider,
                                                      acting_as_operator):
    _seed_code(client)
    event = _record_event(client)
    response = client.post(f"/referral-events/{event['event_id']}/attribute",
                           json={"account_id": "no-such-account"})
    assert response.status_code == 404
    assert response.json()["reason"] == "unknown_account"


def test_event_attribute_refuses_a_second_attribution(client, referral_db,
                                                      seeded_provider,
                                                      accounts,
                                                      acting_as_operator):
    _seed_code(client)
    event = _record_event(client)
    mine, _theirs = accounts
    client.post(f"/referral-events/{event['event_id']}/attribute",
                json={"account_id": mine["account_id"]})
    response = client.post(f"/referral-events/{event['event_id']}/attribute",
                           json={"account_id": mine["account_id"]})
    assert response.status_code == 400


# -- event reads ----------------------------------------------------------


def test_the_sponsor_reads_their_event(client, referral_db, seeded_provider,
                                       acting_as_operator):
    _seed_code(client)
    event = _record_event(client)
    body = client.get(f"/referral-events/{event['event_id']}").json()
    assert body["ok"] is True
    assert body["event"]["external_registration_id"] == "REG-1"
    assert body["read_only"] is True
    assert body["is_authorisation"] is False


def test_a_stranger_read_is_403(client, referral_db, seeded_provider,
                                accounts, acting_as_operator, monkeypatch):
    _seed_code(client)
    event = _record_event(client)
    _as(monkeypatch, OTHER_USER)
    response = client.get(f"/referral-events/{event['event_id']}")
    assert response.status_code == 403


def test_an_unknown_event_is_404(client, referral_db, acting_as_operator):
    response = client.get("/referral-events/no-such")
    assert response.status_code == 404
    assert response.json()["reason"] == "unknown_event"


# -- the reward on verify -------------------------------------------------


def _full_loop(client, monkeypatch):
    """Sponsor issues; referred user (a real identity) attributes an owned
    account; sponsor verifies; the response carries the grant.

    Two real identities exist here, so slice I4 makes the box multi-tenant and
    turns enforcement on: every call carries the acting user's session, which is
    the shape a real deployment has (and the stronger claim -- the refusal paths
    are then ownership gates, not auth gates).
    """
    from governance.identity import identity as identity_svc

    sponsor = identity_svc.create_user("rwr-sponsor@x.co", "Sponsor").user_id
    referred = identity_svc.create_user("rwr-referred@x.co", "Referred").user_id
    sponsor_h = _session(sponsor)
    referred_h = _session(referred)
    _as(monkeypatch, sponsor)
    code = _seed_code(client, code="FT-FULL", headers=sponsor_h)
    event = _record_event(client, code="FT-FULL", reg="REG-FULL",
                          headers=sponsor_h)
    from persistence.repositories_accounts import AccountRegistryRepository

    repo = AccountRegistryRepository()
    mine = repo.register(venue="mt5", venue_login="EVT-FULL",
                         venue_server="S", owner_user_id=referred)
    _as(monkeypatch, referred)
    client.post(f"/referral-events/{event['event_id']}/attribute",
                json={"account_id": mine["account_id"]}, headers=referred_h)
    _as(monkeypatch, sponsor)
    return client.post(f"/referrals/{code['referral_id']}/verify",
                       headers=sponsor_h), referred


def _session(user_id: str) -> dict:
    """A session for `user_id`, satisfying I4's multi-tenant enforcement."""
    from governance.auth import auth as auth_svc
    from governance.identity import identity
    identity.set_password(user_id, "ref-session-password-123")
    return {"Authorization": f"Bearer {auth_svc.issue(user_id)[0]}"}


def test_verify_grants_the_promised_product(client, referral_db,
                                            seeded_provider, monkeypatch):
    response, referred = _full_loop(client, monkeypatch)
    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "verified"
    reward = body["reward"]
    assert reward["granted"] is True
    assert reward["reward_status"] == "issued"
    assert reward["reward_product"] == "challenge_basic"
    assert reward["is_authorisation"] is False
    # The grant actually opened service access for the referred user.
    from governance.identity import Entitlement
    from governance.products import products

    assert products.has(referred, Entitlement.CHALLENGE_MANAGEMENT) is True


def test_verify_does_not_double_grant(client, referral_db, seeded_provider,
                                      monkeypatch):
    response, referred = _full_loop(client, monkeypatch)
    body = response.json()
    assert body["reward"]["reward_status"] == "issued"
    second = client.post(
        f"/referrals/{body['referral']['referral_id']}/verify",
        headers=_session(body["referral"]["owner_user_id"]))
    assert second.status_code == 400


def test_verify_without_a_reward_contract_reports_nothing_promised(
        client, referral_db, seeded_provider, accounts, acting_as_operator,
        monkeypatch):
    # Re-register the programme without a reward product; the loop still works
    # and verification succeeds -- the reward block says nothing was promised.
    ExternalProviderRepository(referral_db).register(
        provider_id="fortraders", name="ForTraders",
        provider_type="funded-prop", referral_program="referral",
        tracking_method="referral_code",
        verification_method="verified-provider-purchase",
        referral_reward_product="", supported_venues=["mt5"],
        supported_accounts=["challenge", "demo", "funded"],
        policy_adapter="providers.fortraders:ForTradersProviderAdapter")
    code = _seed_code(client)
    event = _record_event(client)
    mine, _theirs = accounts
    client.post(f"/referral-events/{event['event_id']}/attribute",
                json={"account_id": mine["account_id"]})
    body = client.post(f"/referrals/{code['referral_id']}/verify").json()
    assert body["action"] == "verified"
    reward = body["reward"]
    assert reward["granted"] is False
    assert reward["reward_status"] == ""
    assert "no reward product" in reward["error_detail"]


# -- tenancy -------------------------------------------------------------


def test_the_tenancy_report_describes_the_rewards_surface(client):
    body = client.get("/system/health").json()["tenancy"]
    assert "POST /referral-events" in body["referral_rewards"]
    assert "is_authorisation: False" in body["referral_rewards"]
    assert any("referral-events" in entry
               for entry in body["ownership_enforced_on"])
