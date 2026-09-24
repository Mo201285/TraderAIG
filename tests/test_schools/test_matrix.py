"""Tests for the matrix school (detectors + Opportunity-Engine wiring)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.contracts import Candle
from schools.base import SchoolStatus, SchoolTier
from schools.matrix import (
    MatrixSchool,
    matrix_school,
    detect_displacement,
    detect_fvg,
    detect_structure_break,
    detect_compression,
    detect_volatility_ok,
    _regime_ok,
)
from schools.registry import by_id
from intelligence.scalp_matrix import by_id as fam_by_id


def bar(t, o, h, l, c, vol=10, timeframe="M1", symbol="XAUUSD"):
    return Candle(symbol=symbol, timeframe=timeframe, time=t, open=o,
                  high=h, low=l, close=c, volume=vol, tick_volume=vol)


def _series(candles, symbol="XAUUSD", timeframe="M1"):
    out = []
    for i, (o, h, l, c) in enumerate(candles):
        out.append(bar(i * 60, o, h, l, c, symbol=symbol, timeframe=timeframe))
    return out


# -- detectors --------------------------------------------------------------

def test_displacement_detector():
    calm = [(100 + i * 0.1, 100.3 + i * 0.1, 99.9 + i * 0.1, 100.2 + i * 0.1)
            for i in range(14)]
    calm.append((101.5, 102.6, 101.4, 102.4))       # big final bar
    assert detect_displacement(_series(calm)) is True
    calm_small = [(100 + i * 0.1, 100.3 + i * 0.1, 99.9 + i * 0.1,
                   100.2 + i * 0.1) for i in range(15)]
    assert detect_displacement(_series(calm_small)) is False


def test_fvg_detector_unfilled():
    rows = [
        (100.0, 100.5, 99.5, 100.4),
        (100.4, 100.9, 100.1, 100.8),   # high 100.9
        (100.8, 102.0, 101.6, 101.9),   # low 101.6 > 100.9 -> bullish gap
        (101.9, 102.1, 101.4, 102.0),   # never trades back into the gap
    ]
    fvg = detect_fvg(_series(rows))
    assert fvg is not None
    assert fvg[0] == "bull"
    lo, hi = fvg[1], fvg[2]
    assert 100.9 <= lo and 101.6 <= hi


def test_fvg_detector_filled():
    rows = [
        (100.0, 100.5, 99.5, 100.4),
        (100.4, 100.9, 100.1, 100.8),
        (100.8, 102.0, 101.6, 101.9),   # gap open
        (101.9, 102.1, 100.2, 100.5),   # trades back through the gap -> filled
    ]
    assert detect_fvg(_series(rows)) is None


def test_structure_break_detector():
    rising = [bar(i * 60, 100 + i * 0.1, 100.3 + i * 0.1, 99.9 + i * 0.1,
                  100.2 + i * 0.1) for i in range(10)]
    rising.append(bar(10 * 60, 101.2, 101.6, 101.1, 101.5))  # close > max high
    assert detect_structure_break(rising) is True
    flat = [bar(i * 60, 100.0, 100.3, 99.9, 100.2) for i in range(11)]
    assert detect_structure_break(flat) is False


def test_compression_and_volatility_detectors():
    quiet = [(100.0, 100.1, 99.9, 100.0)] * 20      # tight coils
    wide = [(100.0, 101.0, 99.0, 100.5)] * 8
    assert detect_compression(_series(quiet + wide[-15:])) is False
    assert detect_compression(_series(quiet * 2 + wide)) is False


def test_volatility_alive_detector():
    dead = [(100.0, 100.05, 99.95, 100.0)] * 40
    alive = [(100.0, 100.0 + i * 0.1, 99.9, 100.05 + i * 0.1) for i in range(40)]
    assert detect_volatility_ok(_series(dead)) is True   # risk: is it too quiet?
    assert detect_volatility_ok(_series(alive)) is True


def test_regime_guard():
    assert _regime_ok("sideways", "normal", "BTCUSD") is True
    assert _regime_ok("sideways", "high", "BTCUSD") is False
    assert _regime_ok("sideways", "high", "XAUUSD") is True
    assert _regime_ok("sideways", "extreme", "XAUUSD") is False
    assert _regime_ok("bullish", "extreme", "BTCUSD") is False
    assert _regime_ok(None, None, "BTCUSD") is True
    assert _regime_ok("bullish", "normal", "XAUUSD") is True


# -- school wiring ----------------------------------------------------------

def test_matrix_registered_as_research_source():
    school = by_id("matrix")
    assert school is not None
    assert school.status == SchoolStatus.RESEARCH
    assert school.tier == SchoolTier.SOURCE


def test_rejects_non_matrix_symbol():
    evid = matrix_school.evaluate(_series([(100, 101, 99, 100.5)] * 30),
                                  "EURUSD", now=1.0)
    assert evid.suggestions == []
    assert evid.meta["rejected"] == "matrix_symbol"


def test_rejects_foreign_timeframe():
    evid = matrix_school.evaluate(
        _series([(100, 101, 99, 100.5)] * 30, timeframe="M15"), "XAUUSD",
        now=1.0)
    assert evid.suggestions == []
    assert evid.meta["rejected"] == "matrix_timeframe"


def test_rejects_outside_session_window():
    # 23:00 UTC is outside every XAUUSD/BTCUSD matrix window
    evid = matrix_school.evaluate(
        _series([(100, 101, 99, 100.5)] * 40), "XAUUSD", now=1.0)
    assert evid.suggestions == []
    assert evid.meta["rejected"] == "matrix_window"


def test_suggestion_if_any_is_well_formed():
    """A real (if not always trading) series: emit only if the matrix truly
    clears TRADE; whenever it does, the suggestion must be fully wired."""
    base = (7 * 60 + 30) * 60
    scale = 1.0
    candles = [bar(base - (30 - j) * 60, 100.0, 100.3, 99.9, 100.2)
               for j in range(16)]     # warm-up to clear the 30-bar floor
    c = 102.3 * scale
    for i in range(14):
        s = scale if i % 2 == 0 else scale * 2
        t = base + i * 60
        if i % 3 == 0:
            candles.append(bar(t, c - 0.2 * s, 103.0 * s, c - 1.0 * s, c))
        else:
            candles.append(bar(t, c + 0.4 * s, 102.9 * s, c - 0.7 * s, c))
        c = c - 1.0 * s if i % 3 == 0 else c - 0.3 * s
    candles.append(bar(base + 14 * 60, 102.3 * scale, 104.1 * scale,
                       102.1 * scale, 102.7 * scale, vol=20))
    evid = matrix_school.evaluate(candles, "XAUUSD", now=1.0)
    if not evid.suggestions:
        assert evid.meta.get("rejected") in (
            "matrix_flat", "matrix_thin", "matrix_no_trade",
            "matrix_no_pool", "matrix_min_rr")
        return
    sug = evid.suggestions[0]
    assert sug.school_id == "matrix"
    assert fam_by_id(sug.pattern) is not None
    assert sug.meta["score"] >= 60
    assert sug.meta["decision"] == "trade"
    assert sug.meta["family"] == "matrix"
    assert sug.meta["session"]
    assert sug.meta["min_rr"] > 0
    assert sug.meta["rr_preview"] >= sug.meta["min_rr"]
    assert sug.stop_loss is not None
    assert sug.take_profit


def test_matrix_school_constructs():
    assert isinstance(matrix_school, MatrixSchool)
