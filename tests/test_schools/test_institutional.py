"""Tests for the institutional-flow school and its board integration."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.contracts import Candle, RegimeSnapshot, TradeDirection, TrendDirection
from core.pipeline import _suggestion_rr
from core.state import CanonicalState, MarketState, state
from schools.institutional import institutional_school
from schools.registry import _schools, by_id


def bar(t, o, h, l, c, vol=10):
    return Candle(symbol="XAUUSD", timeframe="M15", time=t,
                  open=o, high=h, low=l, close=c,
                  volume=float(vol), tick_volume=float(vol))


def _sellside_series():
    candles = []
    c = 101.2
    for i in range(14):
        if i % 2 == 0:
            candles.append(bar(i, c + 0.4, c + 0.7, 100.0, c - 0.6))
        else:
            candles.append(bar(i, c - 0.6, 102.0, 100.2, c + 0.4))
        c = candles[-1].close
    candles.append(bar(14.0, 100.4, 100.6, 99.1, 100.35, vol=1000))
    return candles


def _buyside_series():
    candles = []
    c = 102.3
    for i in range(14):
        if i % 2 == 0:
            candles.append(bar(i, c - 0.2, 103.0, c - 1.0, c + 0.4))
        else:
            candles.append(bar(i, c + 0.4, 102.9, c - 0.7, c - 0.4))
        c = candles[-1].close
    candles.append(bar(14.0, 102.3, 104.1, 102.1, 102.7, vol=20))
    return candles


def _regime(trend=TrendDirection.BULLISH):
    return RegimeSnapshot(snapshot_id="R", timestamp=1.0, symbol="XAUUSD",
                          trend=trend, structure="impulse", volatility="low",
                          liquidity="low", session="london", confidence=0.7)


def test_institutional_school_is_registered_source():
    assert by_id("institutional") is institutional_school
    assert institutional_school.tier.value == "source"
    assert "institutional" in [s.school_id for s in _schools]


def _fresh_state():
    state.__dict__.clear()
    state.__dict__.update(CanonicalState().__dict__)


def test_institutional_school_emits_absorption_long():
    _fresh_state()
    evid = institutional_school.evaluate(_sellside_series(), "XAUUSD",
                                         now=1.0)
    assert evid.bias == TradeDirection.LONG
    assert len(evid.suggestions) == 1
    sug = evid.suggestions[0]
    assert sug.school_id == "institutional"
    assert sug.pattern == "absorption"
    assert sug.direction == TradeDirection.LONG
    assert sug.stop_loss < _sellside_series()[-1].low
    assert sug.take_profit[0] > 100.35
    assert sug.anchor.startswith("raid:")
    assert sug.meta["lesson_key"] == "raid:absorption"
    assert sug.confidence > 0.3


def test_institutional_school_stays_flat_without_footprint():
    _fresh_state()
    candles = _sellside_series()
    candles[-1] = bar(14.0, 100.4, 100.6, 99.8, 99.4, vol=1000)  # no recover
    evid = institutional_school.evaluate(candles, "XAUUSD", now=1.0)
    assert evid.bias == TradeDirection.FLAT
    assert evid.suggestions == []


def test_institutional_school_uses_live_tick_when_available():
    _fresh_state()
    state.upsert_market(MarketState(symbol="XAUUSD", bid=100.55, ask=100.60,
                                    spread=0.05, last_price=100.55,
                                    last_tick_time=1.0))
    evid = institutional_school.evaluate(_sellside_series(), "XAUUSD", now=1.0)
    assert evid.suggestions[0].meta["live"] is True


def test_target_clears_the_min_rr_gate_long():
    _fresh_state()
    candles = _sellside_series()
    evid = institutional_school.evaluate(candles, "XAUUSD", now=1.0)
    sug = evid.suggestions[0]
    assert _suggestion_rr(sug, candles[-1].close) >= 1.2


def test_take_profit_ladder_is_ascending_long():
    _fresh_state()
    candles = _sellside_series()
    evid = institutional_school.evaluate(candles, "XAUUSD", now=1.0)
    sug = evid.suggestions[0]
    tps = sug.take_profit
    assert 1 <= len(tps) <= 3
    assert tps == sorted(tps)                       # TP1 nearest -> farthest
    assert tps[0] > 100.35
    assert sug.meta["ladder"]                       # carries the level breakdown
    assert {l["source"] for l in sug.meta["ladder"]} & {"liquidity_pool"}


def test_take_profit_ladder_descends_for_short():
    _fresh_state()
    candles = _buyside_series()
    evid = institutional_school.evaluate(candles, "XAUUSD", now=1.0)
    sug = evid.suggestions[0]
    tps = sug.take_profit
    assert 1 <= len(tps) <= 3
    assert tps == sorted(tps, reverse=True)
    assert all(t < 102.7 for t in tps)
    assert sug.meta["ladder"]


def test_target_clears_the_min_rr_gate_short():
    _fresh_state()
    candles = _buyside_series()
    evid = institutional_school.evaluate(candles, "XAUUSD", now=1.0)
    assert evid.bias == TradeDirection.SHORT
    sug = evid.suggestions[0]
    assert _suggestion_rr(sug, candles[-1].close) >= 1.2


def test_htf_dampens_institutional_raid_against_trend():
    from schools.base import Suggestion
    from schools.htf import HtfContextFilter

    htf = HtfContextFilter(_regime(trend=TrendDirection.BEARISH))
    raid = Suggestion(school_id="institutional", pattern="sellside_raid",
                      direction=TradeDirection.LONG, entry_zone=[100, 101],
                      stop_loss=99.0, take_profit=[102.0], invalidation=99.0,
                      confidence=0.5)
    v = htf.apply(raid)
    assert v["kind"] == "review"
    assert v["align"] == "against"
    assert v["multiplier"] == 0.6


def test_htf_pass_when_institutional_raid_aligned():
    from schools.base import Suggestion
    from schools.htf import HtfContextFilter

    htf = HtfContextFilter(_regime(trend=TrendDirection.BULLISH))
    raid = Suggestion(school_id="institutional", pattern="buy_side_raid",
                      direction=TradeDirection.SHORT, entry_zone=[103, 102.7],
                      stop_loss=104.2, take_profit=[101.5], invalidation=104.2,
                      confidence=0.5)
    v = htf.apply(raid)
    # buy-side raid (short) against a bull HTF: dampened, not killed
    assert v["kind"] == "review"
    assert v["multiplier"] == 0.6
