"""The `/referrals` attribution routes over the real app.

The layer under test is the one the domain tests cannot see: routes that resolve
the acting principal, consult account ownership, and serialise a referral. The
route-specific failures guarded here are:

- a route that mints a code without a principal (`409`), because a sponsor-less
  script would claim sourcing for nobody;
- an attribution that points at somebody else's account (`403`) or at an
  account that does not exist (`404`); the referred person is the account
  registry's recorded owner, never a body-supplied claim;
- reads that publish somebody else's programme (`403`), answered distinct from
  "no such referral" (`404`);
- verify/decline reserved for the code's sponsor, and verify only after an
  attribution (a code without an account cannot be "confirmed");
- a body that reads like an authorisation: every referral payload carries
  `is_authorisation: False` and names the Risk Governor, so "which account came
  from which code" never reads as "this account may trade";
- an unreachable store is `503`, not an empty list or a fake 200;
- the tenancy report truthfully describes the attribution surface.
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
    REFERRAL_ATTRIBUTED,
    REFERRAL_PENDING,
    AccountRegistryRepository,
    ExternalProviderRepository,
)

OPERATOR = "route-referal-1"
OTHER_USER = "route-referal-2"


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture
def referral_db(monkeypatch):
    """The stores the routes build for themselves, on one test session.

    Routes construct `ReferralRepository()`/`AccountRegistryRepository()` with no
    session, so they read the live session held by `persistence.repositories_accounts`.
    Patch the module factory there, exactly the seam the account-route tests use.
    """
    session = bind_test_session()
    for model in (ReferralRecord, AccountRecord, ExternalProviderRecord,
                  ExternalReferralEvent, AccountConnectionRecord,
                  AccountIdentityRecord, AccountStrategyBindingRecord):
        session.execute(delete(model))
    session.commit()
    monkeypatch.setattr("persistence.repositories_accounts.make_live_session",
                        lambda: session)
    return session


@pytest.fixture
def seeded_provider(referral_db):
    ExternalProviderRepository(referral_db).register(
        provider_id="fortraders", name="ForTraders",
        provider_type="funded-prop", referral_program="referral",
        tracking_method="referral_code",
        verification_method="verified-provider-purchase",
        supported_venues=["mt5"],
        supported_accounts=["challenge", "demo", "funded"],
        policy_adapter="providers.fortraders:ForTradersProviderAdapter")
    return ExternalProviderRepository(referral_db).get("fortraders")


@pytest.fixture
def accounts(referral_db, seeded_provider):
    repo = AccountRegistryRepository(referral_db)
    mine = repo.register(venue="mt5", venue_login="REF-A",
                         venue_server="S", owner_user_id=OPERATOR)
    theirs = repo.register(venue="mt5", venue_login="REF-B",
                           venue_server="S", owner_user_id=OTHER_USER)
    return mine, theirs


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


def _seed_referral(client, code="FT-ALICE-1") -> dict:
    """Issue a code through the route, as the acting principal."""
    body = client.post("/referrals", json={
        "provider_id": "fortraders", "referral_code": code,
        "note": "route test"}).json()
    assert body["ok"] is True
    return body["referral"]


def _seed_via_repo(referral_db, code, owner=OTHER_USER) -> dict:
    """Issue a code straight into the shared session (sponsor = `owner`).

    Used only where issuing must not depend on who the route thinks the principal
    is -- e.g. proving that a different sponsor's code is not actionable by the
    acting principal.
    """
    from persistence.repositories_accounts import ReferralRepository

    return ReferralRepository(referral_db).issue(
        provider_id="fortraders", referral_code=code, owner_user_id=owner)


# -- issue ---------------------------------------------------------------


def test_issue_without_a_principal_is_409(client, referral_db,
                                          seeded_provider, no_principal):
    response = client.post("/referrals", json={
        "provider_id": "fortraders", "referral_code": "FT-X"})
    assert response.status_code == 409
    assert response.json()["reason"] == "no_principal"


def test_issue_creates_a_pending_code(client, referral_db, seeded_provider,
                                      acting_as_operator):
    body = client.post("/referrals", json={
        "provider_id": "fortraders", "referral_code": "FT-ALICE"}).json()
    assert body["ok"] is True
    assert body["action"] == "issued"
    referral = body["referral"]
    assert referral["attribution_status"] == REFERRAL_PENDING
    assert referral["owner_user_id"] == OPERATOR
    assert referral["tracking_method"] == "referral_code"
    assert referral["account_id"] is None
    assert body["is_authorisation"] is False
    assert body["trade_authority"] == "risk/governor.py"


def test_issue_sponsor_is_the_server_not_the_body(client, referral_db,
                                                  seeded_provider,
                                                  acting_as_operator):
    body = client.post("/referrals", json={
        "provider_id": "fortraders", "referral_code": "FT-SPOOF",
        "owner_user_id": OTHER_USER}).json()
    assert body["referral"]["owner_user_id"] == OPERATOR


def test_issue_against_an_unregistered_provider_is_400(client, referral_db,
                                                       seeded_provider,
                                                       acting_as_operator):
    response = client.post("/referrals", json={
        "provider_id": "no-such", "referral_code": "FT-X"})
    assert response.status_code == 400
    assert response.json()["reason"] == "invalid_referral"


def test_issue_refuses_a_duplicate_code(client, referral_db, seeded_provider,
                                        acting_as_operator):
    _seed_referral(client, code="FT-DUP-1")
    response = client.post("/referrals", json={
        "provider_id": "fortraders", "referral_code": "FT-DUP-1"})
    assert response.status_code == 400
    assert "already exists" in response.json()["detail"]


def test_issue_fails_closed_on_store_errors(client, referral_db,
                                            seeded_provider,
                                            acting_as_operator, monkeypatch):
    def _boom(*_args, **_kwargs):
        raise RuntimeError("store down")

    monkeypatch.setattr("persistence.repositories_accounts.make_live_session",
                        _boom)
    response = client.post("/referrals", json={
        "provider_id": "fortraders", "referral_code": "FT-X"})
    assert response.status_code == 503


# -- reads ---------------------------------------------------------------


def test_owner_reads_their_own_referral(client, referral_db, seeded_provider,
                                        acting_as_operator):
    referral = _seed_referral(client)
    body = client.get(f"/referrals/{referral['referral_id']}").json()
    assert body["ok"] is True
    assert body["referral"]["referral_code"] == "FT-ALICE-1"
    assert body["referral"]["is_authorisation"] is False
    assert body["read_only"] is True


def test_reading_someone_elses_referral_is_403(client, referral_db,
                                               seeded_provider,
                                               acting_as_operator):
    bob_row = _seed_via_repo(referral_db, "FT-BOB", owner=OTHER_USER)
    response = client.get(f"/referrals/{bob_row['referral_id']}")
    assert response.status_code == 403


def test_an_unknown_referral_is_404(client, referral_db, acting_as_operator):
    response = client.get("/referrals/no-such")
    assert response.status_code == 404
    assert response.json()["reason"] == "unknown_referral"


def test_the_owner_lists_their_referrals_with_a_summary(client, referral_db,
                                                        seeded_provider,
                                                        acting_as_operator):
    _seed_referral(client, code="FT-A-1")
    _seed_referral(client, code="FT-A-2")
    body = client.get(f"/users/{OPERATOR}/referrals").json()
    assert body["ok"] is True
    assert body["count"] == 2
    assert body["by_attribution_status"][REFERRAL_PENDING] == 2
    assert body["is_authorisation"] is False


def test_listing_someone_elses_referrals_is_403(client, referral_db,
                                                seeded_provider,
                                                acting_as_operator):
    response = client.get(f"/users/{OTHER_USER}/referrals")
    assert response.status_code == 403


def test_a_read_fails_closed_on_store_errors(client, referral_db,
                                             acting_as_operator, monkeypatch):
    def _boom(*_args, **_kwargs):
        raise RuntimeError("store down")

    monkeypatch.setattr("persistence.repositories_accounts.make_live_session",
                        _boom)
    response = client.get("/referrals/no-such")
    assert response.status_code == 503


# -- attribute -----------------------------------------------------------


def test_attribute_requires_a_principal(client, referral_db, seeded_provider,
                                        accounts, no_principal):
    referral = _seed_via_repo(referral_db, "FT-A-ATTR", owner=OPERATOR)
    mine, _theirs = accounts
    response = client.post(f"/referrals/{referral['referral_id']}/attribute",
                           json={"account_id": mine["account_id"]})
    assert response.status_code == 409


def test_attribute_links_the_owners_own_account(client, referral_db,
                                                seeded_provider, accounts,
                                                acting_as_operator):
    referral = _seed_referral(client, code="FT-A-ATTR")
    mine, _theirs = accounts
    body = client.post(f"/referrals/{referral['referral_id']}/attribute",
                       json={"account_id": mine["account_id"]}).json()
    assert body["ok"] is True
    assert body["action"] == "attributed"
    assert body["referral"]["attribution_status"] == REFERRAL_ATTRIBUTED
    assert body["referral"]["account_id"] == mine["account_id"]
    assert body["referral"]["referred_user_id"] == OPERATOR
    assert body["is_authorisation"] is False


def test_attribute_refuses_someone_elses_account(client, referral_db,
                                                 seeded_provider, accounts,
                                                 acting_as_operator):
    referral = _seed_referral(client, code="FT-A-ATTR")
    _mine, theirs = accounts
    response = client.post(f"/referrals/{referral['referral_id']}/attribute",
                           json={"account_id": theirs["account_id"]})
    assert response.status_code == 403


def test_attribute_on_an_unknown_account_is_404(client, referral_db,
                                                seeded_provider,
                                                acting_as_operator):
    referral = _seed_referral(client, code="FT-A-ATTR")
    response = client.post(f"/referrals/{referral['referral_id']}/attribute",
                           json={"account_id": "no-such-account"})
    assert response.status_code == 404
    assert response.json()["reason"] == "unknown_account"


def test_attribute_refuses_an_account_already_attributed(client, referral_db,
                                                         seeded_provider,
                                                         accounts,
                                                         acting_as_operator):
    first = _seed_referral(client, code="FT-A-FIRST")
    second = _seed_referral(client, code="FT-A-SECOND")
    mine, _theirs = accounts
    client.post(f"/referrals/{first['referral_id']}/attribute",
                json={"account_id": mine["account_id"]})
    response = client.post(f"/referrals/{second['referral_id']}/attribute",
                           json={"account_id": mine["account_id"]})
    assert response.status_code == 400
    assert "already attributed" in response.json()["detail"]


# -- verify / decline ----------------------------------------------------


def test_verify_is_sponsor_only(client, referral_db, seeded_provider, accounts,
                                acting_as_operator):
    referral = _seed_via_repo(referral_db, "FT-A-VERIFY", owner=OTHER_USER)
    mine, _theirs = accounts
    client.post(f"/referrals/{referral['referral_id']}/attribute",
                json={"account_id": mine["account_id"]})
    response = client.post(f"/referrals/{referral['referral_id']}/verify")
    assert response.status_code == 403


def test_verify_requires_an_attribution_first(client, referral_db,
                                              seeded_provider,
                                              acting_as_operator):
    referral = _seed_referral(client, code="FT-A-VERIFY")
    response = client.post(f"/referrals/{referral['referral_id']}/verify")
    assert response.status_code == 400
    assert "attributed" in response.json()["detail"]


def test_verify_confirms_an_attributed_code(client, referral_db,
                                            seeded_provider, accounts,
                                            acting_as_operator):
    referral = _seed_referral(client, code="FT-A-VERIFY")
    mine, _theirs = accounts
    client.post(f"/referrals/{referral['referral_id']}/attribute",
                json={"account_id": mine["account_id"]})
    body = client.post(f"/referrals/{referral['referral_id']}/verify").json()
    assert body["ok"] is True
    assert body["action"] == "verified"
    assert body["referral"]["attribution_status"] == "verified"
    assert body["referral"]["verified_at"] is not None
    assert body["is_authorisation"] is False


def test_reverify_is_refused(client, referral_db, seeded_provider, accounts,
                             acting_as_operator):
    referral = _seed_referral(client, code="FT-A-VERIFY")
    mine, _theirs = accounts
    client.post(f"/referrals/{referral['referral_id']}/attribute",
                json={"account_id": mine["account_id"]})
    client.post(f"/referrals/{referral['referral_id']}/verify")
    response = client.post(f"/referrals/{referral['referral_id']}/verify")
    assert response.status_code == 400


def test_decline_cancels_a_pending_code(client, referral_db, seeded_provider,
                                        acting_as_operator):
    referral = _seed_referral(client, code="FT-A-DECLINE")
    body = client.post(f"/referrals/{referral['referral_id']}/decline").json()
    assert body["ok"] is True
    assert body["referral"]["attribution_status"] == "declined"


def test_decline_is_sponsor_only(client, referral_db, seeded_provider,
                                 acting_as_operator):
    referral = _seed_via_repo(referral_db, "FT-A-DECLINE", owner=OTHER_USER)
    response = client.post(f"/referrals/{referral['referral_id']}/decline")
    assert response.status_code == 403


def test_verify_and_decline_of_unknown_is_404(client, referral_db,
                                              acting_as_operator):
    assert client.post("/referrals/no-such/verify").status_code == 404
    assert client.post("/referrals/no-such/decline").status_code == 404


# -- tenancy -------------------------------------------------------------


def test_the_tenancy_report_describes_the_attribution_surface(client):
    body = client.get("/system/health").json()["tenancy"]
    assert "POST /referrals" in body["referral_attribution"]
    assert "is_authorisation: False" in body["referral_attribution"]
    assert any("referral" in entry for entry in body["ownership_enforced_on"])
    assert "POST /referrals/{referral_id}/attribute" in \
        " ".join(body["ownership_enforced_on"])
