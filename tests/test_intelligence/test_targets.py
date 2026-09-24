"""Unit tests for the take-profit ladder builder (swings + strong S/R)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.contracts import Candle, TradeDirection
from intelligence.institutional import PoolCluster
from intelligence.targets import LADDER_MAX, build_target_ladder


def bar(o, h, l, c, t=0.0):
    return Candle(symbol="XAUUSD", timeframe="M15", time=t, open=o,
                  high=h, low=l, close=c, volume=100.0, tick_volume=100.0)


def _series(rows):
    return [bar(*r) for r in rows]


_SWING_HI_SERIES = [
    (100.0, 100.4, 99.8, 100.3), (100.3, 100.8, 100.2, 100.7),
    (100.7, 101.2, 100.6, 101.0), (101.0, 103.0, 100.9, 101.8),
    (101.8, 102.0, 101.2, 101.5), (101.5, 101.7, 101.1, 101.3),
    (101.3, 101.5, 100.4, 100.7), (100.7, 101.0, 100.6, 100.9),
    (100.9, 101.3, 100.8, 101.2), (101.2, 103.4, 101.1, 103.0),
    (103.0, 104.6, 102.9, 103.6), (103.6, 103.8, 102.8, 103.0),
    (103.0, 103.2, 102.6, 102.9), (102.9, 103.1, 102.5, 102.8),
]

_EQ_LOW_SERIES = [
    (100.9, 101.4, 100.9, 101.3), (101.3, 101.8, 101.2, 101.7),
    (101.7, 102.0, 101.5, 101.8), (101.8, 102.2, 101.6, 101.9),
    (101.9, 102.1, 101.3, 101.5), (101.5, 101.7, 101.0, 101.2),
    (101.2, 101.4, 100.7, 100.9), (100.9, 101.1, 100.4, 100.6),
    (100.6, 100.8, 99.8, 100.1),  (100.1, 100.3, 99.8, 99.9),
    (99.9, 100.2, 99.8, 100.2),  (100.2, 100.4, 99.9, 100.3),
    (100.3, 100.6, 100.2, 100.5), (100.5, 100.8, 100.4, 100.7),
]


def test_ladder_uses_nearest_and_farthest_swing_highs():
    ladder = build_target_ladder(_series(_SWING_HI_SERIES), [],
                                 TradeDirection.LONG, price=100.5)
    prices = [l.price for l in ladder]
    sources = [l.source for l in ladder]
    assert 103.0 in prices and 104.6 in prices
    assert sources[0] == "swing_high" and sources[-1] == "swing_high"
    assert prices == sorted(prices)          # TP1 nearest -> farthest
    assert prices[-1] == max(prices)         # farthest is the top of the ladder


def test_ladder_is_capped():
    ladder = build_target_ladder(_series(_SWING_HI_SERIES), [],
                                 TradeDirection.LONG, price=100.5)
    assert len(ladder) <= LADDER_MAX


def test_strong_support_included_and_nearest_first_for_short():
    ladder = build_target_ladder(_series(_EQ_LOW_SERIES), [],
                                 TradeDirection.SHORT, price=100.5)
    support = [l for l in ladder if l.source == "support"
               and abs(l.price - 99.8) < 1e-6]
    assert support and support[0].touches >= 2
    prices = [l.price for l in ladder]
    assert all(p < 100.5 for p in prices)
    assert prices == sorted(prices, reverse=True)   # TP1 nearest -> farthest


def test_levels_dedupe_across_sources():
    pool = PoolCluster(kind="buyside", level=104.6, touches=4, index=10)
    ladder = build_target_ladder(_series(_SWING_HI_SERIES), [pool],
                                 TradeDirection.LONG, price=100.5)
    same_level = [l for l in ladder if abs(l.price - 104.6) < 1e-6]
    assert len(same_level) == 1


def test_empty_ladder_for_flat_direction():
    assert build_target_ladder(_series(_SWING_HI_SERIES), [],
                               TradeDirection.FLAT, price=100.5) == []
