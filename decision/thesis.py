"""Investment Decision Core: thesis construction and candidate selection.

The ThesisEngine turns evidence into documented hypotheses. The
CandidateBoard ranks candidates by priority and produces the
TradeCandidate objects the Risk Governor must approve.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from core.contracts import (
    Candle,
    ThesisStatus,
    TradeDirection,
)
from core.events import Event, EventType, bus
from core.logging import get_logger
from intelligence.evidence import EvidenceSet


log = get_logger("decision")


@dataclass
class Thesis:
    thesis_id: str
    timestamp: float
    symbol: str
    direction: TradeDirection
    entry_zone: List[float]
    stop_loss: float
    take_profit: List[float]
    invalidation: List[float]
    confidence: float
    risk_reward: float
    status: ThesisStatus = ThesisStatus.PENDING
    evidence_ids: List[str] = field(default_factory=list)
    regime_snapshot: Optional[Dict] = None

    def as_dict(self) -> Dict:
        return {
            "thesis_id": self.thesis_id,
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "direction": self.direction.value,
            "entry_zone": self.entry_zone,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "invalidation": self.invalidation,
            "confidence": self.confidence,
            "risk_reward": self.risk_reward,
            "status": self.status.value,
            "evidence_ids": self.evidence_ids,
        }


@dataclass
class TradeCandidate:
    candidate_id: str
    thesis_id: str
    symbol: str
    direction: TradeDirection
    entry: float
    stop_loss: float
    take_profit: float
    size: float
    risk_reward: float
    confidence: float
    priority: int = 0
    status: str = "pending"
    created_at: float = field(default_factory=time.time)
    # Validated-prior linkage (M8.1/M8.2): set when the candidate resolves a
    # promotion-cleared strategy edge; the Risk Governor then gates live usage
    # by the recorded stage (M8.3).
    strategy_id: Optional[str] = None
    strategy_stage: Optional[str] = None
    strategy_edge: Optional[Dict] = None

    def as_dict(self) -> Dict:
        return {
            "candidate_id": self.candidate_id,
            "thesis_id": self.thesis_id,
            "symbol": self.symbol,
            "direction": self.direction.value,
            "entry": self.entry,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "size": self.size,
            "risk_reward": self.risk_reward,
            "confidence": self.confidence,
            "priority": self.priority,
            "status": self.status,
            "created_at": self.created_at,
            "strategy_id": self.strategy_id,
            "strategy_stage": self.strategy_stage,
            "strategy_edge": self.strategy_edge,
        }


class ThesisEngine:
    """Builds hypotheses from evidence, with explicit entry/exit/invalidation."""

    def __init__(self, atr_multiplier_entry: float = 0.3,
                 atr_multiplier_sl: float = 1.0,
                 min_rr: float = 1.2,
                 min_confluence: float = 0.4) -> None:
        self.atr_multiplier_entry = atr_multiplier_entry
        self.atr_multiplier_sl = atr_multiplier_sl
        self.min_rr = min_rr
        self.min_confluence = min_confluence
        self._theses: List[Thesis] = []

    def build_thesis(self, evidence: EvidenceSet, candles: Sequence[Candle],
                     symbol: str) -> Optional[Thesis]:
        direction = evidence.dominant_direction()
        if direction == TradeDirection.FLAT:
            log.info(f"{symbol}: no dominant direction; skip thesis")
            return None
        if evidence.confluence_score < self.min_confluence:
            log.info(f"{symbol}: confluence {evidence.confluence_score:.2f} below "
                     f"threshold {self.min_confluence}; skip")
            return None

        atr = self._average_true_range(candles)
        if atr <= 0:
            log.warning(f"{symbol}: ATR is zero; cannot build thesis")
            return None

        price = candles[-1].close

        if direction == TradeDirection.LONG:
            entry_low = price - atr * self.atr_multiplier_entry
            entry_high = price
            sl = price - atr * self.atr_multiplier_sl
            tp1, tp2 = self._targets_long(candles[-1].high, atr)
        else:
            entry_low = price
            entry_high = price + atr * self.atr_multiplier_entry
            sl = price + atr * self.atr_multiplier_sl
            tp1, tp2 = self._targets_short(candles[-1].low, atr)

        rr = self._risk_reward(sl, tp1, price, direction)
        if rr < self.min_rr:
            log.info(f"{symbol}: R:R {rr:.2f} below limit {self.min_rr}; skip")
            return None

        invalidation_zone = self._invalidation(sl, price, atr, direction)

        thesis = Thesis(
            thesis_id=str(uuid.uuid4()),
            timestamp=time.time(),
            symbol=symbol,
            direction=direction,
            entry_zone=[round(entry_low, 5), round(entry_high, 5)],
            stop_loss=round(sl, 5),
            take_profit=[round(tp1, 5), round(tp2, 5)],
            invalidation=[round(invalidation_zone, 5)],
            confidence=evidence.confluence_score,
            risk_reward=rr,
            status=ThesisStatus.ACTIVE,
            evidence_ids=[evidence.evidence_id],
        )
        self._theses.append(thesis)

        bus.emit(Event(
            type=EventType.THESIS_CONSTRUCTED,
            source="decision.thesis",
            payload={"thesis": thesis.as_dict()},
        ))
        log.info(f"{symbol}: thesis {thesis.thesis_id[:8]} {direction.value} "
                 f"RR={rr:.2f} conf={thesis.confidence:.2f}")
        return thesis

    # -- helpers --------------------------------------------------------
    def _average_true_range(self, candles: Sequence[Candle], period: int = 14) -> float:
        if len(candles) < 2:
            return 0.0
        trs: List[float] = []
        for i in range(1, len(candles)):
            today = candles[i]
            prev = candles[i - 1]
            tr = max(
                today.high - today.low,
                abs(today.high - prev.close),
                abs(today.low - prev.close),
            )
            trs.append(tr)
        if not trs:
            return 0.0
        window = trs[-period:]
        return sum(window) / len(window)

    def _targets_long(self, recent_high: float, atr: float) -> tuple[float, float]:
        return recent_high + atr * 1.0, recent_high + atr * 2.0

    def _targets_short(self, recent_low: float, atr: float) -> tuple[float, float]:
        return recent_low - atr * 1.0, recent_low - atr * 2.0

    def _risk_reward(self, sl: float, tp1: float, price: float,
                     direction: TradeDirection) -> float:
        if direction == TradeDirection.LONG:
            risk = price - sl
            reward = tp1 - price
        else:
            risk = sl - price
            reward = price - tp1
        if risk <= 0:
            return 0.0
        return reward / risk

    def _invalidation(self, sl: float, price: float, atr: float,
                      direction: TradeDirection) -> float:
        if direction == TradeDirection.LONG:
            # Any close below SL * (1 - buffer) invalidates the thesis.
            return sl - atr * 0.15
        return sl + atr * 0.15


thesis_engine = ThesisEngine()
