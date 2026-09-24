"""Strategy Registry promotion state machine tests (spec 7.6)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import tempfile
import os

from research.strategy_lab.contracts import (
    ExitReason,
    OosSplit,
    PromotionStage,
    SpreadBucket,
    StrategyFamily,
    TradeObservation,
    VolatilityBucket,
)
from research.strategy_lab.registry import StrategyRegistry
from research.strategy_lab.validation import ValidationLab


def _passing_report(strategy_id="s1"):
    def _r(i):
        return -0.5 if i % 5 == 4 else 0.7
    obs = [
        TradeObservation(
            experiment_id="e", strategy_id=strategy_id,
            family=StrategyFamily.OB_MITIGATION, variant_hash="h",
            asset="XAUUSD", htf_tf="H1", setup_tf="M15", trigger_tf="M1",
            session="london", weekday=2, regime="bullish/normal",
            volatility_bucket=VolatilityBucket.MEDIUM,
            spread_bucket=SpreadBucket.NORMAL,
            entry_type="matrix_pool", sl_model="lt", tp_model="zt",
            pattern_geometry="", macro_state="",
            mfe_r=1.0, mae_r=-0.5,
            exit_reason=ExitReason.TARGET if _r(i) > 0 else ExitReason.STOP,
            oos_split=OosSplit.OUT_OF_SAMPLE if i >= 30 else OosSplit.IN_SAMPLE,
            walkforward_window=i % 2,
            pnl=_r(i), r_multiple=_r(i))
        for i in range(40)
    ]
    return ValidationLab().evaluate(strategy_id, "XAUUSD", obs)


def test_registry_register_and_validate_stage():
    reg = StrategyRegistry()
    reg.register("s1", "h", StrategyFamily.OB_MITIGATION, "XAUUSD")
    assert reg.get("s1").stage is PromotionStage.RESEARCH


def test_promote_requires_passing_report_at_validated():
    reg = StrategyRegistry()
    reg.register("s1", "h", StrategyFamily.OB_MITIGATION, "XAUUSD")
    assert reg.promote("s1")                       # -> CANDIDATE
    assert reg.get("s1").stage is PromotionStage.CANDIDATE
    assert not reg.promote("s1", validation=None)  # no report -> blocked
    assert reg.get("s1").stage is PromotionStage.CANDIDATE
    assert reg.promote("s1", validation=_passing_report())  # -> VALIDATED
    assert reg.get("s1").stage is PromotionStage.VALIDATED


def test_full_promotion_ladder():
    reg = StrategyRegistry()
    reg.register("s1", "h", StrategyFamily.OB_MITIGATION, "XAUUSD")
    report = _passing_report("s1")
    assert reg.promote("s1")                          # CANDIDATE
    assert reg.promote("s1", validation=report)      # VALIDATED
    assert reg.promote("s1")                          # PAPER
    assert reg.promote("s1")                          # PRODUCTION
    assert reg.get("s1").stage is PromotionStage.PRODUCTION
    assert not reg.promote("s1")                      # terminal


def test_demote_to_quarantine_sink_and_terminal():
    reg = StrategyRegistry()
    reg.register("s1", "h", StrategyFamily.OB_MITIGATION, "XAUUSD")
    reg.promote("s1")
    assert reg.demote("s1", "oos_ev_negative")
    assert reg.get("s1").stage is PromotionStage.QUARANTINED
    assert not reg.promote("s1")
    assert not reg.demote("s1", "again")


def test_registry_persistence_roundtrip():
    tmp = os.path.join(tempfile.mkdtemp(), "registry.json")
    reg = StrategyRegistry(tmp)
    reg.register("s1", "h", StrategyFamily.OB_MITIGATION, "XAUUSD")
    reg.promote("s1")
    reg.promote("s1", validation=_passing_report("s1"))

    reg2 = StrategyRegistry()
    loaded = reg2.load(tmp)
    assert loaded == 1
    assert reg2.get("s1").stage is PromotionStage.VALIDATED
    assert reg2.get("s1").validation.samples == 40


def test_registry_knows_its_entries():
    reg = StrategyRegistry()
    reg.register("a", "h1", StrategyFamily.OB_MITIGATION, "XAUUSD")
    reg.register("b", "h2", StrategyFamily.ICT_FVG_CONTINUATION, "BTCUSD")
    assert len(reg.list()) == 2
    assert len(reg.list(stage=PromotionStage.RESEARCH)) == 2
    reg.promote("a")
    assert len(reg.list(stage=PromotionStage.RESEARCH)) == 1


def test_attach_validation():
    reg = StrategyRegistry()
    reg.register("s1", "h", StrategyFamily.OB_MITIGATION, "XAUUSD")
    assert reg.attach_validation("s1", _passing_report("s1"))
    assert reg.get("s1").validation.samples == 40
