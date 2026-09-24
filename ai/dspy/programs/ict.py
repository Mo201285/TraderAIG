"""ICT / SMC reasoning program.

Composable Program (DSPy) over the market state, or a deterministic
fallback when the layer is disabled. Only ever consumes **structured
market state** (never raw candles), per the integration norm.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..modules.market import MarketAnalyzer, Evidence

MODULE_CHAIN = (
    "evaluate_session",
    "classify_market_structure",
    "analyze_liquidity",
    "score_confluence",
)


class ICTProgram:
    SCHOOL = "ICT/SMC"

    def __init__(self, symbol: str = "XAUUSD", timeframe: str = "M15") -> None:
        self.symbol = symbol
        self.timeframe = timeframe

    def _state(self, market_state: Dict[str, Any]) -> Dict[str, Any]:
        state = dict(market_state or {})
        state.setdefault("symbol", self.symbol)
        state.setdefault("timeframe", self.timeframe)
        return state

    def run(self, market_state: Dict[str, Any]) -> Optional[Evidence]:
        """Deterministic pass when the DSPy layer is disabled/offline.

        Composes the module chain in the contract order and fuses their
        deterministic evidence into a single SchoolEvidence verdict.
        """
        ctx = self._state(market_state)
        evidences = [
            MarketAnalyzer(pid, school=self.SCHOOL).run(ctx)
            for pid in MODULE_CHAIN
        ]
        active = [ev for ev in evidences if ev is not None]
        if not active:
            return None
        bullish = sum(1 for ev in active if ev.direction == "buy")
        bearish = sum(1 for ev in active if ev.direction == "sell")
        direction = "buy" if bullish > bearish else "sell" if bearish > bullish else "neutral"

        def or_(a: Any, b: Any) -> Any:
            return a if a else b

        score = sum(ev.confidence for ev in active) / len(active)
        reasons: list = []
        invalidations: list = []
        for ev in active:
            reasons.extend(ev.evidence)
            invalidations.extend(ev.invalidation)

        return Evidence(
            school=self.SCHOOL,
            symbol=self.symbol,
            timeframe=self.timeframe,
            direction=direction,
            setup="ict_program:det",  # recommendable tag for later promotion
            confidence=score,
            evidence=reasons or [f"{direction} confluence"],
            invalidation=invalidations,
        )

    # -- enabled path -------------------------------------------------------
    def build(self):

        # Program = the composition of the module chain cores
        return ICTProgramDSPy.build(self._state)


class ICTProgramDSPy:
    """DSPy composition shell, only importable while the layer is enabled.

    ``build`` exists so the structure (module chain -> predictors -> fused
    verdict) is explicit and versionable. Actual composition requires a
    networked LM env; the deterministic ``ICTProgram.run`` path is the
    offline-safe behaviour used by pipeline/backtest hooks.
    """

    @staticmethod
    def build(state_fn):
        from ..runtime import disabled_reason

        reason = disabled_reason()
        if reason:
            raise RuntimeError(f"dspy layer disabled: {reason}")
        try:
            from ..modules import build_module

            return [build_module(pid)() for pid in MODULE_CHAIN]
        except Exception as exc:  # compiler/tooling surface
            raise NotImplementedError(
                "end-to-end DSPy composition needs a networked LM env; "
                "deterministic ICTProgram.run() is the offline path."
            ) from exc
