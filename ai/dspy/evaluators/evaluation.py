"""Program evaluation harness.

Evaluate *any* callable — a deterministic program, a backtest-tube, or a
future DSPy program — against labelled examples using the professional
trading metric. Pure-python and dspy-free by design (evaluation must come
before optimisation and must run everywhere).
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List

from .metrics import aggregate, score_trade, trading_metric


def evaluate_program(
    program: Callable[[Dict[str, Any]], Any],
    examples: List[Dict[str, Any]],
    metric: Callable[[Dict[str, Any], Dict[str, Any]], float] = trading_metric,
    tag: str = "program",
) -> Dict[str, Any]:
    """Run ``program(example)`` per example and score with ``metric``.

    Prediction can be any mapping-shaped value; ``score_trade`` reads it
    as a dict, so typed dspy.Prediction objects also work.
    """
    rows: List[Dict[str, Any]] = []
    failures = 0
    for example in examples:
        try:
            prediction = program(example)
            pred = prediction.as_dict() if hasattr(prediction, "as_dict") else dict(getattr(prediction, "__dict__", {}) or {})
            pred = pred if isinstance(pred, dict) else {"prediction": pred}
            scored = score_trade(example, pred)
            rows.append(scored)
        except Exception as exc:  # a failing program must not kill the run
            failures += 1
            rows.append({
                "score": 0.0,
                "components": dict.fromkeys(("direction", "entry", "risk", "timing", "mae_mfe", "rr", "regime", "drawdown_impact", "false_positive"), 0.0),
                "hit": False,
                "directional": False,
                "error": f"{type(exc).__name__}: {exc}",
            })
    report = aggregate(rows)
    report.update({
        "tag": tag,
        "failures": failures,
        "metric": getattr(metric, "__name__", "metric"),
    })
    return report


__all__ = ["evaluate_program", "aggregate"]
