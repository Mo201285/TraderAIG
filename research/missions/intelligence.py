"""The Ollama intelligence router (RMI-03, row 752).

MASTER_ARCHITECTURE s6 is not one LLM but an AI INTELLIGENCE ROUTER: fast
local Ollama, strong local Ollama, cloud fallback only when a task is worth
the cost. Ollama is the Local Inference Layer (summarise, classify, extract,
analyse, structured evidence -- never a replacement for the Research Core or
DSPy), and this module is the REPORT half of that contract, mirroring
`ai/dspy/models.py`'s discipline:

* `route` maps a task class to its tier and names the model that WOULD run it
  from what is actually known -- the configured model (env) first, else the
  local catalogue the Ollama server reports -- and refuses an unknown task
  class outright (no invented tier);
* `router_report` probes the local server best-effort with a short timeout
  (offline-safe: unreachable -> `reachable: False` and the honest route, never
  an invented model name);
* nothing here CALLS a model. It is an intelligence read surface for
  Paperclip when it picks the `model` a mission's crew runs on.

Every payload carries `is_authorisation: False` and names the Risk Governor.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Iterable

from research.evidence_plane import IS_AUTHORISATION, TRADE_AUTHORITY

FAST_LOCAL_TASKS = ("classify", "code", "extract", "summarize")
STRONG_LOCAL_TASKS = ("analyze", "hypothesis", "review", "synthesize")
TASK_CLASSES = FAST_LOCAL_TASKS + STRONG_LOCAL_TASKS
TIERS = ("fast_local", "strong_local", "cloud_fallback")

CLOUD_NOTE = (
    "cloud fallback is reserved for a task worth the cost (MASTER "
    "ARCHITECTURE s6); this report never calls any model, local or cloud"
)


def _tier_for(task_class: str) -> str:
    return "fast_local" if task_class in FAST_LOCAL_TASKS else "strong_local"


def route(task_class: str, *, local_models: Iterable[str] = (),
          configured: str = "", reachable: bool = False) -> Dict[str, Any]:
    """Route one task class honestly; raises on an unknown class."""
    wanted = str(task_class or "").strip()
    if wanted not in TASK_CLASSES:
        raise ValueError(
            f"unknown task class {wanted!r}; known classes are "
            f"{', '.join(TASK_CLASSES)}")
    tier = _tier_for(wanted)
    models = sorted({str(m).strip() for m in local_models if str(m).strip()})
    named = str(configured or "").strip()
    if named:
        model, source = named, "configured"
    elif models:
        # deterministic pick: the smallest catalogue model is the fast tier's,
        # the largest is the strong tier's -- same probe, same answers.
        model, source = (models[0] if tier == "fast_local" else models[-1]), "local_probe"
    else:
        model, source = "", "unavailable"
    return {
        "task_class": wanted,
        "tier": tier,
        "model": model,
        "source": source,
        "reachable": bool(reachable),
    }


def router_report(*, probe: Dict[str, Any] | None = None,
                  configured: str | None = None) -> Dict[str, Any]:
    """The full router read surface (best-effort probe, never raises)."""
    if probe is None:
        from ai.dspy.models import probe_local_models
        probe = probe_local_models(timeout=1.5)
    if configured is None:
        from ai.dspy.lm import LM_ENV
        configured = os.environ.get(LM_ENV, "")
    reachable = bool(probe.get("reachable"))
    names = [str(m.get("name") or "") for m in probe.get("models", [])
             if isinstance(m, dict)]
    routes = [
        route(tc, local_models=names, configured=configured,
              reachable=reachable)
        for tc in TASK_CLASSES
    ]
    return {
        "routes": routes,
        "tiers": list(TIERS),
        "task_classes": list(TASK_CLASSES),
        "probe": {
            "reachable": reachable,
            "models": sorted(n for n in names if n),
            "model_count": len([n for n in names if n]),
        },
        "configured_model": str(configured or "").strip() or None,
        "cloud_fallback": {"wired": False, "note": CLOUD_NOTE},
        "is_authorisation": IS_AUTHORISATION,
        "trade_authority": TRADE_AUTHORITY,
    }


__all__ = ["FAST_LOCAL_TASKS", "STRONG_LOCAL_TASKS", "TASK_CLASSES",
           "TIERS", "route", "router_report"]
