from fastapi.testclient import TestClient
import pytest

import operations.api as api
from governance.identity import IdentityService, SubscriptionPlan, identity as _global_identity


@pytest.fixture()
def two_tenants(monkeypatch):
    svc = IdentityService()
    svc.rehydrate()
    p = svc.create_user(email="enf-owner@x.com", display_name="O",
                        plan=SubscriptionPlan.INSTITUTIONAL)
    svc.activate_subscription(p.user_id, SubscriptionPlan.INSTITUTIONAL)
    o = svc.create_user(email="enf-peer@y.com", display_name="P",
                        plan=SubscriptionPlan.INSTITUTIONAL)
    svc.activate_subscription(o.user_id, SubscriptionPlan.INSTITUTIONAL)
    monkeypatch.setattr(_global_identity, "_users", svc._users)
    monkeypatch.setattr(_global_identity, "_subscriptions", svc._subscriptions)
    monkeypatch.setattr(_global_identity, "_audit", svc._audit)
    monkeypatch.setenv("IDENTITY_PRIMARY_EMAIL", "enf-owner@x.com")
    yield TestClient(api.app), p.user_id, o.user_id


def test_reads_gated_when_multi_tenant(two_tenants, monkeypatch):
    client, p, o = two_tenants
    monkeypatch.delenv("TRADERAIG_AUTH", raising=False)
    # tenant-scoped read (account) should require session when multi-tenant?
    resp = client.get("/account")
    assert resp.status_code in (401, 403)
    h = client.get("/system/health").json()
    t = h.get("tenancy") or next((v for v in h.values() if isinstance(v, dict) and "reads_gated" in v), {})
    assert t["multi_tenant"] is True
    assert t["reads_gated"] is True
