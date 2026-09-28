"""MT5 Bridge: writes approved trade signals to the shared JSON file.

The EA (TraderAIG.mq5) polls this file, enforces its own local risk
ceiling, and executes. The bridge is deliberately thin: no decisions
happen here, only approved candidate transport.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Dict, Optional

from core.config import settings
from core.logging import get_logger
from decision.candidate import TradeCandidate


log = get_logger("execution.bridge")


def terminal_common_files() -> Optional[Path]:
    """The real terminal common-data `Files` dir on Windows, else None.

    `%APPDATA%\\MetaQuotes\\Terminal\\Common\\Files` is where the EA's
    `FILE_COMMON` writes land. It is the only directory a real host should
    read market frames from, so it is worth detecting rather than assuming.
    """
    appdata = os.getenv("APPDATA")
    if os.name != "nt" or not appdata:
        return None
    candidate = Path(appdata) / "MetaQuotes" / "Terminal" / "Common" / "Files"
    return candidate if candidate.is_dir() else None


class MT5Bridge:
    """File-based signal bridge to the MT5 terminal."""

    def __init__(self, filename: str = "TraderAIG_bridge.json",
                 directory: Optional[str] = None,
                 market_subdir: str = "market") -> None:
        self.filename = filename
        self._explicit_directory = directory is not None
        self.directory = directory or self._default_directory()
        # Market frames live in their own directory and their own files: the
        # signal file stays the single authority for approved orders, so a
        # market publisher can never overwrite (or be overwritten by) a signal.
        self.market_subdir = market_subdir

    def _default_directory(self) -> str:
        # Prefer a configured common-data path; otherwise use settings.root.
        env = os.getenv("MT5_COMMON_DATA")
        if env:
            return env
        return str(settings.root_dir / "bridge")

    @property
    def bridge_file(self) -> Path:
        return Path(self.directory) / self.filename

    @property
    def market_directory(self) -> Path:
        """Where market frames are read from.

        An explicitly passed directory always wins (tests, scratch proofs, a
        second instance). Otherwise, with no `MT5_COMMON_DATA` set, a real
        Windows terminal's `Common\\Files` beats the developer `bridge/` path:
        otherwise the poller runs happily against an empty directory and ingests
        nothing while the EA publishes perfectly - a silent 24/7 outage.
        The signal file is deliberately NOT redirected; only market reads move.
        """
        if not self._explicit_directory and not os.getenv("MT5_COMMON_DATA"):
            common = terminal_common_files()
            if common is not None:
                return common / self.market_subdir
        return Path(self.directory) / self.market_subdir

    def send_signal(self, candidate: TradeCandidate,
                    fill_hint: Optional[float] = None) -> bool:
        """Write an APPROVED candidate as a JSON command for the EA."""
        payload = self._payload(candidate, fill_hint)
        ok = self.send_signal_frame(payload)
        if ok:
            from operations.ws_bridge import hub, SIGNAL_TOPIC
            hub.publish(SIGNAL_TOPIC, {
                "msg": "signal",
                "topic": SIGNAL_TOPIC,
                "payload": payload,
                "sent_at": time.time(),
            })
        return ok

    def send_signal_frame(self, payload: Dict) -> bool:
        """Write an already-stamped signal payload to the bridge file.

        Used by the terminal-side proxy, which received the payload over the
        WebSocket channel and is relaying it through the *same* file the EA
        polls — so the real-time path and the offline path share one wire.
        """
        try:
            self.bridge_file.parent.mkdir(parents=True, exist_ok=True)
            self.bridge_file.write_text(
                json.dumps(payload, indent=2), encoding="utf-8"
            )
            log.info(f"Bridge signal written: {payload.get('symbol')} "
                     f"{payload.get('action')} vol={payload.get('volume')}")
            return True
        except OSError as exc:
            log.error(f"Bridge write failed: {exc}")
            return False

    def _payload(self, candidate: TradeCandidate,
                 fill_hint: Optional[float] = None) -> Dict:
        return {
            "signal": "trade",
            "symbol": candidate.symbol,
            "action": "buy" if candidate.direction.value == "long" else "sell",
            "volume": round(candidate.size, 2),
            "sl": candidate.stop_loss,
            "tp": candidate.take_profit,
            "price": candidate.entry if fill_hint is None else fill_hint,
            "candidate_id": candidate.candidate_id,
            "sent_at": time.time(),
        }

    def read_status(self) -> Optional[Dict]:
        """Read the EA's latest status ack."""
        try:
            if not self.bridge_file.exists():
                return None
            return json.loads(self.bridge_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    # -- market transport (28.6) ----------------------------------------
    def write_market_frame(self, payload: Dict) -> bool:
        """Write one terminal market frame (tick and/or bar) for the plane.

        One file per symbol, written atomically (temp + replace) so the backend
        can never read a half-written frame. The caller is the EA/proxy; the
        backend only ever *reads* these files, so a frame can never be invented
        on this side of the wire.
        """
        symbol = str(payload.get("symbol") or "").strip().upper()
        if not symbol:
            log.warning("Bridge market frame rejected: no symbol")
            return False
        try:
            self.market_directory.mkdir(parents=True, exist_ok=True)
            target = self.market_directory / f"{symbol}.json"
            tmp = target.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            os.replace(str(tmp), str(target))
            return True
        except OSError as exc:
            log.error(f"Bridge market write failed for {symbol}: {exc}")
            return False

    def read_market_frames(self) -> Dict[str, Dict]:
        """Read every terminal market frame on disk, keyed by symbol.

        A malformed or unreadable file is skipped (never guessed at); the
        plane's ingest is the only thing that turns these into market state.
        """
        frames: Dict[str, Dict] = {}
        try:
            files = sorted(self.market_directory.glob("*.json"))
        except OSError:
            return frames
        for path in files:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                log.warning(f"Bridge market frame unreadable: {path.name} ({exc})")
                continue
            if isinstance(payload, dict) and payload.get("symbol"):
                frames[str(payload["symbol"]).strip().upper()] = payload
        return frames


bridge = MT5Bridge()
