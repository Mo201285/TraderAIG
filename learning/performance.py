"""Performance attribution: where PnL came from and who is accountable.

Breaks down realized PnL by strategy component (direction, regime,
session, entry type) and produces a repeatable report.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from core.logging import get_logger
from learning.experience import ExperienceRecord, ledger


log = get_logger("learning.performance")


@dataclass
class PerformanceReport:
    generated_at: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    gross_pnl: float
    net_pnl: float
    win_rate: float
    profit_factor: float
    average_win: float
    average_loss: float
    max_drawdown: float
    by_error_type: Dict[str, int] = field(default_factory=dict)
    by_direction: Dict[str, Dict] = field(default_factory=dict)
    lessons: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict:
        return {
            "generated_at": self.generated_at,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "gross_pnl": round(self.gross_pnl, 2),
            "net_pnl": round(self.net_pnl, 2),
            "win_rate": round(self.win_rate, 4),
            "profit_factor": round(self.profit_factor, 2),
            "average_win": round(self.average_win, 2),
            "average_loss": round(self.average_loss, 2),
            "max_drawdown": round(self.max_drawdown, 2),
            "by_error_type": self.by_error_type,
            "by_direction": self.by_direction,
            "lessons": self.lessons,
        }


class PerformanceAttributor:
    """Translates experience records into a PerformanceReport."""

    def __init__(self, ledger_ref=None) -> None:
        self._ledger = ledger_ref or ledger

    def _system_records(self, records: Optional[Sequence[ExperienceRecord]],
                        ownership: Optional[str]) -> List[ExperienceRecord]:
        """m8.5 filter: system vs manual ownership, never merged."""
        records = list(records if records is not None else self._ledger.all())
        if ownership is not None:
            return [r for r in records
                    if (r.actual_result or {}).get("origin", "system") == ownership]
        return [r for r in records
                if (r.actual_result or {}).get("origin", "system") == "system"]

    def generate(self, records: Optional[Sequence[ExperienceRecord]] = None,
                 ownership: Optional[str] = None) -> PerformanceReport:
        """Generate a report, optionally restricted to one ownership class.

        M8.5: ``ownership`` isolates accountability - "system" (runtime
        decisions) vs "manual" (operator-entered records). Default (None)
        keeps prior behaviour: only "system" records are attributed.
        """
        records = self._system_records(records, ownership)
        if not records:
            return PerformanceReport(
                generated_at=time.time(), total_trades=0, winning_trades=0,
                losing_trades=0, gross_pnl=0.0, net_pnl=0.0, win_rate=0.0,
                profit_factor=0.0, average_win=0.0, average_loss=0.0,
                max_drawdown=0.0,
            )

        pnls = []
        wins, losses = 0, 0
        gross_wins, gross_losses = 0.0, 0.0
        direction_stats: Dict[str, Dict] = {}
        error_counts: Dict[str, int] = {}

        running_pnl = 0.0
        peak = 0.0
        max_dd = 0.0

        for rec in records:
            result = rec.actual_result or {}
            pnl = result.get("pnl", 0.0)
            pnls.append(pnl)
            running_pnl += pnl
            peak = max(peak, running_pnl)
            max_dd = min(max_dd, running_pnl - peak)

            if pnl > 0:
                wins += 1
                gross_wins += pnl
            elif pnl < 0:
                losses += 1
                gross_losses += abs(pnl)

            err = rec.error_classification.value if rec.error_classification else "unclassified"
            error_counts[err] = error_counts.get(err, 0) + 1

            # Direction split from candidate_id prefix is not available here;
            # store coarse bucket by error type for now.
            bucket = direction_stats.setdefault(err, {"count": 0, "pnl": 0.0})
            bucket["count"] += 1
            bucket["pnl"] += pnl

        total = len(pnls)
        avg_win = gross_wins / wins if wins else 0.0
        avg_loss = gross_losses / losses if losses else 0.0
        profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else 0.0

        return PerformanceReport(
            generated_at=time.time(),
            total_trades=total,
            winning_trades=wins,
            losing_trades=losses,
            gross_pnl=gross_wins,
            net_pnl=sum(pnls),
            win_rate=wins / total,
            profit_factor=profit_factor,
            average_win=avg_win,
            average_loss=avg_loss,
            max_drawdown=max_dd,
            by_error_type=error_counts,
            by_direction=direction_stats,
        )

    def by_strategy(self, records: Optional[Sequence[ExperienceRecord]] = None,
                    ownership: Optional[str] = None) -> List[Dict]:
        """Per-strategy rollup (L1 appendix B): PnL attributed to each strategy.

        Real executions (mt5:*/exec:*) now carry ``metadata["strategy_id"]``
        (E1), so drift and this rollup share one provenance key. Records
        without a strategy stamp roll into ``unattributed`` rather than being
        dropped, keeping totals reconcilable.
        """
        rows = self._system_records(records, ownership)
        groups: Dict[str, List[ExperienceRecord]] = {}
        for rec in rows:
            sid = (rec.metadata or {}).get("strategy_id") or "unattributed"
            groups.setdefault(str(sid), []).append(rec)

        out: List[Dict] = []
        for sid, group in groups.items():
            report = self.generate(group, ownership=ownership).as_dict()
            out.append({
                "strategy_id": sid,
                "total_trades": report["total_trades"],
                "winning_trades": report["winning_trades"],
                "losing_trades": report["losing_trades"],
                "gross_pnl": report["gross_pnl"],
                "net_pnl": report["net_pnl"],
                "win_rate": report["win_rate"],
                "profit_factor": report["profit_factor"],
                "average_win": report["average_win"],
                "average_loss": report["average_loss"],
                "max_drawdown": report["max_drawdown"],
            })
        out.sort(key=lambda row: row["net_pnl"], reverse=True)
        return out


attributor = PerformanceAttributor()
