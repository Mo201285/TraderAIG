"""Cross-strategy PnL correlation (Portfolio Intelligence).

Correlation is computed over the experience ledger's realised PnL series,
grouped by ``strategy_id`` (metadata key stamped at execution time by the
execution adapters). This answers the institutional question "are my
strategies diversifying or doubling up?" and feeds concentration warnings.

Series with fewer than ``MIN_SAMPLES`` pairwise observations are reported
as ``insufficient_data`` rather than fabricated with a number.
"""
from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Sequence

from core.logging import get_logger


log = get_logger("portfolio.correlation")


MIN_SAMPLES = 3


def _pearson(x: List[float], y: List[float]) -> float:
    """Pearson correlation for two equal-length series. Returns NaN for
    degenerate inputs (constant series or too few samples)."""
    n = len(x)
    if n < 2:
        return float("nan")
    mx = sum(x) / n
    my = sum(y) / n
    num = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    dx = math.sqrt(sum((xi - mx) ** 2 for xi in x))
    dy = math.sqrt(sum((yi - my) ** 2 for yi in y))
    if dx == 0.0 or dy == 0.0 or num == 0.0:
        return float("nan")
    return num / (dx * dy)


def _pnl_series(records: Sequence[Any]) -> Dict[str, Dict[str, Any]]:
    """Group ledger records into per-strategy PnL series (chronological)."""
    by_strategy: Dict[str, List[float]] = {}
    for rec in records:
        sid = (rec.metadata or {}).get("strategy_id")
        if not sid:
            continue
        res = rec.actual_result or {}
        pnl = res.get("pnl")
        if pnl is None:
            continue
        by_strategy.setdefault(str(sid), []).append(float(pnl))

    out: Dict[str, Dict[str, Any]] = {}
    for sid, series in by_strategy.items():
        out[sid] = {"series": series, "trades": len(series),
                    "net_pnl": sum(series)}
    return out


def strategy_correlation(ledger_ref=None,
                         min_samples: int = MIN_SAMPLES) -> List[Dict[str, Any]]:
    """Cross-strategy Pearson matrix over realised PnL.

    Returns a list of pairwise entries (only strategies with >= ``min_samples``
    are paired together); strategies lacking the sample count are reported once
    in the ``insufficient_data`` list.
    """
    if ledger_ref is None:
        try:
            from learning.experience import ledger as ledger_singleton
            ledger_ref = ledger_singleton
        except Exception:  # noqa: BLE001
            return []

    try:
        records = ledger_ref.all()
    except Exception:  # noqa: BLE001
        records = []

    series = _pnl_series(records)
    names = sorted(series.keys())

    pairs: List[Dict[str, Any]] = []
    insufficient: List[str] = []
    for i, a in enumerate(names):
        if series[a]["trades"] < min_samples:
            insufficient.append(a)
            continue
        for b in names[i + 1:]:
            if series[b]["trades"] < min_samples:
                continue
            n = min(len(series[a]["series"]), len(series[b]["series"]))
            # Align by trade index from the most recent n trades so both
            # strategies are compared over the same horizon window.
            x = series[a]["series"][-n:]
            y = series[b]["series"][-n:]
            if n < min_samples:
                insufficient.append(f"{a}~{b}")
                continue
            r = _pearson(x, y)
            pairs.append({
                "a": a,
                "b": b,
                "correlation": round(r, 4),
                "samples": n,
                "net_pnl_a": round(series[a]["net_pnl"], 2),
                "net_pnl_b": round(series[b]["net_pnl"], 2),
                "diversifying": (not math.isnan(r) and r < -0.3),
                "concentrated": (not math.isnan(r) and r >= 0.8),
            })

    pairs.sort(key=lambda p: (p["a"], p["b"]))
    return {
        "generated_at": time.time(),
        "pairs": pairs,
        "insufficient_data": sorted(set(insufficient)),
        "strategies_tracked": len(names),
    }
