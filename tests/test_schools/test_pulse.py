"""Tests for the experimental Pulse school (RESEARCH tier, backtest-only).
Purpose-built for XAUUSD (gold) and BTCUSD (bitcoin), each with its own
movement-engineered profile."""

import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.contracts import Candle, TradeDirection
from schools.base import SchoolStatus, SchoolTier
from schools.pulse import PULSE_FAMILY, pulse_school, _profile
from schools.registry import _schools, by_id

_UTCTZ = datetime.timezone.utc


def bar(t, o, h, l, c, vol=10, timeframe="M1", symbol="XAUUSD"):
    return Candle(symbol=symbol, timeframe=timeframe, time=t,
                  open=o, high=h, low=l, close=c,
                  volume=float(vol), tick_volume=float(vol))


def _base(minute_of_day: int, day: int = 6) -> float:
    return datetime.datetime(2026, 1, day, minute_of_day // 60,
                             minute_of_day % 60, tzinfo=_UTCTZ).timestamp()


def _series(minute_of_day=7 * 60 + 30, symbol="XAUUSD", scale=1.0,
            timeframe="M1"):
    candles = []
    base = _base(minute_of_day)
    c = 102.3 * scale
    s = scale
    for i in range(14):
        t = base + i * 60
        if i % 2 == 0:
            candles.append(bar(t, c - 0.2 * s, 103.0 * s, c - 1.0 * s,
                               c + 0.4 * s, symbol=symbol, timeframe=timeframe))
        else:
            candles.append(bar(t, c + 0.4 * s, 102.9 * s, c - 0.7 * s,
                               c - 0.4 * s, symbol=symbol, timeframe=timeframe))
        c = candles[-1].close
    candles.append(bar(base + 14 * 60, 102.3 * s, 104.1 * s, 102.1 * s,
                       102.7 * s, vol=20, symbol=symbol, timeframe=timeframe))
    return candles


def _fresh():
    pulse_school._last_pulse.clear()
    pulse_school._session_day.clear()
    pulse_school._session_trades.clear()


def test_pulse_is_registered_research_source():
    assert by_id("pulse") is pulse_school
    assert pulse_school.tier == SchoolTier.SOURCE
    assert pulse_school.status == SchoolStatus.RESEARCH
    assert "pulse" in [s.school_id for s in _schools]


def test_profiles_exist_for_gold_and_bitcoin_only():
    assert set(_profile("XAUUSD").keys()) == set(_profile("BTCUSD").keys())
    assert _profile("XAUUSD")["movement"] == "gold"
    assert _profile("BTCUSD")["movement"] == "bitcoin"
    assert _profile("EURUSD") is None
    assert _profile(None) is None


def test_pulse_rejects_unsupported_symbol():
    _fresh()
    candles = _series(minute_of_day=7 * 60 + 30, symbol="EURUSD")
    evid = pulse_school.evaluate(candles, "EURUSD", now=1.0)
    assert evid.suggestions == []
    assert evid.meta["rejected"] == "pulse_symbol"
    assert "XAUUSD" in evid.meta["allowed"]


def test_gold_emits_inside_london_window():
    _fresh()
    evid = pulse_school.evaluate(_series(minute_of_day=7 * 60 + 30),
                                 "XAUUSD", now=1.0)
    assert len(evid.suggestions) == 1
    sug = evid.suggestions[0]
    assert sug.school_id == "pulse"
    assert sug.direction == TradeDirection.SHORT
    assert sug.meta["session"] == "london"
    assert sug.meta["movement_profile"] == "gold"
    assert sug.meta["family"] == PULSE_FAMILY
    assert sug.meta["cost_ratio_max"] == 0.33
    assert sug.meta["time_stop_seconds"] == 360
    assert sug.meta["cadence_cap"] == 200


def test_bitcoin_uses_its_own_movement_profile():
    _fresh()
    scale = 700.0  # ~$71,000 BTC with gold-proportional bars
    evid = pulse_school.evaluate(
        _series(minute_of_day=15 * 60, symbol="BTCUSD", scale=scale),
        "BTCUSD", now=1.0)
    assert len(evid.suggestions) == 1
    sug = evid.suggestions[0]
    assert sug.meta["session"] == "newyork"
    assert sug.meta["movement_profile"] == "bitcoin"
    assert sug.meta["cost_ratio_max"] == 0.25
    assert sug.meta["time_stop_seconds"] == 360
    assert sug.school_id == "pulse"


def test_bitcoin_outside_window_silent():
    _fresh()
    evid = pulse_school.evaluate(
        _series(minute_of_day=23 * 60, symbol="BTCUSD", scale=700.0),
        "BTCUSD", now=1.0)
    assert evid.suggestions == []
    assert evid.meta["rejected"] == "outside_pulse_window"


def test_gold_silent_outside_window():
    _fresh()
    evid = pulse_school.evaluate(_series(minute_of_day=12 * 60),
                                 "XAUUSD", now=1.0)
    assert evid.suggestions == []
    assert evid.meta["rejected"] == "outside_pulse_window"


def test_pulse_discards_sub_minimum_depth_events():
    _fresh()
    # gold needs >= $0.50 of raid depth; shrink the bars so depth is tiny
    evid = pulse_school.evaluate(_series(minute_of_day=7 * 60 + 30,
                                         scale=0.1),
                                 "XAUUSD", now=1.0)
    assert evid.suggestions == []
    assert evid.meta["rejected"] == "thin_depth"


def test_pulse_cooldown_between_pulses():
    _fresh()
    candles = _series(minute_of_day=7 * 60 + 30)
    first = pulse_school.evaluate(candles, "XAUUSD", now=1.0)
    assert len(first.suggestions) == 1
    second = pulse_school.evaluate(candles, "XAUUSD", now=1.0)
    assert second.suggestions == []
    assert second.meta["rejected"] == "pulse_cooldown"


def test_pulse_requires_fast_timeframe():
    _fresh()
    candles = _series(minute_of_day=7 * 60 + 30, timeframe="M15")
    evid = pulse_school.evaluate(candles, "XAUUSD", now=1.0)
    assert evid.suggestions == []
    assert evid.meta["rejected"] == "pulse_timeframe"


def test_pulse_respected_window_override(monkeypatch):
    monkeypatch.setenv("QT_PULSE_WINDOWS", "asia:01:00-03:00")
    _fresh()
    evid = pulse_school.evaluate(_series(minute_of_day=2 * 60),
                                 "XAUUSD", now=1.0)
    assert len(evid.suggestions) == 1
    assert evid.suggestions[0].meta["session"] == "asia"
