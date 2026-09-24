"""Integration hooks: core/pipeline.py and operations/backtest.py.

Behaviour-neutral by default: every hook re-checks the gate and degrades to
the deterministic path when the DSPy layer is disabled or offline.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

from .runtime import enabled


def pipeline_enabled() -> bool:
    return os.environ.get("TRADERAIG_DSPY_PIPELINE", "0") == "1" and enabled()


def pipeline_refine(evidence: Any) -> Any:
    """Optional refinement of the evidence object produced by the pipeline.

    Disabled/offline env: returns the evidence object untouched (no-op).
    Enabled env: runs the ICT program over the evidence's structured state
    and returns the fused SchoolEvidence (the pipeline keeps using the same
    ``school_evidence`` field it already consumes).
    """
    if not pipeline_enabled():
        return evidence
    try:
        from .programs import ICTProgram
        from .modules.market import Evidence

        ctx = evidence
        if isinstance(evidence, Evidence):
            ctx = evidence.as_dict()
        elif isinstance(evidence, dict):
            ctx = evidence
        elif hasattr(evidence, "as_dict"):
            ctx = evidence.as_dict()
        program = ICTProgram()
        verdict = program.run(ctx)
        if verdict is None:
            return evidence
        if isinstance(evidence, Evidence):
            evidence.evidence = verdict.evidence
            evidence.confidence = verdict.confidence
            return evidence
        if isinstance(evidence, dict):
            evidence["dspy_refined"] = verdict.as_dict()
        return evidence
    except Exception:
        return evidence


def metric() -> Any:
    """The metric dspy optimisers and backtest reports should bind.

    Signature: ``metric(example: dict, prediction: dict) -> float``.
    """
    from .evaluators.metrics import trading_metric
    return trading_metric


def score_results(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Score a batch of kept outcome records with the trading metric.

    Used by ``operations.backtest.post_run_dspy_report`` to attach a
    metric-bound recap to backtest reports without touching the run.
    """
    from .evaluators.metrics import score_trade, aggregate
    rows = [score_trade(rec, rec.get("prediction", {})) for rec in records]
    return aggregate(rows)


dspy_metric = metric


__all__ = ["pipeline_enabled", "pipeline_refine", "metric", "dspy_metric", "score_results"]
