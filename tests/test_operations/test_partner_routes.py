"""The Evidence Partner routes over the real app (S9 ecosystem).

The layer the domain tests cannot see: routes that resolve the acting
principal, map `ValueError` to `400` and an unreachable store to `503`, keep
onboarding governed and attribution fail-closed. The route-specific failures
guarded here are:

- onboarding needs an acting principal (`409`);
- register returns the partner; an unknown kind or a duplicate is `400`;
- the summary and list are read-only and carry the real counts; a read of an
  unregistered partner is a distinct `404`;
- the lifecycle status route moves a partner and refuses an unknown status;
- evidence intake attributes matter to a registered active partner, and refuses
  an unknown or non-active one (`400`), so `GET /evidence?partner_id=` is a real
  filter, not a promise;
- an unreachable store is `503`, never an empty result.
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
    EvidencePartnerRecord,
    EvidenceRecord,
    SourceRegistryRecord,
)

OPERATOR = "partner-route-principal"


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def partner_db(monkeypatch):
    session = bind_test_session()
    session.execute(delete(EvidenceRecord))
    session.execute(delete(SourceRegistryRecord))
    session.execute(delete(EvidencePartnerRecord))
    session.commit()
    monkeypatch.setattr("persistence.repositories_accounts.make_live_session",
                        lambda: session)
    return session


@pytest.fixture(autouse=True)
def _principal(monkeypatch):
    monkeypatch.setattr("operations.api.identity.principal_user_id",
                        lambda: OPERATOR)


def _partner(**extra):
    body = {
        "partner_id": "acme-research",
        "name": "Acme Research Group",
        "kind": "academic",
    }
    body.update(extra)
    return body


def _evidence(partner_id="acme-research"):
    return {
        "source_kind": "arxiv",
        "external_id": "2401.00020",
        "headline": "A partner-attributed paper",
        "payload_hash": "a" * 64,
        "partner_id": partner_id,
    }


def test_onboarding_needs_a_principal(partner_db, monkeypatch):
    monkeypatch.setattr("operations.api.identity.principal_user_id",
                        lambda: None)
    assert TestClient(app).post("/research/partners",
                                json=_partner()).status_code == 409


def test_register_then_get(client):
    r = client.post("/research/partners", json=_partner())
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["partner"]["partner_id"] == "acme-research"
    assert body["is_authorisation"] is False
    got = client.get("/research/partners/acme-research")
    assert got.status_code == 200
    assert got.json()["partner"]["kind"] == "academic"


def test_register_unknown_kind_is_400(client):
    r = client.post("/research/partners", json=_partner(kind="blogger"))
    assert r.status_code == 400
    assert r.json()["reason"] == "invalid_partner"


def test_register_duplicate_is_400(client):
    assert client.post("/research/partners", json=_partner()).status_code == 200
    r = client.post("/research/partners", json=_partner(name="Acme Two"))
    assert r.status_code == 400
    assert r.json()["reason"] == "invalid_partner"


def test_get_unknown_partner_is_404(client):
    r = client.get("/research/partners/never-registered")
    assert r.status_code == 404
    assert r.json()["reason"] == "unknown_partner"


def test_list_and_summary_are_read_only(client):
    client.post("/research/partners", json=_partner(partner_id="acme-research"))
    client.post("/research/partners",
                json=_partner(partner_id="quandl-data", kind="data_vendor"))
    listed = client.get("/research/partners")
    assert listed.status_code == 200
    assert listed.json()["count"] == 2
    assert listed.json()["read_only"] is True
    assert client.get("/research/partners",
                      params={"kind": "data_vendor"}).json()["count"] == 1
    summary = client.get("/research/partners/summary")
    assert summary.status_code == 200
    s = summary.json()
    assert s["total"] == 2
    assert s["per_kind"] == {"academic": 1, "data_vendor": 1}
    assert s["read_only"] is True
    assert s["is_authorisation"] is False


def test_status_route_moves_partner_and_refuses_unknown(client):
    client.post("/research/partners", json=_partner())
    ok = client.post("/research/partners/acme-research/status",
                     json={"status": "suspended"})
    assert ok.status_code == 200
    assert ok.json()["partner"]["status"] == "suspended"
    bad = client.post("/research/partners/acme-research/status",
                      json={"status": "paused"})
    assert bad.status_code == 400
    missing = client.post("/research/partners/never-registered/status",
                          json={"status": "active"})
    assert missing.status_code == 400


def test_intake_attributes_to_active_partner(client):
    client.post("/research/partners", json=_partner())
    r = client.post("/evidence/intake", json=_evidence())
    assert r.status_code == 200
    assert r.json()["evidence"]["partner_id"] == "acme-research"
    listed = client.get("/evidence", params={"partner_id": "acme-research"})
    assert listed.status_code == 200
    assert listed.json()["count"] == 1
    assert listed.json()["evidence"][0]["partner_id"] == "acme-research"


def test_intake_unknown_partner_is_400(client):
    r = client.post("/evidence/intake", json=_evidence(partner_id="who-dis"))
    assert r.status_code == 400
    assert r.json()["reason"] == "invalid_intake"


def test_intake_from_suspended_partner_is_400(client):
    client.post("/research/partners", json=_partner())
    client.post("/research/partners/acme-research/status",
                json={"status": "suspended"})
    r = client.post("/evidence/intake", json=_evidence())
    assert r.status_code == 400
    assert r.json()["reason"] == "invalid_intake"


def test_source_registration_can_name_a_partner(client):
    client.post("/research/partners", json=_partner())
    r = client.post("/research/sources", json={
        "source_id": "acme-feed",
        "source_type": "academic",
        "provider": "Acme",
        "kind": "arxiv",
        "partner_id": "acme-research",
    })
    assert r.status_code == 200
    assert r.json()["source"]["partner_id"] == "acme-research"


def test_unreachable_store_is_503(client, partner_db, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("store is down")

    monkeypatch.setattr("persistence.repositories_accounts.make_live_session",
                        boom)
    r = client.get("/research/partners")
    assert r.status_code == 503
    assert r.json()["reason"] == "store_unavailable"
