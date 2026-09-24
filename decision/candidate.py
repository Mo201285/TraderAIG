"""Candidate Board: ranks trade candidates and handles approval flow."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import List, Optional

from core.events import Event, EventType, bus
from core.logging import get_logger
from decision.thesis import Thesis, TradeCandidate


log = get_logger("decision.candidate")


class CandidateStatus(str):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    EXPIRED = "expired"


@dataclass
class CandidateBoard:
    """Tracks candidates and applies portfolio-fit scoring."""

    max_open_candidates: int = 5
    _candidates: List[TradeCandidate] = field(default_factory=list)

    def add_candidate(self, thesis: Thesis, prior=None) -> TradeCandidate:
        """Create a candidate from a thesis, sized by a default risk unit.

        `prior` (optional) is a PriorEdge from the Strategy Lab: when present
        and validation-cleared, its conditional edge is blended into the
        priority score and its provenance (strategy_id / stage) is attached to
        the candidate so the Risk Governor can gate live usage by stage (M8.3).
        """
        entry = sum(thesis.entry_zone) / len(thesis.entry_zone)
        candidate = TradeCandidate(
            candidate_id=str(uuid.uuid4()),
            thesis_id=thesis.thesis_id,
            symbol=thesis.symbol,
            direction=thesis.direction,
            entry=entry,
            stop_loss=thesis.stop_loss,
            take_profit=thesis.take_profit[0] if thesis.take_profit else entry,
            size=0.01,  # base size; risk governor adjusts
            risk_reward=thesis.risk_reward,
            confidence=thesis.confidence,
            priority=self._score_priority(thesis, prior),
        )
        if prior is not None:
            candidate.strategy_id = getattr(prior, "strategy_id", None)
            candidate.strategy_stage = getattr(prior, "stage", None)
            candidate.strategy_edge = prior.as_dict() if hasattr(prior, "as_dict") else None
        self._candidates.append(candidate)

        bus.emit(Event(
            type=EventType.CANDIDATE_SELECTED,
            source="decision.candidate",
            payload={"candidate": candidate.as_dict()},
        ))
        log.info(f"New candidate {candidate.candidate_id[:8]} {candidate.symbol} "
                 f"{candidate.direction.value} priority={candidate.priority}")
        return candidate

    def list_open_candidates(self) -> List[TradeCandidate]:
        return [c for c in self._candidates if c.status == CandidateStatus.PENDING]

    def approve(self, candidate_id: str) -> Optional[TradeCandidate]:
        candidate = _find(self._candidates, candidate_id)
        if candidate is None:
            log.warning(f"approve() unknown candidate {candidate_id}")
            return None
        candidate.status = CandidateStatus.APPROVED
        log.info(f"Candidate {candidate_id[:8]} approved")
        return candidate

    def reject(self, candidate_id: str, reason: str = "unspecified") -> None:
        candidate = _find(self._candidates, candidate_id)
        if candidate is None:
            return
        candidate.status = CandidateStatus.REJECTED
        log.info(f"Candidate {candidate_id[:8]} rejected ({reason})")

    def expire_stale(self, max_age_seconds: float = 6 * 3600) -> int:
        now = time.time()
        expired = 0
        for c in self._candidates:
            if c.status == CandidateStatus.PENDING and now - c.created_at > max_age_seconds:
                c.status = CandidateStatus.EXPIRED
                expired += 1
        return expired

    def _score_priority(self, thesis: Thesis, prior=None) -> int:
        """0..100; higher = more attractive.

        Base score is confidence + R:R. When a validated prior matches the
        thesis, the conditional edge is blended in: a positive edge lifts the
        priority (proven setup), a negative/zero edge caps it (abstain). The
        blend is deliberately modest so live evidence still dominates.
        """
        score = thesis.confidence * 100 + thesis.risk_reward * 5
        if prior is not None:
            edge = getattr(prior, "edge_for", None)
            cond = float(edge(thesis.regime_snapshot.get("regime_key")
                              if isinstance(thesis.regime_snapshot, dict) else None,
                              None) if edge else 0.0)
            # R units -> points (cap contribution at +/- 10).
            score += max(-10.0, min(10.0, cond * 10.0))
            if getattr(prior, "is_live_eligible", False):
                score += 2.0
        return min(100, int(score))


def _find(candidates: List[TradeCandidate], candidate_id: str) -> Optional[TradeCandidate]:
    return next((c for c in candidates if c.candidate_id == candidate_id), None)


candidate_board = CandidateBoard()
