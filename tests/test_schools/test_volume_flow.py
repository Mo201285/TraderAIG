"""Volume / Order Flow school: availability gating and absorption."""
from schools.volume_flow import volume_flow_school
from core.contracts import TradeDirection

from .conftest import mk
from .test_price_action import live_zone


def test_disabled_when_no_volume_data():
    candles = [mk(100, 101, 99, 100.5, volume=0.0, tick_volume=0)
               for _ in range(20)]
    ev = volume_flow_school.evaluate(candles, "XAUUSD", now=1.0)
    assert ev.data_available is False
    assert ev.verdict is not None and ev.verdict.kind.value == "disabled"


def test_active_with_tick_volume():
    candles = [mk(100, 101, 99, 100.5) for _ in range(20)]
    ev = volume_flow_school.evaluate(candles, "XAUUSD", now=1.0)
    assert ev.data_available is True
    assert ev.meta.get("data_source") == "tick"


def test_absorption_at_key_zone():
    # heavy volume + a tiny range right on an entry zone -> absorption
    candles = [mk(100, 101.5, 99.5, 100.6) for _ in range(10)]
    candles += [mk(100.6, 100.7, 100.55, 100.62, volume=900.0,
                   tick_volume=90)]            # absorption candle
    zone = live_zone(100.6)
    ev = volume_flow_school.evaluate(candles, "XAUUSD",
                                     zones_from_others=[zone], now=1.0)
    names = [s.name for s in ev.signals]
    assert "absorption" in names
    # the school never produces a standalone entry suggestion
    assert ev.suggestions == []


def test_volume_breakout_confirms_direction():
    # a wide candle closes above an entry zone with heavy volume -> LONG
    candles = [mk(100, 101.5, 99.5, 100.6) for _ in range(10)]
    candles += [mk(103.2, 106.2, 102.6, 105.7, volume=250.0, tick_volume=250)]
    zone = live_zone(104.5)
    ev = volume_flow_school.evaluate(candles, "XAUUSD",
                                     zones_from_others=[zone], now=1.0)
    sigs = [s for s in ev.signals if s.name == "volume_breakout"]
    assert sigs, "a heavy-volume breakout must be confirmed"
    assert all(s.direction == TradeDirection.LONG for s in sigs)
    assert all(s.pattern == "volume_breakout" for s in sigs)
    assert ev.bias == TradeDirection.LONG


def test_vacuum_warning_on_low_volume_break():
    # same geometry but near-zero participation -> trap, never a confirmation
    candles = [mk(100, 101.5, 99.5, 100.6) for _ in range(10)]
    candles += [mk(103.2, 106.2, 102.6, 105.7, volume=5.0, tick_volume=1)]
    zone = live_zone(104.5)
    ev = volume_flow_school.evaluate(candles, "XAUUSD",
                                     zones_from_others=[zone], now=1.0)
    names = [s.name for s in ev.signals]
    assert "volume_breakout" not in names
    assert "vacuum_warning" in names
    vac = [s for s in ev.signals if s.name == "vacuum_warning"]
    assert all(s.direction == TradeDirection.FLAT for s in vac)
