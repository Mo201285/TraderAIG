"""Referral Attribution domain: repository lifecycle and the P2 chain rules.

`referrals` is the first link of the provenance chain row 744 records:
`Referral -> Provider Registry -> Account Registry -> ... -> Entitlement`. The
tests pin the properties that keep it provenance rather than permission:

- the `referrals` table carries no `grants_trade_permission`/`may_trade`/`can_trade`
  column and no foreign key, asserted by inspection -- absence is a fact, not a
  docstring;
- a code may only be issued against a provider that is IN the registry AND has
  a registered referral programme (the registry is the single owner of that
  fact);
- an attribution may only name the account registry's recorded owner as the
  referred person -- the body cannot invent who an account belongs to;
- the lifecycle `pending -> attributed -> verified | declined` is enforced:
  verify requires an attributed code and is final; decline never touches a
  verified row; delete exists only for never-attributed codes;
- a failed lookup raises (fail-closed), never an empty attribution list.
"""

from pathlib import Path
import sys

import pytest
from sqlalchemy import delete, inspect

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
    REFERRAL_ATTRIBUTED,
    REFERRAL_DECLINED,
    REFERRAL_PENDING,
    REFERRAL_VERIFIED,
    AccountConsistencyChecker,
    AccountRegistryRepository,
    ExternalProviderRepository,
    ReferralRepository,
)
from accounts.referral_attribution import (  # noqa: E402
    ReferralAttribution,
)


@pytest.fixture
def session():
    # Every table the AccountConsistencyChecker audits lives in the shared
    # StaticPool test database; a row left by ANY earlier file makes a
    # quiet-checker report "ok: false". Clear the whole family here, not just
    # the tables this file writes.
    s = bind_test_session()
    for model in (ReferralRecord, ExternalReferralEvent, AccountRecord,
                  AccountConnectionRecord, AccountIdentityRecord,
                  AccountStrategyBindingRecord, ExternalProviderRecord):
        s.execute(delete(model))
    s.commit()
    return s


@pytest.fixture
def repo(session):
    return ReferralRepository(session)


@pytest.fixture
def provider(session):
    ExternalProviderRepository(session).register(
        provider_id="fortraders", name="ForTraders",
        provider_type="funded-prop", referral_program="referral",
        tracking_method="referral_code",
        verification_method="verified-provider-purchase",
        supported_venues=["mt5"],
        supported_accounts=["challenge", "demo", "funded"],
        policy_adapter="providers.fortraders:ForTradersProviderAdapter")
    return ExternalProviderRepository(session).get("fortraders")


@pytest.fixture
def account(session):
    return AccountRegistryRepository(session).register(
        venue="mt5", venue_login="1001", venue_server="ICMarkets-Demo",
        owner_user_id="alice", display_name="Alice's account")


@pytest.fixture
def alice_user(session):
    """The sponsor as a real identity row, so a complete chain stays quiet."""
    if session.get(UserRecord, "alice") is None:
        session.add(UserRecord(user_id="alice", email="alice@example.com"))
        session.commit()
    return "alice"


def _issue(repo, *, provider_id="fortraders", code="FT-ALICE-1",
           owner="alice", note=""):
    return repo.issue(provider_id=provider_id, referral_code=code,
                      owner_user_id=owner, note=note)


# -- schema ---------------------------------------------------------------


def test_referrals_table_exists_and_carries_no_fk():
    s = bind_test_session()
    tables = set(inspect(s.get_bind()).get_table_names())
    assert "referrals" in tables
    assert [c for c in ReferralRecord.__table__.columns
            if list(c.foreign_keys)] == []


def test_the_table_never_claims_trade_permission():
    cols = {c.name for c in ReferralRecord.__table__.columns}
    for forbidden in ("grants_trade_permission", "may_trade", "can_trade"):
        assert forbidden not in cols


def test_uniqueness_rules_are_declared():
    names = {uc.name for uc in ReferralRecord.__table__.constraints
             if getattr(uc, "name", None)}
    assert "uq_referral_provider_code" in names
    assert "uq_referral_provider_account" in names


# -- issuing --------------------------------------------------------------


def test_issue_snapshots_the_provider_contract(repo, provider):
    row = _issue(repo)
    assert row["attribution_status"] == REFERRAL_PENDING
    assert row["owner_user_id"] == "alice"
    assert row["account_id"] is None
    assert row["referred_user_id"] is None
    assert row["tracking_method"] == "referral_code"
    assert row["verification_method"] == "verified-provider-purchase"
    assert row["provider_id"] == "fortraders"
    assert row["referral_code"] == "FT-ALICE-1"


def test_issue_refuses_a_provider_outside_the_registry(repo, provider):
    with pytest.raises(ValueError) as exc:
        _issue(repo, provider_id="no-such")
    assert "in the external provider registry" in str(exc.value)


def test_issue_refuses_a_provider_with_no_referral_programme(repo, provider):
    ExternalProviderRepository(repo._session).register(
        provider_id="plain", name="Plain", provider_type="broker",
        referral_program="", tracking_method="",
        verification_method="",
        policy_adapter="providers.fortraders:ForTradersProviderAdapter")
    with pytest.raises(ValueError) as exc:
        _issue(repo, provider_id="plain")
    assert "no referral programme" in str(exc.value)


def test_issue_refuses_empty_identity_facts(repo, provider):
    with pytest.raises(ValueError):
        _issue(repo, provider_id="")
    with pytest.raises(ValueError):
        _issue(repo, code="")
    with pytest.raises(ValueError):
        _issue(repo, owner="")


def test_issue_refuses_a_duplicate_code_within_a_programme(repo, provider):
    _issue(repo)
    with pytest.raises(ValueError) as exc:
        _issue(repo)
    assert "already exists for provider" in str(exc.value)


def test_get_and_get_by_code_roundtrip(repo, provider):
    issued = _issue(repo)
    assert repo.get(issued["referral_id"])["referral_code"] == "FT-ALICE-1"
    got = repo.get_by_code("fortraders", "FT-ALICE-1")
    assert got["referral_id"] == issued["referral_id"]
    assert repo.get("no-such") is None
    assert repo.get_by_code("fortraders", "no-such") is None


# -- attribution lifecycle ------------------------------------------------


def test_attribute_links_the_account_registrys_owner(repo, provider, account):
    issued = _issue(repo)
    got = repo.attribute(issued["referral_id"],
                         account["account_id"])
    assert got["attribution_status"] == REFERRAL_ATTRIBUTED
    assert got["account_id"] == account["account_id"]
    assert got["referred_user_id"] == "alice"
    stored = repo.get(issued["referral_id"])
    assert stored["referred_user_id"] == "alice"


def test_attribute_refuses_a_body_inventing_the_owner(repo, provider, account):
    issued = _issue(repo)
    with pytest.raises(ValueError) as exc:
        repo.attribute(issued["referral_id"], account["account_id"],
                       referred_user_id="mallory")
    assert "belongs to alice, not mallory" in str(exc.value)


def test_attribute_needs_a_referral_that_exists(repo, provider, account):
    with pytest.raises(ValueError):
        repo.attribute("no-such", account["account_id"])


def test_attribute_needs_a_pending_code(repo, provider, account):
    issued = _issue(repo)
    repo.attribute(issued["referral_id"], account["account_id"])
    with pytest.raises(ValueError) as exc:
        repo.attribute(issued["referral_id"], account["account_id"])
    assert "already attributed" in str(exc.value) or \
        "is already" in str(exc.value)


def test_attribute_needs_an_account_that_exists(repo, provider):
    issued = _issue(repo)
    with pytest.raises(ValueError) as exc:
        repo.attribute(issued["referral_id"], "no-such-account")
    assert "not in the account registry" in str(exc.value)


def test_one_account_has_one_origin_per_provider(repo, provider, account):
    first = _issue(repo, code="FT-A-1")
    second = _issue(repo, code="FT-A-2")
    repo.attribute(first["referral_id"], account["account_id"])
    with pytest.raises(ValueError) as exc:
        repo.attribute(second["referral_id"], account["account_id"])
    assert "already attributed to referral" in str(exc.value)


def test_verify_needs_an_attributed_code(repo, provider, account):
    issued = _issue(repo)
    with pytest.raises(ValueError) as exc:
        repo.verify(issued["referral_id"])
    assert "only an attributed code can be verified" in str(exc.value)
    repo.attribute(issued["referral_id"], account["account_id"])
    verified = repo.verify(issued["referral_id"])
    assert verified["attribution_status"] == REFERRAL_VERIFIED
    assert verified["verified_at"] is not None


def test_verify_is_final(repo, provider, account):
    issued = _issue(repo)
    repo.attribute(issued["referral_id"], account["account_id"])
    repo.verify(issued["referral_id"])
    with pytest.raises(ValueError):
        repo.verify(issued["referral_id"])
    with pytest.raises(ValueError) as exc:
        repo.decline(issued["referral_id"])
    assert "confirmed attribution is not declined" in str(exc.value)


def test_decline_cancels_unwanted_codes_but_keeps_the_row(repo, provider):
    issued = _issue(repo)
    declined = repo.decline(issued["referral_id"])
    assert declined["attribution_status"] == REFERRAL_DECLINED
    assert repo.get(issued["referral_id"]) is not None
    with pytest.raises(ValueError):
        repo.attribute(issued["referral_id"], "any")


def test_delete_only_removes_a_pending_code(repo, provider, account):
    issued = _issue(repo)
    assert repo.delete(issued["referral_id"]) is True
    assert repo.get(issued["referral_id"]) is None
    issued = _issue(repo)
    repo.attribute(issued["referral_id"], account["account_id"])
    with pytest.raises(ValueError):
        repo.delete(issued["referral_id"])


# -- reads ---------------------------------------------------------------


def test_list_scoping(repo, provider, account):
    alice1 = _issue(repo, code="FT-A-1", owner="alice")
    bob1 = _issue(repo, code="FT-B-1", owner="bob")
    assert [r["referral_id"] for r in repo.list_for_owner("alice")] == \
        [alice1["referral_id"]]
    repo.attribute(alice1["referral_id"], account["account_id"])
    assert [r["referral_id"] for r in repo.list_for_account(
        account["account_id"])] == [alice1["referral_id"]]
    assert {r["referral_id"] for r in repo.list_by_provider("fortraders")} \
        == {alice1["referral_id"], bob1["referral_id"]}
    assert len(repo.list_all()) == 2
    assert len(repo.list_all(status=REFERRAL_ATTRIBUTED)) == 1


def test_list_filters_by_status(repo, provider):
    repo.issue(provider_id="fortraders", referral_code="FT-1",
               owner_user_id="alice")
    repo.issue(provider_id="fortraders", referral_code="FT-2",
               owner_user_id="alice")
    assert len(repo.list_by_provider("fortraders", status=REFERRAL_PENDING)) == 2
    assert len(repo.list_by_provider("fortraders", status=REFERRAL_VERIFIED)) == 0


# -- fail-closed ---------------------------------------------------------


def test_a_failed_lookup_raises_not_an_empty_attribution(repo, monkeypatch):
    def _boom(*_args, **_kwargs):
        raise RuntimeError("store down")

    monkeypatch.setattr(
        "persistence.repositories_accounts.make_live_session", _boom)
    bare = ReferralRepository()
    with pytest.raises(RuntimeError):
        bare.list_all()


# -- domain vocabulary ----------------------------------------------------


def test_domain_rich_rows_never_carry_trade_authority(repo, provider):
    issued = ReferralAttribution(repo).issue(
        provider_id="fortraders", referral_code="FT-ALICE-1",
        owner_user_id="alice")
    assert issued["is_authorisation"] is False
    assert issued["trade_authority"] == "risk/governor.py"


def test_summary_counts_states(repo, provider, account):
    attr = ReferralAttribution(repo)
    issued = attr.issue(provider_id="fortraders",
                        referral_code="FT-A-1", owner_user_id="alice")
    attr.issue(provider_id="fortraders", referral_code="FT-A-2",
               owner_user_id="alice")
    attr.attribute(issued["referral_id"], account["account_id"])
    summary = attr.summary(attr.for_owner("alice"))
    assert summary["count"] == 2
    assert summary["by_attribution_status"][REFERRAL_PENDING] == 1
    assert summary["by_attribution_status"][REFERRAL_ATTRIBUTED] == 1
    assert summary["is_authorisation"] is False


# -- consistency checker --------------------------------------------------


def test_checker_reports_unknown_provider_and_unknown_sponsor(repo, provider):
    # A row that points at a de-listed provider and a deleted sponsor can only
    # exist after the fact (issue() refuses both at write time), so it is
    # inserted directly -- exactly what the checker exists to surface.
    repo._session.add(ReferralRecord(
        referral_id="orphan-1", provider_id="ghost", referral_code="FT-X",
        owner_user_id="ghost-user", attribution_status=REFERRAL_PENDING,
        tracking_method="referral_code",
        verification_method="verified-provider-purchase"))
    repo._session.commit()
    report = AccountConsistencyChecker(session=repo._session).report()
    kinds = {k for row in report["details"]["referrals"]
             for k in row["kinds"]}
    assert "unknown_provider" in kinds
    assert "unknown_sponsor" in kinds
    assert report["orphaned_referrals"] == 1
    assert report["ok"] is False


def test_checker_reports_unknown_account_after_attribution(repo, provider,
                                                           account,
                                                           alice_user):
    issued = _issue(repo)
    repo.attribute(issued["referral_id"], account["account_id"])
    repo._session.execute(
        delete(AccountRecord).where(
            AccountRecord.account_id == account["account_id"]))
    repo._session.commit()
    report = AccountConsistencyChecker(session=repo._session).report()
    assert any("unknown_account" in r["kinds"]
               for r in report["details"]["referrals"])
    assert report["ok"] is False


def test_checker_is_quiet_when_the_chain_is_complete(repo, provider, account,
                                                    alice_user):
    issued = _issue(repo)
    repo.attribute(issued["referral_id"], account["account_id"])
    report = AccountConsistencyChecker(session=repo._session).report()
    assert report["ok"] is True
    assert report["orphaned_referrals"] == 0
