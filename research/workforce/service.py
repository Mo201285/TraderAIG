"""The governed worker loop (S3): each named seat can be assigned bounded work
and produces a **proposal** -- it never executes.

This docks onto what already exists rather than inventing a second runtime:

* the roster is :mod:`research.workforce.registry` (the section-8 ten seats,
  the same seats the UX-13 surface renders);
* every assignment goes through the AI Action Gateway
  (:mod:`research.workforce.gateway`), which refuses Promote Live / Change Risk
  / Execute a Trade / Modify Production and routes them to the Risk Governor and
  Governance OS -- exactly the UX-13 banner, made live;
* for the research seats the crew semantics already exist in
  :mod:`research.missions.crew`; this loop carries the seat's own task class and
  named model (empty means no model was named, never an invented one).

A proposal is advisory and read-mostly: it has NO trade-permission column, it
carries ``is_authorisation: False`` and names ``risk/governor.py``, and the only
durable effect is the journal row. Nothing here places an order, promotes a
strategy or changes a risk policy.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from research.evidence_plane import IS_AUTHORISATION, TRADE_AUTHORITY

from .gateway import AI_ACTION_GATEWAY, AIActionGateway
from .registry import WorkforceRegistry, WorkforceSeat

# A bounded verb per Ollama task class; an executive seat with no task class
# gets a neutral verb. Deterministic -- the same brief always yields the same
# task text, because the proposal is a contract (as with the mission crew).
_TASK_VERB = {
    "extract": "extract the claim in",
    "analyze": "analyse and propose on",
    "summarize": "summarise the data behind",
    "code": "prepare a bounded change proposal for",
    "hypothesis": "formulate a testable hypothesis for",
    "review": "review the findings in",
}
_DEFAULT_VERB = "prepare a bounded proposal on"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class WorkerProposal:
    proposal_id: str
    seat_id: str
    seat_title: str
    department: str
    layer: str
    task_class: Optional[str]
    brief: str
    task: str
    model: str
    note: str
    status: str = "proposed"
    executed: bool = False
    act: str = "propose"
    gateway: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "seat_id": self.seat_id,
            "seat_title": self.seat_title,
            "department": self.department,
            "layer": self.layer,
            "task_class": self.task_class,
            "brief": self.brief,
            "task": self.task,
            "model": self.model,
            "note": self.note,
            "status": self.status,
            "executed": self.executed,
            "act": self.act,
            "gateway": dict(self.gateway),
            "created_at": self.created_at,
            "is_authorisation": IS_AUTHORISATION,
            "trade_authority": TRADE_AUTHORITY,
        }


class WorkerProposalStore:
    """Durable journal of seats' proposals, keyed by proposal_id."""

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = str(path) if path else ""
        self._lock = threading.Lock()
        self._rows: Dict[str, Dict] = {}
        self._seq = 0
        self.load()

    def allocate_id(self, seat_id: str) -> str:
        with self._lock:
            self._seq += 1
            return f"prop-{seat_id}-{self._seq:04d}"

    def record(self, row: Dict[str, Any]) -> Dict:
        with self._lock:
            self._rows[row["proposal_id"]] = dict(row)
            self._save()
        return dict(row)

    def get(self, proposal_id: str) -> Optional[Dict]:
        with self._lock:
            row = self._rows.get(proposal_id)
            return dict(row) if row else None

    def rows(self) -> List[Dict]:
        with self._lock:
            out = [dict(r) for r in self._rows.values()]
        return sorted(out, key=lambda r: r.get("created_at", ""))

    def for_seat(self, seat_id: str) -> List[Dict]:
        return [r for r in self.rows() if r.get("seat_id") == seat_id]

    # ------------------------------------------------------------------
    def _save(self) -> None:
        if not self.path:
            return
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(list(self._rows.values()), fh, indent=2,
                      ensure_ascii=False)

    def load(self) -> int:
        if not self.path or not Path(self.path).exists():
            return 0
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return 0
        if not isinstance(data, list):
            return 0
        with self._lock:
            for row in data:
                if isinstance(row, dict) and row.get("proposal_id"):
                    self._rows[row["proposal_id"]] = row
            self._seq = len(self._rows)
        return len(self._rows)


class WorkforceService:
    """The governed worker loop over the declared roster."""

    def __init__(self,
                 registry: Optional[WorkforceRegistry] = None,
                 store: Optional[WorkerProposalStore] = None,
                 gateway: Optional[AIActionGateway] = None) -> None:
        self._registry = registry or WorkforceRegistry()
        self._store = store or WorkerProposalStore()
        self._gateway = gateway or AI_ACTION_GATEWAY

    # -- reads ---------------------------------------------------------------
    def seats(self) -> List[Dict[str, Any]]:
        return [s.as_dict() for s in self._registry.list()]

    def seat(self, seat_id: str) -> Optional[Dict[str, Any]]:
        seat = self._registry.get(seat_id)
        return seat.as_dict() if seat else None

    def summary(self) -> Dict[str, Any]:
        base = self._registry.summary()
        rows = self._store.rows()
        return {**base,
                "proposals": len(rows),
                "open_proposals": len([r for r in rows
                                       if r.get("status") == "proposed"])}

    def proposals(self) -> List[Dict[str, Any]]:
        return self._store.rows()

    def proposals_for(self, seat_id: str) -> List[Dict[str, Any]]:
        return self._store.for_seat(seat_id)

    def proposal(self, proposal_id: str) -> Optional[Dict[str, Any]]:
        return self._store.get(proposal_id)

    # -- the loop ------------------------------------------------------------
    def _require_seat(self, seat_id: str) -> WorkforceSeat:
        seat = self._registry.get(seat_id)
        if seat is None:
            raise ValueError(f"no seat {seat_id!r} in the workforce")
        return seat

    def propose(self, *, seat_id: str, brief: str, note: str = "",
                model: str = "") -> Dict[str, Any]:
        """Assign a bounded task to a seat; it returns a PROPOSAL, never execution."""
        seat = self._require_seat(seat_id)
        value = str(brief or "").strip()
        if not value:
            raise ValueError("a seat is given a brief; an empty brief is refused")
        decision = self._gateway.request(seat.seat_id, "propose")
        verb = _TASK_VERB.get(seat.task_class or "", _DEFAULT_VERB)
        proposal = WorkerProposal(
            proposal_id=self._store.allocate_id(seat.seat_id),
            seat_id=seat.seat_id,
            seat_title=seat.title,
            department=seat.department,
            layer=seat.layer,
            task_class=seat.task_class,
            brief=value,
            task=f"{verb}: {value}",
            model=str(model or "").strip(),
            note=str(note or "").strip(),
            gateway=decision.as_dict(),
            created_at=_now(),
        )
        return self._store.record(proposal.as_dict())

    def request_action(self, *, seat_id: str, action: str,
                       target: str = "") -> Dict[str, Any]:
        """Ask the AI Action Gateway whether a seat may take an action.

        The four forbidden actions are always refused (routed to the Risk
        Governor / Governance OS); only ``propose`` is allowed. This is the live
        control behind 'seats propose, never execute'.
        """
        seat = self._require_seat(seat_id)
        return self._gateway.request(seat.seat_id, action,
                                     target=target).as_dict()


__all__ = ["WorkerProposal", "WorkerProposalStore", "WorkforceService"]
