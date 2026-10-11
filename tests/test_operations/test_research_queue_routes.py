"""RMI-01 routes over the real app (row 749): source registry + research queue.

The layer under test is the one the domain tests cannot see: routes that
resolve the acting principal, map `ValueError` to `400` (a malformed source, a
ghost evidence id on a grounded problem, an out-of-range dimension, an unknown
filter, an illegal transition), a distinct `404` for unknown sources/items,
an unreachable store to `503`, and serialise the score/status surfaces. The
route-specific failures guarded here:

- every RMI surface needs an acting principal (`409`);
- registering a source with a blank slug, unknown type/kind/status/cost or a
  duplicate source_id is `400` `invalid_source`;
- `/research/sources/{id}/sync` stamps the run and 404s on an unknown id;
- enqueueing a single problem returns the stored, enriched item; a burst
  returns per-candidate receipts with one good item surviving refused ones;
- a grounded problem citing a ghost evidence id is `400` `invalid_problem`;
- the lifecycle start/complete/supersede maps illegal transitions to `400`
  and unknown items to `404`;
- `GET /research/queue/summary` is not shadowed by `GET /research/queue/{id}`;
- reads are `read_only`, every payload carries `is_authorisation: False`
  naming the Risk Governor, and the tenancy report truthfully describes both
  new surfaces.
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
    ResearchQueueItemRecord,
    SourceRegistryRecord,
)
from research.evidence_plane import EvidencePlaneService  # noqa: E402

OPERATOR = "rmi-route-principal"


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def rmi_db(monkeypatch):
    session = bind_test_session()
    session.execute(delete(ResearchQueueItemRecord))
    session.execute(delete(SourceRegistryRecord))
    session.execute(delete(EvidenceRecord))
    session.commit()
    monkeypatch.setattr("persistence.repositories_accounts.make_live_session",
                        lambda: session)
    return session


@pytest.fixture(autouse=True)
def _principal(monkeypatch):
    monkeypatch.setattr("operations.api.identity.principal_user_id",
                        lambda: OPERATOR)


def _seed_evidence(source_kind: str, external_id: str) -> str:
    row = EvidencePlaneService().ingest(
        source_kind=source_kind, external_id=external_id,
        headline="a claim", content_hash=f"{source_kind}-{external_id}")
    return row["evidence_id"]


def _source_payload(**extra):
    payload = {
        "source_id": "arxiv-ml",
        "source_type": "academic",
        "provider": "arXiv",
        "kind": "arxiv",
        "url_or_feed": "https://export.arxiv.org/oai2",
        "frequency": "daily",
        "reliability": 0.9,
        "cost": "free",
        "status": "active",
        "note": "",
    }
    payload.update(extra)
    return payload


def _problem_payload(**extra):
    payload = {
        "problem": "does a volatility breakout persist across the next close",
        "expected_value": 0.8, "data_availability": 0.7,
        "research_cost": 0.4, "risk": 0.3, "novelty": 0.6,
        "reproducibility": 0.7,
    }
    payload.update(extra)
    return payload


# -- every RMI surface needs an acting principal ------------------------------


def test_all_rmi_routes_need_a_principal(client, rmi_db, monkeypatch):
    monkeypatch.setattr("operations.api.identity.principal_user_id",
                        lambda: None)
    routes = [
        ("post", "/research/sources"),
        ("get", "/research/sources"),
        ("get", "/research/sources/arxiv-ml"),
        ("get", "/research/sources/nope"),
        ("post", "/research/queue"),
        ("get", "/research/queue"),
        ("get", "/research/queue/any"),
        ("post", "/research/queue/any/start"),
        ("post", "/research/queue/any/complete"),
        ("post", "/research/queue/any/supersede"),
        ("get", "/research/queue/summary"),
    ]
    for method, path in routes:
        body = None
        if method == "post" and path == "/research/sources":
            body = _source_payload()
        elif method == "post" and path == "/research/queue":
            body = _problem_payload()
        r = getattr(client, method)(path, json=body) if body is not None \
            else getattr(client, method)(path)
        assert r.status_code == 409, (method, path)
        assert r.json()["reason"] == "no_principal"


# -- the source ledger ---------------------------------------------------------


def test_register_source_and_read_it_back(client):
    r = client.post("/research/sources", json=_source_payload())
    assert r.status_code == 200
    source = r.json()["source"]
    assert source["source_id"] == "arxiv-ml"
    assert source["is_authorisation"] is False
    assert source["trade_authority"] == "risk/governor.py"
    got = client.get("/research/sources/arxiv-ml")
    assert got.status_code == 200
    assert got.json()["source"]["kind"] == "arxiv"
    assert got.json()["read_only"] is True


def test_list_sources_filters_and_is_never_a_permission(client):
    client.post("/research/sources", json=_source_payload())
    client.post("/research/sources", json=_source_payload(
        source_id="ecb-calendar", source_type="macro", kind="macro",
        provider="ECB"))
    all_rows = client.get("/research/sources")
    assert all_rows.status_code == 200
    assert all_rows.json()["count"] == 2
    assert all_rows.json()["read_only"] is True
    macro = client.get("/research/sources", params={"source_type": "macro"})
    assert [s["source_id"] for s in macro.json()["sources"]] == [
        "ecb-calendar"]
    bad = client.get("/research/sources", params={"kind": "twitter"})
    assert bad.status_code == 400
    assert bad.json()["reason"] == "invalid_filter"


def test_register_refuses_malformed_sources(client):
    for payload in (
            _source_payload(source_id="ArxivML"),
            _source_payload(source_type="theory"),
            _source_payload(kind="twitter"),
            _source_payload(status="paused"),
            _source_payload(cost="negotiable")):
        r = client.post("/research/sources", json=payload)
        assert r.status_code == 400, payload
        assert r.json()["reason"] == "invalid_source"
    r = client.post("/research/sources", json=_source_payload())
    dup = client.post("/research/sources", json=_source_payload())
    assert dup.status_code == 400
    assert dup.json()["reason"] == "invalid_source"


def test_get_unknown_source_is_a_distinct_404(client):
    r = client.get("/research/sources/never-existed")
    assert r.status_code == 404
    assert r.json()["reason"] == "unknown_source"


def test_mark_synced_stamps_and_404s_on_unknown(client):
    client.post("/research/sources", json=_source_payload())
    synced = client.post("/research/sources/arxiv-ml/sync")
    assert synced.status_code == 200
    assert synced.json()["source"]["last_sync"]
    nf = client.post("/research/sources/never-existed/sync")
    assert nf.status_code == 404
    assert nf.json()["reason"] == "unknown_source"


# -- the research queue --------------------------------------------------------


def test_enqueue_single_problem_returns_stored_item(client):
    r = client.post("/research/queue", json=_problem_payload())
    assert r.status_code == 200
    item = r.json()["item"]
    assert item["status"] == "queued"
    assert 0.0 <= item["priority_score"] <= 100.0
    assert item["priority_label"] in ("high", "medium", "low")
    assert item["is_authorisation"] is False
    assert r.json()["action"] == "enqueued"


def test_grounded_problem_resolves_lineage(client):
    eid = _seed_evidence("arxiv", "2401.00012")
    r = client.post("/research/queue", json=_problem_payload(
        evidence_ids=[eid]))
    assert r.status_code == 200
    item = r.json()["item"]
    assert item["evidence_lineage"][0]["evidence_id"] == eid
    assert item["backed_trust"] == 1


def test_ghost_citation_is_400(client):
    r = client.post("/research/queue", json=_problem_payload(
        evidence_ids=["ghost-9"]))
    assert r.status_code == 400
    assert r.json()["reason"] == "invalid_problem"


def test_burst_receipts_keep_good_items(client):
    eid = _seed_evidence("arxiv", "2401.00013")
    good = _problem_payload(problem="good one", evidence_ids=[eid])
    bad = _problem_payload(problem="ghost citation", evidence_ids=["ghost-9"])
    r = client.post("/research/queue", json=[good, bad, "not-an-object"])
    assert r.status_code == 200
    payload = r.json()
    assert payload["accepted"] == 1
    assert payload["refused"] == 2
    by_problem = {c["problem"]: c for c in payload["receipts"]}
    assert by_problem["good one"]["accepted"] is True
    assert by_problem["ghost citation"]["accepted"] is False
    assert by_problem[""]["reason"] == "not_an_object"


def test_out_of_range_dimension_is_400(client):
    r = client.post("/research/queue", json=_problem_payload(
        expected_value=1.3))
    assert r.status_code == 400
    assert r.json()["reason"] == "invalid_problem"


def test_queue_reads_order_by_score_desc_and_404(client):
    client.post("/research/queue", json=_problem_payload(problem="weak"))
    client.post("/research/queue", json=_problem_payload(
        problem="strong", expected_value=1.0, data_availability=1.0,
        research_cost=0.0, risk=0.0, novelty=1.0, reproducibility=1.0))
    rows = client.get("/research/queue").json()["items"]
    assert [r["problem"] for r in rows] == ["strong", "weak"]
    first = rows[0]["item_id"]
    got = client.get(f"/research/queue/{first}")
    assert got.status_code == 200
    assert got.json()["item"]["item_id"] == first
    nf = client.get("/research/queue/never-existed")
    assert nf.status_code == 404
    assert nf.json()["reason"] == "unknown_queue_item"


def test_lifecycle_transitions(client):
    item_id = client.post("/research/queue",
                          json=_problem_payload()).json()["item"]["item_id"]
    started = client.post(f"/research/queue/{item_id}/start")
    assert started.status_code == 200
    assert started.json()["item"]["status"] == "active"
    assert started.json()["item"]["started_at"]
    done = client.post(f"/research/queue/{item_id}/complete")
    assert done.status_code == 200
    assert done.json()["item"]["status"] == "completed"
    assert done.json()["item"]["completed_at"]
    assert client.post(f"/research/queue/{item_id}/start").status_code == 400


def test_illegal_transition_is_400_unknown_is_404(client):
    item_id = client.post("/research/queue",
                          json=_problem_payload()).json()["item"]["item_id"]
    r = client.post(f"/research/queue/{item_id}/complete")
    assert r.status_code == 400
    assert r.json()["reason"] == "invalid_transition"
    nf = client.post("/research/queue/never-existed/start")
    assert nf.status_code == 404
    assert nf.json()["reason"] == "unknown_queue_item"


def test_supersede_is_a_terminal_retirement(client):
    item_id = client.post("/research/queue",
                          json=_problem_payload()).json()["item"]["item_id"]
    r = client.post(f"/research/queue/{item_id}/supersede")
    assert r.status_code == 200
    assert r.json()["item"]["status"] == "superseded"
    assert client.post(f"/research/queue/{item_id}/supersede").status_code == 400


def test_queue_summary_surface_is_not_shadowed(client):
    client.post("/research/queue", json=_problem_payload())
    r = client.get("/research/queue/summary")
    assert r.status_code == 200
    q = r.json()["queue"]
    assert q["total"] == 1
    assert q["per_status"] == {"queued": 1, "active": 0, "completed": 0,
                               "superseded": 0}
    assert q["queued_average_priority"] > 0.0
    assert q["next_up"][0]["problem"] == _problem_payload()["problem"]
    assert q["is_authorisation"] is False


# -- store failure and tenancy -------------------------------------------------


def test_unreachable_store_is_503(client, rmi_db, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("store is down")

    monkeypatch.setattr("persistence.repositories_accounts.make_live_session",
                        boom)
    for method, route in (("get", "/research/sources"),
                          ("get", "/research/sources/any"),
                          ("post", "/research/queue"),
                          ("get", "/research/queue"),
                          ("get", "/research/queue/summary")):
        body = _problem_payload() if method == "post" else None
        r = getattr(client, method)(route, json=body) if body is not None \
            else getattr(client, method)(route)
        assert r.status_code == 503, route
        assert r.json()["reason"] == "store_unavailable"


def test_tenancy_report_describes_the_rmi_surfaces(client):
    r = client.get("/system/health")
    t = r.json().get("tenancy", {})
    assert "research_sources" in t
    assert "research_queue" in t
    assert "POST /research/sources" in t["research_sources"]
    assert "ResearchPriorityScorer" in t["research_queue"]
    assert any("research/queue" in entry
               for entry in t["ownership_enforced_on"])
    assert any("research/sources" in entry
               for entry in t["ownership_enforced_on"])
