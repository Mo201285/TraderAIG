"""M8.4: research vs execution learning split tests
(learning/learning_split.py)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from learning.experience import ExperienceRecord
from learning.learning_split import execution_learning, research_learning, split
from research.strategy_lab.contracts import (
    ExitReason,
    OosSplit,
    SpreadBucket,
    StrategyFamily,
    TradeObservation,
    VolatilityBucket,
)


def _record(pnl=5.0, slippage=0.02, delay=50.0, filled=True, origin="system"):
    return ExperienceRecord(
        record_id=f"r-{pnl}-{slippage}-{delay}-{origin}",
        decision_id="d", timestamp=0.0,
        actual_result={"filled": filled, "pnl": pnl, "slippage": slippage,
                       "origin": origin},
        slippage=slippage, delay_ms=delay,
    )


def _observations(n=10, strategy_id="s1", r=0.3, regime="bullish/normal",
                  session="london", weekday=2):
    return [
        TradeObservation(
            experiment_id="e", strategy_id=strategy_id,
            family=StrategyFamily.ICT_LIQUIDITY_SWEEP_REVERSAL, variant_hash="h",
            asset="XAUUSD", htf_tf="H1", setup_tf="M15", trigger_tf="M1",
            session=session, weekday=weekday, regime=regime,
            volatility_bucket=VolatilityBucket.MEDIUM,
            spread_bucket=SpreadBucket.NORMAL,
            entry_type="matrix_pool", sl_model="lt", tp_model="zt",
            pattern_geometry="", macro_state="",
            mfe_r=1.0, mae_r=-0.4, exit_reason=ExitReason.TARGET,
            oos_split=OosSplit.OUT_OF_SAMPLE, walkforward_window=i % 2,
            pnl=r, r_multiple=r)
        for i in range(n)
    ]


def test_execution_learning_counts_and_metrics():
    records = [_record(pnl=10.0), _record(pnl=-5.0, slippage=0.1, delay=90.0),
               _record(pnl=3.0)]
    rep = execution_learning(records)
    assert rep["count"] == 3
    assert rep["wins"] == 2
    assert rep["losses"] == 1
    assert rep["win_rate"] == pytest.approx(2 / 3)
    assert rep["avg_slippage"] == pytest.approx((0.02 + 0.1 + 0.02) / 3, abs=5e-4)
    assert rep["avg_delay_ms"] == pytest.approx((50.0 + 90.0 + 50.0) / 3, abs=5e-2)
    assert "experience_ledger" in rep["storage"]


def test_execution_learning_excludes_manual_ownership():
    records = [_record(origin="manual", pnl=100.0)]
    rep = execution_learning(records)
    assert rep["count"] == 0


def test_execution_learning_excludes_unfilled():
    records = [_record(filled=False, pnl=0.0)]
    rep = execution_learning(records)
    assert rep["count"] == 0


def test_research_learning_aggregates_per_strategy():
    rows = _observations(n=6, strategy_id="sA", r=0.5) + \
        _observations(n=4, strategy_id="sB", r=-0.2, regime="sideways/medium",
                      session="newyork")
    rep = research_learning(rows)
    assert rep["count"] == 10
    assert rep["expected_value"] == pytest.approx((6 * 0.5 + 4 * -0.2) / 10)
    by_id = {s["strategy_id"]: s for s in rep["strategies"]}
    assert set(by_id) == {"sA", "sB"}
    assert rep["by_regime_edge"]["bullish/normal"] == pytest.approx(0.5)
    assert "london" in rep["by_session_edge"]
    assert "strategy_lab observations" in rep["storage"]


def test_split_keeps_tracks_separate():
    rows = _observations(n=5)
    rep = split(records=[_record(), _record(pnl=-1.0)], observations=rows)
    assert rep["research"]["track"] == "research"
    assert rep["execution"]["track"] == "execution"
    assert rep["research"]["storage"] != rep["execution"]["storage"]
