"""Runtime availability probe for the DSPy layer (non-importing).

Never imports ``dspy`` in-process: importing it may block on outbound network
(LM auto-detection / telemetry). Everything here is a fast local check
(``find_spec`` + ``importlib.metadata``).
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import os
from typing import Dict, List

GATE_ENV = "TRADERAIG_DSPY_ENABLED"

LM_ENV_KEYS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "DSPY_LM_API_KEY",
    "TRADERAIG_DSPY_LM_API_KEY",
)


def dspy_installed() -> bool:
    return importlib.util.find_spec("dspy") is not None


def dspy_version() -> str:
    try:
        return importlib.metadata.version("dspy")
    except (importlib.metadata.PackageNotFoundError, OSError):
        return "unknown"


def _configured_lms() -> List[str]:
    mapping = (("OpenAI", "OPENAI_API_KEY"),
               ("Anthropic", "ANTHROPIC_API_KEY"),
               ("Custom(DSPy_LM_API_KEY)", "DSPY_LM_API_KEY"),
               ("Local(TRADERAIG_DSPY_LM_API_KEY)", "TRADERAIG_DSPY_LM_API_KEY"))
    return [name for name, key in mapping if os.environ.get(key)]


def disabled_reason() -> str:
    """Human-readable reason the DSPy layer is disabled (fast, no import)."""
    if os.environ.get(GATE_ENV) != "1":
        return (f"layer gated off: set {GATE_ENV}=1 to opt in "
                "(a subprocess / networked env is expected)")
    if not dspy_installed():
        return "dspy package not installed (pip install -r requirements-ai.txt)"
    if not _configured_lms():
        return "no LLM provider key configured (OPENAI_API_KEY / ANTHROPIC_API_KEY / DSPY_LM_API_KEY)"
    return ""


def enabled() -> bool:
    return disabled_reason() == ""


def status() -> Dict:
    from .evaluators.metrics import METRIC_WEIGHTS
    from .lm import lm_spec
    from .models import catalog
    from .programs import list_programs
    reason = disabled_reason()
    return {
        "ok": True,
        "enabled": reason == "",
        "reason": reason,
        "gate_env": GATE_ENV,
        "dspy_installed": dspy_installed(),
        "dspy_version": dspy_version(),
        "lm_configured": _configured_lms(),
        "lm": lm_spec(),
        "models": catalog(),
        "programs": list_programs(),
        "metric_weights": METRIC_WEIGHTS,
        "routes": ["/research/dspy/status", "/research/dspy/models",
                   "/research/dspy/registry"],
        "sources": _corpus_summary(),
        "governance": "optimization only; outcomes feed the validation lab "
                      "(research -> candidate -> ... -> production), never "
                      "the execution path directly",
    }


def _corpus_summary() -> Dict:
    try:
        from .datasets.strategy_lab import corpus_summary
        return corpus_summary()
    except Exception:  # status must never fail
        return {}
