"""Who may read an account record, and what the API says about it.

The distinction under test throughout: `guard_account()` denies while
authentication is off because it cannot prove who the caller is, and the routes
use `own_record_access()` instead because a narrower question -- "is this the
acting principal's own record?" -- is still answerable. Neither may ever hand over
another user's account, and neither may claim the caller was identified when it
was not.
"""

import pytest
from sqlalchemy import delete, update

from persistence.db import bind_test_session
from persistence.models import UserRecord
from persistence.models_accounts import (
    AccountConnectionRecord,
    AccountIdentityRecord,
    AccountRecord,
)
from persistence.repositories_accounts import AccountRegistryRepository

from accounts import isolation
from accounts.isolation import own_record_access, visible_accounts

OPERATOR = "op-1"
OTHER_USER = "op-2"


@pytest.fixture
def session():
    s = bind_test_session()
    # The test session is process-wide, so a registry row left by one test would
    # make the next one's `register()` raise: the venue identity is already held
    # by a different owner, which is the refusal these tests are here to check.
    for model in (AccountConnectionRecord, AccountIdentityRecord, AccountRecord):
        s.execute(delete(model))
    for user_id in (OPERATOR, OTHER_USER):
        if s.get(UserRecord, user_id) is None:
            s.add(UserRecord(user_id=user_id, email=f"{user_id}@test.local"))
    s.commit()
    return s


@pytest.fixture
def repo(session):
    return AccountRegistryRepository(session)


def _account(repo, login, owner):
    return repo.register(venue="mt5", venue_login=login, venue_server="S",
                         owner_user_id=owner)


# -- own_record_access ----------------------------------------------------


def test_the_owner_may_read_their_own_account(repo):
    account = _account(repo, "1", OPERATOR)
    result = own_record_access(OPERATOR, account["account_id"], repo=repo)
    assert result["allowed"] is True
    assert result["reason"] == "owner"
    assert result["ownership_verified"] is True


def test_another_user_is_denied(repo):
    """The one thing the redirect check must never do."""
    account = _account(repo, "1", OTHER_USER)
    result = own_record_access(OPERATOR, account["account_id"], repo=repo)
    assert result["allowed"] is False
    assert result["reason"] == "not_owner"
    assert result["ownership_verified"] is False


def test_an_unauthenticated_call_is_not_reported_as_authenticated(repo,
                                                                 monkeypatch):
    """Allowed-but-unproven is the case a reader is most likely to misread.

    The account really is the acting principal's, so the read succeeds -- but
    nothing here established that the caller is that principal, and the result
    has to say so or "allowed: true" becomes a claim this deployment cannot make.
    """
    monkeypatch.setattr("accounts.isolation.enforced", lambda: False)
    account = _account(repo, "1", OPERATOR)
    result = own_record_access(OPERATOR, account["account_id"], repo=repo)
    assert result["allowed"] is True
    assert result["caller_authenticated"] is False


def test_authenticated_and_unanuthenticated_agree_for_the_owner(repo,
                                                               monkeypatch):
    """Turning authentication on must not change what an owner may read.

    If it did, enabling `TRADERAIG_AUTH` would lock the operator out of their own
    account, which is the kind of failure that gets discovered in production.
    """
    account = _account(repo, "1", OPERATOR)
    monkeypatch.setattr("accounts.isolation.enforced", lambda: True)
    authenticated = own_record_access(OPERATOR, account["account_id"], repo=repo)
    monkeypatch.setattr("accounts.isolation.enforced", lambda: False)
    anonymous = own_record_access(OPERATOR, account["account_id"], repo=repo)
    assert authenticated["allowed"] == anonymous["allowed"] is True
    assert authenticated["caller_authenticated"] is True
    assert anonymous["caller_authenticated"] is False


def test_an_unowned_account_is_not_handed_to_anyone(repo, session):
    """An account nobody owns belongs to nobody.

    Reachable by an out-of-band insert, which is why the registry's own checker
    reports it. Handing it to the first caller would make "who owns this" a
    function of who asked.
    """
    account = _account(repo, "1", OPERATOR)
    session.execute(
        update(AccountRecord)
        .where(AccountRecord.account_id == account["account_id"])
        .values(owner_user_id=""))
    session.commit()
    result = own_record_access(OPERATOR, account["account_id"], repo=repo)
    assert result["allowed"] is False
    assert result["reason"] == "unowned_account"


def test_no_principal_denies(repo):
    """Empty string is not a principal that owns everything."""
    account = _account(repo, "1", OPERATOR)
    assert own_record_access("", account["account_id"], repo=repo)["reason"] == \
        "no_principal"


def test_an_unknown_account_is_distinguished_from_a_foreign_one(repo):
    """The route turns this into a 404, and the two cases mean different things."""
    account = _account(repo, "1", OPERATOR)
    assert own_record_access(OPERATOR, "nope", repo=repo)["reason"] == \
        "unknown_account"
    assert own_record_access(OTHER_USER, account["account_id"],
                             repo=repo)["reason"] == "not_owner"


def test_a_broken_store_denies(repo):
    class Broken:
        def get(self, _account_id):
            raise RuntimeError("store unavailable")

    assert own_record_access(OPERATOR, "whatever",
                             repo=Broken())["reason"] == "store_unavailable"


# -- the list form --------------------------------------------------------


def test_the_list_hides_other_users_accounts(repo):
    mine = _account(repo, "1", OPERATOR)
    theirs = _account(repo, "2", OTHER_USER)
    rows = repo.list_all()
    visible = visible_accounts(OPERATOR, rows)
    assert [r["account_id"] for r in visible] == [mine["account_id"]]
    assert theirs["account_id"] not in [r["account_id"] for r in visible]


def test_the_list_is_empty_without_a_principal(repo):
    """Otherwise `GET /accounts` would publish the whole registry anonymously."""
    _account(repo, "1", OPERATOR)
    assert visible_accounts("", repo.list_all()) == []


def test_the_list_and_the_single_read_agree(repo):
    """An account visible in the list must also be readable by id.

    The two routes filter separately, so this is where a disagreement would show
    up as an account that appears in the list and 403s on click.
    """
    account = _account(repo, "1", OPERATOR)
    _account(repo, "2", OTHER_USER)
    listed = [r["account_id"] for r in visible_accounts(OPERATOR, repo.list_all())]
    for account_id in listed:
        assert own_record_access(OPERATOR, account_id,
                                 repo=repo)["allowed"] is True
    assert account["account_id"] in listed


# -- the published report -------------------------------------------------


def test_the_report_names_the_wired_routes_without_claiming_a_guard(repo,
                                                                   monkeypatch):
    monkeypatch.setattr("accounts.isolation.enforced", lambda: False)
    report = isolation.isolation_report(repo)
    assert report["wired_into_api"] is True
    assert "GET /accounts" in report["ownership_checked_on"]
    # The strong guard still runs nowhere, and the report must not let a reader
    # conclude that account isolation is active on this deployment.
    assert report["guard_account_called_by_any_route"] is False
    assert report["auth_enforced"] is False
    assert "caller" in report["note"]
