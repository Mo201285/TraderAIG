"""Research & Intelligence Core: regime detection, contexts, evidence.

Computes market-regime snapshots recurrently (Tier 0/1 deterministic
plus optional Tier 2 signals). Emits events when the regime changes.
"""
from __future__ import annotations

import time
import uuid
from typing import Dict, Optional, Sequence

from core.contracts import (
    Candle,
    LiquidityState,
    MarketStructure,
    RegimeSnapshot,
    TradingSession,
    TrendDirection,
    VolatilityRegime,
)
from core.events import Event, EventType, bus
from core.logging import get_logger


log = get_logger("intelligence.regime")


def detect_session(timestamp: float) -> TradingSession:
    """Map UTC hour to a trading session (simplified)."""
    import datetime

    hour = datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc).hour
    hour_utc = hour
    if 0 <= hour_utc < 7:
        return TradingSession.ASIA
    if 7 <= hour_utc < 12:
        return TradingSession.LONDON
    if 12 <= hour_utc < 16:
        return TradingSession.LONDON_NY
    if 16 <= hour_utc < 21:
        return TradingSession.NEW_YORK
    return TradingSession.CLOSED


def compute_volatility(candles: Sequence[Candle], window: int = 20) -> float:
    """Return normalized volatility as ATR ratio over recent candles."""
    if len(candles) < 2:
        return 0.0
    recent = candles[-window:]
    ranges = [c.range for c in recent if c.range > 0]
    if not ranges:
        return 0.0
    mean_range = sum(ranges) / len(ranges)
    if len(ranges) > 1:
        variance = sum((r - mean_range) ** 2 for r in ranges) / len(ranges)
        std = variance ** 0.5
        if mean_range > 0:
            return std / mean_range
    return 0.0


def classify_volatility(cv: float) -> VolatilityRegime:
    if cv < 0.3:
        return VolatilityRegime.LOW
    if cv < 0.6:
        return VolatilityRegime.NORMAL
    if cv < 1.0:
        return VolatilityRegime.HIGH
    return VolatilityRegime.EXTREME


def classify_trend(candles: Sequence[Candle], lookback: int = 50) -> TrendDirection:
    """Simple EMA-based trend classification."""
    if len(candles) < lookback:
        return TrendDirection.SIDEWAYS
    closes = [c.close for c in candles]
    ema_fast = _ema(closes, 10)
    ema_slow = _ema(closes, 50)
    if ema_fast > ema_slow * 1.002:
        return TrendDirection.BULLISH
    if ema_fast < ema_slow * 0.998:
        return TrendDirection.BEARISH
    return TrendDirection.SIDEWAYS


def classify_structure(candles: Sequence[Candle],
                       trend: TrendDirection) -> MarketStructure:
    """Classify price structure using higher-highs/lower-lows logic."""
    if len(candles) < 10:
        return MarketStructure.RANGING

    highs = [c.high for c in candles[-10:]]
    lows = [c.low for c in candles[-10:]]

    higher_highs = all(highs[i] >= highs[i - 1] for i in range(1, len(highs)))
    lower_lows = all(lows[i] <= lows[i - 1] for i in range(1, len(lows)))

    if higher_highs and not lower_lows:
        return MarketStructure.IMPULSE
    if lower_lows and not higher_highs:
        return MarketStructure.BREAKDOWN
    if trend == TrendDirection.SIDEWAYS:
        return MarketStructure.RANGING
    return MarketStructure.PULLBACK


def classify_liquidity(spread: float, volume_tick: float) -> LiquidityState:
    if spread <= 0:
        return LiquidityState.UNKNOWN
    if spread < 5 and volume_tick > 0:
        return LiquidityState.HIGH
    if spread < 20:
        return LiquidityState.MEDIUM
    if spread < 100:
        return LiquidityState.LOW
    return LiquidityState.ILLIQUID


def _ema(values: Sequence[float], period: int) -> float:
    if not values:
        return 0.0
    k = 2 / (period + 1)
    ema = values[0]
    for v in values[1:]:
        ema = v * k + ema * (1 - k)
    return ema


class RegimeEngine:
    """Computes regime snapshots for a single symbol on a single timeframe."""

    def __init__(self, symbol: str, timeframe: str = "M15") -> None:
        self.symbol = symbol
        self.timeframe = timeframe
        self._known_regime: Optional[RegimeSnapshot] = None

    def compute(self, candles: Sequence[Candle],
                spread: float = 0.0, volume_tick: float = 0.0) -> RegimeSnapshot:
        trend = classify_trend(candles)
        structure = classify_structure(candles, trend)
        cv = compute_volatility(candles)
        vol = classify_volatility(cv)
        session = detect_session(time.time())
        liquidity = classify_liquidity(spread, volume_tick)

        snapshot = RegimeSnapshot(
            snapshot_id=str(uuid.uuid4()),
            timestamp=time.time(),
            symbol=self.symbol,
            trend=trend,
            structure=structure,
            volatility=vol,
            session=session,
            liquidity=liquidity,
            confidence=0.8 if len(candles) > 50 else 0.4,
            metadata={
                "timeframe": self.timeframe,
                "volatility_coef": round(cv, 4),
            },
        )

        if self._changed(snapshot):
            bus.emit(Event(
                type=EventType.REGIME_CHANGED,
                source="intelligence.regime",
                payload={"snapshot": snapshot.as_dict()},
            ))
            log.info(f"{self.symbol} regime -> {snapshot.trend.value}/"
                     f"{snapshot.structure.value} ({snapshot.volatility.value})")
        self._known_regime = snapshot
        return snapshot

    def _changed(self, new: RegimeSnapshot) -> bool:
        if self._known_regime is None:
            return True
        old = self._known_regime
        return (old.trend != new.trend
                or old.structure != new.structure
                or old.session != new.session)


def snapshot_to_dict(snapshot: RegimeSnapshot) -> Dict:
    """Public helper mirroring RegimeSnapshot.as_dict contract."""
    return {
        "snapshot_id": snapshot.snapshot_id,
        "timestamp": snapshot.timestamp,
        "symbol": snapshot.symbol,
        "trend": snapshot.trend.value,
        "structure": snapshot.structure.value,
        "volatility": snapshot.volatility.value,
        "session": snapshot.session.value,
        "liquidity": snapshot.liquidity.value,
        "confidence": snapshot.confidence,
        "metadata": snapshot.metadata,
    }
