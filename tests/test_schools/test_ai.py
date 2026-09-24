"""AI Intelligence school: regime advice + correlation/conflict metadata only."""
from schools.ai import ai_school, correlated
from schools.base import SchoolSignal
from core.contracts import (LiquidityState, MarketStructure,
                            RegimeSnapshot, TradingSession, TradeDirection,
                            TrendDirection, VolatilityRegime)

from .conftest import mk


def regime(conf=0.7, structure="ranging", volatility="low", trend="bullish"):
    return RegimeSnapshot(
        snapshot_id="R1", timestamp=1.0, symbol="XAUUSD",
        trend=TrendDirection(trend), structure=MarketStructure(structure),
        volatility=VolatilityRegime(volatility),
        session=TradingSession.NEW_YORK, liquidity=LiquidityState.MEDIUM,
        confidence=conf)


def test_ai_never_votes_but_advises():
    ev = ai_school.evaluate([mk(100, 101, 99, 100.5)], "XAUUSD",
                            regime=regime(), now=1.0)
    assert ev.suggestions == []
    assert ev.meta["model_uncertainty"] == 0.3
    assert "wyckoff" in ev.meta["recommended_schools"]
    assert "volume_flow" in ev.meta["recommended_schools"]


def test_unknown_regime_reports_high_uncertainty():
    ev = ai_school.evaluate([mk(100, 101, 99, 100.5)], "XAUUSD", now=1.0)
    assert ev.meta["model_uncertainty"] >= 0.5


def test_correlated_by_shared_anchor():
    a = _sugg(anchor="sw:3", sl=100.0)
    b = _sugg(anchor="sw:3", sl=100.1)
    assert correlated(a, b)


def test_conflicts_flags_direction_clash_and_correlation():
    sigs = [
        SchoolSignal(name="structure_trend", direction=TradeDirection.LONG,
                     strength=0.6, anchor="sw:3", pattern="trend_continuation"),
        SchoolSignal(name="sweep_confirm", direction=TradeDirection.SHORT,
                     strength=0.6, anchor="sw:3", pattern="sweep_reversal"),
    ]
    out = ai_school.conflicts(sigs)
    kinds = {c["type"] for c in out}
    assert "direction_conflict" in kinds
    assert "correlated_evidence" in kinds


def test_rank_prefers_stronger_evidence():
    ranked = ai_school.rank([
        _sugg(anchor="a", conf=0.4),
        _sugg(anchor="b", conf=0.8),
    ])
    assert ranked[0].anchor == "b"


def test_low_regime_confidence_flags_anomaly():
    ev = ai_school.evaluate([mk(100, 101, 99, 100.5)], "XAUUSD",
                            regime=regime(conf=0.2), now=1.0)
    assert ev.verdict is not None
    assert ev.verdict.meta["anomaly"] is True


def test_ranks_across_instruments_in_one_list():
    from schools.base import SchoolEvidence, SchoolTier
    s1 = _sugg(anchor="a", conf=0.4)
    s2 = _sugg(anchor="b", conf=0.9)
    s3 = _sugg(anchor="c", conf=0.7)
    evs = [
        SchoolEvidence(school_id="structure", tier=SchoolTier.SOURCE,
                       symbol="XAUUSD", timestamp=1.0, suggestions=[s1]),
        SchoolEvidence(school_id="structure", tier=SchoolTier.SOURCE,
                       symbol="EURUSD", timestamp=1.0, suggestions=[s2, s3]),
    ]
    ranked = ai_school.rank_across_instruments(evs)
    assert [r["symbol"] for r in ranked] == ["EURUSD", "EURUSD", "XAUUSD"]
    assert [r["anchor"] for r in ranked] == ["b", "c", "a"]


def _sugg(anchor, sl=100.0, conf=0.6):
    from schools.base import Suggestion
    return Suggestion(school_id="structure", pattern="structure_breakout",
                      direction=TradeDirection.LONG, entry_zone=[100.0, 101.0],
                      stop_loss=sl, take_profit=[105.0], invalidation=sl,
                      confidence=conf, anchor=anchor)
