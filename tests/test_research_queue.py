"""Research Queue domain (row 749, RMI-01 slice R2).

The most important part of the RMI Factory per the operator: the lab does NOT
pick at random what to research. The tests pin the properties that keep the
queue a scored, durable problem ledger and never a permission:

- an item needs a problem and six scored dimensions, each validated into 0..1
  (fail-closed -- an out-of-range dimension is a refusal, not a re-clamp);
- a cited evidence id must exist in the plane (fail-closed on ghost ids), but
  an UNGROUNDED problem is allowed -- the queue holds matters still to be
  studied, and grounding is never invented;
- priority is deterministic: the same seven inputs always give the same score,
  and `ResearchPriorityScorer` weights are constant (expected value first,
  then data availability and reproducibility, inverted research cost, novelty,
  inverted risk) with 100 a pure win and research_cost/risk inverted;
- labels are high/medium/low on the 70/40 thresholds;
- reads order by score descending, so the lab works the ledger top-down;
- the lifecycle is queued -> active -> completed and queued -> superseded;
  terminal items are never re-opened and illegal transitions refuse;
- a burst enqueue issues per-candidate receipts -- one bad candidate is
  refused with its reason and never kills the rest of the burst;
- reads enrich a grounded item with its resolved evidence lineage and
  `backed_trust` (the highest ladder among the cited evidence);
- every outgoing payload carries `is_authorisation: False` and names the Risk
  Governor; the table has no trade-permission column.
"""

from pathlib import Path
import sys

import pytest
from sqlalchemy import delete, inspect

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from persistence.db import bind_test_session  # noqa: E402
from persistence.models_accounts import (  # noqa: E402
    EvidenceRecord,
    ResearchQueueItemRecord,
)
from persistence.repositories_accounts import (  # noqa: E402
    EvidenceRepository,
    ResearchQueueRepository,
)
from research.evidence_plane import EvidencePlaneService  # noqa: E402
from research.queue.priority import ResearchPriorityScorer  # noqa: E402
from research.queue.research_queue import ResearchQueueService  # noqa: E402


@pytest.fixture
def session():
    s = bind_test_session()
    s.execute(delete(ResearchQueueItemRecord))
    s.execute(delete(EvidenceRecord))
    s.commit()
    return s


@pytest.fixture
def plane(session):
    return EvidencePlaneService(EvidenceRepository(session))


@pytest.fixture
def repo(session):
    return ResearchQueueRepository(session)


@pytest.fixture
def service(session):
    return ResearchQueueService(
        repo=ResearchQueueRepository(session),
        plane=EvidencePlaneService(EvidenceRepository(session)))


def _columns(session, table_name: str):
    return {c["name"] for c in inspect(session.get_bind()).get_columns(table_name)}


def _dims(**extra):
    fields = {
        "expected_value": 0.8, "data_availability": 0.7,
        "research_cost": 0.4, "risk": 0.3, "novelty": 0.6,
        "reproducibility": 0.7,
    }
    fields.update(extra)
    return fields


def _problem(**extra):
    fields = {"problem": "does a volatility breakout persist across the "
                         "next close"}
    fields.update(extra if "problem" not in extra else {})
    fields.update(_dims())
    fields.update(extra)
    return {k: v for k, v in fields.items()}


# -- the queue is a knowledge ledger, never a permission ---------------------


def test_queue_table_carries_no_trade_permission_column(session):
    cols = _columns(session, "research_queue_items")
    assert "item_id" in cols
    for banned in ("grants_trade_permission", "may_trade", "can_trade",
                   "allowed_markets", "trade_authority"):
        assert banned not in cols


def test_queue_table_has_no_foreignkeys(session):
    for fk in inspect(session.get_bind()).get_foreign_keys("research_queue_items"):
        raise AssertionError(f"research_queue_items must not carry FK {fk}")


# -- a problem enters scored and validated, or it does not -------------------


def test_blank_problem_is_refused(repo):
    with pytest.raises(ValueError):
        repo.enqueue(**_problem(problem=" "))


def test_out_of_range_dimension_is_refused(repo):
    with pytest.raises(ValueError):
        repo.enqueue(**_problem(expected_value=1.3))
    with pytest.raises(ValueError):
        repo.enqueue(**_problem(risk=-0.2))


def test_ghost_evidence_id_refuses_the_item(repo, plane):
    plane.ingest(source_kind="arxiv", external_id="2401.00001",
                 headline="real", content_hash="a" * 64)
    with pytest.raises(ValueError):
        repo.enqueue(**_problem(evidence_ids=["ghost-1"]))


def test_ungrounded_problem_is_allowed(service):
    row = service.enqueue(**_problem())
    assert row["evidence_ids"] == []
    assert row["status"] == "queued"
    assert row["backed_trust"] is None
    assert row["evidence_ids_not_found"] == []


# -- priority is deterministic and bounded -----------------------------------


def test_scorer_weights_sum_to_one():
    assert sum(ResearchPriorityScorer.WEIGHTS.values()) == 1.0


def test_scorer_orders_dimensions_the_operator_specified():
    scorer = ResearchPriorityScorer()
    ordered = sorted(scorer.WEIGHTS.items(), key=lambda kv: (-kv[1], kv[0]))
    names = [n for n, _ in ordered]
    assert names == ["expected_value", "data_availability", "reproducibility",
                     "research_cost", "novelty", "risk"]


def test_score_is_deterministic():
    first = ResearchPriorityScorer().score(**_dims())
    second = ResearchPriorityScorer().score(**_dims())
    assert first == second


def test_full_win_scores_hundred():
    scorer = ResearchPriorityScorer()
    row = scorer.score(expected_value=1.0, data_availability=1.0,
                       reproducibility=1.0, research_cost=0.0, risk=0.0,
                       novelty=1.0)
    assert row == 100.0


def test_research_cost_and_risk_are_inverted():
    scorer = ResearchPriorityScorer()
    cheap = scorer.score(expected_value=0.5, data_availability=0.5,
                         reproducibility=0.5, research_cost=0.0, risk=0.5,
                         novelty=0.5)
    dear = scorer.score(expected_value=0.5, data_availability=0.5,
                        reproducibility=0.5, research_cost=1.0, risk=0.5,
                        novelty=0.5)
    assert cheap > dear
    safe = scorer.score(expected_value=0.5, data_availability=0.5,
                        reproducibility=0.5, research_cost=0.5, risk=0.0,
                        novelty=0.5)
    risky = scorer.score(expected_value=0.5, data_availability=0.5,
                         reproducibility=0.5, research_cost=0.5, risk=1.0,
                         novelty=0.5)
    assert safe > risky


def test_labels_follow_the_thresholds():
    scorer = ResearchPriorityScorer()
    assert scorer.label_for(90.0) == "high"
    assert scorer.label_for(70.0) == "high"
    assert scorer.label_for(69.99) == "medium"
    assert scorer.label_for(40.0) == "medium"
    assert scorer.label_for(39.99) == "low"


def test_enqueue_stores_score_and_label(repo):
    row = repo.enqueue(**{"problem": "p-1", "expected_value": 0.8,
                          "data_availability": 0.7, "research_cost": 0.4,
                          "risk": 0.3, "novelty": 0.6,
                          "reproducibility": 0.7})
    assert 0.0 <= row["priority_score"] <= 100.0
    assert row["priority_label"] in ("high", "medium", "low")
    assert row["priority_score"] == ResearchPriorityScorer().score(
        expected_value=0.8, data_availability=0.7, research_cost=0.4,
        risk=0.3, novelty=0.6, reproducibility=0.7)


def test_summary_reports_known_statuses_and_averages(repo):
    repo.enqueue(**_problem())
    s = repo.summary()
    assert s["total"] == 1
    assert s["known_statuses"] == ["queued", "active", "completed",
                                   "superseded"]
    assert s["queued_average_priority"] > 0.0
    assert s["next_up"][0]["problem"] == _problem()["problem"]


# -- the lifecycle ------------------------------------------------------------


def test_lifecycle_queued_active_completed(repo):
    item = repo.enqueue(**_problem())
    started = repo.transition(item["item_id"], "active")
    assert started["status"] == "active"
    assert started["started_at"]
    done = repo.transition(item["item_id"], "completed")
    assert done["status"] == "completed"
    assert done["completed_at"]


def test_illegal_transitions_refuse(repo):
    item = repo.enqueue(**_problem())
    with pytest.raises(ValueError):
        repo.transition(item["item_id"], "completed")  # queued -> completed
    superseded = repo.transition(item["item_id"], "superseded")
    assert superseded["status"] == "superseded"
    with pytest.raises(ValueError):
        repo.transition(superseded["item_id"], "active")  # terminal item


def test_terminal_items_are_never_reopened(repo):
    item = repo.enqueue(**_problem())
    repo.transition(item["item_id"], "active")
    repo.transition(item["item_id"], "completed")
    with pytest.raises(ValueError):
        repo.transition(item["item_id"], "active")


def test_unknown_status_filter_refuses(repo):
    repo.enqueue(**_problem())
    with pytest.raises(ValueError):
        repo.list_all(status="draft")


def test_gets_order_by_priority_descending(repo):
    weak = repo.enqueue(**{"problem": "weak", "expected_value": 0.1,
                           "data_availability": 0.1, "research_cost": 0.9,
                           "risk": 0.9, "novelty": 0.1,
                           "reproducibility": 0.1})
    strong = repo.enqueue(**{"problem": "strong", "expected_value": 0.9,
                             "data_availability": 0.9, "research_cost": 0.1,
                             "risk": 0.1, "novelty": 0.9,
                             "reproducibility": 0.9})
    rows = repo.list_all()
    assert [r["item_id"] for r in rows] == [strong["item_id"],
                                            weak["item_id"]]


def test_a_higher_score_is_further_up_the_ledger(repo):
    weak = repo.enqueue(**{"problem": "weak", "expected_value": 0.1,
                           "data_availability": 0.1, "research_cost": 0.9,
                           "risk": 0.9, "novelty": 0.1,
                           "reproducibility": 0.1})
    strong = repo.enqueue(**{"problem": "strong", "expected_value": 0.9,
                             "data_availability": 0.9, "research_cost": 0.1,
                             "risk": 0.1, "novelty": 0.9,
                             "reproducibility": 0.9})
    assert weak["priority_score"] < strong["priority_score"]


# -- service: burst receipts and evidence-grounding reads --------------------


def test_single_enqueue_resolves_lineage_and_backed_trust(service, plane):
    low = plane.ingest(source_kind="internal", external_id="idea-1",
                       headline="low", content_hash="b" * 64)
    mid = plane.ingest(source_kind="arxiv", external_id="2401.00002",
                       headline="mid", content_hash="c" * 64)
    item = service.enqueue(**_problem(evidence_ids=[low["evidence_id"],
                                                    mid["evidence_id"]]))
    assert {r["evidence_id"] for r in item["evidence_lineage"]} == {
        low["evidence_id"], mid["evidence_id"]}
    assert item["backed_trust"] == mid["trust_ladder"]
    assert item["evidence_ids_not_found"] == []


def test_burst_receipts_never_kill_the_rest(service, plane):
    plane.ingest(source_kind="arxiv", external_id="2401.00003",
                 headline="ok", content_hash="d" * 64)
    good = {"problem": "good one", "expected_value": 0.8,
            "data_availability": 0.6, "research_cost": 0.5, "risk": 0.4,
            "novelty": 0.7, "reproducibility": 0.6}
    bad = {"problem": "ghost citation", "evidence_ids": ["ghost-9"],
           "expected_value": 0.5, "data_availability": 0.5,
           "research_cost": 0.5, "risk": 0.5, "novelty": 0.5,
           "reproducibility": 0.5}
    result = service.enqueue_batch([good, bad, "not-an-object"])
    assert result["accepted"] == 1
    assert result["refused"] == 2
    assert result["total"] == 3
    by_problem = {r["problem"]: r for r in result["receipts"]}
    assert by_problem["good one"]["accepted"] is True
    assert by_problem["ghost citation"]["accepted"] is False
    assert by_problem["ghost citation"]["reason"], "refusal must say why"
    assert by_problem[""]["accepted"] is False
    assert by_problem[""]["reason"] == "not_an_object"
    assert len(service.list_all()) == 1


def test_queue_service_payloads_are_never_a_permission(service):
    item = service.enqueue(**_problem())
    for row in (service.get(item["item_id"]),
                service.list_all()[0],
                service.start(item["item_id"]),
                service.summary()):
        assert row["is_authorisation"] is False
        assert row["trade_authority"] == "risk/governor.py"


# -- fail-closed storage ------------------------------------------------------


def test_store_failure_raises_never_reads_empty(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("store is down")

    monkeypatch.setattr("persistence.repositories_accounts.make_live_session",
                        boom)
    with pytest.raises(RuntimeError):
        ResearchQueueRepository().get("any-id")
    with pytest.raises(RuntimeError):
        ResearchQueueRepository().summary()
