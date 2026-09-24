"""Unit tests for the Market Context engine (intelligence/market_reader.py)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import math


from core.contracts import Candle, TrendDirection
from intelligence.market_reader import (
    MarketContext,
    _cluster_zones,
    _ema,
    _median,
    _scale_trend,
    _volatility_bucket,
    build_market_context,
)


def _candle(time: int, o: float, h: float, l: float, c: float) -> Candle:
    return Candle(symbol="TEST", timeframe="M1", time=float(time),
                  open=o, high=h, low=l, close=c, volume=1.0, tick_volume=1.0)


def _uptrend(n=300) -> list[Candle]:
    return [_candle(i, 100 + i * 0.2, 100 + i * 0.2 + 0.4, 100 + i * 0.2 - 0.3,
                    100 + i * 0.2 + 0.1) for i in range(n)]


def _downtrend(n=300) -> list[Candle]:
    return [_candle(i, 160 - i * 0.2, 160 - i * 0.2 + 0.4, 160 - i * 0.2 - 0.3,
                    160 - i * 0.2 - 0.1) for i in range(n)]


def _range_market(n=300) -> list[Candle]:
    base = 130.0
    out = []
    for i in range(n):
        if i >= n - 60:
            wave = 0.0  # flat tail so fast/slow EMAs equalize -> sideways
        else:
            wave = 0.3 * math.sin(i / 12.0)
        out.append(_candle(i, base + wave, base + wave + 0.5,
                           base + wave - 0.5, base + wave))
    return out


def _zone_setup() -> list[Candle]:
    """400-bar series ending with confirmed swing highs at ~135 (same level)."""
    c = _uptrend(400)
    base = 134.0
    for i in range(340, 400):
        peak = (i % 6) == 3
        if peak:
            c[i] = _candle(i, base - 0.1, 135.05, base - 0.2, base + 0.1)
        else:
            c[i] = _candle(i, base, base + 0.3, base - 0.3, base - 0.05)
    return c


# --- primitives -----------------------------------------------------------


def test_ema_track():
    vals = [1.0] * 100
    assert abs(_ema(vals, 10) - 1.0) < 1e-12
    vals2 = list(range(1, 51))
    assert _ema(vals2, 20) > vals2[0]


def test_median_odd():
    assert _median([1, 3, 5]) == 3
    assert _median([]) == 0.0


def test_scale_trend_up():
    closes = [100 + i for i in range(300)]
    assert _scale_trend(closes, 20, 50) is TrendDirection.BULLISH


def test_scale_trend_down():
    closes = [300 - i for i in range(300)]
    assert _scale_trend(closes, 20, 50) is TrendDirection.BEARISH


def test_scale_trend_flat():
    closes = [100.0] * 300
    assert _scale_trend(closes, 20, 50) is TrendDirection.SIDEWAYS


def test_scale_trend_fallback_short():
    closes = [100.0] * 15
    assert _scale_trend(closes, 20, 50) is TrendDirection.SIDEWAYS


def test_volatility_bucket_ratios():
    assert _volatility_bucket(1.0, 1.0) == "medium"
    assert _volatility_bucket(1.9, 1.0) == "extreme"
    assert _volatility_bucket(1.3, 1.0) == "high"
    assert _volatility_bucket(0.5, 1.0) == "low"
    assert _volatility_bucket(1.0, 0.0) == "low"


# --- clustering -----------------------------------------------------------


def test_cluster_zones_confirms_level():
    # Three swings all at price 135 within tolerance
    class Fake:
        def __init__(self, p, i):
            self.price = p
            self.index = i
    items = [Fake(135.0, 10), Fake(135.02, 15), Fake(134.98, 20)]
    zones = _cluster_zones(items, 0.1, "resistance")
    assert len(zones) == 1
    assert zones[0].touches == 3
    assert zones[0].kind == "resistance"
    assert 0 < zones[0].strength <= 1.0


def test_cluster_zones_ignores_single_touch():
    class Fake:
        def __init__(self, p, i):
            self.price = p
            self.index = i
    items = [Fake(100.0, 1)]
    zones = _cluster_zones(items, 0.5, "support")
    assert len(zones) == 0


# --- build_market_context --------------------------------------------------


def test_uptrend_context():
    ctx = build_market_context(_uptrend(300), "TEST", "M5")
    assert isinstance(ctx, MarketContext)
    assert ctx.candles == 300
    assert ctx.macro_trend is TrendDirection.BULLISH
    assert ctx.intermediate_trend is TrendDirection.BULLISH
    assert ctx.context_score > 0
    assert ctx.context_score <= 100
    assert len(ctx.market_story) >= 5
    assert all("en" in s and "ar" in s for s in ctx.market_story)
    assert isinstance(ctx.regime, str)
    assert "/" in ctx.regime


def test_downtrend_context():
    ctx = build_market_context(_downtrend(300), "TEST", "M5")
    assert ctx.macro_trend is TrendDirection.BEARISH
    assert ctx.intermediate_trend is TrendDirection.BEARISH
    assert ctx.micro_trend is TrendDirection.BEARISH


def test_range_market_sideways():
    flat = [_candle(i, 130.0, 130.5, 129.5, 130.0) for i in range(300)]
    ctx = build_market_context(flat, "TEST", "M5")
    assert ctx.intermediate_trend is TrendDirection.SIDEWAYS
    assert ctx.macro_trend is TrendDirection.SIDEWAYS
    assert "sideways" in ctx.regime

    waved = build_market_context(_range_market(300), "TEST", "M5")
    assert 0 <= waved.context_score <= 100
    assert len(waved.market_story) >= 5


def test_support_resistance_formed():
    ctx = build_market_context(_zone_setup(), "TEST", "M5")
    assert len(ctx.resistance_zones) >= 1
    z = ctx.resistance_zones[0]
    assert z.touches >= 2
    assert z.kind == "resistance"
    assert z.price > 0


def test_premium_discount_boundaries():
    extreme_up = _uptrend(300)
    extreme_up[-1] = _candle(299, 300, 302, 299, 301)  # way above range
    ctx = build_market_context(extreme_up, "TEST", "M5")
    # premium > 0 because close near top of last-100 range
    assert ctx.premium_discount >= -1.0
    assert ctx.premium_discount <= 1.0


def test_empty_candles_safe():
    ctx = build_market_context([], "TEST", "M5")
    assert ctx.candles == 0
    assert ctx.context_score >= 0


def test_score_breakdown_has_expected_keys():
    ctx = build_market_context(_uptrend(300), "TEST", "M5")
    for k in ("trend", "structure", "liquidity", "regime", "fair_value",
              "compression", "momentum", "total"):
        assert k in ctx.score_breakdown, f"missing {k}"


def test_story_htf_poi_included():
    # uptrend enough for FVG / OB detection to yield a poi
    ctx = build_market_context(_uptrend(300), "TEST", "M5")
    ids = {s["id"] for s in ctx.market_story}
    assert "score" in ids
    assert "regime" in ids


def test_as_dict_roundtrip():
    ctx = build_market_context(_uptrend(300), "TEST", "M5")
    d = ctx.as_dict()
    assert d["symbol"] == "TEST"
    assert isinstance(d["candles"], int)
    assert isinstance(d["support_zones"], list)
    assert isinstance(d["score_breakdown"], dict)
