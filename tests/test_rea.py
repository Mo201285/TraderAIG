"""The Reverse Engineering Agent seam (research/rea): adapter, registry, service.

REA runs an EXTERNAL engine (`rea-agents`) over a shipped artifact and records
what it observed. The things that must be true and are easy to get subtly wrong
are tested here at the domain layer, without a route and without the real engine:

- the adapter is a bounded, shell-free subprocess seam: an unrouted command and an
  empty target are refused (`invalid_request`) without touching the engine; a
  missing Node/package is an honest `unavailable`; a non-zero exit is
  `engine_failed`; a timeout is `timeout`; stdout that is not JSON is
  `invalid_output`; and only a clean exit with parsed JSON is `completed`;
- the adapter never raises on an engine failure -- it returns a closed outcome --
  so no caller has to catch an exception to map a status code;
- the registry declares the routed capabilities and never invents one;
- the service opens a durable job BEFORE the engine runs, closes it with the
  engine's own outcome (a failure is `failed`, never left running), summarises a
  completed run without copying the full graph, and -- only when asked -- feeds a
  successful run into the Evidence Plane at trust 0 (`internal`), where a re-run
  de-duplicates;
- nothing grants authority: `is_authorisation: False` and the Risk Governor ride
  on every payload, and a failed run is never fed to the plane.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import delete, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from persistence.db import bind_test_session  # noqa: E402
from persistence.models_accounts import EvidenceRecord, ReaJobRecord  # noqa: E402
from persistence.repositories_accounts import (  # noqa: E402
    EvidenceRepository,
    ReaJobRepository,
)
from research.evidence_plane import EvidencePlaneService  # noqa: E402
from research.rea.adapter import (  # noqa: E402
    KNOWN_COMMANDS,
    OUTCOMES,
    ReaAdapter,
    ReaEngineUnavailable,
)
from research.rea.registry import ReaRegistry  # noqa: E402
from research.rea.service import REA_EVIDENCE_SOURCE_KIND, ReaService  # noqa: E402

TRADE_AUTHORITY = "risk/governor.py"

_FAKE_EVIDENCE = {
    "evidence_id": "ev_deadbeef",
    "operation": "analyze_javascript_application",
    "provider": {"id": "rea-javascript-application"},
    "subject": {"name": "app", "local_path": "C:/tmp/app"},
    "limitations": ["parsed as inert text; bundle code was never executed"],
    "normalized_result": {
        "unknowns": [
            {"detail": "Unsupported FunctionDeclaration value."},
            {"reason": "dynamic syntax prevents an exact relation."},
        ],
    },
}


class _StubAdapter:
    """A stand-in for ReaAdapter that returns a fixed result (no real engine)."""

    def __init__(self, result):
        self._result = result
        self.calls = []

    def run(self, command, target, **kwargs):
        self.calls.append((command, target, kwargs))
        return self._result

    def status(self):
        return {"available": True, "node_bin": "node", "package_dir": "/pkg",
                "known_commands": list(KNOWN_COMMANDS), "timeout_seconds": 600,
                "is_authorisation": False, "trade_authority": TRADE_AUTHORITY}


@pytest.fixture
def session():
    s = bind_test_session()
    for model in (ReaJobRecord, EvidenceRecord):
        s.execute(delete(model))
    s.commit()
    return s


# -- registry ---------------------------------------------------------------

def test_registry_declares_only_routed_commands():
    reg = ReaRegistry()
    commands = [c.command for c in reg.list()]
    assert commands, "the registry must declare capabilities"
    assert all(c in KNOWN_COMMANDS for c in commands)
    summary = reg.summary()
    assert summary["count"] == len(commands)
    assert summary["read_only"] is True
    assert summary["is_authorisation"] is False
    assert summary["trade_authority"] == TRADE_AUTHORITY


def test_registry_unknown_command_is_none():
    assert ReaRegistry().get("no-such-command") is None
    assert ReaRegistry().get("").__class__ is type(None)


# -- adapter (pure logic, no engine) ----------------------------------------

def test_adapter_refuses_unrouted_command_without_engine():
    result = ReaAdapter().run("no-such-command", "C:/tmp/app")
    assert result["outcome"] == "invalid_request"
    assert result["ok"] is False
    assert result["is_authorisation"] is False
    assert result["trade_authority"] == TRADE_AUTHORITY
    assert result["outcome"] in OUTCOMES


def test_adapter_refuses_empty_target_without_engine():
    result = ReaAdapter().run("analyze-javascript-application", "  ")
    assert result["outcome"] == "invalid_request"
    assert result["ok"] is False


def test_adapter_reports_unavailable_when_engine_absent(tmp_path):
    # Point at a runtime dir that does not exist and a Node bin that does not
    # exist -- the adapter must report `unavailable`, not raise.
    adapter = ReaAdapter(node_bin=str(tmp_path / "no-node.exe"),
                         runtime_dir=str(tmp_path / "no-pkg"))
    result = adapter.run("analyze-javascript-application", str(tmp_path))
    assert result["outcome"] == "unavailable"
    assert result["ok"] is False
    assert adapter.available() is False


def test_adapter_can_raise_on_unavailable_when_asked(tmp_path):
    adapter = ReaAdapter(node_bin=str(tmp_path / "no-node.exe"),
                         runtime_dir=str(tmp_path / "no-pkg"))
    with pytest.raises(ReaEngineUnavailable):
        adapter.run("analyze-javascript-application", str(tmp_path),
                    raise_on_unavailable=True)


# -- service (fake adapter + real job ledger) --------------------------------

def test_service_records_failed_run_and_never_feeds_a_failure(session):
    stub = _StubAdapter({"outcome": "engine_failed", "ok": False,
                         "detail": "the engine exited with code 2",
                         "progress": [{"phase": "x"}]})
    evidence = EvidencePlaneService(EvidenceRepository(session))
    service = ReaService(adapter=stub, jobs=ReaJobRepository(session),
                         evidence=evidence)
    job = service.investigate(
        command="analyze-javascript-application", target="C:/tmp/app",
        requested_by="TEST-ACCT-1", feed_evidence=True)
    assert job["ok"] is False
    assert job["status"] == "failed"
    assert job["outcome"] == "engine_failed"
    assert job["evidence_id"] == ""
    assert job["is_authorisation"] is False
    assert job["trade_authority"] == TRADE_AUTHORITY
    # a failed run must not have created an evidence row
    assert session.execute(select(EvidenceRecord)).scalars().all() == []


def test_service_completes_and_feeds_evidence_at_trust_zero(session):
    stub = _StubAdapter({"outcome": "completed", "ok": True,
                         "evidence": _FAKE_EVIDENCE, "stdout_bytes": 1234,
                         "progress": [{"phase": "seal", "terminal": True}]})
    evidence = EvidencePlaneService(EvidenceRepository(session))
    service = ReaService(adapter=stub, jobs=ReaJobRepository(session),
                         evidence=evidence)
    job = service.investigate(
        command="analyze-javascript-application", target="C:/tmp/app",
        requested_by="TEST-ACCT-1", feed_evidence=True)
    assert job["ok"] is True
    assert job["status"] == "completed"
    assert job["outcome"] == "completed"
    assert job["evidence_id"], "a fed run names its evidence row"
    # the summary is digest-sized and carries the engine's own limits/unknowns
    assert job["summary"]["evidence_id"] == "ev_deadbeef"
    assert job["summary"]["operation"] == "analyze_javascript_application"
    assert job["summary"]["unknowns"], "unknowns are preserved, not dropped"
    assert job["summary"]["limitations"]
    # the evidence row is internal (our own analysis) at trust level 0
    row = evidence.get(job["evidence_id"])
    assert row["source_kind"] == REA_EVIDENCE_SOURCE_KIND
    assert row["trust_ladder"] == 0
    assert row["is_authorisation"] is False


def test_service_rerun_deduplicates_evidence(session):
    stub = _StubAdapter({"outcome": "completed", "ok": True,
                         "evidence": _FAKE_EVIDENCE, "stdout_bytes": 10,
                         "progress": []})
    evidence = EvidencePlaneService(EvidenceRepository(session))
    service = ReaService(adapter=stub, jobs=ReaJobRepository(session),
                         evidence=evidence)
    first = service.investigate(command="analyze-javascript-application",
                                target="C:/tmp/app", feed_evidence=True)
    second = service.investigate(command="analyze-javascript-application",
                                 target="C:/tmp/app", feed_evidence=True)
    assert first["evidence_id"] == second["evidence_id"]
    rows = session.execute(select(EvidenceRecord)).scalars().all()
    assert len(rows) == 1


def test_service_without_feed_leaves_no_evidence(session):
    stub = _StubAdapter({"outcome": "completed", "ok": True,
                         "evidence": _FAKE_EVIDENCE, "stdout_bytes": 10,
                         "progress": []})
    evidence = EvidencePlaneService(EvidenceRepository(session))
    service = ReaService(adapter=stub, jobs=ReaJobRepository(session),
                         evidence=evidence)
    job = service.investigate(command="analyze-javascript-application",
                              target="C:/tmp/app", feed_evidence=False)
    assert job["ok"] is True
    assert job["evidence_id"] == ""
    assert job["fed_evidence"] is False
    assert session.execute(select(EvidenceRecord)).scalars().all() == []


def test_service_summary_counts(session):
    stub = _StubAdapter({"outcome": "unavailable", "ok": False,
                         "detail": "engine missing", "progress": []})
    service = ReaService(adapter=stub, jobs=ReaJobRepository(session))
    service.investigate(command="analyze-javascript-application", target="C:/x")
    service.investigate(command="analyze-javascript-application", target="C:/y")
    summary = service.summary()
    assert summary["total"] == 2
    assert summary["per_status"]["failed"] == 2
    assert summary["per_outcome"]["unavailable"] == 2
    assert summary["known_commands"] == list(KNOWN_COMMANDS)
    assert summary["is_authorisation"] is False


def test_job_repository_lifecycle_is_terminal(session):
    repo = ReaJobRepository(session)
    job = repo.request(command="analyze-javascript-application", target="C:/x")
    assert job["status"] == "requested"
    repo.start(job["job_id"])
    repo.finish(job["job_id"], outcome="completed",
                summary={"evidence_id": "ev_1"}, progress=[])
    with pytest.raises(ValueError):
        repo.start(job["job_id"])


# -- hardening: the closed vocabulary, the bounded read, the declared roster --

def test_repository_outcome_vocabulary_matches_the_adapter():
    # The repository duplicates the outcome vocabulary on purpose (a load-time
    # cycle forbids importing it); this pins the two equal so they can never drift.
    from persistence.repositories_accounts import REA_OUTCOMES
    assert REA_OUTCOMES == OUTCOMES


def test_job_repository_filters_by_outcome(session):
    repo = ReaJobRepository(session)
    done = repo.request(command="analyze-javascript-application", target="C:/a")
    repo.start(done["job_id"])
    repo.finish(done["job_id"], outcome="completed", progress=[])
    failed = repo.request(command="analyze-javascript-application", target="C:/b")
    repo.start(failed["job_id"])
    repo.fail(failed["job_id"], outcome="engine_failed")

    completed = repo.list_all(outcome="completed")
    assert [r["job_id"] for r in completed] == [done["job_id"]]
    assert repo.count(outcome="engine_failed") == 1
    assert repo.count() == 2
    with pytest.raises(ValueError):
        repo.list_all(outcome="no-such-outcome")


def test_job_repository_pages_a_growing_ledger(session):
    repo = ReaJobRepository(session)
    ids = []
    for i in range(5):
        row = repo.request(command="analyze-javascript-application",
                           target=f"C:/t{i}")
        repo.start(row["job_id"])
        repo.finish(row["job_id"], outcome="completed", progress=[])
        ids.append(row["job_id"])

    page1 = repo.list_all(limit=2, offset=0)
    page2 = repo.list_all(limit=2, offset=2)
    page3 = repo.list_all(limit=2, offset=4)
    assert len(page1) == 2 and len(page2) == 2 and len(page3) == 1
    seen = [r["job_id"] for r in page1 + page2 + page3]
    assert sorted(seen) == sorted(ids)
    # count reports the whole ledger, not the page -- so a page is never
    # mistaken for the table
    assert repo.count() == 5


def test_service_refuses_a_command_the_registry_does_not_declare(session):
    # A command the engine might route but this deployment has NOT declared must
    # be refused before a job row is opened -- the registry is the authority.
    import research.rea.registry as registry_mod
    original = registry_mod._BY_COMMAND
    registry_mod._BY_COMMAND = {}
    try:
        service = ReaService(
            adapter=_StubAdapter({"outcome": "completed", "ok": True,
                                  "evidence": _FAKE_EVIDENCE}),
            jobs=ReaJobRepository(session))
        with pytest.raises(ValueError):
            service.investigate(command="analyze-javascript-application",
                                target="C:/x")
    finally:
        registry_mod._BY_COMMAND = original
    # no job was opened for a command the deployment never declared
    assert session.execute(select(ReaJobRecord)).scalars().all() == []


def test_service_capabilities_roster(session):
    service = ReaService(adapter=_StubAdapter({"outcome": "completed",
                                               "ok": True,
                                               "evidence": _FAKE_EVIDENCE}),
                         jobs=ReaJobRepository(session))
    report = service.capabilities()
    assert report["count"] >= 1
    commands = [c["command"] for c in report["capabilities"]]
    assert commands
    for capability in report["capabilities"]:
        assert capability["proposes_never_executes"] is True
        assert capability["is_authorisation"] is False
        assert capability["trade_authority"] == TRADE_AUTHORITY
    assert report["is_authorisation"] is False
    assert report["trade_authority"] == TRADE_AUTHORITY


# -- real engine integration (skipped when the engine is not pinned) ---------

def _engine_present() -> bool:
    return ReaAdapter().available()


@pytest.mark.skipif(not _engine_present(),
                    reason="the REA engine is not pinned on this deployment")
def test_real_engine_runs_against_a_tiny_javascript_tree(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "index.js").write_text(
        "const x = 1; function f(){ return x + 2; } module.exports = { f };\n",
        encoding="ascii")
    result = ReaAdapter().run("analyze-javascript-application", str(app))
    assert result["outcome"] == "completed", result.get("detail")
    evidence = result["evidence"]
    assert isinstance(evidence, dict)
    assert evidence.get("evidence_id")
    assert evidence.get("operation") == "analyze_javascript_application"
    assert result["progress"], "the engine streams a progress log"
    assert result["is_authorisation"] is False
