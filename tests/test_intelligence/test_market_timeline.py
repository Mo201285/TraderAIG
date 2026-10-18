"""Unit tests for the market timeline (intelligence/market_timeline.py).

The timeline is the chart's read-only narrative: it must be deterministic, must
order events chronologically, and must stay honestly silent when the window is
too short to say anything.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.contracts import Candle
from intelligence.market_timeline import (
    _atr_series,
    build_timeline,
)

_ORDER = {"sweep": 0, "displacement": 1, "fvg": 2, "retrace": 3}


def _candle(time: int, o: float, h: float, l: float, c: float) -> Candle:
    return Candle(symbol="TEST", timeframe="M5", time=float(time),
                  open=o, high=h, low=l, close=c, volume=1.0, tick_volume=1.0)


def _range(n: int, base: float = 2000.0) -> list[Candle]:
    """A quiet, tight, gap-free range — no sweeps, no displacement, no gaps."""
    out = []
    for i in range(n):
        o = base + (i % 2) * 0.02
        out.append(_candle(i, o, o + 0.05, o - 0.05, o + 0.01))
    return out


# --- ATR -------------------------------------------------------------------


def test_atr_series_warmup_then_value():
    candles = _range(30)
    atr = _atr_series(candles, period=14)
    assert len(atr) == 30
    assert atr[0] is None
    assert atr[12] is None
    assert atr[13] is not None
    assert atr[-1] is not None
    assert atr[-1] > 0


# --- shape / safety --------------------------------------------------------


def test_empty_and_short_windows_are_silent():
    assert build_timeline([], "TEST", "M5") == []
    assert build_timeline(_range(4), "TEST", "M5") == []


def test_quiet_range_produces_nothing_structural():
    # No wicks beyond the range, no large candles, no gaps -> no events.
    assert build_timeline(_range(60), "TEST", "M5") == []


def test_event_shape_and_bilingual_text():
    candles = _range(40)
    candles.append(_candle(41, 2000.0, 2003.5, 1999.8, 2000.0))   # sweep high
    tl = build_timeline(candles, "TEST", "M5")
    assert tl, "expected at least one event"
    for e in tl:
        assert set(e) >= {"id", "type", "side", "time", "price", "index",
                          "text_en", "text_ar"}
        assert e["type"] in _ORDER
        assert e["side"] in {"buy", "sell", "neutral"}
        assert e["text_en"] and e["text_ar"]
        assert "_zone" not in e  # internal key must never leak


# --- individual detectors --------------------------------------------------


def test_sweep_high_emits_sell_sweep():
    candles = _range(40)
    candles.append(_candle(41, 2000.0, 2003.5, 1999.97, 2000.0))
    tl = build_timeline(candles, "TEST", "M5")
    sweeps = [e for e in tl if e["type"] == "sweep"]
    assert len(sweeps) == 1
    assert sweeps[0]["side"] == "sell"
    assert sweeps[0]["index"] == len(candles) - 1


def test_sweep_low_emits_buy_sweep():
    candles = _range(40)
    candles.append(_candle(41, 2000.0, 2000.05, 1996.5, 2000.0))
    tl = build_timeline(candles, "TEST", "M5")
    sweeps = [e for e in tl if e["type"] == "sweep"]
    assert len(sweeps) == 1
    assert sweeps[0]["side"] == "buy"


def test_displacement_detected_on_impulse():
    candles = _range(40)
    candles.append(_candle(41, 2000.0, 2004.5, 1999.9, 2004.3))
    tl = build_timeline(candles, "TEST", "M5")
    disp = [e for e in tl if e["type"] == "displacement"]
    assert len(disp) == 1
    assert disp[0]["side"] == "buy"


def test_fvg_then_retrace_ordered():
    candles = _range(40)
    # bullish FVG: candle43.low > candle42.high, then a bar retraces into it.
    candles.append(_candle(41, 2000.0, 2000.6, 1999.9, 2000.5))
    candles.append(_candle(42, 2000.5, 2002.0, 2000.4, 2001.9))
    candles.append(_candle(43, 2002.1, 2003.5, 2002.1, 2003.4))   # gap 2002.0-2002.1
    candles.append(_candle(44, 2003.3, 2003.4, 2002.05, 2002.4))  # retrace into gap
    tl = build_timeline(candles, "TEST", "M5")
    types = [e["type"] for e in tl]
    assert "fvg" in types
    assert "retrace" in types
    assert types.index("fvg") < types.index("retrace")


# --- ordering / determinism ------------------------------------------------


def test_events_are_chronological():
    candles = _range(60)
    candles.append(_candle(61, 2000.0, 2003.0, 1999.5, 2000.0))   # sweep
    candles.append(_candle(62, 2000.5, 2002.0, 2000.4, 2001.9))   # impulse
    candles.append(_candle(63, 2002.1, 2003.5, 2002.1, 2003.4))   # fvg
    candles.append(_candle(64, 2003.3, 2003.4, 2002.05, 2002.4))  # retrace
    tl = build_timeline(candles, "TEST", "M5")
    times = [e["time"] for e in tl]
    assert times == sorted(times)
    # ties read in structural order: sweep before displacement before fvg
    for a, b in zip(tl, tl[1:]):
        if a["time"] == b["time"]:
            assert _ORDER[a["type"]] <= _ORDER[b["type"]]


def test_deterministic():
    candles = _range(50)
    candles.append(_candle(51, 2000.0, 2004.5, 1999.8, 2004.3))
    assert build_timeline(candles, "TEST", "M5") == \
        build_timeline(candles, "TEST", "M5")


def test_max_events_trims_to_most_recent():
    candles = _range(120)
    for i in range(120, 140):
        candles.append(_candle(i, 2000.0, 2004.5, 1999.8, 2004.3))
    full = build_timeline(candles, "TEST", "M5", max_events=1000)
    trimmed = build_timeline(candles, "TEST", "M5", max_events=5)
    assert len(trimmed) <= 5
    assert trimmed == full[-len(trimmed):]
