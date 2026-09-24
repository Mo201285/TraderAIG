"""Volume / Order Flow school (CONFIRMATION tier).

Whether the move is real: actual participation behind price, or a price
vacuum. Active only on instruments that provide volume data
(real volume preferred, tick volume as best effort); otherwise the school
disables itself instead of inventing false confirmation. Never a standalone
entry source.

Learning key (meta): `data_quality` - per-symbol periodic data-suitability
test, not a permanent assumption.
"""
from __future__ import annotations

from statistics import median
from typing import Optional, Sequence

from core.contracts import Candle, RegimeSnapshot, TradeDirection
from core.logging import get_logger

from .base import (School, SchoolEvidence, SchoolSignal, SchoolTier,
                   SchoolVerdict, SchoolZone, VerdictKind)

log = get_logger("schools.volume")


def _has_volume(candles: Sequence[Candle]) -> bool:
    return any(max(c.volume, c.tick_volume) > 0 for c in candles[-20:])


class VolumeFlowSchool(School):
    school_id = "volume_flow"
    name = "Volume / Order Flow"
    tier = SchoolTier.CONFIRMATION

    def evaluate(self, candles: Sequence[Candle], symbol: str,
                 regime: Optional[RegimeSnapshot] = None,
                 zones_from_others: Optional[Sequence[SchoolZone]] = None,
                 now: Optional[float] = None) -> SchoolEvidence:
        evid = self._evid(symbol, now)
        if len(candles) < 8:
            evid.data_available = False
            evid.verdict = self._disabled("insufficient data")
            return evid

        if not _has_volume(candles):
            evid.data_available = False
            evid.verdict = self._disabled(
                "no volume data for symbol - school excluded per data_availability")
            return evid

        vols = [max(c.volume, c.tick_volume) for c in candles[-20:]]
        med_vol = median(vols) or 1.0
        med_range = median([c.range for c in candles[-20:] if c.range > 0]) or 1e-9

        # delta proxy over the last window (close-side participation)
        delta_1 = sum(v if c.is_bullish else -v
                      for c, v in zip(candles[-5:], vols[-5:]))
        delta_2 = sum(v if c.is_bullish else -v
                      for c, v in zip(candles[-10:-5], vols[-10:-5]))

        price = candles[-1].close
        zones = list(zones_from_others) if zones_from_others else []
        attention = [z for z in zones if z.role in ("entry", "objective", "invalidation")]
        occupied = [z for z in attention if z.contains(price)]

        # absorption: heavy volume, tiny result, right at a key zone
        last = candles[-1]
        if last.volume > 0 and last.range > 0 and \
                last.volume > 1.5 * med_vol and last.range < 0.4 * med_range:
            for z in occupied:
                evid.signals.append(SchoolSignal(
                    name="absorption", direction=TradeDirection.SHORT
                    if last.is_bullish else TradeDirection.LONG,
                    strength=0.5, anchor=f"vol:{len(candles)}:{z.zone_type}",
                    pattern="absorption_reversal",
                    meta={"zone": z.zone_type, "lesson_key": "data_quality"}))
                evid.zones.append(SchoolZone(
                    "absorption", last.high, last.low,
                    role="invalidation" if last.close < last.open else "entry",
                    meta={"lesson_key": "data_quality"}))
        # a wide candle: did it leave a zone with participation, or on a vacuum?
        elif last.range > 1.5 * med_range:
            for z in attention:
                broke_above = last.close > z.top and last.low <= z.top
                broke_below = last.close < z.bottom and last.high >= z.bottom
                if not (broke_above or broke_below):
                    continue
                if last.volume > 1.5 * med_vol:
                    d = TradeDirection.LONG if broke_above else TradeDirection.SHORT
                    evid.signals.append(SchoolSignal(
                        name="volume_breakout", direction=d, strength=0.5,
                        anchor=f"vol:{len(candles)}:{z.zone_type}",
                        pattern="volume_breakout",
                        meta={"break": "above" if broke_above else "below",
                              "lesson_key": "data_quality"}))
                    evid.zones.append(SchoolZone(
                        "breakout", last.high, last.low, role="entry",
                        meta={"lesson_key": "data_quality"}))
                elif last.volume < 0.6 * med_vol:
                    evid.signals.append(SchoolSignal(
                        name="vacuum_warning", direction=TradeDirection.FLAT,
                        strength=0.2, anchor=f"vol:{len(candles)}:{z.zone_type}",
                        pattern="vacuum_trap",
                        meta={"break": "above" if broke_above else "below",
                              "lesson_key": "data_quality"}))

        evid.confidence = max((s.strength for s in evid.signals), default=0.0)
        directional = [s for s in evid.signals
                       if s.direction in (TradeDirection.LONG, TradeDirection.SHORT)]
        if directional:
            evid.bias = max(directional, key=lambda s: s.strength).direction
        delta = delta_1 - delta_2
        evid.meta = {"delta_proxy": delta, "data_source": "tick",
                     "data_quality": "tick_derived",
                     "lesson_key": "data_quality",
                     "early_warning": abs(delta) > 0.5 * max(abs(delta_2), 1e-9)
                     and delta < 0}
        return evid

    def _disabled(self, reason: str) -> SchoolVerdict:
        return SchoolVerdict(kind=VerdictKind.DISABLED, reason=reason,
                             authority="advisory")


volume_flow_school = VolumeFlowSchool()
