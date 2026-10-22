from fastapi.testclient import TestClient
import pytest

import operations.api as api
from accounts import isolation
from governance.identity import (IdentityService, SubscriptionPlan,
                                 identity as _global_identity)
from learning.experience import ExperienceRecord, ledger as _global_ledger


@pytest.fixture()
def two_tenants(monkeypatch):
    svc = IdentityService()
    svc.rehydrate()
    principal = svc.create_user(email="ledger-owner@institution.com",
                                display_name="Ledger Owner",
                                plan=SubscriptionPlan.INSTITUTIONAL)
    svc.activate_subscription(principal.user_id, SubscriptionPlan.INSTITUTIONAL)
    other = svc.create_user(email="ledger-peer@elsewhere.test",
                            display_name="Ledger Peer",
                            plan=SubscriptionPlan.INSTITUTIONAL)
    svc.activate_subscription(other.user_id, SubscriptionPlan.INSTITUTIONAL)
    monkeypatch.setattr(_global_identity, "_users", svc._users)
    monkeypatch.setattr(_global_identity, "_subscriptions", svc._subscriptions)
    monkeypatch.setattr(_global_identity, "_audit", svc._audit)
    monkeypatch.setenv("IDENTITY_PRIMARY_EMAIL", "ledger-owner@institution.com")
    _global_ledger.clear()
    yield TestClient(api.app), principal.user_id, other.user_id
    _global_ledger.clear()


@pytest.fixture()
def db_session():
    from persistence.db import bind_test_session
    from persistence.models_accounts import AccountRecord
    from persistence.models_trades import AccountStrategyBindingRecord

    session = bind_test_session()
    session.query(AccountStrategyBindingRecord).delete()
    session.query(AccountRecord).delete()
    session.commit()
    try:
        yield session
    finally:
        session.query(AccountStrategyBindingRecord).delete()
        session.query(AccountRecord).delete()
        session.commit()


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_experiences_are_partitioned_by_owner(two_tenants, monkeypatch):
    client, principal, other = two_tenants
    monkeypatch.setenv("TRADERAIG_AUTH", "1")
    from governance.auth import auth as auth_svc

    token_p = auth_svc.issue(principal)[0]
    token_o = auth_svc.issue(other)[0]

    r1 = ExperienceRecord(record_id="r1", decision_id="d1", timestamp=1.0)
    r1.owner_user_id = principal
    r2 = ExperienceRecord(record_id="r2", decision_id="d2", timestamp=2.0)
    r2.owner_user_id = other
    _global_ledger._records = [r1, r2]

    resp_p = client.get("/learning/experiences", headers=_bearer(token_p))
    assert resp_p.status_code == 200
    ids_p = [x["record_id"] for x in resp_p.json()]
    assert "r1" in ids_p and "r2" not in ids_p

    resp_o = client.get("/learning/experiences", headers=_bearer(token_o))
    assert resp_o.status_code == 200
    ids_o = [x["record_id"] for x in resp_o.json()]
    assert "r2" in ids_o and "r1" not in ids_o


def test_unowned_history_belongs_to_the_default_tenant(two_tenants, monkeypatch):
    """A row with no owner predates partitioning; it is not tenant-less.

    The default tenant keeps it (no data disappears), and a second tenant can
    never claim it.
    """
    client, principal, other = two_tenants
    monkeypatch.setenv("TRADERAIG_AUTH", "1")
    from governance.auth import auth as auth_svc

    legacy = ExperienceRecord(record_id="legacy", decision_id="d",
                              timestamp=0.0)
    assert not (getattr(legacy, "owner_user_id", "") or "")
    _global_ledger._records = [legacy]

    token_p = auth_svc.issue(principal)[0]
    token_o = auth_svc.issue(other)[0]

    mine = client.get("/learning/experiences", headers=_bearer(token_p)).json()
    assert [x["record_id"] for x in mine] == ["legacy"]

    theirs = client.get("/learning/experiences", headers=_bearer(token_o)).json()
    assert [x["record_id"] for x in theirs] == []


def test_account_reads_are_partitioned_by_session(two_tenants, monkeypatch):
    client, principal, other = two_tenants
    monkeypatch.setenv("TRADERAIG_AUTH", "1")
    from governance.auth import auth as auth_svc

    rows = {
        "acct-owner": {"account_id": "acct-owner",
                       "owner_user_id": principal, "venue_login": "1001"},
        "acct-peer": {"account_id": "acct-peer",
                      "owner_user_id": other, "venue_login": "2002"},
    }
    monkeypatch.setattr(isolation, "resolve_account",
                        lambda account_id, repo=None: rows.get(account_id))
    monkeypatch.setattr(
        "persistence.repositories_accounts.AccountRegistryRepository.list_all",
        lambda self: list(rows.values()), raising=True)

    token_p = auth_svc.issue(principal)[0]
    token_o = auth_svc.issue(other)[0]

    listing = client.get("/accounts", headers=_bearer(token_o)).json()
    assert [a["account_id"] for a in listing["accounts"]] == ["acct-peer"]

    own = client.get("/accounts/acct-peer", headers=_bearer(token_o))
    assert own.status_code == 200
    stolen = client.get("/accounts/acct-owner", headers=_bearer(token_o))
    assert stolen.status_code == 403
    assert stolen.json()["reason"] == "not_owner"

    # The owner still reads their own row; partitioning did not hide it.
    mine = client.get("/accounts/acct-owner", headers=_bearer(token_p))
    assert mine.status_code == 200


def test_orphaned_bindings_probe_reports_no_overlap(db_session):
    """I3's integrity probe: two tenants, two accounts, no orphaned binding.

    `orphaned_bindings()` is the checker I3 reuses to prove the partition has
    not left a binding pointing at an account that no longer exists -- which is
    exactly how a cross-tenant read could reappear without any single route
    being wrong.
    """
    from persistence.repositories_accounts import (
        AccountConsistencyChecker, AccountRegistryRepository)

    repo = AccountRegistryRepository(db_session)
    repo.register(venue="mt5", venue_login="1001", owner_user_id="tenant-a")
    repo.register(venue="mt5", venue_login="2002", owner_user_id="tenant-b")

    assert AccountRegistryRepository(db_session).list_for_owner("tenant-a")[
        0]["venue_login"] == "1001"
    assert AccountConsistencyChecker(db_session).orphaned_bindings() == []
