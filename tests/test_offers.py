"""Commercial offers: the operator-authored campaign and its redemption (G1/G2).

This suite pins the properties that keep an offer a *commercial* mechanism and
never a trade permission, and the ones that keep a redemption honest under
retry and concurrency:

- neither table carries a trade-permission column and neither carries a foreign
  key, asserted by inspection -- absence is a fact, not a docstring (rows
  741/742/744/745; MAST 34.18);
- `(offer_id, user_id)` is unique, so "one user uses one offer once" is enforced
  by the database and a retried `redeem` cannot double-grant;
- an offer may only cite a *real* provider and a *real* issued referral code,
  and its grant target must exist in the catalogue / plan set -- a fabricated
  benefit is refused at creation;
- eligibility is a per-(user, offer) verdict that names *why* a user is excluded
  (window, status, cap, already-redeemed, plan) and never discloses another
  user's data;
- opening a link is not a purchase: an offer requiring verification records a
  `pending` redemption and grants nothing;
- a grant goes through exactly one legal channel (`products.grant` or
  `identity.activate_subscription`), and a plan-granting offer that would take an
  entitlement away is declined rather than silently stripping authority;
- every outgoing payload carries `is_authorisation: False` and names the Risk
  Governor;
- a failed store lookup raises (fail-closed).
"""

from pathlib import Path
import sys

import pytest
from sqlalchemy import delete, inspect

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from governance.identity import (  # noqa: E402
    Entitlement,
    SubscriptionPlan,
    SubscriptionStatus,
    identity,
)
from governance.products import get_product, products  # noqa: E402
from persistence.db import bind_test_session  # noqa: E402
from persistence.models_offers import (  # noqa: E402
    CommercialOfferRecord,
    OfferRedemptionRecord,
)
from persistence.models_accounts import (  # noqa: E402
    ExternalProviderRecord,
    ReferralRecord,
)
from persistence.repositories_accounts import (  # noqa: E402
    ExternalProviderRepository,
    ReferralRepository,
)
from persistence.repositories_offers import (  # noqa: E402
    OfferRedemptionRepository,
    OfferRepository,
)
from offers.eligibility import OfferService, offer_window  # noqa: E402

SPONSOR = "offers-sponsor"


@pytest.fixture
def session():
    s = bind_test_session()
    for model in (CommercialOfferRecord, OfferRedemptionRecord,
                  ExternalProviderRecord, ReferralRecord):
        s.execute(delete(model))
    s.commit()
    return s


@pytest.fixture(autouse=True)
def _restore_process_state():
    """Leave the process-wide identity/product registries as found.

    A grant resolves the user in `identity._users` (the `products.grant` gate
    checks the in-memory store, not a `UserRecord` row), so this file creates
    real users and grants real entitlements. Restoring keeps a sibling suite
    from inheriting a principal or a bought product.
    """
    users = dict(identity._users)
    subs = dict(identity._subscriptions)
    audit = list(identity._audit)
    bought = dict(products._entitlements)
    try:
        yield
    finally:
        identity._users.clear()
        identity._users.update(users)
        identity._subscriptions.clear()
        identity._subscriptions.update(subs)
        identity._audit[:] = audit
        products._entitlements.clear()
        products._entitlements.update(bought)


@pytest.fixture
def provider(session):
    ExternalProviderRepository(session).register(
        provider_id="fortraders", name="ForTraders",
        provider_type="funded-prop", referral_program="referral",
        tracking_method="referral_code",
        verification_method="verified-provider-purchase",
        referral_reward_product="challenge_basic",
        supported_venues=["mt5"],
        supported_accounts=["challenge", "demo", "funded"],
        policy_adapter="providers.fortraders:ForTradersProviderAdapter")
    return ExternalProviderRepository(session).get("fortraders")


@pytest.fixture
def referral_code(session, provider):
    ReferralRepository(session).issue(
        provider_id="fortraders", referral_code="FT-OFFER-1",
        owner_user_id=SPONSOR)
    return "FT-OFFER-1"


@pytest.fixture
def offers(session):
    return OfferService(
        offer_repo=OfferRepository(session),
        redemption_repo=OfferRedemptionRepository(session),
        provider_repo=ExternalProviderRepository(session),
        referral_repo=ReferralRepository(session))


def _user(plan=SubscriptionPlan.FREE, status=SubscriptionStatus.ACTIVE):
    """A real identity user, so a grant resolves and lost-entitlements is real.

    Built through `identity.create_user` (which installs a real `Subscription`
    object -- `activate_subscription` mutates that object, so a hand-rolled user
    with no subscription would fail the grant) and then activated to the wanted
    plan, so `identity.activate_subscription` has a well-formed target.
    """
    user = identity.create_user(f"offer-{plan.value}-{status.value}@x.co",
                                f"Offer {plan.value}")
    identity.activate_subscription(user.user_id, plan)
    if status is not SubscriptionStatus.ACTIVE:
        user.subscription_status = status
    return user


def _offer(offers, code, **kw):
    payload = {"title": "Free challenge management", "provider_id": "fortraders",
               "grant_kind": "product", "grant_ref": "challenge_basic",
               "referral_code": code}
    payload.update(kw)
    return offers.create(**payload)["offer"]


# -- schema ---------------------------------------------------------------


def test_tables_exist_and_carry_no_fk():
    s = bind_test_session()
    tables = set(inspect(s.get_bind()).get_table_names())
    assert {"commercial_offers", "offer_redemptions"} <= tables
    for model in (CommercialOfferRecord, OfferRedemptionRecord):
        assert [c for c in model.__table__.columns
                if list(c.foreign_keys)] == []


def test_the_tables_never_claim_trade_permission():
    for model in (CommercialOfferRecord, OfferRedemptionRecord):
        cols = {c.name for c in model.__table__.columns}
        for forbidden in ("grants_trade_permission", "may_trade", "can_trade"):
            assert forbidden not in cols


def test_redemption_uniqueness_is_declared():
    names = {uc.name for uc in OfferRedemptionRecord.__table__.constraints
             if getattr(uc, "name", None)}
    assert "uq_offer_redemption_offer_user" in names


# -- creation validation --------------------------------------------------


def test_create_refuses_an_unknown_provider(offers, referral_code):
    with pytest.raises(ValueError, match="no registered provider"):
        _offer(offers, referral_code, provider_id="ghost")


def test_create_refuses_a_code_not_issued(offers, referral_code):
    with pytest.raises(ValueError, match="not issued"):
        _offer(offers, referral_code, referral_code="FT-NOPE")


def test_create_refuses_an_unknown_product(offers, referral_code):
    with pytest.raises(ValueError, match="unknown product"):
        _offer(offers, referral_code, grant_ref="not_a_product")


def test_create_refuses_an_unknown_plan(offers, referral_code):
    with pytest.raises(ValueError, match="unknown plan"):
        _offer(offers, referral_code, grant_kind="plan", grant_ref="diamond")


def test_create_refuses_an_unknown_grant_kind(offers, referral_code):
    with pytest.raises(ValueError, match="grant_kind must be"):
        _offer(offers, referral_code, grant_kind="crypto", grant_ref="x")


def test_create_records_an_offer_with_is_authorisation_false(
        offers, referral_code):
    body = offers.create(title="Free challenge management",
                         provider_id="fortraders", grant_kind="product",
                         grant_ref="challenge_basic", referral_code=referral_code)
    assert body["offer"]["provider_id"] == "fortraders"
    assert body["offer"]["grant_kind"] == "product"
    assert body["is_authorisation"] is False
    assert body["trade_authority"] == "risk/governor.py"


# -- eligibility ----------------------------------------------------------


def test_available_lists_an_open_offer_as_eligible(offers, referral_code):
    o = _offer(offers, referral_code)
    user = _user()
    view = offers.available_for(user.user_id)
    ids = [e["offer_id"] for e in view["eligible"]]
    assert o["offer_id"] in ids
    assert view["ineligible"] == []
    assert view["is_authorisation"] is False


def test_available_excludes_a_paused_offer_with_a_reason(offers, referral_code):
    o = _offer(offers, referral_code)
    offers.set_status(o["offer_id"], "paused")
    user = _user()
    view = offers.available_for(user.user_id)
    assert view["eligible"] == []
    assert view["ineligible"][0]["reason"] == "offer_not_active"


def test_a_future_offer_is_not_started(offers, referral_code):
    _offer(offers, referral_code, starts_at=9_999_999_999.0)
    user = _user()
    entry = offers.available_for(user.user_id)["ineligible"][0]
    assert entry["reason"] == "offer_not_started"


def test_an_expired_offer_is_expired(offers, referral_code):
    _offer(offers, referral_code, starts_at=1.0, ends_at=2.0)
    user = _user()
    entry = offers.available_for(user.user_id)["ineligible"][0]
    assert entry["reason"] == "offer_expired"


def test_allowed_plans_excludes_a_free_user(offers, referral_code):
    _offer(offers, referral_code, conditions={"allowed_plans": ["pro"]})
    user = _user(plan=SubscriptionPlan.FREE)
    entry = offers.available_for(user.user_id)["ineligible"][0]
    assert entry["reason"] == "plan_not_allowed"


def test_min_plan_excludes_a_lower_plan(offers, referral_code):
    _offer(offers, referral_code, conditions={"min_plan": "pro"})
    user = _user(plan=SubscriptionPlan.FREE)
    entry = offers.available_for(user.user_id)["ineligible"][0]
    assert entry["reason"] == "plan_not_allowed"


def test_offer_window_pure():
    assert offer_window({"starts_at": 0, "ends_at": 0}) == "open"
    assert offer_window({"starts_at": 9_999_999_999, "ends_at": 0}) == "not_started"
    assert offer_window({"starts_at": 0, "ends_at": 1}) == "expired"
    assert offer_window({"starts_at": 1, "ends_at": 9_999_999_999}) == "open"


# -- redemption: the grant path ------------------------------------------


def test_redeem_grants_a_product_and_records_granted(offers, referral_code):
    o = _offer(offers, referral_code)
    user = _user()
    result = offers.redeem(user.user_id, o["offer_id"])
    assert result["status"] == "granted"
    assert result["granted"] is True
    assert result["is_authorisation"] is False
    # The product entitlement is really on the user.
    assert products.has(user.user_id, Entitlement.CHALLENGE_MANAGEMENT)
    assert get_product("challenge_basic") is not None


def test_redeem_without_verification_requires_verification(offers, referral_code):
    o = _offer(offers, referral_code,
               conditions={"requires_verification": True})
    user = _user()
    result = offers.redeem(user.user_id, o["offer_id"])
    assert result["status"] == "pending"
    assert result["granted"] is False
    assert result["reason"] == "verification_required"
    # Nothing was granted.
    assert not products.has(user.user_id, Entitlement.CHALLENGE_MANAGEMENT)


def test_redeem_is_idempotent(offers, referral_code):
    o = _offer(offers, referral_code)
    user = _user()
    first = offers.redeem(user.user_id, o["offer_id"])
    second = offers.redeem(user.user_id, o["offer_id"])
    assert first["status"] == "granted"
    assert second["status"] == "granted"
    assert second.get("redeemed") is True
    # Only one redemption row exists.
    assert OfferRedemptionRepository(
        bind_test_session()).count_for_offer(o["offer_id"]) == 1


def test_redeem_of_unknown_offer_declines(offers, referral_code):
    user = _user()
    result = offers.redeem(user.user_id, "nope")
    assert result["status"] == "declined"
    assert result["reason"] == "offer_unknown"


def test_redeem_exhausted_offer_declines(offers, referral_code):
    o = _offer(offers, referral_code, max_redemptions=1)
    first = _user(plan=SubscriptionPlan.PRO)
    second = _user(plan=SubscriptionPlan.FREE)
    assert offers.redeem(first.user_id, o["offer_id"])["status"] == "granted"
    result = offers.redeem(second.user_id, o["offer_id"])
    assert result["status"] == "declined"
    assert result["reason"] == "offer_exhausted"


def test_redeem_refuses_when_plan_not_allowed(offers, referral_code):
    o = _offer(offers, referral_code, conditions={"allowed_plans": ["pro"]})
    user = _user(plan=SubscriptionPlan.FREE)
    result = offers.redeem(user.user_id, o["offer_id"])
    assert result["status"] == "declined"
    assert result["reason"] == "plan_not_allowed"


# -- plan grants ----------------------------------------------------------


def test_redeem_grants_a_plan_and_persists_it(offers, referral_code):
    o = _offer(offers, referral_code, grant_kind="plan", grant_ref="pro")
    user = _user(plan=SubscriptionPlan.FREE)
    result = offers.redeem(user.user_id, o["offer_id"])
    assert result["status"] == "granted"
    assert result["entitlement_ref"] == "pro"
    assert identity.get_user(user.user_id).plan == SubscriptionPlan.PRO


def test_a_plan_offer_may_only_upgrade(offers, referral_code):
    """Granting a lower plan would strip entitlements; the offer declines."""
    o = _offer(offers, referral_code, grant_kind="plan", grant_ref="free")
    user = _user(plan=SubscriptionPlan.INSTITUTIONAL)
    result = offers.redeem(user.user_id, o["offer_id"])
    assert result["status"] == "declined"
    assert result["reason"] == "grant_would_downgrade"
    # The institutional entitlements are untouched.
    assert identity.get_user(user.user_id).plan == SubscriptionPlan.INSTITUTIONAL


# -- fail-closed ----------------------------------------------------------


def test_a_store_error_raises_rather_than_reporting_no_offers(monkeypatch):
    def _boom(*_a, **_k):
        raise RuntimeError("store down")

    service = OfferService(offer_repo=OfferRepository())
    monkeypatch.setattr(service._offers, "list_all", _boom)
    with pytest.raises(RuntimeError, match="store down"):
        service.available_for("anyone")
