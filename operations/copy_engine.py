"""Copy-engine consumer for the operations event feed.

Consumes promotion/quarantine transitions and change decisions off the shared
event feed and mirrors them into a follower view of the master portfolio.
This is a *consumer* of the feed (the same stream the dashboard reads, and the
same stream Redis mirrors cross-process); it never mutates the master registry
— followers observe and append an overrides trail when a later decision
contradicts an earlier one (governance disputes).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from operations.event_feed import EventFeed, event_feed as default_feed


class CopyEngine:
    """Reads feed events; mirrors registry state into a follower portfolio."""

    def __init__(self, feed: Optional[EventFeed] = None) -> None:
        self._feed = feed or default_feed
        self._cursor = 0
        self._follower: Dict[str, Dict[str, Any]] = {}
        self._overrides: List[Dict[str, Any]] = []
        self._decisions = 0

    # -- consumption ------------------------------------------------------
    def consume(self, topic: Optional[str] = None) -> int:
        """Apply any new feed events; returns how many were consumed."""
        events = self._feed.since(after=self._cursor, topic=topic)
        for e in events:
            self._apply(e)
            self._cursor = max(self._cursor, e["id"])
        return len(events)

    def _apply(self, event: Dict[str, Any]) -> None:
        topic, kind = event["topic"], event["kind"]
        payload = event.get("payload", {})
        if topic == "registry" and kind == "transition":
            self._mirror(payload.get("strategy_id"), {
                "state": payload.get("to_stage"),
                "event": "transition",
                "actor": event["actor"],
                "reason": payload.get("reason", ""),
                "at": event["at"],
            })
            self._decisions += 1
        elif topic == "change" and kind == "decided":
            self._mirror(payload.get("target"), {
                "state": payload.get("outcome"),
                "event": "change_decided",
                "actor": event["actor"],
                "reason": payload.get("reason", ""),
                "at": event["at"],
            })
            self._decisions += 1

    def _mirror(self, key: str, entry: Dict[str, Any]) -> None:
        if not key:
            return
        if key in self._follower:
            previous = self._follower[key]
            new_state = entry.get("state")
            if previous.get("state") and new_state and new_state != previous["state"]:
                # A flip within a short window (e.g. promote then quarantine)
                # is a governance dispute worth surfacing to the operator.
                self._overrides.append({
                    **entry,
                    "key": key,
                    "previous_state": previous["state"],
                })
        self._follower[key] = entry

    # -- read -------------------------------------------------------------
    def follower_portfolio(self) -> Dict[str, Any]:
        return {
            "decisions_consumed": self._decisions,
            "cursor": self._cursor,
            "strategies": dict(self._follower),
            "overrides": list(self._overrides),
        }

    def reset(self) -> None:
        self._cursor = 0
        self._follower.clear()
        self._overrides.clear()
        self._decisions = 0


copy_engine = CopyEngine()
