"""Unit tests for the institutional-flow engine."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.contracts import Candle, TradeDirection, TrendDirection
from intelligence.institutional import InstitutionalFlow, _find_pools


def bar(t, o, h, l, c, vol=10):
    return Candle(symbol="XAUUSD", timeframe="M15", time=t,
                  open=o, high=h, low=l, close=c,
                  volume=float(vol), tick_volume=float(vol))


BASE = 100.0


def _oscillate(pairs, low_level, high_hi, high_lo):
    """Alternating down/up bars that land exact lows at `low_level`."""
    out = []
    c = low_level + 1.2
    for i in range(pairs * 2):
        if i % 2 == 0:  # down bar touching the pool low
            out.append(bar(i, c + 0.4, c + 0.7, low_level, c - 0.6))
        else:           # up bar bouncing off it
            out.append(bar(i, c - 0.6, high_hi, low_level + 0.2, c + 0.4))
        c = out[-1].close
    return out


def _equal_sellside(raid_high=100.6, raid_low=99.1, raid_tick=1000):
    """12 oscillating bars around a 100.0 equal-low pool, then a raid bar."""
    candles = _oscillate(6, 100.0, 102.0, 100.2)
    candles.append(bar(12.0, 100.4, raid_high, raid_low, 100.35,
                       vol=raid_tick))
    return candles


def _equal_buyside():
    """12 oscillating bars around a 103.0 equal-high pool, then a raid bar."""
    candles = []
    c = 102.3
    for i in range(12):
        if i % 2 == 0:  # up bar touching the pool high
            candles.append(bar(i, c - 0.2, 103.0, c - 1.0, c + 0.4))
        else:
            candles.append(bar(i, c + 0.4, 102.9, c - 0.7, c - 0.4))
        c = candles[-1].close
    candles.append(bar(12.0, 102.3, 104.1, 102.1, 102.7, vol=20))
    return candles


def test_find_pools_clusters_equal_lows():
    pools = _find_pools(_equal_sellside())
    sell = [p for p in pools if p.kind == "sellside"]
    assert sell, "expected a sellside cluster"
    assert any(abs(p.level - 100.0) < 1e-6 and p.touches >= 2 for p in sell)


def test_sellside_absorption_raid_yields_long():
    read = InstitutionalFlow().analyze(_equal_sellside(), "XAUUSD")
    assert not read.flat
    e = read.best()
    assert e is not None
    assert e.direction == TradeDirection.LONG
    assert e.kind == "absorption"
    assert e.pool_type == "sellside"
    assert e.pool_level > e.reached          # pool was swept from below
    assert e.pool_level <= 100.2             # nearest resting cluster
    assert e.close_back is True
    assert e.depth > 0
    assert "absorption" in read.narrative


def test_buyside_raid_yields_short():
    read = InstitutionalFlow().analyze(_equal_buyside(), "XAUUSD")
    assert not read.flat
    e = read.best()
    assert e.direction == TradeDirection.SHORT
    assert e.kind == "buyside_raid"
    assert e.pool_type == "buyside"


def test_vacuum_raid_is_weaker():
    heavy = InstitutionalFlow().analyze(_equal_sellside(), "XAUUSD")
    thin = InstitutionalFlow().analyze(
        _equal_sellside(raid_low=99.1, raid_tick=2), "XAUUSD")
    assert thin.best().kind == "vacuum_raid"
    assert thin.best().strength < heavy.best().strength


def test_no_close_back_means_flat():
    # sweep below the pool that stays below: no close back -> no event
    candles = _equal_sellside(raid_high=100.2, raid_low=99.1, raid_tick=1000)
    candles[-1] = bar(10.0, 100.4, 100.2, 99.1, 99.4, vol=1000)
    read = InstitutionalFlow().analyze(candles, "XAUUSD")
    assert read.flat
    assert read.verdict_direction == TradeDirection.FLAT


def test_live_price_probe_flags_in_progress():
    candles = _equal_sellside()
    read = InstitutionalFlow().analyze(candles, "XAUUSD",
                                       current_price=100.55)
    assert not read.flat
    assert read.live_price == 100.55
    assert read.best().live is True


def test_trend_is_reported_even_when_flat():
    read = InstitutionalFlow().analyze(_equal_sellside(), "XAUUSD")
    assert read.trend in (TrendDirection.BULLISH,
                          TrendDirection.BEARISH,
                          TrendDirection.SIDEWAYS)


def test_ladder_is_ordered_for_long():
    read = InstitutionalFlow().analyze(_equal_sellside(), "XAUUSD")
    ladder = read.ladder
    assert read.flat is False
    assert len(ladder) >= 1
    prices = [l.price for l in ladder]
    assert all(p > _equal_sellside()[-1].close for p in prices)
    assert prices == sorted(prices)          # TP1 nearest, ascending
    assert "liquidity_pool" in {l.source for l in ladder}
    for l in ladder:
        assert 0.0 < l.strength <= 1.0


def test_ladder_is_ordered_for_short():
    read = InstitutionalFlow().analyze(_equal_buyside(), "XAUUSD")
    ladder = read.ladder
    assert len(ladder) >= 2
    prices = [l.price for l in ladder]
    assert all(p < _equal_buyside()[-1].close for p in prices)
    assert prices == sorted(prices, reverse=True)     # TP1 nearest, descending


def test_ladder_is_empty_when_flat():
    read = InstitutionalFlow().analyze(_equal_sellside()[:-1] + [
        bar(11.0, 100.4, 100.8, 99.9, 99.5, vol=1000)], "XAUUSD")
    assert read.flat
    assert read.ladder == []
