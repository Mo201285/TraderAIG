"""Redis-backed synchronization for canonical state.

Publishes state snapshots to a Redis channel and refreshes a local
cache keyed per entity. Designed to be optional: when Redis is
unreachable the system degrades to in-memory canonical state only.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional

from core.config import settings
from core.logging import get_logger


log = get_logger("core.redis_state")


class RedisStateSync:
    """Optional publisher/subscriber for canonical state changes.

    Not a source of truth — the source is always the CanonicalState
    store. Redis only carries notifications so other processes
    (dashboards, copy engines, risk consoles) can follow changes.
    """

    PREFIX = "traderaig:state"

    def __init__(self, url: Optional[str] = None) -> None:
        self._client = None
        self._available = False
        if os.getenv("TRADERAIG_STATE_REDIS", "1") in ("0", "false", "no"):
            log.info("Redis state sync disabled via env")
            return
        try:
            import redis
            self._client = redis.Redis.from_url(url or settings.redis.url,
                                                socket_connect_timeout=1)
            self._client.ping()
            self._available = True
            log.info("Redis state sync connected")
        except Exception as exc:  # noqa: BLE001
            log.warning(f"Redis unavailable, state sync disabled: {exc}")

    @property
    def enabled(self) -> bool:
        return self._available

    # -- Publish -------------------------------------------------
    def publish_snapshot(self, key: str, obj: Any) -> None:
        """Publish a JSON snapshot of `obj` to Redis."""
        if not self._available:
            return
        try:
            payload = json.dumps({
                "type": key,
                "timestamp": time.time(),
                "data": obj.as_dict() if hasattr(obj, "as_dict") else obj,
            }, default=str)
            self._client.publish(f"{self.PREFIX}:{key}", payload)
        except Exception as exc:  # noqa: BLE001
            log.debug(f"Redis publish failed for {key}: {exc}")

    # -- Cache helpers -------------------------------------------
    def cache_set(self, key: str, obj: Any, ttl: int = 60) -> None:
        if not self._available:
            return
        try:
            payload = json.dumps(
                obj.as_dict() if hasattr(obj, "as_dict") else obj, default=str
            )
            self._client.setex(f"{self.PREFIX}:cache:{key}", ttl, payload)
        except Exception as exc:  # noqa: BLE001
            log.debug(f"Redis cache_set failed for {key}: {exc}")

    def cache_get(self, key: str) -> Optional[Dict]:
        if not self._available:
            return None
        try:
            raw = self._client.get(f"{self.PREFIX}:cache:{key}")
            return json.loads(raw) if raw else None
        except Exception as exc:  # noqa: BLE001
            log.debug(f"Redis cache_get failed for {key}: {exc}")
            return None

    def flush_state_keys(self) -> None:
        """Drop all traderaig state keys (used at reset)."""
        if not self._available:
            return
        try:
            for k in self._client.scan_iter(match=f"{self.PREFIX}:*", count=100):
                self._client.delete(k)
        except Exception as exc:  # noqa: BLE001
            log.debug(f"Redis flush failed: {exc}")


redis_sync = RedisStateSync()
