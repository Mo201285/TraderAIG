"""RMI-03 routes over the real app (row 752): the Paperclip/CrewAI loop.

The layer under test is the one the domain tests cannot see: routes that
resolve the acting principal, map `ValueError` to `400` (a refused mission,
an illegal transition, an invalid delivery with ghost evidence), a distinct
`404` for unknown queue items / missions / status filters, an unreachable
store to `503`, and serialise the mission + intelligence surfaces. Guarded
here:

- every mission route and the Ollama router report need an acting principal
  (`409`);
- creating a mission against an unknown queue item is `404`, against a
  terminal or busy item (or an empty brief) is `400` `invalid_mission`;
- `GET /research/missions/summary` is not shadowed by
  `GET /research/missions/{id}`;
- start/deliver/fail map illegal transitions to `400` and unknown missions
  to `404`; deliver with ghost evidence is `400` `invalid_delivery` and
  changes nothing;
- `GET /research/intelligence` reports the s6 tiers honestly (offline it
  says `unavailable`, never an invented model);
- reads are `read_only`, every payload carries `is_authorisation: False`
  naming the Risk Governor, and the tenancy report describes the loop.
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
    ResearchMissionRecord,
    ResearchPackageRecord,
    ResearchQueueItemRecord,
)
from research.evidence_plane import EvidencePlaneService  # noqa: E402
from research.missions.intelligence import TASK_CLASSES  # noqa: E402

OPERATOR = "rmi-mission-route-principal"


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def rmi_db(monkeypatch):
    session = bind_test_session()
    session.execute(delete(ResearchMissionRecord))
    session.execute(delete(ResearchQueueItemRecord))
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


def _problem_payload(**extra):
    payload = {
        "problem": "does a volatility breakout persist across the next close",
        "expected_value": 0.8, "data_availability": 0.7,
        "research_cost": 0.4, "risk": 0.3, "novelty": 0.6,
        "reproducibility": 0.7,
    }
    payload.update(extra)
    return payload


def _seed_queue(client) -> str:
    r = client.post("/research/queue", json=_problem_payload())
    assert r.status_code == 200, r.text
    return r.json()["item"]["item_id"]


def _seed_evidence(source_kind: str = "arxiv", tag: str = "tag") -> str:
    row = EvidencePlaneService().ingest(
        source_kind=source_kind, external_id=f"{tag}-paper",
        headline="a claim", content_hash=f"{tag}-{tag}",
        hypothesis="a hypothesis")
    return row["evidence_id"]


def _mission_payload(**extra):
    payload = {"brief": "study the claim", "note": "", "model": ""}
    payload.update(extra)
    return payload


# -- every surface needs an acting principal ----------------------------------


def test_all_mission_routes_need_a_principal(client, rmi_db, monkeypatch):
    monkeypatch.setattr("operations.api.identity.principal_user_id",
                        lambda: None)
    routes = [
        ("post", "/research/missions"),
        ("get", "/research/missions"),
        ("get", "/research/missions/summary"),
        ("get", "/research/missions/any"),
        ("post", "/research/missions/any/start"),
        ("post", "/research/missions/any/deliver"),
        ("post", "/research/missions/any/fail"),
        ("get", "/research/intelligence"),
    ]
    for method, route in routes:
        request = getattr(client, method)
        body = {"brief": "x"} if method == "post" else None
        r = request(route) if body is None else request(route, json=body)
        assert r.status_code == 409, route
        assert r.json()["reason"] == "no_principal"


# -- create -------------------------------------------------------------------


def test_create_mission_is_200_and_lists_back(client):
    item_id = _seed_queue(client)
    r = client.post("/research/missions",
                    json=_mission_payload(queue_item_id=item_id))
    assert r.status_code == 200, r.text
    mission = r.json()["mission"]
    assert mission["status"] == "assigned"
    assert mission["is_authorisation"] is False
    assert mission["trade_authority"] == "risk/governor.py"
    assert [seat["role"] for seat in mission["crew"]] == [
        "researcher", "quant", "data_analyst", "reviewer"]
    listing = client.get("/research/missions").json()
    assert listing["count"] >= 1
    assert listing["missions"][0]["mission_id"] == mission["mission_id"]


def test_create_mission_unknown_queue_item_is_404(client):
    r = client.post("/research/missions",
                    json=_mission_payload(queue_item_id="no-such-item"))
    assert r.status_code == 404
    assert r.json()["reason"] == "unknown_queue_item"


def test_create_mission_refusals_are_400(client):
    item_id = _seed_queue(client)
    r = client.post("/research/missions",
                    json=_mission_payload(queue_item_id=item_id, brief=""))
    assert r.status_code == 400
    assert r.json()["reason"] == "invalid_mission"
    first = client.post("/research/missions",
                        json=_mission_payload(queue_item_id=item_id))
    assert first.status_code == 200, first.text
    busy = client.post("/research/missions",
                       json=_mission_payload(queue_item_id=item_id,
                                             brief="another study"))
    assert busy.status_code == 400
    assert busy.json()["reason"] == "invalid_mission"
    # terminal problem is refused too
    r2 = client.post("/research/queue", json=_problem_payload(
        problem="a finished one"))
    item2 = r2.json()["item"]["item_id"]
    assert client.post(f"/research/queue/{item2}/start").status_code == 200
    assert client.post(f"/research/queue/{item2}/complete").status_code == 200
    r3 = client.post("/research/missions",
                     json=_mission_payload(queue_item_id=item2))
    assert r3.status_code == 400


# -- reads --------------------------------------------------------------------


def test_summary_is_not_shadowed_by_the_mission_id_route(client):
    r = client.get("/research/missions/summary")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["missions"]["total"] == 0
    assert body["missions"]["known_statuses"]
    assert body["read_only"] is True
    assert body["is_authorisation"] is False


def test_get_mission_unknown_id_is_404(client):
    r = client.get("/research/missions/nope")
    assert r.status_code == 404
    assert r.json()["reason"] == "unknown_mission"


def test_unknown_status_filter_is_400(client):
    r = client.get("/research/missions", params={"status": "dreaming"})
    assert r.status_code == 400
    assert r.json()["reason"] == "invalid_filter"


# -- lifecycle ----------------------------------------------------------------


def test_start_deliver_fail_lifecycle_over_http(client):
    item_id = _seed_queue(client)
    evidence = _seed_evidence(source_kind="arxiv", tag="lifecycle")
    mission = client.post(
        "/research/missions",
        json=_mission_payload(queue_item_id=item_id)).json()["mission"]
    mission_id = mission["mission_id"]

    started = client.post(f"/research/missions/{mission_id}/start")
    assert started.status_code == 200, started.text
    assert started.json()["mission"]["status"] == "running"
    assert started.json()["mission"]["queue_item"]["status"] == "active"

    refused = client.post(f"/research/missions/{mission_id}/start")
    assert refused.status_code == 400
    assert refused.json()["reason"] == "invalid_transition"

    delivered = client.post(
        f"/research/missions/{mission_id}/deliver",
        json={"title": "the package", "evidence_ids": [evidence],
              "hypothesis": "h", "method": "cross-sectional",
              "limits": "one instrument"})
    assert delivered.status_code == 200, delivered.text
    body = delivered.json()["mission"]
    assert body["status"] == "delivered"
    assert body["output_package_id"]
    assert body["queue_completed"] is True
    assert body["package"]["backed_trust"] is not None

    again = client.post(
        f"/research/missions/{mission_id}/deliver",
        json={"title": "again", "evidence_ids": [evidence]})
    assert again.status_code == 400
    assert again.json()["reason"] == "invalid_delivery"


def test_deliver_with_ghost_evidence_changes_nothing(client):
    item_id = _seed_queue(client)
    mission_id = client.post(
        "/research/missions",
        json=_mission_payload(queue_item_id=item_id)).json()[
        "mission"]["mission_id"]
    client.post(f"/research/missions/{mission_id}/start")
    r = client.post(
        f"/research/missions/{mission_id}/deliver",
        json={"title": "bad", "evidence_ids": ["ghost-id"]})
    assert r.status_code == 400
    assert r.json()["reason"] == "invalid_delivery"
    still = client.get(f"/research/missions/{mission_id}").json()["mission"]
    assert still["status"] == "running"
    packages = client.get("/research/packages").json()
    assert packages["count"] == 0


def test_deliver_from_assigned_mission_is_400(client):
    item_id = _seed_queue(client)
    evidence = _seed_evidence(source_kind="arxiv", tag="early")
    mission_id = client.post(
        "/research/missions",
        json=_mission_payload(queue_item_id=item_id)).json()[
        "mission"]["mission_id"]
    r = client.post(
        f"/research/missions/{mission_id}/deliver",
        json={"title": "early", "evidence_ids": [evidence]})
    assert r.status_code == 400
    assert r.json()["reason"] == "invalid_delivery"


def test_fail_route_keeps_the_reason_and_leaves_the_problem(client):
    item_id = _seed_queue(client)
    mission_id = client.post(
        "/research/missions",
        json=_mission_payload(queue_item_id=item_id)).json()[
        "mission"]["mission_id"]
    failed = client.post(f"/research/missions/{mission_id}/fail",
                         json={"note": "no data existed"})
    assert failed.status_code == 200, failed.text
    body = failed.json()["mission"]
    assert body["status"] == "failed"
    assert body["note"] == "no data existed"
    assert body["queue_item"]["status"] == "queued"
    refused = client.post(f"/research/missions/{mission_id}/fail",
                          json={"note": "again"})
    assert refused.status_code == 400
    # the problem stays in the ledger: a new mission is still accepted
    retry = client.post("/research/missions",
                        json=_mission_payload(queue_item_id=item_id))
    assert retry.status_code == 200


def test_mission_routes_404_on_unknown_ids(client):
    assert client.post("/research/missions/nope/start").status_code == 404
    assert client.post("/research/missions/nope/deliver",
                       json={"title": "t"}).status_code == 404
    assert client.post("/research/missions/nope/fail").status_code == 404


# -- the Ollama router report -------------------------------------------------


def test_intelligence_report_is_honest_and_needs_a_principal(client,
                                                             rmi_db,
                                                             monkeypatch):
    monkeypatch.setattr("operations.api.identity.principal_user_id",
                        lambda: None)
    assert client.get("/research/intelligence").status_code == 409


def test_intelligence_report_surfaces_the_s6_tiers(client):
    r = client.get("/research/intelligence")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["read_only"] is True
    assert body["is_authorisation"] is False
    assert body["trade_authority"] == "risk/governor.py"
    router = body["router"]
    assert set(router["task_classes"]) == set(TASK_CLASSES)
    assert len(router["routes"]) == len(TASK_CLASSES)
    assert "fast_local" in router["tiers"]
    assert "strong_local" in router["tiers"]
    assert router["cloud_fallback"]["wired"] is False
    assert "reachable" in router["probe"]
    sources = {route_["source"] for route_ in router["routes"]}
    assert sources <= {"configured", "local_probe", "unavailable"}


# -- store failure and tenancy -------------------------------------------------


def test_unreachable_store_is_503(client, rmi_db, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("store is down")

    monkeypatch.setattr("persistence.repositories_accounts.make_live_session",
                        boom)
    for method, route in (("get", "/research/missions"),
                          ("get", "/research/missions/summary"),
                          ("get", "/research/missions/any")):
        r = getattr(client, method)(route)
        assert r.status_code == 503, route
        assert r.json()["reason"] == "store_unavailable"


def test_tenancy_report_describes_the_mission_loop(client):
    t = client.get("/system/health").json().get("tenancy", {})
    assert "research_missions" in t
    assert "POST /research/missions" in t["research_missions"]
    assert "GET /research/intelligence" in t["research_missions"]
    assert any("research/missions" in entry
               for entry in t["ownership_enforced_on"])
    assert any("research/intelligence" in entry
               for entry in t["ownership_enforced_on"])
