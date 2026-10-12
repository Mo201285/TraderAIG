"""Model governance for the DSPy layer (S8 / Phase C).

Turns the DSPy layer's static governance *note* into a computed, read-only
surface. Every registered program version (``ProgramRegistry``) is checked
against two things it already records:

* **The promotion gate.** A version carries the ``baseline_score`` it started
  from and the ``compiled_score`` the optimiser reached. The gate is "the
  compiled program beats its baseline"; a promoted version (paper / production)
  that *failed* the gate, or was promoted with no gate evidence at all, is a
  governance alert.
* **The model it was promoted on.** A version records the ``lm_provider`` /
  ``lm_model`` it was compiled against. The model actually served *now* comes
  from the provider adapter (``ai.dspy.models.catalog``). The same program under
  a different model is drift; a recorded local model that is no longer served is
  a missing-model alert.

Everything here is report-only: it never promotes, quarantines, trades or routes.
No number is invented -- a version without a baseline or compiled score is
``ungated``, not "passed", and a version with no recorded model is ``none``, not
"matching".
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from .registry.programs import ProgramRegistry, ProgramStatus

# A version at or beyond this stage is "in service" and drift on it is an alert
# rather than a note. `validated` is still a lab stage, so it is not in service.
PROMOTED_STATES = (ProgramStatus.PAPER.value, ProgramStatus.PRODUCTION.value)

PROGRAM_ROUTE = "/research/dspy/governance"


def _gate(version) -> Dict[str, Any]:
    compiled = version.compiled_score
    baseline = version.baseline_score
    if compiled is None or baseline is None:
        return {"state": "ungated", "compiled_score": compiled,
                "baseline_score": baseline, "margin": None}
    margin = round(float(compiled) - float(baseline), 6)
    return {
        "state": "passed" if compiled > baseline else "failed",
        "compiled_score": compiled,
        "baseline_score": baseline,
        "margin": margin,
    }


def _model(version, served_model: Optional[str], local_reachable: bool,
           available: List[str]) -> Dict[str, Any]:
    recorded = version.lm_model
    if not recorded:
        return {"state": "none", "compiled_on": None,
                "served_model": served_model}
    if not served_model:
        state = "no_served_model"
    elif recorded == served_model:
        state = "match"
    elif (local_reachable and "/" not in recorded
          and recorded not in available):
        state = "unavailable"
    else:
        state = "changed"
    return {"state": state, "compiled_on": recorded,
            "served_model": served_model}


def governance_report(registry: Optional[ProgramRegistry] = None,
                      catalog_fn: Optional[Callable[[], Dict[str, Any]]] = None
                      ) -> Dict[str, Any]:
    """Computed model-governance + drift report over the program registry."""
    registry = registry or ProgramRegistry()
    if catalog_fn is None:
        from .models import catalog as catalog_fn  # local name; probe is bounded

    try:
        catalogue = catalog_fn() or {}
    except Exception:  # noqa: BLE001 -- a probe failure must never crash the surface
        catalogue = {}

    configured = catalogue.get("configured") or {}
    served_model = configured.get("model") or None
    served_provider = configured.get("provider") or None
    local_reachable = bool(catalogue.get("local_reachable"))
    available = [m.get("name") for m in (catalogue.get("models") or [])
                 if m.get("name")]

    versions = registry.load()
    programs: List[Dict[str, Any]] = []
    alerts: List[Dict[str, Any]] = []
    counts = {"versions": 0, "promoted": 0, "gate_passed": 0,
              "gate_failed": 0, "gate_ungated": 0, "model_drift": 0}

    for v in versions:
        counts["versions"] += 1
        promoted = v.status in PROMOTED_STATES
        gate = _gate(v)
        model = _model(v, served_model, local_reachable, available)
        counts[f"gate_{gate['state']}"] = counts.get(f"gate_{gate['state']}", 0) + 1
        if promoted:
            counts["promoted"] += 1
        if model["state"] in ("changed", "unavailable"):
            counts["model_drift"] += 1

        had_alert = False

        if gate["state"] == "failed":
            had_alert = True
            alerts.append({
                "kind": "promotion_gate_failed", "severity": "high",
                "program": v.program, "version": v.version, "status": v.status,
                "detail": (f"compiled score {gate['compiled_score']} does not beat "
                           f"baseline {gate['baseline_score']}"),
            })
        elif gate["state"] == "ungated" and promoted:
            had_alert = True
            alerts.append({
                "kind": "promoted_without_gate", "severity": "medium",
                "program": v.program, "version": v.version, "status": v.status,
                "detail": "promoted with no recorded baseline/compiled score",
            })

        if model["state"] == "unavailable":
            had_alert = True
            alerts.append({
                "kind": "model_unavailable", "severity": "medium",
                "program": v.program, "version": v.version, "status": v.status,
                "detail": (f"compiled on model {model['compiled_on']!r}, which the "
                           "local endpoint no longer serves"),
            })
        elif model["state"] == "changed" and promoted:
            had_alert = True
            alerts.append({
                "kind": "model_drift", "severity": "high",
                "program": v.program, "version": v.version, "status": v.status,
                "detail": (f"compiled on {model['compiled_on']!r} but "
                           f"{model['served_model']!r} is served now"),
            })

        programs.append({
            "program": v.program,
            "version": v.version,
            "status": v.status,
            "promoted": promoted,
            "gate": gate,
            "model": model,
            "alert": had_alert,
        })

    return {
        "ok": True,
        "route": PROGRAM_ROUTE,
        "served": {
            "provider": served_provider,
            "model": served_model,
            "local_reachable": local_reachable,
            "available_models": available,
        },
        "programs": programs,
        "alerts": alerts,
        "summary": counts,
        "note": ("report-only: governance detects gate regressions and model "
                 "drift; it never promotes, quarantines or trades"),
        "read_only": True,
        "is_authorisation": False,
        "trade_authority": "risk/governor.py",
    }


__all__ = ["governance_report", "PROMOTED_STATES", "PROGRAM_ROUTE"]
