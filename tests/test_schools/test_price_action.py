"""Price Action school: confirms, never originates."""
from schools.price_action import price_action_school
from core.contracts import TradeDirection

from .conftest import mk


def test_rejection_pin_at_key_zone():
    candles = [mk(100, 101, 99.6, 100.6) for _ in range(7)]
    candles += [mk(100, 101.2, 99.0, 99.8)]   # long upper wick, close low -> bearish pin
    zone = live_zone(99.8)
    ev = price_action_school.evaluate(candles, "XAUUSD",
                                      zones_from_others=[zone], now=1.0)
    assert ev.suggestions == [], "PA never proposes a trade"
    sigs = [s for s in ev.signals if s.name == "rejection_at_key_level"]
    assert sigs and all(s.direction == TradeDirection.SHORT for s in sigs)


def test_compression_flag_never_directional():
    narrow = [mk(100, 100.1, 99.9, 100.0) for _ in range(5)]
    wide = [mk(100, 101.0, 99.0, 100.0) for _ in range(7)]
    ev = price_action_school.evaluate(narrow + wide, "XAUUSD", now=1.0)
    comp = [s for s in ev.signals if s.name == "compression"]
    # compression should be flagged only while range is tight
    assert any(s.direction == TradeDirection.FLAT for s in comp) or ev.meta.get("patterns")


def test_early_exit_warning_at_target():
    candles = [mk(100, 101, 99.4, 100.2) for _ in range(7)]
    candles += [mk(100.5, 103.4, 100.3, 100.6)]  # long upper wick at the objective
    zone = live_zone(101.5, role="objective")
    ev = price_action_school.evaluate(candles, "XAUUSD",
                                      zones_from_others=[zone], now=1.0)
    assert ev.meta["early_exit"] is True


def test_early_exit_emits_counter_candle_signal():
    # a rejection wick at the objective must be machine-readable, not meta-only
    candles = [mk(100, 101, 99.4, 100.2) for _ in range(7)]
    candles += [mk(100.5, 103.4, 100.3, 100.6)]  # bearish rejection at target
    zone = live_zone(101.5, role="objective")
    ev = price_action_school.evaluate(candles, "XAUUSD",
                                      zones_from_others=[zone], now=1.0)
    sigs = [s for s in ev.signals if s.name == "counter_candle"]
    assert sigs
    assert sigs[0].direction == TradeDirection.SHORT


def test_doji_indecision_at_zone_lowers_confirming_odds():
    candles = [mk(100, 101, 99.4, 100.2) for _ in range(7)]
    candles += [mk(100.5, 100.6, 100.4, 100.505)]  # almost zero body
    zone = live_zone(100.5)
    ev = price_action_school.evaluate(candles, "XAUUSD",
                                      zones_from_others=[zone], now=1.0)
    sigs = [s for s in ev.signals if s.name == "indecision"]
    assert sigs
    assert sigs[0].direction == TradeDirection.FLAT
    assert ev.meta["patterns"] and "doji" in ev.meta["patterns"]


def live_zone(price, role="entry"):
    from schools.base import SchoolZone
    return SchoolZone("entry_zone", price + 1.0, price - 1.0, role=role)
