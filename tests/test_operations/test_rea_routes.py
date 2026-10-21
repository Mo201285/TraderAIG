"""The `/rea/*` routes over the real app (research/rea).

The domain tests cover the adapter/registry/service; this layer covers what only
the routes can get wrong:

- the REA mutation rail is gated like any other route (a session or the service
  token), and a refused request (unknown command, empty target) is a distinct
  `400` `invalid_request`;
- a run the engine could not answer is a recorded job whose outcome names why --
  the route maps it to `502` with the engine's reason, never a fake `200`;
- a completed run is `200`, the job is readable back by id (`404` for a ghost),
  and the list/summary/capabilities surfaces report it -- the list is a bounded
  page with a true `total`, never a page mistaken for the whole ledger;
- nothing grants authority: `is_authorisation: False` and the Risk Governor ride
  on every payload.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from operations.api import app  # noqa: E402
from persistence.db import bind_test_session  # noqa: E402
from persistence.models_accounts import EvidenceRecord, ReaJobRecord  # noqa: E402
from persistence.repositories_accounts import (  # noqa: E402
    EvidenceRepository,
    ReaJobRepository,
)
from research.evidence_plane import EvidencePlaneService  # noqa: E402
from research.rea.adapter import ReaAdapter, KNOWN_COMMANDS  # noqa: E402
from research.rea.service import ReaService  # noqa: E402

TRADE_AUTHORITY = "risk/governor.py"

OPERATOR = "rea-route-principal"

_FAKE_EVIDENCE = {
    "evidence_id": "ev_route",
    "operation": "analyze_javascript_application",
    "provider": {"id": "rea-javascript-application"},
    "subject": {"name": "app"},
    "limitations": ["parsed as inert text"],
    "normalized_result": {"unknowns": [{"detail": "dynamic syntax"}]},
}


class _StubAdapter:
    def __init__(self, result):
        self._result = result

    def run(self, command, target, **kwargs):
        return self._result

    def status(self):
        return {"available": True, "node_bin": "node", "package_dir": "/pkg",
                "known_commands": list(KNOWN_COMMANDS), "timeout_seconds": 600,
                "is_authorisation": False, "trade_authority": TRADE_AUTHORITY}


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def rea_db(monkeypatch):
    session = bind_test_session()
    for model in (ReaJobRecord, EvidenceRecord):
        session.execute(delete(model))
    session.commit()
    monkeypatch.setattr("persistence.repositories_accounts.make_live_session",
                        lambda: session)
    return session


@pytest.fixture(autouse=True)
def _principal(monkeypatch):
    monkeypatch.setattr("operations.api.identity.principal_user_id",
                        lambda: OPERATOR)


def _bind_service(monkeypatch, session, result):
    service = ReaService(
        adapter=_StubAdapter(result), jobs=ReaJobRepository(session),
        evidence=EvidencePlaneService(EvidenceRepository(session)))
    monkeypatch.setattr("operations.api._rea_service", lambda: service)
    return service


def _ok_result():
    return {"outcome": "completed", "ok": True, "evidence": _FAKE_EVIDENCE,
            "stdout_bytes": 42, "progress": [{"phase": "seal"}]}


# -- the engine cannot answer -------------------------------------------------

def test_all_rea_routes_need_a_principal(client, rea_db, monkeypatch):
    monkeypatch.setattr("operations.api.identity.principal_user_id",
                        lambda: None)
    calls = [
        ("get", "/rea/health", {}),
        ("get", "/rea/capabilities", {}),
        ("post", "/rea/investigate",
         {"json": {"command": "analyze-javascript-application",
                   "target": "C:/x"}}),
        ("get", "/rea/jobs", {}),
        ("get", "/rea/jobs/summary", {}),
        ("get", "/rea/jobs/any", {}),
        ("get", "/rea/jobs/any/evidence", {}),
    ]
    for method, route, kwargs in calls:
        r = getattr(client, method)(route, **kwargs)
        assert r.status_code == 409, route
        assert r.json()["reason"] == "no_principal"


def test_investigate_engine_failure_is_502(client, rea_db, monkeypatch):
    _bind_service(monkeypatch, rea_db,
                  {"outcome": "engine_failed", "ok": False,
                   "detail": "the engine exited with code 2", "progress": []})
    resp = client.post("/rea/investigate",
                       json={"command": "analyze-javascript-application",
                             "target": "C:/tmp/app"})
    assert resp.status_code == 502
    body = resp.json()
    assert body["ok"] is False
    assert body["reason"] == "engine_failed"
    assert body["job"]["status"] == "failed"
    assert body["is_authorisation"] is False
    assert body["trade_authority"] == TRADE_AUTHORITY


def test_investigate_adapter_invalid_request_is_502(client, rea_db, monkeypatch):
    # When the ADAPTER reports invalid_request for a DECLARED command (the engine
    # refused it), the run is a recorded failure -> 502 with the named reason.
    # (The registry pre-check is the separate 400 path, covered below.)
    _bind_service(monkeypatch, rea_db,
                  {"outcome": "invalid_request", "ok": False,
                   "detail": "the engine refused the target", "progress": []})
    resp = client.post("/rea/investigate",
                       json={"command": "analyze-javascript-application",
                             "target": "C:/x"})
    assert resp.status_code == 502
    assert resp.json()["reason"] == "invalid_request"


def test_investigate_undeclared_command_is_400(client, rea_db, monkeypatch):
    # The REAL service refuses a command the registry does not declare, before
    # any job row exists -- a clean 400, the adapter never touched.
    from sqlalchemy import select
    from research.evidence_plane import EvidencePlaneService
    from research.rea.service import ReaService
    service = ReaService(jobs=ReaJobRepository(rea_db),
                         evidence=EvidencePlaneService(EvidenceRepository(rea_db)))
    monkeypatch.setattr("operations.api._rea_service", lambda: service)
    resp = client.post("/rea/investigate",
                       json={"command": "definitely-not-a-command",
                             "target": "C:/x"})
    assert resp.status_code == 400
    assert resp.json()["reason"] == "invalid_request"
    assert rea_db.execute(select(ReaJobRecord)).scalars().all() == []


def test_investigate_empty_target_is_400(client, rea_db, monkeypatch):
    # An empty target is refused by the repository BEFORE the engine is touched,
    # so the route maps the ValueError to a 400 -- and no job row is written.
    _bind_service(monkeypatch, rea_db, _ok_result())
    resp = client.post("/rea/investigate",
                       json={"command": "analyze-javascript-application",
                             "target": ""})
    assert resp.status_code == 400
    assert resp.json()["reason"] == "invalid_request"
    from sqlalchemy import select
    rows = rea_db.execute(select(ReaJobRecord)).scalars().all()
    assert rows == []


# -- the engine answers -------------------------------------------------------

def test_investigate_success_is_200_and_readable(client, rea_db, monkeypatch):
    _bind_service(monkeypatch, rea_db, _ok_result())
    resp = client.post("/rea/investigate",
                       json={"command": "analyze-javascript-application",
                             "target": "C:/tmp/app"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    job_id = body["job"]["job_id"]
    assert body["job"]["status"] == "completed"
    assert body["is_authorisation"] is False

    got = client.get(f"/rea/jobs/{job_id}")
    assert got.status_code == 200
    assert got.json()["job"]["job_id"] == job_id
    assert got.json()["job"]["outcome"] == "completed"


def test_investigate_with_feed_links_evidence(client, rea_db, monkeypatch):
    _bind_service(monkeypatch, rea_db, _ok_result())
    resp = client.post("/rea/investigate",
                       json={"command": "analyze-javascript-application",
                             "target": "C:/tmp/app", "feed_evidence": True})
    assert resp.status_code == 200
    assert resp.json()["job"]["evidence_id"]


def test_list_and_summary_surfaces(client, rea_db, monkeypatch):
    service = _bind_service(monkeypatch, rea_db, _ok_result())
    service.investigate(command="analyze-javascript-application",
                        target="C:/tmp/app")
    lst = client.get("/rea/jobs")
    assert lst.status_code == 200
    assert lst.json()["count"] == 1
    summary = client.get("/rea/jobs/summary")
    assert summary.status_code == 200
    assert summary.json()["rea"]["total"] == 1
    assert summary.json()["rea"]["per_status"]["completed"] == 1


def test_list_invalid_status_filter_is_400(client, rea_db, monkeypatch):
    _bind_service(monkeypatch, rea_db, _ok_result())
    resp = client.get("/rea/jobs?status=no-such-status")
    assert resp.status_code == 400
    assert resp.json()["reason"] == "invalid_filter"


def test_list_invalid_outcome_filter_is_400(client, rea_db, monkeypatch):
    _bind_service(monkeypatch, rea_db, _ok_result())
    resp = client.get("/rea/jobs?outcome=no-such-outcome")
    assert resp.status_code == 400
    assert resp.json()["reason"] == "invalid_filter"


def test_list_pages_the_ledger_with_a_true_total(client, rea_db, monkeypatch):
    service = _bind_service(monkeypatch, rea_db, _ok_result())
    for i in range(5):
        service.investigate(command="analyze-javascript-application",
                            target=f"C:/t{i}")
    page = client.get("/rea/jobs?limit=2&offset=0")
    assert page.status_code == 200
    body = page.json()
    assert body["count"] == 2, "the page is bounded"
    assert body["total"] == 5, "the total is the whole ledger, not the page"
    assert body["limit"] == 2 and body["offset"] == 0
    page2 = client.get("/rea/jobs?limit=2&offset=2")
    assert page2.json()["count"] == 2
    assert page2.json()["total"] == 5


def test_capabilities_surface(client, rea_db, monkeypatch):
    _bind_service(monkeypatch, rea_db, _ok_result())
    resp = client.get("/rea/capabilities")
    assert resp.status_code == 200
    body = resp.json()
    assert body["rea"]["count"] >= 1
    assert body["rea"]["capabilities"]
    assert body["is_authorisation"] is False
    assert body["trade_authority"] == TRADE_AUTHORITY


def test_unknown_job_is_404(client, rea_db, monkeypatch):
    _bind_service(monkeypatch, rea_db, _ok_result())
    resp = client.get("/rea/jobs/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["reason"] == "unknown_job"


# -- the linked evidence read -------------------------------------------------

def test_job_evidence_reads_the_fed_item(client, rea_db, monkeypatch):
    # A fed run is readable back through the linked-evidence surface: the plane
    # item the job was fed into is returned, with `linked: True`.
    service = _bind_service(monkeypatch, rea_db, _ok_result())
    job = service.investigate(command="analyze-javascript-application",
                              target="C:/tmp/app", feed_evidence=True)
    job_id = job["job_id"]
    assert job["evidence_id"], "a fed run links an evidence id"

    resp = client.get(f"/rea/jobs/{job_id}/evidence")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["rea"]["linked"] is True
    assert body["rea"]["linked_evidence_id"] == job["evidence_id"]
    assert body["rea"]["evidence"]["evidence_id"] == job["evidence_id"]
    assert body["rea"]["evidence"]["trust_ladder"] == 0
    assert body["is_authorisation"] is False
    assert body["trade_authority"] == TRADE_AUTHORITY


def test_job_evidence_unfed_is_honest_linked_false(client, rea_db, monkeypatch):
    # A completed run that was never fed is `linked: False` with `reason:
    # not_fed` -- not an error, and not a fabricated item.
    service = _bind_service(monkeypatch, rea_db, _ok_result())
    job = service.investigate(command="analyze-javascript-application",
                              target="C:/tmp/app")
    resp = client.get(f"/rea/jobs/{job['job_id']}/evidence")
    assert resp.status_code == 200
    body = resp.json()
    assert body["rea"]["linked"] is False
    assert body["rea"]["evidence"] is None
    assert body["rea"]["reason"] == "not_fed"


def test_job_evidence_unknown_job_is_404(client, rea_db, monkeypatch):
    _bind_service(monkeypatch, rea_db, _ok_result())
    resp = client.get("/rea/jobs/ghost/evidence")
    assert resp.status_code == 404
    assert resp.json()["reason"] == "unknown_job"


def test_health_surface(client, rea_db, monkeypatch):
    _bind_service(monkeypatch, rea_db, _ok_result())
    resp = client.get("/rea/health")
    assert resp.status_code == 200
    body = resp.json()
    assert "available" in body["rea"]
    assert body["rea"]["registry"]["count"] >= 1
    assert body["is_authorisation"] is False


# -- real engine through the route (skipped when the engine is absent) --------

def _engine_present() -> bool:
    return ReaAdapter().available()


@pytest.mark.skipif(not _engine_present(),
                    reason="the REA engine is not pinned on this deployment")
def test_real_engine_through_the_route(client, rea_db, tmp_path):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "index.js").write_text(
        "module.exports = { a: 1 };\n", encoding="ascii")
    service = ReaService(jobs=ReaJobRepository(rea_db),
                         evidence=EvidencePlaneService(EvidenceRepository(rea_db)))
    # Let the factory build the service, but bind the real job repo to the test
    # session so the live engine runs while the ledger stays isolated.
    import operations.api as api_mod
    monkey = pytest.MonkeyPatch()
    monkey.setattr(api_mod, "_rea_service", lambda: service)
    try:
        resp = client.post("/rea/investigate",
                           json={"command": "analyze-javascript-application",
                                 "target": str(app_dir)})
    finally:
        monkey.undo()
    assert resp.status_code == 200, resp.text
    assert resp.json()["job"]["status"] == "completed"
