"""Repositories: persistence implementations of the core contracts.

Each repository maps ORM rows to/from the domain dataclasses without
leaking SQLAlchemy into business logic.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from governance.identity import (
    AuditEntry,
    Entitlement,
    Subscription,
    User,
)
from learning.experience import ErrorType, ExperienceRecord, MarketSnapshot
from persistence.db import bind_test_session
from persistence.models import (
    AuditRecordDB,
    ExperienceRecordDB,
    OpsRunRecordDB,
    UserRecord,
    VetoRecordDB,
    dumps,
    loads,
)


class UserRepository:
    """Persists/loads `User` records."""

    def __init__(self, session: Optional[Session] = None) -> None:
        self._session = session or bind_test_session()

    def save(self, user: User, subscription: Optional[Subscription] = None) -> None:
        row = self._session.get(UserRecord, user.user_id)
        if row is None:
            row = UserRecord(user_id=user.user_id)
            self._session.add(row)
        row.email = user.email
        row.display_name = user.display_name
        row.plan = user.plan.value
        row.subscription_status = user.subscription_status.value
        row.entitlements_json = dumps(sorted(e.value for e in user.entitlements))
        row.risk_policy_json = dumps(user.risk_policy.as_dict())
        row.account_ids_json = dumps(user.account_ids)
        if subscription is not None:
            row.expires_at = subscription.expires_at
        row.updated_at = datetime.now(timezone.utc).isoformat()
        self._session.commit()

    def get(self, user_id: str) -> Optional[User]:
        row = self._session.get(UserRecord, user_id)
        if row is None:
            return None
        return self._row_to_user(row)

    def get_by_email(self, email: str) -> Optional[User]:
        row = self._session.execute(
            select(UserRecord).where(UserRecord.email == email)
        ).scalar_one_or_none()
        return self._row_to_user(row) if row else None

    def list(self, limit: int = 100) -> List[User]:
        rows = self._session.execute(
            select(UserRecord).limit(limit)
        ).scalars().all()
        return [self._row_to_user(r) for r in rows]

    def save_subscription(self, subscription: Subscription) -> None:
        row = self._session.get(UserRecord, subscription.user_id)
        if row is None:
            return
        row.plan = subscription.plan.value
        row.subscription_status = subscription.status.value
        row.expires_at = subscription.expires_at
        row.updated_at = datetime.now(timezone.utc).isoformat()
        self._session.commit()

    @staticmethod
    def _row_to_user(row: UserRecord) -> User:
        from governance.identity import RiskPolicy

        plan = _enum_cast(row.plan, "governance.identity.SubscriptionPlan")
        status = _enum_cast(
            row.subscription_status, "governance.identity.SubscriptionStatus"
        )
        entitlements_raw = loads(row.entitlements_json) or []
        entitlements = {Entitlement(value) for value in entitlements_raw}

        return User(
            user_id=row.user_id,
            email=row.email,
            display_name=row.display_name,
            plan=plan,
            subscription_status=status,
            entitlements=entitlements,
            risk_policy=RiskPolicy(**loads(row.risk_policy_json)),
            account_ids=loads(row.account_ids_json),
        )


class ExperienceRepository:
    """Persists/loads `ExperienceRecord` rows."""

    def __init__(self, session: Optional[Session] = None) -> None:
        self._session = session or bind_test_session()

    def save(self, record: ExperienceRecord) -> None:
        row = ExperienceRecordDB(
            record_id=record.record_id,
            decision_id=record.decision_id,
            timestamp=record.timestamp,
            thesis_id=record.thesis_id,
            candidate_id=record.candidate_id,
            market_snapshot_json=dumps(record.market_snapshot.__dict__
                                       if record.market_snapshot else {}),
            risk_decision_json=dumps(record.risk_decision or {}),
            actual_result_json=dumps(record.actual_result or {}),
            metadata_json=dumps(record.metadata or {}),
            error_classification=record.error_classification.value
            if record.error_classification else None,
            slippage=record.slippage,
            fees=record.fees,
            lessons_json=dumps(record.lessons),
        )
        self._session.merge(row)
        self._session.commit()

    def list(self, limit: int = 100) -> List[ExperienceRecord]:
        rows = self._session.execute(
            select(ExperienceRecordDB).order_by(
                ExperienceRecordDB.timestamp.desc()).limit(limit)
        ).scalars().all()
        return [self._row_to_record(r) for r in rows]

    @staticmethod
    def _row_to_record(row: ExperienceRecordDB) -> ExperienceRecord:
        market_snapshot_raw = loads(row.market_snapshot_json)
        market_snapshot = MarketSnapshot(**market_snapshot_raw) if market_snapshot_raw else None
        error_classification = ErrorType(row.error_classification) if row.error_classification else None
        return ExperienceRecord(
            record_id=row.record_id,
            decision_id=row.decision_id,
            timestamp=row.timestamp,
            thesis_id=row.thesis_id,
            candidate_id=row.candidate_id,
            market_snapshot=market_snapshot,
            risk_decision=loads(row.risk_decision_json),
            actual_result=loads(row.actual_result_json),
            metadata=loads(row.metadata_json),
            error_classification=error_classification,
            slippage=row.slippage,
            fees=row.fees,
            lessons=loads(row.lessons_json),
        )


class RiskVetoRepository:
    """Persists/loads risk-governor veto records (idempotent by decision_id)."""

    def __init__(self, session: Optional[Session] = None) -> None:
        self._session = session or bind_test_session()

    def save(self, veto: Dict) -> None:
        row = VetoRecordDB(
            decision_id=str(veto.get("decision_id") or ""),
            candidate_id=str(veto.get("candidate_id") or ""),
            kind=str(veto.get("kind") or "vetoed"),
            reason=str(veto.get("reason") or ""),
            checks_json=dumps(veto.get("checks") or []),
            recorded_at=float(veto.get("recorded_at") or 0.0) or None,
        )
        self._session.merge(row)
        self._session.commit()

    def list(self, limit: int = 300) -> List[Dict]:
        rows = self._session.execute(
            select(VetoRecordDB).order_by(
                VetoRecordDB.recorded_at.desc()).limit(limit)
        ).scalars().all()
        return [self._row_to_veto(r) for r in reversed(rows)]

    @staticmethod
    def _row_to_veto(row: VetoRecordDB) -> Dict:
        return {
            "decision_id": row.decision_id,
            "candidate_id": row.candidate_id,
            "kind": row.kind,
            "reason": row.reason,
            "checks": loads(row.checks_json),
            "recorded_at": row.recorded_at,
        }


class OpsRunRepository:
    """Persists/loads the summary of the last exercise run (singleton id=1)."""

    def __init__(self, session: Optional[Session] = None) -> None:
        self._session = session or bind_test_session()

    def save_last(self, last_run: Optional[str] = None,
                  duration_s: float = 0.0, error: Optional[str] = None) -> None:
        self._session.merge(OpsRunRecordDB(
            id=1, last_run=last_run, duration_s=duration_s, error=error))
        self._session.commit()

    def get_last(self) -> Optional[Dict]:
        row = self._session.execute(
            select(OpsRunRecordDB).where(OpsRunRecordDB.id == 1)
        ).scalars().first()
        if row is None:
            return None
        return {"last_run": row.last_run, "duration_s": row.duration_s,
                "error": row.error}


class AuditRepository:
    """Append-only audit persistence."""

    def __init__(self, session: Optional[Session] = None) -> None:
        self._session = session or bind_test_session()

    def append(self, entry: AuditEntry) -> None:
        row = AuditRecordDB(
            entry_id=entry.entry_id,
            timestamp=entry.timestamp,
            actor=entry.actor,
            action=entry.action,
            object_type=entry.object_type,
            object_id=entry.object_id,
            details_json=dumps(entry.details),
            success=entry.success,
        )
        self._session.add(row)
        self._session.commit()

    def list(self, limit: int = 100) -> List[AuditEntry]:
        rows = self._session.execute(
            select(AuditRecordDB).order_by(
                AuditRecordDB.timestamp.desc()).limit(limit)
        ).scalars().all()
        return [self._row_to_entry(r) for r in rows]

    @staticmethod
    def _row_to_entry(row: AuditRecordDB) -> AuditEntry:
        return AuditEntry(
            entry_id=row.entry_id,
            timestamp=row.timestamp,
            actor=row.actor,
            action=row.action,
            object_type=row.object_type,
            object_id=row.object_id,
            details=loads(row.details_json),
            success=row.success,
        )


def _enum_cast(value: str, enum_dotted: str) -> object:
    """Cast string back to the enum member defined in the given module path."""
    import importlib

    mod_name, _, attr = enum_dotted.rpartition(".")
    module = importlib.import_module(mod_name)
    enum_cls = getattr(module, attr)
    return enum_cls(value)
