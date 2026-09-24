"""Macro / Intermarket school (GATE tier, hard authority).

External forces (rates, dollar, global liquidity, news) that exceed any
technical pattern. This is the only school with an *explicit* veto: a
candidate that strongly conflicts with the macro context, or that sits
inside a high-impact event blackout window, is rejected before it even
reaches the statistical gate or the Risk Governor.

Learning key (meta): `missed_blackout_count` - how many times the system
failed to block a trade that the macro context says it should have. This
must be watched first, it is the highest documented financial-risk gap.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from core.contracts import Candle, RegimeSnapshot, TradeDirection
from core.logging import get_logger

from .base import (School, SchoolEvidence, SchoolTier, SchoolVerdict,
                   SchoolZone, Suggestion, VerdictKind)

log = get_logger("schools.macro")

BLACKOUT_MINUTES = 30.0


@dataclass
class EconomicEvent:
    label: str
    start: float
    end: float
    impact: str = "high"          # high | medium | low
    symbol: str = "ALL"           # which instruments affected

    def active_at(self, ts: float) -> bool:
        return self.start <= ts <= self.end


@dataclass
class MacroContext:
    risk_off: bool = False
    risk_on: bool = False
    dxy_trend: str = "flat"       # up | down | flat
    rates_up: bool = False
    calendar: List[EconomicEvent] = field(default_factory=list)
    note: str = "live news feed is a stub: calendar injected via set_calendar()"


class MacroSchool(School):
    school_id = "macro"
    name = "Macro / Intermarket"
    tier = SchoolTier.GATE

    def __init__(self) -> None:
        super().__init__()
        self._context = MacroContext()
        self.blackout_interventions: int = 0

    def set_context(self, **kwargs) -> None:
        for k, v in kwargs.items():
            if hasattr(self._context, k):
                setattr(self._context, k, v)

    def set_calendar(self, events: Sequence[EconomicEvent]) -> None:
        self._context.calendar = list(events)

    def evaluate(self, candles: Sequence[Candle], symbol: str,
                 regime: Optional[RegimeSnapshot] = None,
                 zones_from_others: Optional[Sequence[SchoolZone]] = None,
                 now: Optional[float] = None) -> SchoolEvidence:
        evid = self._evid(symbol, now)
        ts = now if now is not None else (candles[-1].time if candles else None)
        if ts is None:
            evid.verdict = SchoolVerdict(kind=VerdictKind.PASS,
                                         reason="no timestamp", authority="advisory")
            return evid

        active = [e for e in self._context.calendar
                  if (e.symbol == "ALL" or e.symbol == symbol) and e.active_at(ts)]
        if active:
            self.blackout_interventions += 1
            latest = active[-1]
            evid.verdict = SchoolVerdict(
                kind=VerdictKind.REJECT, authority="hard",
                reason=f"economic_blackout: {latest.label} ({latest.impact}, "
                       f"{latest.start:.0f}-{latest.end:.0f})",
                meta={"lesson_key": "missed_blackout_count",
                      "event": latest.label, "impact": latest.impact,
                      "blocked_during": bool(zones_from_others)})
        else:
            evid.verdict = SchoolVerdict(
                kind=VerdictKind.PASS, authority="hard",
                reason="no high-impact event in window",
                size_multiplier=self._cross_asset_multiplier(None),
                meta={"lesson_key": "missed_blackout_count"})
        evid.meta = {"risk_off": self._context.risk_off,
                     "dxy": self._context.dxy_trend,
                     "rates_up": self._context.rates_up,
                     "blackout_interventions": self.blackout_interventions,
                     "context_note": self._context.note}
        return evid

    def gate(self, suggestion: Suggestion, now: Optional[float] = None) -> SchoolVerdict:
        """Candidate-level hard check (alignment + cross-asset lift)."""
        if self._context.risk_off and suggestion.direction == TradeDirection.LONG:
            return SchoolVerdict(kind=VerdictKind.REJECT, authority="hard",
                                 reason="macro misalignment (risk-off vs long)",
                                 meta={"lesson_key": "missed_blackout_count"})
        if self._context.risk_on and suggestion.direction == TradeDirection.SHORT:
            return SchoolVerdict(kind=VerdictKind.REJECT, authority="hard",
                                 reason="macro misalignment (risk-on vs short)",
                                 meta={"lesson_key": "missed_blackout_count"})
        return SchoolVerdict(kind=VerdictKind.PASS, authority="hard",
                             reason="aligned with macro context",
                             size_multiplier=self._cross_asset_multiplier(suggestion),
                             meta={"lesson_key": "missed_blackout_count"})

    def _cross_asset_multiplier(self, suggestion: Optional[Suggestion]) -> float:
        s = suggestion
        if s is None:
            return 1.0
        if self._context.dxy_trend == "down" and s.direction == TradeDirection.LONG:
            return 1.05
        if self._context.dxy_trend == "up" and s.direction == TradeDirection.SHORT:
            return 1.05
        return 1.0

    def eligibility(self, regime: Optional[RegimeSnapshot]) -> bool:
        return True


macro_school = MacroSchool()
