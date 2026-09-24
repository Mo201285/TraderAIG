"""Market Structure school (SOURCE tier).

Reads raw swing structure (HH/HL / LH/LL), Protected High/Low, confirmed
BOS / CHoCH by candle *close*, and produces directional Suggestions plus
structural invalidation anchors. This school is context (bias + invalidation)
and may originate trend/breakout/reversal strategies.

Learning keys (meta): `bos_vs_false_break` ratio per market regime.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence

from core.contracts import Candle, RegimeSnapshot, TradeDirection
from core.logging import get_logger

from .base import School, SchoolEvidence, SchoolSignal, SchoolTier, SchoolZone, Suggestion

log = get_logger("schools.structure")


@dataclass
class _Swing:
    index: int
    price: float
    kind: str  # high | low


def _find_swings(candles: Sequence[Candle], lookback: int = 60) -> List[_Swing]:
    """1-2-1 pivot detection: confirmed by one bar on each side.

    The live (last) bar is never a pivot - it is still forming, so it can
    break a level without re-labelling the structure.
    """
    if len(candles) < 4:
        return []
    start = max(1, len(candles) - lookback)
    end = len(candles) - 1                # last candle excluded (forming)
    swings: List[_Swing] = []
    for i in range(start, end):
        c, left, right = candles[i], candles[i - 1], candles[i + 1]
        if c.high > left.high and c.high >= right.high:
            swings.append(_Swing(i, c.high, "high"))
        if c.low < left.low and c.low <= right.low:
            swings.append(_Swing(i, c.low, "low"))
    return swings


def _classify(lows: Sequence[float], highs: Sequence[float]) -> str:
    """HH/HL, LH/LL labels from the most recent opposite-point sequence."""
    if len(highs) >= 2 and highs[-1] > highs[-2] and lows[-1] > lows[-2]:
        return "HH/HL"
    if len(highs) >= 2 and highs[-1] < highs[-2] and lows[-1] < lows[-2]:
        return "LH/LL"
    return "mixed"


def _atr(candles: Sequence[Candle], period: int = 14) -> float:
    if len(candles) < 2:
        return 0.0
    trs = []
    for i in range(1, len(candles)):
        today, prev = candles[i], candles[i - 1]
        trs.append(max(today.high - today.low,
                       abs(today.high - prev.close), abs(today.low - prev.close)))
    window = trs[-period:]
    return sum(window) / max(1, len(window))


class StructureSchool(School):
    school_id = "structure"
    name = "Market Structure"
    tier = SchoolTier.SOURCE

    def eligibility(self, regime: Optional[RegimeSnapshot]) -> bool:
        return True

    def evaluate(self, candles: Sequence[Candle], symbol: str,
                 regime: Optional[RegimeSnapshot] = None,
                 zones_from_others: Optional[Sequence[SchoolZone]] = None,
                 now: Optional[float] = None) -> SchoolEvidence:
        evid = self._evid(symbol, now)
        if len(candles) < 12:
            return evid

        swings = _find_swings(candles)
        highs = [s for s in swings if s.kind == "high"]
        lows = [s for s in swings if s.kind == "low"]
        if len(highs) < 2 or len(lows) < 2:
            return evid

        price = candles[-1].close
        atr = _atr(candles)
        label = _classify([l.price for l in lows], [h.price for h in highs])

        threats = {"bos_confirmed": False, "choch_confirmed": False}
        invalidation: Optional[float] = None

        # --- trend-continuation context --------------------------------
        if label == "HH/HL":
            lows_below = [l for l in lows if l.price < price]
            if lows_below:
                protected_low = lows_below[-1].price      # last HL still protecting
                pullback = price <= protected_low + atr * 1.0
                evid.bias = TradeDirection.LONG
                evid.signals.append(SchoolSignal(
                    name="structure_trend", direction=TradeDirection.LONG,
                    strength=0.6, anchor=f"sw:{lows_below[-1].index}",
                    pattern="trend_continuation"))
                evid.zones.append(SchoolZone(
                    "protected_low", protected_low + atr * 0.1, protected_low,
                    role="invalidation"))
                if pullback:
                    sl = protected_low - atr * 0.15
                    tp = max(h.price for h in highs) + atr * 2.0
                    evid.suggestions.append(Suggestion(
                        school_id=self.school_id, pattern="trend_continuation",
                        direction=TradeDirection.LONG,
                        entry_zone=[round(protected_low, 5), round(price, 5)],
                        stop_loss=round(sl, 5), take_profit=[round(tp, 5)],
                        invalidation=round(sl, 5),
                        confidence=self._base_conf(0.62, regime),
                        anchor=f"sw:{lows_below[-1].index}",
                        zones=list(evid.zones),
                        meta={"label": label, "lesson_key": "bos_vs_false_break"}))
                invalidation = protected_low

        elif label == "LH/LL":
            highs_above = [h for h in highs if h.price > price]
            if highs_above:
                protected_high = highs_above[-1].price
                pullback = price >= protected_high - atr * 1.0
                evid.bias = TradeDirection.SHORT
                evid.signals.append(SchoolSignal(
                    name="structure_trend", direction=TradeDirection.SHORT,
                    strength=0.6, anchor=f"sw:{highs_above[-1].index}",
                    pattern="trend_continuation"))
                evid.zones.append(SchoolZone(
                    "protected_high", protected_high, protected_high - atr * 0.1,
                    role="invalidation"))
                if pullback:
                    sl = protected_high + atr * 0.15
                    tp = min(l.price for l in lows) - atr * 2.0
                    evid.suggestions.append(Suggestion(
                        school_id=self.school_id, pattern="trend_continuation",
                        direction=TradeDirection.SHORT,
                        entry_zone=[round(price, 5), round(protected_high, 5)],
                        stop_loss=round(sl, 5), take_profit=[round(tp, 5)],
                        invalidation=round(sl, 5),
                        confidence=self._base_conf(0.62, regime),
                        anchor=f"sw:{highs_above[-1].index}",
                        zones=list(evid.zones),
                        meta={"label": label, "lesson_key": "bos_vs_false_break"}))
                invalidation = protected_high

        # --- structural break (BOS / CHoCH) by close --------------------
        last_high = highs[-1]
        last_low = lows[-1]
        # BOS: uptrend protected low broken to the upside -> continuation
        if label == "HH/HL" and price > last_high.price and \
                candles[-1].close > last_high.price:
            threats["bos_confirmed"] = True
            evid.signals.append(SchoolSignal(
                name="bos_confirmed", direction=TradeDirection.LONG,
                strength=0.55, anchor=f"sw:{last_high.index}",
                pattern="structure_breakout",
                meta={"by_close": True}))
            sl = last_high.price - atr * 0.2
            evid.suggestions.append(Suggestion(
                school_id=self.school_id, pattern="structure_breakout",
                direction=TradeDirection.LONG,
                entry_zone=[round(last_high.price, 5), round(price, 5)],
                stop_loss=round(sl, 5),
                take_profit=[round(price + (price - last_low.price) * 1.0, 5)],
                invalidation=round(sl, 5),
                confidence=self._base_conf(0.58, regime),
                anchor=f"sw:{last_high.index}",
                meta={"lesson_key": "bos_vs_false_break",
                      "bos_type": "continuation"}))
        # CHoCH: HH/HL broken to the downside by close -> reversal
        elif label == "HH/HL" and candles[-1].close < lows[-1].price:
            threats["choch_confirmed"] = True
            evid.signals.append(SchoolSignal(
                name="choch_confirmed", direction=TradeDirection.SHORT,
                strength=0.5, anchor=f"sw:{last_low.index}",
                pattern="reversal_after_confirmed_shift",
                meta={"by_close": True}))
            sl = last_low.price + atr * 0.2
            tp = price - price * 0.004
            evid.suggestions.append(Suggestion(
                school_id=self.school_id, pattern="reversal_after_confirmed_shift",
                direction=TradeDirection.SHORT,
                entry_zone=[round(price, 5), round(last_low.price, 5)],
                stop_loss=round(sl, 5), take_profit=[round(tp, 5)],
                invalidation=round(sl, 5),
                confidence=self._base_conf(0.5, regime),
                anchor=f"sw:{last_low.index}",
                meta={"lesson_key": "bos_vs_false_break",
                      "choch_type": "reversal"}))
        # downside mirror of BOS
        elif label == "LH/LL" and candles[-1].close < last_low.price:
            threats["bos_confirmed"] = True
            evid.signals.append(SchoolSignal(
                name="bos_confirmed", direction=TradeDirection.SHORT,
                strength=0.55, anchor=f"sw:{last_low.index}",
                pattern="structure_breakout", meta={"by_close": True}))
            sl = last_low.price + atr * 0.2
            evid.suggestions.append(Suggestion(
                school_id=self.school_id, pattern="structure_breakout",
                direction=TradeDirection.SHORT,
                entry_zone=[round(price, 5), round(last_low.price, 5)],
                stop_loss=round(sl, 5),
                take_profit=[round(price - (last_high.price - price) * 1.0, 5)],
                invalidation=round(sl, 5),
                confidence=self._base_conf(0.58, regime),
                anchor=f"sw:{last_low.index}",
                meta={"lesson_key": "bos_vs_false_break",
                      "bos_type": "continuation"}))
        # upright CHoCH
        elif label == "LH/LL" and candles[-1].close > highs[-1].price:
            threats["choch_confirmed"] = True
            evid.signals.append(SchoolSignal(
                name="choch_confirmed", direction=TradeDirection.LONG,
                strength=0.5, anchor=f"sw:{last_high.index}",
                pattern="reversal_after_confirmed_shift",
                meta={"by_close": True}))
            sl = last_high.price - atr * 0.2
            tp = price + price * 0.004
            evid.suggestions.append(Suggestion(
                school_id=self.school_id, pattern="reversal_after_confirmed_shift",
                direction=TradeDirection.LONG,
                entry_zone=[round(last_high.price, 5), round(price, 5)],
                stop_loss=round(sl, 5), take_profit=[round(tp, 5)],
                invalidation=round(sl, 5),
                confidence=self._base_conf(0.5, regime),
                anchor=f"sw:{last_high.index}",
                meta={"lesson_key": "bos_vs_false_break",
                      "choch_type": "reversal"}))

        evid.meta = {"structure_label": label,
                     **threats,
                     "protected_low": invalidation if label == "HH/HL" else None,
                     "protected_high": invalidation if label == "LH/LL" else None}
        return evid

    def _base_conf(self, base: float, regime: Optional[RegimeSnapshot]) -> float:
        return self.policy.effective_confidence(base)


structure_school = StructureSchool()
