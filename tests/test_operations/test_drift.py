"""M9.3: DriftMonitor tests (operations/drift.py)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from learning.experience import ExperienceRecord
from operations.drift import DriftMonitor, DriftThresholds


def _rec(strategy_id, pnl, slippage=0.02, delay_ms=50.0, filled=True,
         error=None):
    return ExperienceRecord(
        record_id=f"{strategy_id}-{pnl}-{slippage}-{delay_ms}",
        decision_id="d", timestamp=0.0,
        actual_result={"filled": filled, "pnl": pnl,
                       "slippage": slippage, "origin": "system"},
        slippage=slippage, delay_ms=delay_ms,
        error_classification=error,
        metadata={"strategy_id": strategy_id},
    )


def _healthy_records(n=20, pnl=10.0, slippage=0.02, delay=50.0):
    return [_rec("s:A", pnl, slippage, delay) for _ in range(n)]


def test_healthy_baseline_is_ok():
    m = DriftMonitor(thresholds=DriftThresholds(min_baseline_trades=10))
    m.observe(_healthy_records())
    signals = m.evaluate()
    assert len(signals) == 1
    assert signals[0].status == "ok"
    assert signals[0].current["win_rate"] == pytest.approx(1.0)
    assert not m.quarantine_proposals(evaluate_first=False)


def test_records_without_strategy_ignored():
    m = DriftMonitor()
    m.observe([_rec(None, pnl=10.0)])
    m.observe([ExperienceRecord(record_id="x", decision_id="y", timestamp=0.0)])
    assert m.evaluate() == []


def test_degrading_win_rate_and_execution_flags_alert(tmp_path):
    m = DriftMonitor(thresholds=DriftThresholds(
        window=20, min_baseline_trades=10, warn_after_observations=2))
    # baseline healthy window
    m.observe(_healthy_records())
    signals = m.evaluate()
    assert signals[0].status == "ok"
    # degradation window: heavy slippage + latency + losses
    degraded = [_rec("s:A", pnl=-5.0, slippage=0.5, delay_ms=400.0)
                for _ in range(10)]
    m.observe(degraded)
    signals = m.evaluate()
    assert signals[0].status == "alert"
    assert any("slippage" in r for r in signals[0].reasons)
    assert any("latency" in r or "win rate" in r for r in signals[0].reasons)


def test_quarantine_proposal_after_sustained_alert():
    m = DriftMonitor(thresholds=DriftThresholds(
        window=20, min_baseline_trades=10, warn_after_observations=2))
    m.observe(_healthy_records())
    m.evaluate()
    degraded = [_rec("s:A", pnl=-5.0, slippage=0.5, delay_ms=400.0)
                for _ in range(10)]
    for _ in range(3):                      # 3 sustained alert evaluations
        m.observe(degraded)
        m.evaluate()
    proposals = m.quarantine_proposals(evaluate_first=False)
    assert any(p["strategy_id"] == "s:A" for p in proposals)
    assert proposals[0]["suggested_stage"] == "quarantined"


def test_recovery_clears_alert():
    m = DriftMonitor(thresholds=DriftThresholds(
        window=20, min_baseline_trades=10, warn_after_observations=3))
    m.observe(_healthy_records())
    m.observe([_rec("s:A", pnl=-5.0, slippage=0.5, delay_ms=400.0)] * 10)
    m.evaluate()
    assert m._consecutive["s:A"] >= 1
    # healthy returns reset the consecutive counter
    m.observe(_healthy_records())
    sig = m.evaluate()[0]
    assert sig.status == "ok"


def test_ev_below_scope_is_ok_not_alert():
    m = DriftMonitor(thresholds=DriftThresholds(
        window=20, min_baseline_trades=10, alert_ev_floor=0.0))
    # losing strategy from the start: EV below scope -> "ok" not "alert"
    m.observe([_rec("s:neg", pnl=-1.0, slippage=0.02, delay_ms=50.0) for _ in range(20)])
    sig = m.evaluate()[0]
    assert sig.status == "ok"
    assert any("below positive-EV" in r for r in sig.reasons)
