"""Professional trading metric for program evaluation (pure Python, dspy-free).

The metric dspy should optimise against, and the metric backtest reports
bind as a tie-round. Components (project norm):

      Decision Quality + Entry Quality + Risk Quality + Timing
      + MAE/MFE discipline + R:R   + Regime fit + Drawdown impact
      - False-positive penalty (a call that fired but the move never came)

Everything here is deterministic and shape-agnostic over dict payloads, so it
is usable to evaluate *any* callable program — including the deterministic
fallbacks and historical backtests — without importing dspy.
"""

from __future__ import annotations

from typing import Any, Dict, List

MIN_CONFIDENCE_GATE = 0.60
MIN_EDGE_RR = 1.5
MAX_MAE_ATR = 1.0  # max tolerated MAE in ATR units before penalty
MAX_PENALTY = 0.25

# weight by contract: decision holds most of the score, discipline second
METRIC_WEIGHTS = {
    "direction": 0.25,
    "entry": 0.15,
    "risk": 0.15,
    "timing": 0.10,
    "mae_mfe": 0.10,
    "rr": 0.10,
    "regime": 0.05,
    "drawdown_impact": 0.05,
    "false_positive": 0.05,
}


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(x)))


def _get(payload: Any, *names: str, default: Any = None) -> Any:
    """Read key from a nested dict, falling back through aliases."""
    if isinstance(payload, dict):
        for name in names:
            if name in payload and payload[name] is not None:
                return payload[name]
    return default


_QUALITATIVE_FLOATS = {
    "low": 0.25,
    "medium": 0.5,
    "high": 0.75,
    "conservative": 0.4,
    "moderate": 0.5,
    "aggressive": 0.7,
}


def _to_float(value: Any, default: float = 0.0) -> float:
    """Robust float coercion: numbers pass through, qualitative labels map to
    fractions, anything unparseable falls back to ``default``."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in _QUALITATIVE_FLOATS:
            return _QUALITATIVE_FLOATS[text]
        try:
            return float(text)
        except ValueError:
            return default
    return default


def score_trade(example: Dict[str, Any], prediction: Dict[str, Any]) -> Dict[str, Any]:
    """Score a predicted trade against the example's actual outcome."""
    confidence = _to_float(_get(prediction, "confidence", "confluence_score", default=0.0) or 0.0)
    pred_dir = str(_get(prediction, "direction", "recommended_bias", "trade_direction", default="")).lower()
    actual_dir = str(_get(example, "actual_direction", "outcome_direction", default="")).lower()
    moved = bool(_get(example, "moved", "outcome_moved", default=False))
    if not moved:
        actual_dir = _get(example, "outcome_direction", default="") or ""

    # --- decision ---------------------------------------------------------
    directional = pending = False
    if pred_dir in ("buy", "long", "up", "bullish"):
        directional, pending = True, True
    elif pred_dir in ("sell", "short", "down", "bearish"):
        directional, pending = True, False
    held_dir = ("buy" if pending else "sell") if directional else ""
    hit = directional and bool(actual_dir) and (actual_dir == held_dir)
    if not directional:
        decision = 0.0  # nothing to act on
    elif not hit:
        decision = 0.0
    else:
        decision = _clamp(confidence / MIN_CONFIDENCE_GATE)  # 1 at gate
        decision = min(1.0, decision) if confidence >= MIN_CONFIDENCE_GATE else decision * 0.5

    # --- entry ------------------------------------------------------------
    # ideal entry = inside the zone / at the tagged level; else neutral 0.5
    entry_r = _get(prediction, "entry_quality", "entry", default=None)
    if entry_r is None:
        entry = 0.5
    elif isinstance(entry_r, (int, float)):
        entry = _clamp(entry_r)
    else:
        entry = 0.5

    # --- risk -------------------------------------------------------------
    risk_r = _get(prediction, "risk_quality", "risk_score", default=None)
    if risk_r is None:
        risk = 0.5
    elif isinstance(risk_r, (int, float)):
        risk = _clamp(risk_r)
    else:
        risk = 0.5

    # --- timing -----------------------------------------------------------
    timing_r = _get(prediction, "timing_quality", "session_quality", "timing", default=None)
    if timing_r is None:
        timing = 0.5
    elif isinstance(timing_r, (int, float)):
        timing = _clamp(timing_r)
    else:
        timing = 0.5

    # --- MAE / MFE discipline ----------------------------------------------
    mae = _get(example, "mae_atr", "mae", default=None)
    mfe = _get(example, "mfe_atr", "mfe", default=None)
    if mae is None:
        mae_mfe = 0.5  # unavailable -> neutral
    else:
        pen = MAX_PENALTY if _to_float(mae) > MAX_MAE_ATR else 0.0
        benefit = 0.0
        if mfe is not None:
            benefit = min(1.0, _to_float(mfe) / max(1e-9, 2.5 * MAX_MAE_ATR))
        mae_mfe = _clamp(benefit - pen)

    # --- R:R -----------------------------------------------------------------
    rr = _get(example, "rr_ratio", "rr", "reward_risk", default=None)
    if rr is None:
        rr_score = 0.5
    else:
        rrf = max(0.0, _to_float(rr))
        rr_score = _clamp(0.0 if rrf < 1.0 else min(1.0, (rrf - MIN_EDGE_RR + 0.5) / 2.0))

    # --- regime fit -----------------------------------------------------------
    reg = _get(prediction, "regime_fit", "regime", default=None)
    regime = 0.5 if reg is None else _clamp(float(reg)) if isinstance(reg, (int, float)) else (0.7 if str(reg).lower() in ("yes", "aligned", "good") else 0.3)

    # --- drawdown impact -------------------------------------------------------
    ddi = _get(example, "drawdown_impact", default=None)
    drawdown = 0.5 if ddi is None else _clamp(1.0 - _to_float(ddi, default=0.5))

    # --- false positive penalty -------------------------------------------------
    fired = bool(_get(prediction, "trade", "action", "fired", default=True))
    if fired and directional and not moved:
        fp = 0.0
    elif fired and directional and (not hit):
        fp = 0.25
    else:
        fp = 1.0

    components = {
        "direction": decision,
        "entry": entry,
        "risk": risk,
        "timing": timing,
        "mae_mfe": mae_mfe,
        "rr": rr_score,
        "regime": regime,
        "drawdown_impact": drawdown,
        "false_positive": fp,
    }
    total_w = sum(METRIC_WEIGHTS.values())
    score = _clamp(sum(components[k] * METRIC_WEIGHTS[k] for k in components) / total_w)

    return {
        "score": round(score, 4),
        "components": {k: round(v, 4) for k, v in components.items()},
        "hit": hit,
        "directional": directional,
    }


def trading_metric(example: Dict[str, Any], prediction: Dict[str, Any]) -> float:
    """Metric signature compatible with dspy optimisers and backtests."""
    return score_trade(example, prediction)["score"]


def aggregate(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Batch aggregate of ``score_trade`` rows."""
    if not results:
        return {"ok": True, "samples": 0, "mean_score": 0.0, "win_rate": 0.0}
    score = sum(r["score"] for r in results) / len(results)
    scored = [r for r in results if r.get("directional")]
    wins = [r for r in scored if r.get("hit")] if scored else []
    return {
        "ok": True,
        "samples": len(results),
        "directional_samples": len(scored),
        "mean_score": round(score, 4),
        "win_rate": round(len(wins) / len(scored), 4) if scored else 0.0,
        "mean_components": {
            k: round(sum(r["components"][k] for r in results) / len(results), 4)
            for k in METRIC_WEIGHTS
        },
    }


__all__ = ["METRIC_WEIGHTS", "score_trade", "trading_metric", "aggregate", "MIN_CONFIDENCE_GATE", "MIN_EDGE_RR"]
