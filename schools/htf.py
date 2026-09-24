"""Higher-timeframe context filter (GATE tier inside the board).

The board still deliberates on the *trading* timeframe, but a higher-
timeframe regime (D1/H1 vs M15/M5) is a hard authority over *continuation*
ideas: a continuation with no HTF agreement is a counter-trend trade and
should not be initiated on the smaller timeframe. Reversal setups are
contrarian by nature, so they are dampened rather than killed. Everything
is recorded on the suggestion meta (`htf_align`) and in the board gates.
"""
from __future__ import annotations

from typing import Dict

from core.contracts import RegimeSnapshot, TradeDirection, TrendDirection
from .base import Suggestion

# patterns that ride the existing HTF move - killed when HTF disagrees
_CONTINUATION = frozenset({
    "trend_continuation", "structure_breakout", "sos_breakout",
    "volume_breakout",
})
# patterns that trade *against* the HTF impulse - dampened, not killed
_REVERSAL = frozenset({
    "reversal_after_confirmed_shift", "sweep_reversal", "spring_reversal",
    "utad_reversal", "absorption_reversal", "absorption",
    "buy_side_raid", "sell_side_raid", "vacuum_raid",
    "sellside_raid", "buyside_raid",
})


class HtfContextFilter:
    """Apply the HTF regime as a gate over lower-timeframe suggestions."""

    def __init__(self, htf: RegimeSnapshot) -> None:
        self.htf = htf

    def alignment(self, direction: TradeDirection) -> str:
        if self.htf.trend.value == "sideways":
            return "neutral"
        agrees = ((direction == TradeDirection.LONG and
                   self.htf.trend == TrendDirection.BULLISH)
                  or (direction == TradeDirection.SHORT and
                      self.htf.trend == TrendDirection.BEARISH))
        return "aligned" if agrees else "against"

    def apply(self, suggestion: Suggestion) -> Dict:
        """Return a verdict: reject | review (with multiplier) | pass."""
        align = self.alignment(suggestion.direction)
        if align == "neutral":
            return {"kind": "pass", "align": align, "multiplier": 1.0}
        if align == "aligned":
            return {"kind": "pass", "align": align, "multiplier": 1.0}
        if suggestion.pattern in _CONTINUATION:
            return {
                "kind": "reject", "align": align, "multiplier": 0.0,
                "reason": (f"{suggestion.pattern} fights HTF "
                           f"{self.htf.trend.value}"),
            }
        if suggestion.pattern in _REVERSAL:
            return {"kind": "review", "align": align, "multiplier": 0.6}
        return {"kind": "review", "align": align, "multiplier": 0.75}
