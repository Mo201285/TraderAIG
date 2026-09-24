"""Higher-timeframe filter: family-specific treatment of suggestions."""
from schools.base import Suggestion
from schools.htf import HtfContextFilter
from core.contracts import (LiquidityState, MarketStructure, RegimeSnapshot,
                            TradingSession, TradeDirection, TrendDirection,
                            VolatilityRegime)


def htf(trend):
    return RegimeSnapshot(snapshot_id="H", timestamp=1.0, symbol="XAUUSD",
                          trend=TrendDirection(trend),
                          structure=MarketStructure.RANGING,
                          volatility=VolatilityRegime.NORMAL,
                          session=TradingSession.LONDON,
                          liquidity=LiquidityState.MEDIUM,
                          confidence=0.8)


def sugg(pattern, direction=TradeDirection.LONG):
    return Suggestion(school_id="structure", pattern=pattern,
                      direction=direction, entry_zone=[100.0, 101.0],
                      stop_loss=99.0, take_profit=[104.0], invalidation=99.0,
                      confidence=0.6, anchor="sw:9")


def test_continuation_against_htf_is_rejected():
    v = HtfContextFilter(htf("bearish")).apply(
        sugg("trend_continuation", TradeDirection.LONG))
    assert v["kind"] == "reject"
    assert v["align"] == "against"


def test_continuation_with_htf_passes():
    v = HtfContextFilter(htf("bullish")).apply(
        sugg("trend_continuation", TradeDirection.LONG))
    assert v["kind"] == "pass"
    assert v["align"] == "aligned"


def test_reversal_against_htf_is_dampened_not_killed():
    v = HtfContextFilter(htf("bullish")).apply(
        sugg("reversal_after_confirmed_shift", TradeDirection.SHORT))
    assert v["kind"] == "review"
    assert v["multiplier"] == 0.6


def test_sideways_htf_is_neutral_for_everything():
    v = HtfContextFilter(htf("sideways")).apply(
        sugg("trend_continuation", TradeDirection.LONG))
    assert v["kind"] == "pass"
    assert v["align"] == "neutral"
