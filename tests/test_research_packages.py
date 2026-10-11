"""Research Knowledge Factory package domain (row 748, P3 slice).

The Research Package is the institutional object a Paperclip/CrewAI research
mission returns INTO the canonical core (MASTER_ARCHITECTURE s9). The tests pin
the properties that keep the factory a knowledge store and never a permission:

- the `research_packages` table carries no `grants_trade_permission`/`may_trade`/
  `can_trade` column and no foreign key, asserted by inspection;
- a package may only cite evidence rows that already exist: an empty citation
  list or any cited id the plane does not know refuses the whole package
  (fail-closed -- no knowledge entry is fabricated from thin air);
- every package needs a title, and reads reject an unknown status filter;
- the reads enrich a package with its resolved evidence lineage and
  `backed_trust` -- the highest ladder among the cited evidence (a claim's
  maturity is read off its evidence, never asserted by the package);
- `growth()` is the Evidence-Backed Growth compliance surface: it reports ONLY
  what exists, per source family evidence_count + package_count + content_ready
  (no evidence, or evidence with no package, is honestly not content-ready);
- a store failure raises (fail-closed) -- an outage must not read as "no
  packages were ever collected";
- the consistency checker reports research-package drift (a row whose cited
  evidence vanished through out-of-band edits) instead of silently accepting it.
"""

from pathlib import Path
import sys

import pytest
from sqlalchemy import delete, inspect

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from persistence.db import bind_test_session  # noqa: E402
from persistence.models_accounts import (  # noqa: E402
    EvidenceRecord,
    ResearchPackageRecord,
)
from persistence.repositories_accounts import (  # noqa: E402
    AccountConsistencyChecker,
    EvidenceRepository,
    ResearchPackageRepository,
)
from research.evidence_plane import EvidencePlaneService  # noqa: E402
from research.knowledge import ResearchKnowledgeFactory  # noqa: E402


@pytest.fixture
def session():
    s = bind_test_session()
    s.execute(delete(ResearchPackageRecord))
    s.execute(delete(EvidenceRecord))
    s.commit()
    return s


@pytest.fixture
def repo(session):
    return ResearchPackageRepository(session)


@pytest.fixture
def plane(session):
    return EvidencePlaneService(EvidenceRepository(session))


@pytest.fixture
def factory(session):
    return ResearchKnowledgeFactory(
        packages=ResearchPackageRepository(session),
        plane=EvidencePlaneService(EvidenceRepository(session)),
    )


def _columns(session, table_name: str):
    return {c["name"] for c in inspect(session.get_bind()).get_columns(table_name)}


# -- the table is a knowledge object, never a permission ---------------------


def test_package_table_carries_no_trade_permission_column(session):
    cols = _columns(session, "research_packages")
    assert "package_id" in cols
    for banned in ("grants_trade_permission", "may_trade", "can_trade",
                   "allowed_markets", "trade_authority"):
        assert banned not in cols


def test_package_table_has_no_foreignkeys(session):
    for fk in inspect(session.get_bind()).get_foreign_keys("research_packages"):
        assert False, f"research_packages unexpectedly has FK {fk}"
    # no AssertionError means no FK exists; the loop above covers it
    assert True


# -- recording is fail-closed -------------------------------------------------


def test_record_needs_a_title(repo):
    with pytest.raises(ValueError):
        repo.record(title="  ", evidence_ids=["any"])


def test_record_refuses_empty_evidence_list(repo):
    with pytest.raises(ValueError):
        repo.record(title="no fabrication", evidence_ids=[])


def test_record_refuses_evidence_the_plane_does_not_know(repo, session):
    with pytest.raises(ValueError) as exc:
        repo.record(title="ghost citation", evidence_ids=["ghost-1"])
    assert "ghost-1" in str(exc.value)


def test_record_refuses_whole_package_when_only_one_id_is_ghost(repo, plane):
    got = plane.ingest(source_kind="macro", external_id="CPI:2026Q4:US",
                       headline="cpi", content_hash="m" * 64)
    with pytest.raises(ValueError) as exc:
        repo.record(title="one ghost", evidence_ids=[got["evidence_id"],
                                                     "ghost-1"])
    assert "ghost-1" in str(exc.value)


def test_record_roundtrip_enriches_lineage_and_backed_trust(repo, plane, session):
    a = plane.ingest(source_kind="macro", external_id="CPI:2026Q4:US",
                     headline="cpi", markets=["BTC"], content_hash="a" * 64)
    b = plane.ingest(source_kind="macro", external_id="CPI:2026Q5:US",
                     headline="cpi2", markets=["BTC", "ETH"],
                     content_hash="b" * 64)
    plane.advance_trust(b["evidence_id"], level=4)
    package = repo.record(title="Q4 pricing", evidence_ids=[a["evidence_id"],
                                                            b["evidence_id"]],
                          hypothesis="disinflation", method="statistical")
    got = ResearchKnowledgeFactory(repo, plane).get(package["package_id"])
    assert got is not None
    assert got["title"] == "Q4 pricing"
    assert got["hypothesis"] == "disinflation"
    assert sorted(e["evidence_id"] for e in got["evidence_lineage"]) == \
        sorted([a["evidence_id"], b["evidence_id"]])
    assert got["backed_trust"] == 4  # highest ladder among cited evidence
    assert got["evidence_ids_not_found"] == []
    assert got["is_authorisation"] is False
    assert got["trade_authority"] == "risk/governor.py"


# -- reads ---------------------------------------------------------------------


def test_list_filters_by_status_and_citing_evidence(repo, plane):
    a = plane.ingest(source_kind="arxiv", external_id="2401.00010",
                     headline="paper", content_hash="c" * 64)
    plane.ingest(source_kind="arxiv", external_id="2401.00011",
                 headline="paper2", content_hash="d" * 64)
    repo.record(title="pkg one", evidence_ids=[a["evidence_id"]])
    repo.record(title="pkg two",
                evidence_ids=[plane.ingest(source_kind="arxiv",
                                           external_id="2401.00012",
                                           headline="paper3",
                                           content_hash="e" * 64)
                              ["evidence_id"]])
    only_one = repo.list_all(evidence_id=a["evidence_id"])
    assert len(only_one) == 1
    assert only_one[0]["title"] == "pkg one"


def test_list_rejects_unknown_status(repo):
    with pytest.raises(ValueError):
        repo.list_all(status="promoted")


def test_summary_counts_statuses_and_coverage(repo, plane):
    a = plane.ingest(source_kind="macro", external_id="m1", headline="m",
                     content_hash="f" * 64)
    b = plane.ingest(source_kind="macro", external_id="m2", headline="m",
                     content_hash="g" * 64)
    repo.record(title="p1", evidence_ids=[a["evidence_id"]])
    repo.record(title="p2", evidence_ids=[a["evidence_id"], b["evidence_id"]])
    s = repo.summary()
    assert s["total"] == 2
    assert s["per_status"] == {"recorded": 2}
    assert s["cited_evidence_ids"] == 2


# -- Evidence-Backed Growth ----------------------------------------------------

def test_growth_reports_only_what_exists(factory, plane):
    macro = plane.ingest(source_kind="macro", external_id="CPI:2026Q4:US",
                         headline="cpi", markets=["BTC"], content_hash="h" * 64)
    # evidence exists with NO package -> honestly not content-ready
    g1 = factory.growth()
    assert g1["total_evidence"] == 1
    assert g1["per_source"]["macro"]["evidence_count"] == 1
    assert g1["per_source"]["macro"]["package_count"] == 0
    assert g1["per_source"]["macro"]["content_ready"] is False
    assert g1["content_ready_by_anything"] is False
    # package arrives -> that family becomes content-ready
    factory.record_package(title="cpi package",
                           evidence_ids=[macro["evidence_id"]])
    g2 = factory.growth()
    assert g2["per_source"]["macro"]["package_count"] == 1
    assert g2["per_source"]["macro"]["content_ready"] is True
    assert g2["content_ready_by_anything"] is True
    assert g2["content_ready_markets"] == ["BTC"]


def test_growth_flags_packages_with_no_surviving_evidence(factory, session):
    a = factory._plane.ingest(source_kind="arxiv", external_id="2401.00020",
                              headline="p", content_hash="i" * 64)
    factory.record_package(title="pkg", evidence_ids=[a["evidence_id"]])
    session.execute(delete(EvidenceRecord))
    session.commit()
    g = factory.growth()
    assert g["total_evidence"] == 0
    assert g["total_packages"] == 1
    assert g["claimed_by_no_evidence"] is True
    assert g["per_source"] == {}


def test_growth_is_never_a_permission(factory):
    g = factory.growth()
    assert g["is_authorisation"] is False
    assert g["trade_authority"] == "risk/governor.py"


# -- fail-closed storage -------------------------------------------------------

def test_store_failure_raises_never_reads_empty(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("store is down")

    monkeypatch.setattr("persistence.repositories_accounts.make_live_session",
                        boom)
    with pytest.raises(RuntimeError):
        ResearchPackageRepository().get("any-id")


# -- consistency checker -------------------------------------------------------

def test_checker_reports_package_drift_for_ghost_citations(session):
    session.add(ResearchPackageRecord(
        package_id="pkg-ghost", title="ghost citation",
        evidence_ids_json='["ghost-1"]', status="recorded"))
    session.commit()
    checker = AccountConsistencyChecker(session)
    drift = checker.research_packages_drift()
    assert len(drift) == 1
    assert drift[0]["package_id"] == "pkg-ghost"
    assert drift[0]["missing_ids"] == ["ghost-1"]
    report = checker.report()
    assert report["ok"] is False
    assert report["research_packages_drift"] == 1


def test_checker_quiet_when_packages_are_clean(session, plane):
    a = plane.ingest(source_kind="arxiv", external_id="2401.00030",
                     headline="p", content_hash="j" * 64)
    repo = ResearchPackageRepository(session)
    repo.record(title="clean", evidence_ids=[a["evidence_id"]])
    report = AccountConsistencyChecker(session).report()
    assert report["research_packages_drift"] == 0
    assert report["ok"] is True
