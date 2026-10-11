"""Research Queue domain (RMI-01, row 749).

The most important part of the RMI Factory per the operator: the AI does NOT
pick at random what to research. Every problem enters the **research queue** as
a scored, durable row (priority, expected value, data availability, research
cost, risk, novelty, reproducibility), and the lab works it top-down -- first
on whatever is worth the cost of research (MASTER_ARCHITECTURE s9, RMI phase
6).

The service adds the domain vocabulary over `ResearchQueueRepository`: batch
enqueue with per-candidate receipts (the same philosophy as the EvidenceIntake
bus -- one bad candidate never kills a burst), scored reads, the lifecycle
`queued -> active -> completed | queued -> superseded`, and the evidence
lineage enrichment: a grounded queue item's reads resolve its cited evidence
and report `backed_trust`, never inventing it. Everything stays
`is_authorisation: False` and names the Risk Governor.
"""

from typing import Any, Dict, List, Optional

from persistence.repositories_accounts import (
    ResearchQueueRepository,
)
from research.evidence_plane import (
    EvidencePlaneService,
    IS_AUTHORISATION,
    TRADE_AUTHORITY,
)
from research.queue.priority import ResearchPriorityScorer


def _enrich(item: Dict[str, Any],
            index: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    cited = [e for e in item.get("evidence_ids", []) if e]
    resolved = [index[e] for e in cited if e in index]
    missing = [e for e in cited if e not in index]
    backed = max((r["trust_ladder"] for r in resolved), default=None)
    return {**item,
            "evidence_lineage": resolved,
            "evidence_ids_not_found": missing,
            "backed_trust": backed,
            "is_authorisation": IS_AUTHORISATION,
            "trade_authority": TRADE_AUTHORITY}


class ResearchQueueService:
    """Scored problem ledger with evidence-grounded reads."""

    def __init__(self,
                 repo: Optional[ResearchQueueRepository] = None,
                 plane: Optional[EvidencePlaneService] = None) -> None:
        self._repo = repo or ResearchQueueRepository()
        self._plane = plane or EvidencePlaneService()

    def _index(self) -> Dict[str, Dict[str, Any]]:
        return {row["evidence_id"]: row for row in self._plane.list_all()}

    def enqueue(self, *, problem: str,
                expected_value: float = 0.0,
                data_availability: float = 0.0,
                research_cost: float = 0.0, risk: float = 0.0,
                novelty: float = 0.0, reproducibility: float = 0.0,
                evidence_ids: Optional[List[str]] = None,
                note: str = "") -> Dict[str, Any]:
        row = self._repo.enqueue(
            problem=problem, expected_value=expected_value,
            data_availability=data_availability, research_cost=research_cost,
            risk=risk, novelty=novelty, reproducibility=reproducibility,
            evidence_ids=evidence_ids, note=note)
        return _enrich(row, self._index())

    def enqueue_batch(self, candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Enqueue many candidate research problems with per-item receipts.

        One bad candidate (a missing problem, an out-of-range dimension, a
        ghost evidence id) is refused with its reason and never kills the rest
        of the burst (same contract as the EvidenceIntakeBus, row 747).
        """
        receipts = []
        accepted = 0
        for candidate in candidates:
            if not isinstance(candidate, dict):
                receipts.append({
                    "accepted": False, "reason": "not_an_object",
                    "problem": ""})
                continue
            problem = str(candidate.get("problem", "")).strip()
            try:
                row = self.enqueue(
                    problem=problem,
                    expected_value=candidate.get("expected_value", 0.0),
                    data_availability=candidate.get("data_availability", 0.0),
                    research_cost=candidate.get("research_cost", 0.0),
                    risk=candidate.get("risk", 0.0),
                    novelty=candidate.get("novelty", 0.0),
                    reproducibility=candidate.get("reproducibility", 0.0),
                    evidence_ids=candidate.get("evidence_ids"),
                    note=candidate.get("note", ""))
                accepted += 1
                receipts.append({
                    "accepted": True, "reason": "enqueued",
                    "problem": problem, "item_id": row["item_id"],
                    "priority_score": row["priority_score"],
                    "priority_label": row["priority_label"]})
            except ValueError as exc:
                receipts.append({
                    "accepted": False, "reason": str(exc), "problem": problem})
        return {
            "accepted": accepted,
            "refused": len(candidates) - accepted,
            "receipts": receipts,
            "total": len(candidates),
            "is_authorisation": IS_AUTHORISATION,
            "trade_authority": TRADE_AUTHORITY,
        }

    def get(self, item_id: str) -> Optional[Dict[str, Any]]:
        row = self._repo.get(item_id)
        if row is None:
            return None
        return _enrich(row, self._index())

    def list_all(self, *, status: str = "", limit: int = 10_000) -> List[Dict[str, Any]]:
        index = self._index()
        rows = self._repo.list_all(status=status, limit=limit)
        return [_enrich(r, index) for r in rows]

    def start(self, item_id: str) -> Dict[str, Any]:
        return _enrich(self._repo.transition(item_id, "active"), self._index())

    def complete(self, item_id: str) -> Dict[str, Any]:
        return _enrich(self._repo.transition(item_id, "completed"),
                       self._index())

    def supersede(self, item_id: str) -> Dict[str, Any]:
        return _enrich(self._repo.transition(item_id, "superseded"),
                       self._index())

    def summary(self) -> Dict[str, Any]:
        s = self._repo.summary()
        return {**s, "dimension_weights": dict(ResearchPriorityScorer.WEIGHTS),
                "is_authorisation": IS_AUTHORISATION,
                "trade_authority": TRADE_AUTHORITY}
