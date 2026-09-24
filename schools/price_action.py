"""Price Action school (CONFIRMATION tier).

Reads the immediate behavior of candles *at the zones other schools
drew*: pin bars, engulfing, inside bars, and compression->expansion.
It never creates a trade by itself and never chooses a direction; it
only raises/lowers the confidence of a ready Suggestion, or flags a
early-exit warning when a counter-candle appears at the target.

Learning key (meta): `ab_confirm_lift` - whether the presence of this
confirmation actually raised the win rate of candidates (A/B), else the
school should be thinned out of the pipeline.
"""
from __future__ import annotations

from typing import List, Optional, Sequence

from core.contracts import Candle, RegimeSnapshot, TradeDirection
from core.logging import get_logger

from .base import School, SchoolEvidence, SchoolSignal, SchoolTier, SchoolZone

log = get_logger("schools.priceaction")


class PriceActionSchool(School):
    school_id = "price_action"
    name = "Price Action"
    tier = SchoolTier.CONFIRMATION

    def evaluate(self, candles: Sequence[Candle], symbol: str,
                 regime: Optional[RegimeSnapshot] = None,
                 zones_from_others: Optional[Sequence[SchoolZone]] = None,
                 now: Optional[float] = None) -> SchoolEvidence:
        evid = self._evid(symbol, now)
        if len(candles) < 8:
            return evid

        zones = list(zones_from_others) if zones_from_others else []
        price = candles[-1].close
        attention = [z for z in zones if z.role in ("entry", "objective", "invalidation")]
        near_zone = any(z.contains(price) for z in attention)

        patterns: List[str] = []
        early_exit = False

        # compression -> expansion (timing only, never direction)
        if len(candles) >= 8:
            last = [c.range for c in candles[-5:] if c.range > 0]
            prior = [c.range for c in candles[-12:-5] if c.range > 0]
            if last and prior and sum(last) / len(last) < 0.5 * sum(prior) / len(prior):
                patterns.append("compression_to_expansion")
                evid.signals.append(SchoolSignal(
                    name="compression", direction=TradeDirection.FLAT,
                    strength=0.3, pattern="compression_expansion",
                    meta={"lesson_key": "ab_confirm_lift"}))

        last = candles[-1]
        if len(candles) >= 2:
            prev = candles[-2]
            body = max(last.body, 1e-9)
            mid = (last.open + last.close) / 2.0
            # pin bar: wick tells the story, close in the opposite half
            if last.upper_wick >= 2 * body and last.close <= mid:
                patterns.append("pin_bar")
                if near_zone:
                    evid.signals.append(SchoolSignal(
                        name="rejection_at_key_level", direction=TradeDirection.SHORT,
                        strength=0.5, pattern="rejection_at_key_level",
                        meta={"lesson_key": "ab_confirm_lift"}))
            elif last.lower_wick >= 2 * body and last.close >= mid:
                patterns.append("pin_bar")
                if near_zone:
                    evid.signals.append(SchoolSignal(
                        name="rejection_at_key_level", direction=TradeDirection.LONG,
                        strength=0.5, pattern="rejection_at_key_level",
                        meta={"lesson_key": "ab_confirm_lift"}))

            # engulfing
            if last.is_bullish and last.close > prev.high and last.open < prev.low:
                patterns.append("bullish_engulfing")
                if near_zone:
                    evid.signals.append(SchoolSignal(
                        name="engulfing", direction=TradeDirection.LONG,
                        strength=0.45, pattern="rejection_at_key_level",
                        meta={"lesson_key": "ab_confirm_lift"}))
            elif not last.is_bullish and last.close < prev.low and last.open > prev.high:
                patterns.append("bearish_engulfing")
                if near_zone:
                    evid.signals.append(SchoolSignal(
                        name="engulfing", direction=TradeDirection.SHORT,
                        strength=0.45, pattern="rejection_at_key_level",
                        meta={"lesson_key": "ab_confirm_lift"}))

            # inside bar
            if last.high <= prev.high and last.low >= prev.low:
                patterns.append("inside_bar")
                if near_zone:
                    evid.signals.append(SchoolSignal(
                        name="inside_bar", direction=TradeDirection.FLAT,
                        strength=0.2, pattern="compression_expansion",
                        meta={"lesson_key": "ab_confirm_lift"}))

            # doji: indecision at a zone lowers the confirmation odds
            if body < 0.25 * last.range and last.range > 0:
                patterns.append("doji")
                if near_zone:
                    evid.signals.append(SchoolSignal(
                        name="indecision", direction=TradeDirection.FLAT,
                        strength=0.2, pattern="indecision_doji",
                        meta={"lesson_key": "ab_confirm_lift"}))

            # early-exit warning: counter candle near the take-profit zone
            objectives = [z for z in attention if z.role == "objective"]
            for z in objectives:
                if z.contains(price):
                    if last.is_bullish and last.upper_wick >= 2 * max(last.body, 1e-9):
                        early_exit = True
                        evid.signals.append(SchoolSignal(
                            name="counter_candle", direction=TradeDirection.SHORT,
                            strength=0.35, pattern="early_exit_rejection",
                            anchor=f"obj:{z.zone_type}",
                            meta={"lesson_key": "ab_confirm_lift"}))
                    if not last.is_bullish and last.lower_wick >= 2 * max(last.body, 1e-9):
                        early_exit = True
                        evid.signals.append(SchoolSignal(
                            name="counter_candle", direction=TradeDirection.LONG,
                            strength=0.35, pattern="early_exit_rejection",
                            anchor=f"obj:{z.zone_type}",
                            meta={"lesson_key": "ab_confirm_lift"}))

        evid.confidence = max((s.strength for s in evid.signals), default=0.0)
        directional = [s for s in evid.signals
                       if s.direction in (TradeDirection.LONG, TradeDirection.SHORT)]
        if directional:
            evid.bias = max(directional, key=lambda s: s.strength).direction
        evid.meta = {"patterns": patterns, "early_exit": early_exit,
                     "near_key_zone": near_zone,
                     "lesson_key": "ab_confirm_lift"}
        return evid


price_action_school = PriceActionSchool()
