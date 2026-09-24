"""Wyckoff school (SOURCE tier).

Relates *effort* (volume) to *result* (price) through the acquisition /
distribution phase chain. Events are only labelled if their predecessors
exist (PS -> SC -> AR -> ST -> Spring -> SOS -> LPS); the sequence cannot be
skipped. This school is intentionally the slowest signal source.

Learning key (meta): `failure_kind` distinguishes a *classification* error
(events were mislabelled) from a *macro* override (chain correct but the
global context overwhelmed it). These require different corrections.
"""
from __future__ import annotations

from statistics import median
from typing import List, Optional, Sequence

from core.contracts import Candle, RegimeSnapshot, TradeDirection
from core.logging import get_logger

from .base import School, SchoolEvidence, SchoolSignal, SchoolTier, SchoolZone, Suggestion

log = get_logger("schools.wyckoff")

_EVENT_ORDER = ("PS", "SC", "AR", "ST", "SPRING", "SOS", "LPS")


class WyckoffSchool(School):
    school_id = "wyckoff"
    name = "Wyckoff"
    tier = SchoolTier.SOURCE

    def evaluate(self, candles: Sequence[Candle], symbol: str,
                 regime: Optional[RegimeSnapshot] = None,
                 zones_from_others: Optional[Sequence[SchoolZone]] = None,
                 now: Optional[float] = None) -> SchoolEvidence:
        evid = self._evid(symbol, now)
        if len(candles) < 20:
            return evid

        window = list(candles[-60:])
        wins = [_w(c, i) for i, c in enumerate(window)]
        price = window[-1].close
        med_vol = median([w.vol for w in wins]) or 1.0
        med_range = median([w.rng for w in wins]) or 1e-9
        hi_vol = med_vol * 1.5

        sup = min(w.low for w in wins)
        res = max(w.high for w in wins[:-1]) if len(wins) > 1 else wins[0].high
        if (res - sup) / price > 0.06:
            evid.meta.update({"stage": "no_range", "no_setup": True})
            return evid

        events: dict = {}
        prefix_min: List[float] = []
        running = wins[0].low
        for w in wins:
            prefix_min.append(running)
            running = min(running, w.low)
        for i, w in enumerate(wins):
            atr = max(med_range, (res - sup) * 0.1)

            # -- accumulation chain, strict chronological order -------------
            if not events.get("PS") and i > 0 and w.vol <= med_vol and \
                    w.low <= prefix_min[i]:
                events["PS"] = w

            if events.get("PS") and not events.get("SC") and \
                    w.rng >= 2 * med_range and w.lower_wick >= 0.4 * w.rng and \
                    w.vol >= hi_vol and w.low <= prefix_min[i]:
                events["SC"] = w

            if events.get("SC") and not events.get("AR") and \
                    w.is_bullish and w.close > events["SC"].close and \
                    w.rng >= med_range:
                events["AR"] = w

            if events.get("AR") and not events.get("ST") and \
                    w.low <= events["SC"].low + atr and w.vol <= med_vol and \
                    w.index > events["AR"].index:
                events["ST"] = w

            if events.get("ST") and not events.get("SPRING") and \
                    w.low < events["ST"].low and w.close > events["ST"].low and \
                    w.vol > med_vol:
                events["SPRING"] = w

            if events.get("SPRING") and not events.get("SOS") and \
                    w.close > res and (w.vol >= hi_vol or w.rng >= 2 * med_range):
                events["SOS"] = w

            if events.get("SOS") and not events.get("LPS") and \
                    w.close >= res and w.vol <= med_vol and \
                    w.index > events["SOS"].index:
                events["LPS"] = w

        dist: dict = {}
        acc_active = events.get("SC") is not None
        if not acc_active:
            # ---- distribution chain (mirror, strict chronological order) ----
            prefix_max: List[float] = []
            running = wins[0].high
            for w in wins:
                prefix_max.append(running)
                running = max(running, w.high)
            for i, w in enumerate(wins):
                atr = max(med_range, (res - sup) * 0.1)
                top_area = w.high >= prefix_max[i] - atr * 0.5
                if not dist.get("PSY") and w.rng >= med_range and \
                        w.vol >= hi_vol and top_area and w.index > 0:
                    dist["PSY"] = w
                if dist.get("PSY") and not dist.get("BC") and \
                        w.rng >= 2 * med_range and \
                        w.upper_wick >= 0.4 * w.rng and w.vol >= hi_vol and \
                        top_area and w.index > dist["PSY"].index:
                    dist["BC"] = w
                if dist.get("BC") and not dist.get("AR") and \
                        not w.is_bullish and w.close < dist["BC"].close and \
                        w.rng >= med_range and w.index > dist["BC"].index:
                    dist["AR"] = w
                if dist.get("AR") and not dist.get("UTAD") and \
                        w.high > dist["BC"].high and w.close <= dist["BC"].high and \
                        w.vol > med_vol and w.index > dist["AR"].index:
                    dist["UTAD"] = w
                if dist.get("UTAD") and not dist.get("SOW") and \
                        w.close <= sup + atr and w.vol >= hi_vol and \
                        w.index > dist["UTAD"].index:
                    dist["SOW"] = w

        evid.zones.append(SchoolZone("trading_range", res, sup, role="context"))
        if acc_active:
            stage = events.get("LPS") and "LPS" or events.get("SOS") and "SOS" \
                or events.get("SPRING") and "SPRING" or events.get("ST") and "ST" \
                or events.get("AR") and "AR" or "SC"
        else:
            stage = (dist.get("SOW") and "SOW" or dist.get("UTAD") and "UTAD"
                     or dist.get("AR") and "AR" or dist.get("BC") and "BC"
                     or dist.get("PSY") and "PSY" or None)
        evid.meta.update({"stage": stage or "pre",
                          "events": list(events),
                          "distribution_events": list(dist),
                          "range": [round(sup, 5), round(res, 5)]})
        if stage is None and not (events or dist):
            evid.meta["no_setup"] = True
            return evid

        spring = events.get("SPRING")
        if spring:
            sl = spring.low - med_range * 0.15
            tp = res + (res - sup) * 0.5
            evid.signals.append(SchoolSignal(
                name="spring_reversal", direction=TradeDirection.LONG,
                strength=0.62, anchor=f"wy:{spring.index}", pattern="spring_reversal",
                meta={"lesson_key": "failure_kind",
                      "chain": list(events)}))
            evid.suggestions.append(Suggestion(
                school_id=self.school_id, pattern="spring_reversal",
                direction=TradeDirection.LONG,
                entry_zone=[round(sup, 5), round(price, 5)],
                stop_loss=round(sl, 5), take_profit=[round(tp, 5)],
                invalidation=round(sl, 5),
                confidence=self.policy.effective_confidence(0.62),
                anchor=f"wy:{spring.index}",
                meta={"lesson_key": "failure_kind", "chain": list(events)}))

        utad = dist.get("UTAD")
        if utad:
            sl = utad.high + med_range * 0.15
            tp = sup - (res - sup) * 0.5
            evid.signals.append(SchoolSignal(
                name="utad_reversal", direction=TradeDirection.SHORT,
                strength=0.6, anchor=f"wy:{utad.index}", pattern="utad_reversal",
                meta={"lesson_key": "failure_kind",
                      "chain": list(dist)}))
            evid.suggestions.append(Suggestion(
                school_id=self.school_id, pattern="utad_reversal",
                direction=TradeDirection.SHORT,
                entry_zone=[round(sup, 5), round(price, 5)],
                stop_loss=round(sl, 5), take_profit=[round(tp, 5)],
                invalidation=round(sl, 5),
                confidence=self.policy.effective_confidence(0.6),
                anchor=f"wy:{utad.index}",
                meta={"lesson_key": "failure_kind", "chain": list(dist)}))

        sos = events.get("SOS")
        if sos and price >= res - med_range:
            sl = res - med_range * 0.3
            tp = res + (res - sup) * 1.0
            evid.signals.append(SchoolSignal(
                name="sos_breakout", direction=TradeDirection.LONG,
                strength=0.55, anchor=f"wy:{sos.index}", pattern="sos_breakout",
                meta={"lesson_key": "failure_kind", "chain": list(events)}))
            evid.suggestions.append(Suggestion(
                school_id=self.school_id, pattern="sos_breakout",
                direction=TradeDirection.LONG,
                entry_zone=[round(res, 5), round(price, 5)],
                stop_loss=round(sl, 5), take_profit=[round(tp, 5)],
                invalidation=round(sl, 5),
                confidence=self.policy.effective_confidence(0.55),
                anchor=f"wy:{sos.index}",
                meta={"lesson_key": "failure_kind", "chain": list(events)}))
        return evid


class _Win:
    __slots__ = ("high", "low", "close", "open", "vol", "rng",
                 "is_bullish", "lower_wick", "upper_wick", "index", "par")

    def __init__(self, c: Candle, index: int, par: float) -> None:
        self.high, self.low, self.close, self.open = c.high, c.low, c.close, c.open
        self.vol = max(c.volume, c.tick_volume)
        self.rng = c.range or 1e-9
        self.is_bullish = c.is_bullish
        self.lower_wick = c.lower_wick
        self.upper_wick = c.upper_wick
        self.index = index
        self.par = par


def _w(c: Candle, index: int = 0, par: float = 0.0) -> _Win:
    return _Win(c, index, par or c.low)


wyckoff_school = WyckoffSchool()
