"""Persisted unified event log: one durable envelope for every emitted event.

Every observability surface in this codebase -- the audit trail, the learning
ledger, risk vetoes, evidence -- stores its own record, with its own id column
and its own timestamp format. That is correct for each surface and wrong for the
one question an operator asks at 03:00: what happened, in what order, and what
caused what. This table is the single append-only place that can answer it.

It is a *projection*, not a replacement. The per-surface tables remain the
source of truth for their own fields; an event logged here names the surface it
came from and carries its own envelope, and nothing reads this table to
reconstruct a surface's own columns.
"""
from __future__ import annotations

from sqlalchemy import Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

# Bumped when the envelope's shape changes; stored per row so a reader can tell
# which generation of the contract it is holding rather than guessing.
EVENT_SCHEMA_VERSION = "1"


class EventLogRecord(Base):
    """One durable event envelope in the unified `event_log`."""

    __tablename__ = "event_log"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    schema_version: Mapped[str] = mapped_column(
        String(16), default=EVENT_SCHEMA_VERSION)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    # When the event happened (UTC epoch seconds), separate from when the row was
    # written: an event recovered or replayed keeps the time it describes, and
    # `recorded_at` keeps the time it was persisted, so the two are never the same.
    occurred_at: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    recorded_at: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    account_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True)
    actor: Mapped[str] = mapped_column(String(128), default="")
    subject_type: Mapped[str] = mapped_column(String(64), default="")
    subject_id: Mapped[str] = mapped_column(String(128), default="")
    correlation_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    causation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str] = mapped_column(String(64), default="")
    provider: Mapped[str] = mapped_column(String(128), default="")
    content_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    retention_class: Mapped[str] = mapped_column(
        String(16), default="operational", index=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
