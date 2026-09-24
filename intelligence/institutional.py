"""Institutional flow engine: smart-money footprints on the CURRENT bar.

Drives the runtime (paper/live) decision path with deterministic
institutional-imbalance logic instead of an LLM or hindsight analysis:

  * Liquidity pools are clustered from the most recent lows/highs.
  * A RAID is a sweep of a pool in the current bar (wick or live tick
    through the level) that closes/closes back inside -> the institution
    has taken the resting liquidity, revealing its intention:
        - sell-side pool swept and price recovers  -> LONG intention
        - buy-side pool swept and price backs away  -> SHORT intention
  * ABSORPTION upgrades a raid when the bar fights at the level with
    heavy effort (volume) yet a small body: a real footprint, not noise.
  * VACUUM downgrades it: a sweep on thin effort is low-conviction.

Everything is deterministic (no randomness, no blocking) and auditable via
the `narrative` on each read.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from statistics import median
from typing import Dict, List, Optional, Sequence

from core.contracts import Candle, TradeDirection, TrendDirection
from core.logging import get_logger

from .targets import TargetLevel, build_target_ladder

log = get_logger("intelligence.institutional")

MIN_BARS = 12
POOL_LOOKBACK = 40
POOL_TOL_RATIO = 0.001      # cluster tolerance as a fraction of price
ABSORPTION_EFFORT = 1.5     # effort multiplier vs the recent baseline
VACUUM_EFFORT = 0.6         # below this, a raid is thin
MAX_BODY_RATIO = 0.45       # a "fighting" bar has a small body vs its range


@dataclass
class PoolCluster:
    """A clustered liquidity level (equal lows or highs)."""
    kind: str                  # "sellside" (below) | "buyside" (above)
    level: float
    touches: int
    index: int                 # candle index of the most recent touch


@dataclass
class InstitutionalEvent:
    """One smart-money footprint detected on the current bar."""
    kind: str                       # buy_side_raid | sell_side_raid |
                                    # absorption | vacuum_raid
    pool_type: str                  # sellside | buyside
    pool_level: float
    reached: float                  # actual extreme of the sweep
    direction: TradeDirection
    strength: float                 # 0..1
    depth: float                    # |swept distance|
    close_back: bool
    live: bool                      # confirmed from the live tick
    effort_ratio: float             # vs recent baseline
    touches: int
    narrative: str

    def as_dict(self) -> Dict[str, float]:
        return {
            "kind": self.kind,
            "pool_type": self.pool_type,
            "pool_level": round(self.pool_level, 5),
            "reached": round(self.reached, 5),
            "direction": self.direction.value,
            "strength": round(self.strength, 3),
            "depth": round(self.depth, 5),
            "close_back": self.close_back,
            "live": self.live,
            "effort_ratio": round(self.effort_ratio, 2),
            "touches": self.touches,
            "narrative": self.narrative,
        }


@dataclass
class InstitutionalRead:
    """Verdict of the institutional-flow analysis for the current bar."""
    symbol: str
    timestamp: float
    trend: TrendDirection
    live_price: Optional[float]
    events: List[InstitutionalEvent] = field(default_factory=list)
    verdict_direction: TradeDirection = TradeDirection.FLAT
    strength: float = 0.0
    target_above: Optional[float] = None
    target_below: Optional[float] = None
    buy_pools: List[PoolCluster] = field(default_factory=list)
    sell_pools: List[PoolCluster] = field(default_factory=list)
    ladder: List[TargetLevel] = field(default_factory=list)
    narrative: str = ""

    @property
    def flat(self) -> bool:
        return self.verdict_direction == TradeDirection.FLAT

    def best(self) -> Optional[InstitutionalEvent]:
        if not self.events:
            return None
        return max(self.events, key=lambda e: e.strength)

    def as_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "trend": self.trend.value,
            "live_price": self.live_price,
            "events": [e.as_dict() for e in self.events],
            "verdict_direction": self.verdict_direction.value,
            "strength": round(self.strength, 3),
            "target_above": self.target_above,
            "target_below": self.target_below,
            "ladder": [l.as_dict() for l in self.ladder],
            "narrative": self.narrative,
        }


def _find_pools(candles: Sequence[Candle],
                lookback: int = POOL_LOOKBACK) -> List[PoolCluster]:
    """Cluster recent lows/highs into resting-liquidity levels."""
    window = list(candles[-lookback:])
    if not window:
        return []
    price = window[-1].close
    tol = max(POOL_TOL_RATIO * price, 1e-9)

    pools: List[PoolCluster] = []
    for attr, kind in (("low", "sellside"), ("high", "buyside")):
        values = sorted((getattr(c, attr), i) for i, c in enumerate(window))
        i = 0
        while i < len(values):
            j = i
            group = [values[i]]
            while j + 1 < len(values) and abs(values[j + 1][0] - values[i][0]) <= tol:
                j += 1
                group.append(values[j])
            if len(group) >= 2:
                level = median(v for v, _ in group)
                pools.append(PoolCluster(
                    kind=kind, level=level, touches=len(group),
                    index=group[-1][1]))
            i = j + 1
    return pools


def _effort(bar: Candle) -> Optional[float]:
    """Tick-volume per point of range; None when the bar is flat."""
    if bar.range <= 0 or bar.tick_volume <= 0:
        return None
    return bar.tick_volume / bar.range


def _baseline_effort(candles: Sequence[Candle]) -> float:
    """Median effort over the bars before the current one."""
    samples = []
    for bar in candles[-11:-1]:
        e = _effort(bar)
        if e is not None:
            samples.append(e)
    return median(samples) if samples else 1.0


class InstitutionalFlow:
    """Per-bar institutional-footprint analysis (deterministic)."""

    def analyze(self, candles: Sequence[Candle], symbol: str,
                current_price: Optional[float] = None) -> InstitutionalRead:
        ts = time.time()
        if len(candles) < MIN_BARS:
            return InstitutionalRead(symbol=symbol, timestamp=ts,
                                     trend=TrendDirection.SIDEWAYS,
                                     live_price=current_price)
        from intelligence.smc import analyze as smc_analyze
        context = smc_analyze(candles, symbol)
        trend = context.trend
        last = candles[-1]
        price = current_price if current_price is not None else last.close

        pools = _find_pools(candles)
        sell_pools = [p for p in pools if p.kind == "sellside" and p.level <= price]
        buy_pools = [p for p in pools if p.kind == "buyside" and p.level >= price]
        sell_pools.sort(key=lambda p: abs(p.level - price))
        buy_pools.sort(key=lambda p: abs(p.level - price))

        base = _baseline_effort(candles)
        last_effort = _effort(last)
        effort_ratio = (last_effort / base) if last_effort and base else 1.0
        body_ratio = (last.body / last.range) if last.range > 0 else 1.0

        events: List[InstitutionalEvent] = []
        if last.low <= price and sell_pools and last.low <= sell_pools[0].level:
            pool = sell_pools[0]
            depth = pool.level - last.low
            close_back = price > pool.level
            if close_back:
                events.append(self._event(
                    pool, "sellside", "LONG", TradeDirection.LONG, last,
                    depth, close_back, price, effort_ratio, body_ratio))
        if last.high >= price and buy_pools and last.high >= buy_pools[0].level:
            pool = buy_pools[0]
            depth = last.high - pool.level
            close_back = price < pool.level
            if close_back:
                events.append(self._event(
                    pool, "buyside", "SHORT", TradeDirection.SHORT, last,
                    depth, close_back, price, effort_ratio, body_ratio))

        read = InstitutionalRead(
            symbol=symbol, timestamp=ts, trend=trend, live_price=current_price,
            events=events,
            target_above=min((p.level for p in buy_pools), default=None),
            target_below=max((p.level for p in sell_pools), default=None),
            buy_pools=buy_pools, sell_pools=sell_pools,
        )
        best = read.best()
        if best is not None:
            read.verdict_direction = best.direction
            read.strength = best.strength
            read.ladder = build_target_ladder(
                candles, pools, best.direction, price)
            read.narrative = (f"{best.kind} at {best.pool_level:.5f} "
                              f"({best.pool_type}); intention "
                              f"{best.direction.value} "
                              f"[depth={best.depth:.5f}, "
                              f"effort={effort_ratio:.2f}x] "
                              f"trend={trend.value}")
            log.debug(f"{symbol}: {read.narrative}")
        return read

    def _event(self, pool: PoolCluster, pool_type: str, tag: str,
               direction: TradeDirection, last: Candle, depth: float,
               close_back: bool, price: float, effort_ratio: float,
               body_ratio: float) -> InstitutionalEvent:
        # Classify the footprint of the raid bar.
        if effort_ratio >= ABSORPTION_EFFORT and body_ratio <= MAX_BODY_RATIO:
            kind, kind_mult = "absorption", 1.0
        elif effort_ratio <= VACUUM_EFFORT:
            kind, kind_mult = "vacuum_raid", 0.4
        else:
            kind, kind_mult = f"{pool_type}_raid", 0.8

        strength = min(1.0, (pool.touches / 3.0) * kind_mult * 0.9)
        return InstitutionalEvent(
            kind=kind, pool_type=pool_type, pool_level=pool.level,
            reached=(last.low if direction == TradeDirection.LONG else last.high),
            direction=direction, strength=strength, depth=depth,
            close_back=close_back,
            live=(price != last.close),
            effort_ratio=round(effort_ratio, 2), touches=pool.touches,
            narrative=f"{tag} raid of {pool_type} pool @ {pool.level:.5f}",
        )


institutional_flow = InstitutionalFlow()
