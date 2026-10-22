"""M8.4: research vs execution learning split tests
(learning/learning_split.py)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from learning.experience import ExperienceRecord
from learning.learning_split import (
    attributed_to_account,
    execution_learning,
    research_learning,
    split,
)
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


def _real_record(pnl=4.0):
    return ExperienceRecord(
        record_id=f"mt5:{pnl}",
        decision_id="deal",
        timestamp=0.0,
        actual_result={"filled": True, "pnl": pnl, "origin": "system",
                       "source": "mt5"},
    )


def test_execution_learning_source_filter_keeps_only_the_real_rail():
    """Paper fills have no `source`; they must not pass as live execution."""
    real = _real_record(pnl=4.0)
    paper = _record(pnl=99.0)

    both = execution_learning([real, paper])
    assert both["count"] == 2
    assert both["source_filter"] is None
    assert "paper and live" in both["basis"]

    only_real = execution_learning([real, paper], source="mt5")
    assert only_real["count"] == 1
    assert only_real["net_pnl"] == 4.0
    assert only_real["source_filter"] == "mt5"
    assert "mt5" in only_real["basis"]


def test_execution_learning_tolerates_an_unknown_pnl():
    """`mt5o:` fallback rows carry pnl None (profit unknown), not a number."""
    record = _record()
    record.actual_result["pnl"] = None
    rep = execution_learning([record])
    assert rep["count"] == 1
    assert rep["net_pnl"] == 0.0


def test_attribution_keeps_only_rows_stamped_with_the_connected_account():
    """The ledger outlives a session; another account's rows are not ours."""
    mine = _real_record()
    mine.metadata = {"account": "TEST-ACCT-1"}
    theirs = _real_record(pnl=9.0)
    theirs.record_id = "mt5:theirs"
    theirs.metadata = {"account": "TEST-ACCT-2"}
    legacy = _real_record(pnl=7.0)
    legacy.record_id = "mt5:legacy"
    legacy.metadata = {}

    rows = attributed_to_account([mine, theirs, legacy], "TEST-ACCT-1")
    assert [r.record_id for r in rows] == [mine.record_id]


def test_attribution_is_a_no_op_without_a_connected_account():
    rows = [_real_record(), _record()]
    assert attributed_to_account(rows, 0) == rows
    assert attributed_to_account(rows, "") == rows


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
