"""Slice I4 — enforcement policy for multi-tenant.

When a second tenant exists, tenant-scoped routes require a session regardless
of `TRADERAIG_AUTH`, reads of tenant-scoped data become gated, and
`/system/health.tenancy` flips `reads_gated` / `multi_tenant` / `authenticated`.
Global reference reads (providers, market data, docs) stay open.
"""
from fastapi.testclient import TestClient
import pytest

import operations.api as api
from governance.identity import (IdentityService, SubscriptionPlan,
                                 identity as _global_identity)


@pytest.fixture()
def two_tenants(monkeypatch):
    svc = IdentityService()
    svc.rehydrate()
    principal = svc.create_user(email="enf-owner@x.com", display_name="O",
                                plan=SubscriptionPlan.INSTITUTIONAL)
    svc.activate_subscription(principal.user_id, SubscriptionPlan.INSTITUTIONAL)
    other = svc.create_user(email="enf-peer@y.com", display_name="P",
                            plan=SubscriptionPlan.INSTITUTIONAL)
    svc.activate_subscription(other.user_id, SubscriptionPlan.INSTITUTIONAL)
    monkeypatch.setattr(_global_identity, "_users", svc._users)
    monkeypatch.setattr(_global_identity, "_subscriptions", svc._subscriptions)
    monkeypatch.setattr(_global_identity, "_audit", svc._audit)
    monkeypatch.setenv("IDENTITY_PRIMARY_EMAIL", "enf-owner@x.com")
    monkeypatch.delenv("TRADERAIG_AUTH", raising=False)
    yield TestClient(api.app), principal.user_id, other.user_id


def _tenancy(client):
    body = client.get("/system/health").json()
    if "tenancy" in body:
        return body["tenancy"]
    for value in body.values():
        if isinstance(value, dict) and "reads_gated" in value:
            return value
    raise AssertionError(f"no tenancy block in {body!r}")


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_tenant_route_requires_session_without_env(two_tenants):
    client, principal, other = two_tenants
    assert client.get("/account").status_code in (401, 403)

    block = _tenancy(client)
    assert block["multi_tenant"] is True
    assert block["reads_gated"] is True

    # A session satisfies it and reports who presented it.
    from governance.auth import auth as auth_svc

    token = auth_svc.issue(principal)[0]
    assert client.get("/account", headers=_bearer(token)).status_code == 200
    assert _tenancy(client)["authenticated"] is False  # no session on /system/health


def test_reference_reads_stay_open_under_multi_tenant(two_tenants):
    client, principal, other = two_tenants
    for path in ("/providers", "/market/feeds"):
        resp = client.get(path)
        assert resp.status_code != 401, path
        assert resp.status_code != 403, path


def test_single_tenant_box_on_an_optout_host_is_unchanged(monkeypatch):
    """Slice I4 must not, by itself, gate a one-operator box.

    The unwritten variable no longer means "open" (enforcement is ON by default
    as of 28.19), so the "single-tenant box is unchanged" baseline is the
    explicit opt-out host: `TRADERAIG_AUTH=0` with one tenant stays ungated,
    proving the multi-tenant trigger is what gates, not the default.
    """
    monkeypatch.setenv("TRADERAIG_AUTH", "0")
    monkeypatch.delenv("IDENTITY_PRIMARY_EMAIL", raising=False)
    monkeypatch.setattr(_global_identity, "_users", {})
    client = TestClient(api.app)
    assert client.get("/account").status_code == 200
    block = _tenancy(client)
    assert block["multi_tenant"] is False
    assert block["reads_gated"] is False


def test_single_tenant_box_is_gated_by_the_default(monkeypatch):
    """An unset variable now enforces: a one-tenant box is gated (28.19)."""
    monkeypatch.delenv("TRADERAIG_AUTH", raising=False)
    monkeypatch.delenv("IDENTITY_PRIMARY_EMAIL", raising=False)
    monkeypatch.setattr(_global_identity, "_users", {})
    client = TestClient(api.app)
    # no identity + enforcement on: only the bootstrap create path is open
    assert client.get("/account").status_code in (401, 403)
    block = _tenancy(client)
    assert block["multi_tenant"] is False
    assert block["reads_gated"] is True
