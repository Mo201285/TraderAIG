"""Live operations event feed for dashboard / copy-engine consumers.

A transport-agnostic bus: every event is always recorded in a bounded
in-process ring (works with zero infrastructure), and each publish is also
mirrored to Redis when ``core.redis_state.redis_sync`` is available, so other
processes (dashboards, copy engines, risk consoles) can follow via standard
pub/sub. Last-event ids let consumers resume exactly where they left off.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional

TOPICS = ("registry", "change", "risk", "health", "ops")


class EventFeed:
    """Bounded append-only event bus with resume-by-id consumption."""

    def __init__(self, maxlen: int = 1000) -> None:
        self._seq = 0
        self._events: deque = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    # -- publish ---------------------------------------------------------
    def publish(self, kind: str, topic: str, actor: str = "system",
                payload: Optional[Dict[str, Any]] = None,
                _time: Optional[float] = None) -> Dict[str, Any]:
        if topic not in TOPICS:
            topic = "ops"
        with self._lock:
            self._seq += 1
            event = {
                "id": self._seq,
                "at": (_time or time.time()),
                "kind": kind,
                "topic": topic,
                "actor": actor,
                "payload": dict(payload or {}),
            }
            self._events.append(event)
        self._mirror_redis(event)
        return event

    def _mirror_redis(self, event: Dict[str, Any]) -> None:
        """Optional cross-process notification; never blocks or raises."""
        try:
            from core.redis_state import redis_sync
            if redis_sync.enabled:
                redis_sync.publish_snapshot("events", {
                    "kind": event["kind"],
                    "topic": event["topic"],
                    "actor": event["actor"],
                    "payload": event["payload"],
                })
        except Exception:  # noqa: BLE001
            pass

    # -- consumption ------------------------------------------------------
    def since(self, after: int = 0, topic: Optional[str] = None) -> List[Dict]:
        """Events with id > `after`, newest-last; optionally filtered."""
        with self._lock:
            rows = [dict(e) for e in self._events if e["id"] > after]
        if topic:
            rows = [e for e in rows if e["topic"] == topic]
        return rows

    @property
    def latest(self) -> int:
        with self._lock:
            return self._seq


event_feed = EventFeed()
