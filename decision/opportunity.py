"""Opportunity Engine.

Phase B (PROJECT_MAP "Opportunity Engine", 27.10/28.11): an *Opportunity* is
an explicit, durable, fully-evidenced observation that an instrument offers a
tradeable setup. It is NOT a trade: nothing in this module places orders.

The institutional screen (risk governor + capital allocation + live
eligibility) decides whether an opportunity is QUALIFIED, and — when the
operator-confirmation gate is enabled (`TRADERAIG_OPPORTUNITY_GATE=1`) — an
explicit operator decision (approve/reject) is required before the pipeline
executes it on the next bar. With the gate off (default "0") the pipeline
keeps its governed auto-execution exactly as before; the Opportunity board is
recorded either way so the operator can see every setup with its full evidence.

Authority notes (single-authority rule):
  * The Risk Governor remains the hard gate. The screen packages the real
    RiskDecision (its checks + reason) into the dossier; it never invents
    vetoes and never fabricates numbers.
  * `screen()` uses the already-produced RiskDecision so the governor is not
    re-run redundantly in production. A fresh veto (re-run) only happens at
    execution time for operator-approved opportunities, so execution still
    honours *current* market conditions.
"""

from __future__ import annotations

import calendar
import json
import os
import stat
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

from core.logging import get_logger
from core.contracts import TradeDirection
from decision.candidate import TradeCandidate
from risk.governor import RiskDecision, RiskDecisionKind


log = get_logger("decision.opportunity")

# Durable board location (gitignored; decision/data does not belong in VCS).
# `TRADERAIG_OPPORTUNITY_BOARD` overrides it (tests point it at a temp dir).
BOARD_PATH = Path(os.getenv("TRADERAIG_OPPORTUNITY_BOARD", "").strip()
                  or (Path(__file__).resolve().parent / "data" / "opportunities.json"))


class OpportunityStatus(str, Enum):
    SCAN = "scan"
    QUALIFIED = "qualified"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


def opportunity_gate_mode() -> str:
    """Operator-confirmation gate (TRADERAIG_OPPORTUNITY_GATE).

    "" | "0" | "off" | "false"  -> auto (legacy governed auto-execution)
    "1" | "on" | "true"         -> confirm (qualified opportunities wait for
                                   an explicit operator approve/reject)
    """
    value = os.getenv("TRADERAIG_OPPORTUNITY_GATE", "0").strip().lower()
    if value in ("1", "on", "true", "yes"):
        return "confirm"
    if value in ("0", "off", "false", "no", ""):
        return "auto"
    log.warning(f"TRADERAIG_OPPORTUNITY_GATE={value!r} unrecognised; defaulting to auto")
    return "auto"


def _now() -> float:
    return time.time()


def _utc(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


@dataclass
class Opportunity:
    """A screened setup. Immutable-ish; transitions ride the append-only history."""

    opportunity_id: str
    symbol: str
    direction: str
    source: str
    session_key: str
    thesis_id: Optional[str]
    candidate_id: Optional[str]
    strategy_id: Optional[str]
    strategy_stage: Optional[str]
    entry: float
    stop_loss: float
    take_profit: Optional[float]
    size: float
    risk_reward: float
    confidence: float
    priority: int
    score: float
    status: OpportunityStatus = OpportunityStatus.SCAN
    risk_ok: bool = True
    risk_reason: str = "all checks passed"
    allocation_ok: bool = True
    allocation_reason: str = "within portfolio allocation"
    live_eligible: bool = True
    live_eligibility_reason: str = "live allowed, institutional stage"
    screen_reasons: List[str] = field(default_factory=list)
    evidence: Dict = field(default_factory=dict)
    detected_at: float = field(default_factory=_now)
    qualified_at: Optional[float] = None
    approved_at: Optional[float] = None
    executed_at: Optional[float] = None
    ticket_key: Optional[str] = None
    execute_pending: bool = False
    history: List[Dict] = field(default_factory=list)

    def _append(self, status: str, note: str) -> None:
        self.history.append({"ts": _utc(_now()), "status": status, "note": note})

    def qualify(self, note: str = "passed institutional screen") -> None:
        self.qualified_at = _now()
        self.execute_pending = opportunity_gate_mode() == "confirm"
        self._transition(OpportunityStatus.QUALIFIED, note)

    def approve(self, note: str = "operator approved") -> None:
        self.approved_at = _now()
        # Only the operator-confirmation gate queues the pipeline to pick it up
        # on the next bar. Under gate=auto the governor's approval is immediate
        # (the pipeline executes in the same bar), so nothing stays pending.
        self.execute_pending = opportunity_gate_mode() == "confirm"
        self._transition(OpportunityStatus.APPROVED, note)

    def reject(self, note: str) -> None:
        self.execute_pending = False
        self._transition(OpportunityStatus.REJECTED, note)

    def expire(self, note: str = "stale; no longer actionable") -> None:
        self.execute_pending = False
        self._transition(OpportunityStatus.EXPIRED, note)

    def executed(self, ticket_key: str, note: str = "executed by pipeline") -> None:
        self.executed_at = _now()
        self.ticket_key = ticket_key
        self.execute_pending = False
        self._append("executed", note)

    def _transition(self, status: OpportunityStatus, note: str) -> None:
        self.status = status
        self._append(status.value, note)

    def as_dict(self) -> Dict:
        return {
            "opportunity_id": self.opportunity_id,
            "symbol": self.symbol,
            "direction": self.direction,
            "source": self.source,
            "session_key": self.session_key,
            "thesis_id": self.thesis_id,
            "candidate_id": self.candidate_id,
            "strategy_id": self.strategy_id,
            "strategy_stage": self.strategy_stage,
            "entry": self.entry,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "size": self.size,
            "risk_reward": self.risk_reward,
            "confidence": self.confidence,
            "priority": self.priority,
            "score": self.score,
            "status": self.status.value,
            "risk_ok": self.risk_ok,
            "risk_reason": self.risk_reason,
            "allocation_ok": self.allocation_ok,
            "allocation_reason": self.allocation_reason,
            "live_eligible": self.live_eligible,
            "live_eligibility_reason": self.live_eligibility_reason,
            "screen_reasons": self.screen_reasons,
            "evidence": self.evidence,
            "detected_at": _utc(self.detected_at),
            "qualified_at": _utc(self.qualified_at) if self.qualified_at else None,
            "approved_at": _utc(self.approved_at) if self.approved_at else None,
            "executed_at": _utc(self.executed_at) if self.executed_at else None,
            "ticket_key": self.ticket_key,
            "execute_pending": self.execute_pending,
            "history": self.history,
        }


@dataclass
class OpportunityBoard:
    """Durable, append-only board of opportunities (JSON file, atomic replace)."""

    path: Path = BOARD_PATH
    _lock: threading.RLock = field(default_factory=threading.RLock)
    _opportunities: Dict[str, Opportunity] = field(default_factory=dict)

    # The board is an operator observation window, not the audit trail (the
    # identity audit log and the decision ledger own that). Two properties
    # keep it cheap on a per-candle path:
    #   * bounded entries (a full rewrite stays small), and
    #   * debounced persistence (screened setups batch their write; operator
    #     decisions flush immediately because they are governed decisions).
    _MAX_ENTRIES = 250
    _SAVE_DEBOUNCE_S = 2.0

    def __post_init__(self) -> None:
        self._dirty = False
        self._last_saved = 0.0
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            for item in raw.get("opportunities", []):
                opp = self._from_dict(item)
                self._opportunities[opp.opportunity_id] = opp
            self._prune()
        except Exception as exc:  # never brick the engine on a bad board
            log.error(f"opportunity board unreadable ({self.path}): {exc}")

    def _prune(self) -> None:
        if len(self._opportunities) <= self._MAX_ENTRIES:
            return
        # Keep the newest MAX entries. Ties on `detected_at` (coarse clocks make
        # several records share one stamp) must break by insertion order, not by
        # dict/hash order — a stable sort on the insertion-ordered list does
        # exactly that, so the last-added record is never the one dropped.
        newest_first = sorted(
            enumerate(self._opportunities.values()),
            key=lambda pair: (pair[1].detected_at, pair[0]),
            reverse=True)
        keep = {o.opportunity_id for _, o in newest_first[:self._MAX_ENTRIES]}
        self._opportunities = {
            k: v for k, v in self._opportunities.items() if k in keep}

    def _save(self) -> None:
        """Persist the board. A durable-write failure is a warning, never an
        exception: the trading path must not break on disk IO."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": 1,
                "updated_at": _utc(_now()),
                "opportunities": [o.as_dict() for o in self._opportunities.values()],
            }
            fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(payload, fh, ensure_ascii=False, indent=2)
                os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
                os.replace(tmp, self.path)
            except Exception:
                if os.path.exists(tmp):
                    os.unlink(tmp)
                raise
            self._dirty = False
            self._last_saved = time.monotonic()
        except Exception as exc:  # noqa: BLE001
            log.warning(f"opportunity board save failed ({self.path}): {exc}")

    def flush(self) -> None:
        """Force a durable write (used when a governed decision touched it)."""
        with self._lock:
            if self._opportunities or self._dirty:
                self._save()

    def add(self, opp: Opportunity) -> None:
        """Record a screened setup. The write is debounced so a per-candle
        pipeline cannot turn the board into a hot path; the newest state is
        flushed on the next record once the window elapses."""
        with self._lock:
            self._opportunities[opp.opportunity_id] = opp
            self._prune()
            if time.monotonic() - self._last_saved >= self._SAVE_DEBOUNCE_S:
                self._save()
            else:
                self._dirty = True

    def get(self, opportunity_id: str) -> Optional[Opportunity]:
        return self._opportunities.get(opportunity_id)

    def list(self, statuses: Optional[List[str]] = None,
             symbol: Optional[str] = None) -> List[Opportunity]:
        items = list(self._opportunities.values())
        if statuses:
            wanted = set(statuses)
            items = [o for o in items if o.status.value in wanted]
        if symbol:
            items = [o for o in items if o.symbol == symbol]
        items.sort(key=lambda o: o.detected_at, reverse=True)
        return items

    def update(self, opp: Opportunity) -> None:
        """Persist a status transition immediately: an operator decision or an
        execution outcome is governed state, never a debounced observation."""
        with self._lock:
            self._opportunities[opp.opportunity_id] = opp
            self._save()

    def expire_stale(self, max_age_seconds: float = 6 * 3600) -> int:
        now = _now()
        count = 0
        for opp in self.list(statuses=[OpportunityStatus.QUALIFIED.value,
                                       OpportunityStatus.SCAN.value,
                                       OpportunityStatus.APPROVED.value]):
            if now - opp.detected_at > max_age_seconds:
                opp.expire()
                self.update(opp)
                count += 1
        if count:
            log.info(f"opportunity board: expired {count} stale opportunity/ies")
        return count

    def ready_to_execute(self, symbol: Optional[str] = None) -> List[Opportunity]:
        """APPROVED opportunities awaiting pipeline execution (gate=confirm)."""
        return [
            o for o in self.list(statuses=[OpportunityStatus.APPROVED.value])
            if o.execute_pending and (symbol is None or o.symbol == symbol)
        ]

    @staticmethod
    def _from_dict(item: Dict) -> Opportunity:
        keys = {f.name for f in Opportunity.__dataclass_fields__.values()}
        kwargs = {k: v for k, v in item.items() if k in keys}
        kwargs["detected_at"] = _parse_ts(item.get("detected_at"))
        for name in ("qualified_at", "approved_at", "executed_at"):
            if kwargs.get(name):
                kwargs[name] = _parse_ts(item.get(name))
        kwargs["status"] = OpportunityStatus(kwargs.get("status", OpportunityStatus.SCAN.value))
        kwargs["history"] = item.get("history", [])
        return Opportunity(**kwargs)


def _parse_ts(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        # Stored stamps are UTC ("...Z"), so parse them as UTC (calendar.timegm),
        # never as local time — otherwise a reload on a non-UTC host shifts
        # detected/executed times (and expiry windows) by the UTC offset.
        return float(calendar.timegm(time.strptime(value, "%Y-%m-%dT%H:%M:%SZ")))
    except (ValueError, TypeError):
        return None


class OpportunityEngine:
    """Packages a governed RiskDecision into an evidenced Opportunity.

    The screen does not add authority: risk stays with the Risk Governor, the
    allocation evidence comes from the governor's own portfolio-allocation
    check, and live eligibility records the promotion stage already resolved
    by the pipeline. `screen()` therefore takes the decision produced by the
    governor *before* execution and turns it into a durable, operator-visible
    record. New vetoes are never invented here.

    The board is resolved from the module singleton at call time so operators,
    endpoints and tests can point the engine at any durable board instance.
    An account desk can also inject its own board once at construction.
    """

    def __init__(self, board: Optional[OpportunityBoard] = None) -> None:
        self._board = board

    def screen(self, candidate: TradeCandidate, decision: RiskDecision,
               *, source: str = "pipeline",
               live_eligible: bool = True,
               live_eligibility_reason: str = "live allowed by pipeline stage") -> Opportunity:
        board = self._board or opportunity_board
        risk_ok = decision.kind == RiskDecisionKind.APPROVED
        allocation_ok, allocation_reason = self._allocation_evidence(decision)
        if not risk_ok:
            live_eligible = False
            live_eligibility_reason = "not live-eligible while vetoed"

        reason = decision.reason if not risk_ok else "all checks passed"
        score = float(candidate.priority)
        reasons: List[str] = []
        if not allocation_ok:
            reasons.append(f"allocation: {allocation_reason}")
        if not risk_ok:
            reasons.append(f"risk: {reason}")
        if not live_eligible:
            reasons.append("live: not live-eligible")

        session_key = (
            f"{candidate.symbol}:{candidate.direction.value}:"
            f"{int(candidate.created_at)}"
        )
        evidence = {
            "source": source,
            "risk_decision": decision.as_dict(),
            "portfolio_allocation_check": next(
                (c for c in decision.checks
                 if "allocation" in str(c.get("name", "")).lower()),
                {"name": "portfolio_allocation", "passed": True,
                 "detail": "no allocation check recorded"}),
            "candidate": candidate.as_dict(),
            "stage": {
                "strategy_id": candidate.strategy_id,
                "strategy_stage": candidate.strategy_stage,
                "live_allowed": live_eligible,
                "note": live_eligibility_reason,
            },
            "screen": {
                "rubric": (
                    "score = candidate priority (0..100, portfolio-fit rubric). "
                    "Qualification authority: yes = risk governor APPROVED and "
                    "no fabricated fields; every number is a real recorded value."
                ),
            },
        }

        opp = Opportunity(
            opportunity_id="OPP-" + str(uuid.uuid4())[:12].upper(),
            symbol=candidate.symbol,
            direction=candidate.direction.value,
            source=source,
            session_key=session_key,
            thesis_id=candidate.thesis_id,
            candidate_id=candidate.candidate_id,
            strategy_id=candidate.strategy_id,
            strategy_stage=candidate.strategy_stage,
            entry=candidate.entry,
            stop_loss=candidate.stop_loss,
            take_profit=candidate.take_profit,
            size=candidate.size,
            risk_reward=candidate.risk_reward,
            confidence=candidate.confidence,
            priority=candidate.priority,
            score=score,
            risk_ok=risk_ok,
            risk_reason=reason,
            allocation_ok=allocation_ok,
            allocation_reason=allocation_reason,
            live_eligible=live_eligible,
            live_eligibility_reason=live_eligibility_reason,
            screen_reasons=reasons,
            evidence=evidence,
        )
        if risk_ok:
            opp.qualify()
        else:
            opp.reject(reason)
        board.add(opp)
        log.info(f"Opportunity {opp.opportunity_id} {opp.symbol} {opp.direction} "
                 f"-> {opp.status.value} (risk_ok={risk_ok}, score={score})")
        return opp

    @staticmethod
    def _allocation_evidence(decision: RiskDecision):
        for check in decision.checks:
            if "allocation" in str(check.get("name", "")).lower():
                ok = bool(check.get("passed", True))
                detail = str(check.get("detail",
                                       check.get("reason", "within limits")))
                return ok, detail
        return True, "within portfolio allocation"


opportunity_board = OpportunityBoard()
opportunity_engine = OpportunityEngine()


def rebuild_candidate(opp: Opportunity) -> TradeCandidate:
    """Reconstitute a TradeCandidate from a stored Opportunity for a fresh
    execution-time Risk Governor check. Only fields the governor reads are set;
    this is an execution hand-off, not a re-entry through the Candidate Board."""
    return TradeCandidate(
        candidate_id=opp.candidate_id or "OPP-" + opp.opportunity_id,
        thesis_id=opp.thesis_id,
        symbol=opp.symbol,
        direction=TradeDirection(opp.direction),
        entry=opp.entry,
        stop_loss=opp.stop_loss,
        take_profit=opp.take_profit or opp.entry,
        size=opp.size,
        risk_reward=opp.risk_reward,
        confidence=opp.confidence,
        priority=opp.priority,
        strategy_id=opp.strategy_id,
        strategy_stage=opp.strategy_stage,
    )
