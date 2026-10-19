"""Execution Intelligence: per-venue execution truth (Phase C, ENGINEERING MAST
27.9 / 28.12).

The S5 venue scorecard (`execution/venue_score.py`) scores a venue from the
evidence already stamped on the canonical orders -- fill ratio, slippage,
rejection. Two halves of the Phase-C line were still open, and both come from
the same omission:

1. **Per-venue execution-truth reporting.** `GET /execution/truth` (row 770) is
   platform-wide; nothing broke the truth down by venue. An operator could see
   "avg slippage 0.4" for the whole system but not "the MT5 rail fills 0.3 wide
   and Binance fills 0.05 wide".
2. **Real slippage.** 27.9/28.12 are explicit that *internal intent is not
   execution truth*. Today every executor writes ``OrderState.slippage = 0.0``
   and never diffs the intended price (`OrderState.price`, stamped from the
   candidate entry) against the actual fill (`OrderState.filled_price`). So the
   scorecard's slippage component is vacuously 1.0 in production -- a number by
   omission, not by measurement.

This module measures the truth instead: for every terminal order that actually
filled, it compares intent to execution and reports slippage in **price units**
and in **R multiples** (against the order's own stop distance), direction-aware
so adverse slippage is positive for a long (fill above intent) and for a short
(fill below intent). A venue with no measured fills is reported
``measured: False`` with ``slippage: null`` -- never a zero that reads as
"perfect". Nothing here places an order, switches a venue or grants authority;
it is a read-only report, the same discipline as the scorecard it stands beside.

Where two records disagree the durable trade schema is the tie-breaker: the
report reads the in-memory canonical orders (the same source the rest of the
truth plane uses) and states the sample basis, rather than inventing a merge.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.logging import get_logger

from .venue_score import MT5_VENUE

log = get_logger("execution.execution_truth")


def _adverse_slippage(intended: float, filled: float, *, is_long: bool,
                      stop_distance: float) -> Optional[Dict[str, float]]:
    """Signed adverse slippage of one fill, in price and R units.

    Adverse = the fill was worse than intent, so it is *positive* whether the
    order was long (filled above intent, paid more) or short (filled below
    intent, received less). A favourable fill is negative. Returns ``None``
    when intent/fill are unusable.
    """
    if intended is None or filled is None or intended <= 0 or filled <= 0:
        return None
    raw = (filled - intended) if is_long else (intended - filled)
    out = {"price": round(float(raw), 6),
           "bps": round(float(raw / intended) * 10000.0, 4)}
    if stop_distance and stop_distance > 0:
        out["r"] = round(float(raw / stop_distance), 4)
    else:
        out["r"] = None
    return out


@dataclass
class VenueExecutionTruth:
    """One venue's measured execution truth (intent vs actual fill)."""

    venue: str
    orders: int = 0
    filled: int = 0
    partial: int = 0
    rejected: int = 0
    cancelled: int = 0
    _slips_price: List[float] = field(default_factory=list, repr=False)
    _slips_r: List[float] = field(default_factory=list, repr=False)
    _fees: List[float] = field(default_factory=list, repr=False)

    @property
    def terminal(self) -> int:
        return self.filled + self.partial + self.rejected

    @property
    def fill_ratio(self) -> float:
        return (self.filled / self.terminal) if self.terminal else 0.0

    @property
    def reject_rate(self) -> float:
        return (self.rejected / self.orders) if self.orders else 0.0

    @property
    def measured_fills(self) -> int:
        return len(self._slips_price)

    def as_dict(self) -> Dict[str, Any]:
        avg_price = (sum(self._slips_price) / len(self._slips_price)
                     if self._slips_price else None)
        avg_r = (sum(self._slips_r) / len(self._slips_r)
                 if self._slips_r else None)
        worst = max(self._slips_price) if self._slips_price else None
        return {
            "venue": self.venue,
            "orders": self.orders,
            "terminal": self.terminal,
            "filled": self.filled,
            "partial": self.partial,
            "rejected": self.rejected,
            "cancelled": self.cancelled,
            "fill_ratio": round(self.fill_ratio, 4),
            "reject_rate": round(self.reject_rate, 4),
            "measured_fills": self.measured_fills,
            "measured": self.measured_fills > 0,
            "avg_slippage_price": (None if avg_price is None
                                   else round(avg_price, 6)),
            "avg_slippage_r": (None if avg_r is None else round(avg_r, 4)),
            "worst_slippage_price": (None if worst is None
                                     else round(worst, 6)),
            "total_fees": round(sum(self._fees), 6) if self._fees else None,
        }


class ExecutionTruthReport:
    """Read-only, per-venue execution truth over the canonical orders.

    Mirrors `VenueScorecard`'s construction so the two can sit side by side
    (state_ref injection for tests; the module singleton by default).
    """

    def __init__(self, state_ref: Any = None) -> None:
        self._state_ref = state_ref

    def _state(self) -> Any:
        if self._state_ref is not None:
            return self._state_ref
        from core.state import state
        return state

    def _configured_venues(self, st: Any) -> List[str]:
        venues = [MT5_VENUE]
        try:
            from core.config import settings
            cex = getattr(getattr(settings, "cex", None), "venue", "") or ""
            if cex and cex not in venues:
                venues.append(cex)
        except Exception:  # noqa: BLE001
            pass
        return venues

    @staticmethod
    def _is_long(direction: Any) -> bool:
        return str(getattr(direction, "value", direction)).lower() in (
            "long", "buy")

    def _collect(self) -> Dict[str, Any]:
        st = self._state()
        venues: Dict[str, VenueExecutionTruth] = {
            v: VenueExecutionTruth(venue=v) for v in self._configured_venues(st)
        }
        unattributed = 0
        orders: Dict[str, Any] = getattr(st, "orders", {}) or {}
        for order in orders.values():
            row = order.as_dict() if hasattr(order, "as_dict") else dict(order)
            venue = str(row.get("venue") or "")
            if not venue:
                unattributed += 1
                continue
            bucket = venues.setdefault(venue, VenueExecutionTruth(venue=venue))
            bucket.orders += 1
            status = row.get("status")
            sval = str(getattr(status, "value", status)).lower()
            if sval == "filled":
                bucket.filled += 1
                slip = _adverse_slippage(
                    row.get("price"), row.get("filled_price"),
                    is_long=self._is_long(row.get("direction")),
                    stop_distance=self._stop_distance(row))
                if slip is not None:
                    bucket._slips_price.append(slip["price"])
                    if slip.get("r") is not None:
                        bucket._slips_r.append(slip["r"])
                fee = row.get("commission")
                if fee:
                    bucket._fees.append(float(fee))
            elif sval == "partial":
                bucket.partial += 1
            elif sval == "rejected":
                bucket.rejected += 1
            elif sval == "cancelled":
                bucket.cancelled += 1
        return {"venues": venues, "unattributed": unattributed}

    @staticmethod
    def _stop_distance(row: Dict[str, Any]) -> float:
        price = row.get("price")
        sl = row.get("sl")
        if price is None or sl is None:
            return 0.0
        return abs(float(price) - float(sl))

    def report(self) -> Dict[str, Any]:
        collected = self._collect()
        venues: List[Dict[str, Any]] = [
            v.as_dict() for v in collected["venues"].values()]
        measured = [v for v in collected["venues"].values()
                    if v.measured_fills > 0]
        platform = None
        if measured:
            all_price = [s for v in collected["venues"].values()
                         if v.measured_fills > 0 for s in v._slips_price]
            platform = {
                "measured_fills": len(all_price),
                "avg_slippage_price": round(sum(all_price) / len(all_price), 6),
            }
        return {
            "generated_at": time.time(),
            "read_only": True,
            "is_authorisation": False,
            "trade_authority": "risk/governor.py",
            "measured_slippage": bool(measured),
            "venues": venues,
            "platform": platform,
            "unattributed_orders": collected["unattributed"],
            "note": ("" if measured else
                     "no order carries a measured intent-vs-fill slippage yet "
                     "-- the plan is not the execution; until a fill differs "
                     "from intent this reads 'not measured', not 'zero'"),
        }


execution_truth_report = ExecutionTruthReport()
