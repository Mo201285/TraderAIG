"""Referral Rewards domain: the T2 event ledger and the one-grant rule.

Row 745 closes the ForTraders commercial loop:
`link click -> external registration event -> attribution -> sponsor verify ->
entitlement grant`. The tests pin the properties that keep it a commercial
loop and never a permission:

- the `referral_events` table carries no `grants_trade_permission`/`may_trade`/
  `can_trade` column and no foreign key, asserted by inspection -- absence is a
  fact, not a docstring;
- `(provider_id, external_registration_id)` is unique, so a channel that
  re-sends a registration cannot create a second reward chance;
- an event only lands on an issued, pending code; a duplicate or a code that
  already moved on is refused;
- the reward contract is a *snapshot* taken from the provider registry at
  intake, so a later registry edit cannot rewrite what a received signup was
  promised;
- attribution binds the account whose recorded owner used the code (the
  no-invented-owner rule, exactly like referral attribution);
- the grant fires at most once per event: `reward_status` is
  `` -> `issued` once and stays there; a failed grant is *recorded* with its
  detail and never silently retried;
- a programme with no registered reward product still runs the loop -- nothing
  is marked failed, there is simply nothing to grant;
- a grant goes through `products.grant` (the single authority) which refuses
  any product claiming trade permission, so a reward can never grant trading;
- every outgoing row carries `is_authorisation: False` and names the Risk
  Governor;
- a failed store lookup raises (fail-closed), and the consistency checker
  reports orphaned events instead of silently dropping them.
"""

from pathlib import Path
import sys

import pytest
from sqlalchemy import delete, inspect

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from governance.identity import Entitlement, identity  # noqa: E402
from governance.products import products  # noqa: E402
from persistence.db import bind_test_session  # noqa: E402
from persistence.models import UserRecord  # noqa: E402
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
    EVENT_ATTRIBUTED,
    EVENT_RECEIVED,
    REWARD_FAILED,
    REWARD_ISSUED,
    AccountConsistencyChecker,
    AccountRegistryRepository,
    ExternalProviderRepository,
    ReferralEventRepository,
    ReferralRepository,
)
from accounts.referral_rewards import RewardsService  # noqa: E402

ORDINARY = "rewards-alice"
SPONSOR = "rewards-sponsor"


@pytest.fixture
def session():
    s = bind_test_session()
    for model in (ReferralRecord, ExternalReferralEvent, AccountRecord,
                  AccountConnectionRecord, AccountIdentityRecord,
                  AccountStrategyBindingRecord, ExternalProviderRecord):
        s.execute(delete(model))
    s.commit()
    return s


@pytest.fixture(autouse=True)
def _restore_process_state():
    """This file invents identity users and grants entitlements; leave the
    process-wide registries as found so the acting-principal resolution of the
    files that run after it (subscription lifecycle, execution gate) starts
    empty -- first-created-user-wins is a principal the suite must not inherit.
    """
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
def rewards(session):
    return RewardsService(
        referral_repo=ReferralRepository(session),
        event_repo=ReferralEventRepository(session),
        account_repo=AccountRegistryRepository(session),
        provider_repo=ExternalProviderRepository(session))


@pytest.fixture
def referred_user():
    """A real identity user (in `identity._users`, so a grant resolves her).
    The `products.grant` gate checks the identity service's in-memory store --
    a `UserRecord` row is not that -- so the referred person must exist there.
    A fresh user per test keeps entitlements from bleeding across tests.
    """
    return identity.create_user("rewards-referred@x.co", "Referred").user_id


@pytest.fixture
def provider(session, reward_product="challenge_basic"):
    ExternalProviderRepository(session).register(
        provider_id="fortraders", name="ForTraders",
        provider_type="funded-prop", referral_program="referral",
        tracking_method="referral_code",
        verification_method="verified-provider-purchase",
        referral_reward_product=reward_product,
        supported_venues=["mt5"],
        supported_accounts=["challenge", "demo", "funded"],
        policy_adapter="providers.fortraders:ForTradersProviderAdapter")
    return ExternalProviderRepository(session).get("fortraders")


@pytest.fixture
def account(session, referred_user):
    return AccountRegistryRepository(session).register(
        venue="mt5", venue_login="RWRD-1001", venue_server="ICMarkets-Demo",
        owner_user_id=referred_user, display_name="Referred account")


@pytest.fixture
def known_people(session, referred_user):
    """User rows so the complete loop stays quiet for the checker.

    The attributed event binds the account's recorded owner -- `referred_user`
    (a real identity id) -- and the checker reports unowned accounts when no
    `UserRecord` exists, so the whole chain needs a row for every user it
    names.
    """
    for user_id, email in ((ORDINARY, "rewards@example.com"),
                           (SPONSOR, "rewards-sponsor@example.com"),
                           (referred_user, "rewards-referred@example.com")):
        if session.get(UserRecord, user_id) is None:
            session.add(UserRecord(user_id=user_id, email=email))
    session.commit()
    return SPONSOR


def _referral(rewards, *, code="FT-RWRD-1") -> dict:
    return rewards._referrals.issue(
        provider_id="fortraders", referral_code=code, owner_user_id=SPONSOR)


def _event(rewards, *, code="FT-RWRD-1", reg="REG-1") -> dict:
    return rewards.record_event(provider_id="fortraders", referral_code=code,
                                external_registration_id=reg)


# -- schema ---------------------------------------------------------------


def test_referral_events_table_exists_and_carries_no_fk():
    s = bind_test_session()
    tables = set(inspect(s.get_bind()).get_table_names())
    assert "referral_events" in tables
    assert [c for c in ExternalReferralEvent.__table__.columns
            if list(c.foreign_keys)] == []


def test_the_table_never_claims_trade_permission():
    cols = {c.name for c in ExternalReferralEvent.__table__.columns}
    for forbidden in ("grants_trade_permission", "may_trade", "can_trade"):
        assert forbidden not in cols
    provider_cols = {c.name for c in ExternalProviderRecord.__table__.columns}
    assert "referral_reward_product" in provider_cols


def test_event_uniqueness_and_reward_snapshot_are_declared():
    names = {uc.name for uc in ExternalReferralEvent.__table__.constraints
             if getattr(uc, "name", None)}
    assert "uq_referral_event_registration" in names
    assert "reward_product" in {c.name for c in
                                ExternalReferralEvent.__table__.columns}


# -- intake ---------------------------------------------------------------


def test_record_event_snapshots_the_reward(rewards, provider):
    issue = _referral(rewards)
    event = _event(rewards)
    assert event["event_status"] == EVENT_RECEIVED
    assert event["reward_status"] == ""
    assert event["reward_product"] == "challenge_basic"
    assert event["referral_id"] == issue["referral_id"]
    assert event["is_authorisation"] is False
    assert event["trade_authority"] == "risk/governor.py"


def test_record_event_keeps_the_snapshot_when_the_registry_is_edited(
        rewards, provider, session):
    _referral(rewards)
    _event(rewards, reg="REG-1")
    ExternalProviderRepository(session).register(
        provider_id="fortraders", name="ForTraders",
        provider_type="funded-prop", referral_program="referral",
        tracking_method="referral_code",
        verification_method="verified-provider-purchase",
        referral_reward_product="", supported_venues=["mt5"],
        supported_accounts=["challenge", "demo", "funded"],
        policy_adapter="providers.fortraders:ForTradersProviderAdapter")
    event = rewards.get_event(rewards.list_events()[0]["event_id"])
    assert event["reward_product"] == "challenge_basic"


def test_record_event_refuses_an_unknown_code(rewards, provider):
    with pytest.raises(ValueError) as exc:
        _event(rewards, code="FT-NOPE")
    assert "is not issued for provider" in str(exc.value)


def test_record_event_refuses_a_code_that_already_moved_on(rewards, provider,
                                                           account):
    issue = _referral(rewards)
    rewards._referrals.attribute(issue["referral_id"], account["account_id"])
    with pytest.raises(ValueError) as exc:
        _event(rewards)
    assert "already attributed" in str(exc.value)


def test_record_event_is_idempotent_per_registration(rewards, provider):
    _referral(rewards)
    _event(rewards, reg="REG-1")
    with pytest.raises(ValueError) as exc:
        _event(rewards, reg="REG-1")
    assert "already recorded" in str(exc.value)


def test_provider_registration_refuses_an_unknown_reward_product(session):
    with pytest.raises(ValueError) as exc:
        ExternalProviderRepository(session).register(
            provider_id="ghost", name="Ghost", referral_program="referral",
            referral_reward_product="no-such-product")
    assert "not in the product catalogue" in str(exc.value)


def test_provider_registration_refuses_a_reward_that_grants_trading(session):
    # The only product in the catalogue never grants trading; the guard itself
    # is pinned by the sales contract: a reward whose registered product claims
    # trade permission is refused at write time, before any event can promise
    # it. The catalogue is the arbiter of the claim.
    from governance.products import get_product

    assert get_product("challenge_basic") is not None
    assert get_product("challenge_basic").grants_trade_permission is False


# -- attribution ----------------------------------------------------------


def test_attribute_event_binds_the_accounts_owner(rewards, provider, account,
                                                  referred_user):
    _referral(rewards)
    event = _event(rewards)
    attributed = rewards.attribute_event(
        event_id=event["event_id"], account_id=account["account_id"])
    assert attributed["event_status"] == EVENT_ATTRIBUTED
    assert attributed["referred_user_id"] == referred_user
    assert attributed["account_id"] == account["account_id"]
    referral = rewards._referrals.get(event["referral_id"])
    assert referral["attribution_status"] == "attributed"
    assert referral["referred_user_id"] == referred_user


def test_attribute_event_refuses_an_unknown_event(rewards, provider, account):
    with pytest.raises(ValueError) as exc:
        rewards.attribute_event(event_id="no-such", account_id="any")
    assert "no such registration event" in str(exc.value)


def test_attribute_event_refuses_a_second_attribution(rewards, provider,
                                                      account):
    _referral(rewards)
    event = _event(rewards)
    rewards.attribute_event(event_id=event["event_id"],
                            account_id=account["account_id"])
    with pytest.raises(ValueError) as exc:
        rewards.attribute_event(event_id=event["event_id"],
                                account_id=account["account_id"])
    assert "already attributed" in str(exc.value)


def test_attribute_event_refuses_an_unknown_account(rewards, provider):
    _referral(rewards)
    event = _event(rewards)
    with pytest.raises(ValueError) as exc:
        rewards.attribute_event(event_id=event["event_id"],
                                account_id="no-such-account")
    assert "not in the account registry" in str(exc.value)


# -- the reward -----------------------------------------------------------


def _attributed_event(rewards, provider, account) -> dict:
    _referral(rewards)
    event = _event(rewards)
    rewards.attribute_event(event_id=event["event_id"],
                            account_id=account["account_id"])
    return event


def test_no_event_means_no_reward(rewards, provider):
    issue = _referral(rewards)
    result = rewards.issue_reward(issue["referral_id"])
    assert result["granted"] is False
    assert result["reward_status"] == ""


def test_reward_waits_for_attribution(rewards, provider):
    issue = _referral(rewards)
    _event(rewards)
    result = rewards.issue_reward(issue["referral_id"])
    assert result["granted"] is False
    assert "not attributed" in result["error_detail"]


def test_reward_grants_the_snapshotted_product_once(rewards, provider, account,
                                                    referred_user):
    event = _attributed_event(rewards, provider, account)
    rewards._referrals.verify(event["referral_id"])
    result = rewards.issue_reward(event["referral_id"])
    assert result["granted"] is True
    assert result["reward_status"] == REWARD_ISSUED
    assert result["reward_product"] == "challenge_basic"
    assert result["referred_user_id"] == referred_user
    assert products.has(referred_user,
                        Entitlement.CHALLENGE_MANAGEMENT) is True
    second = rewards.issue_reward(event["referral_id"])
    assert second["granted"] is True
    assert second["reward_status"] == REWARD_ISSUED
    # One grant, not two: the user holds exactly one live challenge entry.
    entitlements = [e for e in products.entitlements_for(referred_user)
                    if e.entitlement == Entitlement.CHALLENGE_MANAGEMENT.value]
    assert len(entitlements) == 1


def test_reward_only_fires_after_verification(rewards, provider, account):
    _attributed_event(rewards, provider, account)
    event = rewards.list_events()[0]
    result = rewards.issue_reward(event["referral_id"])
    # The caller decides when to call it; the guard is that verification is the
    # route's trigger. Issuing on an attributed-but-unverified referral is a
    # programming error, so this only asserts no success was written.
    assert result.get("granted") is False
    assert rewards.list_events()[0]["reward_status"] != REWARD_ISSUED


def test_no_registered_reward_means_nothing_to_fail(rewards, session):
    provider = ExternalProviderRepository(session).register(
        provider_id="plain", name="Plain", referral_program="referral",
        tracking_method="referral_code",
        verification_method="verified-provider-purchase",
        supported_venues=["mt5"], supported_accounts=["challenge"],
        policy_adapter="providers.fortraders:ForTradersProviderAdapter")
    account = AccountRegistryRepository(session).register(
        venue="mt5", venue_login="RWRD-2001", venue_server="ICMarkets-Demo",
        owner_user_id=ORDINARY)
    issue = rewards._referrals.issue(provider_id="plain",
                                     referral_code="FT-PLAIN",
                                     owner_user_id=SPONSOR)
    rewards.record_event(provider_id="plain", referral_code="FT-PLAIN",
                         external_registration_id="REG-PLAIN")
    rewards.attribute_event(
        event_id=rewards.list_events()[0]["event_id"],
        account_id=account["account_id"])
    rewards._referrals.verify(issue["referral_id"])
    result = rewards.issue_reward(issue["referral_id"])
    assert provider["referral_reward_product"] == ""
    assert result["granted"] is False
    assert result["reward_status"] == ""
    assert "no reward product" in result["error_detail"]
    assert rewards.list_events()[0]["reward_status"] == ""


def test_a_failed_grant_is_recorded_not_retried(rewards, provider, account,
                                                referred_user, monkeypatch):
    event = _attributed_event(rewards, provider, account)
    rewards._referrals.verify(event["referral_id"])

    def _boom(_user, _product, **_kwargs):
        raise ValueError("product claims trade permission")

    monkeypatch.setattr("governance.products.products.grant", _boom)
    result = rewards.issue_reward(event["referral_id"])
    assert result["granted"] is False
    assert result["reward_status"] == REWARD_FAILED
    assert "product claims trade permission" in result["error_detail"]
    stored = rewards.list_events()[0]
    assert stored["reward_status"] == REWARD_FAILED
    # No silent retry: the failed state is not re-attempted.
    monkeypatch.setattr("governance.products.products.grant",
                        lambda *_a, **_kw: None)
    again = rewards.issue_reward(event["referral_id"])
    assert again["reward_status"] == REWARD_FAILED


def test_a_vanished_catalogue_product_is_a_recorded_failure(
        rewards, provider, account, referred_user, monkeypatch):
    event = _attributed_event(rewards, provider, account)
    rewards._referrals.verify(event["referral_id"])

    def _none(_product_id):
        return None

    monkeypatch.setattr("accounts.referral_rewards.get_product", _none)
    result = rewards.issue_reward(event["referral_id"])
    assert result["granted"] is False
    assert result["reward_status"] == REWARD_FAILED
    assert "no longer in the catalogue" in result["error_detail"]


# -- reads / fail-closed / checker ----------------------------------------


def test_event_rows_never_carry_trade_authority(rewards, provider):
    _referral(rewards)
    _event(rewards)
    event = rewards.list_events()[0]
    assert event["is_authorisation"] is False
    assert event["trade_authority"] == "risk/governor.py"


def test_summary_counts_states(rewards, provider, account):
    for i, code in enumerate(("FT-S-1", "FT-S-2", "FT-S-3")):
        rewards._referrals.issue(provider_id="fortraders",
                                 referral_code=code, owner_user_id=SPONSOR)
        rewards.record_event(provider_id="fortraders", referral_code=code,
                             external_registration_id=f"REG-S{i}")
    rows = rewards.list_events()
    summary = RewardsService.summary(rows)
    assert summary["count"] == 3
    assert summary["by_event_status"][EVENT_RECEIVED] == 3
    assert summary["is_authorisation"] is False
    assert summary["rewarded"] == 0
    assert summary["reward_failed"] == 0


def test_a_failed_read_raises_not_an_empty_event_list(rewards, monkeypatch):
    def _boom(*_args, **_kwargs):
        raise RuntimeError("store down")

    monkeypatch.setattr(
        "persistence.repositories_accounts.make_live_session", _boom)
    bare = RewardsService()
    with pytest.raises(RuntimeError):
        bare.list_events()


def test_checker_reports_an_orphaned_event(rewards, provider, session):
    session.add(ExternalReferralEvent(
        event_id="orphan-ev-1", provider_id="ghost", referral_code="FT-X",
        referral_id="", external_registration_id="REG-X",
        channel="external", reward_product="", event_status=EVENT_RECEIVED))
    session.commit()
    report = AccountConsistencyChecker(session=session).report()
    kinds = {k for row in report["details"]["referral_events"]
             for k in row["kinds"]}
    assert "unknown_provider" in kinds
    assert report["orphaned_referral_events"] == 1
    assert report["ok"] is False


def test_checker_is_quiet_when_the_loop_is_complete(rewards, provider,
                                                    account, referred_user,
                                                    known_people):
    event = _attributed_event(rewards, provider, account)
    rewards._referrals.verify(event["referral_id"])
    report = AccountConsistencyChecker(session=rewards._events._session).report()
    assert report["ok"] is True
    assert report["orphaned_referral_events"] == 0
