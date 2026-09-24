"""L3 (appendix B): real executed PnL reaches the strategy lab corpus.

Until this feed, the only registry writes came from ``strategy_lab_run.py``
(simulated walk-forward scans), so the research loop never saw reality.
This module folds real Experience-Ledger performance back into the registry
as read-only ``live_performance`` metadata - it never transitions stages
(promotion stays governed through change requests / ReviewLoop).
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional, Sequence

from core.logging import get_logger
from research.strategy_lab.registry import StrategyRegistry

log = get_logger("lab.live_feed")


def feed_registry_from_ledger(registry: StrategyRegistry,
                              records: Sequence[Any],
                              min_trades: int = 30,
                              now: Optional[float] = None) -> Dict[str, Any]:
    """Upsert per-strategy live stats from experience records.

    Only strategies already registered in the corpus are touched; rows without
    a ``strategy_id`` stamp and samples below ``min_trades`` are skipped (a
    tiny live sample must never masquerade as evidence). Returns:
    ``{"fed": {sid: stats}, "skipped": {sid: reason}}``.
    """
    from learning.performance import PerformanceAttributor

    rows = PerformanceAttributor().by_strategy(records, ownership="system")
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now or time.time()))
    fed: Dict[str, Dict] = {}
    skipped: Dict[str, str] = {}

    for row in rows:
        sid = row["strategy_id"]
        if sid in (None, "unattributed"):
            continue
        if registry.get(sid) is None:
            skipped[sid] = "not_in_registry"
            continue
        trades = row["total_trades"]
        if trades < min_trades:
            skipped[sid] = f"too_few_trades:{trades}"
            continue

        stats = {
            "source": "experience_ledger",
            "fed_at": stamp,
            "total_trades": trades,
            "winning_trades": row["winning_trades"],
            "losing_trades": row["losing_trades"],
            "win_rate": row["win_rate"],
            "gross_pnl": round(row["gross_pnl"], 2),
            "net_pnl": round(row["net_pnl"], 2),
            "profit_factor": round(row["profit_factor"], 2),
            "max_drawdown": round(row["max_drawdown"], 2),
        }
        registry.attach_live_performance(sid, stats)
        fed[sid] = stats

    log.info(f"live feed attached {len(fed)} strategies, "
             f"skipped {len(skipped)}")
    return {"fed": fed, "skipped": skipped}


def default_registry(data_dir: Optional[str] = None) -> StrategyRegistry:
    from research.strategy_lab.priors import registry_path_for

    registry = StrategyRegistry(registry_path_for(data_dir))
    registry.load()
    return registry
