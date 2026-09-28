"""Terminal market bridge ingest (Phase B — 28.6, offline/file transport).

The real-time WebSocket channel (`operations/ws_bridge.py` ``market`` frames)
is the fast path. This module is the *file* path: the MQL5 EA writes one
`<SYMBOL>.json` frame per symbol into the bridge `market/` directory, and this
poller reads those frames into the canonical market plane.

Why both: the file bridge is the channel that already works with zero
infrastructure (no proxy, no socket), and it survives a terminal restart. The
plane is the single read path, so a frame that arrives either way becomes the
same quote/window with the same precedence.

Boundaries that are deliberate:
  * The backend never *writes* a market frame — prices are only ever read from
    the terminal side, so no server code path can invent a price.
  * Frames are ingested as `bridge` (priority 50): below `mt5` (100) and `cex`
    (90), so a file frame can never overwrite a live terminal or venue window.
  * Every frame is validated by the plane field-by-field; a frame missing real
    values is counted as rejected with its reason, never defaulted.
  * Off by default (`TRADERAIG_MARKET_BRIDGE=1`): an inert directory is not a
    reason to poll a disk forever.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from typing import Any, Dict, Optional

from core.logging import get_logger
from core.market_plane import market_plane
from execution.bridge import MT5Bridge, bridge


log = get_logger("operations.market_bridge")

MARKET_BRIDGE_ENV = "TRADERAIG_MARKET_BRIDGE"
MAX_TRACKED_REJECTIONS = 20


class MarketBridge:
    """Polls terminal market frames and ingests them into the plane."""

    def __init__(self, bridge_source: Optional[MT5Bridge] = None,
                 plane: Optional[Any] = None) -> None:
        self._bridge = bridge_source or bridge
        self._plane = plane if plane is not None else market_plane
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._active = False
        self._passes = 0
        self._frames_seen = 0
        self._frames_ingested = 0
        self._frames_unchanged = 0
        self._bars_ingested = 0
        self._quotes_ingested = 0
        self._shadowed = 0
        self._last_pass_at: float = 0.0
        self._last_error: str = ""
        self._rejections: list = []
        self._stamps: Dict[str, str] = {}

    # -- one pass -------------------------------------------------------
    def ingest_once(self) -> Dict[str, Any]:
        """Read the market directory once and ingest whatever is there.

        Never raises: a missing directory, a locked file or a malformed frame
        is recorded and skipped, because a market poller must not be able to
        take the process down.

        A frame whose content is identical to the last pass is counted as
        `unchanged` and not re-ingested: the plane upserts by bar time, so
        re-reading the same values is pure work, and re-counting it would make
        "frames ingested" claim a terminal update that never happened.

        The stamp is a hash of the frame content, not the file's mtime: a
        terminal that rewrites a frame with a different price of the same
        string length (`2400.0` -> `2401.0`) inside one filesystem timestamp
        tick would otherwise look untouched and its update would be dropped.
        """
        result = {"seen": 0, "ingested": 0, "bars": 0, "quotes": 0,
                  "rejected": 0, "shadowed": 0, "unchanged": 0}
        try:
            frames = self._bridge.read_market_frames()
        except Exception as exc:  # noqa: BLE001
            self._last_error = str(exc)
            log.warning(f"market bridge read failed: {exc}")
            return result
        self._last_error = ""
        for symbol, payload in frames.items():
            result["seen"] += 1
            stamp = self._stamp(payload)
            if self._stamps.get(symbol) == stamp:
                result["unchanged"] += 1
                self._frames_unchanged += 1
                continue
            try:
                got = self._plane.ingest_bridge_frame(
                    payload, source="bridge:file")
            except Exception as exc:  # noqa: BLE001
                self._note_rejection(symbol, str(exc))
                result["rejected"] += 1
                continue
            if got.get("rejected"):
                self._note_rejection(symbol, str(got["rejected"]))
                result["rejected"] += 1
                # a rejected frame keeps its stamp: re-reading the same broken
                # bytes every pass would only fill the rejection log
                self._stamps[symbol] = stamp
                continue
            self._stamps[symbol] = stamp
            result["ingested"] += 1
            result["bars"] += int(got.get("bars") or 0)
            if got.get("quote"):
                result["quotes"] += 1
            win = self._plane.window(symbol, got.get("timeframe") or "M1")
            if win is not None and win.shadowed:
                result["shadowed"] += len(win.shadowed)
        self._passes += 1
        self._frames_seen += result["seen"]
        self._frames_ingested += result["ingested"]
        self._bars_ingested += result["bars"]
        self._quotes_ingested += result["quotes"]
        self._shadowed += result["shadowed"]
        self._last_pass_at = self._now()
        return result

    @staticmethod
    def _stamp(payload: Dict[str, Any]) -> str:
        """Content hash of a frame: the only change signal that cannot lie.

        Not mtime/size: a rewrite with a same-length value inside one
        filesystem timestamp tick is byte-identical in those two fields, and
        the terminal's real price update would then be skipped as "unchanged".
        """
        try:
            blob = json.dumps(payload, sort_keys=True, default=str)
        except (TypeError, ValueError):
            blob = repr(sorted(payload.items(), key=lambda kv: str(kv[0])))
        return hashlib.sha1(blob.encode("utf-8", "replace")).hexdigest()

    @staticmethod
    def _now() -> float:
        import time

        return time.time()

    def _note_rejection(self, symbol: str, reason: str) -> None:
        self._rejections.append({"symbol": symbol, "reason": reason,
                                 "at": self._now()})
        del self._rejections[:-MAX_TRACKED_REJECTIONS]
        log.warning(f"market bridge frame rejected symbol={symbol}: {reason}")

    # -- lifecycle ------------------------------------------------------
    @staticmethod
    def enabled_by_env() -> bool:
        return os.getenv(MARKET_BRIDGE_ENV, "").strip().lower() in (
            "1", "true", "yes", "on")

    def start(self, interval_seconds: float = 2.0) -> bool:
        """Start the background poller (idempotent)."""
        if self._active:
            return True
        self._stop.clear()
        interval = max(0.5, float(interval_seconds))

        def _run() -> None:
            while not self._stop.is_set():
                try:
                    self.ingest_once()
                except Exception:  # noqa: BLE001
                    log.exception("market bridge pass failed")
                self._stop.wait(interval)

        self._active = True
        self._thread = threading.Thread(target=_run, name="market-bridge",
                                        daemon=True)
        self._thread.start()
        log.info(f"market bridge poller started interval={interval}s")
        return True

    def stop(self) -> bool:
        if not self._active:
            return False
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._active = False
        self._thread = None
        log.info("market bridge poller stopped")
        return True

    def status(self) -> Dict[str, Any]:
        """Real ingest counters for the operator surface (never fabricated)."""
        return {
            "enabled_by_env": self.enabled_by_env(),
            "active": self._active,
            "directory": str(self._bridge.market_directory),
            "passes": self._passes,
            "frames_seen": self._frames_seen,
            "frames_ingested": self._frames_ingested,
            "frames_unchanged": self._frames_unchanged,
            "bars_ingested": self._bars_ingested,
            "quotes_ingested": self._quotes_ingested,
            "shadowed": self._shadowed,
            "last_pass_at": self._last_pass_at or None,
            "last_error": self._last_error or None,
            "rejections": self._rejections[-5:],
        }


market_bridge = MarketBridge()
