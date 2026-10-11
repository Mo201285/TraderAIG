"""The `/providers` External Provider Registry routes over the real app.

The layer under test is the one the domain tests cannot see: routes that read
the catalog and serialise *something*. The route-specific failures guarded here
are:

- an unreachable store reported as 503 (fail-closed, not an empty "no
  providers" that would hide an outage);
- an unknown provider reported as 404 (distinct from a store failure);
- a body that reads like an authorisation. Every listing must carry
  `is_authorisation: False` and name the Risk Governor, so "a provider exists"
  never reads as "accounts from this provider may trade";
- the tenancy report truthfully says the catalog is a public read (a provider
  is not a user record, so ownership scoping intentionally does not apply).
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
    ExternalProviderRecord,
)
from persistence.repositories_accounts import (  # noqa: E402
    ExternalProviderRepository,
)


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture
def provider_db(monkeypatch):
    """A lifted ExternalProviderRepository backed by the shared test session.

    The routes construct `ExternalProviderRepository()` with no session, so they
    read the live session the module holds -- the same seam the account-registry
    route tests patch on their own module.
    """
    session = bind_test_session()
    session.execute(delete(ExternalProviderRecord))
    session.commit()
    monkeypatch.setattr("persistence.repositories_accounts.make_live_session",
                        lambda: session)
    return ExternalProviderRepository(session)


def _seed(repo: ExternalProviderRepository) -> dict:
    return repo.register(
        provider_id="fortraders", name="ForTraders",
        provider_type="funded-prop", referral_program="referral",
        tracking_method="referral_code",
        verification_method="verified-provider-purchase",
        supported_venues=["mt5"],
        supported_accounts=["challenge", "demo", "funded"],
        policy_adapter="providers.fortraders:ForTradersProviderAdapter",
    )


def test_the_catalog_lists_registered_providers(client, provider_db):
    _seed(provider_db)
    body = client.get("/providers").json()
    assert body["ok"] is True
    assert body["count"] == 1
    entry = body["providers"][0]
    assert entry["provider_id"] == "fortraders"
    assert entry["name"] == "ForTraders"
    assert entry["policy_adapter"] == \
        "providers.fortraders:ForTradersProviderAdapter"
    assert body["is_authorisation"] is False
    assert body["trade_authority"] == "risk/governor.py"
    assert body["read_only"] is True


def test_an_unknown_provider_is_404(client, provider_db):
    response = client.get("/providers/not-a-provider")
    assert response.status_code == 404
    body = response.json()
    assert body["reason"] == "unknown_provider"


def test_one_provider_reads_its_registry_row(client, provider_db):
    _seed(provider_db)
    body = client.get("/providers/fortraders").json()
    assert body["ok"] is True
    assert body["provider"]["supported_venues"] == ["mt5"]
    assert body["provider"]["supported_accounts"] == \
        ["challenge", "demo", "funded"]
    assert body["is_authorisation"] is False
    assert body["read_only"] is True


def test_the_catalog_never_claims_trade_permission(client, provider_db):
    """A provider row exists; that must never read as a trade permission."""
    _seed(provider_db)
    body = client.get("/providers").json()
    for entry in body["providers"]:
        assert "grants_trade_permission" not in entry
        assert "may_trade" not in entry


def test_an_unreachable_store_is_503_not_empty_list(client, provider_db,
                                                    monkeypatch):
    """Fail-closed: a failed lookup is NOT "no providers"."""
    def _boom(*_args, **_kwargs):
        raise RuntimeError("store down")

    monkeypatch.setattr(
        "persistence.repositories_accounts.make_live_session", _boom)
    # The route builds ExternalProviderRepository() with no injected session,
    # so it reaches make_live_session() and must surface a 503, never a 200
    # with an empty catalog.
    response = client.get("/providers")
    assert response.status_code == 503
    assert response.json()["reason"] == "store_unavailable"


def test_the_tenancy_report_names_the_catalog_as_a_public_read(client):
    """A provider is not a user record -- ownership scoping does not apply."""
    body = client.get("/system/health").json()["tenancy"]
    assert "GET /providers + GET /providers/{provider_id}" in \
        body["external_provider_registry"]
    assert "NOT ownership-scoped" in body["external_provider_registry"]
