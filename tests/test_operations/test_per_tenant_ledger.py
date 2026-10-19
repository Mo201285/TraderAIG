from fastapi.testclient import TestClient
import pytest

import operations.api as api
from governance.identity import IdentityService, SubscriptionPlan, identity as _global_identity
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
    # reset global ledger
    _global_ledger._records.clear()
    yield TestClient(api.app), principal.user_id, other.user_id
    _global_ledger._records.clear()


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_experiences_are_partitioned_by_owner(two_tenants, monkeypatch):
    client, principal, other = two_tenants
    monkeypatch.setenv("TRADERAIG_AUTH", "1")
    from governance.auth import auth as auth_svc
    token_p = auth_svc.issue(principal)[0]
    token_o = auth_svc.issue(other)[0]
    # add records for both (if model supports owner; will fail red if missing)
    r1 = ExperienceRecord(record_id="r1", decision_id="d1", timestamp=1.0)
    r1.owner_user_id = principal  # may not exist yet
    r2 = ExperienceRecord(record_id="r2", decision_id="d2", timestamp=2.0)
    r2.owner_user_id = other
    # simulate persistence load? for now in-memory
    _global_ledger._records = [r1, r2]
    resp_p = client.get("/learning/experiences", headers=_bearer(token_p))
    assert resp_p.status_code == 200
    ids_p = [x["record_id"] for x in resp_p.json()]
    assert "r1" in ids_p and "r2" not in ids_p
    resp_o = client.get("/learning/experiences", headers=_bearer(token_o))
    assert resp_o.status_code == 200
    ids_o = [x["record_id"] for x in resp_o.json()]
    assert "r2" in ids_o and "r1" not in ids_o
