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


class MT5Bridge:
    """File-based signal bridge to the MT5 terminal."""

    def __init__(self, filename: str = "TraderAIG_bridge.json",
                 directory: Optional[str] = None) -> None:
        self.filename = filename
        self.directory = directory or self._default_directory()

    def _default_directory(self) -> str:
        # Prefer a configured common-data path; otherwise use settings.root.
        env = os.getenv("MT5_COMMON_DATA")
        if env:
            return env
        return str(settings.root_dir / "bridge")

    @property
    def bridge_file(self) -> Path:
        return Path(self.directory) / self.filename

    def send_signal(self, candidate: TradeCandidate,
                    fill_hint: Optional[float] = None) -> bool:
        """Write an APPROVED candidate as a JSON command for the EA."""
        payload = {
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
        try:
            self.bridge_file.parent.mkdir(parents=True, exist_ok=True)
            self.bridge_file.write_text(
                json.dumps(payload, indent=2), encoding="utf-8"
            )
            log.info(f"Bridge signal sent: {candidate.symbol} "
                     f"{payload['action']} vol={payload['volume']}")
            return True
        except OSError as exc:
            log.error(f"Bridge write failed: {exc}")
            return False

    def read_status(self) -> Optional[Dict]:
        """Read the EA's latest status ack."""
        try:
            if not self.bridge_file.exists():
                return None
            return json.loads(self.bridge_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None


bridge = MT5Bridge()
