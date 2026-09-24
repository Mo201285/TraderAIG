"""AI Intelligence school (META tier, no vote).

A meta layer over all other schools: classifies the market regime to decide
which schools even get called, detects when two schools that *look*
aligned are actually correlated (same structure anchor / same zone, so
their agreement carries zero extra information), ranks multiple candidates
on different instruments, and reports model uncertainty when the current
state sits far from trained conditions. It never originates a trade, never
votes in consensus, and has no execution authority - it only reorders and
flags.

Learning key (meta): periodic re-certification of the Regime classification
(is the trained distribution still the live one).
"""
from __future__ import annotations

from typing import List, Optional, Sequence

from core.contracts import Candle, RegimeSnapshot, TradeDirection
from core.logging import get_logger

from .base import (School, SchoolEvidence, SchoolSignal, SchoolTier,
                   SchoolVerdict, SchoolZone, Suggestion, VerdictKind)

log = get_logger("schools.ai")


def correlated(pair_a: Suggestion, pair_b: Suggestion) -> bool:
    """Two suggestions are information-duplicates when they share an anchor."""
    if pair_a.anchor and pair_a.anchor == pair_b.anchor:
        return True
    for za in pair_a.zones:
        for zb in pair_b.zones:
            if za.contains(pair_b.stop_loss) or zb.contains(pair_a.stop_loss):
                return True
    return False


class AISchool(School):
    school_id = "ai"
    name = "AI Intelligence"
    tier = SchoolTier.META

    def evaluate(self, candles: Sequence[Candle], symbol: str,
                 regime: Optional[RegimeSnapshot] = None,
                 zones_from_others: Optional[Sequence[SchoolZone]] = None,
                 now: Optional[float] = None) -> SchoolEvidence:
        evid = self._evid(symbol, now)
        if regime is None:
            evid.verdict = SchoolVerdict(
                kind=VerdictKind.PASS, authority="advisory",
                reason="no regime -> model uncertainty high",
                meta={"model_uncertainty": 0.7, "lesson_key": "re_certify"})
            evid.meta = {"model_uncertainty": 0.7, "lesson_key": "re_certify"}
            return evid

        uncertainty = 1.0 - regime.confidence
        recommended = self._recommend(regime)
        evid.signals.append(SchoolSignal(
            name="regime_classification", direction=TradeDirection.FLAT,
            strength=regime.confidence, pattern="regime_classification",
            meta={"regime": f"{regime.trend.value}/{regime.volatility.value}",
                  "recommended_schools": recommended,
                  "lesson_key": "re_certify"}))
        evid.verdict = SchoolVerdict(
            kind=VerdictKind.PASS, authority="advisory",
            reason=f"regime={regime.trend.value}/{regime.volatility.value} "
                   f"conf={regime.confidence:.2f}",
            meta={"model_uncertainty": round(uncertainty, 3),
                  "recommended_schools": recommended,
                  "anomaly": regime.confidence < 0.3,
                  "lesson_key": "re_certify"})
        evid.meta = {"model_uncertainty": round(uncertainty, 3),
                     "recommended_schools": recommended}
        return evid

    def rank(self, suggestions: Sequence[Suggestion],
             regime: Optional[RegimeSnapshot] = None) -> List[Suggestion]:
        """Order suggestions by relative evidence quality (no direction vote)."""
        def score(s: Suggestion) -> float:
            conf = s.confidence
            return conf * 10 + len(s.zones) * 0.5 - (0.5 if s.pattern == "fvg_continuation" else 0)
        return sorted(suggestions, key=score, reverse=True)

    def rank_across_instruments(
            self, evidences: Sequence[SchoolEvidence]) -> List[dict]:
        """Merge every SOURCE suggestion from all instruments and rank them."""
        symbol_of: dict = {
            id(s): ev.symbol
            for ev in evidences for s in ev.suggestions
        }
        flat = [s for ev in evidences for s in ev.suggestions]
        ranked = self.rank(flat)
        return [{"symbol": symbol_of[id(s)], **s.as_dict()} for s in ranked]

    def conflicts(self, signals: Sequence[SchoolSignal]) -> List[dict]:
        """Flag contradictory directional signals and correlated alignments."""
        out: List[dict] = []
        longs = [s for s in signals if s.direction == TradeDirection.LONG]
        shorts = [s for s in signals if s.direction == TradeDirection.SHORT]
        if longs and shorts:
            out.append({"type": "direction_conflict",
                        "long": [s.name for s in longs],
                        "short": [s.name for s in shorts]})
        anchors = {}
        for s in signals:
            if s.anchor:
                anchors.setdefault(s.anchor, []).append(s.name)
        for anchor, names in anchors.items():
            if len(names) > 1:
                out.append({"type": "correlated_evidence", "anchor": anchor,
                            "schools": names})
        return out

    def _recommend(self, regime: RegimeSnapshot) -> List[str]:
        """Which schools are worth calling under this regime (meta-only)."""
        rec = ["structure", "ict", "price_action"]
        if regime.structure.value in ("ranging", "accumulation", "distribution"):
            rec.append("wyckoff")
        if regime.volatility.value not in ("extreme",):
            rec.append("volume_flow")
        return rec


ai_school = AISchool()
