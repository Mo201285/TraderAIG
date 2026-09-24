"""Minimal macro context updater for live/runtime use.

Keeps MacroSchool fed with a small, deterministic snapshot without
embedding fetch logic into the school itself. This version is intentionally
lightweight: it reads environment hints, maintains freshness metadata, and
can infer a coarse risk regime from known event windows configured by the
caller.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Optional, Sequence

from core.logging import get_logger
from schools.macro import EconomicEvent, macro_school

log = get_logger("operations.macro_feed")


@dataclass
class MacroSnapshot:
    risk_off: bool
    risk_on: bool
    dxy_trend: str
    rates_up: bool
    updated_at: float
    source_status: str
    stale_seconds: float
    event_count: int


class MacroContextUpdater:
    """Refreshes MacroSchool context on a fixed cadence."""

    def __init__(self, refresh_seconds: float = 300.0) -> None:
        self.refresh_seconds = refresh_seconds
        self._last_snapshot: Optional[MacroSnapshot] = None
        self._last_events: list[EconomicEvent] = []

    def set_calendar(self, events: Sequence[EconomicEvent]) -> None:
        self._last_events = list(events)
        macro_school.set_calendar(self._last_events)

    def refresh(self, now: Optional[float] = None,
                force: bool = False) -> MacroSnapshot:
        now = now or time.time()
        if not force and self._last_snapshot and \
                now - self._last_snapshot.updated_at < self.refresh_seconds:
            snap = self._last_snapshot
            snap.stale_seconds = max(0.0, now - snap.updated_at)
            return snap

        risk_mode = os.getenv("TRADERAIG_MACRO_RISK_MODE", "neutral").strip().lower()
        dxy_trend = os.getenv("TRADERAIG_DXY_TREND", "flat").strip().lower()
        rates_up = os.getenv("TRADERAIG_RATES_UP", "0").strip().lower() in ("1", "true", "yes", "on")

        risk_off = risk_mode == "risk_off"
        risk_on = risk_mode == "risk_on"
        macro_school.set_context(risk_off=risk_off, risk_on=risk_on,
                                 dxy_trend=dxy_trend, rates_up=rates_up)
        if self._last_events:
            macro_school.set_calendar(self._last_events)

        snap = MacroSnapshot(
            risk_off=risk_off,
            risk_on=risk_on,
            dxy_trend=dxy_trend if dxy_trend in ("up", "down", "flat") else "flat",
            rates_up=rates_up,
            updated_at=now,
            source_status="env_runtime",
            stale_seconds=0.0,
            event_count=len(self._last_events),
        )
        self._last_snapshot = snap
        log.debug(f"Macro context refreshed: risk_mode={risk_mode} dxy={snap.dxy_trend} events={snap.event_count}")
        return snap

    def status(self, now: Optional[float] = None) -> dict:
        now = now or time.time()
        if self._last_snapshot is None:
            return {"configured": False, "source_status": "uninitialized"}
        snap = self._last_snapshot
        return {
            "configured": True,
            "risk_off": snap.risk_off,
            "risk_on": snap.risk_on,
            "dxy_trend": snap.dxy_trend,
            "rates_up": snap.rates_up,
            "updated_at": snap.updated_at,
            "stale_seconds": max(0.0, now - snap.updated_at),
            "source_status": snap.source_status,
            "event_count": snap.event_count,
        }


macro_updater = MacroContextUpdater()
