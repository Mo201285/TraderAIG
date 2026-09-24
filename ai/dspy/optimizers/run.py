"""Optimiser runner (M7.8 scaffold) — real DSPy compilation, gated.

Design order honoured: corpus -> examples -> deterministic baseline ->
evaluation metric -> optimiser -> compiled program -> report (then the
promotion registry / validation lab).

Offline safety: the gate and the training-corpus checks happen *before* any
dspy import. ``optimize_program`` only touches dspy once it must, i.e. in a
networked environment where the layer is enabled.
"""

from __future__ import annotations

import inspect
import json
import os
from typing import Any, Dict, List, Optional

from .registry import (resolve_optimizer, OPTIMIZER_PRIORITY,
                       OPTIMIZER_PRIORITY_LOCAL)


def default_signature(program_id: str) -> str:
    """Program ids live in the catalogue; optimisation targets a signature."""
    from ..signatures.contracts import _SPECS_BY_ID
    if program_id in _SPECS_BY_ID:
        return program_id
    if program_id == "ict_scalping":
        return "score_confluence"  # verdict-level fusion contract
    return "score_confluence"


def build_trainset(signature_id: str, max_examples: int = 50) -> List[Dict[str, Any]]:
    from ..datasets.strategy_lab import examples_for_program, load_records
    records = load_records(limit=8000)
    return examples_for_program(signature_id, records)[:max_examples]


def _dspy_examples(signature_id: str, examples: List[Dict[str, Any]], inputs: List[str]):
    import dspy
    out = []
    for ex in examples:
        item = dspy.Example(**ex)
        if inputs:
            item = item.with_inputs(*[i for i in inputs if i in ex])
        out.append(item)
    return out


def optimize_program(program_id: str = "ict_scalping",
                     trials: int = 6,
                     bootstrap: Optional[int] = None,
                     max_examples: int = 50,
                     metric=None) -> Dict[str, Any]:
    """Compile a program with the best available optimiser.

    Returns a report dict; never raises with a misleading status. On success
    the ``program_id``/optimised signature is surfaced so the caller can
    promote a candidate in ``registry/programs.py``.
    """
    from ..runtime import disabled_reason

    reason = disabled_reason()
    if reason:
        return {"ok": False, "reason": reason, "elapsed_seconds": 0.0}

    signature_id = default_signature(program_id)

    # corpus checks first -- no dspy import unless we genuinely proceed
    try:
        examples = build_trainset(signature_id, max_examples=max_examples)
    except Exception as exc:
        return {"ok": False, "reason": f"corpus build failed: {exc}", "elapsed_seconds": 0.0}
    if not examples:
        return {"ok": False, "reason": "no training examples in corpus",
                "signature": signature_id, "elapsed_seconds": 0.0}

    # provider config must be valid BEFORE importing dspy (offline-safe)
    from ..lm import lm_spec
    spec = lm_spec()
    if not spec["ok"]:
        return {"ok": False, "reason": f"LM provider: {spec['error']}",
                "signature": signature_id, "elapsed_seconds": 0.0}

    import dspy  # only now (networked env expected)

    from ..lm import configure_lm
    configured = configure_lm()
    if not configured["ok"]:
        return {"ok": False, "reason": f"LM configure failed: {configured['error']}",
                "signature": signature_id, "elapsed_seconds": 0.0}

    from ..evaluators.metrics import trading_metric
    from ..modules import build_module
    from ..signatures.contracts import _SPECS_BY_ID
    from ..evaluators.evaluation import evaluate_program

    metric_fn = metric or trading_metric
    spec = _SPECS_BY_ID[signature_id]

    # deterministic baseline BEFORE optimisation ("evaluation first")
    baseline_program = build_module(signature_id)()
    baseline = evaluate_program(
        lambda ex: _safe_call(baseline_program, ex, spec.inputs),
        examples, metric=metric_fn, tag=f"{signature_id}:baseline")

    resolved = resolve_optimizer(
        dspy,
        priority=(OPTIMIZER_PRIORITY_LOCAL
                  if configured.get("provider") == "local"
                  else OPTIMIZER_PRIORITY))
    if resolved is None:
        return {"ok": False, "reason": f"no optimiser class available among {list(OPTIMIZER_PRIORITY)}",
                "signature": signature_id, "elapsed_seconds": 0.0}
    name, optimizer_cls = resolved

    trainset = _dspy_examples(signature_id, examples, spec.inputs)
    target = build_module(signature_id)()

    compiled = None
    compile_error = None
    optimizer = None
    metric_for_opt = (_gepa_metric_adapter(metric_fn) if name == "GEPA"
                      else _metric_adapter(metric_fn))
    ctor_kwargs = {"metric": metric_for_opt}
    if name == "GEPA":
        # GEPA asserts exactly one of auto / max_full_evals / max_metric_calls,
        # and requires a reflection LM (or custom instruction proposer).
        ctor_kwargs["max_metric_calls"] = max(1, int(20 + 10 * max(1, trials)))
        if configured.get("lm_ref") is not None:
            ctor_kwargs["reflection_lm"] = configured["lm_ref"]
    else:
        # BootstrapFewShot / MIPROv2 take example budgets at construction.
        ctor_kwargs["max_bootstrapped_demos"] = int(bootstrap or 4)
        ctor_kwargs["max_labeled_demos"] = int(bootstrap or 4)
    try:
        optimizer = optimizer_cls(**ctor_kwargs)
    except Exception as exc:  # some versions require extra ctor args
        try:
            optimizer = optimizer_cls(**ctor_kwargs,
                                      max_bootstrapped_demos=int(bootstrap or 4))
        except Exception:
            compile_error = f"optimizer ctor {type(exc).__name__}: {exc}"
    if optimizer is not None:
        attempt_errors = []
        attempts = [lambda: optimizer.compile(target, trainset=trainset)]
        if name == "MIPROv2":
            attempts.insert(0, lambda: optimizer.compile(
                target, trainset=trainset,
                max_bootstrapped_demos=int(bootstrap or 4)))
        for attempt in attempts:
            try:
                compiled = attempt()
                attempt_errors = []
                break
            except Exception as exc:
                attempt_errors.append(f"{type(exc).__name__}: {exc}")
        if attempt_errors and not compile_error:
            compile_error = attempt_errors[-1]

    report = {
        "ok": True,
        "optimizer": name,
        "signature": signature_id,
        "lm_provider": configured.get("provider"),
        "lm_model": configured.get("model"),
        "metric": getattr(metric_fn, "__name__", "metric"),
        "compiled": False,
        "reason": "capability resolved; compile step needs a reachable LM "
                  "(run in a networked env). " + (compile_error or ""),
        "baseline_score": baseline.get("mean_score"),
        "trainset": len(trainset),
        "trials": trials,
    }
    if compiled is not None:
        after = evaluate_program(
            lambda ex: _safe_call(compiled, ex, spec.inputs),
            examples, metric=metric_fn, tag=f"{signature_id}:compiled")
        compiled_str = None
        if hasattr(compiled, "save"):
            import tempfile
            try:
                with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
                    compiled.save(tf.name)
                    tmp = tf.name
                with open(tmp, "r", encoding="utf-8") as f:
                    loaded = f.read().strip()
                os.remove(tmp)
                compiled_str = loaded if len(loaded) > 200 else None
            except Exception:
                compiled_str = None
        if compiled_str is None and hasattr(compiled, "dump_state"):
            try:
                dumped = json.dumps(compiled.dump_state(), default=str)
                compiled_str = dumped if len(dumped) > 200 else None
            except Exception:
                compiled_str = None
        report.update({
            "compiled": True,
            "compiled_score": after.get("mean_score"),
            "program_serialized": compiled_str is not None,
        })
        if compiled_str:
            report["program_blob"] = compiled_str
    return report


def _cast_example(obj: Any) -> Dict[str, Any]:
    """Normalise a dspy.Example / dict / dataclass-like into a plain dict."""
    if isinstance(obj, dict):
        return obj
    to_dict = getattr(obj, "toDict", None)
    if callable(to_dict):
        return to_dict()
    as_dict = getattr(obj, "as_dict", None)
    if callable(as_dict):
        return as_dict()
    try:
        return dict(obj)
    except Exception:
        return {}


def _metric_call(metric, gold, pred, trace):
    """Call the metric with what it accepts: 2-arg metrics like
    ``trading_metric`` get ``(gold, pred)``; 3-arg dspy-style metrics get
    ``(gold, pred, trace)``. Never pass positional args the metric lacks."""
    try:
        sig = inspect.signature(metric)
        pos = sum(1 for p in sig.parameters.values()
                  if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD))
    except Exception:
        pos = 2
    gold = _cast_example(gold)
    pred = _cast_example(pred)
    if pos >= 3:
        return metric(gold, pred, trace)
    return metric(gold, pred)


def _metric_adapter(metric):
    """Adapt to teleprompt metric calls (gold, pred, trace[, pred_name,
    pred_trace]). Extra args are optional: e.g. BootstrapFewShot calls with
    three arguments. No functools.wraps: some optimisers introspect arity."""
    def _wrapped(gold, pred, trace, pred_name=None, pred_trace=None):
        return _metric_call(metric, gold, pred, trace)

    return _wrapped


def _gepa_metric_adapter(metric):
    """GEPA requires a metric with five REQUIRED positional arguments."""
    def _wrapped(gold, pred, trace, pred_name, pred_trace):
        return _metric_call(metric, gold, pred, trace)

    return _wrapped


def _safe_call(program, example: Dict[str, Any], inputs: List[str]) -> Dict[str, Any]:
    kwargs = {name: example.get(name, "") for name in inputs}
    result = program(**kwargs) if hasattr(program, "__call__") else None
    if result is None:
        return {}
    if hasattr(result, "as_dict"):
        return result.as_dict()
    return dict(getattr(result, "__dict__", {}) or {})


__all__ = ["optimize_program", "build_trainset", "default_signature", "OPTIMIZER_PRIORITY"]
