"""Evaluators — the metric + evaluation harness for DSPy programs."""

from .metrics import (
    METRIC_WEIGHTS,
    MIN_CONFIDENCE_GATE,
    MIN_EDGE_RR,
    aggregate,
    score_trade,
    trading_metric,
)
from .evaluation import evaluate_program

__all__ = [
    "METRIC_WEIGHTS",
    "MIN_CONFIDENCE_GATE",
    "MIN_EDGE_RR",
    "aggregate",
    "score_trade",
    "trading_metric",
    "evaluate_program",
]
