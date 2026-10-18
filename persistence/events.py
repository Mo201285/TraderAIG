"""The shared event envelope and its durable writer.

One vocabulary for anything that wants to be findable later: a stable
``event_id`, a UTC ``occurred_at``, a ``schema_version`` so a reader knows which
generation of the contract it holds, and a ``content_hash`` so the same event
emitted twice is one row.

This is a *projection* of the surfaces that already exist (audit, learning,
vetoes, evidence) into one ordered, causally-linked log, not a replacement for
them: a surface keeps its own table and this log names the surface it came from.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from .models_events import EVENT_SCHEMA_VERSION

# Env flag that turns the durable projection ON. Absent/empty is OFF: writing a
# row for every domain event (including per-cycle `EVIDENCE_GATHERED`) is a
# deployment choice with a real cost, so the safe default is not to.
EVENT_LOG_ENV = "TRADERAIG_EVENT_LOG"

# Retention is a class, not a per-row duration: `permanent` is the irreversible
# record (audit, vetoes, deals), `long` is learning matter kept for training,
# `operational` is telemetry an operator may prune. A writer that cannot name a
# class does not get to invent one.
RETENTION_CLASSES = ("permanent", "long", "operational")


def enabled_by_env() -> bool:
    """True only when `TRADERAIG_EVENT_LOG` is explicitly truthy.

    Mirrors `MarketBridge.enabled_by_env` / `persistence_enabled`: an absent or
    empty value keeps the durable projection off, so merely importing or booting
    the app never starts writing a row per event.
    """
    return os.getenv(EVENT_LOG_ENV, "").strip().lower() in (
        "1", "true", "yes", "on")



def _now() -> float:
    return datetime.now(timezone.utc).timestamp()


def content_hash(payload: Any) -> str:
    """Stable hash of a payload for de-duplication.

    Sorted keys and a string fallback, because the value being hashed is an
    arbitrary event payload: a hash that varies with dict ordering would call
    the same event two events.
    """
    try:
        blob = json.dumps(payload, sort_keys=True, default=str,
                          ensure_ascii=False)
    except (TypeError, ValueError):
        blob = str(payload)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def build_event(
    event_type: str,
    *,
    payload: Any = None,
    occurred_at: float | None = None,
    account_id: str | None = None,
    actor: str = "",
    subject_type: str = "",
    subject_id: str = "",
    correlation_id: str = "",
    causation_id: str | None = None,
    source: str = "",
    provider: str = "",
    retention_class: str = "operational",
    event_id: str | None = None,
    schema_version: str = EVENT_SCHEMA_VERSION,
) -> Dict[str, Any]:
    """Build one envelope. Raises on an unknown retention class.

    A bad class is a programming error, not a store outage, so it is not
    swallowed here the way a failed write is in `emit`.
    """
    if retention_class not in RETENTION_CLASSES:
        raise ValueError(
            f"unknown retention_class {retention_class!r}; "
            f"expected one of {RETENTION_CLASSES}")
    body = payload if isinstance(payload, dict) else (
        {"value": payload} if payload is not None else {})
    return {
        "event_id": str(event_id or uuid.uuid4().hex),
        "schema_version": str(schema_version),
        "event_type": str(event_type or ""),
        "occurred_at": float(occurred_at if occurred_at is not None else _now()),
        "recorded_at": _now(),
        "account_id": (str(account_id) if account_id else None),
        "actor": str(actor or ""),
        "subject_type": str(subject_type or ""),
        "subject_id": str(subject_id or ""),
        "correlation_id": str(correlation_id or ""),
        "causation_id": (str(causation_id) if causation_id else None),
        "source": str(source or ""),
        "provider": str(provider or ""),
        "content_hash": content_hash(body),
        "retention_class": str(retention_class),
        "payload": body,
    }


def emit(
    event_type: str,
    *,
    payload: Any = None,
    session=None,
    **fields: Any,
) -> Dict[str, Any] | None:
    """Build and durably append one event; never raises on a store failure.

    Observability must not be able to fail the thing it observes. A store that
    cannot be reached degrades to no record and returns `None`, in keeping with
    the audit and challenge paths, rather than taking the caller down. A bad
    retention class still raises: that is a bug, not an outage.
    """
    envelope = build_event(event_type, payload=payload, **fields)
    try:
        from .repositories import EventLogRepository  # local: avoid an import cycle

        EventLogRepository(session).append(envelope)
    except Exception:  # noqa: BLE001  (a write failure must not surface here)
        return None
    return envelope


def record_event(event: Any, *, session=None) -> Dict[str, Any] | None:
    """Persist one `core.events.Event` in the unified log.

    Shaped as an `EventBus.subscribe_all` handler: it reads a duck-typed event
    (`.type`, `.payload`, ``timestamp``, `event_id`, `source`, `correlation_id`)
    so wiring it to the bus does not make this module import the bus.
    """
    etype = getattr(event, "type", "")
    etype = getattr(etype, "value", etype)
    return emit(
        str(etype or ""),
        payload=dict(getattr(event, "payload", {}) or {}),
        occurred_at=getattr(event, "timestamp", None),
        source=str(getattr(event, "source", "") or ""),
        correlation_id=str(getattr(event, "correlation_id", "") or ""),
        event_id=getattr(event, "event_id", None),
        session=session,
    )


def attach(bus) -> None:
    """Subscribe the durable log to every event published on `bus`.

    Opt-in on purpose: wiring it at startup turns every published event into a
    committed row, including the hot execution path, which is a deployment
    decision rather than an import side effect.
    """
    bus.subscribe_all(record_event)
