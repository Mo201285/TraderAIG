"""S4 Portfolio Intelligence: the cross-strategy Capital Allocation Engine.

S4's ratifying row asks for "cross-strategy correlation + allocation engine over
the existing aggregation" (PROJECT_MAP row 631). The correlation half already
exists (:mod:`portfolio.correlation`); this module adds the allocation half, and
it is deliberately an *engine over* the existing pieces, not a new authority:

* it reads the same realised-PnL series the correlation matrix uses and the
  same durable caps :class:`portfolio.investment.CapitalAllocationBoard` holds;
* it produces an advisory **AllocationProposal** -- target fractions of equity
  per strategy -- and never places an order, never mutates a cap and never
  grants a permission;
* the method is deterministic and fully explained: inverse-volatility
  (risk parity) weights, a correlation penalty for strategies that double up,
  then a water-filling clamp against each strategy's cap so the institutional
  ceiling is never exceeded;
* it fails closed to an honest ``unavailable`` when there is not enough evidence
  to size anything -- it never fabricates a weight.

The engine is read-only: the durable effect of this module is nothing. Acting on
a proposal stays the operator's call through the governed allocation routes.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.logging import get_logger
from portfolio.correlation import (
    MIN_SAMPLES,
    _pnl_series,
    strategy_correlation,
)
from portfolio.investment import CapitalAllocationBoard


log = get_logger("portfolio.allocation")

# A concentrated pair (from portfolio.correlation) divides the adjusted weight
# of each participant; deterministic and bounded, so a duplicated strategy can
# never dominate a diversified book.
_CONCENTRATION_PENALTY = 0.5
METHODS = ("risk_parity", "equal_weight")


def _stdev(series: List[float]) -> float:
    n = len(series)
    if n < 2:
        return 0.0
    mean = sum(series) / n
    return math.sqrt(sum((x - mean) ** 2 for x in series) / n)


@dataclass
class AllocationProposal:
    method: str
    status: str                       # proposed | unavailable
    universe: List[str]
    weights: Dict[str, float]
    cash: float
    detail: List[Dict[str, Any]]
    insufficient_data: List[str]
    reason: str = ""
    generated_at: float = field(default_factory=time.time)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "method": self.method,
            "status": self.status,
            "universe": list(self.universe),
            "weights": {k: round(v, 4) for k, v in self.weights.items()},
            "cash": round(self.cash, 4),
            "detail": self.detail,
            "insufficient_data": sorted(self.insufficient_data),
            "reason": self.reason,
            "generated_at": self.generated_at,
            "read_only": True,
            "is_authorisation": False,
            "trade_authority": "risk/governor.py",
        }


class PortfolioAllocationEngine:
    """Deterministic risk-parity allocation over the existing aggregation."""

    def __init__(self, board: Optional[CapitalAllocationBoard] = None,
                 ledger_ref=None) -> None:
        self._board = board or CapitalAllocationBoard()
        self._ledger = ledger_ref

    def _ledger_ref(self):
        if self._ledger is not None:
            return self._ledger
        try:
            from learning.experience import ledger as ledger_singleton
            return ledger_singleton
        except Exception:  # noqa: BLE001
            return None

    def propose(self, *, method: str = "risk_parity",
                universe: Optional[List[str]] = None) -> AllocationProposal:
        if method not in METHODS:
            raise ValueError(
                f"unknown allocation method {method!r}; expected one of "
                f"{', '.join(METHODS)}")

        ledger_ref = self._ledger_ref()
        records = []
        if ledger_ref is not None:
            try:
                records = list(ledger_ref.all())
            except Exception:  # noqa: BLE001
                records = []
        series = _pnl_series(records)

        names = sorted(series)
        if universe is not None:
            wanted = {str(s) for s in universe}
            names = [n for n in names if n in wanted]

        if not names:
            return AllocationProposal(
                method=method, status="unavailable", universe=[],
                weights={}, cash=1.0, detail=[], insufficient_data=[],
                reason="no strategy has any realised PnL history; nothing to "
                       "size (no weight is invented)")

        # Eligible = enough samples AND non-degenerate volatility.
        eligible: List[str] = []
        insufficient: List[str] = []
        vol: Dict[str, float] = {}
        for sid in names:
            v = _stdev(series[sid]["series"])
            vol[sid] = v
            if series[sid]["trades"] < MIN_SAMPLES or v <= 0.0:
                insufficient.append(sid)
            else:
                eligible.append(sid)

        if not eligible:
            return AllocationProposal(
                method=method, status="unavailable", universe=names,
                weights={}, cash=1.0,
                detail=[self._detail_row(sid, vol, None, 0.0, 0.0, 0.0)
                        for sid in names],
                insufficient_data=insufficient,
                reason=("no strategy has enough non-degenerate samples to "
                        "risk-weight; every weight stays unallocated rather "
                        "than fabricated"))

        # Base weights.
        if method == "equal_weight":
            base = {sid: 1.0 / len(eligible) for sid in eligible}
        else:  # risk_parity: weight inversely proportional to volatility
            inv = {sid: 1.0 / vol[sid] for sid in eligible}
            total = sum(inv.values())
            base = {sid: inv[sid] / total for sid in eligible}

        # Correlation penalty: strategies in a concentrated pair are damped.
        penalty = {sid: 0 for sid in eligible}
        corr = strategy_correlation(ledger_ref=ledger_ref or _EmptyLedger())
        for pair in corr.get("pairs", []):
            if pair.get("concentrated"):
                for sid in (pair["a"], pair["b"]):
                    if sid in penalty:
                        penalty[sid] += 1
        adjusted = {sid: base[sid] / (1.0 + _CONCENTRATION_PENALTY * penalty[sid])
                    for sid in eligible}
        adj_total = sum(adjusted.values())
        if adj_total <= 0.0:
            adjusted = dict(base)
            adj_total = sum(adjusted.values())

        weights, cash = self._water_fill(adjusted, adj_total)
        detail = [self._detail_row(sid, vol, base.get(sid), penalty.get(sid, 0),
                                   weights.get(sid, 0.0),
                                   self._board.cap_for(sid))
                  for sid in eligible]
        return AllocationProposal(
            method=method, status="proposed", universe=names,
            weights=weights, cash=cash, detail=detail,
            insufficient_data=insufficient,
            reason=("advisory risk-parity weights clamped to each strategy's "
                    "cap; unallocated remainder is held as cash"))

    def _water_fill(self, weights: Dict[str, float], total: float
                    ) -> "tuple[Dict[str, float], float]":
        """Distribute 1.0 proportional to ``weights`` under per-strategy caps."""
        free = set(weights)
        remaining = 1.0
        alloc: Dict[str, float] = {}
        while free and remaining > 1e-9:
            bucket = sum(weights[sid] for sid in free)
            if bucket <= 0.0:
                break
            clamped = False
            for sid in sorted(free):
                share = remaining * (weights[sid] / bucket)
                cap = self._board.cap_for(sid)
                if share > cap + 1e-9:
                    alloc[sid] = cap
                    remaining -= cap
                    free.discard(sid)
                    clamped = True
            if not clamped:
                for sid in free:
                    alloc[sid] = remaining * (weights[sid] / bucket)
                remaining = 0.0
                break
        return alloc, max(0.0, remaining)

    @staticmethod
    def _detail_row(sid: str, vol: Dict[str, float],
                    base: Optional[float], penalty: int,
                    weight: float, cap: float) -> Dict[str, Any]:
        return {
            "strategy_id": sid,
            "volatility": round(vol.get(sid, 0.0), 6),
            "base_weight": None if base is None else round(base, 4),
            "correlation_penalty": penalty,
            "cap": round(cap, 4),
            "weight": round(weight, 4),
        }


class _EmptyLedger:
    """A ledger shim for the no-ledger path (returns no records)."""

    def all(self):  # noqa: D401 - simple stand-in
        return []


__all__ = [
    "AllocationProposal",
    "METHODS",
    "PortfolioAllocationEngine",
]
