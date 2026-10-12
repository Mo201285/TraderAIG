"""The Partner Network routes over the real app (S11).

The layer the domain tests cannot see: routes that resolve the acting principal,
map `ValueError` to `400` and an unreachable store to `503`, keep the
attestation governed and the coverage honest. The route-specific failures
guarded here are:

- the network and policy reads are read-only and deny being an authority;
- attesting needs an acting principal (`409`);
- attesting a provider absent from the registry is a distinct `404`;
- a successful attestation then makes the venue `accounted` in the network view;
- the lifecycle status route moves an attestation and refuses an unknown status
  and a missing attestation;
- the attestation list and one-by-id read are honest (`404` when absent);
- an unreachable store is `503`, never an empty network.
"""

from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from operations import api  # noqa: E402
from operations.api import app  # noqa: E402
from persistence.db import bind_test_session  # noqa: E402
from persistence.models_accounts import (  # noqa: E402
    ExternalProviderRecord,
    PartnerAttestationRecord,
)
from persistence.repositories_accounts import (  # noqa: E402
    ExternalProviderRepository,
    PartnerAttestationRepository,
)
from providers.network import PartnerNetworkService  # noqa: E402

OPERATOR = "partner-network-principal"


class _FakeScorecard:
    def __init__(self, venues):
        self._venues = venues

    def scorecard(self):
        return {"venues": self._venues}


def _venue(name, orders):
    return {"venue": name, "metrics": {"orders": orders}}


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def partner_db(monkeypatch):
    session = bind_test_session()
    session.query(ExternalProviderRecord).delete()
    session.query(PartnerAttestationRecord).delete()
    session.commit()
    monkeypatch.setattr("persistence.repositories_accounts.make_live_session",
                        lambda: session)
    service = PartnerNetworkService(
        provider_repo=ExternalProviderRepository(session=session),
        attestation_repo=PartnerAttestationRepository(session=session),
        scorecard=_FakeScorecard([_venue("mt5", 1), _venue("binance", 0)]))
    monkeypatch.setattr(api, "_partner_network_service", lambda: service)
    return session


@pytest.fixture(autouse=True)
def _principal(monkeypatch):
    monkeypatch.setattr("operations.api.identity.principal_user_id",
                        lambda: OPERATOR)


def _seed(db, provider_id="fortraders", name="ForTraders", venues=("mt5",)):
    ExternalProviderRepository(session=db).register(
        provider_id=provider_id, name=name, provider_type="prop_firm",
        supported_venues=list(venues))


def test_network_read_is_read_only_and_authority_free(client):
    r = client.get("/partner-network")
    assert r.status_code == 200
    body = r.json()
    assert body["read_only"] is True
    assert body["is_authorisation"] is False
    assert body["trade_authority"] == "risk/governor.py"
    assert "coverage" in body and "venues" in body


def test_policy_route(client):
    r = client.get("/partner-network/policy")
    assert r.status_code == 200
    assert r.json()["policy"]["venue_states"] == [
        "accounted", "pending_attestation", "unattributed"]


def test_attest_needs_a_principal(partner_db, monkeypatch):
    monkeypatch.setattr("operations.api.identity.principal_user_id",
                        lambda: None)
    assert TestClient(app).post(
        "/partner-network/fortraders/attest").status_code == 409


def test_attest_unknown_provider_is_404(client):
    r = client.post("/partner-network/ghost/attest", json={"note": "x"})
    assert r.status_code == 404
    assert r.json()["reason"] == "unknown_provider"


def test_attest_then_network_accounted(client, partner_db):
    _seed(partner_db)
    r = client.post("/partner-network/fortraders/attest",
                    json={"note": "signed"})
    assert r.status_code == 200
    body = r.json()
    assert body["attestation"]["attested_by"] == OPERATOR
    assert body["attestation"]["note"] == "signed"
    assert body["action"] == "attested"
    mt5 = next(v for v in client.get("/partner-network").json()["venues"]
               if v["venue"] == "mt5")
    assert mt5["state"] == "accounted"


def test_status_route_moves_and_refuses_unknown(client, partner_db):
    _seed(partner_db)
    client.post("/partner-network/fortraders/attest", json={})
    ok = client.post("/partner-network/fortraders/status",
                     json={"status": "suspended"})
    assert ok.status_code == 200
    assert ok.json()["attestation"]["status"] == "suspended"
    bad = client.post("/partner-network/fortraders/status",
                      json={"status": "paused"})
    assert bad.status_code == 400
    assert bad.json()["reason"] == "invalid_status"
    missing = client.post("/partner-network/ghost/status",
                          json={"status": "attested"})
    assert missing.status_code == 400


def test_attestations_list_and_get(client, partner_db):
    _seed(partner_db)
    client.post("/partner-network/fortraders/attest", json={})
    listed = client.get("/partner-network/attestations")
    assert listed.status_code == 200
    assert listed.json()["count"] == 1
    assert listed.json()["read_only"] is True
    one = client.get("/partner-network/attestations/fortraders")
    assert one.status_code == 200
    assert one.json()["provider_id"] == "fortraders"
    absent = client.get("/partner-network/attestations/ghost")
    assert absent.status_code == 404
    assert absent.json()["reason"] == "no_attestation"


def test_unreachable_store_is_503(client, partner_db, monkeypatch):
    monkeypatch.setattr(api, "_partner_network_service",
                        lambda: PartnerNetworkService())

    def boom(*args, **kwargs):
        raise RuntimeError("store is down")

    monkeypatch.setattr("persistence.repositories_accounts.make_live_session",
                        boom)
    r = client.get("/partner-network")
    assert r.status_code == 503
    assert r.json()["reason"] == "store_unavailable"
