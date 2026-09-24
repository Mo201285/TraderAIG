"""CONTEXT CLASSIFIER (context gateway for execution pipelines).

Classifies the candle buffer into a cheap runtime ContextSnapshot used by
the trading loops: SMC evidence + spread/volume context + an optional
user-level risk policy override. Deterministic and never blocks the
trading path.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence

from core.contracts import Candle
from core.logging import get_logger
from intelligence.smc import SMCEvidence, analyze


log = get_logger("intelligence.context")


@dataclass
class ContextSnapshot:
    """Cheap classified context handed to the execution pipeline."""

    symbol: str
    timeframe: str
    timestamp: float
    candles: int
    spread: float
    volume_tick: float
    evidence: Optional[SMCEvidence]
    user_policy: Optional[Any] = None

    def as_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "timestamp": self.timestamp,
            "candles": self.candles,
            "spread": self.spread,
            "volume_tick": self.volume_tick,
            "evidence": self.evidence.as_dict() if self.evidence else None,
            "user_policy": self.user_policy,
        }


class ContextClassifier:
    """Classify the current candle buffer into a ContextSnapshot."""

    def __init__(self, user_policy: Optional[Any] = None) -> None:
        self.user_policy = user_policy

    def classify(self, candles: Sequence[Candle], spread: float = 0.0,
                 volume_tick: float = 0.0,
                 symbol: Optional[str] = None,
                 timeframe: Optional[str] = None) -> ContextSnapshot:
        win = list(candles)
        sym = symbol or (win[-1].symbol if win else "XAUUSD")
        tf = timeframe or (win[-1].timeframe if win else "M15")
        evidence = analyze(win, sym, tf) if win else None
        snap = ContextSnapshot(
            symbol=sym, timeframe=tf, timestamp=time.time(),
            candles=len(win), spread=spread, volume_tick=volume_tick,
            evidence=evidence, user_policy=self.user_policy,
        )
        log.debug(f"{sym} context: {len(win)} candles, "
                  f"trend={evidence.trend.value if evidence else 'n/a'}")
        return snap


context_classifier = ContextClassifier()
