"""Research Mission domain (row 752, RMI-03 slice).

The master architecture's research chain is `Paperclip -> Research Mission ->
CrewAI -> Research Package -> TrederAIG Research API` (MASTER_ARCHITECTURE
s8/s9): Paperclip is the organisation that decides what to study, the Research
Mission is that decision as a durable assignment of a queue problem to a
four-role CrewAI crew, and Ollama is the intelligence layer (s6) whose router
names the model each task would run on. The tests pin the properties that keep
the loop an institutional research assignment and never a permission:

- the `research_missions` table carries no trade-permission column and no
  foreign key, asserted by inspection;
- `create` is fail-closed and issueable only against a queue problem the
  ledger already holds: unknown or terminal queue item, empty brief, an
  already-open mission on the same item and a non-canonical crew are all
  refused;
- the crew is deterministic: the same brief always composes the same four
  s9 seats with the same task text; `model` is carried verbatim and never
  invented when absent;
- the lifecycle is assigned -> running -> delivered | failed (assigned ->
  failed allowed); terminal missions are never re-opened;
- `start` picks a still-queued queue item up and says whether it did;
- `deliver` records the Research Package FIRST through the fail-closed
  knowledge factory (a crew that cites nothing or cites a ghost delivers
  nothing and the mission stays running) and only then stamps the mission
  delivered and completes the queue item;
- `fail` keeps its reason on the row and leaves the problem in the ledger --
  a failed mission never blocks a later one;
- the Ollama router (s6) routes task classes to fast/strong local tiers
  deterministically, reports an offline server honestly (no invented model
  name) and refuses an unknown task class;
- the consistency checker reports mission drift (an unknown queue item or a
  delivered mission whose package vanished out-of-band);
- every payload is `is_authorisation: False` and names the Risk Governor.
"""

from pathlib import Path
import sys

import pytest
from sqlalchemy import delete, inspect, update

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from persistence.db import bind_test_session  # noqa: E402
from persistence.models_accounts import (  # noqa: E402
    EvidenceRecord,
    ResearchMissionRecord,
    ResearchPackageRecord,
    ResearchQueueItemRecord,
)
from persistence.repositories_accounts import (  # noqa: E402
    AccountConsistencyChecker,
    EvidenceRepository,
    MISSION_STATUSES,
    ResearchMissionRepository,
    ResearchPackageRepository,
    ResearchQueueRepository,
)
from research.evidence_plane import EvidencePlaneService  # noqa: E402
from research.knowledge import ResearchKnowledgeFactory  # noqa: E402
from research.missions.crew import CREW_ROLES, compose_crew  # noqa: E402
from research.missions.intelligence import (  # noqa: E402
    FAST_LOCAL_TASKS,
    STRONG_LOCAL_TASKS,
    TASK_CLASSES,
    route,
    router_report,
)
from research.missions.service import ResearchMissionService  # noqa: E402


@pytest.fixture
def session():
    s = bind_test_session()
    s.execute(delete(ResearchMissionRecord))
    s.execute(delete(ResearchQueueItemRecord))
    s.execute(delete(ResearchPackageRecord))
    s.execute(delete(EvidenceRecord))
    s.commit()
    return s


@pytest.fixture
def service(session):
    return ResearchMissionService(
        missions=ResearchMissionRepository(session),
        queue=ResearchQueueRepository(session),
        knowledge=ResearchKnowledgeFactory(
            packages=ResearchPackageRepository(session),
            plane=EvidencePlaneService(EvidenceRepository(session))))


@pytest.fixture
def plane(session):
    return EvidencePlaneService(EvidenceRepository(session))


def _item(queue, problem="does a volatility breakout persist"):
    return queue.enqueue(
        problem=problem, expected_value=0.8, data_availability=0.7,
        research_cost=0.4, risk=0.3, novelty=0.6, reproducibility=0.7)


def _columns(session, table_name: str):
    return {c["name"] for c in inspect(session.get_bind()).get_columns(table_name)}


# -- shape: self-contained, never permission -----------------------------------


def test_the_mission_table_is_self_contained_and_never_a_permission(session):
    columns = _columns(session, "research_missions")
    assert {"mission_id", "queue_item_id", "brief", "crew_json", "model",
            "status", "output_package_id", "note", "created_at", "updated_at",
            "started_at", "finished_at"} <= columns
    for banned in ("grants_trade_permission", "may_trade", "can_trade"):
        assert banned not in columns
    inspector = inspect(session.get_bind())
    foreign_keys = inspector.get_foreign_keys("research_missions")
    assert not foreign_keys, "the mission table must stay self-contained"


def test_create_issues_the_canonical_crew_against_a_live_queue_item(
        service, session):
    item = _item(ResearchQueueRepository(session))
    mission = service.create(
        queue_item_id=item["item_id"], brief="study the claim",
        model="llama3.2:3b", note="assigned by Paperclip")
    assert mission["status"] == "assigned"
    assert mission["queue_item_id"] == item["item_id"]
    assert mission["model"] == "llama3.2:3b"
    assert mission["note"] == "assigned by Paperclip"
    roles = [seat["role"] for seat in mission["crew"]]
    assert roles == list(CREW_ROLES)
    assert mission["output_package_id"] == ""
    assert mission["is_authorisation"] is False
    assert mission["trade_authority"] == "risk/governor.py"
    assert mission["queue_item"]["problem"] == item["problem"]


def test_create_is_fail_closed(service, session):
    queue = ResearchQueueRepository(session)
    item = _item(queue)
    with pytest.raises(ValueError):
        service.create(queue_item_id=item["item_id"], brief="")
    with pytest.raises(ValueError):
        service.create(queue_item_id="no-such-item", brief="study x")
    terminal = _item(queue, problem="a finished problem")
    queue.transition(terminal["item_id"], "active")
    queue.transition(terminal["item_id"], "completed")
    with pytest.raises(ValueError):
        service.create(queue_item_id=terminal["item_id"], brief="study x")
    service.create(queue_item_id=item["item_id"], brief="study x")
    with pytest.raises(ValueError):
        service.create(queue_item_id=item["item_id"], brief="study x again")


def test_the_crew_cannot_be_invented(service, session):
    item = _item(ResearchQueueRepository(session))
    repo = ResearchMissionRepository(session)
    good_crew = compose_crew("study x")
    repo.create(queue_item_id=item["item_id"], brief="study x",
                crew=good_crew)
    fifth_role = good_crew + [{"role": "navigator", "task": "steer"}]
    with pytest.raises(ValueError):
        repo.create(queue_item_id=item["item_id"], brief="study x",
                    crew=fifth_role)
    no_reviewer = [seat for seat in good_crew
                   if seat["role"] != "reviewer"]
    with pytest.raises(ValueError):
        repo.create(queue_item_id=item["item_id"], brief="study x",
                    crew=no_reviewer)
    with pytest.raises(ValueError):
        repo.create(queue_item_id=item["item_id"], brief="study x", crew=[])


# -- crew: deterministic s9 seats ----------------------------------------------


def test_crew_composition_is_deterministic_and_pinned_to_s9_roles():
    first = compose_crew("what is the claim", model="llama3.2:3b")
    second = compose_crew("what is the claim", model="llama3.2:3b")
    assert first == second
    assert [seat["role"] for seat in first] == list(CREW_ROLES)
    for seat in first:
        assert "what is the claim" in seat["task"]
        assert seat["task_class"] in TASK_CLASSES
        assert seat["model"] == "llama3.2:3b"
    unnamed = compose_crew("what is the claim")
    assert all(seat["model"] == "" for seat in unnamed)
    with pytest.raises(ValueError):
        compose_crew("   ")


# -- Ollama router: s6 tiers, honest offline -----------------------------------


def test_the_router_routes_every_task_class_to_a_tier():
    for task in FAST_LOCAL_TASKS:
        assert route(task)["tier"] == "fast_local"
    for task in STRONG_LOCAL_TASKS:
        assert route(task)["tier"] == "strong_local"
    with pytest.raises(ValueError):
        route("dream")


def test_the_router_names_models_deterministically_and_honestly():
    fast = route("summarize", local_models=["b-model", "a-model"])
    strong = route("review", local_models=["b-model", "a-model"])
    assert fast["model"] == "a-model"
    assert fast["source"] == "local_probe"
    assert strong["model"] == "b-model"
    configured = route("summarize", local_models=["b", "a"],
                       configured="cg", reachable=True)
    assert configured["model"] == "cg"
    assert configured["source"] == "configured"
    offline = route("summarize", local_models=[], configured="",
                    reachable=False)
    assert offline["model"] == ""
    assert offline["source"] == "unavailable"
    assert offline["reachable"] is False


def test_router_report_is_a_read_surface_that_never_calls_a_model():
    report = router_report(probe={
        "reachable": True,
        "models": [{"name": "llama3.2:3b", "size_gb": 2.1},
                   {"name": "llama3.2:8b", "size_gb": 5.5}]},
        configured="llama3.2:3b")
    assert report["probe"]["reachable"] is True
    assert report["probe"]["model_count"] == 2
    assert report["configured_model"] == "llama3.2:3b"
    routes = report["routes"]
    assert len(routes) == len(TASK_CLASSES)
    assert {r["task_class"] for r in routes} == set(TASK_CLASSES)
    by_class = {r["task_class"]: r for r in routes}
    assert by_class["review"]["tier"] == "strong_local"
    assert by_class["review"]["model"] == "llama3.2:3b"
    assert by_class["summarize"]["tier"] == "fast_local"
    assert report["cloud_fallback"]["wired"] is False
    assert report["is_authorisation"] is False


def test_router_report_is_honest_offline():
    report = router_report(probe={"reachable": False, "models": []},
                           configured="")
    assert report["probe"]["reachable"] is False
    assert report["configured_model"] is None
    assert all(r["source"] == "unavailable" for r in report["routes"])
    assert all(r["model"] == "" for r in report["routes"])


# -- lifecycle -----------------------------------------------------------------


def test_start_moves_the_mission_and_picks_the_queue_item_up(
        service, session):
    item = _item(ResearchQueueRepository(session))
    mission = service.create(queue_item_id=item["item_id"],
                             brief="study x")
    started = service.start(mission["mission_id"])
    assert started["status"] == "running"
    assert started["queue_transitioned"] is True
    assert started["queue_item"]["status"] == "active"
    assert started["started_at"]
    with pytest.raises(ValueError):
        service.start(mission["mission_id"])


def test_start_leaves_an_already_active_item_where_it_is(service, session):
    queue = ResearchQueueRepository(session)
    item = _item(queue)
    queue.transition(item["item_id"], "active")
    mission = service.create(queue_item_id=item["item_id"], brief="study x")
    started = service.start(mission["mission_id"])
    assert started["status"] == "running"
    assert started["queue_transitioned"] is False


def test_start_refuses_a_problem_the_ledger_retired(service, session):
    queue = ResearchQueueRepository(session)
    item = _item(queue)
    mission = service.create(queue_item_id=item["item_id"], brief="study x")
    queue.transition(item["item_id"], "active")
    queue.transition(item["item_id"], "completed")
    with pytest.raises(ValueError):
        service.start(mission["mission_id"])


def test_deliver_records_the_package_first_and_closes_the_loop(
        service, session, plane):
    evidence = plane.ingest(source_kind="arxiv", external_id="2401.00030",
                            headline="a verified claim", content_hash="c" * 64)
    item = _item(ResearchQueueRepository(session))
    mission = service.create(queue_item_id=item["item_id"], brief="study x")
    service.start(mission["mission_id"])
    delivered = service.deliver(
        mission_id=mission["mission_id"], title="the package",
        evidence_ids=[evidence["evidence_id"]],
        hypothesis="the claim holds", method="cross-sectional",
        limits="one instrument")
    assert delivered["status"] == "delivered"
    assert delivered["output_package_id"]
    assert delivered["package"]["title"] == "the package"
    assert delivered["package"]["backed_trust"] == evidence["trust_ladder"]
    assert delivered["queue_completed"] is True
    assert delivered["queue_item"]["status"] == "completed"
    assert delivered["finished_at"]
    # the queue item is now terminal -- no new mission on it
    with pytest.raises(ValueError):
        service.create(queue_item_id=item["item_id"], brief="study x again")
    # the delivered mission is terminal
    with pytest.raises(ValueError):
        service.deliver(
            mission_id=mission["mission_id"], title="again",
            evidence_ids=[evidence["evidence_id"]])


def test_deliver_is_fail_closed_and_changes_nothing(service, session, plane):
    evidence = plane.ingest(source_kind="arxiv", external_id="2401.00031",
                            headline="a claim", content_hash="d" * 64)
    packages = ResearchPackageRepository(session)
    item = _item(ResearchQueueRepository(session))
    mission = service.create(queue_item_id=item["item_id"], brief="study x")
    service.start(mission["mission_id"])
    with pytest.raises(ValueError):
        service.deliver(mission_id=mission["mission_id"], title="bad",
                        evidence_ids=["ghost-id"])
    with pytest.raises(ValueError):
        service.deliver(mission_id=mission["mission_id"], title="bad",
                        evidence_ids=[])
    after = service.get(mission["mission_id"])
    assert after["status"] == "running"
    assert packages.list_all() == []
    good = service.deliver(
        mission_id=mission["mission_id"], title="good",
        evidence_ids=[evidence["evidence_id"]])
    assert good["status"] == "delivered"


def test_deliver_requires_a_running_mission(service, session, plane):
    evidence = plane.ingest(source_kind="arxiv", external_id="2401.00032",
                            headline="a claim", content_hash="e" * 64)
    item = _item(ResearchQueueRepository(session))
    mission = service.create(queue_item_id=item["item_id"], brief="study x")
    with pytest.raises(ValueError):
        service.deliver(mission_id=mission["mission_id"], title="early",
                        evidence_ids=[evidence["evidence_id"]])
    assert service.get(mission["mission_id"])["status"] == "assigned"


def test_fail_keeps_the_reason_and_the_problem_in_the_ledger(
        service, session):
    item = _item(ResearchQueueRepository(session))
    mission = service.create(queue_item_id=item["item_id"],
                             brief="study x", note="first try")
    failed = service.fail(mission["mission_id"], note="no data existed")
    assert failed["status"] == "failed"
    assert failed["note"] == "no data existed"
    assert failed["finished_at"]
    assert failed["queue_item"]["status"] == "queued"
    with pytest.raises(ValueError):
        service.start(mission["mission_id"])
    retry = service.create(queue_item_id=item["item_id"], brief="study x")
    assert retry["status"] == "assigned"


# -- summary and checker -------------------------------------------------------


def test_summary_counts_lifecycles_honestly(service, session):
    empty = service.summary()
    assert empty["total"] == 0
    assert empty["open"] == 0
    assert set(empty["known_statuses"]) == set(MISSION_STATUSES)
    item = _item(ResearchQueueRepository(session))
    service.create(queue_item_id=item["item_id"], brief="study x")
    summary = service.summary()
    assert summary["total"] == 1
    assert summary["per_status"]["assigned"] == 1
    assert summary["open"] == 1
    assert summary["is_authorisation"] is False


def test_checker_reports_mission_drift(session, plane):
    repo = ResearchMissionRepository(session)
    queue = ResearchQueueRepository(session)
    item = _item(queue)
    evidence = plane.ingest(source_kind="arxiv", external_id="2401.00033",
                            headline="a claim", content_hash="f" * 64)
    mission = repo.create(queue_item_id=item["item_id"], brief="study x",
                          crew=compose_crew("study x"))
    repo.start(mission["mission_id"])
    repo.deliver(mission["mission_id"], "pkg-x")
    session.add(ResearchPackageRecord(
        package_id="pkg-x", title="the package", status="recorded",
        evidence_ids_json=f'["{evidence["evidence_id"]}"]'))
    session.execute(update(ResearchMissionRecord).where(
        ResearchMissionRecord.mission_id == mission["mission_id"]).values(
        queue_item_id="ghost-item"))
    session.commit()
    checker = AccountConsistencyChecker(session)
    drift = checker.research_missions_drift()
    assert any(d["mission_id"] == mission["mission_id"] and
               "unknown_queue_item" in d["problems"] for d in drift)
    report = checker.report()
    assert report["ok"] is False
    assert report["research_missions_drift"] >= 1
    # the drift row must not leak into sibling tests' quiet-checker scans
    session.execute(delete(ResearchMissionRecord))
    session.execute(delete(ResearchQueueItemRecord))
    session.execute(delete(ResearchPackageRecord))
    session.execute(delete(EvidenceRecord))
    session.commit()


def test_checker_is_quiet_for_a_delivered_mission_out_of_band_wiped(
        session, plane):
    repo = ResearchMissionRepository(session)
    queue = ResearchQueueRepository(session)
    item = _item(queue)
    evidence = plane.ingest(source_kind="arxiv", external_id="2401.00034",
                            headline="a claim", content_hash="g" * 64)
    mission = repo.create(queue_item_id=item["item_id"], brief="study x",
                          crew=compose_crew("study x"))
    repo.start(mission["mission_id"])
    repo.deliver(mission["mission_id"], "pkg-y")
    session.add(ResearchPackageRecord(
        package_id="pkg-y", title="the package", status="recorded",
        evidence_ids_json=f'["{evidence["evidence_id"]}"]'))
    session.commit()
    assert AccountConsistencyChecker(session).report()["ok"] is True
    # out-of-band: the delivered package vanishes -> the mission is red
    session.execute(update(ResearchMissionRecord).where(
        ResearchMissionRecord.mission_id == mission["mission_id"]).values(
        output_package_id="pkg-z"))
    session.commit()
    drift = AccountConsistencyChecker(session).research_missions_drift()
    assert any(d["mission_id"] == mission["mission_id"] and
               "unknown_output_package" in d["problems"] for d in drift)
    # the drift row must not leak into sibling tests' quiet-checker scans
    session.execute(delete(ResearchMissionRecord))
    session.execute(delete(ResearchQueueItemRecord))
    session.execute(delete(ResearchPackageRecord))
    session.execute(delete(EvidenceRecord))
    session.commit()
