"""Pattern Geometry school (CONFIRMATION tier).

Detects deterministic geometric chart structures and uses them as a
confidence layer over source schools rather than as an independent originator.

Current supported patterns:
  - bull_flag / bear_flag
  - ascending_triangle / descending_triangle
  - double_top / double_bottom
  - rising_wedge / falling_wedge
  - rectangle_range

The school never creates a trade by itself. It only raises or lowers the
confidence of an existing source suggestion when the geometric structure
supports or contradicts that suggestion.
"""
from __future__ import annotations

from statistics import median
from typing import List, Optional, Sequence

from core.contracts import Candle, RegimeSnapshot, TradeDirection
from core.logging import get_logger

from .base import School, SchoolEvidence, SchoolSignal, SchoolTier, SchoolZone

log = get_logger("schools.pattern_geometry")


def _recent(candles: Sequence[Candle], n: int = 12) -> List[Candle]:
    return list(candles[-n:])


def _slope(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    return (values[-1] - values[0]) / max(1, len(values) - 1)


def _atr(candles: Sequence[Candle], period: int = 14) -> float:
    if len(candles) < 2:
        return 0.0
    trs = []
    for i in range(1, len(candles)):
        today, prev = candles[i], candles[i - 1]
        trs.append(max(today.high - today.low,
                       abs(today.high - prev.close),
                       abs(today.low - prev.close)))
    window = trs[-period:]
    return sum(window) / max(1, len(window))


class PatternGeometrySchool(School):
    school_id = "pattern_geometry"
    name = "Pattern Geometry"
    tier = SchoolTier.CONFIRMATION

    def evaluate(self, candles: Sequence[Candle], symbol: str,
                 regime: Optional[RegimeSnapshot] = None,
                 zones_from_others: Optional[Sequence[SchoolZone]] = None,
                 now: Optional[float] = None) -> SchoolEvidence:
        evid = self._evid(symbol, now)
        if len(candles) < 12:
            return evid

        price = candles[-1].close
        window = _recent(candles, 12)
        highs = [c.high for c in window]
        lows = [c.low for c in window]
        closes = [c.close for c in window]
        atr = _atr(candles)
        width = max(highs) - min(lows)
        top_band = max(highs)
        low_band = min(lows)
        tol = max(atr * 0.35, price * 0.0008)

        patterns: List[str] = []
        zones = list(zones_from_others) if zones_from_others else []
        near_zone = any(z.contains(price) for z in zones if z.role in ("entry", "objective", "invalidation"))

        # Flags: shallow counter-slope after impulse, without structural failure.
        pre = list(candles[-20:-12]) if len(candles) >= 20 else list(candles[:-12])
        pre_closes = [c.close for c in pre] if pre else []
        pre_highs = [c.high for c in pre] if pre else []
        pre_lows = [c.low for c in pre] if pre else []
        pre_slope = _slope(pre_closes)
        win_slope = _slope(closes)
        if pre_closes:
            impulse = abs(pre_closes[-1] - pre_closes[0])
            retrace = abs(closes[-1] - closes[0])
            retrace_ok = retrace <= max(atr * 2.0, impulse * 0.45)
            hold_above_mid = min(lows) >= (min(pre_lows) + max(pre_highs)) / 2 if pre_highs and pre_lows else False
            hold_below_mid = max(highs) <= (min(pre_lows) + max(pre_highs)) / 2 if pre_highs and pre_lows else False
            trend_allows_long = getattr(getattr(regime, "trend", None), "value", None) != "bearish"
            trend_allows_short = getattr(getattr(regime, "trend", None), "value", None) != "bullish"
            if pre_slope > 0 and win_slope < 0 and abs(win_slope) < abs(pre_slope) * 0.5 \
                    and retrace_ok and hold_above_mid and trend_allows_long:
                patterns.append("bull_flag")
                evid.signals.append(SchoolSignal(
                    name="bull_flag", direction=TradeDirection.LONG,
                    strength=0.28 if near_zone else 0.18,
                    pattern="bull_flag",
                    meta={"lesson_key": "pattern_geometry", "near_zone": near_zone,
                          "retrace_ok": retrace_ok}))
            elif pre_slope < 0 and win_slope > 0 and abs(win_slope) < abs(pre_slope) * 0.5 \
                    and retrace_ok and hold_below_mid and trend_allows_short:
                patterns.append("bear_flag")
                evid.signals.append(SchoolSignal(
                    name="bear_flag", direction=TradeDirection.SHORT,
                    strength=0.28 if near_zone else 0.18,
                    pattern="bear_flag",
                    meta={"lesson_key": "pattern_geometry", "near_zone": near_zone,
                          "retrace_ok": retrace_ok}))

        # Triangles: flat top with rising lows, or flat bottom with falling highs.
        flat_top = max(highs[-4:]) - min(highs[-4:]) <= tol
        rising_lows = _slope(lows[-6:]) > 0
        flat_bottom = max(lows[-4:]) - min(lows[-4:]) <= tol
        falling_highs = _slope(highs[-6:]) < 0
        if flat_top and rising_lows:
            patterns.append("ascending_triangle")
            evid.signals.append(SchoolSignal(
                name="ascending_triangle", direction=TradeDirection.LONG,
                strength=0.38 if near_zone else 0.28,
                pattern="ascending_triangle",
                meta={"lesson_key": "pattern_geometry", "near_zone": near_zone}))
        if flat_bottom and falling_highs:
            patterns.append("descending_triangle")
            evid.signals.append(SchoolSignal(
                name="descending_triangle", direction=TradeDirection.SHORT,
                strength=0.38 if near_zone else 0.28,
                pattern="descending_triangle",
                meta={"lesson_key": "pattern_geometry", "near_zone": near_zone}))

        # Double tops / bottoms.
        if len(highs) >= 8:
            hh1, hh2 = max(highs[:6]), max(highs[6:])
            ll1, ll2 = min(lows[:6]), min(lows[6:])
            neckline_top = min(closes[4:8]) if len(closes) >= 8 else min(closes)
            neckline_bottom = max(closes[4:8]) if len(closes) >= 8 else max(closes)
            if abs(hh1 - hh2) <= tol and price < neckline_top:
                patterns.append("double_top")
                evid.signals.append(SchoolSignal(
                    name="double_top", direction=TradeDirection.SHORT,
                    strength=0.4 if near_zone else 0.3,
                    pattern="double_top",
                    meta={"lesson_key": "pattern_geometry", "near_zone": near_zone}))
            if abs(ll1 - ll2) <= tol and price > neckline_bottom:
                patterns.append("double_bottom")
                evid.signals.append(SchoolSignal(
                    name="double_bottom", direction=TradeDirection.LONG,
                    strength=0.4 if near_zone else 0.3,
                    pattern="double_bottom",
                    meta={"lesson_key": "pattern_geometry", "near_zone": near_zone}))

        # Wedges: both bounds slope together while range compresses.
        hi_slope = _slope(highs)
        lo_slope = _slope(lows)
        first_half = window[:6]
        second_half = window[6:]
        first_rng = max(c.high for c in first_half) - min(c.low for c in first_half)
        second_rng = max(c.high for c in second_half) - min(c.low for c in second_half)
        compressing = second_rng < first_rng * 0.85 if first_rng > 0 else False
        if compressing and hi_slope > 0 and lo_slope > 0:
            patterns.append("rising_wedge")
            evid.signals.append(SchoolSignal(
                name="rising_wedge", direction=TradeDirection.SHORT,
                strength=0.32,
                pattern="rising_wedge",
                meta={"lesson_key": "pattern_geometry"}))
        if compressing and hi_slope < 0 and lo_slope < 0:
            patterns.append("falling_wedge")
            evid.signals.append(SchoolSignal(
                name="falling_wedge", direction=TradeDirection.LONG,
                strength=0.32,
                pattern="falling_wedge",
                meta={"lesson_key": "pattern_geometry"}))

        # Rectangle consolidation = timing/compression warning, not direction source.
        med_range = median([c.range for c in window if c.range > 0]) or 1e-9
        if width <= med_range * 3.2:
            patterns.append("rectangle_range")
            evid.signals.append(SchoolSignal(
                name="rectangle_range", direction=TradeDirection.FLAT,
                strength=0.18,
                pattern="rectangle_range",
                meta={"lesson_key": "pattern_geometry"}))
            evid.zones.append(SchoolZone(
                "rectangle_range", top_band, low_band, role="context",
                meta={"lesson_key": "pattern_geometry"}))

        evid.confidence = max((s.strength for s in evid.signals), default=0.0)
        directional = [s for s in evid.signals if s.direction in (TradeDirection.LONG, TradeDirection.SHORT)]
        if directional:
            evid.bias = max(directional, key=lambda s: s.strength).direction
        evid.meta = {
            "patterns": patterns,
            "near_key_zone": near_zone,
            "width": round(width, 5),
            "atr": round(atr, 5),
            "lesson_key": "pattern_geometry",
        }
        return evid


pattern_geometry_school = PatternGeometrySchool()
