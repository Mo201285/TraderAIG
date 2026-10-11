"""The Research Knowledge Factory routes over the real app (row 748, P3 slice).

The layer under test is the one the domain tests cannot see: routes that
resolve the acting principal, map `ValueError` to `400` (an empty or ghost
citation list, a missing title, an unknown status filter), a distinct `404`
for an unknown package, an unreachable store to `503`, and serialise the
evidence-backed growth surface. The route-specific failures guarded here:

- every factory route needs an acting principal (`409`);
- recording a package that cites evidence the plane does not know is `400`
  `invalid_package` listing the offenders -- the whole package is refused;
- recording a package with no citations is `400` (no fabrication);
- a successful record returns the resolved evidence lineage and `backed_trust`,
  and every payload carries `is_authorisation: False` naming the Risk Governor;
- reads return a distinct `404` `unknown_package`; a bad status filter is
  `400`; a dead store is `503`, never an empty result;
- `GET /research/growth` reports only what exists: a family with evidence but
  no package is honestly not content-ready;
- the tenancy report truthfully describes the research factory.
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
    EvidenceRecord,
    ResearchPackageRecord,
)
from research.evidence_plane import EvidencePlaneService  # noqa: E402

OPERATOR = "research-route-principal"


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def research_db(monkeypatch):
    session = bind_test_session()
    session.execute(delete(ResearchPackageRecord))
    session.execute(delete(EvidenceRecord))
    session.commit()
    monkeypatch.setattr("persistence.repositories_accounts.make_live_session",
                        lambda: session)
    return session


@pytest.fixture(autouse=True)
def _principal(monkeypatch):
    monkeypatch.setattr("operations.api.identity.principal_user_id",
                        lambda: OPERATOR)


def _seed_evidence(source_kind: str, external_id: str, *,
                   markets=None, headline: str = "a claim") -> str:
    row = EvidencePlaneService().ingest(
        source_kind=source_kind, external_id=external_id, headline=headline,
        markets=markets, content_hash=f"{source_kind}-{external_id}")
    return row["evidence_id"]


def _package_payload(evidence_ids, **extra):
    payload = {"title": extra.pop("title", "a research package"),
               "evidence_ids": evidence_ids}
    payload.update(extra)
    return payload


def test_all_factory_routes_need_a_principal(client, research_db, monkeypatch):
    monkeypatch.setattr("operations.api.identity.principal_user_id",
                        lambda: None)
    for route, kwargs in [
        ("/research/packages", {"method": "post",
                                "json": _package_payload(["x"])}),
        ("/research/packages", {"method": "get"}),
        ("/research/packages/any", {"method": "get"}),
        ("/research/knowledge", {"method": "get"}),
        ("/research/growth", {"method": "get"}),
    ]:
        if kwargs["method"] == "get":
            r = getattr(client, "get")(route)
        elif kwargs["method"] == "post":
            r = client.post(route, json=kwargs["json"])
        else:  # pragma: no cover
            raise AssertionError(kwargs)
        assert r.status_code == 409, route
        assert r.json()["reason"] == "no_principal"


def test_record_package_citing_existing_evidence(client):
    eid = _seed_evidence("macro", "CPI:2026Q4:US", markets=["BTC"])
    r = client.post("/research/packages",
                    json=_package_payload([eid], hypothesis="disinflation"))
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["action"] == "recorded"
    package = body["package"]
    assert package["title"] == "a research package"
    assert package["evidence_ids"] == [eid]
    assert package["evidence_lineage"][0]["evidence_id"] == eid
    assert package["backed_trust"] == 1
    assert package["is_authorisation"] is False
    assert body["trade_authority"] == "risk/governor.py"


def test_record_refuses_ghost_citations(client):
    r = client.post("/research/packages", json=_package_payload(["ghost-1"]))
    assert r.status_code == 400
    assert r.json()["reason"] == "invalid_package"
    assert "ghost-1" in r.json()["detail"]


def test_record_refuses_no_citations(client):
    r = client.post("/research/packages", json=_package_payload([]))
    assert r.status_code == 400
    assert r.json()["reason"] == "invalid_package"


def test_record_refuses_missing_title(client):
    eid = _seed_evidence("macro", "CPI:2026Q4:US")
    r = client.post("/research/packages",
                    json={"title": "  ", "evidence_ids": [eid]})
    assert r.status_code == 400
    assert r.json()["reason"] == "invalid_package"


def test_list_filters_by_citing_evidence(client):
    eid = _seed_evidence("macro", "CPI:2026Q4:US", markets=["BTC"])
    other = _seed_evidence("macro", "CPI:2026Q5:US", markets=["BTC", "ETH"])
    client.post("/research/packages", json=_package_payload([eid]))
    client.post("/research/packages", json=_package_payload([other]))
    listed = client.get("/research/packages", params={"evidence_id": eid})
    assert listed.status_code == 200
    assert listed.json()["count"] == 1
    assert listed.json()["read_only"] is True
    assert listed.json()["is_authorisation"] is False


def test_list_rejects_unknown_status(client):
    r = client.get("/research/packages", params={"status": "promoted"})
    assert r.status_code == 400
    assert r.json()["reason"] == "invalid_filter"


def test_get_returns_package_and_distinct_404(client):
    eid = _seed_evidence("arxiv", "2401.00010")
    created = client.post("/research/packages",
                          json=_package_payload([eid])).json()["package"]
    got = client.get(f"/research/packages/{created['package_id']}")
    assert got.status_code == 200
    assert got.json()["package"]["backed_trust"] == 1
    assert got.json()["is_authorisation"] is False
    nf = client.get("/research/packages/never-existed")
    assert nf.status_code == 404
    assert nf.json()["reason"] == "unknown_package"


def test_knowledge_summary_surface(client):
    eid = _seed_evidence("macro", "CPI:2026Q4:US")
    client.post("/research/packages", json=_package_payload([eid]))
    r = client.get("/research/knowledge")
    assert r.status_code == 200
    k = r.json()["knowledge"]
    assert k["total"] == 1
    assert k["per_status"] == {"recorded": 1}
    assert k["cited_evidence_ids"] == 1
    assert k["is_authorisation"] is False


def test_growth_reports_evidence_without_package_as_not_content_ready(client):
    eid = _seed_evidence("macro", "CPI:2026Q4:US", markets=["BTC"])
    client.post("/research/packages", json=_package_payload([eid]))
    _seed_evidence("arxiv", "2401.00010")  # evidence, no package
    r = client.get("/research/growth")
    assert r.status_code == 200
    g = r.json()["growth"]
    assert g["per_source"]["macro"]["content_ready"] is True
    assert g["per_source"]["arxiv"]["content_ready"] is False
    assert g["per_source"]["arxiv"]["evidence_count"] == 1
    assert g["per_source"]["arxiv"]["package_count"] == 0
    assert g["content_ready_markets"] == ["BTC"]
    assert g["is_authorisation"] is False


def test_unreachable_store_is_503(client, research_db, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("store is down")

    monkeypatch.setattr("persistence.repositories_accounts.make_live_session",
                        boom)
    for route in ("/research/packages",
                  "/research/packages/any",
                  "/research/knowledge",
                  "/research/growth"):
        r = client.get(route)
        assert r.status_code == 503, route
        assert r.json()["reason"] == "store_unavailable"


def test_tenancy_report_describes_research_factory(client):
    r = client.get("/system/health")
    t = r.json().get("tenancy", {})
    assert "research_knowledge_factory" in t
    assert "POST /research/packages" in t["research_knowledge_factory"]
    assert any("research/packages" in entry
               for entry in t["ownership_enforced_on"])
