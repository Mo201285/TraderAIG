"""Evidence Plane domain: the ONE institutional object the external world feeds.

Row 746 (P1 slice) turns n8n-delivered external reality -- arXiv/SSRN papers,
GitHub events, macro prints, sentiment snapshots -- into durable evidence. The
tests pin the properties that keep the plane institutional and never a
permission:

- the `evidence_items` table carries no `grants_trade_permission`/`may_trade`/
  `can_trade` column and no foreign key, asserted by inspection -- absence is a
  fact, not a docstring;
- ingestion is idempotent by `content_hash`: the same inbound matter returns
  the stored row with ``is_new=False``, never a second copy (the intake
  contract n8n works against);
- unknown `source_kind` is refused, and an out-of-ladder trust default is
  refused -- fail-closed at intake;
- external kinds arrive at trust level 1 (external evidence); an `internal`
  idea starts at level 0 -- the lab does not invent external backing;
- the trust ladder is 0..9 and ONLY moves up: a downgrade is refused
  (monotonic evidence about the evidence);
- classification attaches the structured reading; absent fields stay absent
  ("not reported" is never "zero"), and an explicit empty list/string is a real
  write, distinct from omitting the field;
- every outgoing row carries `is_authorisation: False` and names the Risk
  Governor;
- a failed store lookup raises (fail-closed) -- an outage must not read as "no
  evidence was ever collected";
- the consistency checker reports evidence drift (unknown kind, malformed
  hash, ladder out of bounds) instead of silently accepting it; a duplicated
  content_hash is not checked because the column is UNIQUE, and a checker that
  reports an impossible state is a checker nobody can trust.
"""

from pathlib import Path
import sys

import pytest
from sqlalchemy import delete, inspect, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from persistence.db import bind_test_session  # noqa: E402
from persistence.models_accounts import EvidenceRecord  # noqa: E402
from persistence.repositories_accounts import (  # noqa: E402
    AccountConsistencyChecker,
    EvidenceRepository,
)
from research.evidence_plane import (  # noqa: E402
    EXTERNAL_START_LEVEL,
    INTERNAL_START_LEVEL,
    EvidencePlaneService,
    TRUST_GOVERNANCE,
    TRUST_PRODUCTION,
)


@pytest.fixture
def session():
    s = bind_test_session()
    s.execute(delete(EvidenceRecord))
    s.commit()
    return s


@pytest.fixture
def plane(session):
    return EvidencePlaneService(EvidenceRepository(session))


def _columns(session, table_name: str):
    return {c["name"] for c in inspect(session.get_bind()).get_columns(table_name)}


def test_evidence_table_grants_no_trade_permission(session):
    cols = _columns(session, "evidence_items")
    forbidden = {"grants_trade_permission", "may_trade", "can_trade"}
    assert not (forbidden & cols), f"evidence_items must not carry {forbidden}"
    for expected in ("evidence_id", "source_kind", "external_id", "source_uri",
                     "topic", "headline", "content_hash", "relevance",
                     "confidence", "source_quality", "markets_json",
                     "timeframes_json", "regimes_json", "hypothesis",
                     "trust_ladder", "note", "created_at"):
        assert expected in cols, f"evidence_items missing column {expected}"


def test_evidence_table_has_no_foreign_keys(session):
    fks = inspect(session.get_bind()).get_foreign_keys("evidence_items")
    assert fks == [], "evidence_items is self-contained: no foreign keys"


def test_ingest_stores_external_at_level_one(plane, session):
    row = plane.ingest(source_kind="arxiv", external_id="2401.00001",
                       headline="A paper about volatility",
                       payload={"paper": "2401.00001"})
    assert row["is_new"] is True
    assert row["source_kind"] == "arxiv"
    assert row["trust_ladder"] == EXTERNAL_START_LEVEL == 1
    assert row["trust_label"] == "external_evidence"
    assert row["content_hash"]
    got = session.get(EvidenceRecord, row["evidence_id"])
    assert got is not None
    assert got.markets_json == "[]"


def test_internal_idea_starts_at_level_zero(plane):
    row = plane.ingest(source_kind="internal", external_id="idea-1",
                       headline="lab hypothesis", payload={"i": 1})
    assert row["trust_ladder"] == INTERNAL_START_LEVEL == 0
    assert row["trust_label"] == "ai_idea"


def test_same_content_again_is_idempotent(plane, session):
    first = plane.ingest(source_kind="macro", external_id="CPI:2026Q1:US",
                         headline="CPI",
                         content_hash="same-digest", payload={"h": "x"})
    second = plane.ingest(source_kind="macro", external_id="CPI:2026Q1:US",
                          headline="CPI re-sent",
                          content_hash="same-digest", payload={"h": "x2"})
    assert second["evidence_id"] == first["evidence_id"]
    assert second["is_new"] is False
    count = session.execute(select(EvidenceRecord)).scalars().all()
    assert len(count) == 1
    assert count[0].headline == "CPI"  # the stored row wins; nothing overwritten


def test_same_external_matter_one_copy_only(plane, session):
    """Idempotency through the content digest, not through the caller passing
    the key by hand: the same payload string must be stored once."""
    a = plane.ingest(source_kind="github", external_id="repo:release:v1.0.0",
                     headline="release", payload={"kind": "github-event",
                                                  "repo": "acme/x"})
    b = plane.ingest(source_kind="github", external_id="repo:release:v1.0.0",
                     headline="release", payload={"kind": "github-event",
                                                  "repo": "acme/x"})
    assert a["evidence_id"] == b["evidence_id"]
    assert a["is_new"] is True
    assert b["is_new"] is False


def test_unknown_source_kind_refused(plane):
    with pytest.raises(ValueError):
        plane.ingest(source_kind="youtube", external_id="x", headline="nope",
                     payload="x")


def test_out_of_ladder_default_refused(session):
    repo = EvidenceRepository(session)
    with pytest.raises(ValueError):
        repo.ingest(content_hash="h", source_kind="internal",
                    external_id="x", headline="x", trust_ladder=57)
    with pytest.raises(ValueError):
        repo.ingest(content_hash="h2", source_kind="internal",
                    external_id="x", headline="x", trust_ladder=-3)


def test_classify_absent_fields_stay_absent(plane):
    row = plane.ingest(source_kind="sentiment", external_id="BTC:2026-10-07",
                       headline="btc snapshot", payload={"s": 1})
    plane.classify(row["evidence_id"], relevance=0.62)
    row2 = plane.classify(row["evidence_id"], markets=["BTC"], regimes=["trending"])
    assert row2["relevance"] == 0.62  # untouched by the second call
    assert row2["confidence"] is None  # still absent, not zero
    assert row2["markets"] == ["BTC"]
    assert row2["regimes"] == ["trending"]
    assert row2["timeframes"] == []


def test_classify_explicit_empty_is_a_real_write(plane):
    row = plane.ingest(source_kind="arxiv", external_id="2401.00002",
                       headline="h", payload={"a": 1})
    plane.classify(row["evidence_id"], markets=["BTC", "ETH"])
    assert plane.get(row["evidence_id"])["markets"] == ["BTC", "ETH"]
    plane.classify(row["evidence_id"], markets=[], confidence=0.5)
    row2 = plane.get(row["evidence_id"])
    assert row2["markets"] == []
    assert row2["confidence"] == 0.5


def test_get_unknown_returns_none(plane):
    assert plane.get("no-such-id") is None


def test_reads_fail_closed(plane):
    class Boom:
        def list_all(self, **kwargs):
            raise RuntimeError("store is down")

    plane._repo = Boom()
    with pytest.raises(RuntimeError):
        plane.list_all()


def test_advance_trust_is_monotonic_up(plane):
    row = plane.ingest(source_kind="arxiv", external_id="2401.00003",
                       headline="h", payload={"p": 1})  # level 1
    plane.advance_trust(row["evidence_id"], TRUST_GOVERNANCE)  # 8
    assert plane.get(row["evidence_id"])["trust_ladder"] == 8
    with pytest.raises(ValueError):
        plane.advance_trust(row["evidence_id"], 2)  # downward: refused
    plane.advance_trust(row["evidence_id"], TRUST_PRODUCTION)  # 9
    assert plane.get(row["evidence_id"])["trust_ladder"] == 9


def test_advance_trust_bounds_refused(plane):
    row = plane.ingest(source_kind="macro", external_id="NFP:2026Q1:US",
                       headline="nfp", payload={"m": 1})
    with pytest.raises(ValueError):
        plane.advance_trust(row["evidence_id"], -1)
    with pytest.raises(ValueError):
        plane.advance_trust(row["evidence_id"], 11)


def test_every_outgoing_row_is_not_authorisation(plane):
    row = plane.ingest(source_kind="ssrn", external_id="SRN-1", headline="h",
                       payload={"z": 1})
    got = plane.get(row["evidence_id"])
    for key in ("is_authorisation", "trade_authority"):
        assert key in got
    assert got["is_authorisation"] is False
    assert got["trade_authority"] == "risk/governor.py"
    assert plane.get(row["evidence_id"])["trust_label"] in (
        "external_evidence", "ai_idea")


def test_list_all_filters(plane, session):
    plane.ingest(source_kind="arxiv", external_id="2401.00004", headline="a1",
                 payload={"f": 1}, markets=["BTC"], regimes=["trending"],
                 topic="volatility")
    plane.ingest(source_kind="macro", external_id="CPI:2026Q2:US", headline="a2",
                 payload={"f": 2}, markets=["XAUUSD"], regimes=["high_volatility"],
                 topic="macro.cpi")
    all_rows = plane.list_all()
    assert len(all_rows) == 2
    assert len(plane.list_all(source_kind="arxiv")) == 1
    assert len(plane.list_all(topic="macro.cpi")) == 1
    assert len(plane.list_all(market="BTC")) == 1
    assert len(plane.list_all(regime="high_volatility")) == 1
    assert len(plane.list_all(min_trust=1)) == 2
    assert len(plane.list_all(min_trust=5)) == 0


def test_summary_buckets(plane):
    plane.ingest(source_kind="arxiv", external_id="2401.00005", headline="h",
                 payload={"s": 1})
    plane.ingest(source_kind="macro", external_id="CPI:2026Q3:US", headline="h",
                 payload={"s": 2})
    plane.ingest(source_kind="internal", external_id="idea-9", headline="h",
                 payload={"s": 3})
    summary = plane.summary()
    assert summary["total"] == 3
    assert summary["per_source"] == {"arxiv": 1, "macro": 1, "internal": 1}
    assert summary["per_ladder"]["0"] == 1
    assert summary["per_ladder"]["1"] == 2
    assert summary["per_ladder"]["9"] == 0
    assert set(summary["per_ladder"]) == {str(i) for i in range(10)}
    assert summary["is_authorisation"] is False
    assert summary["trade_authority"] == "risk/governor.py"


def test_drift_reports_bad_rows_and_quiet_after_cleanup(session):
    """Out-of-band inserts (the only way to break the invariants, since ingest
    validates them) are reported by the checker, then the checker is quiet once
    the rows are gone -- a quiet report is a real fact, not a default. A
    duplicated content_hash is not part of the test: the column is UNIQUE, so a
    duplicate is impossible and checking for it would report an un-triggerable
    state."""
    import uuid

    rows = [
        (uuid.uuid4().hex, "not-a-kind", "x" * 64, 1),
        (uuid.uuid4().hex, "arxiv", "y" * 64, -1),
        (uuid.uuid4().hex, "macro", "", 5),
    ]
    for evidence_id, kind, digest, trust in rows:
        session.add(EvidenceRecord(
            evidence_id=evidence_id, source_kind=kind,
            content_hash=digest if digest else "", headline="out-of-band",
            trust_ladder=trust))
    session.commit()

    checker = AccountConsistencyChecker(session)
    drift = checker.evidence_drift()
    kinds = {kind for row in drift for kind in row["kinds"]}
    assert "unknown_source_kind" in kinds
    assert "bad_content_hash" in kinds
    assert "trust_ladder_out_of_bounds" in kinds
    assert "duplicate_content_hash" not in (
        kind for row in drift for kind in row["kinds"])
    report = checker.report()
    assert report["ok"] is False
    assert report["evidence_drift"] == 3

    session.execute(delete(EvidenceRecord))
    session.commit()
    quiet = AccountConsistencyChecker(session).report()
    assert quiet["ok"] is True
    assert quiet["evidence_drift"] == 0
