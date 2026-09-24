"""Change Governance — audited change-request tracker and approval loop.

Closes the governance orphan: production-affecting changes (registry promote /
quarantine, config edits) are captured as change requests, reviewed, and only
*applied* by an explicit approval — never as a side effect of a report or a
queue read. Promotions/quarantines are applied through the same engine-safety
guard and registry state-machine as ``/ops/review/apply`` (M9.5), so the loop
can propose but the change board is the single gate that mutates.

Every transition writes a history line; an injected ``audit`` callable (the
identity service's ``record_audit``) appends an append-only audit entry.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional

ALLOWED_KINDS = ("promote", "quarantine", "config")
TRANSITIONS = ("approved", "denied", "cancelled")


@dataclass
class ChangeRequest:
    """One requested change on the path to production."""

    id: str
    kind: str
    target: str
    reason: str
    status: str = "pending"
    payload: Dict[str, Any] = field(default_factory=dict)
    requested_by: str = "operator"
    decided_by: str = ""
    created_at: float = field(default_factory=time.time)
    decided_at: Optional[float] = None
    history: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ChangeRequestStore:
    """In-memory change board. Immutable to the trading loop; the registry is
    only touched inside ``approve`` through the guarded review apply."""

    def __init__(self, audit: Optional[Callable[..., None]] = None) -> None:
        self._requests: Dict[str, ChangeRequest] = {}
        self._seq = 0
        self._audit = audit  # record_audit(actor, action, object_type, id, ...)

    # -- queries ------------------------------------------------------------
    def get(self, cr_id: str) -> Optional[ChangeRequest]:
        return self._requests.get(cr_id)

    def list(self, status: Optional[str] = None) -> List[Dict]:
        items = [r.as_dict() for r in self._requests.values()]
        if status:
            items = [r for r in items if r["status"] == status]
        items.sort(key=lambda r: r["created_at"], reverse=True)
        return items

    # -- lifecycle ----------------------------------------------------------
    def submit(self, kind: str, target: str, reason: str,
               payload: Optional[Dict[str, Any]] = None,
               requested_by: str = "operator") -> ChangeRequest:
        if kind not in ALLOWED_KINDS:
            raise ValueError(
                f"kind must be one of {', '.join(ALLOWED_KINDS)}; got {kind!r}")
        self._seq += 1
        cr = ChangeRequest(
            id=f"{time.strftime('%Y%m%d')}-{self._seq:03d}",
            kind=kind, target=target, reason=reason,
            payload=dict(payload or {}), requested_by=requested_by,
        )
        cr.history.append(f"submitted by {requested_by} [{kind}@{target}]")
        self._requests[cr.id] = cr
        self._emit_audit(requested_by, "change.submit", cr.id, {"kind": kind,
                          "target": target, "reason": reason}, True)
        return cr

    def approve(self, cr_id: str, decided_by: str = "operator",
                reason: str = "",
                registry: Any = None,
                engine_guard: Optional[Callable[[str], bool]] = None,
                audit: Optional[Callable[..., None]] = None) -> Dict:
        """Decide a change. Promote/quarantine requests are *applied* through
        the guarded review loop; if live execution is at risk the request
        stays pinned. ``registry`` can be a real lab registry or any object
        exposing ``get/promote/demote`` (tests pass fakes)."""
        cr = self._requests.get(cr_id)
        if cr is None:
            return {"ok": False, "reason": "unknown_request", "id": cr_id}
        if cr.status != "pending":
            return {"ok": False, "reason": "not_pending", "id": cr_id,
                    "status": cr.status}

        apply_result: Dict[str, Any] = {}
        if cr.kind in ("promote", "quarantine") and registry is not None:
            from operations.quality import ReviewLoop
            loop = ReviewLoop(registry=registry, engine_guard=engine_guard)
            apply_result = loop.apply(
                kind=cr.kind, strategy_id=cr.target,
                reason=reason or cr.reason or "approved_change")
            if not apply_result.get("applied"):
                return {"ok": False, "id": cr_id, "status": cr.status,
                        "reason": apply_result.get("reason", "not_applied"),
                        "detail": apply_result.get("detail", "")}

        cr.status = "approved"
        cr.decided_by = decided_by
        cr.decided_at = time.time()
        extra = f" | applied: {apply_result.get('to_stage', cr.kind)}" if apply_result else ""
        cr.history.append(
            f"approved by {decided_by}{' (' + reason + ')' if reason else ''}{extra}")
        self._emit_audit(decided_by, "change.approve", cr.id,
                         {"kind": cr.kind, "target": cr.target,
                          "reason": reason or cr.reason,
                          "applied": apply_result.get("applied", True)}, True,
                         audit)
        return {"ok": True, "id": cr_id, "status": "approved", **apply_result}

    def deny(self, cr_id: str, decided_by: str = "operator",
             reason: str = "",
             audit: Optional[Callable[..., None]] = None) -> Dict:
        cr = self._requests.get(cr_id)
        if cr is None:
            return {"ok": False, "reason": "unknown_request"}
        if cr.status != "pending":
            return {"ok": False, "reason": "not_pending", "status": cr.status}
        cr.status = "denied"
        cr.decided_by = decided_by
        cr.decided_at = time.time()
        cr.history.append(
            f"denied by {decided_by}{' (' + reason + ')' if reason else ''}")
        self._emit_audit(decided_by, "change.deny", cr.id,
                         {"target": cr.target, "reason": reason}, True, audit)
        return {"ok": True, "id": cr_id, "status": "denied"}

    def cancel(self, cr_id: str, requested_by: str = "operator",
               audit: Optional[Callable[..., None]] = None) -> Dict:
        cr = self._requests.get(cr_id)
        if cr is None:
            return {"ok": False, "reason": "unknown_request"}
        if cr.status != "pending":
            return {"ok": False, "reason": "not_pending", "status": cr.status}
        cr.status = "cancelled"
        cr.history.append(f"cancelled by {requested_by}")
        self._emit_audit(requested_by, "change.cancel", cr.id,
                         {"target": cr.target}, True, audit)
        return {"ok": True, "id": cr_id, "status": "cancelled"}

    # -- audit --------------------------------------------------------------
    def _emit_audit(self, actor: str, action: str, cr_id: str,
                    details: Dict[str, Any], success: bool,
                    audit: Optional[Callable[..., None]] = None) -> None:
        audit = audit or self._audit
        if audit is None:
            return
        try:
            audit(actor, action, "change_request", cr_id,
                  details or {}, success)
        except Exception:  # noqa: BLE001  audit must never break a decision
            pass


change_board = ChangeRequestStore()
