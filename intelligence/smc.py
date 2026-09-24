"""SMART MONEY CONCEPTS (SMC) ANALYSIS ENGINE.

Applies liquidity, Order Block (OB), Fair Value Gap (FVG), and
market-structure logic to produce evidence for thesis construction.

This module is deterministic and fast; it never blocks the trading path.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Sequence

from core.contracts import Candle, TradeDirection, TrendDirection
from core.logging import get_logger


log = get_logger("intelligence.smc")


# ===========================================================================
# Enumerations
# ===========================================================================


class BreakType(str, Enum):
    """Types of market-structure breaks."""

    NO_BREAK = "no_break"
    BOS = "break_of_structure"  # continuation
    CHoCH = "change_of_character"  # reversal
    MSS = "market_structure_shift"  # deep reversal
    INVALID = "invalid"


class LiquidityZones(Enum):
    """Zones commonly targeted by institutional liquidity-seeking."""

    EQUAL_HIGH = "equal_high"
    EQUAL_LOW = "equal_low"
    PREV_HIGH = "prev_high"
    PREV_LOW = "prev_low"
    SWING_HIGH = "swing_high"
    SWING_LOW = "swing_low"
    TRENDLINE = "trendline"
    NONE = "none"


# ===========================================================================
# Data containers
# ===========================================================================


@dataclass
class FVG:
    """Fair Value Gap (imbalance) between candles."""

    index: int
    top: float
    bottom: float
    time: float
    direction: TradeDirection = TradeDirection.LONG
    filled: bool = False
    fill_time: Optional[float] = None

    @property
    def size(self) -> float:
        return self.top - self.bottom

    def is_valid(self) -> bool:
        return self.size > 0


@dataclass
class OrderBlock:
    """Order Block: last opposite candle before an impulsive move."""

    index: int
    top: float
    bottom: float
    direction: TradeDirection
    time: float
    mitigated: bool = False

    @property
    def is_bullish(self) -> bool:
        return self.direction == TradeDirection.LONG

    @property
    def size(self) -> float:
        return self.top - self.bottom


@dataclass
class Structure:
    """A market-structure point (swing)."""

    index: int
    price: float
    type: str  # 'high' | 'low'
    time: float


@dataclass
class LiquidityCluster:
    """A group of equal lows/highs considered a liquidity pool."""

    zone_type: LiquidityZones
    price: float
    first_index: int
    last_index: int
    strength: float  # 0..1 how many touches


@dataclass
class SMCEvidence:
    """Aggregated SMC analysis result for a symbol."""

    symbol: str
    timeframe: str
    timestamp: float
    trend: TrendDirection
    last_swing: Optional[Structure]
    last_fvg: Optional[FVG]
    last_ob: Optional[OrderBlock]
    liquidity_pools: List[LiquidityCluster] = field(default_factory=list)
    structure_breaks: List[BreakType] = field(default_factory=list)
    bs_ob_distance: float = 0.0
    risk_reward_map: List[float] = field(default_factory=list)

    def as_dict(self) -> Dict:
        """Canonical JSON representation for external consumers."""
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "timestamp": self.timestamp,
            "trend": self.trend.value,
            "last_swing": (
                {"index": self.last_swing.index, "price": self.last_swing.price,
                 "type": self.last_swing.type} if self.last_swing else None
            ),
            "last_fvg": (
                {"top": self.last_fvg.top, "bottom": self.last_fvg.bottom,
                 "filled": self.last_fvg.filled} if self.last_fvg else None
            ),
            "last_ob": (
                {"top": self.last_ob.top, "bottom": self.last_ob.bottom,
                 "direction": self.last_ob.direction.value} if self.last_ob else None
            ),
            "liquidity_pools": [
                {"type": z.zone_type.value, "price": z.price, "strength": z.strength}
                for z in self.liquidity_pools
            ],
            "structure_breaks": [b.value for b in self.structure_breaks],
        }
# ===========================================================================
# Swing detection
# ===========================================================================


def _find_swings(candles: Sequence[Candle], lookback: int = 50) -> List[Structure]:
    """Find swing highs/lows using a 2-candle confirmation window."""
    swings: List[Structure] = []
    if len(candles) < 5:
        return swings

    start = max(0, len(candles) - lookback)
    for i in range(start + 2, len(candles) - 2):
        c = candles[i]
        prev2, prev1 = candles[i - 1], candles[i - 2]
        next1, next2 = candles[i + 1], candles[i + 2]

        if c.high > prev1.high and c.high > prev2.high and \
           c.high > next1.high and c.high > next2.high:
            swings.append(Structure(i, c.high, "high", c.time))
        if c.low < prev1.low and c.low < prev2.low and \
           c.low < next1.low and c.low < next2.low:
            swings.append(Structure(i, c.low, "low", c.time))
    return swings


# ===========================================================================
# FVG / Order Block detection
# ===========================================================================


def _find_fvgs(candles: Sequence[Candle], lookback: int = 50) -> List[FVG]:
    """Three-candle imbalance: candle[1] gap not covered by candle[0]/candle[2]."""
    fvgs: List[FVG] = []
    if len(candles) < 3:
        return fvgs

    start = max(0, len(candles) - lookback)
    for i in range(start + 1, len(candles) - 1):
        prev, cur, _ = candles[i - 1], candles[i], candles[i + 1]

        if cur.low > prev.high:  # bullish FVG
            fvgs.append(FVG(index=i, top=cur.low, bottom=prev.high,
                            direction=TradeDirection.LONG, time=cur.time))
        elif cur.high < prev.low:  # bearish FVG
            fvgs.append(FVG(index=i, top=prev.low, bottom=cur.high,
                            direction=TradeDirection.SHORT, time=cur.time))
    return fvgs


def _find_order_blocks(candles: Sequence[Candle], lookback: int = 50) -> List[OrderBlock]:
    """Order Blocks: the last down candle before an up impulse (and vice versa)."""
    obs: List[OrderBlock] = []
    if len(candles) < 5:
        return obs

    start = max(0, len(candles) - lookback)
    for i in range(start + 1, len(candles) - 1):
        prev, cur, nxt = candles[i - 1], candles[i], candles[i + 1]

        # Bullish OB: prev bearish, current/nxt strong bullish impulse
        imp_size = nxt.range
        if imp_size > 0:
            if not prev.is_bullish and nxt.is_bullish and \
               nxt.close > cur.close * 1.0:
                obs.append(OrderBlock(
                    index=prev.index if hasattr(prev, "index") else i - 1,
                    top=prev.high,
                    bottom=prev.low,
                    direction=TradeDirection.LONG,
                    time=prev.time,
                ))

            if prev.is_bullish and not nxt.is_bullish and \
               nxt.close < cur.close * 1.0:
                obs.append(OrderBlock(
                    index=prev.index if hasattr(prev, "index") else i - 1,
                    top=prev.high,
                    bottom=prev.low,
                    direction=TradeDirection.SHORT,
                    time=prev.time,
                ))
    return obs


# ===========================================================================
# Liquidity detection
# ===========================================================================


def _find_liquidity(candles: Sequence[Candle], swings: List[Structure],
                    lookback: int = 50) -> List[LiquidityCluster]:
    """Detect equal highs/lows clusters from recent swings."""
    pools: List[LiquidityCluster] = []

    highs = [s for s in swings if s.type == "high"]
    lows = [s for s in swings if s.type == "low"]

    def _cluster(items: List[Structure], tol_pips: float, zone: LiquidityZones) -> None:
        if len(items) < 2:
            return
        for i in range(len(items) - 1):
            a = items[i]
            for b in items[i + 1:]:
                if abs(a.price - b.price) <= tol_pips:
                    pools.append(LiquidityCluster(
                        zone_type=zone,
                        price=(a.price + b.price) / 2,
                        first_index=a.index,
                        last_index=b.index,
                        strength=min(1.0, (b.index - a.index) / 20.0),
                    ))

    pip = 0.01  # extremely simplified; real pip derived from symbol
    for sym_pip in (pip * 5,):  # cluster tolerance
        _cluster(highs, sym_pip, LiquidityZones.EQUAL_HIGH)
        _cluster(lows, sym_pip, LiquidityZones.EQUAL_LOW)

    return pools


# ===========================================================================
# Structure break detection
# ===========================================================================


def _detect_structure_break(candles: Sequence[Candle],
                            swings: List[Structure],
                            current_price: float) -> BreakType:
    """Detect whether recent candle broke a swing level (BOS/CHoCH)."""
    if len(swings) < 2:
        return BreakType.NO_BREAK

    last = swings[-1]
    prev = swings[-2]

    # Simplify: if current price crosses the most recent swing high/low.
    if last.type == "high":
        if current_price > last.price:
            return BreakType.BOS if last.price > prev.price else BreakType.CHoCH
    elif last.type == "low":
        if current_price < last.price:
            return BreakType.BOS if last.price < prev.price else BreakType.CHoCH
    return BreakType.NO_BREAK


# ===========================================================================
# Main entry point
# ===========================================================================


def analyze(candles: Sequence[Candle], symbol: str = "XAUUSD",
            timeframe: str = "M15") -> SMCEvidence:
    """Run the full SMC analysis pipeline over the supplied candle buffer."""
    if len(candles) < 10:
        return SMCEvidence(
            symbol=symbol, timeframe=timeframe, timestamp=time.time(),
            trend=TrendDirection.SIDEWAYS,
            last_swing=None, last_fvg=None, last_ob=None,
        )

    swings = _find_swings(candles)
    fvgs = _find_fvgs(candles)
    obs = _find_order_blocks(candles)
    pools = _find_liquidity(candles, swings)
    current_price = candles[-1].close
    trend = _infer_trend(candles)

    last_swing = swings[-1] if swings else None
    last_fvg = fvgs[-1] if fvgs else None
    last_ob = obs[-1] if obs else None
    break_type = _detect_structure_break(candles, swings, current_price)

    evidence = SMCEvidence(
        symbol=symbol,
        timeframe=timeframe,
        timestamp=time.time(),
        trend=trend,
        last_swing=last_swing,
        last_fvg=last_fvg,
        last_ob=last_ob,
        liquidity_pools=pools,
        structure_breaks=[break_type],
    )
    log.debug(f"{symbol} SMC evidence: trend={trend.value}, "
              f"n_swings={len(swings)}, n_fvgs={len(fvgs)}, "
              f"n_obs={len(obs)}, break={break_type.value}")
    return evidence


def _infer_trend(candles: Sequence[Candle]) -> TrendDirection:
    """EMA50 vs EMA200 shortcut for trend side."""
    if len(candles) < 200:
        if len(candles) < 50:
            return TrendDirection.SIDEWAYS
        ema = _ema([c.close for c in candles], 20)
        return TrendDirection.BULLISH if candles[-1].close > ema else TrendDirection.BEARISH

    ema_fast = _ema([c.close for c in candles], 50)
    ema_slow = _ema([c.close for c in candles], 200)
    if ema_fast > ema_slow:
        return TrendDirection.BULLISH
    if ema_fast < ema_slow:
        return TrendDirection.BEARISH
    return TrendDirection.SIDEWAYS


def _ema(values: List[float], period: int) -> float:
    if not values:
        return 0.0
    k = 2 / (period + 1)
    ema = values[0]
    for v in values[1:]:
        ema = v * k + ema * (1 - k)
    return ema


# ===========================================================================
# Scalp-oriented helpers (zone resolution + internal liquidity targets)
# ===========================================================================


def mark_fvgs_filled(fvgs: Sequence[FVG],
                     candles: Sequence[Candle]) -> List[FVG]:
    """Mark an imbalance resolved once price closes through the *whole* gap
    from the losing side and exits the far edge:

      bullish gap  -> filled when a later close < bottom
      bearish gap  -> filled when a later close > top

    A close *into* the gap, or further in trade direction, does not resolve
    the imbalance (that is exactly the retrace being traded).
    """
    for f in fvgs:
        if f.direction == TradeDirection.LONG:
            f.filled = any(c.close < f.bottom for c in candles[f.index + 1:])
        else:
            f.filled = any(c.close > f.top for c in candles[f.index + 1:])
    return list(fvgs)


def unfilled_fvgs(candles: Sequence[Candle],
                  lookback: int = 50) -> List[FVG]:
    """Fresh, not-yet-resolved imbalance gaps (never fully crossed)."""
    fvgs = _find_fvgs(candles, lookback)
    return mark_fvgs_filled(fvgs, candles)


def nearest_liquidity_after(pools: Sequence[LiquidityCluster],
                            price: float,
                            direction: TradeDirection,
                            candles: Optional[Sequence[Candle]] = None,
                            max_gap_idx: int = 10) -> Optional[LiquidityCluster]:
    """Nearest *internal* (non-swept) liquidity pool beyond `price` in the
    trade direction, restricted to recent formations so the target stays a
    scalp (nearby liquidity) rather than a distant structural objective.
    """
    if direction == TradeDirection.LONG:
        cands = [p for p in pools if p.price > price]
        cands.sort(key=lambda p: p.price)
    elif direction == TradeDirection.SHORT:
        cands = [p for p in pools if p.price < price]
        cands.sort(key=lambda p: p.price, reverse=True)
    else:
        return None
    for pool in cands:
        if candles is not None and max_gap_idx:
            if pool.last_index >= len(candles) - max_gap_idx:
                return pool
        else:
            return pool
    return None
