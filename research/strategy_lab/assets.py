"""RMI-05 Strategy Asset Layer.

S2's ratifying row asks for "asset metadata + valuation hooks on the existing
registry" (PROJECT_MAP row 629). This module is exactly that and nothing more:

* **Asset metadata** -- a strategy registered by the lab (or the RMI-04 bridge)
  gains durable, operator-authored metadata (owner, title, description, tags,
  arbitrary key/values) plus the read-only research provenance the bridge
  already recorded (package id, cited evidence, ``backed_trust``). The metadata
  journal is keyed by ``strategy_id`` and is a *hook over* the existing
  ``StrategyRegistry`` -- the frozen lab contracts are not modified, so the
  promotion ladder and its persistence stay byte-for-byte what the lab tests
  pinned.
* **Valuation hooks** -- :class:`StrategyValuationModel` is the pluggable seam;
  :class:`DefaultValuationModel` is a deterministic, fully-explainable model
  that values a strategy **only from evidence that exists** (its
  ``ValidationReport`` and its live ``live_performance``) and refuses to invent
  a number: a strategy with neither is reported ``unproven`` with a stated
  basis, never a made-up score.

The layer is read-mostly and never promotes, never trades and never grants a
permission: it is the asset view *over* the governed registry, and every
outgoing payload carries ``is_authorisation: False`` /
``trade_authority: "risk/governor.py"``.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from research.evidence_plane import IS_AUTHORISATION, TRADE_AUTHORITY

from .contracts import (
    PromotionStage,
    StrategyFamily,
    StrategyRegistryEntry,
)
from .registry import StrategyRegistry
from .research_bridge import ResearchBindingStore

# Stage multiplies the evidence score: a strategy that has not climbed the
# governed ladder yet cannot be valued as if it had. Quarantined is worth zero.
_STAGE_WEIGHT = {
    PromotionStage.RESEARCH: 0.25,
    PromotionStage.CANDIDATE: 0.50,
    PromotionStage.VALIDATED: 0.70,
    PromotionStage.PAPER: 0.85,
    PromotionStage.PRODUCTION: 1.00,
    PromotionStage.QUARANTINED: 0.00,
}

_TIER_FLOORS = (("institutional", 0.75), ("proven", 0.50), ("emerging", 0.20))


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class StrategyAssetError(RuntimeError):
    """An asset operation was refused (fail-closed)."""


# ---------------------------------------------------------------------------
# Valuation
# ---------------------------------------------------------------------------


@dataclass
class AssetValuation:
    """An explainable, bounded valuation of a strategy asset.

    ``score`` is always in ``[0, 1]`` and ``components`` names every
    contribution so the number is never a black box. When there is no evidence
    at all the valuation is honest about it: ``tier == "unproven"``,
    ``score == 0.0`` and a ``basis`` that says why.
    """

    strategy_id: str
    score: float = 0.0
    tier: str = "unproven"
    components: Dict[str, float] = field(default_factory=dict)
    basis: str = ""
    has_validation: bool = False
    has_live: bool = False

    def as_dict(self) -> Dict:
        return {
            "strategy_id": self.strategy_id,
            "score": round(float(self.score), 4),
            "tier": self.tier,
            "components": {k: round(float(v), 4)
                           for k, v in self.components.items()},
            "basis": self.basis,
            "has_validation": self.has_validation,
            "has_live": self.has_live,
            "is_authorisation": IS_AUTHORISATION,
            "trade_authority": TRADE_AUTHORITY,
        }


class StrategyValuationModel:
    """The valuation hook: implement ``value(entry, metadata) -> AssetValuation``."""

    def value(self, entry: StrategyRegistryEntry,
              metadata: Dict) -> AssetValuation:  # pragma: no cover - interface
        raise NotImplementedError


class DefaultValuationModel(StrategyValuationModel):
    """Deterministic valuation from real evidence only (validation + live).

    The model blends the validation report's own quality signals (did it pass,
    how many trades, expected value, profit factor, Monte-Carlo survival) with
    any live realized performance the Experience Ledger has fed in, then scales
    by the strategy's governed stage. Every term is bounded and named; a
    strategy with no report and no live record is ``unproven`` (score 0.0).
    """

    #: full-credit reference points, all auditable constants
    SAMPLE_FULL = 100.0
    EV_FULL = 0.5
    PF_FULL = 2.0
    LIVE_R_FULL = 5.0

    def value(self, entry: StrategyRegistryEntry,
              metadata: Dict) -> AssetValuation:
        report = entry.validation
        live = entry.live_performance or {}
        has_validation = report is not None
        has_live = bool(live)

        if not has_validation and not has_live:
            return AssetValuation(
                strategy_id=entry.strategy_id, score=0.0, tier="unproven",
                components={}, has_validation=False, has_live=False,
                basis=("no validation report and no live performance - there "
                       "is nothing to value yet"))

        components: Dict[str, float] = {}

        validation_quality = 0.0
        if has_validation:
            pass_q = 1.0 if report.passed else 0.0
            sample_q = _clamp01(report.samples / self.SAMPLE_FULL)
            ev_q = _clamp01(report.expected_value / self.EV_FULL)
            pf_q = _clamp01((report.profit_factor - 1.0) / (self.PF_FULL - 1.0))
            surv_q = _clamp01(report.monte_carlo_survival)
            validation_quality = (
                0.30 * pass_q + 0.20 * sample_q + 0.20 * ev_q
                + 0.15 * pf_q + 0.15 * surv_q)
            components.update({
                "validation_pass": pass_q,
                "sample_quality": sample_q,
                "expected_value_quality": ev_q,
                "profit_factor_quality": pf_q,
                "survival_quality": surv_q,
            })

        live_quality = 0.0
        if has_live:
            realized = float(live.get("realized_r")
                             or live.get("net_pnl") or 0.0)
            live_quality = _clamp01(realized / self.LIVE_R_FULL)
            components["live_realized_quality"] = live_quality

        if has_live and has_validation:
            raw = 0.70 * validation_quality + 0.30 * live_quality
        elif has_live:
            raw = live_quality
        else:
            raw = validation_quality

        stage_weight = _STAGE_WEIGHT.get(entry.stage, 0.0)
        components["stage_weight"] = stage_weight
        score = _clamp01(raw * stage_weight)

        tier = "unproven"
        for name, floor in _TIER_FLOORS:
            if score >= floor:
                tier = name
                break

        basis_bits = []
        if has_validation:
            basis_bits.append(
                f"validation {'passed' if report.passed else 'failed'} "
                f"({report.samples} trades)")
        if has_live:
            basis_bits.append("live performance recorded")
        basis_bits.append(f"stage {entry.stage.value} (x{stage_weight:g})")
        return AssetValuation(
            strategy_id=entry.strategy_id, score=score, tier=tier,
            components=components, has_validation=has_validation,
            has_live=has_live, basis="; ".join(basis_bits))


# ---------------------------------------------------------------------------
# Metadata journal (a hook over the registry)
# ---------------------------------------------------------------------------


class StrategyAssetMetadataStore:
    """Durable operator-authored asset metadata, keyed by strategy_id."""

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = str(path) if path else ""
        self._lock = threading.Lock()
        self._entries: Dict[str, Dict] = {}
        self.load()

    def record(self, strategy_id: str, metadata: Dict) -> Dict:
        sid = str(strategy_id or "").strip()
        if not sid:
            raise StrategyAssetError("asset metadata needs a strategy_id")
        clean = {str(k): v for k, v in dict(metadata or {}).items()}
        with self._lock:
            existing = self._entries.get(sid, {"strategy_id": sid})
            merged = {**existing, **clean, "strategy_id": sid,
                      "updated_at": _now()}
            merged.setdefault("created_at", _now())
            self._entries[sid] = merged
            self._save()
            return dict(merged)

    def get(self, strategy_id: str) -> Dict:
        with self._lock:
            entry = self._entries.get(str(strategy_id or ""))
            return dict(entry) if entry else {}

    def entries(self) -> List[Dict]:
        with self._lock:
            return [dict(e) for e in self._entries.values()]

    def _save(self) -> None:
        if not self.path:
            return
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(list(self._entries.values()), fh,
                      indent=2, ensure_ascii=False)

    def load(self) -> int:
        if not self.path or not Path(self.path).exists():
            return 0
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return 0
        self._entries = {d["strategy_id"]: d for d in data
                         if d.get("strategy_id")}
        return len(self._entries)


# ---------------------------------------------------------------------------
# The asset view
# ---------------------------------------------------------------------------


@dataclass
class StrategyAsset:
    """A first-class strategy asset: registry entry + metadata + provenance + value."""

    strategy_id: str
    family: StrategyFamily
    asset: str
    stage: PromotionStage
    metadata: Dict = field(default_factory=dict)
    provenance: Dict = field(default_factory=dict)
    validation: Optional[Dict] = None
    live_performance: Dict = field(default_factory=dict)
    valuation: Optional[AssetValuation] = None
    history: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict:
        return {
            "strategy_id": self.strategy_id,
            "family": self.family.value,
            "asset": self.asset,
            "stage": self.stage.value,
            "metadata": dict(self.metadata),
            "provenance": dict(self.provenance),
            "validation": self.validation,
            "live_performance": dict(self.live_performance),
            "valuation": self.valuation.as_dict() if self.valuation else None,
            "history": list(self.history),
            "is_authorisation": IS_AUTHORISATION,
            "trade_authority": TRADE_AUTHORITY,
        }


class StrategyAssetLayer:
    """Read-mostly asset view over the governed ``StrategyRegistry``.

    Metadata is attached **only** to a strategy that already exists in the
    registry (fail-closed: an unregistered id is refused rather than
    materialised). Valuation always goes through the injected model hook.
    """

    def __init__(self, registry: StrategyRegistry,
                 bindings: Optional[ResearchBindingStore] = None,
                 metadata: Optional[StrategyAssetMetadataStore] = None,
                 model: Optional[StrategyValuationModel] = None) -> None:
        self._registry = registry
        self._bindings = bindings
        self._metadata = metadata or StrategyAssetMetadataStore()
        self._model = model or DefaultValuationModel()

    def metadata_for(self, strategy_id: str) -> Dict:
        return self._metadata.get(strategy_id)

    def attach_metadata(self, strategy_id: str, metadata: Dict) -> Dict:
        if self._registry.get(strategy_id) is None:
            raise StrategyAssetError(
                f"strategy {strategy_id} is not in the lab registry; asset "
                f"metadata may only be attached to a registered strategy")
        return self._metadata.record(strategy_id, metadata)

    def value(self, entry: StrategyRegistryEntry) -> AssetValuation:
        return self._model.value(entry, self._metadata.get(entry.strategy_id))

    def asset(self, strategy_id: str) -> Optional[StrategyAsset]:
        entry = self._registry.get(strategy_id)
        if entry is None:
            return None
        provenance = (self._bindings.get(strategy_id) if self._bindings
                      else None) or {}
        return StrategyAsset(
            strategy_id=entry.strategy_id,
            family=entry.family,
            asset=entry.asset,
            stage=entry.stage,
            metadata=self._metadata.get(entry.strategy_id),
            provenance=provenance,
            validation=(entry.validation.as_dict()
                        if entry.validation is not None else None),
            live_performance=dict(entry.live_performance or {}),
            valuation=self.value(entry),
            history=list(entry.history))

    def assets(self) -> List[StrategyAsset]:
        out: List[StrategyAsset] = []
        for entry in self._registry.list():
            asset = self.asset(entry.strategy_id)
            if asset is not None:
                out.append(asset)
        return out
