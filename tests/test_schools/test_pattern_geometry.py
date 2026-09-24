"""Pattern Geometry school tests."""

from schools.pattern_geometry import pattern_geometry_school
from schools.registry import by_id
from core.contracts import TradeDirection

from .conftest import mk
from .test_price_action import live_zone


def _bull_flag_series():
    out = []
    price = 100.0
    for i in range(8):
        o = price
        c = o + 1.2
        out.append(mk(o, c + 0.4, o - 0.2, c, t=500000 + i * 900, i=i))
        price = c
    for i in range(8, 20):
        o = price
        c = o - 0.25
        out.append(mk(o, o + 0.15, c - 0.15, c, t=500000 + i * 900, i=i))
        price = c
    return out


def _ascending_triangle_series():
    vals = [
        (100.0, 103.0, 99.5, 102.0),
        (102.0, 103.1, 100.4, 102.2),
        (102.1, 103.05, 100.9, 102.4),
        (102.3, 103.02, 101.4, 102.6),
        (102.5, 103.0, 101.8, 102.7),
        (102.6, 103.03, 102.1, 102.8),
        (102.7, 103.04, 102.3, 102.9),
        (102.8, 103.01, 102.5, 102.95),
        (102.9, 103.0, 102.6, 102.98),
        (102.95, 103.02, 102.7, 103.0),
        (102.98, 103.01, 102.8, 103.0),
        (102.99, 103.0, 102.86, 103.0),
    ]
    return [mk(o, h, l, c, t=600000 + i * 900, i=i) for i, (o, h, l, c) in enumerate(vals)]


def _double_top_series():
    vals = [
        (100, 101, 99.5, 100.7),
        (100.7, 102.5, 100.4, 102.2),
        (102.2, 104.2, 101.8, 103.9),
        (103.9, 105.0, 103.4, 104.6),
        (104.5, 103.8, 102.9, 103.1),
        (103.1, 104.4, 102.8, 104.0),
        (104.0, 104.95, 103.6, 104.5),
        (104.5, 104.8, 102.7, 103.0),
        (103.0, 103.2, 101.5, 101.9),
        (101.9, 102.0, 101.0, 101.4),
        (101.4, 101.5, 100.9, 101.1),
        (101.1, 101.3, 100.6, 100.8),
    ]
    return [mk(o, h, l, c, t=700000 + i * 900, i=i) for i, (o, h, l, c) in enumerate(vals)]


def test_pattern_geometry_school_is_registered_confirmation():
    assert by_id("pattern_geometry") is pattern_geometry_school
    assert pattern_geometry_school.tier.value == "confirmation"


def test_bull_flag_confirms_long_near_zone():
    candles = _bull_flag_series()
    ev = pattern_geometry_school.evaluate(candles, "XAUUSD",
                                          zones_from_others=[live_zone(candles[-1].close - 0.5,
                                                                       candles[-1].close + 0.5)],
                                          now=1.0)
    names = [s.name for s in ev.signals]
    assert "bull_flag" in names
    assert any(s.direction == TradeDirection.LONG for s in ev.signals)


def test_ascending_triangle_confirms_long():
    ev = pattern_geometry_school.evaluate(_ascending_triangle_series(), "XAUUSD", now=1.0)
    assert "ascending_triangle" in ev.meta["patterns"]
    assert any(s.direction == TradeDirection.LONG for s in ev.signals)


def test_double_top_confirms_short():
    ev = pattern_geometry_school.evaluate(_double_top_series(), "XAUUSD", now=1.0)
    assert "double_top" in ev.meta["patterns"]
    assert any(s.direction == TradeDirection.SHORT for s in ev.signals)
