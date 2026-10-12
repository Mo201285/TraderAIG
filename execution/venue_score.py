"""S5 Execution Network: venue scoring between MT5 and CEX.

The venue scorecard answers an institutional question the Execution Truth
plane (spec section 7, row 770) cannot: *which venue is actually executing
well for us?* It is an engine over the same canonical evidence -- the
attributed orders in :mod:`core.state` -- never a new execution authority and
never a second source of truth.

Design rules:

* **Evidence only.** A venue's score is a deterministic function of the
  canonical orders attributed to it (fill ratio, realised slippage, rejection
  rate). Nothing here places an order, changes a setting or grants a
  permission -- the payload is advisory and carries ``is_authorisation: False``.
* **Honest when thin.** A venue with fewer than ``MIN_SAMPLES`` *terminal*
  orders (filled + partial + rejected) is reported ``unproven`` with
  ``score: null`` and ``components: null`` -- the engine never invents a number
  from too little history (the same discipline as rows 774/779).
* **Attribution is explicit.** Orders with no venue are counted as
  ``unattributed`` rather than folded into a rail, so the operator can see how
  much execution is actually attributable before trusting any score.

The scoring model is a pluggable seam (``VenueScoreModel``); the default is a
weights-over-components average, each component named and bounded to [0, 1].
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.contracts import OrderStatus
from core.logging import get_logger


log = get_logger("execution.venue_score")


# Terminal orders (filled + partial + rejected) a venue needs before it is
# scored; below this it is reported ``unproven`` rather than given a number.
MIN_SAMPLES = 3

# The broker rail's canonical venue label (the account registry uses "mt5" as
# the account *type*; the per-server identity lives in ``venue_server``).
MT5_VENUE = "mt5"

DEFAULT_WEIGHTS = {
    "fill_quality": 0.4,
    "slippage_quality": 0.3,
    "reliability": 0.3,
}

METHOD = "default_v1"


@dataclass
class VenueMetrics:
    """Aggregated execution evidence for one venue (canonical orders only)."""

    venue: str
    orders: int = 0
    filled: int = 0
    partial: int = 0
    rejected: int = 0
    cancelled: int = 0
    total_volume: float = 0.0
    _slips: List[float] = field(default_factory=list, repr=False)
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
    def avg_slippage(self) -> Optional[float]:
        return (sum(self._slips) / len(self._slips)) if self._slips else None

    @property
    def avg_commission(self) -> Optional[float]:
        return (sum(self._fees) / len(self._fees)) if self._fees else None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "venue": self.venue,
            "orders": self.orders,
            "filled": self.filled,
            "partial": self.partial,
            "rejected": self.rejected,
            "cancelled": self.cancelled,
            "terminal": self.terminal,
            "fill_ratio": round(self.fill_ratio, 4),
            "reject_rate": round(self.reject_rate, 4),
            "total_volume": round(self.total_volume, 4),
            "avg_slippage": (None if self.avg_slippage is None
                             else round(self.avg_slippage, 6)),
            "avg_commission": (None if self.avg_commission is None
                               else round(self.avg_commission, 6)),
        }


@dataclass
class VenueScore:
    """A venue's score plus the evidence and components behind it."""

    venue: str
    scored: bool
    score: Optional[float]
    tier: str
    samples: int
    components: Optional[Dict[str, float]]
    metrics: Dict[str, Any]
    basis: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "venue": self.venue,
            "scored": self.scored,
            "score": None if self.score is None else round(self.score, 4),
            "tier": self.tier,
            "samples": self.samples,
            "components": self.components,
            "metrics": self.metrics,
            "basis": self.basis,
        }


class VenueScoreModel:
    """Pluggable scoring seam; a model scores one venue's metrics."""

    def score(self, metrics: VenueMetrics,
              min_samples: int = MIN_SAMPLES) -> VenueScore:
        raise NotImplementedError


class DefaultVenueScoreModel(VenueScoreModel):
    """Deterministic weights-over-components score in [0, 1].

    Components (each bounded to [0, 1], higher is better):

    * ``fill_quality`` = filled / terminal -- how often an intent becomes a fill;
    * ``slippage_quality`` = 1 / (1 + |avg slippage|) -- 1.0 at zero slippage;
    * ``reliability`` = 1 - rejections / orders -- how rarely the venue refuses.
    """

    def __init__(self, weights: Optional[Dict[str, float]] = None) -> None:
        self._weights = dict(weights or DEFAULT_WEIGHTS)

    def score(self, metrics: VenueMetrics,
              min_samples: int = MIN_SAMPLES) -> VenueScore:
        terminal = metrics.terminal
        if terminal < min_samples:
            return VenueScore(
                venue=metrics.venue, scored=False, score=None, tier="unproven",
                samples=terminal, components=None, metrics=metrics.as_dict(),
                basis=(f"{terminal} terminal order(s); {min_samples} needed to "
                       f"score -- no number is invented"))
        fill_quality = metrics.fill_ratio
        slippage_quality = 1.0 / (1.0 + abs(metrics.avg_slippage or 0.0))
        reliability = 1.0 - metrics.reject_rate
        components = {
            "fill_quality": round(fill_quality, 4),
            "slippage_quality": round(slippage_quality, 4),
            "reliability": round(reliability, 4),
        }
        score = sum(self._weights[k] * components[k] for k in self._weights)
        score = max(0.0, min(1.0, score))
        tier = "strong" if score >= 0.7 else "fair" if score >= 0.4 else "weak"
        return VenueScore(
            venue=metrics.venue, scored=True, score=score, tier=tier,
            samples=terminal, components=components, metrics=metrics.as_dict(),
            basis=("weighted fill_ratio / |slippage| / rejection over canonical "
                   "orders (method %s)" % METHOD),
        )


class VenueScorecard:
    """Read-only scorecard over the canonical orders' venue attribution."""

    def __init__(self, state_ref=None,
                 model: Optional[VenueScoreModel] = None) -> None:
        self._state = state_ref
        self._model = model or DefaultVenueScoreModel()

    def _state_ref(self):
        if self._state is not None:
            return self._state
        from core.state import state as canonical
        return canonical

    def _configured_venues(self, st) -> Dict[str, str]:
        out = {"mt5": ""}
        try:
            from core.config import settings
            if settings.cex.venue:
                out["cex"] = str(settings.cex.venue)
        except Exception:  # noqa: BLE001
            pass
        return out

    def _collect(self) -> "tuple[Dict[str, VenueMetrics], int, str]":
        st = self._state_ref()
        metrics: Dict[str, VenueMetrics] = {}
        unattributed = 0
        for order in st.orders.values():
            row = order.as_dict()
            venue = str(row.get("venue") or "").strip()
            if not venue:
                unattributed += 1
                continue
            m = metrics.setdefault(venue, VenueMetrics(venue=venue))
            m.orders += 1
            m.total_volume += float(row.get("volume") or 0.0)
            raw = row.get("status")
            status = str(getattr(raw, "value", None) or raw or "")
            if status == OrderStatus.FILLED.value:
                m.filled += 1
                m._slips.append(float(row.get("slippage") or 0.0))
                m._fees.append(float(row.get("commission") or 0.0))
            elif status == OrderStatus.PARTIAL.value:
                m.partial += 1
            elif status == OrderStatus.REJECTED.value:
                m.rejected += 1
            elif status == OrderStatus.CANCELLED.value:
                m.cancelled += 1
        try:
            broker = str(st.account.broker or "")
        except Exception:  # noqa: BLE001
            broker = ""
        return metrics, unattributed, broker

    def scorecard(self) -> Dict[str, Any]:
        st = self._state_ref()
        metrics, unattributed, broker = self._collect()

        # Always surface the two rails (MT5 + the configured CEX venue) even
        # with no evidence, so an unproven rail is visible rather than absent.
        configured = self._configured_venues(st)
        venues = set(metrics) | {"mt5"}
        if configured.get("cex"):
            venues.add(configured["cex"])

        scores = [self._model.score(metrics.get(v) or VenueMetrics(venue=v))
                  for v in sorted(venues)]
        scored = [s for s in scores if s.scored]
        recommended = None
        if scored:
            recommended = max(scored, key=lambda s: (s.score, s.venue)).venue

        return {
            "generated_at": time.time(),
            "read_only": True,
            "is_authorisation": False,
            "trade_authority": "risk/governor.py",
            "method": METHOD,
            "min_samples": MIN_SAMPLES,
            "weights": dict(DEFAULT_WEIGHTS),
            "venues": [s.as_dict() for s in scores],
            "recommended": recommended,
            "recommendation_basis": (
                "highest score among venues with >= min_samples terminal "
                "orders (advisory only)"),
            "configured": {"mt5_rail": True, "cex_venue": configured.get("cex")},
            "account_broker": broker,
            "unattributed_orders": unattributed,
            "note": ("advisory scorecard over canonical order evidence; the "
                     "venue gate and any switch stay the operator's call"),
        }


__all__ = [
    "DEFAULT_WEIGHTS",
    "DefaultVenueScoreModel",
    "METHOD",
    "MIN_SAMPLES",
    "MT5_VENUE",
    "VenueMetrics",
    "VenueScore",
    "VenueScoreModel",
    "VenueScorecard",
]
