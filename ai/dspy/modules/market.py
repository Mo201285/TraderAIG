"""MarketAnalyzer — the per-school analysis module (lazy DSPy wrapper).

Represents one school's reasoning program. ``run`` is deterministic + dspy-free
when the layer is disabled (returns a structured evidence dict, the same shape
the DSPy program would refine): this is what keeps the system fully usable
offline while the optimisation loop is enabled only where LMs can be reached.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import time
import uuid
from typing import Any, Dict, List, Optional


@dataclass
class Evidence:
    """SchoolEvidence standard (PROJECT_MAP integration norm)."""
    school: str
    symbol: str
    timeframe: str
    direction: str
    setup: str
    confidence: float
    evidence: List[str] = field(default_factory=list)
    invalidation: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    def as_dict(self) -> Dict[str, Any]:
        return {
            "school": self.school,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "direction": self.direction,
            "setup": self.setup,
            "confidence": round(float(self.confidence), 3),
            "evidence": list(self.evidence),
            "invalidation": list(self.invalidation),
            "created_at": self.created_at,
            "evidence_id": uuid.uuid4().hex[:12],
        }


class MarketAnalyzer:
    """Per-school analysis entry point.

    - disabled env  -> deterministic structured evidence (no imports)
    - enabled env   -> builds the DSPy program from its signature contract and
                       delegates the same market_state payload to it.
    """

    def __init__(self, program_id: str, school: str) -> None:
        from ..signatures.contracts import _SPECS_BY_ID

        spec = _SPECS_BY_ID.get(program_id)
        self.program_id = program_id
        self.school = school
        self.inputs = list(spec.inputs) if spec else []

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def _pick(context: Dict[str, Any], *names: str, default: Any = None) -> Any:
        for name in names:
            if name in context and context[name] is not None:
                return context[name]
        return default

    # -- deterministic fallback (keep usable offline) ---------------------
    def run(self, market_state: Dict[str, Any]) -> Optional[Evidence]:
        return self._deterministic(market_state)

    def _deterministic(self, ctx: Dict[str, Any]) -> Optional[Evidence]:
        symbol = self._pick(ctx, "symbol", "symbol_code", default="UNKNOWN")
        timeframe = self._pick(ctx, "timeframe", default="M15")
        trend = ctx.get("trend", {}).get("direction", "unknown") if isinstance(ctx.get("trend"), dict) else ctx.get("trend", "unknown")
        bias = ctx.get("bias", trend)
        direction = "buy" if str(bias).lower() in ("up", "bullish", "buy") else "sell" if str(bias).lower() in ("down", "bearish", "sell") else "neutral"
        confidence = min(1.0, float(ctx.get("liquidity_score", 0.55)))
        reasons = list(ctx.get("evidence", []))
        if callable(getattr(reasons, "items", None)):
            reasons = [str(k) for k in reasons]
        reasons = [str(r) for r in reasons][:6]
        invalidations = [str(x) for x in ctx.get("invalidation", []) for x in ([x] if not isinstance(x, (list, tuple)) else x)][:4]
        return Evidence(
            school=self.school,
            symbol=str(symbol),
            timeframe=str(timeframe),
            direction=direction,
            setup=f"{self.program_id}:det",
            confidence=confidence,
            evidence=reasons or ["no explicit evidence in market state"],
            invalidation=invalidations,
        )

    # -- enabled path (manual / evolved) ----------------------------------
    def build(self):
        from . import build_module

        return build_module(self.program_id)


__all__ = ["MarketAnalyzer", "Evidence"]
