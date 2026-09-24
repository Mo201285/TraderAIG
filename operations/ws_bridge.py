"""Real-time MT5 bridge channel (WebSocket) — server side of the wire-up.

Topology (production): the API holds the decision plane; a terminal-side
proxy (`scripts/mt5_bridge_proxy.py`) keeps a WebSocket to ``/bridge/ws`` and
receives APPROVED signal frames in real time, then writes them through the
existing file bridge so the EA executes exactly as before. Acks and terminal
status stream back over the same socket. The file bridge stays authoritative;
this channel is the real-time transport on top of it.

Wire contract (JSON frames, ``msg`` discriminator):
  server → client  hello   {session_id}
                   signal  {topic, payload, sent_at}
                   pong    {}                 (reply to client ping)
                   error   {error, code?}
  client → server  hello   {role: "terminal"}
                   ping    {}
                   ack     {payload: {candidate_id, accepted, ...}}
                   status  {payload: {..terminal snapshot..}}
                   error   {payload: {error, ...}}

Single-authority rule: the server is the only producer of ``signal`` frames;
a client-sent ``signal`` is reported as an error, never relayed.
"""
from __future__ import annotations

import asyncio
import os
import threading
import time
import uuid
from typing import Any, Dict, Optional

from core.logging import get_logger


log = get_logger("operations.ws_bridge")

BRIDGE_TOKEN_ENV = "TRADERAIG_BRIDGE_TOKEN"

QUEUE_CAPACITY = 256

CLIENT_MSGS = frozenset({"hello", "ping", "ack", "status", "error"})
SIGNAL_TOPIC = "signals"


def _now() -> float:
    return time.time()


def token_ok(candidate: Optional[str]) -> bool:
    """Allow the connection only when a configured token is matched.

    Empty server token means the bridge is open (zero-config local/dev use).
    """
    expected = os.getenv(BRIDGE_TOKEN_ENV, "")
    if not expected:
        return True
    return bool(candidate) and candidate == expected


class BridgeSession:
    """One connected terminal proxy. Not thread-safe; must be used on the
    event-loop thread (methods simply collect state for the hub)."""

    def __init__(self, session_id: str, loop: "asyncio.AbstractEventLoop") -> None:
        self.id = session_id
        self.loop = loop
        self.role = "terminal"
        self.connected_at = _now()
        self.last_seen = self.connected_at
        self.queue: "asyncio.Queue[Optional[Dict[str, Any]]]" = (
            asyncio.Queue(maxsize=QUEUE_CAPACITY)
        )
        self.last_status: Optional[Dict[str, Any]] = None
        self.last_ack: Optional[Dict[str, Any]] = None
        self.closed = False

    def enqueue(self, frame: Dict[str, Any]) -> bool:
        """Push a server→client frame. Safe to call from any thread."""
        if self.closed:
            return False
        try:
            self.loop.call_soon_threadsafe(self.queue.put_nowait, frame)
            return True
        except (RuntimeError, asyncio.QueueFull):
            if self.closed:
                return False
            log.warning(f"bridge session {self.id}: queue full, dropping frame")
            return False


class BridgeHub:
    """Thread-safe registry of connected bridge sessions + signal fan-out."""

    def __init__(self) -> None:
        self._sessions: Dict[str, BridgeSession] = {}
        self._lock = threading.RLock()

    def register(self, session_id: Optional[str] = None,
                 loop: Optional["asyncio.AbstractEventLoop"] = None) -> BridgeSession:
        session = BridgeSession(session_id or uuid.uuid4().hex[:12], loop)
        with self._lock:
            self._sessions[session.id] = session
        log.info(f"bridge session {session.id}: connected")
        return session

    def unregister(self, session_id: str) -> None:
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is not None:
            session.closed = True
            log.info(f"bridge session {session_id}: disconnected")

    def get(self, session_id: str) -> Optional[BridgeSession]:
        with self._lock:
            return self._sessions.get(session_id)

    def set_role(self, session_id: str, role: str) -> None:
        session = self.get(session_id)
        if session is not None:
            session.role = role or "terminal"

    def touch(self, session_id: str) -> None:
        session = self.get(session_id)
        if session is not None:
            session.last_seen = _now()

    def record(self, session_id: str, msg: str, frame: Dict[str, Any]) -> None:
        """Fold client acks/status into the session for /bridge/status."""
        session = self.get(session_id)
        if session is None:
            return
        payload = frame.get("payload")
        if msg == "ack":
            session.last_ack = payload if isinstance(payload, dict) else frame
        elif msg == "status":
            session.last_status = payload if isinstance(payload, dict) else frame

    def publish(self, topic: str, frame: Dict[str, Any]) -> int:
        """Broadcast a server→client frame to every live session."""
        with self._lock:
            targets = list(self._sessions.values())
        delivered = 0
        for session in targets:
            if session.enqueue(frame):
                delivered += 1
        if delivered:
            log.debug(f"bridge publish topic={topic} delivered={delivered}")
        return delivered

    def status(self) -> Dict[str, Any]:
        with self._lock:
            sessions = [
                {
                    "id": s.id,
                    "role": s.role,
                    "connected_at": s.connected_at,
                    "last_seen": s.last_seen,
                    "last_ack": s.last_ack,
                    "last_status": s.last_status,
                }
                for s in self._sessions.values()
            ]
        return {
            "open": bool(self._sessions),
            "sessions": sessions,
            "token_required": bool(os.getenv(BRIDGE_TOKEN_ENV, "")),
        }

    def clear(self) -> None:
        with self._lock:
            for session in self._sessions.values():
                session.closed = True
            self._sessions.clear()


hub = BridgeHub()
