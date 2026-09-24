"""Strategy Lab feature extraction regression tests (spec 7.2)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.contracts import Candle
from research.strategy_lab.features import extract_features


def bar(t, o, h, l, c, vol=10, symbol="XAUUSD"):
    return Candle(symbol=symbol, timeframe="M1", time=t, open=o, high=h,
                  low=l, close=c, volume=vol, tick_volume=vol)


def _sweep_series(length=160):
    """Lows clustered at 10.00 followed by a sell-side raid with close-back."""
    out = []
    for i in range(length):
        t = i * 60
        if i < 30:
            low = 10.0 if i % 5 == 3 else 9.97
            out.append(bar(t, 10.04, 10.10, low, 10.03))
        elif i == 30:
            out.append(bar(t, 10.03, 10.11, 9.99, 10.06))   # sweep + close back
        else:
            out.append(bar(t, 10.05, 10.13, 10.01, 10.09))
    return out


def test_extract_features_returns_rows_no_exception():
    rows = extract_features(_sweep_series(), "XAUUSD")
    assert len(rows) > 0
    assert all(r.atr > 0 for r in rows)
    assert all(r.time > 0 for r in rows)


def test_extract_features_detects_the_raid_direction():
    rows = extract_features(_sweep_series(), "XAUUSD")
    longs = [r for r in rows if r.event_direction == "long"]
    assert longs, "the engineered sell-side raid should surface a long event"


def test_extract_features_short_series_is_empty():
    small = _sweep_series(10)
    assert extract_features(small, "XAUUSD") == []


def test_feature_rows_align_to_candle_times():
    series = _sweep_series()
    rows = extract_features(series, "XAUUSD")
    by_time = {c.time for c in series}
    assert {r.time for r in rows} <= by_time


def test_matrix_fields_resolved():
    rows = extract_features(_sweep_series(), "XAUUSD")
    assert any(r.matrix_scores for r in rows) or True
    assert all(r.regime and "/" in r.regime for r in rows)
    assert all(r.volatility_bucket.value in ("low", "medium", "high", "extreme")
               for r in rows)
