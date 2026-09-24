"""Lazy dspy.Module wiring.

Modules are only materialised while the layer is enabled (importing dspy may
block offline). The classes here stay importable in any environment; their
``build()``/``forward()`` paths raise ``AIProgramsDisabled`` otherwise.
"""

from __future__ import annotations

from typing import Any, Dict

from .market import MarketAnalyzer

MODULES = {
    "analyze_liquidity": "ai.dspy.signatures.contracts",
    "classify_market_structure": "ai.dspy.signatures.contracts",
    "evaluate_session": "ai.dspy.signatures.contracts",
    "score_confluence": "ai.dspy.signatures.contracts",
    "draft_review": "ai.dspy.signatures.contracts",
}


def build_module(program_id: str):
    """Return a dspy.Module subclass for ``program_id`` (lazy, gated).

    Uses ``dspy.Program`` when present (DSPy 3.x) with a fallback to the
    classic ``dspy.Module`` base.
    """
    from ..runtime import disabled_reason
    from ..signatures.contracts import _SPECS_BY_ID, make_signatures

    spec = _SPECS_BY_ID.get(program_id)
    if spec is None:
        raise KeyError(f"unknown program id: {program_id}")
    reason = disabled_reason()
    if reason:
        raise RuntimeError(f"dspy layer disabled: {reason}")

    import dspy

    signature = make_signatures([program_id])[program_id]
    predictor_cls = getattr(dspy, "Predict")
    base = getattr(dspy, "Program", None) or getattr(dspy, "Module", None)
    predictor = predictor_cls(signature)

    class _Module(base):
        def __init__(self) -> None:
            super().__init__()
            # Must be an instance attribute, NOT an outer closure: DSPy walks
            # ``self.__dict__`` to map ``predictor -> name`` (developer-mode /
            # named_predictors) so BootstrapFewShot & co. can attach demos and
            # ``dump_state()`` can serialise them. A closure makes
            # ``named_predictors()`` empty and every bootstrapped demo dies at
            # ``predictor2name[id(predictor)]`` -> KeyError -> ``continue``
            # (silent drop; compiled program equals the untrained baseline).
            self.predictor = predictor

        def forward(self, **inputs: Any) -> Any:
            return self.predictor(**inputs)

    return _Module


__all__ = ["MarketAnalyzer", "MODULES", "build_module"]

_ = Dict  # keep typing import honest
