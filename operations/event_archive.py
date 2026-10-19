"""Durable Event Store for the ops/events feed (Phase B, ENGINEERING MAST
28.15 Institutional Auditability).

`operations/event_feed.py` is a *bounded in-process ring* (maxlen 1000) mirrored
to Redis: it is ephemeral coordination, and its own docstring says so. The
durable `event_log` (`persistence/events.py`) already exists but was only ever
fed from `core.events.bus`, so **the ops/events stream was never archived** --
a registry transition published to the feed was gone the moment the ring
wrapped, and there was nothing to replay.

This module closes that gap without touching a single publisher: it subscribes
to the feed (`EventFeed.subscribe`) and, when the operator opts in, writes each
event to the durable log with a stable id derived from the feed sequence, so
`event_id` is idempotent (a replayed publish is one row) and order is
preserved.

Opt-in on purpose (`TRADERAIG_EVENT_ARCHIVE=1`), matching `TRADERAIG_EVENT_LOG`
and `MARKET_BRIDGE`: archiving every feed event is a deployment choice with a
real write cost, so the safe default is off. Nothing here grants authority or
places an order; it records what already happened.

Replay reads the durable rows back in causal (occurred_at) order and returns
them feed-shaped (`id/at/kind/topic/actor/payload`), so a consumer that follows
`/ops/events` live can follow `/events/replay` afterwards and see the same
events, oldest-first, with the honest caveat that only events published *while
archiving was on* are present.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from core.logging import get_logger

log = get_logger("operations.event_archive")

ENV_FLAG = "TRADERAIG_EVENT_ARCHIVE"

# Feed topics map to the durable `event_type` as "ops.<kind>" so the archive is
# filterable by event_type via the existing EventLogRepository, and a reader can
# tell a feed-archived event from a bus event by its prefix.
EVENT_TYPE_PREFIX = "ops."


def archive_enabled_by_env() -> bool:
    return os.getenv(ENV_FLAG, "0").strip().lower() in ("1", "true", "yes", "on")


def _envelope_from_feed(event: Dict[str, Any]) -> Dict[str, Any]:
    """Map one feed event to a durable envelope (idempotent by feed id)."""
    from persistence import events as event_log

    feed_id = int(event.get("id") or 0)
    return event_log.build_event(
        f"{EVENT_TYPE_PREFIX}{event.get('kind', '')}",
        payload={"topic": event.get("topic", ""),
                 "kind": event.get("kind", ""),
                 **dict(event.get("payload") or {})},
        occurred_at=event.get("at"),
        actor=str(event.get("actor") or ""),
        subject_type="feed_event",
        subject_id=str(feed_id),
        source="event_feed",
        retention_class="operational",
        # Deterministic id: feed ids are monotonic within a process, so the same
        # event archived twice merges to one row instead of duplicating.
        event_id=f"feed-{feed_id}-{event.get('kind', '')}",
    )


def archive_event(event: Dict[str, Any], *, session=None) -> Optional[str]:
    """Archive one feed event; never raises (a store outage must not break
    publish). Returns the event_id or None."""
    try:
        from persistence.repositories import EventLogRepository

        envelope = _envelope_from_feed(event)
        EventLogRepository(session).append(envelope)
        return envelope["event_id"]
    except Exception:  # noqa: BLE001
        log.debug("event archive write skipped")
        return None


class EventArchive:
    """Feeds the durable log from the ops/events ring, and replays it back."""

    def __init__(self, feed: Any = None) -> None:
        self._feed = feed
        self._attached = False
        self._archived = 0

    def attach(self) -> bool:
        """Subscribe to the feed (opt-in). Idempotent."""
        if not archive_enabled_by_env():
            return False
        if self._attached:
            return True
        feed = self._feed
        if feed is None:
            from operations.event_feed import event_feed
            feed = event_feed
        feed.subscribe(self._on_event)
        self._attached = True
        log.info("event archive attached to the ops/events feed")
        return True

    def _on_event(self, event: Dict[str, Any]) -> None:
        if archive_event(event) is not None:
            self._archived += 1

    # -- replay ----------------------------------------------------------
    def replay(self, limit: int = 200,
               event_type: str = "") -> Dict[str, Any]:
        """Read the archived ops/events back, oldest-first (causal order).

        `event_type` narrows to one feed kind (e.g. "transition"); the default
        reads every archived feed event. Rows are re-shaped into the live
        feed's event shape so a consumer can switch from live to replay without
        translating.
        """
        limit = max(1, min(int(limit), 1000))
        from persistence.repositories import EventLogRepository

        repo = EventLogRepository()
        etype = event_type or None
        if etype and not etype.startswith(EVENT_TYPE_PREFIX):
            etype = f"{EVENT_TYPE_PREFIX}{etype}"
        rows = repo.list(limit=limit, event_type=etype)
        events = [self._to_feed_shape(r) for r in rows
                  if r.get("source") == "event_feed"]
        return {
            "enabled": archive_enabled_by_env(),
            "count": len(events),
            "events": events,
            # Honest boundary: the archive only holds events published while it
            # was attached -- an empty replay means "not archived", never
            # "nothing happened".
            "note": ("replay covers events published while "
                     "TRADERAIG_EVENT_ARCHIVE was on; empty means not archived"),
        }

    @staticmethod
    def _to_feed_shape(row: Dict[str, Any]) -> Dict[str, Any]:
        payload = dict(row.get("payload") or {})
        return {
            "id": row.get("subject_id") or "",
            "at": row.get("occurred_at"),
            "kind": payload.get("kind", row.get("event_type", "")),
            "topic": payload.get("topic", ""),
            "actor": row.get("actor", ""),
            "payload": payload,
        }


event_archive = EventArchive()
