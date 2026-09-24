"""Analytical-school framework: the common Evidence Contract.

Every school produces the *same* typed artifact (SchoolEvidence) and
exports the same lifecycle (evaluate / learn / eligibility / policy),
so schools stay homogeneous and comparable. Tiers follow the explicit
Source / Confirmation / Gate split:

  SOURCE        - may originate a directional Suggestion (Structure, ICT, Wyckoff)
  CONFIRMATION  - raises or lowers the confidence of a ready Suggestion only
                  (Price Action, Volume/Order Flow); never invents a direction
  GATE          - hard or statistical authority over every Suggestion before
                  the Risk Governor (Macro = hard, Quant = statistical)
  META          - no vote; classifies regime, ranks suggestions, flags conflicts
                  (AI Intelligence)

Lesson field tags (also on each Suggestion.metadata) are the learning keys
each school cares about:
  structure: bos_vs_false_break, per-regime
  ict:       zone_freshness (0/1/2+), sweep_confirmed
  wyckoff:   failure_kind = classification_error | macro_override
  price_action: ab_confirm_lift (A/B vs baseline)
  volume:    data_quality vs per-symbol filter
  macro:     missed_blackout_count
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

from core.contracts import Candle, RegimeSnapshot, TradeDirection


class SchoolTier(str, Enum):
    SOURCE = "source"
    CONFIRMATION = "confirmation"
    GATE = "gate"
    META = "meta"


class VerdictKind(str, Enum):
    PASS = "pass"
    REJECT = "reject"
    REVIEW = "review"      # soft: allow but flag/warn (statistics not yet conclusive)
    DISABLED = "disabled"  # school is off for this symbol/data (e.g. no volume)


class PolicyStatus(str, Enum):
    INIT = "init"              # cold start, no samples yet
    LEARNING = "learning"      # samples present but below confidence threshold
    ACTIVE = "active"          # statistically confident, gate enforced
    SUSPENDED = "suspended"    # live drift outside expected band -> review, not delete
    REVIEW = "review"          # manual re-certification required


class SchoolStatus(str, Enum):
    """Deployment status of a school: principal vs under evaluation.

    APPROVED  - the school's output may drive trade selection (the strategy).
    RESEARCH  - evaluated and logged for observation only; never selected so
                long as an approved source has anything to say, and always
                tagged (meta["research"]=True) when used as a fallback.
    """
    APPROVED = "approved"
    RESEARCH = "research"


@dataclass
class SchoolSignal:
    """A single claim from a school. Direct always found on the chart."""
    name: str
    direction: TradeDirection
    strength: float                    # 0..1 (base, before policy multiplier)
    anchor: str = ""                   # structure anchor id for correlation dedupe
    pattern: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "direction": self.direction.value,
            "strength": round(self.strength, 3),
            "anchor": self.anchor,
            "pattern": self.pattern,
            "meta": self.meta,
        }


@dataclass
class SchoolZone:
    """A price region drawn by a school (entry/objective/support/resistance)."""
    zone_type: str
    top: float
    bottom: float
    role: str = "context"              # entry | objective | invalidation | context
    touches: int = 0                   # times price has already traded the zone
    fresh: bool = True                 # never--- or first-touch only is tradeable
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def mid(self) -> float:
        return (self.top + self.bottom) / 2.0

    def contains(self, price: float) -> bool:
        return self.bottom <= price <= self.top

    def as_dict(self) -> Dict[str, Any]:
        return {
            "zone_type": self.zone_type,
            "top": round(self.top, 5),
            "bottom": round(self.bottom, 5),
            "role": self.role,
            "touches": self.touches,
            "fresh": self.fresh,
            "meta": self.meta,
        }


@dataclass
class SchoolVerdict:
    """Gate/meta outcome attached to a SchoolEvidence."""
    kind: VerdictKind = VerdictKind.PASS
    reason: str = ""
    authority: str = "advisory"        # advisory | hard | statistical
    size_multiplier: float = 1.0       # quant regime-conditioned sizing hint
    meta: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind.value,
            "reason": self.reason,
            "authority": self.authority,
            "size_multiplier": round(self.size_multiplier, 3),
            "meta": self.meta,
        }


@dataclass
class SchoolEvidence:
    """Homogeneous artifact every school returns from evaluate()."""
    school_id: str
    tier: SchoolTier
    symbol: str
    timestamp: float
    bias: TradeDirection = TradeDirection.FLAT
    confidence: float = 0.0
    signals: List[SchoolSignal] = field(default_factory=list)
    zones: List[SchoolZone] = field(default_factory=list)
    suggestions: List["Suggestion"] = field(default_factory=list)   # SOURCE only
    verdict: Optional[SchoolVerdict] = None                          # GATE/META
    data_available: bool = True
    meta: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "school_id": self.school_id,
            "tier": self.tier.value,
            "symbol": self.symbol,
            "timestamp": self.timestamp,
            "bias": self.bias.value,
            "confidence": round(self.confidence, 3),
            "signals": [s.as_dict() for s in self.signals],
            "zones": [z.as_dict() for z in self.zones],
            "suggestions": [s.as_dict() for s in self.suggestions],
            "verdict": self.verdict.as_dict() if self.verdict else None,
            "data_available": self.data_available,
            "meta": self.meta,
        }


@dataclass
class Suggestion:
    """A directional trade idea produced by a SOURCE school."""
    school_id: str
    pattern: str
    direction: TradeDirection
    entry_zone: List[float]            # [low, high]
    stop_loss: float
    take_profit: List[float]
    invalidation: float
    confidence: float                  # 0..1 base from the school
    anchor: str = ""                   # dedupe key across schools
    zones: List[SchoolZone] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "school_id": self.school_id,
            "pattern": self.pattern,
            "direction": self.direction.value,
            "entry_zone": self.entry_zone,
            "stop_loss": round(self.stop_loss, 5),
            "take_profit": [round(t, 5) for t in self.take_profit],
            "invalidation": round(self.invalidation, 5),
            "confidence": round(self.confidence, 3),
            "anchor": self.anchor,
            "meta": self.meta,
        }


@dataclass
class SchoolPolicy:
    """Learned operating policy for one school (or pattern inside a school)."""
    school_id: str
    tier: SchoolTier
    enabled: bool = True
    status: PolicyStatus = PolicyStatus.INIT
    confidence_multiplier: float = 1.0
    expectancy_by_regime: Dict[str, float] = field(default_factory=dict)
    sample_by_regime: Dict[str, int] = field(default_factory=dict)
    winrate_by_regime: Dict[str, float] = field(default_factory=dict)
    last_learned_at: float = 0.0
    note: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "school_id": self.school_id,
            "tier": self.tier.value,
            "enabled": self.enabled,
            "status": self.status.value,
            "confidence_multiplier": round(self.confidence_multiplier, 3),
            "expectancy_by_regime": self.expectancy_by_regime,
            "sample_by_regime": self.sample_by_regime,
            "winrate_by_regime": self.winrate_by_regime,
            "last_learned_at": self.last_learned_at,
            "note": self.note,
        }

    def effective_confidence(self, base: float) -> float:
        """School confidence after the learned multiplier."""
        return max(0.0, min(1.0, base * self.confidence_multiplier))

    def mark_learned(self) -> None:
        self.last_learned_at = time.time()


class School(ABC):
    """Common contract every analytical school implements."""

    school_id: str = ""
    name: str = ""
    tier: SchoolTier = SchoolTier.META
    status: SchoolStatus = SchoolStatus.RESEARCH

    def __init__(self) -> None:
        self.policy = SchoolPolicy(self.school_id, self.tier)

    # -- lifecycle ------------------------------------------------------
    @abstractmethod
    def evaluate(self, candles: Sequence[Candle], symbol: str,
                 regime: Optional[RegimeSnapshot] = None,
                 zones_from_others: Optional[Sequence[SchoolZone]] = None,
                 now: Optional[float] = None) -> SchoolEvidence:
        """Run the school over the candle buffer. Deterministic, never blocks."""

    def eligibility(self, regime: Optional[RegimeSnapshot]) -> bool:
        """Whether this school is allowed to run under the current regime."""
        return self.policy.enabled

    def learn(self, samples: Sequence[Any]) -> SchoolPolicy:
        """Consume outcome-tagged experiences and update the policy."""
        return self.policy

    # -- helpers --------------------------------------------------------
    def _evid(self, symbol: str, now: Optional[float] = None) -> SchoolEvidence:
        return SchoolEvidence(
            school_id=self.school_id, tier=self.tier, symbol=symbol,
            timestamp=now if now is not None else time.time())
