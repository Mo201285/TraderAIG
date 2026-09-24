"""Validated Prior Provider (PROJECT_MAP M8.1/M8.2).

Bridges the Strategy Lab and the runtime decision layer *without* fusing
them: this module only *reads* the persisted strategy registry and lab
observations and publishes the conditional edge as a read-only prior. It
never mutates the registry, never opens orders, and never changes what the
Risk Governor enforces.

A "prior" is a validated strategy lift usable by the decision layer:

  - strategy_id, stage (only VALIDATED/PAPER/PRODUCTION are eligible),
  - global expected value / win rate / sample count,
  - conditional buckets by regime and session (so the matrix/decision layer
    can read the edge for the *current* regime/session/asset),
  - oos_ev, monte_carlo survival and the pass state of the validation gates.

Prior eligibility is a hard rule: a strategy whose registry stage is below
VALIDATED (or that has no passing validation) is never exposed as a prior.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from .contracts import (
    PromotionStage,
    StrategyFamily,
    StrategyRegistryEntry,
    ValidationReport,
)


# Registry stages whose validated edge may be consumed by the runtime.
# PAPER and PRODUCTION are the promotion-ladder targets (UPDATE.md M8);
# VALIDATED qualifies only for the matrix/decision read (never live size).
ELIGIBLE_STAGES = {
    PromotionStage.VALIDATED,
    PromotionStage.PAPER,
    PromotionStage.PRODUCTION,
}

LIVE_STAGES = {PromotionStage.PAPER, PromotionStage.PRODUCTION}


@dataclass(frozen=True)
class PriorEdge:
    """A read-only conditional-edge prior for one strategy."""

    strategy_id: str
    family: str
    asset: str
    stage: str
    expected_value: float
    win_rate: float
    samples: int
    oos_ev: Optional[float]
    survival: float
    passed: bool
    regime_edge: Dict[str, float] = field(default_factory=dict)
    session_edge: Dict[str, float] = field(default_factory=dict)
    regimes_allowed: List[str] = field(default_factory=list)
    sessions_allowed: List[str] = field(default_factory=list)

    @property
    def is_live_eligible(self) -> bool:
        """True when the strategy may size live orders (PAPER/PRODUCTION)."""
        try:
            return PromotionStage(self.stage) in LIVE_STAGES
        except ValueError:
            return False

    def edge_for(self, regime: Optional[str] = None,
                 session: Optional[str] = None) -> float:
        """Conditional expected value for a regime/session bucket, else the
        global EV. Filters *allowed* buckets first: if the strategy explicitly
        restricts regimes/sessions and the active bucket is not allowed, the
        edge is treated as unavailable (0.0) so the caller can abstain."""
        if self.regimes_allowed and regime and regime not in self.regimes_allowed:
            return 0.0
        if self.sessions_allowed and session and session not in self.sessions_allowed:
            return 0.0
        if regime and regime in self.regime_edge:
            return self.regime_edge[regime]
        if session and session in self.session_edge:
            return self.session_edge[session]
        return self.expected_value

    def as_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "family": self.family,
            "asset": self.asset,
            "stage": self.stage,
            "expected_value": round(self.expected_value, 4),
            "win_rate": round(self.win_rate, 4),
            "samples": self.samples,
            "oos_ev": None if self.oos_ev is None else round(self.oos_ev, 4),
            "survival": round(self.survival, 4),
            "passed": self.passed,
            "live_eligible": self.is_live_eligible,
            "regime_edge": {k: round(v, 4) for k, v in self.regime_edge.items()},
            "session_edge": {k: round(v, 4) for k, v in self.session_edge.items()},
            "regimes_allowed": list(self.regimes_allowed),
            "sessions_allowed": list(self.sessions_allowed),
        }


def registry_entry_to_prior(entry: StrategyRegistryEntry) -> Optional[PriorEdge]:
    """Project one registry entry into a prior, or None when not eligible."""
    if entry.stage not in ELIGIBLE_STAGES:
        return None
    v = entry.validation
    if v is None or not v.passed:
        return None
    return PriorEdge(
        strategy_id=entry.strategy_id,
        family=entry.family.value,
        asset=entry.asset,
        stage=entry.stage.value,
        expected_value=v.expected_value,
        win_rate=v.win_rate,
        samples=v.samples,
        oos_ev=v.oos_ev,
        survival=v.monte_carlo_survival,
        passed=v.passed,
        regime_edge=v.regime_concentration,
        session_edge=v.session_concentration,
    )


class PriorProvider:
    """Read-only view over the strategy registry exposing validated priors.

    ``load()`` is idempotent; the provider never persists anything. A registry
    path that does not exist simply means "no validated priors yet" (the
    runtime then proceeds on live evidence only, as today).
    """

    def __init__(self, registry_path: Optional[str] = None,
                 strategies: Optional[Sequence[PriorEdge]] = None) -> None:
        self.registry_path = registry_path
        self._priors: List[PriorEdge] = list(strategies or [])
        self._loaded = bool(strategies)
        self._stamp_cache = None

    @staticmethod
    def _stamp(path: str):
        """(mtime_ns, size) of the registry file, or None when absent."""
        try:
            st = os.stat(path)
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def load(self, path: Optional[str] = None) -> int:
        """Load the registry file (best-effort). Returns the number of
        *eligible* validated priors found.

        Reads are mtime-cached: a ``load()`` call on an unchanged file is a
        cheap stat and no-op (idempotent); once the registry file changes on
        disk (a promote/quarantine landed through governance), the same
        process automatically re-reads it. An injected ``strategies`` provider
        stays frozen (test/static case).
        """
        if self._loaded and path is None:
            stamp = self._stamp(self.registry_path or "")
            if stamp is None:
                return len(self._priors)
            if stamp == self._stamp_cache:
                return len(self._priors)
        self.registry_path = path or self.registry_path
        self._priors = []
        self._loaded = False
        self._stamp_cache = None
        if not self.registry_path or not os.path.exists(self.registry_path):
            return 0
        try:
            with open(self.registry_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return 0
        for d in data:
            try:
                validation = None
                if d.get("validation"):
                    validation = ValidationReport(**d["validation"])
                entry = StrategyRegistryEntry(
                    strategy_id=d["strategy_id"],
                    variant_hash=d["variant_hash"],
                    family=StrategyFamily(d["family"]),
                    asset=d["asset"],
                    stage=PromotionStage(d["stage"]),
                    validation=validation,
                    history=list(d.get("history", [])),
                )
            except (KeyError, ValueError, TypeError):
                continue
            prior = registry_entry_to_prior(entry)
            if prior is not None:
                self._priors.append(prior)
        self._loaded = True
        self._stamp_cache = self._stamp(self.registry_path)
        return len(self._priors)

    def all(self) -> List[PriorEdge]:
        return list(self._priors)

    def by_asset(self, asset: str) -> List[PriorEdge]:
        key = asset.upper()
        return [p for p in self._priors if p.asset.upper() == key]

    def by_family(self, family: str) -> List[PriorEdge]:
        return [p for p in self._priors if p.family == family]

    def lookup(self, asset: Optional[str] = None, family: Optional[str] = None,
               regime: Optional[str] = None, session: Optional[str] = None,
               live_only: bool = False) -> List[PriorEdge]:
        """Best-matched validated priors, ordered by conditional EV desc."""
        rows = list(self._priors)
        if live_only:
            rows = [p for p in rows if p.is_live_eligible]
        if asset:
            rows = [p for p in rows if p.asset.upper() == asset.upper()]
        if family:
            rows = [p for p in rows if p.family == family]

        def sort_key(p: PriorEdge):
            return p.edge_for(regime, session)

        return sorted(rows, key=sort_key, reverse=True)

    def best_for(self, asset: Optional[str] = None, family: Optional[str] = None,
                 regime: Optional[str] = None, session: Optional[str] = None,
                 live_only: bool = False,
                 min_edge: float = 0.0) -> Optional[PriorEdge]:
        """The single best validated prior matching the conditions, or None.

        ``min_edge`` is a hard floor: a prior whose conditional (or global)
        EV is below the floor is not worth blending into the decision.
        """
        rows = self.lookup(asset=asset, family=family, regime=regime,
                           session=session, live_only=live_only)
        for p in rows:
            if p.edge_for(regime, session) >= min_edge:
                return p
        return None


def registry_path_for(data_dir: Optional[str] = None) -> str:
    base = data_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "data")
    return os.path.join(base, "registry.json")


class _RegistryStageLens:
    """mtime-cached view of the persisted promotion stage per strategy_id.

    Read-only and cheap: an unchanged registry costs one os.stat per call. The
    Risk Governor (and the MT5 local gate) use this to resolve the *current*
    registry truth at veto time so a quarantine that lands mid-cycle vetoes
    the very next candidate instead of waiting for recorded-stage staleness.
    """

    def __init__(self, registry_path: str) -> None:
        self._path = registry_path
        self._stamp_cache = None
        self._stages: Dict[str, str] = {}

    def _stamp(self):
        try:
            st = os.stat(self._path)
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def stages(self) -> Dict[str, str]:
        stamp = self._stamp()
        if stamp is not None and stamp == self._stamp_cache:
            return self._stages
        self._stages = {}
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            for d in data:
                try:
                    self._stages[str(d["strategy_id"])] = \
                        PromotionStage(d["stage"]).value
                except (KeyError, ValueError, TypeError):
                    continue
        except (OSError, ValueError):
            pass
        self._stamp_cache = stamp
        return self._stages


_lens_current: Optional[_RegistryStageLens] = None
_lens_path: Optional[str] = None


def registry_stage_resolver(data_dir: Optional[str] = None):
    """resolver(candidate) -> current registry stage for its strategy.

    Returns None when the candidate carries no strategy_id or the strategy is
    unknown to the persisted registry (the governor then falls back to the
    stage recorded at decision time). A strategy that was *quarantined* on
    disk resolves to ``quarantined`` so the hard gate vetoes immediately.
    """
    global _lens_current, _lens_path
    path = registry_path_for(data_dir)
    if _lens_current is None or _lens_path != path:
        _lens_current = _RegistryStageLens(path)
        _lens_path = path
    lens = _lens_current

    def resolve(candidate: Any) -> Optional[str]:
        sid = getattr(candidate, "strategy_id", None)
        if not sid:
            return None
        return lens.stages().get(str(sid))

    return resolve


_current: Optional[PriorProvider] = None


def default_provider(data_dir: Optional[str] = None) -> PriorProvider:
    """Shared provider over the lab's persisted registry (read-only).

    A provider is reused while its registry path is unchanged, but ``load()``
    runs on every call so a governance transition written to ``registry.json``
    mid-process is picked up immediately (the load itself is mtime-cached, so
    an unchanged file is just an os.stat no-op). A different ``data_dir``
    re-points the shared provider instead of silently reusing the old file.
    """
    global _current
    path = registry_path_for(data_dir)
    if _current is None or _current.registry_path != path:
        _current = PriorProvider(registry_path=path)
    _current.load()
    return _current
