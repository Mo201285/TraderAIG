"""Learning split: Research Learning vs Execution Learning (M8.4).

UPDATE.md §9/§10 requires the two learning tracks to stay *separate* in both
storage and reporting:

  - Research Learning consumes the Strategy Lab's recorded trade observations
    (jsonl corpus under research/strategy_lab/data) - what setups/strategies
    produced edge in replay. This is off-flow, never touches live runtime.
  - Execution Learning consumes the Experience Ledger's *filled* records
    (slippage, latency, fees, fill quality, realized PnL) - how the runtime
    actually executed. This is the Execution Truth plane's learning surface.

This module is purely a read/compute helper; it mutates neither store.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional, Sequence

from core.logging import get_logger
from learning.experience import ExperienceRecord, ledger


log = get_logger("learning.split")


def execution_learning(records: Sequence[ExperienceRecord],
                       *, source: Optional[str] = None) -> Dict[str, Any]:
    """Execution-side learning stats over filled system records.

    With `source` set, only records whose `actual_result["source"]` matches are
    counted. The Execution Truth plane passes `"mt5"` so its "realized" figures
    are real account fills, not paper/simulated ones that merely lack a source
    (an absent source used to default into the live bucket).
    """
    filled = [
        r for r in records
        if (r.actual_result or {}).get("filled") is True
        and (r.actual_result or {}).get("origin", "system") == "system"
        and (source is None
             or (r.actual_result or {}).get("source") == source)
    ]

    def pnl_of(r: ExperienceRecord) -> float:
        value = (r.actual_result or {}).get("pnl")
        # `mt5o:` fallback records carry pnl None (profit unknown); that is not
        # a breakeven trade and must not crash the surface that reads them.
        return float(value) if value is not None else 0.0

    pnls = [pnl_of(r) for r in filled]
    wins = sum(1 for p in pnls if p > 0)
    losses = sum(1 for p in pnls if p < 0)

    def avg(key: str, default: float = 0.0) -> float:
        if not filled:
            return default
        values = [float(getattr(r, key, 0.0) or 0.0) for r in filled]
        return sum(values) / len(values)

    slippages = [float((r.actual_result or {}).get("slippage", 0.0) or 0.0)
                 for r in filled]
    fill_ticks = [bool((r.actual_result or {}).get("filled")) for r in filled]

    errors: Dict[str, int] = {}
    for r in filled:
        key = r.error_classification.value if r.error_classification else "unclassified"
        errors[key] = errors.get(key, 0) + 1

    return {
        "track": "execution",
        "count": len(filled),
        "win_rate": (wins / len(filled)) if filled else 0.0,
        "wins": wins,
        "losses": losses,
        "net_pnl": round(sum(pnls), 4),
        "avg_pnl": round(sum(pnls) / len(filled), 4) if filled else 0.0,
        "avg_slippage": round(sum(slippages) / len(filled), 4) if filled else 0.0,
        "avg_delay_ms": round(avg("delay_ms"), 2),
        "avg_fees": round(avg("fees"), 4),
        "error_counts": errors,
        "fill_count": sum(1 for f in fill_ticks if f),
        "source_filter": source,
        "basis": (f"fills recorded with actual_result.source == {source!r}"
                  if source else
                  "all filled system records (paper and live together)"),
        "storage": "experience_ledger (persistence DB)",
    }


def attributed_to_account(records: Sequence[ExperienceRecord],
                          account_login: Any) -> list:
    """Records whose metadata names `account_login`.

    The ledger outlives any one terminal session, so a row written while a
    different account was attached is not evidence about *this* account. A
    falsy login (disconnected) is a no-op: with no account to attribute to,
    the caller keeps whatever it had rather than silently dropping history.
    """
    login = str(account_login or "").strip()
    if not login or login == "0":
        return list(records)
    return [r for r in records
            if str((r.metadata or {}).get("account") or "") == login]


def research_learning(observations) -> Dict[str, Any]:
    """Research-side learning stats over lab observations (TradeObservation)."""
    from research.strategy_lab.validation import aggregate_observations

    rows = list(observations or [])
    total = len(rows)
    per_strategy: Dict[str, Dict[str, Any]] = {}
    by_regime: Dict[str, list] = {}
    by_session: Dict[str, list] = {}

    for o in rows:
        sid = getattr(o, "strategy_id", None) or "unknown"
        per_strategy.setdefault(sid, []).append(o)
        regime = getattr(o, "regime", None) or "unknown"
        by_regime.setdefault(regime, []).append(getattr(o, "r_multiple", 0.0))
        session = getattr(o, "session", None) or "unknown"
        by_session.setdefault(session, []).append(getattr(o, "r_multiple", 0.0))

    strategy_stats = sorted(
        ({**aggregate_observations(obs),
          "strategy_id": sid,
          "passed": aggregate_observations(obs)["expected_value"] > 0.0}
         for sid, obs in per_strategy.items()),
        key=lambda s: -s["expected_value"],
    )

    regime_edge = {
        k: round(sum(v) / len(v), 4) for k, v in by_regime.items()}
    session_edge = {
        k: round(sum(v) / len(v), 4) for k, v in by_session.items()}

    stats = aggregate_observations(rows)
    return {
        "track": "research",
        "count": total,
        "win_rate": stats["win_rate"],
        "expected_value": stats["expected_value"],
        "profit_factor": stats["profit_factor"],
        "by_regime_edge": regime_edge,
        "by_session_edge": session_edge,
        "strategies": strategy_stats,
        "storage": "strategy_lab observations (jsonl corpus)",
    }


def split(records: Optional[Sequence[ExperienceRecord]] = None,
          observations=None) -> Dict[str, Any]:
    """Combined split report; both tracks remain independent."""
    recs = list(records if records is not None else ledger.all())
    return {
        "generated_at": time.time(),
        "research": research_learning(observations),
        "execution": execution_learning(recs),
        "note": ("research and execution learning are recorded in separate "
                 "stores and must not be merged for edge attribution"),
    }
