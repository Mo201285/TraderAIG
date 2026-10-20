"""Repositories for the Commercial Offer Registry (Phase G, slice G1).

Session and error discipline are copied verbatim from `repositories_accounts.py`
and for the same stated reasons: hold a session per call (a repository held for
a request lifetime exhausts the pool), and every method returns a definite
answer **or raises** -- an offer ledger that reported "no offers" while the store
was down would switch a whole campaign off silently, and a redemption ledger
that reported "not redeemed" while the store was down would double-grant on the
next tick. Fail-closed is the only safe reading.

The uniqueness rules the database enforces are also the idempotency rules the
domain relies on: one code per provider is enforced on `referrals`, and one
redemption per `(offer_id, user_id)` is enforced here, so a retried `redeem`
finds the existing row rather than writing a second grant.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import json
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from persistence.db import make_live_session
from persistence.models_offers import (
    CommercialOfferRecord,
    OfferRedemptionRecord,
)

# The operator lifecycle of an offer. `active` is the only state a redemption is
# allowed against; the other two are deliberate operator acts, kept distinct so
# a report can tell "an operator paused this" from "this campaign's window
# closed" (the latter is derived from dates in the service, never stored).
OFFER_STATUSES = ("active", "paused", "retired")

# The redemption lifecycle. `pending` is the honest state when the offer's
# conditions require a verification the platform does not have -- it is a real
# outcome, not a failure: opening a referral link is not proof of a purchase, so
# a redemption that cannot yet be proven is neither granted nor declined.
REDEMPTION_STATUSES = ("pending", "granted", "declined", "failed")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class OfferRepository:
    """Durable catalog of operator-authored commercial offers."""

    def __init__(self, session: Optional[Session] = None) -> None:
        self._injected = session
        self._session = session

    @contextmanager
    def _db(self):
        if self._injected is not None:
            yield self._injected
            return
        session = self._session or make_live_session()
        try:
            yield session
        finally:
            session.close()

    def create(self, *, title: str, provider_id: str,
               grant_kind: str, grant_ref: str, referral_code: str = "",
               conditions: Optional[Dict[str, Any]] = None,
               starts_at: float = 0.0, ends_at: float = 0.0,
               max_redemptions: int = 0, created_by: str = "",
               note: str = "", status: str = "active") -> Dict[str, Any]:
        """Record one offer. Validated fail-closed before any write.

        A new offer is a new row, never an upsert: an offer is identified by its
        generated `offer_id`, and two offers with the same title are two
        campaigns (a corrected one and a superseded one), not one row.
        """
        payload = {
            "title": title, "provider_id": provider_id,
            "grant_kind": grant_kind, "grant_ref": grant_ref,
            "referral_code": referral_code,
            "conditions": conditions or {},
            "starts_at": starts_at, "ends_at": ends_at,
            "max_redemptions": max_redemptions,
            "created_by": created_by, "status": status,
        }
        _validate_offer(payload)

        now_iso = _now_iso()
        row = CommercialOfferRecord(
            offer_id=uuid.uuid4().hex,
            title=str(title or "").strip(),
            provider_id=str(provider_id or "").strip(),
            referral_code=str(referral_code or "").strip(),
            grant_kind=str(grant_kind or "").strip().lower(),
            grant_ref=str(grant_ref or "").strip(),
            conditions_json=json.dumps(dict(conditions or {})),
            starts_at=float(starts_at or 0.0),
            ends_at=float(ends_at or 0.0),
            max_redemptions=int(max_redemptions or 0),
            status=str(status or "active"),
            created_by=str(created_by or ""),
            note=str(note or ""),
            created_at=now_iso, updated_at=now_iso,
        )
        with self._db() as session:
            session.add(row)
            session.commit()
            return _row_to_offer(row)

    def update(self, offer_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
        """Correct an existing offer in place. Unknown offer returns None.

        Only the columns an operator may legitimately change are accepted; the
        generated `offer_id` and `created_at` are never writable.
        """
        writable = {
            "title", "referral_code", "grant_kind", "grant_ref",
            "conditions", "starts_at", "ends_at", "max_redemptions",
            "status", "note", "provider_id",
        }
        with self._db() as session:
            row = session.get(CommercialOfferRecord, str(offer_id or ""))
            if row is None:
                return None
            merged = _row_to_offer(row)
            merged.update({k: v for k, v in fields.items() if k in writable})
            _validate_offer(merged)
            if "title" in fields:
                row.title = str(fields["title"] or "").strip()
            if "provider_id" in fields:
                row.provider_id = str(fields["provider_id"] or "").strip()
            if "referral_code" in fields:
                row.referral_code = str(fields["referral_code"] or "").strip()
            if "grant_kind" in fields:
                row.grant_kind = str(fields["grant_kind"] or "").strip().lower()
            if "grant_ref" in fields:
                row.grant_ref = str(fields["grant_ref"] or "").strip()
            if "conditions" in fields:
                row.conditions_json = json.dumps(dict(fields["conditions"] or {}))
            if "starts_at" in fields:
                row.starts_at = float(fields["starts_at"] or 0.0)
            if "ends_at" in fields:
                row.ends_at = float(fields["ends_at"] or 0.0)
            if "max_redemptions" in fields:
                row.max_redemptions = int(fields["max_redemptions"] or 0)
            if "status" in fields:
                row.status = str(fields["status"] or "").strip()
            if "note" in fields:
                row.note = str(fields["note"] or "")
            row.updated_at = _now_iso()
            session.commit()
            return _row_to_offer(row)

    def get(self, offer_id: str) -> Optional[Dict[str, Any]]:
        with self._db() as session:
            row = session.get(CommercialOfferRecord, str(offer_id or ""))
        return _row_to_offer(row) if row is not None else None

    def list_all(self, *, status: str = "",
                 provider_id: str = "") -> List[Dict[str, Any]]:
        with self._db() as session:
            query = select(CommercialOfferRecord)
            if status:
                query = query.where(CommercialOfferRecord.status == str(status))
            if provider_id:
                query = query.where(
                    CommercialOfferRecord.provider_id == str(provider_id))
            rows = session.execute(
                query.order_by(CommercialOfferRecord.created_at.desc())
            ).scalars().all()
        return [_row_to_offer(r) for r in rows]


class OfferRedemptionRepository:
    """Durable record of one user's redemption of one offer."""

    def __init__(self, session: Optional[Session] = None) -> None:
        self._injected = session
        self._session = session

    @contextmanager
    def _db(self):
        if self._injected is not None:
            yield self._injected
            return
        session = self._session or make_live_session()
        try:
            yield session
        finally:
            session.close()

    def get(self, offer_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """The one redemption of `offer_id` by `user_id`, or None."""
        with self._db() as session:
            row = session.execute(
                select(OfferRedemptionRecord).where(
                    OfferRedemptionRecord.offer_id == str(offer_id or ""),
                    OfferRedemptionRecord.user_id == str(user_id or ""),
                )).scalars().first()
        return _row_to_redemption(row) if row is not None else None

    def list_for_user(self, user_id: str) -> List[Dict[str, Any]]:
        with self._db() as session:
            rows = session.execute(
                select(OfferRedemptionRecord).where(
                    OfferRedemptionRecord.user_id == str(user_id or "")
                ).order_by(OfferRedemptionRecord.created_at.desc())
            ).scalars().all()
        return [_row_to_redemption(r) for r in rows]

    def count_for_offer(self, offer_id: str) -> int:
        """How many redemptions exist for an offer (any status)."""
        with self._db() as session:
            rows = session.execute(
                select(OfferRedemptionRecord).where(
                    OfferRedemptionRecord.offer_id == str(offer_id or "")
                )).scalars().all()
        return len(rows)

    def record(self, *, offer_id: str, user_id: str, provider_id: str,
               referral_code: str, grant_kind: str, grant_ref: str,
               status: str = "pending", entitlement_ref: str = "",
               reason: str = "", note: str = "") -> Dict[str, Any]:
        """Open a redemption row for `(offer_id, user_id)`, once only.

        Idempotency is enforced by the database, not by a prior read: a second
        INSERT for the same `(offer_id, user_id)` raises `IntegrityError`
        (`uq_offer_redemption_offer_user`), and that is surfaced as a
        `ValueError`. A "have they redeemed?" SELECT first would still let two
        concurrent requests both pass the check and both write; the unique
        constraint is the only thing that makes "one user uses one offer at most
        once" true under concurrency, so the check-then-insert shape is
        deliberately avoided here.

        The caller is expected to write the `pending` row **before** attempting
        the grant: that insert is the lock. If it succeeds, this caller owns the
        single grant for this pair; if it fails, somebody already has it and no
        grant is attempted. Snapshots the offer's grant target so an offer
        edited later cannot rewrite what this redemption was promised.
        """
        offer_id = str(offer_id or "").strip()
        user_id = str(user_id or "").strip()
        if str(status) not in REDEMPTION_STATUSES:
            raise ValueError(
                f"unknown redemption status {status!r}; expected one of "
                f"{list(REDEMPTION_STATUSES)}")
        now_iso = _now_iso()
        row = OfferRedemptionRecord(
            redemption_id=uuid.uuid4().hex,
            offer_id=offer_id, user_id=user_id,
            provider_id=str(provider_id or ""),
            referral_code=str(referral_code or ""),
            grant_kind=str(grant_kind or ""),
            grant_ref=str(grant_ref or ""),
            status=str(status),
            entitlement_ref=str(entitlement_ref or ""),
            reason=str(reason or ""),
            note=str(note or ""),
            created_at=now_iso, updated_at=now_iso,
        )
        with self._db() as session:
            session.add(row)
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise ValueError(
                    f"user {user_id!r} has already redeemed offer "
                    f"{offer_id!r}; one user uses one offer at most once"
                ) from exc
            return _row_to_redemption(row)

    def set_outcome(self, redemption_id: str, status: str, *,
                    entitlement_ref: str = "",
                    reason: str = "") -> Optional[Dict[str, Any]]:
        """Move a redemption to its outcome (granted / declined / failed)."""
        if str(status) not in REDEMPTION_STATUSES:
            raise ValueError(
                f"unknown redemption status {status!r}; expected one of "
                f"{list(REDEMPTION_STATUSES)}")
        with self._db() as session:
            row = session.get(OfferRedemptionRecord,
                              str(redemption_id or ""))
            if row is None:
                return None
            row.status = str(status)
            if entitlement_ref:
                row.entitlement_ref = str(entitlement_ref)
            if reason:
                row.reason = str(reason)
            row.updated_at = _now_iso()
            session.commit()
            return _row_to_redemption(row)


def _validate_offer(payload: Dict[str, Any]) -> None:
    """Fail-closed validation shared by `create` and `update`.

    The grant target must be a *named* one: an offer that names no product or no
    plan is an offer that grants nothing while claiming to, which is exactly the
    fabricated-benefit shape this family refuses. The kind is one of the two the
    platform can actually honour.
    """
    provider_id = str(payload.get("provider_id") or "").strip()
    if not provider_id:
        raise ValueError("an offer must name a provider_id")
    grant_kind = str(payload.get("grant_kind") or "").strip().lower()
    if grant_kind not in ("product", "plan"):
        raise ValueError(
            f"grant_kind must be 'product' or 'plan', not {grant_kind!r}")
    grant_ref = str(payload.get("grant_ref") or "").strip()
    if not grant_ref:
        raise ValueError(
            "an offer must name a grant_ref (the product id or the plan)")
    starts = float(payload.get("starts_at") or 0.0)
    ends = float(payload.get("ends_at") or 0.0)
    if starts and ends and ends < starts:
        raise ValueError("ends_at cannot precede starts_at")
    status = str(payload.get("status") or "active")
    if status not in OFFER_STATUSES:
        raise ValueError(
            f"unknown offer status {status!r}; expected one of "
            f"{list(OFFER_STATUSES)}")


def _row_to_offer(row: CommercialOfferRecord) -> Dict[str, Any]:
    def _loads(text: str) -> Dict[str, Any]:
        try:
            value = json.loads(text or "{}")
            return value if isinstance(value, dict) else {}
        except Exception:  # noqa: BLE001
            return {}

    return {
        "offer_id": row.offer_id,
        "title": row.title,
        "provider_id": row.provider_id,
        "referral_code": row.referral_code,
        "grant_kind": row.grant_kind,
        "grant_ref": row.grant_ref,
        "conditions": _loads(row.conditions_json),
        "starts_at": row.starts_at,
        "ends_at": row.ends_at,
        "max_redemptions": row.max_redemptions,
        "status": row.status,
        "created_by": row.created_by,
        "note": row.note,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _row_to_redemption(row: OfferRedemptionRecord) -> Dict[str, Any]:
    return {
        "redemption_id": row.redemption_id,
        "offer_id": row.offer_id,
        "user_id": row.user_id,
        "provider_id": row.provider_id,
        "referral_code": row.referral_code,
        "grant_kind": row.grant_kind,
        "grant_ref": row.grant_ref,
        "status": row.status,
        "entitlement_ref": row.entitlement_ref,
        "reason": row.reason,
        "note": row.note,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


__all__ = [
    "OFFER_STATUSES",
    "OfferRedemptionRepository",
    "OfferRepository",
    "REDEMPTION_STATUSES",
]
