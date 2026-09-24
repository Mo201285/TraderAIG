"""Learning & Evolution Core: Experience Ledger + outcome classification.

Records every decision and its outcome. Error classification lives inline on
``ExperienceRecord.classify()`` (the taxonomy in ``ErrorType``); the dead
wrapper ``ErrorClassifier``/module ``ReplayEngine`` were removed (L4 appendix
B) - nothing consumed them while the research lab keeps its own ReplayEngine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from core.contracts import (
    RegimeSnapshot,
)
from core.logging import get_logger


log = get_logger("learning")


class ErrorType(str, Enum):
    EXPECTED_LOSS = "expected_loss"
    THESIS_ERROR = "thesis_error"
    DATA_ERROR = "data_error"
    EXECUTION_ERROR = "execution_error"
    RISK_ERROR = "risk_error"
    OPERATIONAL_ERROR = "operational_error"
    MODEL_DRIFT = "model_drift"
    UNKNOWN = "unknown"


@dataclass
class MarketSnapshot:
    symbol: str
    timestamp: float
    bid: float
    ask: float
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class ExperienceRecord:
    record_id: str
    decision_id: str
    timestamp: float
    market_snapshot: Optional[MarketSnapshot] = None
    regime: Optional[RegimeSnapshot] = None
    evidence_ids: List[str] = field(default_factory=list)
    thesis_id: Optional[str] = None
    candidate_id: Optional[str] = None
    risk_decision: Optional[Dict] = None
    execution_plan: Optional[Dict] = None
    actual_result: Optional[Dict] = None
    slippage: float = 0.0
    fees: float = 0.0
    delay_ms: float = 0.0
    error_classification: Optional[ErrorType] = None
    lessons: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def classify(self) -> ErrorType:
        """Automatically classify the outcome of this decision."""
        result = self.actual_result or {}
        pnl = result.get("pnl", 0.0)
        slippage = result.get("slippage", 0.0)
        rejection = result.get("rejection_reason")
        filled = result.get("filled", False)

        if rejection:
            return ErrorType.OPERATIONAL_ERROR
        if not filled:
            return ErrorType.EXECUTION_ERROR
        if slippage and slippage > self.slippage * 2:
            return ErrorType.EXECUTION_ERROR
        if pnl < 0:
            # Not necessarily a mistake; Expected Loss covers the normal loss band.
            if pnl < -abs(self._expected_risk()):
                return ErrorType.THESIS_ERROR
            return ErrorType.EXPECTED_LOSS
        return ErrorType.EXPECTED_LOSS

    def _expected_risk(self) -> float:
        if not self.regime:
            return 0.0
        return self.regime.confidence * 100.0 * 0.01  # crude loss proxy

    def as_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "decision_id": self.decision_id,
            "timestamp": self.timestamp,
            "thesis_id": self.thesis_id,
            "candidate_id": self.candidate_id,
            "slippage": self.slippage,
            "fees": self.fees,
            "delay_ms": self.delay_ms,
            "error_classification": self.error_classification.value
            if self.error_classification else None,
            "lessons": self.lessons,
            "actual_result": self.actual_result,
        }


class ExperienceLedger:
    """Append-only store of ExperienceRecords."""

    def __init__(self) -> None:
        self._records: List[ExperienceRecord] = []

    def record(self, record: ExperienceRecord) -> None:
        self._records.append(record)
        self._persist(record)
        log.debug(f"Experience recorded: {record.record_id[:8]} "
                  f"({record.error_classification.value if record.error_classification else 'pending'})")

    def by_candidate(self, candidate_id: str) -> List[ExperienceRecord]:
        return [r for r in self._records if r.candidate_id == candidate_id]

    def all(self) -> List[ExperienceRecord]:
        return list(self._records)

    def load_from_db(self, limit: int = 500) -> int:
        """Hydrate the in-memory ledger from persistence once (no-op if loaded).

        Returns how many records were loaded (0 when nothing/disabled/already loaded).
        """
        if self._records:
            return 0
        try:
            from persistence.db import make_live_session, persistence_enabled
            from persistence.repositories import ExperienceRepository

            if not persistence_enabled():
                return 0
            self._records = ExperienceRepository(make_live_session()).list(limit)
            return len(self._records)
        except Exception:  # noqa: BLE001
            return 0

    def stats(self) -> Dict[str, int]:
        counts = {}
        for r in self._records:
            key = r.error_classification.value if r.error_classification else "unclassified"
            counts[key] = counts.get(key, 0) + 1
        return counts

    def _persist(self, record: ExperienceRecord) -> None:
        try:
            from persistence.db import make_live_session, persistence_enabled
            from persistence.repositories import ExperienceRepository

            if not persistence_enabled():
                return
            session = make_live_session()
            try:
                ExperienceRepository(session).save(record)
            finally:
                session.close()
        except Exception:  # noqa: BLE001
            log.debug(f"Experience persistence skipped for {record.record_id[:8]}")


ledger = ExperienceLedger()
