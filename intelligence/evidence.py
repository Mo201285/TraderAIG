"""Evidence aggregation: combines regime + SMC signals into scored evidence.

The EvidenceAggregator consumes RegimeSnapshots and SMCEvidence output and
produces a scored EvidenceSet that the Thesis Engine can consume.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from core.contracts import (
    Candle,
    MarketStructure,
    RegimeSnapshot,
    TradeDirection,
    TrendDirection,
    VolatilityRegime,
)
from core.events import Event, EventType, bus
from core.logging import get_logger
from intelligence.regime import RegimeEngine, snapshot_to_dict
from intelligence.smc import SMCEvidence, analyze as smc_analyze


log = get_logger("intelligence.evidence")


@dataclass
class Signal:
    name: str
    direction: TradeDirection
    strength: float  # 0..1
    source: str
    details: Dict = field(default_factory=dict)

    def as_dict(self) -> Dict:
        return {
            "name": self.name,
            "direction": self.direction.value,
            "strength": self.strength,
            "source": self.source,
            "details": self.details,
        }


@dataclass
class EvidenceSet:
    evidence_id: str
    timestamp: float
    regime: Optional[RegimeSnapshot] = None
    smc: Optional[SMCEvidence] = None
    signals: List[Signal] = field(default_factory=list)
    confluence_score: float = 0.0
    conflicts: List[str] = field(default_factory=list)

    def dominant_direction(self) -> TradeDirection:
        long_score = sum(s.strength for s in self.signals
                         if s.direction == TradeDirection.LONG)
        short_score = sum(s.strength for s in self.signals
                          if s.direction == TradeDirection.SHORT)
        if long_score > short_score * 1.1:
            return TradeDirection.LONG
        if short_score > long_score * 1.1:
            return TradeDirection.SHORT
        return TradeDirection.FLAT

    def as_dict(self) -> Dict:
        return {
            "evidence_id": self.evidence_id,
            "timestamp": self.timestamp,
            "signals": [s.as_dict() for s in self.signals],
            "confluence_score": self.confluence_score,
            "conflicts": self.conflicts,
            "dominant_direction": self.dominant_direction().value,
            "regime": snapshot_to_dict(self.regime) if self.regime else None,
            "smc": self.smc.as_dict() if self.smc else None,
        }


class EvidenceAggregator:
    """Builds EvidenceSet from regime + SMC, scoring strength of each signal."""

    def __init__(self) -> None:
        self._runs: int = 0
        self._last_evidence: Optional[EvidenceSet] = None

    def evaluate(self, candles: Sequence[Candle], symbol: str,
                 timeframe: str = "M15") -> EvidenceSet:
        self._runs += 1
        regime = RegimeEngine(symbol, timeframe).compute(candles)
        smc_evidence = smc_analyze(candles, symbol, timeframe)

        signals: List[Signal] = []

        # Regime-based signals
        if regime.trend == TrendDirection.BULLISH:
            signals.append(Signal("trend", TradeDirection.LONG, 0.6,
                                  "regime", {"trend": regime.trend.value}))
        elif regime.trend == TrendDirection.BEARISH:
            signals.append(Signal("trend", TradeDirection.SHORT, 0.6,
                                  "regime", {"trend": regime.trend.value}))

        if regime.structure in (MarketStructure.IMPULSE,):
            signals.append(Signal("structure_impulse", TradeDirection.LONG, 0.4,
                                  "regime", {"structure": regime.structure.value}))
        elif regime.structure == MarketStructure.BREAKDOWN:
            signals.append(Signal("structure_breakdown", TradeDirection.SHORT, 0.4,
                                  "regime", {"structure": regime.structure.value}))

        if regime.volatility == VolatilityRegime.LOW:
            signals.append(Signal("low_volatility_setup", TradeDirection.FLAT, 0.3,
                                  "regime", {"volatility": regime.volatility.value}))

        # SMC-based signals (structure breaks & order blocks)
        breaks = smc_evidence.structure_breaks
        if breaks and breaks[-1] in ("break_of_structure", "change_of_character"):
            direction = (
                TradeDirection.LONG if smc_evidence.last_swing and
                smc_evidence.last_swing.type == "high" else TradeDirection.SHORT
            )
            signals.append(Signal("structure_break", direction, 0.5,
                                  "smc", {"break": breaks[-1]}))

        if smc_evidence.last_ob is not None:
            ob_dir = smc_evidence.last_ob.direction
            signals.append(Signal("order_block", ob_dir, 0.5,
                                  "smc", {"ob_top": smc_evidence.last_ob.top,
                                          "ob_bottom": smc_evidence.last_ob.bottom}))

        if smc_evidence.last_fvg is not None and not smc_evidence.last_fvg.filled:
            signals.append(Signal("fvg", TradeDirection.FLAT, 0.3,
                                  "smc", {"fvg": "unmitigated"}))

        # Liquidity pools imply a move toward a pool
        if smc_evidence.liquidity_pools:
            nearest = min(smc_evidence.liquidity_pools,
                          key=lambda z: abs(z.price - candles[-1].close))
            direction = (TradeDirection.SHORT
                         if nearest.zone_type.value in ("equal_high", "prev_high")
                         else TradeDirection.LONG)
            signals.append(Signal("liquidity_pool", direction,
                                  nearest.strength, "smc",
                                  {"pool": nearest.zone_type.value,
                                   "price": nearest.price}))

        # Build evidence
        conflicts = []
        dom = _dominant(signals)
        if dom.is_conflicting(signals):
            conflicts.append("mixed_directions")

        evidence = EvidenceSet(
            evidence_id=str(uuid.uuid4()),
            timestamp=time.time(),
            regime=regime,
            smc=smc_evidence,
            signals=signals,
            conflicts=conflicts,
            confluence_score=_confluence(signals),
        )
        self._last_evidence = evidence

        bus.emit(Event(
            type=EventType.EVIDENCE_GATHERED,
            source="intelligence.evidence",
            payload={"evidence": evidence.as_dict()},
        ))
        log.info(f"Evidence gathered for {symbol}: confluence="
                 f"{evidence.confluence_score:.2f}, dom={dom.direction.value}")
        return evidence


class _Dominance:
    """Tracks directional strength of a signal list."""

    def __init__(self, direction: TradeDirection) -> None:
        self.direction = direction

    def is_conflicting(self, signals: Sequence[Signal]) -> bool:
        seen_long = any(s.direction == TradeDirection.LONG for s in signals)
        seen_short = any(s.direction == TradeDirection.SHORT for s in signals)
        return seen_long and seen_short


def _dominant(signals: Sequence[Signal]) -> _Dominance:
    long_w = sum(s.strength for s in signals if s.direction == TradeDirection.LONG)
    short_w = sum(s.strength for s in signals if s.direction == TradeDirection.SHORT)
    if long_w >= short_w:
        return _Dominance(TradeDirection.LONG)
    return _Dominance(TradeDirection.SHORT)


def _confluence(signals: Sequence[Signal]) -> float:
    """Blend signal strengths into a 0..1 convergence score."""
    if not signals:
        return 0.0
    active = [s for s in signals if s.direction != TradeDirection.FLAT]
    if not active:
        return 0.0
    return min(1.0, sum(s.strength for s in active) / (0.6 * len(active) + 0.1))


aggregator = EvidenceAggregator()
