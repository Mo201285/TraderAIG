"""Ownership separation tests for MT5-originated trades."""

from types import SimpleNamespace

from execution.mt5_adapter import MT5Adapter
from learning.experience import ExperienceRecord
from learning.performance import PerformanceAttributor


def test_origin_classifier_marks_traderaig_magic_or_comment_as_system():
    adapter = MT5Adapter()
    assert adapter._classify_origin(magic=123456, comment="") == "system"
    assert adapter._classify_origin(magic=0, comment="TraderAIG:abc123") == "system"


def test_origin_classifier_marks_unlabeled_trade_as_manual():
    adapter = MT5Adapter()
    assert adapter._classify_origin(magic=0, comment="") == "manual"
    assert adapter._classify_origin(magic=None, comment=None) == "manual"


def test_deal_to_record_tags_origin_metadata(monkeypatch):
    adapter = MT5Adapter()
    seen = []

    monkeypatch.setattr("learning.experience.ledger.record", lambda rec: seen.append(rec), raising=False)

    deal = SimpleNamespace(
        deal=11,
        ticket=11,
        time=1000,
        symbol="XAUUSD",
        volume=0.1,
        price=2000.0,
        type=0,
        entry=0,
        profit=10.0,
        commission=-1.0,
        swap=0.0,
        magic=123456,
        comment="TraderAIG:test",
    )
    adapter._deal_to_record(deal)

    assert seen
    rec = seen[-1]
    assert rec.actual_result["origin"] == "system"
    assert rec.metadata["magic"] == 123456
    assert rec.metadata["comment"] == "TraderAIG:test"


def test_performance_excludes_manual_records_by_default():
    attributor = PerformanceAttributor()
    records = [
        ExperienceRecord(
            record_id="sys-1",
            decision_id="d1",
            timestamp=1.0,
            actual_result={"pnl": 50.0, "filled": True, "origin": "system"},
        ),
        ExperienceRecord(
            record_id="man-1",
            decision_id="d2",
            timestamp=2.0,
            actual_result={"pnl": -200.0, "filled": True, "origin": "manual"},
        ),
    ]

    report = attributor.generate(records)
    assert report.total_trades == 1
    assert report.net_pnl == 50.0


def test_performance_by_strategy_rolls_up_provenance():
    """L1 (appendix B): per-strategy PnL from real execution provenance,
    with un-stamped records landing in `unattributed` (never dropped)."""
    attributor = PerformanceAttributor()
    records = [
        ExperienceRecord(record_id="a1", decision_id="d", timestamp=1.0,
                         actual_result={"pnl": 10.0, "filled": True,
                                        "origin": "system"},
                         metadata={"strategy_id": "s:one"}),
        ExperienceRecord(record_id="a2", decision_id="d", timestamp=2.0,
                         actual_result={"pnl": -4.0, "filled": True,
                                        "origin": "system"},
                         metadata={"strategy_id": "s:one"}),
        ExperienceRecord(record_id="b1", decision_id="d", timestamp=3.0,
                         actual_result={"pnl": 30.0, "filled": True,
                                        "origin": "system"},
                         metadata={"strategy_id": "s:two"}),
        ExperienceRecord(record_id="m1", decision_id="d", timestamp=4.0,
                         actual_result={"pnl": 99.0, "filled": True,
                                        "origin": "manual"}),
        ExperienceRecord(record_id="u1", decision_id="d", timestamp=5.0,
                         actual_result={"pnl": 5.0, "filled": True,
                                        "origin": "system"}),
    ]

    rows = attributor.by_strategy(records)
    by = {r["strategy_id"]: r for r in rows}
    assert by["s:one"]["net_pnl"] == 6.0
    assert by["s:one"]["total_trades"] == 2
    assert by["s:two"]["net_pnl"] == 30.0
    assert "unattributed" in by
    assert by["unattributed"]["net_pnl"] == 5.0
    # manual-owned records never mix into the attribution (system-only rollup)
    total_system = sum(r["net_pnl"] for r in rows)
    assert total_system == 41.0
