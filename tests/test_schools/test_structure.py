"""Market Structure school: trend/bias and structural invalidation."""
from schools.structure import structure_school
from schools import structure
from core.contracts import TradeDirection

from .conftest import bos_breakout, deep_pushdown, mk, swing_path


def test_pullback_in_uptrend_offers_long_continuation():
    candles = swing_path()
    ev = structure_school.evaluate(candles, "XAUUSD", now=1.0)

    assert ev.bias == TradeDirection.LONG
    assert ev.suggestions, "a pullback into the protected higher-low must propose"
    assert all(s.direction == TradeDirection.LONG for s in ev.suggestions)
    assert any(s.pattern == "trend_continuation" for s in ev.suggestions)
    # invalidation anchor always below the protected low, never above
    for s in ev.suggestions:
        assert s.stop_loss < candles[-1].close


def test_bos_requires_close_confirmation():
    candles = bos_breakout()
    ev = structure_school.evaluate(candles, "XAUUSD", now=1.0)
    assert ev.signals, "break above the last high must confirm a BOS by close"
    assert ev.meta.get("bos_confirmed") is True
    assert any(s.pattern == "structure_breakout" for s in ev.suggestions)


def test_choch_reversal_after_shift():
    candles = deep_pushdown()
    ev = structure_school.evaluate(candles, "XAUUSD", now=1.0)
    assert ev.meta.get("choch_confirmed") is True
    assert any(s.pattern == "reversal_after_confirmed_shift"
               and s.direction == TradeDirection.SHORT
               for s in ev.suggestions)


def test_structural_invalidation_side():
    candles = swing_path()
    ev = structure_school.evaluate(candles, "XAUUSD", now=1.0)
    pl = ev.meta.get("protected_low")
    assert pl is not None
    # protected low sits between the base and the newest higher-low
    assert 100.0 <= pl <= 104.6


def test_flat_when_no_structure():
    candles = [mk(100 + i * 0.01, 100.05, 99.95, 100.01 + i * 0.005 * (i % 2))
               for i in range(20)]
    ev = structure_school.evaluate(candles, "XAUUSD", now=1.0)
    assert ev.suggestions == []


def test_swing_scanner_types():
    candles = swing_path()
    swings = structure._find_swings(candles)
    assert swings
    assert all(s.kind in ("high", "low") for s in swings)
    highs = [s.price for s in swings if s.kind == "high"]
    lows = [s.price for s in swings if s.kind == "low"]
    assert len(highs) >= 2 and len(lows) >= 2
    assert highs[-1] > highs[-2] and lows[-1] > lows[-2]
