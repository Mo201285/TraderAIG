"""The commercial-offer routes (Phase G, S3), asserted over the real app.

The failure these guard is the one the whole slice exists to prevent: a client
route that acts for a user other than the caller, an admin route reachable
without the acting principal's authority, or a redemption that grants a benefit
it should not (before verification, twice, or on a fabricated offer).

`GET /offers`, `POST /offers`, `PUT /offers/{id}` and `POST /offers/{id}/status`
are the operator surface; `GET /offers/available`, `GET /me/redemptions` and
`POST /offers/{id}/redeem` are the client surface and resolve the user from the
acting principal -- never from the request.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from operations.api import app  # noqa: E402
from persistence.db import bind_test_session  # noqa: E402
from persistence.models_accounts import (  # noqa: E402
    ExternalProviderRecord,
    ReferralRecord,
)
from persistence.models_offers import (  # noqa: E402
    CommercialOfferRecord,
    OfferRedemptionRecord,
)
from persistence.repositories_accounts import (  # noqa: E402
    ExternalProviderRepository,
    ReferralRepository,
)

OPERATOR = "offers-route-op"


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture
def store(monkeypatch):
    session = bind_test_session()
    for model in (CommercialOfferRecord, OfferRedemptionRecord,
                  ExternalProviderRecord, ReferralRecord):
        session.execute(delete(model))
    session.commit()
    monkeypatch.setattr("persistence.repositories_accounts.make_live_session",
                        lambda: session)
    monkeypatch.setattr("persistence.repositories_offers.make_live_session",
                        lambda: session)
    ExternalProviderRepository(session).register(
        provider_id="fortraders", name="ForTraders",
        provider_type="funded-prop", referral_program="referral",
        tracking_method="referral_code",
        verification_method="verified-provider-purchase",
        referral_reward_product="challenge_basic",
        supported_venues=["mt5"],
        supported_accounts=["challenge", "demo", "funded"])
    ReferralRepository(session).issue(
        provider_id="fortraders", referral_code="FT-ROUTE-1",
        owner_user_id=OPERATOR)
    return session


@pytest.fixture
def acting_as_operator(monkeypatch):
    """An ACTIVE institutional principal, so `_guard(API_ACCESS)` passes.

    Inserted into the identity service itself (not monkeypatched behind it),
    because `_guard` calls `identity.can(actor, ...)`, which reads the real
    in-memory user map, and the product grant at redemption resolves the same
    user. State is saved and restored so a sibling suite keeps clean.
    """
    import governance.identity as gov
    from governance.identity import SubscriptionPlan

    idents = gov.identity
    saved = (dict(idents._users), dict(idents._subscriptions), list(idents._audit))
    idents._users = {}
    idents._subscriptions = {}
    idents._audit = []

    user = idents.create_user(f"{OPERATOR}@x.co", "Offer operator")
    idents.activate_subscription(user.user_id, SubscriptionPlan.INSTITUTIONAL)

    monkeypatch.setattr("operations.api.identity.principal_user_id",
                        lambda: user.user_id)
    yield user.user_id
    idents._users, idents._subscriptions, idents._audit = saved


def _create_offer(client, **overrides):
    body = {"title": "Free challenge management", "provider_id": "fortraders",
            "grant_kind": "product", "grant_ref": "challenge_basic",
            "referral_code": "FT-ROUTE-1"}
    body.update(overrides)
    return client.post("/offers", json=body)


# -- admin surface --------------------------------------------------------


def test_create_offer_requires_the_operator(client, store, acting_as_operator):
    r = _create_offer(client)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["offer"]["provider_id"] == "fortraders"
    assert body["is_authorisation"] is False


def test_create_offer_refuses_a_missing_principal(client, store, monkeypatch):
    import governance.identity as gov
    monkeypatch.setattr("operations.api.identity.principal_user_id", lambda: None)
    gov.identity._users = {}
    r = _create_offer(client)
    assert r.status_code == 409


def test_create_offer_refuses_a_bad_body(client, store, acting_as_operator):
    r = _create_offer(client, grant_kind="crypto", grant_ref="x")
    assert r.status_code == 400


def test_list_offers_is_read_only_and_global(client, store, acting_as_operator):
    _create_offer(client)
    r = client.get("/offers")
    assert r.status_code == 200
    assert r.json()["count"] == 1
    assert r.json()["is_authorisation"] is False


def test_update_and_status_offer(client, store, acting_as_operator):
    offer_id = _create_offer(client).json()["offer"]["offer_id"]
    r = client.put(f"/offers/{offer_id}", json={"title": "Renamed"})
    assert r.status_code == 200
    assert r.json()["offer"]["title"] == "Renamed"
    r = client.post(f"/offers/{offer_id}/status", json={"status": "paused"})
    assert r.status_code == 200
    assert r.json()["offer"]["status"] == "paused"


def test_status_on_unknown_offer_is_404(client, store, acting_as_operator):
    r = client.post("/offers/nope/status", json={"status": "paused"})
    assert r.status_code == 404


# -- client surface -------------------------------------------------------


def test_available_lists_an_eligible_offer(client, store, acting_as_operator):
    offer_id = _create_offer(client).json()["offer"]["offer_id"]
    r = client.get("/offers/available")
    assert r.status_code == 200
    ids = [o["offer_id"] for o in r.json()["eligible"]]
    assert offer_id in ids


def test_redeem_grants_and_is_idempotent(client, store, acting_as_operator):
    offer_id = _create_offer(client).json()["offer"]["offer_id"]
    first = client.post(f"/offers/{offer_id}/redeem")
    assert first.status_code == 200
    assert first.json()["status"] == "granted"
    second = client.post(f"/offers/{offer_id}/redeem")
    assert second.json()["status"] == "granted"
    # One redemption row only.
    from sqlalchemy import select
    rows = store.execute(select(OfferRedemptionRecord)).scalars().all()
    assert len(rows) == 1


def test_redeem_requires_verification_grants_nothing(client, store,
                                                     acting_as_operator):
    offer_id = _create_offer(
        client, conditions={"requires_verification": True}
    ).json()["offer"]["offer_id"]
    r = client.post(f"/offers/{offer_id}/redeem")
    assert r.status_code == 200
    assert r.json()["status"] == "pending"
    assert r.json()["granted"] is False


def test_my_redemptions_lists_only_the_caller(client, store, acting_as_operator):
    offer_id = _create_offer(client).json()["offer"]["offer_id"]
    client.post(f"/offers/{offer_id}/redeem")
    r = client.get("/me/redemptions")
    assert r.status_code == 200
    assert r.json()["count"] == 1


def test_client_routes_resolve_the_actor_not_a_body(client, store,
                                                    acting_as_operator):
    """`/me/redemptions` answers only for the acting principal.

    There is no user id in the path or body to spoof -- the route takes none --
    so the response can only ever be the caller's own redemptions.
    """
    r = client.get("/me/redemptions")
    assert r.status_code == 200
    assert r.json()["user_id"] == acting_as_operator
