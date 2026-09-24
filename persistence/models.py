"""SQLAlchemy ORM models mirroring the canonical state contracts."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Float,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class UserRecord(Base):
    """Persisted user + subscription + entitlements (governance)."""

    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255), default="")
    plan: Mapped[str] = mapped_column(String(32), default="free")
    subscription_status: Mapped[str] = mapped_column(String(32), default="pending")
    entitlements_json: Mapped[str] = mapped_column(Text, default="[]")
    risk_policy_json: Mapped[str] = mapped_column(Text, default="{}")
    account_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    expires_at: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[str] = mapped_column(String(64), default=_now_iso)
    updated_at: Mapped[str] = mapped_column(String(64), default=_now_iso)


class ExperienceRecordDB(Base):
    """Persisted experience records from the learning ledger."""

    __tablename__ = "experiences"

    record_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    decision_id: Mapped[str] = mapped_column(String(64), index=True)
    timestamp: Mapped[float] = mapped_column(Float, default=0.0)
    thesis_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    candidate_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    market_snapshot_json: Mapped[str] = mapped_column(Text, default="{}")
    risk_decision_json: Mapped[str] = mapped_column(Text, default="{}")
    actual_result_json: Mapped[str] = mapped_column(Text, default="{}")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    error_classification: Mapped[str | None] = mapped_column(String(32), nullable=True)
    slippage: Mapped[float] = mapped_column(Float, default=0.0)
    fees: Mapped[float] = mapped_column(Float, default=0.0)
    lessons_json: Mapped[str] = mapped_column(Text, default="[]")


class VetoRecordDB(Base):
    """Persisted risk-governor veto records (idempotent by decision_id)."""

    __tablename__ = "risk_vetoes"

    decision_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    kind: Mapped[str] = mapped_column(String(32), default="vetoed")
    reason: Mapped[str] = mapped_column(Text, default="")
    checks_json: Mapped[str] = mapped_column(Text, default="[]")
    recorded_at: Mapped[float] = mapped_column(
        Float, default=lambda: datetime.now(timezone.utc).timestamp())


class OpsRunRecordDB(Base):
    """Persisted summary of the last in-process exercise run (singleton row)."""

    __tablename__ = "ops_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_run: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_s: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[float] = mapped_column(
        Float, default=lambda: datetime.now(timezone.utc).timestamp())


class AuditRecordDB(Base):
    """Persisted governance audit trail."""

    __tablename__ = "audit"

    entry_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    timestamp: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    actor: Mapped[str] = mapped_column(String(128), default="")
    action: Mapped[str] = mapped_column(String(128), index=True)
    object_type: Mapped[str] = mapped_column(String(64), default="")
    object_id: Mapped[str] = mapped_column(String(64), default="")
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    success: Mapped[bool] = mapped_column(Boolean, default=True)


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def loads(text: str):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return {}
