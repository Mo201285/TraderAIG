"""Canonical contracts / domain types for TraderAIG.

These are the shared, typed data structures that all components
read from and write to. Each represents a slice of canonical truth.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any as AnyType
from typing import Dict


class TrendDirection(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    SIDEWAYS = "sideways"


class MarketStructure(str, Enum):
    ACCUMULATION = "accumulation"
    DISTRIBUTION = "distribution"
    IMPULSE = "impulse"
    PULLBACK = "pullback"
    BREAKDOWN = "breakdown"
    RANGING = "ranging"


class VolatilityRegime(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    EXTREME = "extreme"


class TradingSession(str, Enum):
    ASIA = "asia"
    LONDON = "london"
    NEW_YORK = "new_york"
    LONDON_NY = "london_ny"
    CLOSED = "closed"


class LiquidityState(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    ILLIQUID = "illiquid"
    UNKNOWN = "unknown"


class TradeDirection(str, Enum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


class ThesisStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    INVALIDATED = "invalidated"
    COMPLETED = "completed"
    EXPIRED = "expired"


class OrderStatus(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    FILLED = "filled"
    PARTIAL = "partial"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


class PositionStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"


class VulnerabilityType(str, Enum):
    """Smart Money Concepts vulnerability types for liquidity analysis."""

    PREMIUM = "premium"
    DISCOUNT = "discount"
    EQUAL_HIGHS = "equal_highs"
    EQUAL_LOWS = "equal_lows"
    OLD_HIGH = "old_high"
    OLD_LOW = "old_low"
    TRENDLINE = "trendline"
    CLOSE_NONE = "none"


class SessionType(str, Enum):
    ASIAN = "asian"
    LONDON = "london"
    NEW_YORK = "new_york"
    LONDON_NY = "london_ny"


class RangeStatus(str, Enum):
    ACTIVE = "active"
    BROKEN = "broken"


# ---------------------------------------------------------------------------
# Market
# ---------------------------------------------------------------------------


@dataclass
class MarketSnapshot:
    symbol: str
    timestamp: float
    bid: float
    ask: float
    spread: float
    high: float
    low: float
    close: float
    open: float
    volume: float


@dataclass
class Candle:
    symbol: str
    timeframe: str
    time: float
    open: float
    high: float
    low: float
    close: float
    volume: float
    tick_volume: float

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def is_bullish(self) -> bool:
        return self.close >= self.open

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        return min(self.open, self.close) - self.low


# ---------------------------------------------------------------------------
# Regime
# ---------------------------------------------------------------------------

@dataclass
class RegimeSnapshot:
    snapshot_id: str
    timestamp: float
    symbol: str
    trend: TrendDirection
    structure: MarketStructure
    volatility: VolatilityRegime
    session: TradingSession
    liquidity: LiquidityState
    confidence: float = 0.5
    metadata: Dict[str, AnyType] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, AnyType]:
        return {
            "snapshot_id": self.snapshot_id,
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "trend": self.trend.value,
            "structure": self.structure.value,
            "volatility": self.volatility.value,
            "session": self.session.value,
            "liquidity": self.liquidity.value,
            "confidence": self.confidence,
            "metadata": self.metadata,
        }
