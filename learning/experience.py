"""Learning & Evolution Core: Experience Ledger + outcome classification.

Records every decision and its outcome. Error classification lives inline on
``ExperienceRecord.classify()`` (the taxonomy in ``ErrorType``); the dead
wrapper ``ErrorClassifier``/module ``ReplayEngine`` were removed (L4 appendix
B) - nothing consumed them while the research lab keeps its own ReplayEngine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

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
    # The broker answered and refused the order ("Invalid stops", "Market
    # closed"). Distinct from RISK_ERROR (the idea was refused before it
    # reached the venue) and from OPERATIONAL_ERROR (nothing was tried).
    VENUE_REJECTION = "venue_rejection"
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
    owner_user_id: str = ""

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


_current_owner_provider: Optional[Callable[[], Optional[str]]] = None
_default_owner_provider: Optional[Callable[[], Optional[str]]] = None


def set_current_owner_provider(
        provider: Optional[Callable[[], Optional[str]]]) -> None:
    """Wire the tenant of the request that is writing (slice I3).

    Called once by the API layer with `owner_scope`, so a record produced while
    serving a tenant is stamped with that tenant's id no matter which module
    built it. Off-request (the 24/7 pipeline) it resolves to the default
    tenant, which is who owns the box's spontaneous trades.
    """
    global _current_owner_provider
    _current_owner_provider = provider


def set_default_owner_provider(
        provider: Optional[Callable[[], Optional[str]]]) -> None:
    """Wire who owns rows that carry no owner.

    Every record written before multi-tenancy has an empty `owner_user_id`. It
    is not a tenant-less record: it is the default tenant's history, and hiding
    it the moment partitioning lands would look like data loss. Only the
    default tenant may claim those rows.
    """
    global _default_owner_provider
    _default_owner_provider = provider


def _resolve(provider: Optional[Callable[[], Optional[str]]]) -> Optional[str]:
    if provider is None:
        return None
    try:
        return provider()
    except Exception:  # noqa: BLE001
        # A provider that raises must not break a write or a read: fall back to
        # "no owner known", which is the pre-partition behaviour.
        return None


def _current_owner() -> Optional[str]:
    return _resolve(_current_owner_provider)


def _default_owner() -> Optional[str]:
    return _resolve(_default_owner_provider)


class ExperienceLedger:
    """Append-only store of ExperienceRecords, keyed by `record_id`.

    Records are never deleted, but they are not duplicated either: a record_id
    identifies one fact, so re-recording it updates the entry instead of
    appending a copy. The MT5 history sync re-reads the same closed deals every
    cycle, and without this rule the in-memory ledger grew a copy of every deal
    per cycle while the database (which upserts by the same id) stayed clean --
    invisible in storage, and loud only in the surfaces that read memory:
    /mt5/history showed 27k rows for 47 deals, and execution "closes / realized
    PnL" summed the same fill hundreds of times.
    """

    def __init__(self) -> None:
        self._records: List[ExperienceRecord] = []
        self._by_owner: Dict[str, List[ExperienceRecord]] = {}
        self._by_id: Dict[str, ExperienceRecord] = {}

    def clear(self) -> None:
        """Drop the in-memory mirror (a fresh run/replay, never the database).

        Resets must come through here rather than assigning `_records`: the
        id index has to be dropped with the list, or the next `record()` of an
        id that was just cleared would "update" an entry no longer in the
        store and the caller would see nothing at all.
        """
        self._records = []
        self._by_owner.clear()
        self._by_id.clear()

    def record(self, record: ExperienceRecord) -> bool:
        """Store one record; True when it is new, False when it updated one.

        Replay is normal (history re-reads, retried writes), so the caller can
        use the return value to count *new* experiences rather than re-counting
        the whole window on every sync cycle.
        """
        if not (getattr(record, "owner_user_id", "") or ""):
            record.owner_user_id = _current_owner() or _default_owner() or ""
        prior = self._by_id.get(record.record_id)
        if prior is not None:
            # Update in place: owner buckets and `all()` snapshots hold this
            # same object, so they must see the newer fact rather than a stale
            # twin nobody will read.
            prior.__dict__.update(record.__dict__)
            self._persist(prior)
            return False
        self._records.append(record)
        self._by_id[record.record_id] = record
        owner = str(record.owner_user_id or "")
        if owner and owner in self._by_owner:
            self._by_owner[owner].append(record)
        self._persist(record)
        log.debug(f"Experience recorded: {record.record_id[:8]} "
                  f"({record.error_classification.value if record.error_classification else 'pending'})")
        return True


    def _matches(self, record: ExperienceRecord, owner: str) -> bool:
        held = str(getattr(record, "owner_user_id", "") or "")
        if held:
            return held == owner
        # No owner means the row predates partitioning: the default tenant's
        # history, and nobody else's.
        return owner == _default_owner()

    def by_candidate(self, candidate_id: str) -> List[ExperienceRecord]:
        return [r for r in self._records if r.candidate_id == candidate_id]

    def all(self) -> List[ExperienceRecord]:
        return list(self._records)

    def list(self, *, owner_user_id: Optional[str] = None) -> List[ExperienceRecord]:
        if not owner_user_id:
            return list(self._records)
        owner = str(owner_user_id)
        source = self._by_owner.get(owner)
        if source is None:
            source = self._records
        return [r for r in source if self._matches(r, owner)]

    def load_from_db(self, limit: int = 500, *,
                     owner_user_id: Optional[str] = None) -> int:
        """Hydrate the in-memory ledger from persistence once (no-op if loaded).

        Returns how many records were loaded (0 when nothing/disabled/already
        loaded).

        With no `owner_user_id` the whole ledger (the default tenant's history)
        is hydrated, exactly as before. With one, only that tenant's rows are
        read and they are kept in their own bucket: a tenant read must never
        replace the shared in-memory ledger with a single tenant's slice, which
        would make every other reader see that one tenant's history.
        """
        owner = str(owner_user_id) if owner_user_id else None
        if owner is None:
            if self._records:
                return 0
        elif owner in self._by_owner:
            return 0
        try:
            from persistence.db import make_live_session, persistence_enabled
            from persistence.repositories import ExperienceRepository

            if not persistence_enabled():
                return 0
            repo = ExperienceRepository(make_live_session())
            if owner is None:
                rows = repo.list(limit)
                self._records = rows
                self._by_id = {r.record_id: r for r in rows}
            elif owner == _default_owner():
                # The default tenant also owns every unowned row, and the repo
                # cannot express "mine or unowned" without that rule leaking
                # upward. Read the table as before and select here instead.
                rows = [r for r in repo.list(limit) if self._matches(r, owner)]
                self._by_owner[owner] = rows
                for r in rows:
                    self._by_id.setdefault(r.record_id, r)
            else:
                rows = repo.list(limit, owner_user_id=owner)
                self._by_owner[owner] = rows
                for r in rows:
                    self._by_id.setdefault(r.record_id, r)
            return len(rows)
        except Exception:  # noqa: BLE001
            # Not the same as "nothing to load": this means the DURABLE ledger
            # could not be read, and the process then runs with an empty
            # learning history while every consumer of it (school board, lab
            # live feed, attribution) reports on that history as if it were
            # complete. Still never raise during boot -- an unreadable ledger
            # must not stop the backend -- but say so instead of returning 0
            # in silence, which is how "durable" stays true on paper while the
            # records are simply not there.
            log.warning(
                "experience ledger hydration failed; running with an empty "
                "in-memory ledger for this process", exc_info=True)
            return 0

    def stats(self, *, owner_user_id: Optional[str] = None) -> Dict[str, int]:
        counts = {}
        for r in self.list(owner_user_id=owner_user_id):
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
            # Never raise: a record that cannot be written must not take down the
            # decision that produced it -- the in-memory ledger still holds it
            # for this process. But it IS a real loss, and at debug it happened
            # invisibly, which is how a durability claim could stay true on paper
            # while rows were being dropped. WARNING makes the drop findable
            # without turning a storage hiccup into an outage.
            log.warning(
                "experience persistence skipped for %s; the record survives in "
                "memory for this process only", record.record_id[:8],
                exc_info=True)


ledger = ExperienceLedger()
