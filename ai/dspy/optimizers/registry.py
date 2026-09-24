"""Optimiser selection (version-safe).

The optimiser runs in the watchduced subprocess (``worker.py``). We never
import dspy here; ``resolve_optimizer`` is called by the worker with the
already-imported module.
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

# Ordered by preference: GEPA is the DSPy 3.x auto-optimiser, MIPROv2 the
# established instruction/candidate optimiser, BootstrapFewShot the safest
# default for constrained (RAM-limited) environments.
OPTIMIZER_PRIORITY = ("GEPA", "MIPROv2", "BootstrapFewShot")

# For local (Ollama / LM Studio / vLLM) providers with small models, an
# example-demo optimiser is far more robust than a reflection-heavy one.
OPTIMIZER_PRIORITY_LOCAL = ("BootstrapFewShot", "MIPROv2", "GEPA")

# scaffold version of optimizer classes available in dspy 3.3.x
_OPTIMIZER_INITS: dict = {}


def optimizer_names() -> Tuple[str, ...]:
    return OPTIMIZER_PRIORITY


def resolve_optimizer(dspy_module: Any, priority=None) -> Optional[Tuple[str, Any]]:
    """Return ``(name, class)`` of the first available optimiser."""
    order = priority or OPTIMIZER_PRIORITY
    for name in order:
        cls = getattr(dspy_module, name, None)
        if cls is not None:
            return name, cls
    return None


__all__ = ["OPTIMIZER_PRIORITY", "optimizer_names", "resolve_optimizer"]
