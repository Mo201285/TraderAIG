"""Negative tests for noisy Pattern Geometry detections."""

from schools.pattern_geometry import pattern_geometry_school

from .conftest import deep_pushdown


def test_deep_pushdown_is_not_misread_as_bull_flag():
    ev = pattern_geometry_school.evaluate(deep_pushdown(), "XAUUSD", now=1.0)
    assert "bull_flag" not in ev.meta["patterns"]
